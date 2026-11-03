package tv.dumbtv.home;

import android.app.Activity;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
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
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
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
    private int selected;
    private String loaded = "";
    private long shownDay;
    private long shownHour;
    private boolean cacheError;
    private LinearLayout root, content;
    private TextView footer;
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            long today = dayStart(System.currentTimeMillis());
            if (load() || today != shownDay || System.currentTimeMillis()/HOUR != shownHour) {
                selected = today != shownDay ? 0 : selected; render();
            } else updateFooter();
            handler.postDelayed(this, 60000);
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        Config cfg = Config.get(this); cfg.refresh();
        if (!"on".equals(cfg.get("review.enabled", "off"))) { finish(); return; }
        load(); render();
    }
    @Override protected void onResume() { super.onResume(); if (!isFinishing()) handler.post(poll); }
    @Override protected void onPause() { handler.removeCallbacks(poll); super.onPause(); }

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
    private ScrollView scrolling(LinearLayout child) {
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(false); scroll.setFocusable(false);
        scroll.setClipToPadding(false); scroll.setPadding(dp(3), dp(3), dp(3), dp(8));
        scroll.addView(child, new FrameLayout.LayoutParams(MATCH, WRAP)); return scroll;
    }

    private void render() {
        shownDay = dayStart(System.currentTimeMillis());
        shownHour = System.currentTimeMillis()/HOUR;
        long start = plusDays(shownDay, selected), end = plusDays(start, 1);
        root = column(); root.setBackgroundColor(0xFF0A1425); root.setPadding(dp(34), dp(22), dp(34), dp(18));
        LinearLayout header = new LinearLayout(this); header.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout titles = column();
        titles.addView(label("Daily Review", 26, WHITE));
        titles.addView(label(fmt(start, "EEEE, MMMM d") + "  ·  " + zone.getDisplayName(zone.inDaylightTime(new Date(start)), TimeZone.SHORT), 13, MUTED));
        header.addView(titles, new LinearLayout.LayoutParams(0, WRAP, 1));
        header.addView(button("Back to apps", this::finish));
        root.addView(header, new LinearLayout.LayoutParams(MATCH, WRAP));
        LinearLayout tabs = new LinearLayout(this); tabs.setPadding(0, dp(12), 0, dp(12));
        TextView active = null;
        for (int i=0; i<7; i++) {
            final int day = i;
            TextView tab = button((i == 0 ? "Today" : i == 1 ? "Tomorrow" : fmt(plusDays(shownDay, i), "EEE d"))
                    + (selected == i ? "  •" : ""), () -> { selected = day; render(); });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, WRAP, 1); lp.rightMargin = dp(6);
            tabs.addView(tab, lp); if (i == selected) active = tab;
        }
        root.addView(tabs);
        content = new LinearLayout(this);
        LinearLayout left = column();
        left.addView(scrolling(weatherCard(start, end)), new LinearLayout.LayoutParams(MATCH, 0, 1.1f));
        LinearLayout.LayoutParams workLp = new LinearLayout.LayoutParams(MATCH, 0, 1); workLp.topMargin = dp(10);
        left.addView(scrolling(workCard(start, end)), workLp);
        LinearLayout.LayoutParams leftLp = new LinearLayout.LayoutParams(0, MATCH, .34f); leftLp.rightMargin = dp(14);
        content.addView(left, leftLp);
        content.addView(scrolling(agenda(start, end)), new LinearLayout.LayoutParams(0, MATCH, .66f));
        root.addView(content, new LinearLayout.LayoutParams(MATCH, 0, 1));
        hourly(start, end);
        footer = label("", 10, MUTED); footer.setPadding(0, dp(8), 0, 0);
        updateFooter(); root.addView(footer);
        setContentView(root); if (active != null) active.requestFocus();
    }

    private void updateFooter() {
        if (footer == null) return;
        JSONObject weather = object(data, "weather"), calendar = object(data, "calendar");
        int errors = 0; for (JSONObject source : objects(calendar, "sources")) if (!source.optString("error").isEmpty()) errors++;
        String note = "Calendar checked " + age(calendar.optLong("checkedAt")) + "  ·  NWS forecast checked " + age(weather.optLong("fetchedAt"))
                + "  ·  Hourly mini refresh";
        if (!calendar.optString("error").isEmpty() || errors > 0) note += "  ·  Calendar needs attention";
        if (!weather.optString("error").isEmpty()) note += "  ·  Weather refresh unavailable";
        if (cacheError) note += "  ·  Cache unavailable; last valid view retained";
        footer.setText(note);
    }

    private LinearLayout weatherCard(long start, long end) {
        LinearLayout box = card(); JSONObject weather = object(data, "weather");
        addLine(box, weather.optString("label", "Weather"), 14, ACCENT);
        JSONObject current = null, daily = null; Integer high = null, low = null;
        long target = selected == 0 ? System.currentTimeMillis() : start + 12*HOUR;
        for (JSONObject p : objects(weather, "hourly")) if (p.optLong("start") <= target && p.optLong("end") > target) current = p;
        for (JSONObject p : objects(weather, "daily")) if (p.optLong("start") >= start && p.optLong("start") < end) {
            if (p.optBoolean("day")) { high = p.optInt("temperature"); daily = p; }
            else { low = p.optInt("temperature"); if (daily == null) daily = p; }
        }
        if (current != null) {
            addLine(box, current.optInt("temperature") + "°F", 38, WHITE);
            addLine(box, current.optString("condition"), 17, WHITE);
            addLine(box, "Forecast · " + fmt(target, "h a") + "  |  Wind " + current.optString("wind"), 11, MUTED);
        } else addLine(box, daily == null ? "Forecast unavailable for this time" : daily.optString("condition"), 16, MUTED);
        addLine(box, "High " + (high == null ? "—" : high + "°") + "   Low " + (low == null ? "—" : low + "°"), 15, WHITE);
        if (weather.optLong("hourlyIssuedAt") > 0) addLine(box, "NWS issued " + age(weather.optLong("hourlyIssuedAt")), 10, MUTED);
        if (!weather.optString("error").isEmpty() || System.currentTimeMillis()-weather.optLong("fetchedAt") > 2*HOUR
                || System.currentTimeMillis()-weather.optLong("hourlyIssuedAt") > 6*HOUR)
            addLine(box, "Saved forecast · check refresh time below", 11, 0xFFFFCA83);
        focusLines(box); return box;
    }

    private LinearLayout workCard(long start, long end) {
        LinearLayout box = card(); addLine(box, "Work availability", 14, ACCENT);
        JSONObject calendar = object(data, "calendar"); boolean found = false;
        for (JSONObject source : objects(calendar, "sources")) {
            if (!source.optBoolean("busyOnly")) continue;
            found = true;
            if (!calendar.optString("error").isEmpty() || !source.optString("error").isEmpty() || source.optLong("fetchedAt") < System.currentTimeMillis()-2*HOUR) {
                addLine(box, "Saved or unavailable · " + age(source.optLong("fetchedAt")), 12, 0xFFFFCA83);
            }
            if (source.optLong("fetchedAt") == 0 || start < calendar.optLong("start") || end > calendar.optLong("end")) {
                addLine(box, "Availability unavailable", 13, MUTED); continue;
            }
            List<JSONObject> busy = new ArrayList<>();
            for (JSONObject event : objects(source, "events")) if (overlaps(event, start, end)) busy.add(event);
            Collections.sort(busy, Comparator.comparingLong(p -> p.optLong("start")));
            Calendar working = Calendar.getInstance(zone); working.setTimeInMillis(start); working.set(Calendar.HOUR_OF_DAY, 8);
            long a = working.getTimeInMillis(); working.set(Calendar.HOUR_OF_DAY, 18); long finish = working.getTimeInMillis();
            addLine(box, "Calendar availability · 8 AM–6 PM", 10, MUTED);
            for (JSONObject event : busy) {
                long b = Math.max(a, event.optLong("start")), e = Math.min(finish, event.optLong("end"));
                if (e <= a || b >= finish) continue;
                if (b > a) addLine(box, fmt(a, "h:mm") + "–" + fmt(b, "h:mm a") + "  Available", 12, 0xFF91D8B7);
                addLine(box, fmt(b, "h:mm") + "–" + fmt(e, "h:mm a") + "  Busy", 12, 0xFFFFC18F);
                a = Math.max(a, e);
            }
            if (a < finish) addLine(box, fmt(a, "h:mm") + "–" + fmt(finish, "h:mm a") + "  Available", 12, 0xFF91D8B7);
        }
        if (!found) addLine(box, "Work calendar not loaded", 12, MUTED);
        focusLines(box); return box;
    }

    private LinearLayout agenda(long start, long end) {
        LinearLayout list = column(); JSONObject calendar = object(data, "calendar");
        Map<String, JSONObject> instances = new LinkedHashMap<>();
        addLine(list, "Family & calendars", 18, WHITE);
        StringBuilder warnings = new StringBuilder(); int sourceCount = 0;
        for (JSONObject source : objects(calendar, "sources")) {
            sourceCount++;
            boolean stale = System.currentTimeMillis()-source.optLong("fetchedAt") > 2*HOUR || !source.optString("error").isEmpty();
            if (stale) warnings.append(warnings.length() == 0 ? "Saved/unavailable: " : " · ").append(source.optString("label"));
            for (JSONObject event : objects(source, "events")) if (overlaps(event, start, end)) {
                String key = event.optString("key");
                // Same iCalendar instance copied to multiple calendars appears once.
                // Independent calendars' distinct events keep their own identities.
                try {
                    JSONObject existing = instances.get(key);
                    if (existing == null) instances.put(key, new JSONObject(event.toString()));
                    else existing.put("source", existing.optString("source") + " / " + event.optString("source"));
                } catch (JSONException ignored) { cacheError = true; }
            }
        }
        List<JSONObject> events = new ArrayList<>(instances.values());
        Collections.sort(events, (a, b) -> {
            int allDay = Boolean.compare(b.optBoolean("allDay"), a.optBoolean("allDay"));
            return allDay != 0 ? allDay : Long.compare(a.optLong("start"), b.optLong("start"));
        });
        addLine(list, sourceCount + " calendars · source labels on every event", 11, MUTED);
        if (!calendar.optString("error").isEmpty()) addLine(list, calendar.optString("error"), 12, 0xFFFFCA83);
        if (warnings.length() > 0) addLine(list, warnings.toString(), 11, 0xFFFFCA83);
        if (start < calendar.optLong("start") || end > calendar.optLong("end"))
            addLine(list, "This day has not been refreshed yet", 13, 0xFFFFCA83);
        if (events.isEmpty()) addLine(list, sourceCount == 0 ? "Calendar setup is pending on the mini"
                : "No saved events for this day", 18, MUTED);
        for (JSONObject event : events) {
            LinearLayout row = card();
            String time = event.optBoolean("allDay") ? "ALL DAY" : fmt(Math.max(start, event.optLong("start")), "h:mm a")
                    + " – " + fmt(Math.min(end, event.optLong("end")), "h:mm a");
            int color = ACCENT;
            try { color = android.graphics.Color.parseColor(event.optString("color")); }
            catch (IllegalArgumentException ignored) { /* Untrusted provider color uses fallback. */ }
            addLine(row, time + "  ·  " + event.optString("source"), 12, color);
            addLine(row, event.optString("title"), 18, WHITE);
            if (!event.optString("location").isEmpty()) addLine(row, event.optString("location"), 12, MUTED);
            row.setFocusable(true); row.setContentDescription(time + ", " + event.optString("title") + ", " + event.optString("source"));
            row.setOnFocusChangeListener((view, focus) -> view.setBackground(Ui.round(focus ? 0xFF294463 : 0xFF15233A, dp(12))));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(MATCH, WRAP); lp.bottomMargin = dp(8);
            list.addView(row, lp);
        }
        return list;
    }

    private void hourly(long start, long end) {
        JSONObject weather = object(data, "weather");
        TextView title = label("Hourly forecast · temperature / rain chance", 12, ACCENT); title.setPadding(0, dp(8), 0, dp(5));
        root.addView(title);
        HorizontalScrollView scroll = new HorizontalScrollView(this); scroll.setFocusable(false);
        LinearLayout hours = new LinearLayout(this); int count = 0;
        for (JSONObject p : objects(weather, "hourly")) {
            if (!overlaps(p, start, end) || (selected == 0 && p.optLong("end") <= System.currentTimeMillis())) continue;
            LinearLayout cell = column(); cell.setPadding(dp(10), dp(7), dp(10), dp(7));
            addLine(cell, fmt(p.optLong("start"), "h a"), 11, MUTED);
            addLine(cell, p.optInt("temperature") + "°  /  " + (p.isNull("rain") ? "—" : p.optInt("rain") + "%"), 14, WHITE);
            TextView condition = label(p.optString("condition"), 10, MUTED); condition.setMaxLines(2); cell.addView(condition);
            cell.setFocusable(true); cell.setOnFocusChangeListener((v, focused) -> v.setBackground(Ui.round(focused ? 0xFF294463 : 0xFF15233A, dp(8))));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(124), dp(87)); lp.rightMargin = dp(6); hours.addView(cell, lp); count++;
        }
        if (count == 0) hours.addView(label("No hourly forecast available for this day", 13, MUTED));
        scroll.addView(hours, new FrameLayout.LayoutParams(WRAP, WRAP));
        root.addView(scroll, new LinearLayout.LayoutParams(MATCH, dp(91)));
    }
}
