package tv.dumbtv.home;

import android.content.Context;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;
import android.widget.ScrollView;

/** Slow overflow-only agenda sweep; callbacks exist only while the review is visible. */
final class AgendaScrollView extends ScrollView implements Runnable {
    private final ReviewScroll motion = new ReviewScroll();
    private boolean active;

    AgendaScrollView(Context context) { super(context); }

    void setActive(boolean value) {
        removeCallbacks(this); active = value;
        if (active) {
            motion.reset(SystemClock.uptimeMillis(), getScrollY());
            post(this);
        }
    }

    private int maximum() {
        return getChildCount() == 0 ? 0 : Math.max(0,
                getChildAt(0).getBottom() + getPaddingBottom() - getHeight());
    }

    void manualInteraction() {
        motion.manual(SystemClock.uptimeMillis(), getScrollY(), maximum());
    }

    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        manualInteraction(); return super.dispatchTouchEvent(event);
    }

    @Override public void run() {
        if (!active || !isAttachedToWindow() || getWindowVisibility() != View.VISIBLE) return;
        int maximum = maximum();
        if (maximum <= 0) return;
        int next = motion.step(SystemClock.uptimeMillis(), getScrollY(), maximum,
                14.0 * getResources().getDisplayMetrics().density);
        if (next != getScrollY()) scrollTo(0, next);
        postDelayed(this, 50);
    }

    @Override protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
        super.onLayout(changed, left, top, right, bottom);
        removeCallbacks(this); if (active) post(this);
    }

    @Override protected void onDetachedFromWindow() {
        removeCallbacks(this); super.onDetachedFromWindow();
    }

    @Override protected void onWindowVisibilityChanged(int visibility) {
        super.onWindowVisibilityChanged(visibility);
        removeCallbacks(this); if (active && visibility == View.VISIBLE) post(this);
    }
}
