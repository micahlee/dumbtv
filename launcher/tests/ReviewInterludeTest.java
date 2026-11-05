package tv.dumbtv.home;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.Calendar;
import java.util.GregorianCalendar;
public final class ReviewInterludeTest {
    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    public static void main(String[] args) {
        ReviewInterlude cycle = new ReviewInterlude(180000, 45000);
        cycle.resume(0);
        check(!cycle.tick(179999, true), "read the dashboard first");
        check(cycle.tick(180000, true), "photo interlude starts at three minutes");
        check(cycle.tick(224999, true), "photos remain for45 seconds");
        check(!cycle.tick(225000, true), "automatic return to review");
        check(cycle.delay(225000)==180000, "full review interval after returning");
        cycle.interact(230000);
        check(!cycle.tick(409999, true), "remote input postpones the next interlude");
        check(cycle.tick(410000, true), "photos resume after fresh reading interval");
        cycle.interact(410001);
        check(!cycle.tick(410001, true), "remote returns immediately and resets deadline");
        cycle.pause(); check(!cycle.tick(999999, true), "no photo work behind another app");
        cycle.resume(1000000);
        check(!cycle.tick(1179999, true), "resume starts with the dashboard");
        check(!cycle.tick(1180000, false), "missing photos never leave a blank interlude");
        check(cycle.delay(1180000)==180000, "missing cache does not tight retry");
        check(cycle.tick(5000000, true), "late callback begins one fresh photo period");
        check(cycle.delay(5000000)==45000, "late callback never catches up old periods");
        MemoryDates.Photo a=MemoryDates.parse("2008-11-05_0000000000000001_c.jpg");
        MemoryDates.Photo b=MemoryDates.parse("2010-11-05_0000000000000002_c.jpg");
        MemoryDates.Photo c=MemoryDates.parse("2020-11-05_0000000000000003_c.jpg");
        check(a!=null && a.collage, "collage filenames carry the type");
        check(MemoryDates.parse("2008-11-05_0000000000000001.jpg")!=null, "legacy cache compatibility");
        Calendar today=new GregorianCalendar(2026,10,5);
        check(MemoryDates.choose(Arrays.asList(a,b,c),today).size()==3, "mixed-year pages remain on this day");
        MemoryDeck deck=new MemoryDeck(); Set<String> seen=new HashSet<>();
        for(int i=0;i<3;i++) {
            List<MemoryDates.Photo> next=deck.order(Arrays.asList(a,b,c));
            check(seen.add(next.get(0).file), "no repeated page before the deck is exhausted");
            deck.shown(next.get(0).file);
        }
        check(!deck.order(Arrays.asList(a,b,c)).isEmpty(), "next deck remains available");
        deck=new MemoryDeck(); deck.skip(a.file);
        check(deck.order(Arrays.asList(a,b)).get(0)==b, "unreadable pages do not strand readable pages");
        System.out.println("ReviewInterludeTest passed: timed return, remote reset, lifecycle, missing cache and unique page deck");
    }
}
