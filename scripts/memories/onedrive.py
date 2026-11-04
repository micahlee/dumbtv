"""Read personal OneDrive photo metadata and selected originals through Graph.

No synced folders, filename-derived dates, credentials on the TV, or cloud writes.
The Microsoft Graph PowerShell SDK owns the consented authentication cache.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import time
from urllib.parse import quote, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, build_opener

BASE = 'https://graph.microsoft.com/v1.0/'
DELTA = BASE + 'me/drive/root/delta?$select=id,photo,image,file,size,eTag,deleted,remoteItem&$top=1000'
TYPES = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/heic': '.heic', 'image/heif': '.heif'}


class GraphError(RuntimeError):
    def __init__(self, status=0):
        super().__init__('OneDrive API request failed; preserving the TV cache')
        self.status = status


def graph_url(url):
    value = urlsplit(url)
    if (value.scheme != 'https' or value.netloc != 'graph.microsoft.com'
            or not value.path.startswith('/v1.0/') or value.fragment):
        raise GraphError()
    return url


class Graph:
    def __init__(self, settings):
        bridge = Path(__file__).with_name('graph.ps1')
        environment = os.environ.copy()
        if settings.get('dotnet_root'):
            runtime = str(Path(settings['dotnet_root']).expanduser())
            environment['DOTNET_ROOT'] = runtime
            # The PowerShell global-tool shim starts its own dotnet child by
            # name. A GUI login agent normally has only the system PATH.
            environment['PATH'] = runtime + os.pathsep + environment.get('PATH', os.defpath)
        self.process = subprocess.Popen([str(Path(settings['pwsh']).expanduser()), '-NoLogo', '-NoProfile',
                                         '-NonInteractive', '-File', str(bridge)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, bufsize=1, env=environment)
        try:
            ready = self.read(100)
            if ready.get('ready') is not True or not ready.get('drive'):
                raise GraphError()
            self.drive = ready['drive']
        except (RuntimeError, ValueError):
            self.close()
            raise RuntimeError('OneDrive photo provider could not start; preserving the TV cache') from None

    def read(self, timeout):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout):
                raise GraphError()
        line = self.process.stdout.readline()
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError:
            # Device-code prompts are intentionally not written into scheduled-job logs.
            raise GraphError() from None

    def get(self, url):
        self.process.stdin.write(json.dumps({'url': graph_url(url)}) + '\n')
        self.process.stdin.flush()
        response = self.read(90)
        if 'error' in response:
            raise GraphError(response.get('status', 0))
        if not isinstance(response.get('data'), dict):
            raise GraphError()
        return response['data']

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()


def atomic_json(path, value):
    temp = path.with_name(path.name + '.next')
    temp.write_text(json.dumps(value, separators=(',', ':')))
    temp.replace(path)


def update_index(graph, path, deadline):
    """Commit only a complete delta; a failed page never discards the prior index."""
    prior = json.loads(path.read_text()) if path.exists() else {}
    if prior and (prior.get('version') != 1 or prior.get('drive') != graph.drive):
        raise RuntimeError('OneDrive account changed; review photo setup before refreshing')
    initial = prior.get('delta', DELTA)
    for reset in (False, True):
        items = {} if reset else dict(prior.get('items', {}))
        url, seen = DELTA if reset else initial, set()
        try:
            while True:
                if time.monotonic() >= deadline or url in seen:
                    raise GraphError()
                seen.add(url)
                page = graph.get(graph_url(url))
                if not isinstance(page.get('value'), list):
                    raise GraphError()
                for item in page['value']:
                    if not isinstance(item, dict) or not isinstance(item.get('id'), str):
                        raise GraphError()
                    key = item['id']
                    if 'deleted' in item or 'remoteItem' in item:
                        items.pop(key, None)
                    elif 'file' in item:
                        if item['file'].get('mimeType') in TYPES:
                            # Store no source names, paths, GPS, download URLs or tokens.
                            items[key] = {k: item[k] for k in ('id', 'eTag', 'size', 'image') if k in item}
                            items[key]['file'] = {'mimeType': item['file']['mimeType']}
                            items[key]['photo'] = {'takenDateTime': (item.get('photo') or {}).get('takenDateTime')}
                        else:
                            items.pop(key, None)
                following, delta = page.get('@odata.nextLink'), page.get('@odata.deltaLink')
                if bool(following) == bool(delta):
                    raise GraphError()
                if delta:
                    value = {'version': 1, 'drive': graph.drive, 'delta': graph_url(delta), 'items': items}
                    atomic_json(path, value)
                    return items
                url = graph_url(following)
        except GraphError as error:
            if error.status == 410 and not reset and initial != DELTA:
                continue
            raise


def captured(item):
    value = (item.get('photo') or {}).get('takenDateTime')
    if not isinstance(value, str):
        return None
    try:
        # Keep the capture date carried by the photo, not its upload/modification day.
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def select_photos(items, today, config, limit=None):
    buckets = [[] for _ in range(config.get('days_ahead', 7) + 1)]
    dates = [today + dt.timedelta(days=i) for i in range(len(buckets))]
    recent, undated = [], 0
    for item in items.values():
        taken = captured(item)
        if taken is None:
            undated += 1
            continue
        key = hashlib.sha256(item['id'].encode()).hexdigest()
        for i, day in enumerate(dates):
            if (taken.month, taken.day) == (day.month, day.day) and taken.year < day.year:
                image = item.get('image') or {}
                landscape = (image.get('width') or 0) >= (image.get('height') or 1)
                buckets[i].append((not landscape, key, item))
                break
        if 0 <= (today - taken).days < config.get('recent_days', 0):
            recent.append((taken, key, item))
    chosen = []
    for i, bucket in enumerate(buckets):
        chosen.extend(sorted(bucket, key=lambda x: x[:2])[:max(config.get('per_day', 40), 80) if i == 0 else config.get('per_day', 40)])
    memories = [item for _, _, item in chosen[:limit or config.get('max_photos', 240)]]
    recent.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return memories, [item for _, _, item in recent[:config.get('recent_limit', 30)]], undated


class SecureRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if urlsplit(newurl).scheme != 'https':
            raise GraphError()
        return super().redirect_request(request, fp, code, message, headers, newurl)


def download(url, target, expected, deadline):
    value = urlsplit(url)
    if value.scheme != 'https' or not value.hostname or value.username or value.password:
        raise GraphError()
    temp = target.with_name(target.name + '.part')
    try:
        # Preauthenticated Microsoft URL: no Graph bearer credential goes to the CDN.
        opener = build_opener(HTTPSHandler(), SecureRedirects())
        with opener.open(url, timeout=30) as response, temp.open('wb') as output:
            if urlsplit(response.url).scheme != 'https':
                raise GraphError()
            size = 0
            while True:
                if time.monotonic() >= deadline:
                    raise GraphError()
                chunk = response.read(min(1024 * 1024, expected + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > expected:
                    raise GraphError()
                output.write(chunk)
        if size != expected:
            raise GraphError()
        temp.replace(target)
    except OSError:
        raise GraphError() from None
    finally:
        temp.unlink(missing_ok=True)


def prepare(config, state, today, limit=None):
    settings = config['onedrive']
    folder = state / 'cloud-originals'
    folder.mkdir(mode=0o700, exist_ok=True)
    deadline = time.monotonic() + settings.get('budget_seconds', 600)
    graph = Graph(settings)
    try:
        items = update_index(graph, state / 'onedrive-index.json', deadline)
        memories, recent, undated = select_photos(items, today, config, limit)
        paths, total = {}, 0
        for item in memories + recent:
            if item['id'] in paths:
                continue
            size = item.get('size')
            if type(size) is not int or not 0 < size <= settings.get('max_photo_bytes', 64 * 1024 * 1024):
                raise RuntimeError('OneDrive photo exceeds the download limit; TV cache retained')
            total += size
            if total > settings.get('max_cache_bytes', 1024 * 1024 * 1024) or time.monotonic() >= deadline:
                raise GraphError()
            if not isinstance(item.get('eTag'), str) or not item['eTag']:
                raise GraphError()
            key = hashlib.sha256((graph.drive + ':' + item['id'] + ':' + item['eTag']).encode()).hexdigest()[:16]
            target = folder / (str(captured(item)) + '_' + key + TYPES[item['file']['mimeType']])
            if not target.exists() or target.stat().st_size != size:
                # Personal OneDrive can omit downloadUrl when a $select projection
                # is present. Fetch this selected item's full metadata, keeping
                # only its version/size and transient download URL in memory.
                live = graph.get(BASE + 'me/drive/items/' + quote(item['id'], safe=''))
                if live.get('eTag') != item.get('eTag') or live.get('size') != size:
                    raise RuntimeError('OneDrive photo changed during refresh; TV cache retained')
                download(live.get('@microsoft.graph.downloadUrl', ''), target, size, deadline)
            paths[item['id']] = target
        keep = set(paths.values())
        for old in folder.iterdir():
            if old.is_file() and old not in keep:
                old.unlink()
        return ([(p.stem, p, captured(item)) for item in memories for p in [paths[item['id']]]],
                [(captured(item), paths[item['id']]) for item in recent], undated,
                {'source': 'onedrive-api', 'cloudPhotosIndexed': len(items)})
    finally:
        graph.close()
