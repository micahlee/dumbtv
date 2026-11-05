"""Private Mac-only deduplication and collage preparation from already curated originals."""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time

VERSION = 2


def atomic_json(path, value):
    temp = path.with_name(path.name + '.next')
    temp.write_text(json.dumps(value, sort_keys=True))
    temp.chmod(0o600)
    temp.replace(path)


def source_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(value):
    if not isinstance(value, dict) or value.get('version') != VERSION:
        raise RuntimeError('Photo fingerprint is incomplete; TV cache retained')
    for name, length in [('pixelHash', 64), ('differenceHash', 16)]:
        if not isinstance(value.get(name), str) or not re.fullmatch('[0-9a-f]{' + str(length) + '}', value[name]):
            raise RuntimeError('Photo fingerprint is incomplete; TV cache retained')
    grid = value.get('colorGrid')
    if not isinstance(grid, list) or len(grid) != 192 or any(type(v) is not int or not 0 <= v <= 255 for v in grid):
        raise RuntimeError('Photo fingerprint is incomplete; TV cache retained')
    if any(type(value.get(k)) is not int or not 0 < value[k] <= 256 for k in ['width', 'height']):
        raise RuntimeError('Photo fingerprint is incomplete; TV cache retained')
    if value.get('orientationMode') not in ('metadata', 'pixels') or not isinstance(value.get('description', ''), str):
        raise RuntimeError('Photo orientation analysis is incomplete; TV cache retained')
    return value


def useful_description(value):
    text = ' '.join(value.split())
    if not 4 <= len(text) <= 46 or any(ord(c) < 32 for c in text):
        return ''
    if re.search(r'(?i)(https?://|www\.|@|copyright|all rights reserved|\.(jpg|jpeg|png|heic)\b)', text):
        return ''
    if re.match(r'(?i)^(sony(?: dsc)?|canon|nikon|olympus(?: digital camera)?|panasonic|kodak|samsung|apple|iphone|digital camera|dsc|img|dcim|untitled|image|photo)[\s_\d.-]*$', text):
        return ''
    if not any(c.isalpha() for c in text):
        return ''
    return text


def page_title(page):
    dates = [p['taken'] for p in page]
    first = min(dates)
    if len(set(dates)) == 1:
        return first.strftime('%B ') + str(first.day) + ', ' + str(first.year)
    if len({(d.month, d.day) for d in dates}) == 1:
        return first.strftime('%B ') + str(first.day) + ' · Through the years'
    return first.strftime('%b ') + str(first.day) + ' – ' + max(dates).strftime('%b ') + str(max(dates).day)


def photo_caption(entry, kind):
    date = entry['taken'].strftime('%Y' if kind == 'memories' else '%b %d, %Y')
    description = useful_description(entry['fingerprint'].get('description', ''))
    return description + ' · ' + date if description else date


def same_photo(a, b):
    if a['pixelHash'] == b['pixelHash']:
        return True
    aspect_a, aspect_b = a['width'] / a['height'], b['width'] / b['height']
    if abs(aspect_a - aspect_b) / max(aspect_a, aspect_b) > .01:
        return False
    if bin(int(a['differenceHash'], 16) ^ int(b['differenceHash'], 16)).count('1') > 1:
        return False
    # A strict color-layout match prevents flat/dark dHash collisions and avoids
    # broadly merging different photos of the same person or scene.
    return math.sqrt(sum((x-y)**2 for x, y in zip(a['colorGrid'], b['colorGrid'])) / 192) <= 2.5


def groups(entries):
    """Balanced 2–4 photo pages; never repeat an image to fill a leftover slot."""
    if len(entries) < 2:
        return []
    count = (len(entries) + 3) // 4
    size, extra = divmod(len(entries), count)
    result, offset = [], 0
    for i in range(count):
        length = size + (i < extra)
        result.append(entries[offset:offset+length])
        offset += length
    return result


