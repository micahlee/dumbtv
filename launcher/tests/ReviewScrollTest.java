package tv.dumbtv.home;

public final class ReviewScrollTest {
    private static void equal(int actual, int expected, String message) {
        if (actual != expected) throw new AssertionError(message + ": " + actual + " != " + expected);
    }
    public static void main(String[] args) {
        ReviewScroll scroll = new ReviewScroll();
        scroll.reset(0, 0);
        equal(scroll.step(10000, 0, 0, 20), 0, "short day stays still");
        scroll.reset(0, 0);
        equal(scroll.step(4900, 0, 10, 20), 0, "initial reading pause");
        int position = 0;
        for (long time = 5000; time <= 5500; time += 50)
            position = scroll.step(time, position, 10, 20);
        equal(position, 10, "overflow reaches the final row");
        equal(scroll.step(10400, position, 10, 20), 10, "bottom reading pause");
        equal(scroll.step(10550, 10, 10, 20), 9, "reverse slowly after bottom pause");
        for (long time = 10600; time <= 11000; time += 50)
            position = scroll.step(time, position, 10, 20);
        equal(position, 0, "returns to the first row");
        equal(scroll.step(15900, 0, 10, 20), 0, "top reading pause");
        scroll.manual(16000, 4, 100);
        equal(scroll.step(16100, 25, 100, 20), 25, "does not undo manual motion");
        equal(scroll.step(25900, 40, 100, 20), 40, "remote pause tracks current position");
        equal(scroll.step(26050, 40, 100, 20), 41, "resumes from manual position");
        equal(scroll.step(999999, 41, 100, 20), 43, "late frame never jumps a page");
        scroll.reset(1000000, 43);
        equal(scroll.step(1004900, 43, 100, 20), 43, "resume gives another reading pause");
        scroll.manual(1005000, 100, 100);
        equal(scroll.step(1015050, 100, 100, 20), 99, "manual bottom resumes upward");
        equal(scroll.step(1015100, 99, 0, 20), 0, "shortened content clamps safely");
        System.out.println("ReviewScrollTest passed: overflow, end pauses, reverse, manual control and lifecycle reset");
    }
}
