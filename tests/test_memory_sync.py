"""Date prefiltering and failed-transfer safety; no real devices or personal photos."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("memory_sync", Path(__file__).resolve().parents[1] / "scripts/memories/sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class MemorySyncTest(unittest.TestCase):
    def test_filename_dates_are_validated(self):
        self.assertEqual(sync.filename_date("2020-11-02 09-15-22.heic"), dt.date(2020, 11, 2))
        self.assertEqual(sync.filename_date("IMG_20200229_1234.jpg"), dt.date(2020, 2, 29))
        self.assertIsNone(sync.filename_date("IMG_20210229.jpg"))
        self.assertIsNone(sync.filename_date("IMG_1234.jpg"))

    def test_rollover_and_current_year_exclusion(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("2020-12-31.jpg", "2026-12-31.jpg", "2026-01-01.jpg", "IMG_1234.jpg"):
                (root / name).write_bytes(b"fixture")
            chosen, undated = sync.candidates([root], dt.date(2026, 12, 31), days_ahead=1)
            self.assertEqual({p.name for _, p, _ in chosen}, {"2020-12-31.jpg", "2026-01-01.jpg"})
            self.assertEqual(undated, 1)

    def test_failure_never_activates_or_prunes_an_incomplete_generation(self):
        class FakeADB:
            def __init__(self): self.calls = []
            def call(self, *args, **kwargs):
                self.calls.append(args)
                if args[0] == "push": raise RuntimeError("simulated failed image push")
                return ""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "2020-11-02_0123456789abcdef.jpg"
            path.write_bytes(b"fixture")
            adb = FakeADB()
            with self.assertRaises(RuntimeError): sync.publish(adb, [path], Path(d) / "index.txt")
            commands = [args[1] for args in adb.calls if args[0] == "shell"]
            self.assertFalse(any("index.txt.next " in c or "rm -f" in c for c in commands))

    def test_missing_source_and_empty_index_preserve_previous_cache(self):
        with self.assertRaises(RuntimeError): sync.candidates(["/not/a/photo/source"], dt.date.today())
        with self.assertRaises(RuntimeError): sync.publish(None, [], None)

    def test_recent_photos_use_actual_seven_day_window(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("2026-11-02.jpg", "2026-10-27.heic", "2026-10-26.jpg",
                         "2025-11-02.jpg", "2026-11-03.jpg", "IMG_1234.jpg"):
                (root / name).write_bytes(b"fixture")
            selected = sync.recent_candidates([root], dt.date(2026, 11, 2))
            self.assertEqual([p.name for _, p in selected], ["2026-11-02.jpg", "2026-10-27.heic"])

    def test_failed_wallpaper_transfer_keeps_existing_collection(self):
        class FakeADB:
            def __init__(self): self.calls = []
            def call(self, *args, **kwargs):
                self.calls.append(args)
                if args[0] == "push": raise RuntimeError("simulated failed push")
                return "recent_fedcba9876543210.jpg\npersonal.jpg"
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "recent_0123456789abcdef.jpg"
            path.write_bytes(b"fixture")
            adb = FakeADB()
            with self.assertRaises(RuntimeError): sync.publish_wallpapers(adb, [path])
            self.assertFalse(any("rm -f" in str(c) for c in adb.calls))

    def test_wallpaper_cleanup_preserves_user_added_pictures(self):
        class FakeADB:
            def __init__(self): self.calls = []
            def call(self, *args, **kwargs):
                self.calls.append(args)
                return "recent_fedcba9876543210.jpg\npersonal.jpg" if args[0] == "shell" and args[1].startswith("ls ") else ""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "recent_0123456789abcdef.jpg"
            path.write_bytes(b"fixture")
            adb = FakeADB()
            sync.publish_wallpapers(adb, [path])
            removes = [c[1] for c in adb.calls if c[0] == "shell" and c[1].startswith("rm -f")]
            self.assertEqual(removes, ["rm -f " + sync.WALLPAPER_REMOTE + "/recent_fedcba9876543210.jpg"])


class PhotoCurationTest(unittest.TestCase):
    def result(self, **changes):
        metrics = dict(version=1, faces=0, people=0, textBlocks=0,
                       sceneScore=0.0, documentScore=0.0, textCoverage=0.0)
        metrics.update(changes)
        return {"curation": metrics}

    def test_people_and_places_are_kept_but_utility_and_uncertain_images_are_not(self):
        for metrics, eligible in [(dict(people=1), True), (dict(faces=1, textBlocks=2, textCoverage=0.02), True),
                                  (dict(sceneScore=0.8), True), (dict(documentScore=0.9, faces=1), False),
                                  (dict(documentScore=0.2, textBlocks=14, textCoverage=0.05), False),
                                  (dict(textBlocks=10, textCoverage=0.2, sceneScore=0.6), False),
                                  (dict(sceneScore=0.1), False)]:
            with self.subTest(metrics=metrics):
                self.assertEqual(sync.curation_record(self.result(**metrics))["eligible"], eligible)

    def test_missing_and_invalid_analysis_cannot_prove_eligibility(self):
        for data in [{}, self.result(version=0), self.result(sceneScore=float("nan")), self.result(people=-1)]:
            with self.assertRaises(RuntimeError): sync.curation_record(data)

    def helper(self, args, **kwargs):
        Path(args[2]).write_bytes(b"converted fixture")
        data = {"taken": None}
        if "--curate" in args:
            data.update(self.result(documentScore=0.95))
        return subprocess.CompletedProcess(args, 0, json.dumps(data), "")

    def test_legacy_wallpaper_cache_is_rechecked_and_rejected_results_are_cached(self):
        with tempfile.TemporaryDirectory() as d, patch.object(sync.subprocess, "run", side_effect=self.helper) as helper:
            root = Path(d); source = root / "source"; source.mkdir(); state = root / "state"; state.mkdir()
            (source / "2026-11-02.jpg").write_bytes(b"source fixture")
            config = dict(sources=[str(source)], image_helper="fixture-helper", recent_days=7)
            frames, _ = sync.prepare_wallpapers(config, state, dt.date(2026, 11, 2))
            self.assertEqual(len(frames), 1)
            config["suitable_only"] = True
            frames, stats = sync.prepare_wallpapers(config, state, dt.date(2026, 11, 2))
            self.assertEqual(frames, []); self.assertEqual(stats["rejected"], 1)
            self.assertEqual(list((state / "wallpapers").glob("*.jpg")), [])
            self.assertIn("--curate", helper.call_args.args[0])
            calls = helper.call_count
            sync.prepare_wallpapers(config, state, dt.date(2026, 11, 2))
            self.assertEqual(helper.call_count, calls)

    def test_legacy_anniversary_cache_cannot_bypass_filter(self):
        with tempfile.TemporaryDirectory() as d, patch.object(sync.subprocess, "run", side_effect=self.helper):
            root = Path(d); source = root / "source"; source.mkdir(); state = root / "state"
            (source / ("2000-" + dt.date.today().strftime("%m-%d") + ".jpg")).write_bytes(b"source fixture")
            config = dict(owner_host=socket.gethostname(), sources=[str(source)], state_dir=str(state),
                          image_helper="fixture-helper", days_ahead=0)
            self.assertEqual(sync.refresh(config, prepare_only=True)["photos"], 1)
            config["suitable_only"] = True
            result = sync.refresh(config, prepare_only=True)
            self.assertEqual(result["photos"], 0); self.assertEqual(result["photosRejected"], 1)

    def test_empty_curated_wallpapers_remove_generated_files_only(self):
        class FakeADB:
            def __init__(self): self.calls = []
            def call(self, *args, **kwargs):
                self.calls.append(args)
                return "recent_0123456789abcdef.jpg\npersonal.jpg" if args[0] == "shell" and args[1].startswith("ls ") else ""
        adb = FakeADB(); sync.publish_wallpapers(adb, [])
        self.assertEqual(adb.calls, [])
        sync.publish_wallpapers(adb, [], clear_empty=True)
        removes = [c[1] for c in adb.calls if c[0] == "shell" and c[1].startswith("rm -f")]
        self.assertEqual(removes, ["rm -f " + sync.WALLPAPER_REMOTE + "/recent_0123456789abcdef.jpg"])

    def test_empty_curated_index_requires_explicit_opt_in(self):
        class FakeADB:
            def call(self, *args, **kwargs): return ""
        with tempfile.TemporaryDirectory() as d:
            index = Path(d) / "index.txt"
            with self.assertRaises(RuntimeError): sync.publish(FakeADB(), [], index)
            sync.publish(FakeADB(), [], index, allow_empty=True)
            self.assertEqual(index.read_text(), "")


if __name__ == "__main__": unittest.main()
