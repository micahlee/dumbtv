package tv.dumbtv.home;

import java.util.Arrays;
import java.util.Collections;

public final class ReviewWeatherTest {
    private static final long HOUR = 3600000;
    private static ReviewWeather.Hour hour(long hour, double temperature, Double rain) {
        return new ReviewWeather.Hour(hour*HOUR, (hour+1)*HOUR, temperature, rain, "Mostly Sunny", true);
    }
    private static void kind(String text, ReviewWeather.Kind expected) {
        if (ReviewWeather.kind(text) != expected) throw new AssertionError("Wrong symbol for " + text);
    }
    private static void near(double value, double expected) {
        if (Math.abs(value-expected) > .000001) throw new AssertionError(value + " != " + expected);
    }
    public static void main(String[] args) {
        kind("Sunny", ReviewWeather.Kind.CLEAR); kind("Clear", ReviewWeather.Kind.CLEAR);
        kind("Mostly Sunny", ReviewWeather.Kind.PARTLY_CLOUDY); kind("Partly Cloudy", ReviewWeather.Kind.PARTLY_CLOUDY);
        kind("Mostly Cloudy", ReviewWeather.Kind.CLOUDY); kind("Overcast", ReviewWeather.Kind.CLOUDY);
        kind("Chance Light Rain", ReviewWeather.Kind.RAIN); kind("Drizzle", ReviewWeather.Kind.RAIN);
        kind("Slight Chance Showers And Thunderstorms", ReviewWeather.Kind.STORM);
        kind("Snow Showers", ReviewWeather.Kind.SNOW); kind("Flurries", ReviewWeather.Kind.SNOW);
        kind("Rain And Snow", ReviewWeather.Kind.MIX); kind("Wintry Mix", ReviewWeather.Kind.MIX);
        kind("Freezing Rain", ReviewWeather.Kind.ICE); kind("Sleet", ReviewWeather.Kind.ICE);
        kind("Freezing Fog", ReviewWeather.Kind.FOG); kind("Haze", ReviewWeather.Kind.FOG);
        kind("Breezy", ReviewWeather.Kind.WIND); kind("Unavailable", ReviewWeather.Kind.UNKNOWN);

        ReviewWeather.Series trend = new ReviewWeather.Series(Arrays.asList(hour(3, 60, 30.0), hour(1, 50, null),
                hour(2, 75, 0.0)), 0, 24*HOUR, HOUR);
        if (trend.hours.size() != 3 || !trend.connected(1) || !trend.connected(2)) throw new AssertionError("time ordering");
        near(trend.x(0), 0); near(trend.x(1), .5); near(trend.x(2), 1);
        if (!(trend.y(1) > trend.y(2) && trend.y(2) > trend.y(0))) throw new AssertionError("warmth must plot higher");
        if (trend.hours.get(0).rain != null || trend.hours.get(1).rain == null) throw new AssertionError("unknown versus zero precipitation");

        ReviewWeather.Series gap = new ReviewWeather.Series(Arrays.asList(hour(1, 50, -1.0), hour(4, 60, Double.NaN),
                hour(5, 65, 101.0)), 0, 24*HOUR, HOUR);
        near(gap.x(1), .75);
        if (gap.connected(1) || !gap.connected(2)) throw new AssertionError("missing hours must not be interpolated");
        for (ReviewWeather.Hour hour : gap.hours) if (hour.rain != null) throw new AssertionError("invalid precipitation");

        ReviewWeather.Series flat = new ReviewWeather.Series(Arrays.asList(hour(1, 60, 5.0), hour(2, 60, 5.0)), 0, 24*HOUR, HOUR);
        near(flat.y(0), .5); near(flat.y(1), .5);
        ReviewWeather.Series one = new ReviewWeather.Series(Collections.singletonList(hour(23, 60, null)), 0, 24*HOUR, 23*HOUR);
        near(one.x(0), .5); near(one.y(0), .5);
        ReviewWeather.Series filtered = new ReviewWeather.Series(Arrays.asList(hour(0, 40, null), hour(1, 50, null),
                hour(2, Double.NaN, null), hour(24, 60, null), hour(3, 500, null)), 0, 24*HOUR, HOUR);
        if (filtered.hours.size() != 1) throw new AssertionError("expired, next-day or invalid data retained");
        ReviewWeather.Series empty = new ReviewWeather.Series(Collections.emptyList(), 0, 24*HOUR, HOUR);
        if (!empty.hours.isEmpty() || !(empty.high > empty.low)) throw new AssertionError("empty chart safety");
        System.out.println("ReviewWeatherTest passed: symbols, chronology, real time spacing, gaps, flat/single/empty series and unknown precipitation");
    }
}
