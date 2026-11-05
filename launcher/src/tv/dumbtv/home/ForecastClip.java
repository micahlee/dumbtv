package tv.dumbtv.home;

import java.io.File;

/** Pure validation for the Mini's bounded, immutable local forecast manifest. */
final class ForecastClip {
    static final long MAX_BYTES = 96L * 1024 * 1024, MAX_AGE = 12L * 3600000;
    final File file;
    final String title;
    final long published, expires;
    ForecastClip(File file, String title, long published, long expires) {
        this.file = file; this.title = title; this.published = published; this.expires = expires;
    }
    static boolean valid(String file, String source, String title, long published, long expires,
                         long now, long duration, long size) {
        return file != null && file.matches("forecast_[0-9a-f]{64}\\.mp4")
                && "WYFF".equals(source) && title != null && !title.trim().isEmpty() && title.length() <= 200
                && published > 0 && published <= now + 300000 && now < expires
                && expires > published && expires - published <= MAX_AGE && now - published <= MAX_AGE
                && duration >= 10 && duration <= 600 && size > 0 && size <= MAX_BYTES;
    }
}
