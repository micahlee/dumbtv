"""Graph photo selection and interrupted-refresh safety; synthetic data only."""
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'scripts/memories'
spec = importlib.util.spec_from_file_location('onedrive', ROOT / 'onedrive.py')
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)
spec = importlib.util.spec_from_file_location('sync', ROOT / 'sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def photo(key, taken='2020-11-04T12:00:00Z', **changes):
    return dict(id=key, photo={'takenDateTime': taken}, file={'mimeType': 'image/jpeg'},
                size=4, eTag='v1', **changes)


class FakeGraph:
    drive = 'fixture-drive'

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url):
        self.calls.append(url)
        value = self.pages[len(self.calls) - 1]
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        pass


class OneDrivePhotoTests(unittest.TestCase):
    def test_cloud_capture_dates_override_embedded_dates_and_recheck_old_cache(self):
        today = dt.date.today()
        anniversary = today.replace(year=2000)
        for embedded in ['2019--1-01', str(today.replace(year=2016))]:
            with self.subTest(embedded=embedded), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); state = root / 'state'; state.mkdir()
                memory = root / 'camera.jpg'; memory.write_bytes(b'original')
                recent = root / 'recent.jpg'; recent.write_bytes(b'original')
                config = dict(owner_host=socket.gethostname(), state_dir=str(state), photo_source='onedrive-api',
                              frame_fill='blur', suitable_only=True, days_ahead=0, recent_days=7, image_helper='fixture')
                old_key = sync.image_cache_key(memory, {'frame_fill': 'blur'})
                old_name = str(today.replace(year=2016)) + '_' + old_key + '.jpg'
                (state / 'frames').mkdir(); (state / 'frames' / old_name).write_bytes(b'old frame')
                (state / 'metadata.json').write_text(json.dumps({old_key: dict(file=old_name, dateSource='EXIF',
                                                                           eligible=True, curationVersion=1)}))
                def helper(args, **kwargs):
                    Path(args[2]).write_bytes(b'new frame')
                    value = dict(taken=embedded, width=1920, height=1080, frameFill='blur', sourceWidth=900,
                                 sourceHeight=1200, curation=dict(version=1, faces=1, people=1, textBlocks=0,
                                 sceneScore=0, documentScore=0, textCoverage=0))
                    return subprocess.CompletedProcess(args, 0, json.dumps(value), '')
                prepared = ([('fixture', memory, anniversary)], [(today, recent)], 0, {'source': 'onedrive-api'})
                with patch.dict(sys.modules, onedrive=cloud), patch.object(cloud, 'prepare', return_value=prepared), \
                     patch.object(sync.subprocess, 'run', side_effect=helper):
                    result = sync.refresh(config, prepare_only=True)
                self.assertEqual((result['photos'], result['wallpapers'], result['conversionFailures']), (1, 1, 0))
                records = json.loads((state / 'metadata.json').read_text())
                record = records[sync.image_cache_key(memory, config)]
                self.assertTrue(record['file'].startswith(str(anniversary) + '_'))
                self.assertEqual(record['dateSource'], 'OneDrive photo API')
                wallpaper = next(iter(json.loads((state / 'wallpapers.json').read_text()).values()))
                self.assertEqual(wallpaper['taken'], str(today))
                self.assertEqual(wallpaper['dateSource'], 'OneDrive photo API')

    def test_dotnet_tool_starts_with_the_minimal_login_agent_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = root / 'runtime'; runtime.mkdir()
            shim = root / 'pwsh'
            # The vendor's .NET tool shim starts a child named dotnet. GUI jobs
            # do not inherit a Homebrew path, even when the shim path is absolute.
            shim.write_text('#!/bin/sh\nexec dotnet "$@"\n')
            dotnet = runtime / 'dotnet'
            dotnet.write_text('#!/bin/sh\necho \'{"ready":true,"drive":"fixture"}\'\n'
                              'while IFS= read -r request; do echo \'{"data":{"probe":true}}\'; done\n')
            shim.chmod(0o700); dotnet.chmod(0o700)
            with patch.dict(os.environ, PATH='/usr/bin:/bin'):
                graph = cloud.Graph({'pwsh': str(shim), 'dotnet_root': str(runtime)})
                try:
                    self.assertTrue(graph.get(cloud.BASE + 'me/drive')['probe'])
                finally:
                    graph.close()

    def test_complete_delta_uses_last_occurrence_and_deletions(self):
        pages = [{'value': [photo('a'), photo('gone')], '@odata.nextLink': cloud.BASE + 'next?opaque=a%2Fb'},
                 {'value': [photo('a', '2021-11-04T12:00:00Z'), {'id': 'gone', 'deleted': {}}],
                  '@odata.deltaLink': cloud.BASE + 'delta?opaque=next'}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'index.json'
            graph = FakeGraph(pages)
            items = cloud.update_index(graph, path, time.monotonic() + 5)
            self.assertEqual(set(items), {'a'})
            self.assertEqual(cloud.captured(items['a']), dt.date(2021, 11, 4))
            self.assertEqual(graph.calls[1], pages[0]['@odata.nextLink'])
            self.assertEqual(json.loads(path.read_text())['drive'], graph.drive)

    def test_failed_page_keeps_old_index_and_delta(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'index.json'
            prior = dict(version=1, drive='fixture-drive', delta=cloud.BASE + 'delta?old', items={'kept': photo('kept')})
            cloud.atomic_json(path, prior)
            original = path.read_bytes()
            graph = FakeGraph([{'value': [{'id': 'kept', 'deleted': {}}], '@odata.nextLink': cloud.BASE + 'page2'}, cloud.GraphError(429)])
            with self.assertRaises(cloud.GraphError):
                cloud.update_index(graph, path, time.monotonic() + 5)
            self.assertEqual(path.read_bytes(), original)

    def test_expired_delta_rebuilds_once_and_account_switch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'index.json'
            cloud.atomic_json(path, dict(version=1, drive='fixture-drive', delta=cloud.BASE + 'old', items={'old': photo('old')}))
            graph = FakeGraph([cloud.GraphError(410), {'value': [photo('new')], '@odata.deltaLink': cloud.BASE + 'new'}])
            self.assertEqual(set(cloud.update_index(graph, path, time.monotonic() + 5)), {'new'})
            self.assertEqual(graph.calls[1], cloud.DELTA)
            graph.drive = 'another-account'
            with self.assertRaisesRegex(RuntimeError, 'account changed'):
                cloud.update_index(graph, path, time.monotonic() + 5)

    def test_api_capture_dates_drive_selection(self):
        values = [photo('portrait', image={'width': 800, 'height': 1200}),
                  photo('landscape', image={'width': 1600, 'height': 900}),
                  photo('today', '2026-11-04T23:00:00-05:00'),
                  photo('week', '2026-10-29T10:00:00Z'), photo('too-old', '2026-10-28T10:00:00Z'),
                  photo('2020-11-04-filename-only', None)]
        memories, recent, undated = cloud.select_photos({x['id']: x for x in values}, dt.date(2026, 11, 4),
                                                       dict(days_ahead=0, max_photos=30, recent_days=7))
        self.assertEqual({p['id'] for p in memories}, {'landscape', 'portrait'})
        self.assertEqual([p['id'] for p in recent], ['today', 'week'])
        self.assertEqual(undated, 1)

    def test_daily_sample_is_stable_and_independent_of_orientation_year_and_input_order(self):
        values = [photo(str(i), image={'width': 1600, 'height': 900}) for i in range(200)]
        config = dict(days_ahead=0, max_photos=30)
        def sample(values, year=2026):
            selected, _, _ = cloud.select_photos({p['id']: p for p in values}, dt.date(year, 11, 4), config)
            return [p['id'] for p in selected]
        original = sample(values)
        self.assertEqual(len(set(original)), 30)
        self.assertEqual(original, sample(list(reversed(values))))
        changed = [photo(str(i), f'{2000 + i % 20}-11-04T12:00:00Z',
                         image={'width': 800, 'height': 1200} if i % 2 else {'width': 1600, 'height': 900})
                   for i in range(200)]
        self.assertEqual(original, sample(changed))
        self.assertNotEqual(original, sample(values, year=2027))
        # Over many independent daily seeds, neither orientation group dominates.
        counts = [sum(int(key) % 2 for key in sample(changed, year)) for year in range(2026, 2126)]
        self.assertGreater(sum(counts), 1200)
        self.assertLess(sum(counts), 1800)

    def test_diversity_rebalances_large_sessions_across_years_without_orientation_bias(self):
        values=[photo('session'+str(i),'2010-11-04T10:00:00Z') for i in range(510)]
        for year in range(2014,2024):
            values.extend(photo(str(year)+'-'+str(i),str(year)+'-11-04T12:00:00Z') for i in range(8))
        config=dict(days_ahead=0,max_photos=30,photo_diversity=True)
        def select(items,day=dt.date(2026,11,4)):
            return cloud.select_photos({p['id']:p for p in items},day,config)[0]
        selected=select(values)
        self.assertEqual(len(selected),30)
        counts={year:sum(cloud.captured(p).year==year for p in selected) for year in [2010,*range(2014,2024)]}
        self.assertEqual(len(counts),11);self.assertTrue(all(2<=v<=3 for v in counts.values()))
        self.assertEqual([p['id'] for p in selected],[p['id'] for p in select(list(reversed(values)))])
        changed=[dict(p,image=dict(width=800,height=1200)) for p in values]
        self.assertEqual([p['id'] for p in selected],[p['id'] for p in select(changed)])
        self.assertNotEqual([p['id'] for p in selected],[p['id'] for p in select(values,dt.date(2027,11,4))])

    def test_diversity_spreads_capture_sessions_within_a_year(self):
        values=[photo('burst'+str(i),'2010-11-04T10:00:00Z') for i in range(500)]
        values.extend(photo('other'+str(i),'2010-11-04T18:00:00Z') for i in range(4))
        selected,_,_=cloud.select_photos({p['id']:p for p in values},dt.date(2026,11,4),
                                         dict(days_ahead=0,max_photos=8,photo_diversity=True))
        self.assertEqual(sum(p['id'].startswith('other') for p in selected),4)
        self.assertEqual(len({p['id'] for p in selected}),8)

    def test_new_year_and_leap_day_selection(self):
        values = [photo('end', '2020-12-31T12:00:00Z'), photo('next', '2026-01-01T12:00:00Z'), photo('leap', '2024-02-29T12:00:00Z')]
        items = {x['id']: x for x in values}
        memories, _, _ = cloud.select_photos(items, dt.date(2026, 12, 31), dict(days_ahead=1))
        self.assertEqual({p['id'] for p in memories}, {'end', 'next'})
        memories, _, _ = cloud.select_photos(items, dt.date(2028, 2, 29), dict(days_ahead=0))
        self.assertEqual([p['id'] for p in memories], ['leap'])

    def test_authenticated_pagination_never_leaves_graph(self):
        for url in ['http://graph.microsoft.com/v1.0/me', 'https://example.com/v1.0/me',
                    'https://graph.microsoft.com@elsewhere.test/v1.0/me', 'https://graph.microsoft.com/beta/me']:
            with self.assertRaises(cloud.GraphError):
                cloud.graph_url(url)

    def test_partial_or_oversize_download_never_replaces_a_cached_original(self):
        class Response(io.BytesIO):
            url = 'https://download.example.test/photo'
        for content in (b'ab', b'oversized'):
            with tempfile.TemporaryDirectory() as directory, patch.object(cloud, 'build_opener') as opener:
                target = Path(directory) / 'photo.jpg'
                target.write_bytes(b'old')
                opener.return_value.open.return_value = Response(content)
                with self.assertRaises(cloud.GraphError):
                    cloud.download(Response.url, target, 4, time.monotonic() + 5)
                self.assertEqual(target.read_bytes(), b'old')
                self.assertFalse(target.with_name('photo.jpg.part').exists())

    def test_insecure_download_and_redirect_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(cloud, 'build_opener') as opener:
            with self.assertRaises(cloud.GraphError):
                cloud.download('http://download.example.test/photo', Path(directory) / 'photo', 4, time.monotonic() + 5)
            opener.assert_not_called()
        with self.assertRaises(cloud.GraphError):
            cloud.SecureRedirects().redirect_request(None, None, 302, '', {}, 'http://download.example.test/photo')

    def test_api_dry_run_is_read_only_and_never_enumerates_a_synced_folder(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, onedrive=cloud), \
             patch.object(cloud, 'Graph') as graph, patch.object(sync, 'candidates') as local:
            state = Path(directory) / 'not-created'
            config = dict(owner_host=socket.gethostname(), state_dir=str(state), photo_source='onedrive-api')
            self.assertEqual(sync.refresh(config, dry_run=True)['status'], 'cloud_index_not_prepared')
            self.assertFalse(state.exists())
            graph.assert_not_called()
            local.assert_not_called()

    def test_preparation_downloads_only_selected_api_photos_and_reuses_versions(self):
        values = [photo('memory'), photo('recent', '2026-11-03T12:00:00Z'), photo('other', '2020-06-01T12:00:00Z')]
        graph = FakeGraph([{'value': values, '@odata.deltaLink': cloud.BASE + 'delta?ready'},
                           {'id': 'memory', 'size': 4, 'eTag': 'v1', '@microsoft.graph.downloadUrl': 'https://download.example.test/m'},
                           {'id': 'recent', 'size': 4, 'eTag': 'v1', '@microsoft.graph.downloadUrl': 'https://download.example.test/r'},
                           {'value': [], '@odata.deltaLink': cloud.BASE + 'delta?next'}])
        with tempfile.TemporaryDirectory() as directory, patch.object(cloud, 'Graph', return_value=graph), \
             patch.object(cloud, 'download', side_effect=lambda url, path, size, deadline: path.write_bytes(b'jpeg')) as downloads:
            config = dict(onedrive={'pwsh': 'fixture'}, days_ahead=0, recent_days=7)
            memories, recent, _, status = cloud.prepare(config, Path(directory), dt.date(2026, 11, 4))
            self.assertEqual(len(memories), 1)
            self.assertEqual(len(recent), 1)
            self.assertEqual(memories[0][2], dt.date(2020, 11, 4))
            self.assertEqual(status['source'], 'onedrive-api')
            self.assertEqual(downloads.call_count, 2)
            cloud.prepare(config, Path(directory), dt.date(2026, 11, 4))
            self.assertEqual(downloads.call_count, 2)
            self.assertEqual(len(list((Path(directory) / 'cloud-originals').iterdir())), 2)

    def test_missing_download_annotation_keeps_original_cache_unmodified(self):
        graph = FakeGraph([{'value': [photo('memory')], '@odata.deltaLink': cloud.BASE + 'delta?ready'},
                           {'id': 'memory', 'size': 4, 'eTag': 'v1'}])
        with tempfile.TemporaryDirectory() as directory, patch.object(cloud, 'Graph', return_value=graph):
            state = Path(directory)
            folder = state / 'cloud-originals'; folder.mkdir()
            prior = folder / 'previous.jpg'; prior.write_bytes(b'old')
            with self.assertRaises(cloud.GraphError):
                cloud.prepare(dict(onedrive={'pwsh': 'fixture'}, days_ahead=0), state, dt.date(2026, 11, 4))
            self.assertEqual(prior.read_bytes(), b'old')
            self.assertEqual(list(folder.iterdir()), [prior])

    def test_api_failure_never_falls_back_to_local_folder_or_publishes(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, onedrive=cloud), \
             patch.object(cloud, 'prepare', side_effect=cloud.GraphError()), \
             patch.object(sync, 'candidates') as local, patch.object(sync, 'publish') as publish:
            config = dict(owner_host=socket.gethostname(), state_dir=directory, photo_source='onedrive-api',
                          sources=['unused-local-folder'])
            with self.assertRaises(cloud.GraphError):
                sync.refresh(config)
            local.assert_not_called()
            publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
