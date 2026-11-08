# Daily Review

An opt-in native tile in the existing launcher, with no Android network or
calendar permission. It shows today's weather, an hourly forecast sidebar,
and a full-height composite agenda for today. There is no day-navigation bar.
The header is a single compact line and event rows put times beside titles to
fit more of the day at a glance. An overflowing agenda scrolls automatically at
14 density-independent pixels per second, pauses five seconds at each end, then
reverses. It stays still when the full day fits. Remote or touch input pauses the
motion for ten seconds; ordinary manual scrolling still works. Motion stops when
Daily Review leaves the foreground and restarts with a reading pause on return.
Its visible window keeps the screen awake while the dashboard is being read.
Leaving Daily Review restores ordinary TV idle/screensaver behavior; no global
idle or sleep timeout is changed.
Source labels and colors distinguish family, subscribed sports, on-call,
personal and work inputs.
The calendar's display titles are preserved. Free/busy-only calendars use the
FreeBusy API and never invent meeting titles. Work busy intervals appear in the
agenda alongside other events. There is no separate work-availability strip;
the weather sidebar gives that space to the hourly chart.

### Brief photo interludes

Set `review.photos=on` in the existing TV `home.conf` after preparing a collage
cache on the Mini. While Daily Review is visible it shows the dashboard for three
minutes, then its own offline photo view for 45 seconds (three 15-second collage
slides), and returns automatically. It never starts the system screensaver or
wakes the TV on a timer. Missing/unreadable collage photos return to the dashboard.
The photo view uses the same curated cache as the idle slideshow; a shuffled deck
avoids repeating a page until the available collection has been shown.

A navigation-button press during photos returns immediately to Daily Review and
consumes that press, so Back does not also exit the dashboard. Holding a key does
not cause a second action. Volume continues to work; Home/power retain their
system behavior. Any normal interaction restarts the reading interval. Leaving
the Activity cancels the cycle and photo decoder; returning starts on the review.
The external bridge sends Home a fixed review request with a short UI deadline
bounded by the original execution deadline. Home opens the normal tile path only while
resumed/focused, opted in and unexpired; leaving Home cancels a pending request.
Back still returns to the chooser. Opt-ins and timing refresh when review resumes.
Weather/calendar refreshes received during photos appear when review returns.

`review.photo_interval_seconds` (default `180`, range `15`–`3600`) and
`review.photo_duration_seconds` (default `45`, range `5`–`180`) are optional private
configuration values. Turning `review.photos=off` restores continuous review.
The feature is off by default and also requires `memories.enabled=on`.

Weather uses local vector icons for clear sun/moon, partly cloudy, cloudy, rain,
thunderstorms, snow, ice/mix, fog and wind. The original forecast text remains
visible; unknown conditions use an unknown symbol. The remaining hourly forecast
is a native temperature line chart with numeric temperatures, time labels,
condition icons and precipitation-probability bars. Left/right while the chart
is focused inspects each hour's exact temperature, condition and precipitation
chance. The calendar keeps its full height and width. Actual elapsed time sets
horizontal spacing; missing intervals break the line rather than interpolating.
Unknown precipitation is displayed as unknown, not zero. Flat, single-point and
unavailable forecasts have explicit safe display behavior. No image downloads,
chart libraries, new permissions or Mini/provider changes are needed.

## Mini configuration

Build/install only fresh, clean, fetched `origin/main`, as for the existing
TV Memories helper. `build-mac.sh` also copies `daily_review.py`. The native app
binary and macOS consent identity do not change. Add a `daily_review` object to
the Mini's private existing `config.json`:

```json
{
  "daily_review": {
    "enabled": true,
    "gws": "/absolute/path/to/your/existing/gws-wrapper",
    "timezone": "America/New_York",
    "calendar_labels": {},
    "exclude_calendars": [],
    "weather": {"latitude": 0, "longitude": 0, "label": "Your chosen location"}
  }
}
```

