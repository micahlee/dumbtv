#!/usr/bin/env python3
"""Mini-owned, read-only Google Calendar/NWS projection. No credentials reach the TV."""
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unicodedata
import urllib.request
from zoneinfo import ZoneInfo

MAX_BYTES = 4 * 1024 * 1024
REMOTE = "/sdcard/Android/data/tv.dumbtv.home/files/review"
UTC = dt.timezone.utc


def text(value, limit=300):
    return "".join(c for c in str(value or "") if not unicodedata.category(c).startswith("C"))[:limit].strip()


def stamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def epoch(value):
    parsed = stamp(value)
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return int(parsed.timestamp() * 1000)


def private_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = json.dumps(data, ensure_ascii=False).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("projection_too_large")
    fd, name = tempfile.mkstemp(prefix=".review-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def gws(binary, resource, method, params=None, body=None):
    args = [binary, "calendar", resource, method]
    if params is not None:
        args += ["--params", json.dumps(params)]
    if body is not None:
        args += ["--json", json.dumps(body)]
    # Private temporary files bound stdout without keeping provider output in logs.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        child = subprocess.Popen(args, stdout=output, stderr=errors)
        try:
            import time
            deadline = time.monotonic() + 30
            while child.poll() is None:
                if output.tell() > MAX_BYTES or errors.tell() > 65536 or time.monotonic() > deadline:
                    raise RuntimeError("calendar_read_incomplete")
                time.sleep(.05)
            if child.returncode or output.tell() > MAX_BYTES:
                raise RuntimeError("calendar_access_needed")
            output.seek(0)
            data = json.load(output)
            if not isinstance(data, dict) or "error" in data:
                raise RuntimeError("calendar_read_incomplete")
            return data
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()


def pages(binary, resource, params):
    items, tokens = [], set()
    for _ in range(20):
        data = gws(binary, resource, "list", params)
        if not isinstance(data.get("items", []), list):
            raise ValueError("calendar_items_invalid")
        items.extend(data.get("items", []))
        if len(items) > 10000:
            raise ValueError("calendar_result_too_large")
        token = data.get("nextPageToken")
        if not token:
            return items
        if token in tokens:
            break
        tokens.add(token)
        params = dict(params, pageToken=token)
    raise RuntimeError("calendar_pagination_incomplete")


def boundaries(now, zone, days=7):
    start = dt.datetime.combine(now.astimezone(zone).date(), dt.time(), zone)
    return start, start + dt.timedelta(days=days)


def event_record(event, zone, source):
    if event.get("status") == "cancelled" or any(
            a.get("self") and a.get("responseStatus") == "declined" for a in event.get("attendees", [])):
        return None
    a, b = event["start"], event["end"]
    all_day = "date" in a
    if all_day:
        start = dt.datetime.combine(dt.date.fromisoformat(a["date"]), dt.time(), zone)
        end = dt.datetime.combine(dt.date.fromisoformat(b["date"]), dt.time(), zone)
        start_ms, end_ms = int(start.timestamp()*1000), int(end.timestamp()*1000)
    else:
        start_ms, end_ms = epoch(a["dateTime"]), epoch(b["dateTime"])
    if end_ms <= start_ms:
        raise ValueError("invalid_event_interval")
    identity = str(event.get("iCalUID") or event.get("id") or "") + ":" + str(start_ms)
    return {"key": hashlib.sha256(identity.encode()).hexdigest()[:24], "start": start_ms, "end": end_ms,
            "allDay": all_day, "title": text(event.get("summary")) or "Untitled event",
            "location": text(event.get("location"), 180), "source": source["label"],
            "color": source["color"], "busyOnly": False,
            "transparent": event.get("transparency") == "transparent"}


def busy_records(data, calendar_id, source):
    calendar = data.get("calendars", {}).get(calendar_id)
    if not isinstance(calendar, dict) or calendar.get("errors") or not isinstance(calendar.get("busy"), list):
        raise RuntimeError("work_availability_incomplete")
    intervals = sorted((epoch(x["start"]), epoch(x["end"])) for x in calendar["busy"])
    merged = []
    for a, b in intervals:
        if b <= a:
            raise ValueError("invalid_busy_interval")
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a, b])
    return [{"key": "busy-" + str(a), "start": a, "end": b, "allDay": False,
             "title": "Busy", "location": "", "source": source["label"], "color": source["color"],
             "busyOnly": True, "transparent": False} for a, b in merged]


def calendars(config, old, now):
    zone = ZoneInfo(config.get("timezone", "America/New_York"))
    start, end = boundaries(now, zone)
    binary = config["gws"]
    current = pages(binary, "calendarList", {"maxResults": 250,
                    "fields": "items(id,summary,summaryOverride,primary,accessRole,backgroundColor,deleted),nextPageToken"})
    sources = []
    for calendar in current:
        cid = calendar["id"]
        if calendar.get("deleted") or cid in config.get("exclude_calendars", []):
            continue
        key = hashlib.sha256(cid.encode()).hexdigest()[:24]
        busy = calendar.get("accessRole") == "freeBusyReader"
        label = config.get("calendar_labels", {}).get(cid) or (
            "Work" if busy else "Personal" if calendar.get("primary") else
            calendar.get("summaryOverride") or calendar.get("summary") or "Calendar")
        source = {"key": key, "label": text(label, 80), "color": calendar.get("backgroundColor", "#7fb7ff"),
                  "busyOnly": busy, "via": "Google Calendar"}
        previous = next((s for s in old.get("rawSources", old.get("sources", [])) if s.get("key") == key), {})
        try:
            if busy:
                data = gws(binary, "freebusy", "query", body={"timeMin": start.isoformat(),
                           "timeMax": end.isoformat(), "timeZone": str(zone), "items": [{"id": cid}]})
                records = busy_records(data, cid, source)
            else:
                raw = pages(binary, "events", {"calendarId": cid, "timeMin": start.isoformat(),
                            "timeMax": end.isoformat(), "singleEvents": True, "orderBy": "startTime",
                            "showDeleted": False, "maxResults": 2500,
                            "fields": "items(id,iCalUID,summary,start,end,status,location,transparency,attendees(self,responseStatus)),nextPageToken"})
                records = [record for event in raw if (record := event_record(event, zone, source))]
            source.update(events=records, fetchedAt=int(now.timestamp()*1000), error="")
        except (RuntimeError, ValueError, KeyError, TypeError, OSError):
            source.update(events=previous.get("events", []), fetchedAt=previous.get("fetchedAt", 0),
                          error="Refresh failed; showing saved events" if previous else "Calendar access needed")
        sources.append(source)
    if not sources:
        raise RuntimeError("calendar_list_empty")
    return {"start": int(start.timestamp()*1000), "end": int(end.timestamp()*1000),
            "sources": sources, "checkedAt": int(now.timestamp()*1000), "error": ""}


