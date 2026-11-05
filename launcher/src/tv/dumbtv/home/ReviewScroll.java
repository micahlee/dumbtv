package tv.dumbtv.home;

/** Clock-driven agenda motion, independent of Android for deterministic checks. */
final class ReviewScroll {
    private double offset;
    private int direction = 1;
    private long previous, holdUntil;

    void reset(long now, int current) {
        offset = current; direction = 1; previous = now; holdUntil = now + 5000;
    }

    void manual(long now, int current, int maximum) {
        offset = Math.max(0, Math.min(maximum, current));
        if (offset <= 0) direction = 1;
        else if (offset >= maximum) direction = -1;
        previous = now; holdUntil = now + 10000;
    }

    int step(long now, int current, int maximum, double pixelsPerSecond) {
        if (maximum <= 0) { offset = 0; previous = now; return 0; }
        if (now < holdUntil) {
            // Follow remote-driven scrolling during the pause instead of undoing it.
            offset = Math.max(0, Math.min(maximum, current)); previous = now;
            return (int) Math.round(offset);
        }
        long elapsed = Math.max(0, Math.min(100, now - Math.max(previous, holdUntil)));
        previous = now;
        offset = Math.max(0, Math.min(maximum, offset));
        if (elapsed == 0) return (int) Math.round(offset);
        offset += direction * pixelsPerSecond * elapsed / 1000.0;
        if (offset >= maximum) {
            offset = maximum; direction = -1; holdUntil = now + 5000;
        } else if (offset <= 0) {
            offset = 0; direction = 1; holdUntil = now + 5000;
        }
        return (int) Math.round(offset);
    }
}