Use the host's existing authenticated CLI/guard, never exported tokens or a
credential-store workaround. macOS may require the user's normal local Keychain
approval. A failed read preserves the previous source's events and original
successful refresh time. Other sources can still update. Missing permissions,
partial pagination, an API error and an empty successful feed are distinct.

The existing **TV Photos → Refresh now** action and hourly owner loop update both
features. Review runs before and independently of OneDrive photo enumeration.
Routine refresh never wakes the TV. When the TV is asleep the existing owner
retries later; the on-TV review remains cached. This version has no Axon
notification, scheduled wake or phone action.

Add `review.enabled=on` to the TV's existing `home.conf`; optionally put
`daily-review` in `apps.order`. Normal hide, rename and move work for this built-in
tile. It has no separate package or App info action. Back returns to the chooser;
Home uses the existing guard. The Activity can later be explicitly launched as
`tv.dumbtv.home/.DailyReview`; it ignores external payloads and reads only its
local opt-in cache.

## Data and failure behavior

- Google Calendar supplies every accessible, non-deleted calendar from the
  calendar list unless explicitly excluded. This includes subscriptions such as
  Crossbar; their upstream publication delay is controlled by Google/the feed.
- Recurring instances are expanded, cancelled and self-declined events omitted,
  all-day exclusive end dates and timezone/DST boundaries retained. The cache
  covers seven days so today's view can roll over at midnight without a new fetch.
- Display grouping combines matching iCalendar instances and independently
  copied events across calendars when normalized titles, start/end and all-day
  status match. Matching ignores case and extra whitespace. Venue conflicts,
  different times and distinct events within the same calendar stay separate.
  A missing venue is filled from the matching copy; ambiguous matches remain
  separate. Busy-only/untitled entries do not use title matching. All originating
  calendar labels are retained, without rewriting any calendar or cached event.
- The TV cache contains only bounded display titles, locations, times, calendar
  display labels/colors and source freshness. No credentials, descriptions,
  structured conference metadata, attendee identities or raw calendar IDs are transferred.
- NWS point, daily and hourly forecasts are fetched as a complete pair. The
  current temperature is explicitly a **forecast**, not a station observation.
  High/low fields remain blank when the provider no longer supplies that period.
  Source issue times are stored separately from check time. Missing hourly
  coverage and stale/failed inputs are visible rather than fabricated.
- Cache publication is an atomic rename after a successful ADB push. A failed
  transfer leaves the active TV snapshot intact. Local files are private; the
  Android app uses its own external-files directory as the existing photo cache
  does. A bounded parser retains its last valid snapshot if a file is malformed.
- Disable just this feature by setting `review.enabled=off` on the TV and
  `daily_review.enabled=false` on the Mini. Other launcher and photo settings
  remain independent. Deleting this feature's `review/` cache is optional.

