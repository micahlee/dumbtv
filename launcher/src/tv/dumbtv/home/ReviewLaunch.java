package tv.dumbtv.home;

/** One bounded foreground request, never a scheduled/background launch. */
final class ReviewLaunch {
    static final String ACTION = "tv.dumbtv.home.OPEN_DAILY_REVIEW";
    static final String DEADLINE = "review.execute_before";
    private long deadline;

    void offer(long until, long now) {
        deadline = until > now && until - now <= 30000 ? until : 0;
    }
    void cancel() { deadline = 0; }
    boolean pending(long now) {
        if (now >= deadline) cancel();
        return deadline > now;
    }
    boolean take(long now, boolean enabled, boolean resumed, boolean focused) {
        if (!enabled || now >= deadline) { cancel(); return false; }
        if (!resumed || !focused) return false;
        cancel(); return true;
    }
}
