package tv.dumbtv.home;
public final class ReviewRotationTest {
    private static void check(boolean b, String message) { if (!b) throw new AssertionError(message); }
    public static void main(String[] args) {
        ReviewRotation r = new ReviewRotation(180000, 45000, true); r.resume(0);
        check(r.tick(179999, true, true)==0,"read review first");
        check(r.tick(180000, true, true)==1,"first photos");
        check(r.tick(225000, true, true)==2,"forecast follows first photos");
        check(r.tick(300000, true, true)==2,"full clip not a photo-length timeout");
        r.videoFinished(384000,true); check(r.phase()==3,"second photos after completion");
        check(r.tick(428999,true,true)==3,"second photos full period");
        check(r.tick(429000,true,true)==0,"loop to review");
        check(r.delay(429000)==180000,"fresh full review interval");
        r.interact(500000);check(r.phase()==0,"Back/input returns review");
        r.tick(680000,true,true);r.tick(725000,true,true);r.pause();r.videoFinished(726000,true);
        check(r.tick(99999999,true,true)==0,"no playback cycle behind another app");
        r.resume(1000000);check(r.tick(1180000,false,true)==2,"no photos still offers weather");
        r.videoFinished(1181000,false);check(r.phase()==0,"no empty second slideshow");
        r.resume(2000000);r.tick(2180000,true,false);
        check(r.tick(2225000,true,false)==3,"stale/missing weather skips safely to second photos");
        check(r.tick(2270000,true,false)==0,"missing weather returns review");
        r.resume(3000000);check(r.tick(99999999,false,false)==0,"all unavailable retains review");
        check(r.delay(99999999)==180000,"no retry spin");
        r.resume(0);r.tick(180000,true,true);r.tick(225000,true,true);
        check(r.tick(840000,true,true)==3,"wedged video has bounded watchdog");
        ReviewRotation legacy = new ReviewRotation(180000,45000,false);legacy.resume(0);
        check(legacy.tick(180000,true,true)==1 && legacy.tick(225000,true,true)==0,"opt-out preserves original cycle");
        long now=2000000000000L;
        check(ForecastClip.valid("forecast_"+repeat('a',64)+".mp4","WYFF","Forecast",now-1000,now+10000,now,159,1000),"current manifest");
        check(!ForecastClip.valid("../video.mp4","WYFF","Forecast",now-1000,now+10000,now,159,1000),"no path traversal");
        check(!ForecastClip.valid("forecast_"+repeat('a',64)+".mp4","WYFF","Forecast",now-1000,now-1,now,159,1000),"expired clip");
        check(!ForecastClip.valid("forecast_"+repeat('a',64)+".mp4","OTHER","Forecast",now-1000,now+10000,now,159,1000),"fixed source");
        check(!ForecastClip.valid("forecast_"+repeat('a',64)+".mp4","WYFF","Forecast",now-1000,now+10000,now,999,1000),"duration bound");
        check(!ForecastClip.valid("forecast_"+repeat('a',64)+".mp4","WYFF","Forecast",now-1000,now+10000,now,159,ForecastClip.MAX_BYTES+1),"size bound");
        System.out.println("ReviewRotationTest passed");
    }
    private static String repeat(char c,int n) { StringBuilder b=new StringBuilder();while(n-->0)b.append(c);return b.toString(); }
}
