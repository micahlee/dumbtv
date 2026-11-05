"""Check the page dissolve timing with a synthetic clock and no device."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PhotoTransitionTest(unittest.TestCase):
    def test_dissolve_is_bounded_monotonic_and_gentle(self):
        home = os.environ.get("JAVA_HOME")
        javac = str(Path(home) / "bin/javac") if home else shutil.which("javac")
        java = str(Path(home) / "bin/java") if home else shutil.which("java")
        if not javac or not java:
            self.skipTest("JDK required for photo transition regression")
        if not home and subprocess.run([javac, "-version"], capture_output=True, timeout=10).returncode:
            self.skipTest("JDK unavailable")
        with tempfile.TemporaryDirectory() as output:
            subprocess.run([javac, "--release", "8", "-d", output,
                            str(ROOT / "launcher/src/tv/dumbtv/home/PhotoTransition.java"),
                            str(ROOT / "launcher/tests/PhotoTransitionTest.java")],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run([java, "-cp", output, "tv.dumbtv.home.PhotoTransitionTest"],
                                    check=True, capture_output=True, text=True, timeout=10)
            self.assertIn("PhotoTransitionTest passed", result.stdout)
