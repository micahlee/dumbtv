"""Synthetic station fixtures only; no network or household content in tests."""
import importlib.util
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/'scripts/memories'
spec=importlib.util.spec_from_file_location('weather_video',ROOT/'weather_video.py');video=importlib.util.module_from_spec(spec);spec.loader.exec_module(video)
NOW=1800000000
ARTICLE='https://www.wyff4.com/article/current-forecast/12345678'
MEDIA='https://streaming.hearstdigitalstudios.com/11111111-1111-1111-1111-111111111111/video_16x9_720p.mp4'

def flight(value):return '<script>self.__next_f.push([1,'+json.dumps('0:'+json.dumps(value)+'\n')+'])</script>'
def content():return dict(id='forecast-id',site=dict(site_prefix='wyff'),subsection=dict(slug='videocast'),
                          metadata=dict(social_share_url='/article/current-forecast/12345678'))
def media():return dict(media_type='video',role=3,source=dict(title='WYFF US'),videoId='11111111-1111-1111-1111-111111111111',
                       created_at='2027-01-15T07:58:20Z',duration=159,title='Light showers this morning',transcodings=[
                       dict(codec='H_264',status='Complete',width=1280,height=720,full_url=MEDIA)])
# Freeze fixture time to its explicit, timezone-bearing publication timestamp.
NOW=video.timestamp('2027-01-15T08:00:00Z')

class Response(io.BytesIO):
    def __init__(self,data,url=MEDIA,content_type='video/mp4',length=None):
        super().__init__(data);self.url=url;self.headers={'Content-Type':content_type,'Content-Length':str(len(data) if length is None else length)}

class WeatherVideoTests(unittest.TestCase):
    def test_dedicated_weather_role_selects_forecast_not_generic_channel_keywords(self):
        item=content();identifier,url=video.lead(flight(dict(type='weather_lead',data=dict(content=item))))
        item['media']=[media()];result=video.select_video(flight(dict(voltronArticle=item)),identifier,url,NOW)
        self.assertEqual(result['title'],'Light showers this morning');self.assertEqual(result['durationSeconds'],159)
        self.assertEqual(result['expiresAt'],(NOW-100+12*3600)*1000)
        for changed in [dict(item,subsection=dict(slug='news')),dict(item,site=dict(site_prefix='other'))]:
            with self.assertRaises(ValueError):video.select_video(flight(changed),identifier,url,NOW)
        with self.assertRaises(ValueError):video.lead(flight(dict(type='news',data=dict(content=item))))

    def test_ambiguous_stale_future_and_wrong_renditions_are_rejected(self):
        for change in [dict(created_at='2000-01-01T00:00:00Z'),dict(created_at='2099-01-01T00:00:00Z'),
                       dict(created_at='2027-01-15T08:00:00'),dict(duration=601),dict(source=dict(title='Other')),
                       dict(transcodings=[]),dict(transcodings=[dict(codec='HEVC',status='Complete',height=720,width=1280,full_url=MEDIA)])]:
            item=content();item['media']=[dict(media(),**change)]
            with self.assertRaises(ValueError):video.select_video(flight(item),'forecast-id',ARTICLE,NOW)
        item=content();item['media']=[media(),media()]
        with self.assertRaises(ValueError):video.select_video(flight(item),'forecast-id',ARTICLE,NOW)
        with self.assertRaises(ValueError):video.page_objects('garbage').__next__()

    def test_provider_urls_and_redirects_cannot_escape_fixed_https_sources(self):
        for url in ['http://www.wyff4.com/weather','https://www.wyff4.com@elsewhere.test/weather',
                    'https://elsewhere.test/article/forecast/123','https://www.wyff4.com:443/weather',
                    'https://www.wyff4.com/weather?redirect=elsewhere']:
            with self.assertRaises(ValueError):video.safe_url(url)
        for url in [MEDIA.replace('https:','http:'),MEDIA.replace('streaming.hearstdigitalstudios.com','elsewhere.test'),
                    MEDIA+'?redirect=elsewhere',MEDIA.replace('.mp4','.html')]:
            with self.assertRaises(ValueError):video.safe_url(url,True)

    def test_incomplete_wrong_type_and_oversize_downloads_never_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for response in [Response(b'bad'),Response(b'0000ftypcontent',length=100),Response(b'0000ftypcontent',content_type='text/html'),
                             Response(b'0000ftypcontent',length=video.MAX_VIDEO+1)]:
                with patch.object(video,'response',return_value=response),self.assertRaises(ValueError):video.download(MEDIA,root)
                self.assertEqual(list(root.iterdir()),[])
            with patch.object(video,'response',return_value=Response(b'0000ftypcontent')):
                name,size=video.download(MEDIA,root)
            self.assertTrue(video.NAME.fullmatch(name));self.assertEqual(size,15)

    def test_same_clip_reuses_file_without_extending_editorial_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=content();article=dict(source,media=[media()]);pages=[flight(dict(type='weather_lead',data=dict(content=source))),flight(article)]
            def html(url):return pages[0] if url==video.WEATHER else pages[1]
            with patch.object(video,'html',side_effect=html),patch.object(video,'response',side_effect=lambda *a:Response(b'0000ftypcontent')):
                first=video.prepare(root,NOW)
                with patch.object(video,'download',side_effect=AssertionError('must reuse')):
                    second=video.prepare(root,NOW+1000)
            self.assertEqual(first['file'],second['file']);self.assertEqual(first['expiresAt'],second['expiresAt'])
            self.assertGreater(second['fetchedAt'],first['fetchedAt'])

    def test_publication_verifies_media_before_atomic_manifest_and_retains_predecessor(self):
        class ADB:
            def __init__(self,fail=False):self.calls=[];self.fail=fail
            def call(self,*args,**kwargs):
                self.calls.append(args)
                if args[0]=='shell' and args[1].startswith('cat '):return '{}'
                if args[0]=='shell' and args[1].startswith('sha256sum '):
                    if '.next' not in args[1]: return ''
                    return ('bad' if self.fail else 'a'*64)+' file'
                return ''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);value=dict(file='forecast_'+'a'*64+'.mp4');(root/value['file']).write_bytes(b'media');(root/'forecast.json').write_text('{}')
            adb=ADB(True)
            with self.assertRaises(RuntimeError):video.publish(adb,root,value)
            self.assertFalse(any('forecast.json' in ' '.join(c) for c in adb.calls if c[0]=='push'))
            adb=ADB();video.publish(adb,root,value)
            pushed=next(i for i,c in enumerate(adb.calls) if c[0]=='push' and c[-1].endswith('forecast.json.next'))
            verified=next(i for i,c in enumerate(adb.calls) if c[0]=='shell' and c[1].startswith('sha256sum ') and '.next' in c[1])
            self.assertGreater(pushed,verified)
            self.assertEqual(adb.calls[pushed+1],('shell','mv '+video.REMOTE+'/forecast.json.next '+video.REMOTE+'/forecast.json'))

    def test_disabled_or_wrong_owner_does_no_network_work(self):
        with patch.object(video,'prepare',side_effect=AssertionError('no fetch')):
            self.assertEqual(video.refresh({})['status'],'disabled')
            with self.assertRaises(RuntimeError):video.refresh(dict(weather_video=dict(enabled=True),owner_host='other-host'))

if __name__=='__main__':unittest.main()
