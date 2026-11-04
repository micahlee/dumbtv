# Public Microsoft SDK credential adapter for personal OneDrive. Its normal
# TokenRequestContext reuses the personal-account cache; the higher-level Graph
# connect path initializes separate token profiles and clears opaque-token scope
# fields. Tokens stay in memory and in Microsoft's encrypted Keychain cache.
$null = Get-MgContext
$core = [AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.GetName().Name -eq 'Microsoft.Graph.Authentication.Core' }
$moduleRoot = (Get-Module Microsoft.Graph.Authentication).ModuleBase
$references = @($core.Location, "$moduleRoot/Dependencies/Core/Azure.Core.dll", "$moduleRoot/Dependencies/System.ClientModel.dll") + @(Get-ChildItem -LiteralPath "$PSHOME/ref" -Filter *.dll | Select-Object -ExpandProperty FullName)
$dll = Join-Path ([IO.Path]::GetTempPath()) ('tv-graph-' + [guid]::NewGuid() + '.dll')
try {
    # Load the public interface adapter into the SDK's isolated AssemblyLoadContext.
    # CS1701 is its net6 reference unified with PowerShell's later runtime.
    Add-Type -OutputAssembly $dll -CompilerOptions /nowarn:1701 -ReferencedAssemblies $references -TypeDefinition @'
using System;
using System.Threading;
using System.Threading.Tasks;
using Azure.Core;
using Microsoft.Graph.PowerShell.Authentication;
public sealed class MemoryGraphOutput : IPSGraphOutputWriter {
 public Action<string> WriteObject {get;set;}
 public Action<string> WriteDebug {get;set;} = text => {};
 public Action<string> WriteWarning {get;set;} = text => {};
 public Action<Exception,string,int,object> WriteError {get;set;} = (e,s,i,o) => {};
 public Action<object,string> WriteInformation {get;set;} = (o,s) => {};
 public Action<string> WriteVerbose {get;set;} = text => {};
 public MemoryGraphOutput(bool interactive) {
  WriteObject = text => {
   if (!interactive) throw new UnauthorizedAccessException("OneDrive sign-in required");
   Console.WriteLine(text);
  };
 }
 public static async Task<AccessToken> GetToken(IAuthContext context, CancellationToken cancel) {
  var credential = await Microsoft.Graph.PowerShell.Authentication.Core.Utilities.AuthenticationHelpers.GetTokenCredentialAsync(context, cancel);
  return await credential.GetTokenAsync(new TokenRequestContext(context.Scopes), cancel);
 }
}
'@
    $loader = [System.Runtime.Loader.AssemblyLoadContext]::GetLoadContext($core)
    $extension = $loader.LoadFromAssemblyPath($dll)
} finally { if (Test-Path -LiteralPath $dll) { Remove-Item -LiteralPath $dll } }
$writerType = $extension.GetType('MemoryGraphOutput')
$session = $core.GetType('Microsoft.Graph.PowerShell.Authentication.GraphSession').GetProperty('Instance').GetValue($null)
$session.Environment = Get-MgEnvironment -Name Global
$context = [Microsoft.Graph.PowerShell.Authentication.AuthContext]::new()
$context.TenantId = 'consumers'
$context.Scopes = @('Files.Read')
$context.ContextScope = 'CurrentUser'
$context.AuthType = 'Delegated'
$context.TokenCredentialType = 'DeviceCode'
$script:tokenExpiry = [DateTimeOffset]::MinValue
function Update-GraphToken([bool]$interactive = $false) {
    # Never allow a scheduled cache miss/refresh to produce an interactive prompt.
    $session.OutputWriter = [Activator]::CreateInstance($writerType, @($interactive))
    $cancel = [Threading.CancellationTokenSource]::new($(if ($interactive) { 900000 } else { 30000 }))
    try {
        $task = $writerType.GetMethod('GetToken').Invoke($null, @($context, $cancel.Token))
        $token = $task.GetAwaiter().GetResult()
        if ([string]$context.ContextScope -ne 'CurrentUser') { throw 'Secure persistence required' }
        $secure = ConvertTo-SecureString $token.Token -AsPlainText -Force
        Connect-MgGraph -AccessToken $secure -NoWelcome -ClientTimeout 60
        $script:tokenExpiry = $token.ExpiresOn
    } finally { $cancel.Dispose() }
}