Provider contracts:
[Google event listing](https://developers.google.com/workspace/calendar/api/v3/reference/events/list),
[Google FreeBusy](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query),
[NWS weather API](https://www.weather.gov/documentation/services-web-api).

### Optional lightweight calendar deduplication

The Mini can ask a lightweight model about independently authored copies whose
titles or durations differ. This is opt-in under `daily_review.dedup`:

```json
{
  "enabled": true,
  "model": "your-installed-light-model",
  "command": ["/absolute/path/to/python3", "/absolute/path/to/classifier.py"],
  "context": "Optional explicit team, person or venue aliases confirmed by the owner."
}
```

The command reads one bounded JSON object on stdin: `version`, `model`,
`instructions`, `context` and `pairs` (each has `id` and two `events`). It returns
`{"decisions":[{"id":"pair-id","choice":"same","confidence":0.99}]}`.
Allowed choices are `same`, `different`, and `uncertain`. IDs must cover every
submitted pair exactly once; confidence must be finite and between zero and one.
The model sees display titles, calendar labels, local times and locations only.
Descriptions, attendees, calendar IDs and credentials are never sent.

Candidates must be on different calendars, timed (not all-day/busy-only), overlap,
start within five minutes and end within 90 minutes. Conflicting structured venues
and generic titles such as “Appointment” or “November meeting” never reach the
model. Exact copies need no model call. At most 32 candidate pairs
are considered per refresh, and the command has a 60-second total budget. Only
`same` judgments with confidence at least 0.8 can group. Every pair in a group
must agree; transitive bridges, repeated source calendars and groups over eight
records remain separate. Confidence is a model score, not a correctness guarantee.

Successful judgments, including negative/uncertain answers, are cached privately
by complete event identity/content, configured model/command/context and prompt
version. Unchanged facts make no additional calls. A changed event invalidates
its judgments immediately. Failed classifications keep separate rows and back off
for one hour. Partial/invalid responses are discarded, never partially applied.
Unavailable or stale source records do not participate. Bump `VERSION` when
changing classifier semantics so old decisions cannot survive a policy change.

Complete originals remain in `calendar.rawSources`. The legacy TV display fields
in `calendar.sources` receive a shared group key, the shortest original title,
the complete time span and all original source badges. When source intervals
differ, the metadata says **Source times differ** and lists those intervals.
Refresh fallback always uses the originals. Disabling deduplication restores the
raw projection. No source calendar is edited and no TV APK update is needed.
`review/status.json` records the model, candidate/group counts and availability.

For an existing Axon installation, `axon_dedup.py` is an optional adapter:

```text
python3 axon_dedup.py --axon /absolute/path/to/axon --home /private/axon/home
```

It defaults to the existing `tv-daily-review` caller Service and
`intelligence-openai` provider; either can be selected with `--caller-service`
and `--provider`. Its model must be explicitly configured from the installed
provider catalog. The caller's ServiceAccount needs only
`service:intelligence-openai:decide`; the adapter discovers its current Process
and uses the supported CLI. Provider/model pins, typed choices and stable call
idempotency keys preserve attribution and prevent blind resubmission after an
uncertain acknowledgment. API keys remain with the existing provider. Pair facts
use short local IDs in the model input so each typed question has unambiguous
evidence. Local judgments retain the original opaque cache IDs.

`tests/evaluate_calendar_dedup.py --model MODEL --command COMMAND...` explicitly
runs the model against the maintained synthetic positive/negative corpus and
reports false merges and missed duplicates through the same candidate/confidence
policy. It is not part of offline tests and never reads personal calendars.

### WYFF video rotation (opt-in)

Enable `weather_video: {"enabled": true}` in the private Mini configuration and
`review.weather_video=on` in TV `home.conf`. The loop becomes:

1. Daily Review: three minutes, with remote input restarting its reading interval.
2. Slideshow: 45 seconds, using the existing shared no-repeat page deck.
3. Latest fresh WYFF forecast: the full clip, always starting muted.
4. Slideshow: another 45 seconds, continuing that same deck.
5. Return to Daily Review and repeat.

OK/Enter or clicking the video's sound control toggles its own audio. It never
changes system volume. Back/other navigation returns to Daily Review and consumes
the press; Home/power remain system-owned and volume controls remain available.
Leaving the activity, losing the video surface, decode failure or the bounded
watchdog releases the player. Audio focus loss remutes; a new clip always starts
muted and never restores sound automatically. Missing/stale clips are skipped.
When the weather opt-in is off, the original review/photos/review loop is retained.

The Mini reads WYFF's dedicated weather lead and its matching videocast article,
not the mixed YouTube upload feed. It selects a complete H.264 MP4 up to 720p,
10–600 seconds and 96 MiB. It verifies bounded HTTPS responses and transfer hashes
before atomically publishing an immutable filename and small manifest. Clips
expire 12 hours after the video's original creation time; refreshing metadata does
not extend expiry. No credentials or network permission are added to the TV.
The existing native owner checks for a newer forecast at startup and every hour,
independently of OneDrive photo processing. An unchanged clip is reused. Sleeping TVs are
never woken for routine refresh. Offline playback uses the last valid cache;
expired or failed media returns to the remaining loop. The station's page data
is not a documented API: format/source ambiguity retains the previous cache.