def fetch(url):
    if not url.startswith("https://api.weather.gov/"):
        raise ValueError("unexpected_weather_host")
    request = urllib.request.Request(url, headers={"User-Agent": "DumbTV-DailyReview (https://github.com/micahlee/dumbtv)",
                                                  "Accept": "application/geo+json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise ValueError("weather_result_too_large")
    return json.loads(raw)["properties"]


def weather(config, now):
    lat, lon = config["latitude"], config["longitude"]
    if not all(isinstance(n, (int, float)) and math.isfinite(n) for n in (lat, lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("weather_location_invalid")
    point = fetch("https://api.weather.gov/points/%.4f,%.4f" % (lat, lon))
    daily, hourly = fetch(point["forecast"]), fetch(point["forecastHourly"])
    def periods(data):
        rows = []
        for p in data["periods"]:
            a, b = epoch(p["startTime"]), epoch(p["endTime"])
            temperature = p["temperature"]
            if b <= a or not isinstance(temperature, (int, float)) or p.get("temperatureUnit") != "F":
                raise ValueError("forecast_invalid")
            pop = p.get("probabilityOfPrecipitation", {}).get("value")
            rows.append({"start": a, "end": b, "temperature": temperature, "day": bool(p["isDaytime"]),
                         "name": text(p.get("name"), 50), "condition": text(p["shortForecast"], 100),
                         "rain": pop if isinstance(pop, (int, float)) and 0 <= pop <= 100 else None,
                         "wind": text(p.get("windSpeed"), 40) + " " + text(p.get("windDirection"), 10)})
        return rows
    hours, days = periods(hourly), periods(daily)
    now_ms = int(now.timestamp()*1000)
    if not days or not hours or not any(p["start"] <= now_ms < p["end"] for p in hours):
        raise RuntimeError("forecast_does_not_cover_now")
    return {"label": text(config.get("label", "Local weather"), 80), "daily": days, "hourly": hours,
            "source": "National Weather Service", "dailyIssuedAt": epoch(daily["updateTime"]),
            "hourlyIssuedAt": epoch(hourly["updateTime"]), "fetchedAt": now_ms, "error": ""}


def refresh(owner, prepare_only=False, now=None):
    if socket.gethostname() != owner["owner_host"]:
        raise RuntimeError("wrong_refresh_host")
    config = owner["daily_review"]
    zone = ZoneInfo(config.get("timezone", "America/New_York"))
    now = now or dt.datetime.now(UTC)
    root = Path(owner["state_dir"]).expanduser() / "review"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "refresh.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "already_running"
        path = root / "review.json"
        old = json.loads(path.read_text()) if path.exists() else {}
        data = {"version": 1, "timezone": str(zone), "builtAt": int(now.timestamp()*1000)}
        try:
            data["calendar"] = calendars(config, old.get("calendar", {}), now)
        except (RuntimeError, ValueError, KeyError, TypeError, OSError):
            data["calendar"] = dict(old.get("calendar", {}), error="Calendar refresh unavailable; check the mini")
        from calendar_dedup import project
        data["calendar"] = project(data["calendar"], dict(config.get("dedup", {}),
                                    timezone=str(zone)), root / "dedup-decisions.json", now.timestamp())
        try:
            data["weather"] = weather(config["weather"], now)
        except (RuntimeError, ValueError, KeyError, TypeError, OSError):
            data["weather"] = dict(old.get("weather", {}), error="Weather refresh unavailable; showing saved forecast")
        private_json(path, data)
        status = {"preparedAt": data["builtAt"], "calendarSources": len(data["calendar"].get("sources", [])),
                  "calendarNeedsAttention": bool(data["calendar"].get("error")) or any(s.get("error") for s in data["calendar"].get("sources", [])),
                  "weatherNeedsAttention": bool(data["weather"].get("error")), "status": "prepared"}
        status["calendarDedup"] = data["calendar"].get("dedup", {"state": "disabled"})
        if not prepare_only:
            from sync import ADB
            adb = ADB(owner["adb"], owner.get("device", ""), owner.get("adb_port", 5038), owner.get("device_service"))
            if adb.connect():
                adb.call("shell", "mkdir -p " + REMOTE)
                adb.call("push", str(path), REMOTE + "/review.json.next")
                adb.call("shell", "mv " + REMOTE + "/review.json.next " + REMOTE + "/review.json")
                status["status"] = "published"
            else:
                status["status"] = "tv_offline"
        private_json(root / "status.json", status)
        return status
