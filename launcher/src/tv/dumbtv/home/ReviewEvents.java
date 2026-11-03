package tv.dumbtv.home;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Display-only grouping: never changes the source calendars or their cached records. */
final class ReviewEvents {
    private ReviewEvents() {}

    static final class Event {
        final String key, title, color;
        final long start, end;
        final boolean allDay, busyOnly;
        String location;
        final Map<String, String> sources = new LinkedHashMap<>();
        final LinkedHashSet<String> keys = new LinkedHashSet<>();

        Event(String key, long start, long end, boolean allDay, boolean busyOnly,
                String title, String location, String sourceKey, String sourceLabel, String color) {
            this.key = key; this.start = start; this.end = end;
            this.allDay = allDay; this.busyOnly = busyOnly; this.title = title;
            this.location = location; this.color = color;
            sources.put(sourceKey, sourceLabel);
            if (!key.isEmpty()) keys.add(key);
        }

        Event copy() {
            Event copy = new Event(key, start, end, allDay, busyOnly, title, location, "", "", color);
            copy.sources.clear(); copy.sources.putAll(sources);
            copy.keys.clear(); copy.keys.addAll(keys); return copy;
        }

        String sourceLabels() {
            StringBuilder labels = new StringBuilder();
            for (String label : new LinkedHashSet<>(sources.values())) {
                if (labels.length() > 0) labels.append(" · ");
                labels.append(label);
            }
            return labels.toString();
        }
    }

    private static String normalized(String value) {
        return Normalizer.normalize(value, Normalizer.Form.NFKC)
                .replaceAll("[\\s\\p{Z}]+", " ").trim().toLowerCase(Locale.ROOT);
    }

    private static boolean compatible(Event a, Event b) {
        return a.start == b.start && a.end == b.end && a.allDay == b.allDay && a.busyOnly == b.busyOnly
                && (normalized(a.location).isEmpty() || normalized(b.location).isEmpty()
                    || normalized(a.location).equals(normalized(b.location)));
    }

    private static String signature(Event event) {
        return normalized(event.title) + "\u0000" + event.start + ":" + event.end + ":" + event.allDay + ":" + event.busyOnly;
    }

    static List<Event> combine(List<Event> input) {
        List<Event> result = new ArrayList<>();
        Map<String, LinkedHashSet<String>> venues = new LinkedHashMap<>();
        for (Event event : input) if (!normalized(event.location).isEmpty()) {
            String signature = signature(event);
            if (!venues.containsKey(signature)) venues.put(signature, new LinkedHashSet<>());
            venues.get(signature).add(normalized(event.location));
        }
        for (Event event : input) {
            Event match = null; int matches = 0;
            for (Event candidate : result) {
                if (!event.key.isEmpty() && candidate.keys.contains(event.key) && compatible(candidate, event)) {
                    match = candidate; matches++;
                }
            }
            if (matches == 0 && !event.busyOnly && !normalized(event.title).isEmpty()
                    && !"untitled event".equals(normalized(event.title))) {
                for (Event candidate : result) {
                    boolean sharedSource = false;
                    for (String source : event.sources.keySet()) if (candidate.sources.containsKey(source)) sharedSource = true;
                    boolean ambiguousVenue = (normalized(candidate.location).isEmpty() || normalized(event.location).isEmpty())
                            && venues.containsKey(signature(event)) && venues.get(signature(event)).size() > 1;
                    if (!sharedSource && !ambiguousVenue && compatible(candidate, event)
                            && normalized(candidate.title).equals(normalized(event.title))) {
                        match = candidate; matches++;
                    }
                }
            }
            // A blank venue that could refer to two different events is ambiguous: retain it.
            if (matches != 1) result.add(event.copy());
            else {
                match.sources.putAll(event.sources);
                match.keys.addAll(event.keys);
                if (normalized(match.location).isEmpty()) match.location = event.location;
            }
        }
        result.sort((a, b) -> {
            int allDay = Boolean.compare(b.allDay, a.allDay);
            return allDay != 0 ? allDay : Long.compare(a.start, b.start);
        });
        return result;
    }
}