def varied_groups(entries):
    """At most one capture year per page when multiple years are available.

    Keep sparse years rather than filling pages with surplus from one session.
    This groups events/dates, not identified faces. Single-year pools retain a
    visual-scene ordering to reduce adjacent similar shots where possible.
    """
    years = {}
    for entry in entries:
        years.setdefault(entry['taken'].year, []).append(entry)
    if len(years) < 2:
        # A scene/type difference is a useful tie-break, never a face identity claim.
        remaining = list(entries); ordered = []
        while remaining:
            if not ordered: chosen = 0
            else:
                prior = ordered[-1]
                def distance(p):
                    return (p['proof'].get('curationReason') != prior['proof'].get('curationReason'),
                            sum((a-b)**2 for a,b in zip(p['fingerprint']['colorGrid'], prior['fingerprint']['colorGrid'])))
                chosen = max(range(len(remaining)), key=lambda i:distance(remaining[i]))
            ordered.append(remaining.pop(chosen))
        return groups(ordered)
    total = len(entries)
    # Without this cap a 500-photo session plus three other photos still produces
    # pages entirely of that session. Deferred originals remain in OneDrive.
    for year, photos in years.items():
        years[year] = photos[:min(len(photos), total-len(photos))]
    total = sum(map(len, years.values()))
    count = max(max(map(len, years.values())), (total+3)//4)
    pages = [[] for _ in range(count)]
    for year, photos in sorted(years.items(), key=lambda p:(-len(p[1]), p[0])):
        available = set(range(count))
        for photo in photos:
            # Spread scenery and people as well as years, without identity inference.
            def score(i):
                return (len(pages[i]), sum(p['proof'].get('curationReason') == photo['proof'].get('curationReason')
                                          for p in pages[i]), i)
            target = min(available, key=score)
            pages[target].append(photo);available.remove(target)
    assert all(2 <= len(page) <= 4 for page in pages)
    return pages


def native(helper, *args):
    result = subprocess.run([str(helper), *map(str, args)], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Collage preparation failed; TV cache retained')
    try:
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (TypeError, ValueError):
        raise RuntimeError('Collage preparation failed; TV cache retained') from None


def prepare(config, state, entries, kind):
    if kind not in ('memories', 'wallpapers'):
        raise RuntimeError('Unknown collage collection')
    overrides = config.get('photo_orientation_overrides', {})
    if not isinstance(overrides, dict) or any(
            not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key)
            or value not in ('metadata', 'pixels') for key, value in overrides.items()):
        raise RuntimeError('Reviewed photo orientation settings are invalid; TV cache retained')
    helper = config.get('collage_helper', str(Path(config['image_helper']).with_name('memory-collage')))
    folder = state / 'collages'
    folder.mkdir(mode=0o700, exist_ok=True)
    analysis_path = state / 'collage-analysis.json'
    analysis = json.loads(analysis_path.read_text()) if analysis_path.exists() else {}
    if not isinstance(analysis, dict):
        raise RuntimeError('Photo fingerprint cache is invalid; TV cache retained')
    deadline = time.monotonic() + config.get('collage_budget_seconds', 180)
    unique, hashes, duplicates = [], set(), 0
    for entry in entries:
        if time.monotonic() >= deadline:
            raise RuntimeError('Collage refresh budget exceeded; TV cache retained')
        proof = entry['proof']
        if proof.get('eligible') is not True or proof.get('curationVersion') != 1:
            raise RuntimeError('Collages require curated originals; TV cache retained')
        sha = source_hash(entry['source'])
        if sha in hashes:
            duplicates += 1
            continue
        hashes.add(sha)
        reviewed = overrides.get(sha, 'automatic')
        if (not isinstance(analysis.get(sha), dict) or analysis[sha].get('version') != VERSION
                or analysis[sha].get('orientationOverride', 'automatic') != reviewed):
            args = ('--fingerprint', entry['source']) + ((reviewed,) if reviewed != 'automatic' else ())
            analysis[sha] = dict(fingerprint(native(helper, *args)), orientationOverride=reviewed)
        fp = fingerprint(analysis[sha])
        if any(same_photo(fp, other['fingerprint']) for other in unique):
            duplicates += 1
            continue
        unique.append(dict(entry, fingerprint=fp, sourceSHA256=sha))
    buckets = {}
    for entry in unique:
        # A page must not claim today's anniversary while containing another day.
        bucket = entry['taken'].strftime('%m-%d') if kind == 'memories' else 'recent'
        buckets.setdefault(bucket, []).append(entry)
    frames, records, unpaired, deferred = [], {}, 0, 0
    previous_path = state / ('collage-' + kind + '.json')
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    for bucket in buckets.values():
        if len(bucket) == 1:
            unpaired += 1
        pages = varied_groups(bucket) if config.get('photo_diversity') else groups(bucket)
        deferred += max(0, len(bucket) - sum(map(len, pages))) if len(bucket) > 1 else 0
        for page in pages:
            if time.monotonic() >= deadline:
                raise RuntimeError('Collage refresh budget exceeded; TV cache retained')
            members = [dict(sourceSHA256=p['sourceSHA256'], taken=str(p['taken']),
                            pixelHash=p['fingerprint']['pixelHash'], orientationMode=p['fingerprint']['orientationMode'],
                            caption=photo_caption(p, kind), curationReason=p['proof'].get('curationReason'),
                            eligible=True, curationVersion=1) for p in page]
            key = hashlib.sha256(('scrapbook-v2:' + kind + ':' + json.dumps(members, sort_keys=True)).encode()).hexdigest()[:16]
            name = (str(min(p['taken'] for p in page)) + '_' + key + '_s.jpg' if kind == 'memories'
                    else 'recent_' + key + '.jpg')
            target = folder / name
            result = {}
            if not target.is_file() or not target.stat().st_size:
                manifest = folder / (key + '.manifest.json')
                temp = folder / (name + '.part')
                try:
                    atomic_json(manifest, {'version': VERSION, 'seed': key, 'title': page_title(page), 'photos': [
                        {'path': str(p['source']), 'caption': photo_caption(p, kind),
                         'orientationMode': p['fingerprint']['orientationMode']} for p in page]})
                    result = native(helper, manifest, temp)
                    if (result.get('width'), result.get('height'), result.get('photos'), result.get('frameFill')) != (1920, 1080, len(page), 'scrapbook') or not temp.is_file() or not temp.stat().st_size:
                        raise RuntimeError('Collage rendering is incomplete; TV cache retained')
                    temp.replace(target)
                finally:
                    manifest.unlink(missing_ok=True)
                    temp.unlink(missing_ok=True)
            frames.append(target)
            records[name] = dict(version=VERSION, kind=kind, members=members, photos=len(page), frameFill='scrapbook',
                                 title=page_title(page), layout=result.get('layout', previous.get(name, {}).get('layout', [])))
    atomic_json(analysis_path, analysis)
    atomic_json(state / ('collage-' + kind + '.json'), records)
    return frames, dict(uniquePhotos=sum(p['photos'] for p in records.values()), eligibleUniquePhotos=len(unique),
                        diversityDeferredPhotos=deferred, duplicatesRemoved=duplicates, unpairedPhotos=unpaired,
                        pages=len(frames), fingerprintHashes=sorted(hashes))


def prune(state, keep, fingerprint_hashes):
    folder = state / 'collages'
    for file in folder.iterdir():
        if re.fullmatch(r'(?:(?:19|20)\d\d-\d\d-\d\d_[0-9a-f]{16}_[cs]|recent_[0-9a-f]{16})\.jpg', file.name) and file.name not in keep:
            file.unlink()
    analysis_path = state / 'collage-analysis.json'
    if analysis_path.exists():
        analysis = json.loads(analysis_path.read_text())
        atomic_json(analysis_path, {key: value for key, value in analysis.items() if key in fingerprint_hashes})
