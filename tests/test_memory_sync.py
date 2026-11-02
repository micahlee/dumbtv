"""Date prefiltering and failed-transfer safety; no real devices or personal photos."""
import datetime as dt
import importlib.util
from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__": unittest.main()
