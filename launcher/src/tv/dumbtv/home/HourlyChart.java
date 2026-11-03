package tv.dumbtv.home;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.text.TextPaint;
import android.text.TextUtils;
import android.view.KeyEvent;
import android.view.View;
import android.view.accessibility.AccessibilityEvent;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/** One static native chart for the remaining day; Left/Right inspects every hour. */
final class HourlyChart extends View {
    private static final int TEXT = 0xFFF2F5FC, MUTED = 0xFFAFBED4, BLUE = 0xFF79BFFF;
    private final ReviewWeather.Series series;
    private final TimeZone zone;
    private final Paint ink = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final TextPaint text = new TextPaint(Paint.ANTI_ALIAS_FLAG);
    private int selected;

    HourlyChart(Context context, ReviewWeather.Series series, TimeZone zone) {
        super(context); this.series = series; this.zone = zone;
        text.setTypeface(Ui.MEDIUM); ink.setStrokeCap(Paint.Cap.ROUND);
        setFocusable(!series.hours.isEmpty()); updateDescription();
    }
    private int dp(float value) { return Ui.dp(getContext(), value); }
    private String time(long value) {
        SimpleDateFormat format = new SimpleDateFormat("h a", Locale.US); format.setTimeZone(zone);
        return format.format(new Date(value));
    }
    private String rain(ReviewWeather.Hour hour) { return hour.rain == null ? "—" : Math.round(hour.rain) + "%"; }
    private void updateDescription() {
        if (series.hours.isEmpty()) { setContentDescription("Hourly forecast unavailable for today"); return; }
        ReviewWeather.Hour hour = series.hours.get(selected);
        setContentDescription("Hourly forecast, " + time(hour.start) + ", " + Math.round(hour.temperature)
                + " degrees F, " + hour.condition + ", precipitation " + (hour.rain == null ? "unknown" : rain(hour))
                + ". Left and right inspect hours.");
    }
    @Override public boolean onKeyDown(int code, KeyEvent event) {
        int next = selected;
        if (code == KeyEvent.KEYCODE_DPAD_LEFT && selected > 0) next--;
        else if (code == KeyEvent.KEYCODE_DPAD_RIGHT && selected+1 < series.hours.size()) next++;
        else return super.onKeyDown(code, event);
        selected = next; updateDescription(); invalidate(); sendAccessibilityEvent(AccessibilityEvent.TYPE_VIEW_SELECTED);
        return true;
    }
    @Override protected void onFocusChanged(boolean focused, int direction, Rect previous) {
        super.onFocusChanged(focused, direction, previous); invalidate();
    }
    private void label(Canvas canvas, String value, float x, float y, float size, int color, Paint.Align align) {
        text.setTextSize(dp(size)); text.setColor(color); text.setTextAlign(align); canvas.drawText(value, x, y, text);
    }
    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        int background = hasFocus() ? 0xFF15233A : 0xFF0A1425;
        if (hasFocus()) {
            ink.setStyle(Paint.Style.FILL); ink.setColor(background);
            canvas.drawRoundRect(new RectF(0, 0, getWidth(), getHeight()), dp(8), dp(8), ink);
            ink.setStyle(Paint.Style.STROKE); ink.setStrokeWidth(dp(1)); ink.setColor(0xFF527CA8);
            canvas.drawRoundRect(new RectF(dp(1), dp(1), getWidth()-dp(1), getHeight()-dp(1)), dp(8), dp(8), ink);
            ink.setStyle(Paint.Style.FILL);
        }
        if (series.hours.isEmpty()) {
            label(canvas, "No hourly forecast for today", dp(8), dp(20), 11, MUTED, Paint.Align.LEFT); return;
        }
        float left = dp(15), right = getWidth()-dp(15), top = dp(43), bottom = getHeight()-dp(66);
        ReviewWeather.Hour chosen = series.hours.get(selected);
        label(canvas, time(chosen.start) + " · " + Math.round(chosen.temperature) + "°F", dp(8), dp(14), 12, TEXT, Paint.Align.LEFT);
        WeatherIcon.drop(canvas, getWidth()-dp(54), dp(2), dp(14));
        label(canvas, rain(chosen), getWidth()-dp(8), dp(14), 11, BLUE, Paint.Align.RIGHT);
        text.setTextSize(dp(10)); text.setColor(MUTED); text.setTextAlign(Paint.Align.LEFT);
        canvas.drawText(TextUtils.ellipsize(chosen.condition, text, getWidth()-dp(16), TextUtils.TruncateAt.END).toString(), dp(8), dp(29), text);
        if (bottom <= top) return;
        ink.setStrokeWidth(dp(1)); ink.setColor(0xFF263B55);
        canvas.drawLine(left, top, right, top, ink); canvas.drawLine(left, bottom, right, bottom, ink);
        canvas.drawLine(left, (top+bottom)/2, right, (top+bottom)/2, ink);
        int size = series.hours.size(), stride = Math.max(1, (int)Math.ceil((size-1)/4.0));
        float lastX = 0, lastY = 0;
        for (int i=0; i<size; i++) {
            ReviewWeather.Hour hour = series.hours.get(i);
            float x = left+(right-left)*(float)series.x(i), y = bottom-(bottom-top)*(float)series.y(i);
            if (series.connected(i)) { ink.setColor(BLUE); ink.setStrokeWidth(dp(2.5f)); canvas.drawLine(lastX, lastY, x, y, ink); }
            ink.setColor(i == selected ? TEXT : BLUE); canvas.drawCircle(x, y, dp(i == selected ? 3.5f : 2), ink);
            if (i == selected) {
                ink.setColor(0x66527CA8); ink.setStrokeWidth(dp(1)); canvas.drawLine(x, top, x, bottom, ink);
            }
            if (i%stride == 0 || i == size-1) {
                label(canvas, Math.round(hour.temperature) + "°", x, y-dp(7), 11, TEXT, Paint.Align.CENTER);
                WeatherIcon.draw(canvas, x-dp(10), bottom+dp(5), dp(20), ReviewWeather.kind(hour.condition), hour.day, background);
                label(canvas, time(hour.start), x, bottom+dp(39), 9, MUTED, Paint.Align.CENTER);
            }
            float barWidth = Math.min(dp(9), (right-left)/Math.max(1, size)*.55f), baseline = getHeight()-dp(7);
            ink.setColor(0xFF42668B); ink.setStrokeWidth(dp(1)); canvas.drawLine(x-barWidth/2, baseline, x+barWidth/2, baseline, ink);
            if (hour.rain == null) {
                ink.setColor(MUTED); canvas.drawLine(x-barWidth/2, baseline-dp(4), x+barWidth/2, baseline-dp(4), ink);
            } else {
                ink.setColor(BLUE); canvas.drawRect(x-barWidth/2, baseline-dp(16)*(float)(hour.rain/100), x+barWidth/2, baseline, ink);
            }
            lastX = x; lastY = y;
        }
    }
}
