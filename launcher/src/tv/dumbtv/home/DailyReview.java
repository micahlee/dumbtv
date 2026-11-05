package tv.dumbtv.home;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;

/** Offline family dashboard. Only the Mini reads Google/NWS; this Activity has no network access. */
public final class DailyReview extends Activity {
    private static final int MATCH = ViewGroup.LayoutParams.MATCH_PARENT;
    private static final int WRAP = ViewGroup.LayoutParams.WRAP_CONTENT;
    private static final int WHITE = 0xFFF2F5FC, MUTED = 0xFFAFBED4, ACCENT = 0xFF9BC7FF;
    private static final long HOUR = 3600000L;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private JSONObject data = new JSONObject();
    private TimeZone zone = TimeZone.getTimeZone("America/New_York");
    private String loaded = "";
    private long shownDay;
    private long shownHour;
    private boolean cacheError;
    private LinearLayout root, content;
    private TextView footer;
    private AgendaScrollView agendaScroll;
    private boolean resumed;
    private FrameLayout stage;
    private MemoryFrame photoFrame;
    private View dashboardFocus;
    private final MemoryDeck photoDeck = new MemoryDeck();
    private ReviewRotation interlude;
    private WeatherVideoFrame videoFrame;
    private boolean weatherEnabled, photosEnabled;
    private int shownPhase = ReviewRotation.REVIEW;
    private boolean pendingRender;
    private int consumedPhotoKey = KeyEvent.KEYCODE_UNKNOWN;
    private final Runnable cycle = new Runnable() {
        @Override public void run() {
            if (!resumed || interlude == null) return;
            int phase = interlude.tick(SystemClock.uptimeMillis(), (photosEnabled && MemoryFrame.hasCollages(DailyReview.this)),
                    weatherEnabled && readClip() != null);
            showPhase(phase);
            handler.removeCallbacks(this);
            handler.postDelayed(this, interlude.delay(SystemClock.uptimeMillis()));
        }
    };
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            long today = dayStart(System.currentTimeMillis());
            boolean changed = load() || today != shownDay || System.currentTimeMillis()/HOUR != shownHour;
            if (photoFrame != null || videoFrame != null) pendingRender |= changed;
            else if (changed || pendingRender) { pendingRender = false; render(); }
            else updateFooter();
            handler.postDelayed(this, 60000);
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        Config cfg = Config.get(this); cfg.refresh();
        if (!"on".equals(cfg.get("review.enabled", "off"))) { finish(); return; }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        load(); render();
    }
    @Override protected void onResume() {
        super.onResume(); resumed = true;
        Config cfg = Config.get(this); cfg.refresh();
        if (!"on".equals(cfg.get("review.enabled", "off"))) { finish(); return; }
        // The external launcher can reuse this task. Re-read opt-ins and timing
        // on every resume instead of retaining a previous invocation's settings.
        weatherEnabled = "on".equals(cfg.get("review.weather_video", "off"));
        photosEnabled = "on".equals(cfg.get("review.photos", "off")) && "on".equals(cfg.get("memories.enabled", "off"));
        interlude = (photosEnabled || weatherEnabled)
                ? new ReviewRotation(seconds(cfg, "review.photo_interval_seconds", 180, 15, 3600),
                    seconds(cfg, "review.photo_duration_seconds", 45, 5, 180), weatherEnabled) : null;
        if (!isFinishing()) {
            handler.post(poll);
            if (agendaScroll != null) agendaScroll.setActive(true);
            if (interlude != null) { interlude.resume(SystemClock.uptimeMillis()); schedulePhotos(); }
        }
    }
    @Override protected void onPause() {
        resumed = false; handler.removeCallbacks(poll); handler.removeCallbacks(cycle);
        consumedPhotoKey = KeyEvent.KEYCODE_UNKNOWN;
        if (interlude != null) interlude.pause();
        showPhase(ReviewRotation.REVIEW);
        if (agendaScroll != null) agendaScroll.setActive(false);
        super.onPause();
    }
    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        int code = event.getKeyCode();
        if (consumedPhotoKey != KeyEvent.KEYCODE_UNKNOWN && code == consumedPhotoKey) {
            if (event.getAction() == KeyEvent.ACTION_UP) consumedPhotoKey = KeyEvent.KEYCODE_UNKNOWN;
            return true;
        }
        if (event.getAction() == KeyEvent.ACTION_DOWN) {
            if (videoFrame != null) {
                if (code == KeyEvent.KEYCODE_DPAD_CENTER || code == KeyEvent.KEYCODE_ENTER
                        || code == KeyEvent.KEYCODE_NUMPAD_ENTER) {
                    if (event.getRepeatCount() == 0) videoFrame.toggleSound();
                    consumedPhotoKey = code; return true;
                }
                // Sound remains muted until an explicit OK; hardware volume never changes that gate.
                if (code == KeyEvent.KEYCODE_VOLUME_UP || code == KeyEvent.KEYCODE_VOLUME_DOWN
                        || code == KeyEvent.KEYCODE_VOLUME_MUTE) return super.dispatchKeyEvent(event);
            }
            boolean wasMedia = photoFrame != null || videoFrame != null;
            if (interlude != null) { interlude.interact(SystemClock.uptimeMillis()); schedulePhotos(); }
            if (wasMedia) {
                showPhase(ReviewRotation.REVIEW);
                if (code != KeyEvent.KEYCODE_VOLUME_UP && code != KeyEvent.KEYCODE_VOLUME_DOWN
                        && code != KeyEvent.KEYCODE_VOLUME_MUTE && code != KeyEvent.KEYCODE_POWER
                        && code != KeyEvent.KEYCODE_HOME) { consumedPhotoKey = code; return true; }
            }
        }
        if (event.getAction() == KeyEvent.ACTION_DOWN && agendaScroll != null)
            agendaScroll.manualInteraction();
        return super.dispatchKeyEvent(event);
    }

    private long seconds(Config cfg, String key, int fallback, int minimum, int maximum) {
        try { return Math.max(minimum, Math.min(maximum, Integer.parseInt(cfg.get(key, "" + fallback)))) * 1000L; }
        catch (NumberFormatException ignored) { return fallback * 1000L; }
    }
    private void schedulePhotos() {
        handler.removeCallbacks(cycle);
        if (resumed && interlude != null) handler.postDelayed(cycle, interlude.delay(SystemClock.uptimeMillis()));
    }
    private ForecastClip readClip() {
        if (!weatherEnabled) return null;
        File directory = new File(Config.get(this).dir, "weather-video");
        File manifest = new File(directory, "forecast.json");
        if (!manifest.isFile() || manifest.length() > 8192) return null;
        try (FileInputStream input = new FileInputStream(manifest);
                ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[1024]; int n;
            while ((n = input.read(buffer)) != -1) {
                if (out.size() + n > 8192) return null;
                out.write(buffer, 0, n);
            }
            JSONObject value = new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8));
            String name = value.optString("file"), title = value.optString("title");
            long published = value.optLong("publishedAt"), expires = value.optLong("expiresAt"), size = value.optLong("bytes");
            if (value.optInt("version") != 1 || !ForecastClip.valid(name, value.optString("source"), title,
                    published, expires, System.currentTimeMillis(), value.optLong("durationSeconds"), size)) return null;
            File file = new File(directory, name);
            if (!file.isFile() || file.length() != size || !file.getCanonicalFile().getParentFile().equals(directory.getCanonicalFile())) return null;
            return new ForecastClip(file, title, published, expires);
        } catch (IOException | JSONException ignored) { return null; }
    }
    private void showPhase(int phase) {
        if (phase == shownPhase) return;
        if (shownPhase == ReviewRotation.REVIEW) dashboardFocus = getCurrentFocus();
        if (photoFrame != null) { photoFrame.stop(); stage.removeView(photoFrame); photoFrame = null; }
        if (videoFrame != null) { videoFrame.stop(); stage.removeView(videoFrame); videoFrame = null; }
        shownPhase = phase;
        if (phase == ReviewRotation.REVIEW) {
            root.setVisibility(View.VISIBLE);
            if (pendingRender && resumed) { pendingRender = false; render(); }
            else {
                if (resumed && dashboardFocus != null) dashboardFocus.requestFocus();
                if (agendaScroll != null) agendaScroll.setActive(resumed);
            }
            return;
        }
        agendaScroll.setActive(false); root.setVisibility(View.INVISIBLE);
        if (phase == ReviewRotation.VIDEO) {
            ForecastClip clip = readClip();
            if (clip == null) { handler.post(this::videoFinished); return; }
            videoFrame = new WeatherVideoFrame(this, clip, this::videoFinished);
            stage.addView(videoFrame, new FrameLayout.LayoutParams(MATCH, MATCH));
        } else {
            photoFrame = new MemoryFrame(this, photoDeck, true, () -> {
                if (!resumed || interlude == null) return;
                interlude.interact(SystemClock.uptimeMillis()); showPhase(ReviewRotation.REVIEW); schedulePhotos();
            });
            stage.addView(photoFrame, new FrameLayout.LayoutParams(MATCH, MATCH));
        }
    }
    private void videoFinished() {
        if (!resumed || interlude == null || shownPhase != ReviewRotation.VIDEO) return;
        interlude.videoFinished(SystemClock.uptimeMillis(), (photosEnabled && MemoryFrame.hasCollages(this)));
        showPhase(interlude.phase()); schedulePhotos();
    }

    private boolean load() {
        File file = new File(Config.get(this).dir, "review/review.json");
        String signature = file.lastModified() + ":" + file.length();
        if (signature.equals(loaded)) return false;
        loaded = signature;
        try (FileInputStream input = new FileInputStream(file);
                ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192]; int count;
            while ((count = input.read(buffer)) != -1) {
                if (bytes.size() + count > 4194304) throw new IOException("Review is too large");
                bytes.write(buffer, 0, count);
            }
            JSONObject next = new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
            if (next.optInt("version") != 1) throw new JSONException("Unknown review version");
            data = next;
            zone = TimeZone.getTimeZone(data.optString("timezone", "America/New_York"));
            cacheError = false;
        } catch (IOException | JSONException ignored) {
            cacheError = true;
            // Retain the last successfully parsed generation in memory; never show a crash or credentials.
        }
        return true;
    }

    private int dp(float value) { return Ui.dp(this, value); }
    private LinearLayout column() { LinearLayout v = new LinearLayout(this); v.setOrientation(LinearLayout.VERTICAL); return v; }
    private TextView label(String text, float size, int color) {
        TextView v = Ui.text(this, size, color, Ui.MEDIUM); v.setText(text); return v;
    }
    private TextView button(String title, Runnable click) {
        TextView v = label(title, 13, WHITE);
        v.setPadding(dp(15), dp(10), dp(15), dp(10)); v.setGravity(Gravity.CENTER);
        v.setFocusable(true); v.setClickable(true);
        Ui.focusStyle(v, ACCENT, 0xFF1B2B43, dp(8));
        v.setOnClickListener(view -> click.run()); return v;
    }
    private String fmt(long time, String pattern) {
        SimpleDateFormat format = new SimpleDateFormat(pattern, Locale.US); format.setTimeZone(zone);
        return format.format(new Date(time));
    }
    private long dayStart(long time) {
        Calendar calendar = Calendar.getInstance(zone); calendar.setTimeInMillis(time);
        calendar.set(Calendar.HOUR_OF_DAY, 0); calendar.set(Calendar.MINUTE, 0);
        calendar.set(Calendar.SECOND, 0); calendar.set(Calendar.MILLISECOND, 0);
        return calendar.getTimeInMillis();
    }
    private long plusDays(long time, int days) {
        Calendar calendar = Calendar.getInstance(zone); calendar.setTimeInMillis(time);
        calendar.add(Calendar.DATE, days); return calendar.getTimeInMillis();
    }
    private String age(long time) {
        if (time <= 0) return "not refreshed";
        long minutes = Math.max(0, (System.currentTimeMillis()-time)/60000);
        return minutes < 1 ? "just now" : minutes < 60 ? minutes + "m ago" : minutes < 1440
                ? minutes/60 + "h ago" : fmt(time, "MMM d, h:mm a");
    }
    private JSONObject object(JSONObject parent, String name) {
        JSONObject result = parent.optJSONObject(name); return result == null ? new JSONObject() : result;
    }
    private List<JSONObject> objects(JSONObject parent, String name) {
        List<JSONObject> result = new ArrayList<>(); JSONArray array = parent.optJSONArray(name);
        if (array != null) for (int i=0; i<array.length(); i++) {
            JSONObject row = array.optJSONObject(i); if (row != null) result.add(row);
        }
        return result;
    }
    private boolean overlaps(JSONObject event, long start, long end) {
        return event.optLong("start") < end && event.optLong("end") > start;
    }
    private LinearLayout card() {
        LinearLayout box = column(); box.setPadding(dp(16), dp(14), dp(16), dp(14));
        box.setBackground(Ui.round(0xFF15233A, dp(12))); return box;
    }
    private void addLine(LinearLayout box, String line, float size, int color) {
        TextView text = label(line, size, color);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(MATCH, WRAP); lp.bottomMargin = dp(6);
        box.addView(text, lp);
    }
    private void focusLines(LinearLayout box) {
        for (int i=0; i<box.getChildCount(); i++) {
            View line = box.getChildAt(i); line.setFocusable(true);
            line.setOnFocusChangeListener((v, focused) -> v.setBackground(Ui.round(focused ? 0xFF294463 : 0x00000000, dp(4))));
        }
    }
    private AgendaScrollView scrolling(LinearLayout child) {
        AgendaScrollView scroll = new AgendaScrollView(this); scroll.setFillViewport(false); scroll.setFocusable(false);
        scroll.setClipToPadding(false); scroll.setPadding(dp(3), dp(3), dp(3), dp(8));
        scroll.addView(child, new FrameLayout.LayoutParams(MATCH, WRAP)); return scroll;
    }

    private void render() {
        if (agendaScroll != null) agendaScroll.setActive(false);
        shownDay = dayStart(System.currentTimeMillis());
        shownHour = System.currentTimeMillis()/HOUR;
        long start = shownDay, end = plusDays(start, 1);
        root = column(); root.setBackgroundColor(0xFF0A1425); root.setPadding(dp(28), dp(16), dp(28), dp(14));
        LinearLayout header = new LinearLayout(this); header.setGravity(Gravity.CENTER_VERTICAL);
        header.addView(label("Daily Review", 20, WHITE));
        TextView date = label("   " + fmt(start, "EEEE, MMMM d"), 13, MUTED);
        header.addView(date, new LinearLayout.LayoutParams(0, WRAP, 1));
        TextView back = button("Back to apps", this::finish); back.setPadding(dp(12), dp(7), dp(12), dp(7));
        header.addView(back);
        root.addView(header, new LinearLayout.LayoutParams(MATCH, WRAP));
        content = new LinearLayout(this);
        LinearLayout left = column();
        left.addView(weatherCard(start, end), new LinearLayout.LayoutParams(MATCH, WRAP));
        TextView hourlyTitle = label("Hourly forecast", 12, ACCENT); hourlyTitle.setPadding(dp(3), dp(10), 0, dp(5));
        left.addView(hourlyTitle);
        left.addView(hourly(start, end), new LinearLayout.LayoutParams(MATCH, 0, 1));
        LinearLayout.LayoutParams leftLp = new LinearLayout.LayoutParams(0, MATCH, .28f); leftLp.rightMargin = dp(16);
        content.addView(left, leftLp);
        LinearLayout agenda = agenda(start, end);
        agendaScroll = scrolling(agenda);
        content.addView(agendaScroll, new LinearLayout.LayoutParams(0, MATCH, .72f));
        LinearLayout.LayoutParams bodyLp = new LinearLayout.LayoutParams(MATCH, 0, 1); bodyLp.topMargin = dp(12);
        root.addView(content, bodyLp);
        footer = label("", 10, MUTED); footer.setPadding(0, dp(8), 0, 0);
        updateFooter(); root.addView(footer);
        stage = new FrameLayout(this); stage.addView(root, new FrameLayout.LayoutParams(MATCH, MATCH));
        setContentView(stage);
        back.requestFocus();
        for (int i=0; i<agenda.getChildCount(); i++) if (agenda.getChildAt(i).isFocusable()) {
            agenda.getChildAt(i).requestFocus(); break;
        }
        agendaScroll.setActive(resumed);
    }

    private void updateFooter() {
        if (footer == null) return;
        JSONObject weather = object(data, "weather"), calendar = object(data, "calendar");
        int errors = 0; for (JSONObject source : objects(calendar, "sources")) if (!source.optString("error").isEmpty()) errors++;
        String note = "Calendar checked " + age(calendar.optLong("checkedAt")) + "  ·  NWS forecast checked " + age(weather.optLong("fetchedAt"))
                + "  ·  Refreshes hourly";
        if (!calendar.optString("error").isEmpty() || errors > 0) note += "  ·  Calendar needs attention";
        if (!weather.optString("error").isEmpty()) note += "  ·  Weather refresh unavailable";
        if (cacheError) note += "  ·  Cache unavailable; last valid view retained";
        footer.setText(note);
    }

    private LinearLayout weatherCard(long start, long end) {
        LinearLayout box = card(); JSONObject weather = object(data, "weather");
        addLine(box, weather.optString("label", "Weather"), 14, ACCENT);
        JSONObject current = null, daily = null; Integer high = null, low = null;
        long target = System.currentTimeMillis();
        for (JSONObject p : objects(weather, "hourly")) if (p.optLong("start") <= target && p.optLong("end") > target) current = p;
        for (JSONObject p : objects(weather, "daily")) if (p.optLong("start") >= start && p.optLong("start") < end) {
            if (p.optBoolean("day")) { high = p.optInt("temperature"); daily = p; }
            else { low = p.optInt("temperature"); if (daily == null) daily = p; }
        }
        String range = "High " + (high == null ? "—" : high + "°") + "  Low " + (low == null ? "—" : low + "°");
        String condition = current != null ? current.optString("condition") : daily == null ? "Forecast unavailable" : daily.optString("condition");
        boolean daylight = current != null ? current.optBoolean("day", true) : daily == null || daily.optBoolean("day", true);
        LinearLayout summary = new LinearLayout(this); summary.setGravity(Gravity.CENTER_VERTICAL);
        summary.addView(new WeatherIcon(this, ReviewWeather.kind(condition), daylight, 0xFF15233A, condition),
                new LinearLayout.LayoutParams(dp(50), dp(50)));
        LinearLayout temperatures = column(); temperatures.setPadding(dp(8), 0, 0, dp(4));
        temperatures.addView(label(current == null ? "—°F" : current.optInt("temperature") + "°F", 30, WHITE));
        TextView highLow = label(range, 12, WHITE); highLow.setPadding(0, dp(3), 0, 0); temperatures.addView(highLow);
        summary.addView(temperatures, new LinearLayout.LayoutParams(0, WRAP, 1));
        box.addView(summary, new LinearLayout.LayoutParams(MATCH, WRAP));
        addLine(box, condition, 15, WHITE);
        if (current != null) {
            LinearLayout precipitation = new LinearLayout(this); precipitation.setGravity(Gravity.CENTER_VERTICAL);
            precipitation.addView(WeatherIcon.precipitation(this), new LinearLayout.LayoutParams(dp(13), dp(13)));
            TextView detail = label(" " + (current.isNull("rain") ? "—" : current.optInt("rain") + "%")
                    + " precip · Wind " + current.optString("wind"), 10, MUTED);
            precipitation.addView(detail, new LinearLayout.LayoutParams(0, WRAP, 1)); box.addView(precipitation);
        }
        addLine(box, "Forecast · " + fmt(target, "h a") + "  ·  NWS " + age(weather.optLong("hourlyIssuedAt")), 10, MUTED);
        if (!weather.optString("error").isEmpty() || System.currentTimeMillis()-weather.optLong("fetchedAt") > 2*HOUR
                || System.currentTimeMillis()-weather.optLong("hourlyIssuedAt") > 6*HOUR)
            addLine(box, "Saved forecast · check refresh time below", 11, 0xFFFFCA83);
        focusLines(box); return box;
    }

    private LinearLayout agenda(long start, long end) {
        LinearLayout list = column(); JSONObject calendar = object(data, "calendar");
        List<ReviewEvents.Event> raw = new ArrayList<>();
        StringBuilder warnings = new StringBuilder(); int sourceCount = 0;
        for (JSONObject source : objects(calendar, "sources")) {
            sourceCount++;
            boolean stale = System.currentTimeMillis()-source.optLong("fetchedAt") > 2*HOUR || !source.optString("error").isEmpty();
            if (stale) warnings.append(warnings.length() == 0 ? "Saved/unavailable: " : " · ").append(source.optString("label"));
            for (JSONObject event : objects(source, "events")) if (overlaps(event, start, end)) {
                raw.add(new ReviewEvents.Event(event.optString("key"), event.optLong("start"), event.optLong("end"),
                        event.optBoolean("allDay"), event.optBoolean("busyOnly"), event.optString("title"),
                        event.optString("location"), source.optString("key", source.optString("label")),
                        source.optString("label"), event.optString("color")));
            }
        }
        List<ReviewEvents.Event> events = ReviewEvents.combine(raw);
        LinearLayout heading = new LinearLayout(this); heading.setGravity(Gravity.CENTER_VERTICAL);
        heading.addView(label("Today's calendar", 17, WHITE), new LinearLayout.LayoutParams(0, WRAP, 1));
        heading.addView(label(events.size() + " events · " + sourceCount + " calendars", 11, MUTED));
        LinearLayout.LayoutParams headingLp = new LinearLayout.LayoutParams(MATCH, WRAP); headingLp.bottomMargin = dp(10);
        list.addView(heading, headingLp);
        if (!calendar.optString("error").isEmpty()) addLine(list, calendar.optString("error"), 11, 0xFFFFCA83);
        if (warnings.length() > 0) addLine(list, warnings.toString(), 10, 0xFFFFCA83);
        if (start < calendar.optLong("start") || end > calendar.optLong("end"))
            addLine(list, "Today has not been refreshed yet", 12, 0xFFFFCA83);
        if (events.isEmpty()) addLine(list, sourceCount == 0 ? "Calendar setup is pending on the mini" : "No saved events for today", 17, MUTED);
        for (ReviewEvents.Event event : events) {
            LinearLayout row = new LinearLayout(this); row.setGravity(Gravity.TOP);
            row.setPadding(dp(12), dp(6), dp(12), dp(6)); row.setBackground(Ui.round(0xFF15233A, dp(8)));
            String time = event.allDay ? "All day" : fmt(Math.max(start, event.start), "h:mm a")
                    + "\n– " + fmt(Math.min(end, event.end), "h:mm a");
            int color = ACCENT;
            try { color = android.graphics.Color.parseColor(event.color); }
            catch (IllegalArgumentException ignored) { /* Provider color uses fallback. */ }
            TextView when = label(time, 12, color); when.setPadding(0, dp(2), dp(12), 0);
            row.addView(when, new LinearLayout.LayoutParams(dp(99), WRAP));
            LinearLayout detail = column();
            detail.addView(label(event.title, events.size() > 10 ? 14 : 16, WHITE), new LinearLayout.LayoutParams(MATCH, WRAP));
            String metadata = event.sourceLabels() + (event.location.isEmpty() ? "" : "  ·  " + event.location);
            TextView sources = label(metadata, 10, MUTED); sources.setPadding(0, dp(3), 0, 0);
            detail.addView(sources, new LinearLayout.LayoutParams(MATCH, WRAP));
            row.addView(detail, new LinearLayout.LayoutParams(0, WRAP, 1));
            row.setFocusable(true); row.setContentDescription(time + ", " + event.title + ", " + metadata);
            row.setOnFocusChangeListener((view, focus) -> view.setBackground(Ui.round(focus ? 0xFF294463 : 0xFF15233A, dp(8))));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(MATCH, WRAP); lp.bottomMargin = dp(5); list.addView(row, lp);
        }
        return list;
    }

    private HourlyChart hourly(long start, long end) {
        List<ReviewWeather.Hour> hours = new ArrayList<>();
        for (JSONObject p : objects(object(data, "weather"), "hourly")) {
            Double rain = p.isNull("rain") ? null : p.optDouble("rain", Double.NaN);
            hours.add(new ReviewWeather.Hour(p.optLong("start"), p.optLong("end"),
                    p.optDouble("temperature", Double.NaN), rain, p.optString("condition"), p.optBoolean("day", true)));
        }
        return new HourlyChart(this, new ReviewWeather.Series(hours, start, end, System.currentTimeMillis()), zone);
    }
}
