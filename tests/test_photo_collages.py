"""Synthetic-only collage grouping, deduplication, rendering and publication safety."""
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'scripts/memories'
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result
collages, sync = module('collages'), module('sync')


def fp(color=20, key='a', difference='0000000000000000', width=256, height=192):
    return dict(version=1, width=width, height=height, pixelHash=hashlib.sha256(key.encode()).hexdigest(),
                differenceHash=difference, colorGrid=[color] * 192)


class PhotoCollageTest(unittest.TestCase):
    def test_balanced_pages_never_repeat_or_leave_a_single_photo(self):
        for size in range(2, 61):
            pages = collages.groups(list(range(size)))
            self.assertEqual([n for page in pages for n in page], list(range(size)))
            self.assertTrue(all(2 <= len(page) <= 4 for page in pages))
        self.assertEqual(collages.groups([1]), [])
        self.assertEqual(collages.groups([]), [])

    def test_visual_match_is_conservative_about_color_aspect_and_shape(self):
        self.assertTrue(collages.same_photo(fp(), fp(key='a')))
        self.assertTrue(collages.same_photo(fp(), fp(color=21, key='reencoded', difference='0000000000000001')))
        self.assertFalse(collages.same_photo(fp(), fp(color=70, key='other')))
        self.assertFalse(collages.same_photo(fp(), fp(key='other', difference='ffffffffffffffff')))
        self.assertFalse(collages.same_photo(fp(), fp(key='other', width=192, height=256)))
        for bad in [dict(fp(), colorGrid=[]), dict(fp(), differenceHash='bad'), dict(fp(), version=0)]:
            with self.assertRaises(RuntimeError): collages.fingerprint(bad)

    def test_duplicate_files_and_matching_pixels_are_removed_before_packing(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory); entries = []
            values = ['a', 'b', 'c', 'd', 'e', 'a', 'metadata-copy']
            for i, value in enumerate(values):
                source = state / ('input' + str(i)); source.write_text(value)
                entries.append(dict(source=source, taken=dt.date(2000+i, 11, 5),
                                    proof=dict(eligible=True, curationVersion=1, curationReason='people')))
            def native(helper, *args):
                if args[0] == '--fingerprint':
                    key = Path(args[1]).read_text(); key = 'a' if key == 'metadata-copy' else key
                    return fp(color=20 + 35 * 'abcde'.index(key), key=key)
                manifest = json.loads(Path(args[0]).read_text());Path(args[1]).write_bytes(b'JPEG')
                return dict(width=1920, height=1080, photos=len(manifest['photos']), frameFill='blur')
            with patch.object(collages, 'native', side_effect=native):
                frames, stats = collages.prepare(dict(image_helper='fixture'), state, entries, 'memories')
            self.assertEqual((stats['uniquePhotos'], stats['duplicatesRemoved'], len(frames)), (5, 2, 2))
            records = json.loads((state / 'collage-memories.json').read_text())
            members = [p['sourceSHA256'] for page in records.values() for p in page['members']]
            self.assertEqual(len(members), len(set(members)))
            self.assertEqual(sorted(page['photos'] for page in records.values()), [2, 3])
            self.assertTrue(all(sync.NAME.fullmatch(p.name) and p.name.endswith('_c.jpg') for p in frames))

    def test_lone_dates_are_not_mixed_into_false_anniversary_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory); entries=[]
            for i in range(2):
                source=state/str(i);source.write_text(str(i))
                entries.append(dict(source=source, taken=dt.date(2000, 11, 5+i), proof=dict(eligible=True, curationVersion=1)))
            with patch.object(collages, 'native', side_effect=[fp(), fp(color=100,key='b')]):
                frames,stats=collages.prepare(dict(image_helper='fixture'),state,entries,'memories')
            self.assertEqual(frames,[]);self.assertEqual(stats['unpairedPhotos'],2)

    def test_uncurated_or_failed_collages_never_activate_a_new_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir();state=root/'state';state.mkdir()
            old_index=state/'index.txt';old_index.write_text('prior-complete-generation\n')
            for year in range(2000,2005):
                (source/(str(year)+'-'+dt.date.today().strftime('%m-%d')+'.jpg')).write_text(str(year))
            config=dict(owner_host=socket.gethostname(),sources=[str(source)],state_dir=str(state),
                        image_helper='fixture-image',photo_collages=True,suitable_only=True,days_ahead=0)
            def image(args,**kwargs):
                Path(args[2]).write_bytes(b'frame')
                return subprocess.CompletedProcess(args,0,json.dumps(dict(taken=None,curation=dict(version=1,
                    faces=1,people=1,textBlocks=0,sceneScore=0.,documentScore=0.,textCoverage=0.))), '')
            rendered=[]
            def native(helper,*args):
                if args[0]=='--fingerprint':
                    key=Path(args[1]).read_text();return fp(color=20+35*(int(key)-2000),key=key)
                rendered.append(1)
                if len(rendered)==2:raise RuntimeError('fixture render failure')
                manifest=json.loads(Path(args[0]).read_text());Path(args[1]).write_bytes(b'JPEG')
                return dict(width=1920,height=1080,photos=len(manifest['photos']),frameFill='blur')
            with patch.dict(sys.modules,collages=collages),patch.object(sync.subprocess,'run',side_effect=image), \
                 patch.object(collages,'native',side_effect=native),patch.object(sync,'ADB') as adb:
                with self.assertRaises(RuntimeError):sync.refresh(config)
                adb.assert_not_called()
            self.assertEqual(old_index.read_text(),'prior-complete-generation\n')
            # A later successful attempt reuses completed analysis/frames and
            # still leaves the published index alone in prepare-only mode.
            with patch.dict(sys.modules,collages=collages),patch.object(sync.subprocess,'run',side_effect=image) as converter, \
                 patch.object(collages,'native',side_effect=native):
                result=sync.refresh(config,prepare_only=True)
                converter.assert_not_called()
            self.assertEqual((result['photos'],result['sourcePhotos'],result['duplicatesRemoved']),(2,5,0))
            self.assertEqual(old_index.read_text(),'prior-complete-generation\n')
            self.assertEqual(len(list((state/'frames').glob('*.jpg'))),5)
            bad=[dict(source=next(source.iterdir()),taken=dt.date(2000,11,5),proof=dict(eligible=False,curationVersion=1))]
            with self.assertRaises(RuntimeError):collages.prepare(config,state,bad,'memories')

    def test_collage_refresh_reuses_curated_input_frames_and_bounds_fingerprint_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory); (state/'collages').mkdir()
            obsolete=state/'collages/2000-11-05_0123456789abcdef_c.jpg';obsolete.write_bytes(b'old')
            collages.atomic_json(state/'collage-analysis.json',{'kept':fp(),'old':fp()})
            collages.prune(state,set(),{'kept'})
            self.assertFalse(obsolete.exists())
            self.assertEqual(set(json.loads((state/'collage-analysis.json').read_text())),{'kept'})


