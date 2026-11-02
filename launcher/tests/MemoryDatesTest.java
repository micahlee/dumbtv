package tv.dumbtv.home;
import java.util.Arrays;
import java.util.Calendar;
import java.util.GregorianCalendar;
import java.util.List;
public final class MemoryDatesTest {
    private static MemoryDates.Photo photo(String date) {
        MemoryDates.Photo p = MemoryDates.parse(date + "_0123456789abcdef.jpg");
        if (p == null) throw new AssertionError(date);
        return p;
    }
    public static void main(String[] args) {
        Calendar today = new GregorianCalendar(2026, Calendar.NOVEMBER, 2);
        MemoryDates.Photo exact = photo("2020-11-02"), other = photo("2021-11-01"), current = photo("2026-11-02");
        List<MemoryDates.Photo> chosen = MemoryDates.choose(Arrays.asList(other, current, exact), today);
        if (chosen.size() != 1 || chosen.get(0) != exact) throw new AssertionError("prior-year exact date must win");
        if (MemoryDates.choose(Arrays.asList(current), today).size() != 0) throw new AssertionError("exclude current year");
        if (MemoryDates.choose(Arrays.asList(other), today).get(0) != other) throw new AssertionError("nearby fallback");
        MemoryDates.Photo dec = photo("2019-12-31"), distant = photo("2020-06-01");
        chosen = MemoryDates.choose(Arrays.asList(dec, distant), new GregorianCalendar(2026, 0, 1));
        if (chosen.size() != 1 || chosen.get(0) != dec) throw new AssertionError("year-boundary nearby date");
        if (MemoryDates.choose(Arrays.asList(distant), today).get(0) != distant) throw new AssertionError("offline fallback");
        if (MemoryDates.parse("../2020-11-02_0123456789abcdef.jpg") != null
                || MemoryDates.parse("2021-02-29_0123456789abcdef.jpg") != null
                || MemoryDates.parse("2020-13-01_0123456789abcdef.jpg") != null) throw new AssertionError("invalid filename/date");
        if (MemoryDates.parse("2020-02-29_0123456789abcdef.jpg") == null) throw new AssertionError("leap day");
        System.out.println("MemoryDatesTest passed");
    }
}
