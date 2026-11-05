package tv.dumbtv.home;

/** Foreground-only dashboard/photo cycle. A late timer never catches up with missed phases. */
final class ReviewInterlude {
    final long reviewMillis, photoMillis;
    private long due;
    private boolean active, photos;

    ReviewInterlude(long reviewMillis, long photoMillis) {
        this.reviewMillis = reviewMillis; this.photoMillis = photoMillis;
    }
    void resume(long now) { active = true; interact(now); }
    void pause() { active = false; photos = false; }
    void interact(long now) { photos = false; due = now + reviewMillis; }
    boolean tick(long now, boolean available) {
        if (!active) return false;
        if (now >= due) {
            photos = !photos && available;
            due = now + (photos ? photoMillis : reviewMillis);
        }
        return photos;
    }
    long delay(long now) { return Math.max(1, due - now); }
}