@unittest.skipUnless(sys.platform=='darwin' and shutil.which('swiftc'), 'macOS native renderer')
class NativeCollageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:from PIL import Image
        except ImportError:raise unittest.SkipTest('Pillow is required only for synthetic native renderer checks')
        cls.Image=Image;cls.workspace=tempfile.TemporaryDirectory();cls.root=Path(cls.workspace.name);cls.helper=cls.root/'collage'
        subprocess.run(['swiftc','-O',str(ROOT/'collage.swift'),'-o',str(cls.helper)],check=True,capture_output=True,timeout=60)
    @classmethod
    def tearDownClass(cls):cls.workspace.cleanup()
    def test_normalization_detects_metadata_copies_and_jpeg_reencoding(self):
        from PIL.PngImagePlugin import PngInfo
        image=self.Image.new('RGB',(320,240));image.putdata([(x//2,y//2,(x+y)//3) for y in range(240) for x in range(320)])
        paths=[self.root/'original.png',self.root/'metadata.png',self.root/'encoded.jpg']
        image.save(paths[0]);meta=PngInfo();meta.add_text('fixture','different metadata');image.save(paths[1],pnginfo=meta,compress_level=1)
        image.save(paths[2],quality=75)
        fingerprints=[collages.fingerprint(collages.native(self.helper,'--fingerprint',p)) for p in paths]
        self.assertNotEqual(collages.source_hash(paths[0]),collages.source_hash(paths[1]))
        self.assertEqual(fingerprints[0]['pixelHash'],fingerprints[1]['pixelHash'])
        self.assertTrue(collages.same_photo(fingerprints[0],fingerprints[2]))
    def test_collages_are_full_hd_uncropped_and_metadata_free(self):
        portrait=self.Image.new('RGB',(300,600),'red');landscape=self.Image.new('RGB',(600,300),'blue')
        for image in [portrait,landscape]:
            w,h=image.size
            for x,y,color in [(0,0,'lime'),(w-60,0,'yellow'),(0,h-60,'cyan'),(w-60,h-60,'magenta')]:
                image.paste(color,(x,y,x+60,y+60))
        sources=[self.root/'portrait.png',self.root/'landscape.png'];portrait.save(sources[0]);landscape.save(sources[1])
        for count in [2,3,4]:
            manifest=self.root/'manifest.json';output=self.root/('page'+str(count)+'.jpg')
            # Layout-only fixture may reuse sources; production grouping prevents repetition.
            manifest.write_text(json.dumps({'version':1,'photos':[{'path':str(sources[i%2]),'caption':'2008'} for i in range(count)]}))
            result=collages.native(self.helper,manifest,output);self.assertEqual(result['photos'],count)
            with self.Image.open(output) as image:
                self.assertEqual(image.size,(1920,1080))
                # ImageIO may add color-space EXIF. Original GPS/camera/capture fields are absent.
                for tag in [34853, 271, 272, 306, 270]:self.assertNotIn(tag,image.getexif())
                if count==2:
                    # Portrait fits completely: 300x600 -> 524x1048, centered in the left cell.
                    for point,expected in [((240,35),(0,255,0)),((715,35),(255,255,0)),
                                           ((240,1040),(0,255,255)),((715,1040),(255,0,255))]:
                        actual=image.getpixel(point);self.assertLess(max(abs(a-b) for a,b in zip(actual,expected)),35)

if __name__=='__main__':unittest.main()
