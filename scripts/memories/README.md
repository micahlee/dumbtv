# Offline photo memories

This opt-in addition to the launcher displays locally cached photos as an Android
DreamService. The launcher still has no network or storage permission on Fire OS 7.
It reads only its own `files/memories/` directory. The feature is off unless
`memories.enabled=on` is set in `home.conf` and its service is selected as the system
screensaver. Options then includes **Preview photo memories**.

Photos taken on today's month and day in earlier years take priority. If none are
cached, photos within three calendar days are used, then other cached memories.
Fallback captions show the actual photo date instead of claiming “On this day.”
The TV reselects on every slide, including across midnight. Images fit without
cropping and change every 15 seconds; a clock and capture year/date are overlaid.

## Mac refresh owner

`sync.py` reads a local OneDrive photo mirror. It does not receive Microsoft tokens,
publish photos, or modify the OneDrive originals. Its filename-date prefilter avoids
downloading an entire cloud library. `image.swift` uses macOS ImageIO to prefer the
actual EXIF capture date, respect orientation, and produce JPEGs up to 1920 pixels
on the long edge. GPS and camera metadata are omitted from the TV copies. Photos
without dated filenames are skipped in this initial version.

The default cache covers today and seven upcoming days, with at most 240 photos
and 128 MiB per active generation. The prior generation is retained for safe
transition. Every file is copied before an atomic photo-index replacement; a failed
copy, unavailable OneDrive folder, or empty refresh preserves the previous TV index.
The refresh never wakes a sleeping TV. An hourly launch agent can retry while the
TV is on. The TV plays its own cache even if the Mac is unavailable.

Use a dedicated private JSON configuration (mode 0600) with these keys:

```json
{
  "owner_host": "the-exact-hostname-of-the-refresh-Mac",
  "sources": ["/absolute/path/to/OneDrive/Photos/Camera Roll"],
  "state_dir": "/absolute/path/to/private/cache",
  "image_helper": "/absolute/path/to/memory-image",
  "adb": "/absolute/path/to/adb",
  "device": "TV_HOST:5555"
}
```

Do not commit this configuration, photo indexes, photos, ADB keys, or job logs.
The hostname check prevents accidentally moving the job to a different Mac.
Compile the helper with `swiftc scripts/memories/image.swift -o memory-image`.
Run `python3 scripts/memories/sync.py --config CONFIG --dry-run` first;
`--prepare-only` creates the Mac cache without contacting the TV.

Before installing on a real TV or deploying the refresh job, fetch `origin/main`,
verify the clean checkout equals that ref, and create fresh artifacts from it.
Keep the flag off until the cache is ready. Restore the original Android screensaver
settings and stop the refresh job to undo this feature; no Amazon package needs to
be disabled. Preserve the existing screen-off and sleep timeouts unless the owner
chooses different power behavior.

## Checks

`MemoryDatesTest.java` covers prior-year selection, nearby and offline fallbacks,
New Year wraparound, leap days, and malformed or unsafe index entries.
Run it with the same host JDK as the other launcher tests. `tests/test_memory_sync.py`
covers date prefiltering and failure before atomic index activation.
Real-device acceptance must also check automatic idle entry, exit, Home behavior,
and that the scheduled owner is the intended Mac. Do not infer every-frame ad
elimination or streaming-playback compatibility from a window-focus check.
