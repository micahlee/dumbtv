"""Synthetic-only model boundary, cache, source preservation and TV integration tests."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/memories"))
import calendar_dedup as dedup
import daily_review as review

BASE = 1794168000000


def event(key, title, minutes=60, location=""):
    return dict(key=key, title=title, start=BASE, end=BASE+minutes*60000,
                location=location, allDay=False, busyOnly=False, color="#336699", transparent=False)


def calendar(*events):
    return {"sources": [{"key": "source-"+str(i), "label": "Calendar "+str(i), "events": [e],
                          "fetchedAt": BASE, "error": ""} for i, e in enumerate(events)]}


CONFIG = {"enabled": True, "model": "synthetic-light", "command": ["synthetic-classifier"]}


def same(config, pairs):
    return {p["id"]: {"choice": "same", "confidence": .99} for p in pairs}


class CalendarDedupTest(unittest.TestCase):
    def project(self, data, response=same, config=None):
        with tempfile.TemporaryDirectory() as folder, patch.object(dedup, "classify", side_effect=response):
            return dedup.project(data, config or CONFIG, Path(folder)/"cache.json", now=BASE/1000)

    def test_variant_meeting_and_game_durations_keep_originals_and_all_source_badges(self):
        for a, b in [(event("a", "Community meeting"), event("b", "November Community Meeting", 120)),
                     (event("a", "Alex vs City"), event("b", "12B vs City Royals", 75))]:
            data = calendar(a, b)
            before = copy.deepcopy(data)
            result = self.project(data)
            self.assertEqual(data, before)
            self.assertEqual(result["rawSources"], before["sources"])
            x, y = [s["events"][0] for s in result["sources"]]
            self.assertEqual((x["key"], x["title"], x["start"], x["end"], x["location"]),
                             (y["key"], y["title"], y["start"], y["end"], y["location"]))
            self.assertEqual(x["end"], b["end"])
            self.assertIn("Source times differ:", x["location"])
            self.assertEqual(result["dedup"]["groups"], 1)
            self.assertEqual([s["label"] for s in result["sources"]], ["Calendar 0", "Calendar 1"])

    def test_model_confidence_uncertainty_and_failure_never_hide_events(self):
        data = calendar(event("a", "Community meeting"), event("b", "Monthly community meeting", 120))
        for choice, confidence in [("same", .79), ("uncertain", 1), ("different", 1)]:
            def response(config, pairs):
                return {p["id"]: {"choice": choice, "confidence": confidence} for p in pairs}
            self.assertEqual(self.project(data, response)["sources"], data["sources"])
        def failure(*args): raise RuntimeError("provider unavailable")
        result = self.project(data, failure)
        self.assertEqual(result["sources"], data["sources"])
        self.assertEqual(result["dedup"]["state"], "unavailable")

    def test_same_time_distinct_people_games_venues_busy_and_all_day_are_preserved(self):
        data = calendar(event("a", "Alex dental"), event("b", "Jordan dental", 75))
        def different(config, pairs):
            return {p["id"]: {"choice": "different", "confidence": .99} for p in pairs}
        self.assertEqual(self.project(data, different)["sources"], data["sources"])
        for changed in [dict(busyOnly=True), dict(allDay=True),
                        dict(start=BASE+10*60000), dict(end=BASE+180*60000)]:
            a, b = event("a", "Game", location="Main rink"), event("b", "Game copy", 75)
            b.update(changed)
            result = self.project(calendar(a, b))
            self.assertEqual(result["dedup"]["candidates"], 0)
        data = calendar(event("a", "Community meeting"), event("b", "Community meeting copy", 75))
        data["sources"][1]["key"] = data["sources"][0]["key"]
        self.assertEqual(self.project(data)["dedup"]["candidates"], 0)

    def test_ambiguous_transitive_bridge_is_not_merged(self):
        data = calendar(event("a", "Alex haircut"), event("b", "Haircut", 75), event("c", "Jordan haircut", 90))
        def response(config, pairs):
            return {p["id"]: {"choice": "different" if all("haircut" != e["title"].lower() for e in p["events"]) else "same", "confidence": .99} for p in pairs}
        self.assertEqual(self.project(data, response)["sources"], data["sources"])

    def test_exact_copies_bridge_to_one_variant_without_modeling_exact_pair(self):
        data = calendar(event("a", "Community meeting"), event("b", "Community meeting"), event("c", "Monthly community meeting", 75))
        result = self.project(data)
        self.assertEqual(result["dedup"]["groups"], 1)
        self.assertEqual(result["dedup"]["modelPairs"], 2)

    def test_unchanged_negative_and_positive_decisions_cached_and_changes_invalidate(self):
        for choice in ["same", "different", "uncertain"]:
            def response(config, pairs): return {p["id"]: {"choice": choice, "confidence": .99} for p in pairs}
            with tempfile.TemporaryDirectory() as folder, patch.object(dedup, "classify", side_effect=response) as model:
                path = Path(folder)/"cache.json"
                data = calendar(event("a", "Community meeting"), event("b", "Monthly community meeting", 75))
                first = dedup.project(data, CONFIG, path, BASE/1000)
                self.assertEqual(model.call_count, 1)
                self.assertEqual(dedup.project(first, CONFIG, path, BASE/1000)["dedup"]["modelPairs"], 0)
                self.assertEqual(model.call_count, 1)
                data["sources"].reverse()
                dedup.project(data, CONFIG, path, BASE/1000)
                self.assertEqual(model.call_count, 1)
                data["sources"][1]["events"][0]["end"] += 60000
                dedup.project(data, CONFIG, path, BASE/1000)
                self.assertEqual(model.call_count, 2)
                dedup.project(data, dict(CONFIG, context="explicit alias"), path, BASE/1000)
                self.assertEqual(model.call_count, 3)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_model_backoff_and_changed_input_does_not_reuse_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(dedup, "classify", side_effect=RuntimeError()) as model:
            path = Path(folder)/"cache.json"
            data = calendar(event("a", "Community meeting"), event("b", "Monthly community meeting", 75))
            dedup.project(data, CONFIG, path, BASE/1000)
            dedup.project(data, CONFIG, path, BASE/1000+100)
            self.assertEqual(model.call_count, 1)
            dedup.project(data, CONFIG, path, BASE/1000+3601)
            self.assertEqual(model.call_count, 2)

    def test_disabled_or_unavailable_sources_restore_original_projection(self):
        data = calendar(event("a", "Community meeting"), event("b", "Monthly community meeting", 75))
        grouped = self.project(data)
        self.assertEqual(self.project(grouped, config={"enabled": False})["sources"], data["sources"])
        for unavailable in [dict(data, error="refresh failed"),
                            {"sources": [dict(s, error="saved") for s in data["sources"]]}]:
            self.assertEqual(self.project(unavailable)["sources"], data["sources"] if "error" in unavailable else unavailable["sources"])

    def test_subprocess_strict_schema_rejects_unknown_duplicate_missing_and_invalid_confidence(self):
        pairs = [{"id": "a", "events": []}, {"id": "b", "events": []}]
        for decisions in [[], [{"id": "z", "choice": "same", "confidence": 1}]*2,
                          [{"id": "a", "choice": "same", "confidence": 1}]*2,
                          [{"id": "a", "choice": "same", "confidence": True}, {"id": "b", "choice": "same", "confidence": 1}],
                          [{"id": "a", "choice": "same", "confidence": float("nan")}, {"id": "b", "choice": "same", "confidence": 1}]]:
            command = [sys.executable, "-c", "import json; print("+repr(json.dumps({"decisions": decisions}))+ ")"]
            with self.assertRaises(ValueError): dedup.classify(dict(CONFIG, command=command), pairs)
        self.assertEqual(dedup.classify(dict(CONFIG, command=[sys.executable, "-c", 'print(\'{"decisions": []}\')']), []), {})

    def test_fallback_uses_raw_source_events_after_failed_refresh(self):
        old = self.project(calendar(event("a", "Community meeting"), event("b", "Monthly community meeting", 75)))
        # Calendar identity is hashed exactly as the real provider boundary.
        old["rawSources"][0]["key"] = review.hashlib.sha256(b"fixture-calendar").hexdigest()[:24]
        old["sources"][0]["key"] = old["rawSources"][0]["key"]
        with patch.object(review, "pages", side_effect=[[{"id": "fixture-calendar", "summary": "Family", "accessRole": "reader"}], RuntimeError()]):
            result = review.calendars({"gws": "fixture"}, old, review.dt.datetime.fromtimestamp(BASE/1000, review.UTC))
        self.assertEqual(result["sources"][0]["events"], old["rawSources"][0]["events"])

    def test_generic_names_need_acquired_evidence_before_merging(self):
        for a, b in [("Appointment", "Appointment"), ("Meeting", "November meeting"),
                     ("Game", "Game"), ("Weekly practice", "Practice")]:
            data = calendar(event("a", a), event("b", b, 75))
            result = self.project(data)
            self.assertEqual(result["dedup"]["candidates"], 1)
            self.assertEqual(result["sources"], data["sources"])

    def test_source_evidence_can_resolve_venue_conflict_and_invalidates_on_change(self):
        data = calendar(event("a", "Alex game", location="North rink"), event("b", "12B vs City", 75, location="South rink"))
        evidence = json.dumps([{"id": "read-1", "query": "{fixture}", "digest": "fixture-digest", "executionComplete": True}, {"id": "failed-read", "query": "{badExploration}", "digest": "failed-digest", "executionComplete": False}])
        def response(config, pairs):
            return {p["id"]: {"choice": "same", "confidence": .99, "evidence": ["read-1"], "sourceEvidenceJSON": evidence} for p in pairs}
        with tempfile.TemporaryDirectory() as folder, patch.object(dedup, "classify", side_effect=response) as model:
            path = Path(folder)/"cache.json"
            first = dedup.project(data, CONFIG, path, BASE/1000)
            self.assertEqual(first["dedup"]["groups"], 1)
            location = first["sources"][0]["events"][0]["location"]
            self.assertIn("Source venues differ: North rink / South rink", location)
            with patch.object(dedup, "run_agent", return_value={"current": True}) as verifier:
                dedup.project(data, CONFIG, path, BASE/1000)
                refs = json.loads(verifier.call_args.args[1]["sourceEvidenceJSON"])
                self.assertEqual(len(refs), 1)
                self.assertEqual(refs[0]["query"], "{fixture}")
                self.assertTrue(all(r["executionComplete"] for r in refs))
            self.assertEqual(model.call_count, 1)
            with patch.object(dedup, "run_agent", return_value={"current": False}):
                dedup.project(data, CONFIG, path, BASE/1000)
            self.assertEqual(model.call_count, 2)

    def test_candidate_budget_never_partially_groups_snapshot(self):
        data = calendar(event("a", "Community meeting"), event("b", "Community meeting copy", 75),
                        event("c", "Monthly community meeting", 90))
        with patch.object(dedup, "MAX_PAIRS", 1):
            result = self.project(data)
        self.assertEqual(result["sources"], data["sources"])
        self.assertEqual(result["dedup"]["state"], "unavailable")

    def test_stale_source_and_duplicate_source_component_cannot_hide_events(self):
        data = calendar(event("a", "Community meeting"), event("b", "Community meeting copy", 75))
        data["sources"][0]["fetchedAt"] -= 3*3600000
        result = self.project(data)
        self.assertEqual(result["dedup"]["candidates"], 0)
        self.assertEqual(result["sources"], data["sources"])
        data = calendar(event("a", "Community meeting"), event("b", "Community meeting copy", 75),
                        event("c", "Monthly community meeting", 90))
        data["sources"][2]["key"] = data["sources"][0]["key"]
        self.assertEqual(self.project(data)["sources"], data["sources"])

    def test_projection_runs_through_actual_tv_grouping(self):
        home = os.environ.get("JAVA_HOME")
        javac = str(Path(home)/"bin/javac") if home else shutil.which("javac")
        java = str(Path(home)/"bin/java") if home else shutil.which("java")
        if not javac or not java or subprocess.run([javac, "-version"], capture_output=True).returncode:
            self.skipTest("JDK required for actual TV grouping integration")
        data = self.project(calendar(event("a", "Community meeting"), event("b", "November community meeting", 120)))
        lines = ["package tv.dumbtv.home; import java.util.*; public class ProjectedReviewTest { public static void main(String[] args) { List<ReviewEvents.Event> input = new ArrayList<>();"]
        for source in data["sources"]:
            for e in source["events"]:
                values = [json.dumps(e["key"]), str(e["start"])+"L", str(e["end"])+"L", "false", "false",
                          json.dumps(e["title"]), json.dumps(e["location"]), json.dumps(source["key"]),
                          json.dumps(source["label"]), json.dumps(e["color"])]
                lines.append("input.add(new ReviewEvents.Event("+",".join(values)+"));")
        lines.append('List<ReviewEvents.Event> output = ReviewEvents.combine(input); if (output.size()!=1 || output.get(0).sources.size()!=2 || !output.get(0).location.contains("Source times differ:")) throw new AssertionError("projection did not group with provenance"); }}')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"ProjectedReviewTest.java"
            path.write_text("\n".join(lines))
            subprocess.run([javac, "--release", "8", "-d", folder,
                            str(ROOT/"launcher/src/tv/dumbtv/home/ReviewEvents.java"), str(path)], check=True, capture_output=True)
            subprocess.run([java, "-cp", folder, "tv.dumbtv.home.ProjectedReviewTest"], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
