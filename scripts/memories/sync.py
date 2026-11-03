#!/usr/bin/env python3
"""Refresh an offline TV photo cache from a local OneDrive mirror. No cloud credentials."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import math
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
WALLPAPER = re.compile(r"recent_[0-9a-f]{16}\.jpg\Z")
WALLPAPER_REMOTE = "/sdcard/Android/data/tv.dumbtv.home/files/wallpapers"
CURATION_VERSION = 1
BLUR_RENDER_VERSION = "blur-16x9-v1"


def frame_fill(config):
    value = config.get("frame_fill", "black")
    if value not in ("black", "blur"):
        raise RuntimeError("Unknown photo frame fill")
    return value


def image_cache_key(source, config):
    info = source.stat()
    material = str(source) + ":" + str(info.st_size) + ":" + str(info.st_mtime_ns)
    if frame_fill(config) == "blur":
        material += ":" + BLUR_RENDER_VERSION
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def image_arguments(config, source, target, wallpaper=False):
    arguments = [config["image_helper"], str(source), str(target)]
    if wallpaper:
        arguments.append("--wallpaper")
    if config.get("suitable_only", False):
        arguments.append("--curate")
    if frame_fill(config) == "blur":
        arguments.append("--blur-fill")
    return arguments


def frame_record(data, config):
    style = frame_fill(config)
    if style == "blur" and (data.get("frameFill") != "blur" or data.get("width") != 1920
                            or data.get("height") != 1080):
        raise RuntimeError("Photo frame rendering is incomplete")
    return {"frameFill": style, "sourceWidth": data.get("sourceWidth"),
            "sourceHeight": data.get("sourceHeight")}


def curation_record(data):
    """Conservative people/place selection. Missing analysis is never eligibility proof."""
    metrics = data.get("curation", {})
    if not isinstance(metrics, dict) or metrics.get("version") != CURATION_VERSION:
        raise RuntimeError("Photo eligibility analysis is missing")
    for field in ["faces", "people", "textBlocks"]:
        if type(metrics.get(field)) is not int or metrics[field] < 0:
            raise RuntimeError("Photo eligibility analysis is invalid")
    for field in ["sceneScore", "documentScore", "textCoverage"]:
        value = metrics.get(field)
        if not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise RuntimeError("Photo eligibility analysis is invalid")
    document, blocks, coverage = metrics["documentScore"], metrics["textBlocks"], metrics["textCoverage"]
    if document >= 0.55 or (document >= 0.12 and blocks >= 6 and coverage >= 0.025):
        eligible, reason = False, "document"
    elif blocks >= 8 and coverage >= 0.12:
        eligible, reason = False, "text-heavy"
    elif metrics["faces"] or metrics["people"]:
        eligible, reason = True, "people"
    elif metrics["sceneScore"] >= 0.45:
        eligible, reason = True, "place"
    else:
        eligible, reason = False, "uncertain-or-object"
    return {"curationVersion": CURATION_VERSION, "eligible": eligible, "curationReason": reason}


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


def recent_candidates(sources, today, days=7, limit=30):
    selected = []
    for root in sources:
        root = Path(root).expanduser()
        if not root.is_dir():
            raise RuntimeError("OneDrive photo folder is unavailable")
        errors = []
        for directory, dirs, files in os.walk(root, onerror=errors.append):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for name in files:
                if Path(name).suffix.lower() not in EXTENSIONS:
                    continue
                taken = filename_date(name)
                if taken is not None and 0 <= (today - taken).days < days:
                    selected.append((taken, Path(directory) / name))
        if errors:
            raise RuntimeError("OneDrive photo enumeration was incomplete")
    return sorted(selected, key=lambda p: (p[0], str(p[1])), reverse=True)[:limit]


def prepare_wallpapers(config, state, today):
    frame_fill(config)
    selected = recent_candidates(config["sources"], today, config.get("recent_days", 7),
                                 config.get("recent_limit", 30))
    folder = state / "wallpapers"
    folder.mkdir(exist_ok=True)
    metadata_file = state / "wallpapers.json"
    metadata = json.loads(metadata_file.read_text()) if metadata_file.exists() else {}
    frames, used = [], 0
    curate = config.get("suitable_only", False)
    stats = {"rejected": 0, "failures": 0, "complete": True}
    seen = set()
    deadline = time.monotonic() + config.get("recent_budget_seconds", 120)
    for named_date, source in selected:
        if time.monotonic() > deadline:
            stats["complete"] = False
            break
        key = image_cache_key(source, config)
        name = "recent_" + key + ".jpg"
        seen.add(name)
        target = folder / name
        record = metadata.get(name, {})
        checked = record.get("curationVersion") == CURATION_VERSION and type(record.get("eligible")) is bool
        if curate and checked and not record["eligible"]:
            stats["rejected"] += 1
            continue
        if not target.is_file() or (curate and not checked):
            temp = folder / (name + ".part")
            try:
                result = subprocess.run(image_arguments(config, source, temp, wallpaper=True),
                                        capture_output=True, text=True, timeout=60)
                if result.returncode:
                    raise RuntimeError("Image conversion failed")
                values = json.loads(result.stdout)
                rendering = frame_record(values, config)
                proof = curation_record(values) if curate else {}
                if curate and not proof["eligible"]:
                    metadata[name] = proof
                    stats["rejected"] += 1
                    continue
                taken = dt.date.fromisoformat(values["taken"]) if values.get("taken") else named_date
                if not 0 <= (today - taken).days < config.get("recent_days", 7):
                    continue
                temp.replace(target)
                metadata[name] = {"taken": str(taken), "dateSource": "EXIF" if values.get("taken") else "filename", **proof, **rendering}
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                stats["failures"] += 1
                continue
            finally:
                temp.unlink(missing_ok=True)
        taken = dt.date.fromisoformat(metadata.get(name, {}).get("taken", str(named_date)))
        if not 0 <= (today - taken).days < config.get("recent_days", 7):
            continue
        if used + target.stat().st_size > config.get("recent_max_bytes", 67108864):
            stats["complete"] = False
            break
        used += target.stat().st_size
        frames.append(target)
    if frames or (curate and stats["complete"] and not stats["failures"]):
        # Bound the local rolling cache too, while preserving it on an empty refresh.
        current = {p.name for p in frames}
        for old in folder.iterdir():
            if WALLPAPER.fullmatch(old.name) and old.name not in current:
                old.unlink()
        metadata = {name: record for name, record in metadata.items() if name in seen}
    temp = state / "wallpapers.json.next"
    temp.write_text(json.dumps(metadata, sort_keys=True))
    temp.replace(metadata_file)
    return frames, stats


def publish_wallpapers(adb, frames, clear_empty=False):
    if not frames and not clear_empty:
        return  # Keep the last collection if there are no new eligible pictures.
    if any(not WALLPAPER.fullmatch(p.name) for p in frames):
        raise RuntimeError("Invalid wallpaper filename")
    adb.call("shell", "mkdir -p " + WALLPAPER_REMOTE)
    listing = adb.call("shell", "ls -1 " + WALLPAPER_REMOTE).splitlines()
    existing = set(listing)
    for image in frames:
        if image.name not in existing:
            adb.call("push", str(image), WALLPAPER_REMOTE + "/" + image.name + ".part", timeout=60)
            adb.call("shell", "mv " + WALLPAPER_REMOTE + "/" + image.name + ".part "
                     + WALLPAPER_REMOTE + "/" + image.name)
    # Only our generated pictures are owned by this job. Preserve user-added wallpapers.
    obsolete = [n for n in listing if WALLPAPER.fullmatch(n) and n not in {p.name for p in frames}]
    if obsolete:
        adb.call("shell", "rm -f " + " ".join(WALLPAPER_REMOTE + "/" + n for n in obsolete))


def publish(adb, frames, index_path, allow_empty=False):
    """Every new image must exist before the atomic index replacement. No prune on failure."""
    names = [p.name for p in frames]
    if (not names and not allow_empty) or any(not NAME.fullmatch(n) for n in names):
        raise RuntimeError("Refusing an empty or invalid photo index")
    adb.call("shell", "mkdir -p " + REMOTE)
    listing = adb.call("shell", "ls -1 " + REMOTE).splitlines()
    old_index = adb.call("shell", "cat " + REMOTE + "/index.txt 2>/dev/null || true").splitlines()
    existing = set(listing)
    for photo in frames:
        if photo.name not in existing:
            adb.call("push", str(photo), REMOTE + "/" + photo.name + ".part", timeout=60)
            adb.call("shell", "mv " + REMOTE + "/" + photo.name + ".part " + REMOTE + "/" + photo.name)
    index_path.write_text("\n".join(names) + "\n" if names else "")
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
    frame_fill(config)
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
        frames, used, failures, rejected = [], 0, 0, 0
        curate = config.get("suitable_only", False)
        complete = True
        deadline = time.monotonic() + config.get("budget_seconds", 480)
        for _, path, named_date in selected:
            if time.monotonic() > deadline:
                complete = False
                break
            key = image_cache_key(path, config)
            record = metadata.get(key, {})
            checked = record.get("curationVersion") == CURATION_VERSION and type(record.get("eligible")) is bool
            if curate and checked and not record["eligible"]:
                rejected += 1
                continue
            filename = record.get("file", "")
            photo = cache / filename
            if not NAME.fullmatch(filename) or not photo.is_file() or (curate and not checked):
                temp = cache / (key + ".part.jpg")
                try:
                    result = subprocess.run(image_arguments(config, path, temp),
                                            capture_output=True, text=True, timeout=60)
                    if result.returncode:
                        raise RuntimeError("Image conversion failed")
                    data = json.loads(result.stdout)
                    rendering = frame_record(data, config)
                    proof = curation_record(data) if curate else {}
                    if curate and not proof["eligible"]:
                        metadata[key] = proof
                        rejected += 1
                        continue
                    taken = dt.date.fromisoformat(data["taken"]) if data.get("taken") else named_date
                    if (taken.month, taken.day) not in allowed or taken >= today:
                        continue
                    filename = str(taken) + "_" + key + ".jpg"
                    photo = cache / filename
                    temp.replace(photo)
                    metadata[key] = {"file": filename,
                                     "dateSource": "EXIF" if data.get("taken") else "filename", **proof, **rendering}
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                    failures += 1
                    continue
                finally:
                    temp.unlink(missing_ok=True)
            size = photo.stat().st_size
            if used + size > config.get("max_bytes", 134217728):
                complete = False
                break
            used += size
            frames.append(photo)
        metadata_tmp = state / "metadata.json.next"
        metadata_tmp.write_text(json.dumps(metadata, sort_keys=True))
        metadata_tmp.replace(metadata_file)
        if not frames and (not curate or failures or not complete):
            raise RuntimeError("No eligible photos were prepared; preserving the TV cache")
        status = {"date": str(today), "photos": len(frames), "bytes": used,
                  "conversionFailures": failures, "undatedSkipped": undated, "photosRejected": rejected,
                  "frameFill": frame_fill(config)}
        wallpapers, wallpaper_stats = prepare_wallpapers(config, state, today) if config.get("recent_days", 0) else ([], {})
        status["wallpapers"] = len(wallpapers)
        status["wallpapersRejected"] = wallpaper_stats.get("rejected", 0)
        status["wallpaperAnalysisFailures"] = wallpaper_stats.get("failures", 0)
        if prepare_only:
            status["status"] = "prepared"
        else:
            adb = ADB(config["adb"], config["device"], config.get("adb_port", 5038))
            if not adb.connect():
                status["status"] = "tv_offline"
            else:
                retain = publish(adb, frames, state / "index.txt", allow_empty=curate and complete and not failures)
                publish_wallpapers(adb, wallpapers, clear_empty=curate and wallpaper_stats.get("complete", False)
                                   and not wallpaper_stats.get("failures"))
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
