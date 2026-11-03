"""Synthetic provider boundaries: calendar completeness, privacy, DST and cache safety."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("daily_review", ROOT / "scripts/memories/daily_review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
ZONE = ZoneInfo("America/New_York")
NOW = dt.datetime(2026, 11, 3, 12, tzinfo=dt.timezone.utc)
SOURCE = {"label": "Family", "color": "#336699"}


class DailyReviewTest(unittest.TestCase):
    def test_exclusive_all_day_end_spans_dst_without_losing_an_hour(self):
        start, end = review.boundaries(dt.datetime(2026, 11, 1, 12, tzinfo=dt.timezone.utc), ZONE, 1)
        self.assertEqual((end.timestamp()-start.timestamp())/3600, 25)
        event = review.event_record({"id": "fixture", "summary": "On call", "start": {"date": "2026-11-01"},
                                     "end": {"date": "2026-11-02"}}, ZONE, SOURCE)
        self.assertEqual(event["end"]-event["start"], 25*3600000)

    def test_cancellations_declines_timezone_and_recurrence_instances(self):
        event = {"id": "fixture", "iCalUID": "recurring-fixture", "summary": "Practice", "description": "private",
                 "start": {"dateTime": "2026-11-03T18:00:00-05:00"}, "end": {"dateTime": "2026-11-03T19:00:00-05:00"}}
        first = review.event_record(event, ZONE, SOURCE)
        self.assertNotIn("description", first)
        self.assertEqual(review.event_record(dict(event, status="cancelled"), ZONE, SOURCE), None)
        self.assertIsNone(review.event_record(dict(event, attendees=[{"self": True, "responseStatus": "declined"}]), ZONE, SOURCE))
        following = dict(event, start={"dateTime": "2026-11-04T18:00:00-05:00"}, end={"dateTime": "2026-11-04T19:00:00-05:00"})
        self.assertNotEqual(first["key"], review.event_record(following, ZONE, SOURCE)["key"])
        self.assertEqual(first["key"], review.event_record(dict(event, id="calendar-copy"), ZONE, SOURCE)["key"])
        with self.assertRaises(ValueError):
            review.event_record(dict(event, start={"dateTime": "2026-11-03T18:00:00"}), ZONE, SOURCE)

    def test_freebusy_merges_overlaps_and_rejects_missing_calendars_or_errors(self):
        intervals = [{"start": "2026-11-03T09:00:00-05:00", "end": "2026-11-03T10:00:00-05:00"},
                     {"start": "2026-11-03T09:30:00-05:00", "end": "2026-11-03T11:00:00-05:00"}]
        data = {"calendars": {"fixture-work": {"busy": intervals}}}
        result = review.busy_records(data, "fixture-work", SOURCE)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Busy")
        self.assertEqual(result[0]["end"]-result[0]["start"], 2*3600000)
        self.assertEqual(review.busy_records({"calendars": {"fixture-work": {"busy": []}}}, "fixture-work", SOURCE), [])
        for bad in ({}, {"calendars": {"fixture-work": {"busy": [], "errors": [{"reason": "notFound"}]}}}):
            with self.assertRaises(RuntimeError): review.busy_records(bad, "fixture-work", SOURCE)

    def test_pagination_does_not_turn_an_incomplete_feed_into_success(self):
        with patch.object(review, "gws", side_effect=[{"items": [1], "nextPageToken": "a"}, {"items": [2]}]):
            self.assertEqual(review.pages("fixture", "events", {}), [1, 2])
        with patch.object(review, "gws", return_value={"items": [1], "nextPageToken": "repeat"}):
            with self.assertRaises(RuntimeError): review.pages("fixture", "events", {})

    def test_partial_calendar_failure_keeps_only_its_previous_events_and_age(self):
        config = {"gws": "fixture-gws"}
        calendars = [{"id": "family", "summary": "Family", "accessRole": "reader"},
                     {"id": "work", "accessRole": "freeBusyReader"}]
        key = review.hashlib.sha256(b"work").hexdigest()[:24]
        old = {"sources": [{"key": key, "events": [{"title": "Busy"}], "fetchedAt": 123}]}
        def page(binary, resource, params):
            return calendars if resource == "calendarList" else []
        with patch.object(review, "pages", side_effect=page), patch.object(review, "gws", side_effect=RuntimeError("denied")):
            data = review.calendars(config, old, NOW)
        self.assertEqual(data["sources"][0]["events"], [])
        self.assertEqual(data["sources"][0]["error"], "")
        self.assertEqual(data["sources"][1]["events"], [{"title": "Busy"}])
        self.assertEqual(data["sources"][1]["fetchedAt"], 123)
        self.assertNotIn("id", data["sources"][1])

    def test_credentials_failure_does_not_erase_calendar_or_refresh_its_age(self):
        with tempfile.TemporaryDirectory() as folder:
            config = dict(owner_host=socket.gethostname(), state_dir=folder, daily_review={"gws": "fixture"})
            path = Path(folder)/"review/review.json"
            old = {"calendar": {"checkedAt": 123, "sources": [{"label": "Family", "events": []}]},
                   "weather": {"fetchedAt": 456, "daily": [{"condition": "Clear"}]}}
            review.private_json(path, old)
            with patch.object(review, "calendars", side_effect=RuntimeError("access")), patch.object(review, "weather", side_effect=RuntimeError("offline")):
                result = review.refresh(config, prepare_only=True, now=NOW)
            data = json.loads(path.read_text())
            self.assertEqual(data["calendar"]["checkedAt"], 123)
            self.assertEqual(data["weather"]["fetchedAt"], 456)
            self.assertTrue(result["weatherNeedsAttention"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_transfer_never_switches_the_active_tv_snapshot(self):
        class FakeADB:
            calls = []
            def __init__(self, *args): pass
            def connect(self): return True
            def call(self, *args):
                self.calls.append(args)
                if args[0] == "push": raise RuntimeError("failed push")
        class FakeSync:
            ADB = FakeADB
        with tempfile.TemporaryDirectory() as folder:
            owner = dict(owner_host=socket.gethostname(), state_dir=folder, adb="fixture", device="fixture",
                         daily_review={"gws": "fixture", "weather": {}})
            with patch.object(review, "calendars", return_value={"sources": []}), patch.object(review, "weather", return_value={}), patch.dict(sys.modules, {"sync": FakeSync}):
                with self.assertRaises(RuntimeError): review.refresh(owner, now=NOW)
            self.assertFalse(any("mv " in str(call) for call in FakeADB.calls))

    def test_weather_rejects_unrelated_hosts_and_forecasts_that_do_not_cover_now(self):
        with self.assertRaises(ValueError): review.fetch("https://example.invalid/weather")
        point = {"forecast": "daily", "forecastHourly": "hourly"}
        period = {"startTime": "2026-11-02T01:00:00-05:00", "endTime": "2026-11-02T02:00:00-05:00",
                  "temperature": 60, "temperatureUnit": "F", "isDaytime": False, "shortForecast": "Clear"}
        with patch.object(review, "fetch", side_effect=[point, {"periods": [period]}, {"periods": [period]}]):
            with self.assertRaises(RuntimeError): review.weather({"latitude": 0, "longitude": 0}, NOW)
