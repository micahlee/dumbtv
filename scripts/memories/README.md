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
The refresh never wakes a sleeping TV. The native **TV Memories** login-session
app owns a loopback-only ADB server on port 5038 and an hourly refresh, with quiet
retries while the TV is unavailable. Its app identity provides macOS's normal
Local Network consent flow; no privacy databases or protections are changed.
The TV plays its own cache even if the Mac is unavailable.

### People and places, rather than utility images

Set `suitable_only` to `true` to require local Apple Vision analysis for **both**
photo streams. The mini detects person/face presence and broad scenery/place
categories, and rejects documents, handwritten notes, screenshots, text-heavy
images and uncertain/object-only images. It does not identify people. No face
embeddings, names or recognized text strings are saved or sent to another service.
OneDrive originals are never changed.

Versioned decisions are cached against each source's path, size and modification
time. Legacy converted pictures without a decision are rechecked before reuse;
missing or failed analysis never counts as approval. A fully analyzed empty
collection may clear the managed TV collection, leaving a plain home/clock.
An unavailable source, interrupted analysis or failed copy preserves the last
valid collection. Classification is conservative and uncertain pictures are skipped.

When enabling this on an existing unfiltered installation, pause the owner and
hide/park the old photo display until the curated collection has been published.
The publish step removes obsolete generated wallpapers; it preserves user-added
wallpapers. The slideshow activates only the newly curated index.

### Recent photos behind the app chooser

Set `recent_days` to `7` in the Mac configuration to also prepare photos taken
today or during the preceding six days. This uses the actual recent date, rather
than the anniversary filter used by the idle slideshow. EXIF capture dates
override dated filenames. The initial version skips photos without dated filenames.
Up to 30 recent pictures (64 MiB) are prepared, with a separate two-minute budget.
They are fitted onto a 1920×1080 black canvas so portraits remain uncropped.
Only generated `recent_*.jpg` files in the launcher's own `files/wallpapers/`
directory are managed; user-added wallpapers are preserved.

Choose `background=image`, `rotate=minute`, and, for readable tiles, `dim=60` in
`home.conf`. The launcher changes the wallpaper every minute while home is visible.
The last collection remains available if a refresh fails or finds no recent photos.
Disable rotation or choose a solid background to undo it.

### Full-frame soft background

Set `frame_fill` to `"blur"` in the Mac configuration for a complete 1920×1080
frame in both streams. The original photo stays sharp, centered and aspect-fitted
with all its edges intact. A separately scaled, blurred and darkened copy fills
the space behind it. Only this decorative backdrop is cropped. No surroundings
are invented, and no photo is sent to an image-generation service.

The mini pre-renders the JPEG, so the TV still decodes just one image per slide.
People/place filtering runs on the original thumbnail before composition.
Versioned render keys force existing black-border copies to be regenerated under
new filenames; the ordinary complete-file/atomic-index publication rules apply.
Set `frame_fill` back to `"black"` and refresh to restore the previous presentation.
The default is `"black"` for existing configurations.

For smooth gradients in the slideshow, set `memories.color=full` in the TV's
`home.conf`. This opts into ARGB_8888 decoding instead of the default compact
RGB_565. A 1920×1080 image uses about 8 MiB rather than 4 MiB; only the current
slide and its replacement are decoded, and blurring still happens on the Mac.
Compact decoding was observed to create visible bands in otherwise smooth JPEG
backgrounds. Set `memories.color=compact` to restore the smaller color buffer.
Home wallpapers already use full-color decoding.

Use a dedicated private JSON configuration (mode 0600) with these keys:

```json
{
  "owner_host": "the-exact-hostname-of-the-refresh-Mac",
  "sources": ["/absolute/path/to/OneDrive/Photos/Camera Roll"],
  "state_dir": "/absolute/path/to/private/cache",
  "image_helper": "/absolute/path/to/memory-image",
  "adb": "/absolute/path/to/adb",
  "adb_port": 5038,
  "suitable_only": true,
  "frame_fill": "blur",
  "device": "TV_HOST:5555"
}
```

Do not commit this configuration, photo indexes, photos, ADB keys, or job logs.
The hostname check prevents accidentally moving the job to a different Mac.
Build installable Mac artifacts with `scripts/memories/build-mac.sh OUTPUT`.
The script fetches and enforces clean `origin/main` before building. The app's
menu provides refresh status, **Refresh now**, and **Quit until next login**.
macOS can request both Local Network permission and permission to read
OneDrive-managed files for this native app; these are separate normal prompts.
For a fixed-address TV, the owning LaunchAgent may set `ADB_MDNS=0` in its
`EnvironmentVariables` to avoid unnecessary discovery. This also avoids a
reproduced ADB 37 discovery-parser crash on one Mac/LAN; direct authenticated
TCP connections still work. See [ADB's discovery switch](https://android.googlesource.com/platform/packages/modules/adb/+/45c08c5130b7f5f8787c0c226e72eb0d3a7f7f45/client/main.cpp).
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
