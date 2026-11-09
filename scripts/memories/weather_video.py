#!/usr/bin/env python3
"""Read WYFF's dedicated forecast, cache one bounded MP4, and atomically publish it.

Runs only on the configured Mini. No YouTube downloads, credentials, TV wake,
cloud writes or arbitrary provider URLs. Format changes preserve prior cache;
the TV independently rejects expired manifests.
"""
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
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

WEATHER = 'https://www.wyff4.com/weather'
REMOTE = '/sdcard/Android/data/tv.dumbtv.home/files/weather-video'
MAX_HTML = 4 * 1024 * 1024
MAX_VIDEO = 96 * 1024 * 1024
MAX_AGE = 12 * 3600
NAME = re.compile(r'forecast_[0-9a-f]{64}\.mp4\Z')
UTC = dt.timezone.utc


def safe_url(url, media=False):
    p = urlsplit(url)
    host = 'streaming.hearstdigitalstudios.com' if media else 'www.wyff4.com'
    if (p.scheme != 'https' or p.netloc != host or p.username or p.password or p.fragment or p.query
            or (media and not re.fullmatch(r'/[0-9a-f-]{36}/[A-Za-z0-9_.-]+\.mp4', p.path))
            or (not media and p.path != '/weather' and not re.fullmatch(r'/article/[a-z0-9-]+/[0-9]+', p.path))):
        raise ValueError('forecast_source_invalid')
    return url


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        safe_url(newurl, urlsplit(request.full_url).hostname == 'streaming.hearstdigitalstudios.com')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def response(url, media=False):
    safe_url(url, media)
    return build_opener(Redirects()).open(Request(url, headers={'User-Agent': 'Mozilla/5.0 (TV forecast cache)'}), timeout=25)


def html(url):
    with response(url) as source:
        safe_url(source.url)
        if 'text/html' not in source.headers.get('Content-Type', ''):
            raise ValueError('forecast_page_invalid')
        data = source.read(MAX_HTML+1)
    if len(data) > MAX_HTML:
        raise ValueError('forecast_page_too_large')
    return data.decode('utf-8')


def objects(value, depth=0):
    if depth > 100:
        raise ValueError('forecast_page_invalid')
    if isinstance(value, dict):
        yield value
        for child in value.values(): yield from objects(child, depth+1)
    elif isinstance(value, list):
        for child in value: yield from objects(child, depth+1)


