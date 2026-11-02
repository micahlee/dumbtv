package tv.dumbtv.home;

import java.util.ArrayList;
import java.util.Calendar;
import java.util.GregorianCalendar;
import java.util.List;

/** Date selection is independent of Android and uses capture dates, never upload dates. */
final class MemoryDates {
    static final class Photo {
        final String file;
        final int year, month, day;
        Photo(String file, int year, int month, int day) {
            this.file = file; this.year = year; this.month = month; this.day = day;
        }
    }

    static Photo parse(String line) {
        if (!line.matches("(?:19|20)[0-9]{2}-[0-9]{2}-[0-9]{2}_[0-9a-f]{16}\\.jpg")) return null;
        int year = Integer.parseInt(line.substring(0, 4));
        int month = Integer.parseInt(line.substring(5, 7));
        int day = Integer.parseInt(line.substring(8, 10));
        Calendar c = new GregorianCalendar();
        c.clear(); c.setLenient(false); c.set(year, month - 1, day);
        try { c.getTimeInMillis(); } catch (IllegalArgumentException e) { return null; }
        return new Photo(line, year, month, day);
    }

    static boolean onThisDay(Photo p, Calendar today) {
        return p.year < today.get(Calendar.YEAR) && p.month == today.get(Calendar.MONTH) + 1
                && p.day == today.get(Calendar.DAY_OF_MONTH);
    }

    private static int ordinal(int month, int day) {
        Calendar c = new GregorianCalendar(2000, month - 1, day);
        return c.get(Calendar.DAY_OF_YEAR);
    }

    static List<Photo> choose(List<Photo> all, Calendar today) {
        List<Photo> exact = new ArrayList<>(), nearby = new ArrayList<>(), older = new ArrayList<>();
        int now = ordinal(today.get(Calendar.MONTH) + 1, today.get(Calendar.DAY_OF_MONTH));
        for (Photo p : all) {
            if (p.year >= today.get(Calendar.YEAR)) continue;
            older.add(p);
            if (onThisDay(p, today)) exact.add(p);
            int delta = Math.abs(now - ordinal(p.month, p.day));
            if (Math.min(delta, 366 - delta) <= 3) nearby.add(p);
        }
        return !exact.isEmpty() ? exact : !nearby.isEmpty() ? nearby : older;
    }
}
