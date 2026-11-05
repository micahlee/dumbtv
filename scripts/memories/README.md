# Offline photo memories

The same Mini owner can optionally refresh the [Daily Review weather/calendar tile](DAILY-REVIEW.md).

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

### Collages and duplicate photos

Set `photo_collages` to `true` in the Mini configuration to build 1920×1080 JPEG
collages before transfer. This requires `suitable_only: true`. Existing people/
place filtering runs on each original first. The native `memory-collage` helper
then fingerprints eligible originals, removes exact files and normalized-pixel
copies, and conservatively matches re-encodes using aspect ratio, a difference
hash and a strict color-layout comparison. It does not broadly merge photos of
the same people or place. Heavily edited/cropped copies may remain distinct.
Fingerprints and source paths remain private on the Mini; only JPEG pages and
the safe slideshow index reach the TV.

Each distinct selected photo appears once per collection. Balanced pages contain
two to four photos; a leftover slot is never filled by repeating a photo. Each
photo stays complete over its own blurred fill, with its actual capture year
(or recent date) drawn on the Mini. Anniversary pages never mix different month/
days or label a mixed-year collage as a single year. A pool with fewer than two
unique eligible photos has no collage page; Daily Review stays on its dashboard
when there are no collage pages. The same processing applies to recent wallpapers.

Failed analysis/rendering never publishes a partial collage collection. Content-
addressed pages and fingerprint decisions are reused; successful refreshes bound
the working cache to current photos/pages and the published generation. The
originals are read-only. Disable `photo_collages` and refresh to restore individual
photos. The build script includes the helper and Python module, with no additional
runtime packages, online image service or new Microsoft sign-in.

Set `photo_source` to `"onedrive-api"` to read personal OneDrive directly through
Microsoft Graph. The Mini keeps a private metadata index using the paginated
drive delta API, then downloads only selected anniversary and recent photos into
its own bounded rendering cache. Capture dates come from the Graph **photo**
facet and remain authoritative during rendering; upload dates and source filenames are
not used to decide when a cloud photo was taken. Photos without a capture date
are skipped. Anniversary candidates use an equal daily pseudorandom ranking,
without orientation preference or year quotas. The ranking stays stable through
hourly refreshes and changes with the current date. The configured candidate cap
applies before people/place filtering, so the published count can be smaller;
rejected candidates are never displayed. The source never reads the synced
OneDrive directory or falls back to it.

Microsoft Graph PowerShell owns the read-only `Files.Read` sign-in, token refresh
and macOS Keychain cache on the Mini. No client registration or secret is needed.
Only API GET operations are used. Cloud originals are never modified. No tokens,
download URLs or source names are written into ordinary logs or copied to the TV.
An interrupted metadata page or download preserves the last TV collection. The
index binds to the original drive so switching Microsoft accounts requires review.
`image.swift` uses macOS ImageIO to respect orientation and render JPEGs, omitting
GPS and camera metadata from TV copies.

The legacy local-folder source remains available with `photo_source: "local"`
(the compatibility default) and `sources: ["/absolute/photo/folder"]`. Only that
mode uses dated filenames as a prefilter. An API failure never activates it.

The default cache covers today and seven upcoming days, with at most 240 photos
and 128 MiB per active generation. The prior generation is retained for safe
transition. Every file is copied before an atomic photo-index replacement; a failed
copy, unavailable photo source, or incomplete refresh preserves the previous TV index.
The refresh never wakes a sleeping TV. Cloud photos can be prepared while the TV
is unavailable; publication waits until it can be reached. The native **TV Memories** login-session
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
override dated filenames in legacy local mode. API mode retains the Graph capture
date even when embedded EXIF dates are malformed or disagree. Versioned render
keys recheck earlier cloud-cache entries made under the EXIF date policy.
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
  "photo_source": "onedrive-api",
  "onedrive": {
    "pwsh": "/absolute/path/to/pwsh",
    "budget_seconds": 600,
    "max_photo_bytes": 67108864,
    "max_cache_bytes": 1073741824
  },
  "state_dir": "/absolute/path/to/private/cache",
  "image_helper": "/absolute/path/to/memory-image",
  "adb": "/absolute/path/to/adb",
  "adb_port": 5038,
  "suitable_only": true,
  "frame_fill": "blur",
  "device": "TV_HOST:5555"
}
```

Install PowerShell from Microsoft's official distribution and install only the
`Microsoft.Graph.Authentication` module version `2.41.2` for the refresh account.
Sign in **inside the Mini's GUI login session**, using
`pwsh -NoLogo -NoProfile -File /absolute/path/to/graph.ps1 -SignIn`.
Review the personal-account read-only consent on Microsoft's displayed login page.
Explicit setup allows 15 minutes to complete sign-in. It uses the SDK's public
credential API with persistent storage and the normal personal-account token
profile. It does not use the higher-level connect path's temporary-storage fallback.
An SSH-only login can lack Keychain access even when the desktop is unlocked.
For a .NET-tool installation of PowerShell, set `onedrive.dotnet_root` to the
installed .NET runtime directory containing `dotnet`. The child process receives
both `DOTNET_ROOT` and this directory on its own `PATH`, so the tool shim works
with the minimal environment supplied to a GUI login agent.
Scheduled refreshes reuse that cache and fail quietly if sign-in is required;
they never display a browser or renew consent automatically. Graph's photo facet
does not provide the people/place classification needed here, so Apple Vision
continues to filter documents and other unsuitable images locally.

The first refresh enumerates photo metadata across the drive; subsequent runs
fetch changes. A failed page does not commit a partial index. Expired delta tokens
trigger a full rebuild. The default cloud-original cache is bounded to 1 GiB and
64 MiB per photo; only the selected originals are retained after a successful
preparation. The TV continues to use its existing smaller JPEG cache.

Do not commit this configuration, photo indexes, photos, ADB keys, or job logs.
The hostname check prevents accidentally moving the job to a different Mac.
Build installable Mac artifacts with `scripts/memories/build-mac.sh OUTPUT`.
The script fetches and enforces clean `origin/main` before building. The app's
menu provides refresh status, **Refresh now**, and **Quit until next login**.
macOS requests Local Network permission for this native app. The API source
does not require access to OneDrive-managed local files.
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
