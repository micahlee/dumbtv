package tv.dumbtv.home;
public final class PhotoTransitionTest {
    public static void main(String[] args) {
        if (PhotoTransition.progress(-1) != 0 || PhotoTransition.progress(0) != 0
                || PhotoTransition.progress(900) != 1 || PhotoTransition.progress(10000) != 1)
            throw new AssertionError("bounded endpoints");
        float previous = 0;
        for (int t = 0; t <= 900; t++) {
            float next = PhotoTransition.progress(t);
            if (next < previous) throw new AssertionError("no reversal"); previous = next;
        }
        if (PhotoTransition.progress(100) >= 100f/900 || PhotoTransition.progress(800) <= 800f/900)
            throw new AssertionError("gentle start and settle");
        System.out.println("PhotoTransitionTest passed");
    }
}
