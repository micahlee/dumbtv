# Read-only JSON-lines transport. Microsoft owns sign-in, refresh and Keychain storage.
param([switch]$SignIn)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Import-Module Microsoft.Graph.Authentication -RequiredVersion 2.41.2
try {
    . (Join-Path $PSScriptRoot 'graph-auth.ps1')
    Update-GraphToken -interactive ([bool]$SignIn)
    $drive = Invoke-MgGraphRequest -Method GET -Uri 'https://graph.microsoft.com/v1.0/me/drive?$select=id,driveType' -OutputType Hashtable
    if ($drive.driveType -ne 'personal' -or !$drive.id) { throw 'Personal OneDrive required' }
    if ($SignIn) { @{signedIn=$true; driveType=$drive.driveType} | ConvertTo-Json -Compress; exit 0 }
    @{ready=$true; drive=$drive.id} | ConvertTo-Json -Compress
} catch {
    # Exceptions may include account information or authentication URLs.
    @{error='OneDrive sign-in or secure login-session cache required'} | ConvertTo-Json -Compress
    exit 1
}
while ($null -ne ($line = [Console]::ReadLine())) {
    try {
        $request = $line | ConvertFrom-Json
        $uri = [Uri]$request.url
        if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'graph.microsoft.com' -or
            $uri.Port -ne 443 -or $uri.UserInfo -or !$uri.AbsolutePath.StartsWith('/v1.0/')) {
            throw 'Invalid Graph URL'
        }
        if ($script:tokenExpiry -lt [DateTimeOffset]::UtcNow.AddMinutes(2)) { Update-GraphToken }
        $data = Invoke-MgGraphRequest -Method GET -Uri $uri.AbsoluteUri -OutputType Hashtable
        @{data=$data} | ConvertTo-Json -Depth 30 -Compress
    } catch {
        $status = 0
        if ($_.Exception.Response.StatusCode) { $status = [int]$_.Exception.Response.StatusCode }
        @{error='OneDrive request failed'; status=$status} | ConvertTo-Json -Compress
    }
}
