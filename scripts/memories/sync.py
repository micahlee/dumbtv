#!/usr/bin/env python3
"""Refresh an offline TV photo cache from a local OneDrive mirror. No cloud credentials."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

REMOTE = "/sdcard/Android/data/tv.dumbtv.home/files/memories"
NAME = re.compile(r"(?:19|20)\d\d-\d\d-\d\d_[0-9a-f]{16}\.jpg\Z")
DATE = re.compile(r"((?:19|20)\d{2})[-_]?([01]\d)[-_]?([0-3]\d)")
EXTENSIONS = {".jpg", ".jpeg", ".heic", ".heif", ".png"}


def filename_date(name):
    match = DATE.search(name)
    if not match:
        return None
    try:
        return dt.date(*(int(x) for x in match.groups()))
    except ValueError:
        return None


def candidates(sources, today, days_ahead=7, per_day=40, limit=240):
    """Filename dates are a cheap prefilter; ImageIO capture dates override them later."""
    dates = [today + dt.timedelta(days=i) for i in range(days_ahead + 1)]
    buckets = [[] for _ in dates]
    undated = 0
    for root in sources:
        root = Path(root).expanduser()
        if not root.is_dir():
            raise RuntimeError("OneDrive photo folder is unavailable; preserving the TV cache")
        errors = []
        for directory, dirs, files in os.walk(root, onerror=errors.append):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for name in files:
                if Path(name).suffix.lower() not in EXTENSIONS:
                    continue
                taken = filename_date(name)
                if taken is None:
                    undated += 1
                    continue
                for i, date in enumerate(dates):
                    if (taken.month, taken.day) == (date.month, date.day) and taken.year < date.year:
                        path = Path(directory) / name
                        key = hashlib.sha256(str(path).encode()).hexdigest()
                        buckets[i].append((key, path, taken))
                        break
        if errors:
            raise RuntimeError("OneDrive photo enumeration was incomplete; preserving the TV cache")
    selected = []
    for i, bucket in enumerate(buckets):
        # Give today more variety; use deterministic hashes to avoid grouping by year/folder.
        selected.extend(sorted(bucket)[:max(per_day, 80) if i == 0 else per_day])
    return selected[:limit], undated


class ADB:
    def __init__(self, executable, device, port=5038):
        self.arguments, self.device = [executable, "-P", str(port)], device

    def call(self, *args, timeout=30):
        result = subprocess.run(self.arguments + ["-s", self.device, *args],
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            if "unauthorized" in result.stderr.lower():
                raise RuntimeError("TV requires authorization for this Mac")
            raise RuntimeError("TV transfer failed; keeping its previous photo index")
        return result.stdout.strip()

    def connect(self):
        host, port = self.device.rsplit(":", 1)
        try:
            with socket.create_connection((host, int(port)), timeout=3):
                pass
        except OSError:
            return False  # Never wake a sleeping TV merely to refresh its photos.
        result = subprocess.run(self.arguments + ["connect", self.device],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise RuntimeError("Could not connect to the TV")
        self.call("get-state")
        return True


def publish(adb, frames, index_path):
    """Every new image must exist before the atomic index replacement. No prune on failure."""
    names = [p.name for p in frames]
    if not names or any(not NAME.fullmatch(n) for n in names):
        raise RuntimeError("Refusing an empty or invalid photo index")
    adb.call("shell", "mkdir -p " + REMOTE)
    listing = adb.call("shell", "ls -1 " + REMOTE).splitlines()
    old_index = adb.call("shell", "cat " + REMOTE + "/index.txt 2>/dev/null || true").splitlines()
    existing = set(listing)
    for photo in frames:
        if photo.name not in existing:
            adb.call("push", str(photo), REMOTE + "/" + photo.name + ".part", timeout=60)
            adb.call("shell", "mv " + REMOTE + "/" + photo.name + ".part " + REMOTE + "/" + photo.name)
    index_path.write_text("\n".join(names) + "\n")
    adb.call("push", str(index_path), REMOTE + "/index.txt.next")
    adb.call("shell", "mv " + REMOTE + "/index.txt.next " + REMOTE + "/index.txt")
    # Retain the prior generation too, so a running slideshow can finish its current read.
    retain = set(names) | {n for n in old_index if NAME.fullmatch(n)}
    obsolete = [n for n in listing if NAME.fullmatch(n) and n not in retain]
    if obsolete:
        adb.call("shell", "rm -f " + " ".join(REMOTE + "/" + n for n in obsolete))
    return retain


def refresh(config, prepare_only=False, dry_run=False, limit=None):
    if socket.gethostname() != config["owner_host"]:
        raise RuntimeError("This refresh is configured for a different Mac")
    today = dt.date.today()
    selected, undated = candidates(config["sources"], today,
                                   config.get("days_ahead", 7), config.get("per_day", 40),
                                   limit or config.get("max_photos", 240))
    if dry_run:
        return {"selected": len(selected), "undatedSkipped": undated, "date": str(today)}
    state = Path(config["state_dir"]).expanduser()
    state.mkdir(parents=True, exist_ok=True)
    with (state / "refresh.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "already_running"}
        cache = state / "frames"
        cache.mkdir(exist_ok=True)
        metadata_file = state / "metadata.json"
        metadata = json.loads(metadata_file.read_text()) if metadata_file.exists() else {}
        allowed = {(d.month, d.day) for d in
                   (today + dt.timedelta(days=i) for i in range(config.get("days_ahead", 7) + 1))}
        frames, used, failures = [], 0, 0
        deadline = time.monotonic() + config.get("budget_seconds", 480)
        for _, path, named_date in selected:
            if time.monotonic() > deadline:
                break
            info = path.stat()
            key = hashlib.sha256((str(path) + ":" + str(info.st_size) + ":"
                                  + str(info.st_mtime_ns)).encode()).hexdigest()[:16]
            record = metadata.get(key, {})
            filename = record.get("file", "")
            photo = cache / filename
            if not NAME.fullmatch(filename) or not photo.is_file():
                temp = cache / (key + ".part.jpg")
                try:
                    result = subprocess.run([config["image_helper"], str(path), str(temp)],
                                            capture_output=True, text=True, timeout=60)
                    if result.returncode:
                        raise RuntimeError("Image conversion failed")
                    data = json.loads(result.stdout)
                    taken = dt.date.fromisoformat(data["taken"]) if data.get("taken") else named_date
                    if (taken.month, taken.day) not in allowed or taken >= today:
                        continue
                    filename = str(taken) + "_" + key + ".jpg"
                    photo = cache / filename
                    temp.replace(photo)
                    metadata[key] = {"file": filename,
                                     "dateSource": "EXIF" if data.get("taken") else "filename"}
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                    failures += 1
                    continue
                finally:
                    temp.unlink(missing_ok=True)
            size = photo.stat().st_size
            if used + size > config.get("max_bytes", 134217728):
                break
            used += size
            frames.append(photo)
        metadata_tmp = state / "metadata.json.next"
        metadata_tmp.write_text(json.dumps(metadata, sort_keys=True))
        metadata_tmp.replace(metadata_file)
        if not frames:
            raise RuntimeError("No eligible photos were prepared; preserving the TV cache")
        status = {"date": str(today), "photos": len(frames), "bytes": used,
                  "conversionFailures": failures, "undatedSkipped": undated}
        if prepare_only:
            status["status"] = "prepared"
        else:
            adb = ADB(config["adb"], config["device"], config.get("adb_port", 5038))
            if not adb.connect():
                status["status"] = "tv_offline"
            else:
                retain = publish(adb, frames, state / "index.txt")
                for old in cache.iterdir():
                    if NAME.fullmatch(old.name) and old.name not in retain:
                        old.unlink()
                status["status"] = "published"
        (state / "status.json").write_text(json.dumps(status, indent=2) + "\n")
        return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    os.umask(0o077)
    config = json.loads(Path(args.config).expanduser().read_text())
    try:
        print(json.dumps(refresh(config, args.prepare_only, args.dry_run, args.limit)))
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        # No source photo names, credentials or device addresses in normal logs.
        reason = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print(json.dumps({"status": "failed", "error": reason}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
