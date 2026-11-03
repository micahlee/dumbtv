"""Run the actual Android-independent event grouping code against duplicate/conflict cases."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReviewEventGroupingTest(unittest.TestCase):
    def test_event_copies_and_distinct_appointments(self):
        home = os.environ.get("JAVA_HOME")
        javac = str(Path(home)/"bin/javac") if home else shutil.which("javac")
        java = str(Path(home)/"bin/java") if home else shutil.which("java")
        if not javac or not java:
            self.skipTest("JDK required for native event grouping regression")
        with tempfile.TemporaryDirectory() as output:
            subprocess.run([javac, "--release", "8", "-d", output,
                            str(ROOT/"launcher/src/tv/dumbtv/home/ReviewEvents.java"),
                            str(ROOT/"launcher/tests/ReviewEventsTest.java")], check=True, capture_output=True, timeout=30)
            result = subprocess.run([java, "-cp", output, "tv.dumbtv.home.ReviewEventsTest"],
                                    check=True, capture_output=True, text=True, timeout=10)
            self.assertIn("ReviewEventsTest passed", result.stdout)
