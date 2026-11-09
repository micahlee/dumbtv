"""Serial-bound discovery tests use synthetic endpoints and no real devices."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'scripts/memories'
sys.path.insert(0, str(ROOT))
import sync


class DeviceServiceTest(unittest.TestCase):
    def result(self, args, **kwargs):
        output = 'SYNTHETIC' if args[-2:] == ['shell', 'getprop ro.serialno'] else 'device'
        return subprocess.CompletedProcess(args, 0, output, '')

    def test_service_is_resolved_again_after_address_and_port_change(self):
        with patch('device_service.resolve', side_effect=[('first.local', 5555), ('second.local', 5556)]) as resolve, \
             patch.object(sync.socket, 'create_connection') as tcp, \
             patch.object(sync.subprocess, 'run', side_effect=self.result) as adb:
            connection = sync.ADB('fixture-adb', 'obsolete.local:5555', 5038, 'adb-SYNTHETIC')
            self.assertTrue(connection.connect())
            self.assertTrue(connection.connect())
            self.assertEqual(resolve.call_count, 2)
            self.assertEqual([c.args[0] for c in tcp.call_args_list], [('first.local', 5555), ('second.local', 5556)])
            self.assertEqual(connection.device, 'second.local:5556')
            self.assertEqual(sum(c.args[0][-2:] == ['shell', 'getprop ro.serialno'] for c in adb.call_args_list), 2)
            self.assertFalse(any('obsolete.local' in str(c) for c in adb.call_args_list))

    def test_missing_service_never_falls_back_to_generic_or_saved_address(self):
        with patch('device_service.resolve', side_effect=RuntimeError('unavailable')), \
             patch.object(sync.subprocess, 'run') as adb, patch.object(sync.socket, 'create_connection') as tcp:
            self.assertFalse(sync.ADB('fixture-adb', 'obsolete.local:5555', 5038, 'adb-SYNTHETIC').connect())
            adb.assert_not_called(); tcp.assert_not_called()

    def test_wrong_serial_is_rejected_before_publication(self):
        wrong = subprocess.CompletedProcess([], 0, 'OTHER', '')
        with patch('device_service.resolve', return_value=('discovered.local', 5555)), \
             patch.object(sync.socket, 'create_connection'), patch.object(sync.subprocess, 'run', return_value=wrong) as adb:
            with self.assertRaisesRegex(RuntimeError, 'identity'):
                sync.ADB('fixture-adb', '', 5038, 'adb-SYNTHETIC').connect()
            self.assertFalse(any('push' in c.args[0] for c in adb.call_args_list))

    def test_legacy_explicit_endpoint_still_works(self):
        with patch.object(sync.socket, 'create_connection'), patch.object(sync.subprocess, 'run', side_effect=self.result):
            self.assertTrue(sync.ADB('fixture-adb', 'fixture.local:5555').connect())

    def test_invalid_service_is_not_treated_as_a_legacy_endpoint(self):
        import device_service
        for value in ['', 'Android.local', 'adb-', 'adb-bad._tcp.local', 'adb-a\n', 'adb-' + 'a'*65, None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                device_service.serial(value)
        self.assertEqual(device_service.serial('adb-SYNTHETIC'), 'SYNTHETIC')

    def test_review_without_saved_address_preserves_tv_when_discovery_is_missing(self):
        import datetime as dt
        import socket
        import tempfile
        import daily_review
        with tempfile.TemporaryDirectory() as folder:
            config = dict(owner_host=socket.gethostname(), state_dir=folder, adb='fixture-adb',
                          device_service='adb-SYNTHETIC', daily_review=dict(enabled=True, weather={}))
            with patch.object(daily_review, 'calendars', return_value={'sources': []}), \
                 patch.object(daily_review, 'weather', return_value={}), \
                 patch('device_service.resolve', side_effect=RuntimeError('unavailable')), \
                 patch.object(sync.subprocess, 'run') as adb:
                status = daily_review.refresh(config, now=dt.datetime(2026, 11, 9, tzinfo=dt.timezone.utc))
                self.assertEqual(status['status'], 'tv_offline')
                adb.assert_not_called()
                self.assertTrue((Path(folder) / 'review/review.json').exists())
