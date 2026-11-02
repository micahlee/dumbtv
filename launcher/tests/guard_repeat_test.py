"""Exercise the real Guard event handler with minimal Android boundary stubs.
No TV actions and no APK installation. The overlay rendering is not modeled.
"""
import argparse, os, pathlib, shutil, subprocess, tempfile
root=pathlib.Path(__file__).resolve().parents[2]
jdk=pathlib.Path(os.environ['JAVA_HOME'])/'bin' if os.environ.get('JAVA_HOME') else pathlib.Path(shutil.which('javac')).parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', help='Also verify this git revision reproduces the regression')
args=parser.parse_args()
stubs={
'android/content/ComponentName.java':'package android.content; public class ComponentName { public final String cls; public ComponentName(String p,String c){cls=c;} }',
'android/content/pm/PackageManager.java':'''package android.content.pm; public class PackageManager { public static class NameNotFoundException extends Exception {} public Object getActivityInfo(android.content.ComponentName c,int flags) throws NameNotFoundException { if(c.cls.endsWith("Activity"))return new Object(); throw new NameNotFoundException(); } }''',
'android/util/Log.java':'package android.util; public class Log { public static int i(String tag,String message){return 0;} }',
'android/content/Context.java':'''package android.content; public class Context { public static final String ALARM_SERVICE="alarm",WINDOW_SERVICE="window"; public Object getSystemService(String s){return android.app.AlarmManager.instance;} public android.content.pm.PackageManager getPackageManager(){return new android.content.pm.PackageManager();} public String getPackageName(){return "tv.dumbtv.home";} public void startActivity(Intent i){} public void registerReceiver(BroadcastReceiver r,IntentFilter f){} public void unregisterReceiver(BroadcastReceiver r){} }''',
'android/accessibilityservice/AccessibilityService.java':'''package android.accessibilityservice; public abstract class AccessibilityService extends android.content.Context { protected void onServiceConnected(){} public void onDestroy(){} public abstract void onAccessibilityEvent(android.view.accessibility.AccessibilityEvent e); public abstract void onInterrupt(); }''',
'android/content/Intent.java':'''package android.content; public class Intent { public static final String ACTION_MAIN="main",CATEGORY_HOME="home",ACTION_SCREEN_ON="screen"; public static final int FLAG_ACTIVITY_NEW_TASK=1,FLAG_ACTIVITY_RESET_TASK_IF_NEEDED=2; public Intent(String s){} public Intent addCategory(String s){return this;} public Intent setClass(Context c,Class<?> k){return this;} public Intent addFlags(int f){return this;} public Intent setPackage(String p){return this;} }''',
'android/content/ActivityNotFoundException.java':'package android.content; public class ActivityNotFoundException extends RuntimeException {}',
'android/content/BroadcastReceiver.java':'package android.content; public abstract class BroadcastReceiver { public abstract void onReceive(Context c,Intent i); }',
'android/content/IntentFilter.java':'package android.content; public class IntentFilter { public IntentFilter(String s){} }',
'android/app/ActivityOptions.java':'package android.app; public class ActivityOptions { public static ActivityOptions makeCustomAnimation(android.content.Context c,int a,int b){return new ActivityOptions();} public Object toBundle(){return null;} }',
'android/app/AlarmManager.java':'''package android.app; public class AlarmManager { public static final AlarmManager instance=new AlarmManager(); public static final int ELAPSED_REALTIME=1; public int launches; public void setExact(int t,long when,PendingIntent i){launches++;} public void cancel(PendingIntent p){} }''',
'android/app/PendingIntent.java':'package android.app; public class PendingIntent { public static final int FLAG_UPDATE_CURRENT=1; public static PendingIntent getActivity(android.content.Context c,int id,android.content.Intent i,int flags,Object b){return new PendingIntent();} }',
'android/graphics/PixelFormat.java':'package android.graphics; public class PixelFormat { public static final int OPAQUE=1; }',
'android/os/Build.java':'package android.os; public class Build { public static class VERSION { public static final int SDK_INT=28; } }',
'android/os/Looper.java':'package android.os; public class Looper { public static Looper getMainLooper(){return null;} }',
'android/os/Handler.java':'''package android.os; public class Handler {
 private static final java.util.Map<Runnable,Long> tasks=new java.util.HashMap<>();
 public Handler(Looper l){} public void removeCallbacks(Runnable r){tasks.remove(r);}
 public void postDelayed(Runnable r,long t){tasks.put(r,SystemClock.now+t);}
 public static void dispatch(long now){SystemClock.now=now; for(java.util.Map.Entry<Runnable,Long> e:new java.util.HashMap<>(tasks).entrySet()){if(e.getValue()<=now){tasks.remove(e.getKey());e.getKey().run();}}}
 }''',
'android/os/SystemClock.java':'package android.os; public class SystemClock { public static long now=10000; public static long uptimeMillis(){return now;} public static long elapsedRealtime(){return now;} }',
'android/view/View.java':'''package android.view; public class View { public static final int GONE=8,VISIBLE=0; public View(android.content.Context c){} public void setVisibility(int v){} public int getVisibility(){return GONE;} public ViewTreeObserver getViewTreeObserver(){return new ViewTreeObserver();} public void setBackgroundColor(int c){} }''',
'android/view/ViewTreeObserver.java':'package android.view; public class ViewTreeObserver { public interface OnPreDrawListener { boolean onPreDraw(); } public void addOnPreDrawListener(OnPreDrawListener l){} public void removeOnPreDrawListener(OnPreDrawListener l){} }',
'android/view/WindowManager.java':'''package android.view; public class WindowManager { public static class LayoutParams { public static final int MATCH_PARENT=-1,TYPE_ACCESSIBILITY_OVERLAY=1,FLAG_NOT_FOCUSABLE=2,FLAG_NOT_TOUCHABLE=4,FLAG_LAYOUT_IN_SCREEN=8; public int windowAnimations; public LayoutParams(int a,int b,int c,int d,int e){} } public void addView(View v,LayoutParams p){} public void removeView(View v){} }''',
'android/view/accessibility/AccessibilityEvent.java':'''package android.view.accessibility; public class AccessibilityEvent { public static final int TYPE_WINDOW_STATE_CHANGED=32; private String p,c; public AccessibilityEvent(String p,String c){this.p=p;this.c=c;} public long getEventTime(){return android.os.SystemClock.now;} public int getWindowId(){return 1;} public int getEventType(){return TYPE_WINDOW_STATE_CHANGED;} public CharSequence getPackageName(){return p;} public CharSequence getClassName(){return c;} }''',
 'tv/dumbtv/home/Config.java':'package tv.dumbtv.home; class Config { final java.io.File dir=new java.io.File("/no-debug-home-file"); static Config get(android.content.Context c){return new Config();} int background(){return 0;} }',
 'tv/dumbtv/home/Keeper.java':'package tv.dumbtv.home; class Keeper { static void pause(){} }',
 'tv/dumbtv/home/Home.java':'package tv.dumbtv.home; class Home { public boolean hasWindowFocus(){return true;} }',
 'tv/dumbtv/home/GuardRepeatTest.java':'''package tv.dumbtv.home;
import android.app.AlarmManager; import android.os.SystemClock; import android.view.accessibility.AccessibilityEvent;
public class GuardRepeatTest {
 static final String AMAZON="com.amazon.tv.launcher", HOME="com.amazon.tv.launcher.ui.HomeActivity_vNext";
 static void event(Guard g,String p,String c,long t){SystemClock.now=t;g.onAccessibilityEvent(new AccessibilityEvent(p,c));}
 static void count(int n,String why){if(AlarmManager.instance.launches!=n)throw new AssertionError(why+": expected "+n+", got "+AlarmManager.instance.launches);}
 public static void main(String[] args){
 Guard g=new Guard();
 event(g,AMAZON,HOME,10000); count(1,"first HOME redirects");
 event(g,AMAZON,HOME,10100); count(1,"duplicate event stays throttled");
 event(g,"tv.dumbtv.home","tv.dumbtv.home.Home",10200);
 event(g,AMAZON,HOME,10300); count(2,"second HOME after chooser redirects inside one second");
 event(g,AMAZON,HOME,10400); count(2,"repeat of second event stays throttled");
 event(g,"com.espn.gtv","StartupActivity",10500);
 event(g,AMAZON,HOME,10600); count(3,"quick app-to-HOME redirects");
 event(g,AMAZON,"com.amazon.tv.launcher.ui.MainSettingsActivity",10700); count(3,"Settings left alone");
 Guard.pause(); event(g,AMAZON,HOME,10800);count(3,"intentional Amazon home pause respected");
 event(g,"tv.dumbtv.home","tv.dumbtv.home.Home",10900);
 event(g,AMAZON,HOME,11000);count(4,"leaving intentional Amazon view resumes takeover");
 event(g,AMAZON,HOME,11050); count(4,"second HOME while first return is pending is coalesced");
 Guard.arrived(g); // Even an already-canceled alarm must recover through its queued retry.
 android.os.Handler.dispatch(12000); count(5,"suppressed HOME retried after throttle expires");
 event(g,AMAZON,HOME,12100); event(g,"com.espn.gtv","StartupActivity",12200);
 android.os.Handler.dispatch(13000); count(5,"leaving for an app cancels delayed retry");
 event(g,AMAZON,HOME,14000); count(6,"new visit redirects");
 event(g,AMAZON,HOME,14100); event(g,AMAZON,"com.amazon.tv.launcher.ui.MainSettingsActivity",14200);
 android.os.Handler.dispatch(15000); count(6,"retry does not leave Settings");
 event(g,AMAZON,HOME,16000); count(7,"later visit redirects");
 event(g,AMAZON,HOME,16100); Guard.pause();
 android.os.Handler.dispatch(17000); count(7,"retry respects explicit pause");
 event(g,"tv.dumbtv.home","tv.dumbtv.home.Home",17100);
 event(g,AMAZON,HOME,18000); count(8,"next request redirects");
 event(g,AMAZON,HOME,18100);
 event(g,"tv.dumbtv.home","android.view.View",18110);
 event(g,"tv.dumbtv.home","tv.dumbtv.home.Home",18120);
 android.os.Handler.dispatch(19000); count(9,"own overlay and late Home event must not cancel return");
 event(g,AMAZON,HOME,20000); count(10,"new request redirects");
 event(g,AMAZON,HOME,20100);
 event(g,AMAZON,"android.widget.FrameLayout",20150);
 android.os.Handler.dispatch(21000); count(11,"Amazon widget event must not cancel return");
 event(g,AMAZON,HOME,22000); count(12,"another request redirects");
 event(g,AMAZON,HOME,22100);
 event(g,"tv.dumbtv.home","tv.dumbtv.home.Options",22150);
 android.os.Handler.dispatch(23000); count(12,"Options cancels return");
 System.out.println("GuardRepeatTest passed: captured overlay/Home/widget races and deliberate navigation");
 }
}'''
}
patched=(root/'launcher/src/tv/dumbtv/home/Guard.java').read_text()
cases=[]
if args.baseline:
 original=subprocess.check_output(['git','show',args.baseline+':launcher/src/tv/dumbtv/home/Guard.java'],cwd=root,text=True)
 cases.append(('original',original))
cases.append(('patched',patched))
for label,source in cases:
 with tempfile.TemporaryDirectory(prefix='guard-repeat-') as temp:
  d=pathlib.Path(temp)
  for name,text in {**stubs,'tv/dumbtv/home/Guard.java':source}.items():
   p=d/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
  subprocess.run([str(jdk/'javac'),'-d',str(d/'classes')]+[str(p) for p in d.rglob('*.java')],check=True)
  r=subprocess.run([str(jdk/'java'),'-cp',str(d/'classes'),'tv.dumbtv.home.GuardRepeatTest'],capture_output=True,text=True)
  print(label+': '+r.stdout+r.stderr,flush=True)
  if label=='original': assert r.returncode!=0 and ('second HOME after chooser' in r.stderr or 'suppressed HOME retried' in r.stderr or 'own overlay' in r.stderr)
  else: assert r.returncode==0
