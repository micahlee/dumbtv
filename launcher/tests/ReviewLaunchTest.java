package tv.dumbtv.home;
public final class ReviewLaunchTest {
    private static void check(boolean value,String why) { if(!value)throw new AssertionError(why); }
    public static void main(String[] args) {
        ReviewLaunch launch=new ReviewLaunch();long now=1793879000000L;
        check(!launch.pending(now),"ordinary Home has no review effect");
        launch.offer(now+30000,now);
        check(!launch.take(now,true,false,true),"background Home cannot launch");
        check(!launch.take(now,true,true,false),"unfocused Home cannot launch");
        check(launch.take(now+1,true,true,true),"ready foreground Home consumes the request");
        check(!launch.take(now+2,true,true,true),"request is used once");
        launch.offer(now+30000,now);launch.cancel();
        check(!launch.take(now+1,true,true,true),"leaving Home cancels late launch");
        launch.offer(now+1000,now);
        check(!launch.take(now+1000,true,true,true),"deadline boundary expires");
        launch.offer(now+1000,now);check(!launch.pending(now+1000),"expired queued request is discarded");
        check(!launch.take(now+500,true,true,true),"discarded request cannot revive after clock correction");
        launch.offer(now+30001,now);
        check(!launch.take(now,true,true,true),"unbounded deadline is rejected");
        launch.offer(now-1,now);
        check(!launch.take(now,true,true,true),"expired request is rejected");
        launch.offer(now+1000,now);
        check(!launch.take(now,false,true,true),"disabled review cannot launch");
        check(!launch.take(now+1,true,true,true),"disabled request does not revive later");
        System.out.println("ReviewLaunchTest passed: foreground, focus, opt-in, expiry, one-use and cancellation");
    }
}