def page_objects(page):
    """Parse public Next flight JSON only; never evaluate provider JavaScript."""
    if len(page.encode()) > MAX_HTML:
        raise ValueError('forecast_page_too_large')
    chunks = [json.loads(m.group(1)) for m in re.finditer(
        r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)', page)]
    if not chunks:
        raise ValueError('forecast_page_format_changed')
    for line in ''.join(chunks).splitlines():
        if ':' not in line: continue
        data = line.split(':', 1)[1]
        if not data.startswith(('{', '[')): continue
        try: value = json.loads(data)
        except ValueError: continue
        yield from objects(value)


def mapping(value):
    return value if isinstance(value, dict) else {}


def is_weather(content):
    return (isinstance(content, dict) and mapping(content.get('site')).get('site_prefix') == 'wyff'
            and mapping(content.get('subsection')).get('slug') == 'videocast')


def lead(page):
    leads = {}
    for row in page_objects(page):
        if row.get('type') == 'weather_lead':
            content = mapping(row.get('data')).get('content')
            if is_weather(content) and isinstance(content.get('id'), str): leads[content['id']] = content
    if len(leads) != 1:
        raise ValueError('forecast_lead_ambiguous')
    item = next(iter(leads.values()))
    path = mapping(item.get('metadata')).get('social_share_url', '')
    url = safe_url(urljoin(WEATHER, path))
    if not urlsplit(url).path.startswith('/article/'):
        raise ValueError('forecast_article_invalid')
    return item['id'], url


def timestamp(value):
    if not isinstance(value, str): raise ValueError('forecast_date_invalid')
    date = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None: raise ValueError('forecast_date_invalid')
    return int(date.timestamp())


def select_video(page, identifier, article_url, now):
    contents = {row['id']: row for row in page_objects(page)
                if row.get('id') == identifier and is_weather(row) and isinstance(row.get('media'), list)}
    if len(contents) != 1: raise ValueError('forecast_article_mismatch')
    article = contents[identifier]
    candidates = [v for v in article['media'] if v.get('media_type') == 'video' and v.get('role') == 3
                  and str(mapping(v.get('source')).get('title', '')).startswith('WYFF')]
    if len(candidates) != 1: raise ValueError('forecast_video_ambiguous')
    video = candidates[0]
    published = timestamp(video.get('created_at'))
    if published > now+300 or now-published >= MAX_AGE: raise ValueError('forecast_stale')
    duration = video.get('duration')
    if not isinstance(duration, (int, float)) or not 10 <= duration <= 600: raise ValueError('forecast_duration_invalid')
    renditions = [v for v in video.get('transcodings', [])
                  if v.get('codec') == 'H_264' and v.get('status') == 'Complete'
                  and isinstance(v.get('height'), int) and 270 <= v['height'] <= 720
                  and isinstance(v.get('width'), int) and 1 <= v['width'] <= 1280]
    if not renditions: raise ValueError('forecast_format_unavailable')
    media = max(renditions, key=lambda v:v['height'])
    url = safe_url(media.get('full_url', ''), True)
    identifier = video.get('videoId')
    if not isinstance(identifier, str) or not re.fullmatch('[0-9a-f-]{36}', identifier): raise ValueError('forecast_video_invalid')
    title = ' '.join(str(video.get('title', '')).split())[:200]
    if not title or any(ord(c)<32 for c in title): raise ValueError('forecast_title_invalid')
    return dict(videoId=identifier, mediaURL=url, sourceURL=article_url, title=title,
                publishedAt=published*1000, expiresAt=(published+MAX_AGE)*1000, durationSeconds=int(duration))


def atomic_json(path, data):
    temp = path.with_name(path.name+'.next')
    temp.write_text(json.dumps(data, ensure_ascii=False)); temp.chmod(0o600); temp.replace(path)


def download(url, folder):
    temp = folder/'download.part'; deadline = time.monotonic()+180
    try:
        digest = hashlib.sha256(); size = 0; prefix = b''
        with response(url, True) as source, temp.open('wb') as target:
            safe_url(source.url, True)
            if source.headers.get('Content-Type', '').split(';')[0] != 'video/mp4': raise ValueError('forecast_media_invalid')
            expected = int(source.headers.get('Content-Length', '0'))
            if expected <= 0 or expected > MAX_VIDEO: raise ValueError('forecast_media_too_large')
            while True:
                if time.monotonic() > deadline: raise ValueError('forecast_download_timeout')
                chunk = source.read(1048576)
                if not chunk: break
                if not prefix: prefix = chunk[:32]
                size += len(chunk)
                if size > min(expected, MAX_VIDEO): raise ValueError('forecast_media_too_large')
                digest.update(chunk); target.write(chunk)
            if size != expected or prefix[4:8] != b'ftyp': raise ValueError('forecast_media_incomplete')
            target.flush(); os.fsync(target.fileno())
        name = 'forecast_'+digest.hexdigest()+'.mp4'; temp.replace(folder/name)
        return name, size
    finally: temp.unlink(missing_ok=True)


def prepare(folder, now):
    identifier, article = lead(html(WEATHER)); value = select_video(html(article), identifier, article, now)
    previous = json.loads((folder/'source.json').read_text()) if (folder/'source.json').exists() else {}
    name = previous.get('file', '')
    if (previous.get('videoId'), previous.get('mediaURL')) == (value['videoId'], value['mediaURL']) and NAME.fullmatch(name):
        target = folder/name
        if target.is_file() and target.stat().st_size == previous.get('bytes'):
            size = target.stat().st_size
        else: name, size = download(value['mediaURL'], folder)
    else: name, size = download(value['mediaURL'], folder)
    manifest = dict(version=1, source='WYFF', file=name, bytes=size, title=value['title'],
                    publishedAt=value['publishedAt'], expiresAt=value['expiresAt'],
                    durationSeconds=value['durationSeconds'], fetchedAt=now*1000)
    atomic_json(folder/'source.json', dict(value, file=name, bytes=size))
    atomic_json(folder/'forecast.json', manifest)
    return manifest


def publish(adb, folder, value):
    name = value['file']
    if not NAME.fullmatch(name): raise ValueError('forecast_filename_invalid')
    adb.call('shell', 'mkdir -p '+REMOTE)
    # A previous interrupted transfer must not accumulate orphaned large partials.
    for partial in adb.call('shell', 'ls '+REMOTE).splitlines():
        if partial.endswith('.next') and NAME.fullmatch(partial[:-5]):
            adb.call('shell', 'rm -f '+REMOTE+'/'+partial)
    old = adb.call('shell', 'cat '+REMOTE+'/forecast.json 2>/dev/null || true')
    try: prior = json.loads(old).get('file', '')
    except ValueError: prior = ''
    digest = name[len('forecast_'):-4]
    existing = adb.call('shell', 'sha256sum '+REMOTE+'/'+name+' 2>/dev/null || true').split()
    if not existing or existing[0] != digest:
        adb.call('push', str(folder/name), REMOTE+'/'+name+'.next', timeout=90)
        actual = adb.call('shell', 'sha256sum '+REMOTE+'/'+name+'.next').split()
        if not actual or actual[0] != digest: raise RuntimeError('forecast_transfer_incomplete')
        adb.call('shell', 'mv '+REMOTE+'/'+name+'.next '+REMOTE+'/'+name)
    adb.call('push', str(folder/'forecast.json'), REMOTE+'/forecast.json.next')
    adb.call('shell', 'mv '+REMOTE+'/forecast.json.next '+REMOTE+'/forecast.json')
    listing = adb.call('shell', 'ls '+REMOTE).splitlines()
    for obsolete in listing:
        if NAME.fullmatch(obsolete) and obsolete not in (name, prior): adb.call('shell', 'rm -f '+REMOTE+'/'+obsolete)


def refresh(config, prepare_only=False):
    if not config.get('weather_video', {}).get('enabled'): return dict(status='disabled')
    if socket.gethostname() != config['owner_host']: raise RuntimeError('forecast_wrong_host')
    folder = Path(config['state_dir']).expanduser()/'weather-video'; folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (folder/'refresh.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return dict(status='already_running')
        value = prepare(folder, int(time.time()))
        result = dict(status='prepared', publishedAt=value['publishedAt'], expiresAt=value['expiresAt'], bytes=value['bytes'])
        if not prepare_only:
            from sync import ADB
            adb = ADB(config['adb'], config.get('device', ''), config.get('adb_port', 5038), config.get('device_service'))
            if adb.connect(): publish(adb, folder, value); result['status'] = 'published'
            else: result['status'] = 'tv_offline'
        # Keep current and one predecessor locally; the native player pins its open file.
        previous = json.loads((folder/'status.json').read_text()) if (folder/'status.json').exists() else {}
        for p in folder.iterdir():
            if NAME.fullmatch(p.name) and p.name not in (value['file'], previous.get('file')): p.unlink()
        result['file'] = value['file']; atomic_json(folder/'status.json', result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--config', required=True)
    parser.add_argument('--prepare-only', action='store_true'); args = parser.parse_args(); os.umask(0o077)
    try:
        print(json.dumps(refresh(json.loads(Path(args.config).read_text()), args.prepare_only)))
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(json.dumps(dict(status='failed_previous_cache_retained', reason=type(error).__name__)))
        return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
