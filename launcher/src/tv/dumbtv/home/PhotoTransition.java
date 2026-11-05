package tv.dumbtv.home;

/** A short page dissolve, independent of system-wide window/animator settings. */
final class PhotoTransition {
    static final long DURATION_MS = 900;
    static float progress(long elapsed) {
        float t = Math.max(0f, Math.min(1f, elapsed / (float) DURATION_MS));
        return t * t * (3f - 2f * t);
    }
}
