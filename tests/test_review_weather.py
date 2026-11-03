"""Native weather meanings and chart math, with no device, live weather or personal data."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReviewWeatherTest(unittest.TestCase):
    def test_forecast_symbols_and_temperature_series(self):
        home = os.environ.get("JAVA_HOME")
        javac = str(Path(home)/"bin/javac") if home else shutil.which("javac")
        java = str(Path(home)/"bin/java") if home else shutil.which("java")
        if not javac or not java:
            self.skipTest("JDK required for native weather regression")
        if not home and subprocess.run([javac, "-version"], capture_output=True, timeout=10).returncode:
            self.skipTest("JDK unavailable (the macOS Java launcher may only be a stub)")
        with tempfile.TemporaryDirectory() as output:
            subprocess.run([javac, "--release", "8", "-d", output,
                            str(ROOT/"launcher/src/tv/dumbtv/home/ReviewWeather.java"),
                            str(ROOT/"launcher/tests/ReviewWeatherTest.java")],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run([java, "-cp", output, "tv.dumbtv.home.ReviewWeatherTest"],
                                    check=True, capture_output=True, text=True, timeout=10)
            self.assertIn("ReviewWeatherTest passed", result.stdout)
