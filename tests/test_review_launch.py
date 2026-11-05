"""Run the bounded Home entry regression with a synthetic clock and no device."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReviewLaunchTest(unittest.TestCase):
    def test_foreground_opt_in_expiry_single_use_and_cancellation(self):
        home = os.environ.get("JAVA_HOME")
        javac = str(Path(home) / "bin/javac") if home else shutil.which("javac")
        java = str(Path(home) / "bin/java") if home else shutil.which("java")
        if not javac or not java:
            self.skipTest("JDK required for native bounded Home entry regression")
        if not home and subprocess.run([javac, "-version"], capture_output=True, timeout=10).returncode:
            self.skipTest("JDK unavailable")
        with tempfile.TemporaryDirectory() as output:
            subprocess.run([javac, "--release", "8", "-d", output,
                            str(ROOT / "launcher/src/tv/dumbtv/home/ReviewLaunch.java"),
                            str(ROOT / "launcher/tests/ReviewLaunchTest.java")],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run([java, "-cp", output, "tv.dumbtv.home.ReviewLaunchTest"],
                                    check=True, capture_output=True, text=True, timeout=10)
            self.assertIn("ReviewLaunchTest passed", result.stdout)
