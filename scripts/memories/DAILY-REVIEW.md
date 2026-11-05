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
The review uses its own hidden, reusable task so an external bridge launch cannot
be reduced to bringing the app chooser's existing task forward. Back still returns
to that chooser; opt-ins and timing are refreshed whenever review resumes.
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
