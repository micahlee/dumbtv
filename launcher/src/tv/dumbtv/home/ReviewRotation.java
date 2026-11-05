package tv.dumbtv.home;

/** Foreground-only review/photos/video/photos loop; late callbacks never catch up. */
final class ReviewRotation {
    static final int REVIEW = 0, PHOTOS_BEFORE = 1, VIDEO = 2, PHOTOS_AFTER = 3;
    private final long reviewMillis, photoMillis;
    private final boolean weather;
    private long due;
    private int phase;
    private boolean active;
    ReviewRotation(long reviewMillis, long photoMillis, boolean weather) {
        this.reviewMillis = reviewMillis; this.photoMillis = photoMillis; this.weather = weather;
    }
    void resume(long now) { active = true; interact(now); }
    void pause() { active = false; phase = REVIEW; }
    void interact(long now) { phase = REVIEW; due = now + reviewMillis; }
    int phase() { return phase; }
    int tick(long now, boolean photos, boolean video) {
        if (active && now >= due) advance(now, photos, video);
        return phase;
    }
    void videoFinished(long now, boolean photos) {
        if (active && phase == VIDEO) advance(now, photos, false);
    }
    private void advance(long now, boolean photos, boolean video) {
        for (int i = 0; i < 4; i++) {
            phase = (phase + 1) % 4;
            if (phase == REVIEW || (phase == VIDEO && weather && video)
                    || ((phase == PHOTOS_BEFORE || phase == PHOTOS_AFTER) && photos
                        && (weather || phase == PHOTOS_BEFORE))) break;
        }
        due = now + (phase == REVIEW ? reviewMillis : phase == VIDEO ? 615000 : photoMillis);
    }
    long delay(long now) { return Math.max(1, due - now); }
}
