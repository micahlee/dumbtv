package tv.dumbtv.home;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.TreeMap;

/** Weather meanings and chart coordinates, independent of Android drawing. */
final class ReviewWeather {
    enum Kind { CLEAR, PARTLY_CLOUDY, CLOUDY, RAIN, STORM, SNOW, ICE, MIX, FOG, WIND, UNKNOWN }
    private ReviewWeather() {}

    static Kind kind(String condition) {
        String value = condition.toLowerCase(Locale.ROOT);
        if (value.contains("thunder")) return Kind.STORM;
        boolean snow = value.contains("snow") || value.contains("flurr");
        boolean rain = value.contains("rain") || value.contains("drizz");
        if (value.contains("wintry") || (snow && (rain || value.contains("sleet")))) return Kind.MIX;
        if (value.contains("sleet") || value.contains("ice pellet") || value.contains("hail")
                || value.contains("freezing rain") || value.contains("freezing drizz")) return Kind.ICE;
        if (snow) return Kind.SNOW;
        if (rain || value.contains("shower")) return Kind.RAIN;
        if (value.contains("fog") || value.contains("mist") || value.contains("haze") || value.contains("smoke")) return Kind.FOG;
        if (value.contains("partly") || value.contains("mostly sunny") || value.contains("few clouds")) return Kind.PARTLY_CLOUDY;
        if (value.contains("cloud") || value.contains("overcast")) return Kind.CLOUDY;
        if (value.contains("windy") || value.contains("breezy") || value.contains("gusty")) return Kind.WIND;
        if (value.contains("sunny") || value.contains("clear")) return Kind.CLEAR;
        return Kind.UNKNOWN;
    }

    static final class Hour {
        final long start, end;
        final double temperature;
        final Double rain;
        final String condition;
        final boolean day;
        Hour(long start, long end, double temperature, Double rain, String condition, boolean day) {
            this.start = start; this.end = end; this.temperature = temperature;
            this.rain = rain != null && Double.isFinite(rain) && rain >= 0 && rain <= 100 ? rain : null;
            this.condition = condition; this.day = day;
        }
    }

    static final class Series {
        final List<Hour> hours;
        final double low, high;
        Series(List<Hour> input, long dayStart, long dayEnd, long now) {
            TreeMap<Long, Hour> ordered = new TreeMap<>();
            for (Hour hour : input) if (hour.end > hour.start && hour.end > now && hour.end > dayStart
                    && hour.start < dayEnd && Double.isFinite(hour.temperature)
                    && hour.temperature >= -150 && hour.temperature <= 150 && !ordered.containsKey(hour.start))
                ordered.put(hour.start, hour);
            hours = Collections.unmodifiableList(new ArrayList<>(ordered.values()));
            double min = Double.POSITIVE_INFINITY, max = Double.NEGATIVE_INFINITY;
            for (Hour hour : hours) { min = Math.min(min, hour.temperature); max = Math.max(max, hour.temperature); }
            if (hours.isEmpty()) { low = 0; high = 10; }
            else if (max-min < 1) { low = min-5; high = max+5; }
            else { low = Math.floor((min-2)/5)*5; high = Math.ceil((max+2)/5)*5; }
        }
        double x(int index) {
            if (hours.size() < 2) return .5;
            return (double)(hours.get(index).start-hours.get(0).start)
                    / (hours.get(hours.size()-1).start-hours.get(0).start);
        }
        double y(int index) { return (hours.get(index).temperature-low)/(high-low); }
        boolean connected(int index) { return index > 0 && hours.get(index-1).end == hours.get(index).start; }
    }
}
