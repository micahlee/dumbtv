"""Check the page dissolve timing with a synthetic clock and no device."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReviewRotationTest(unittest.TestCase):
    def test_four_phase_loop_skip_watchdog_remote_and_manifest_bounds(self):
        home = os.environ.get("JAVA_HOME")
        javac = str(Path(home) / "bin/javac") if home else shutil.which("javac")
        java = str(Path(home) / "bin/java") if home else shutil.which("java")
        if not javac or not java:
            self.skipTest("JDK required for photo transition regression")
        if not home and subprocess.run([javac, "-version"], capture_output=True, timeout=10).returncode:
            self.skipTest("JDK unavailable")
        with tempfile.TemporaryDirectory() as output:
            subprocess.run([javac, "--release", "8", "-d", output,
                            str(ROOT / "launcher/src/tv/dumbtv/home/ReviewRotation.java"),
                            str(ROOT / "launcher/src/tv/dumbtv/home/ForecastClip.java"),
                            str(ROOT / "launcher/tests/ReviewRotationTest.java")],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run([java, "-cp", output, "tv.dumbtv.home.ReviewRotationTest"],
                                    check=True, capture_output=True, text=True, timeout=10)
            self.assertIn("ReviewRotationTest passed", result.stdout)
