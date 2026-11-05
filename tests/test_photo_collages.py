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
    return dict(version=2, orientationMode="metadata", description="", width=width, height=height, pixelHash=hashlib.sha256(key.encode()).hexdigest(),
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
                return dict(width=1920, height=1080, photos=len(manifest['photos']), frameFill='scrapbook')
            with patch.object(collages, 'native', side_effect=native):
                frames, stats = collages.prepare(dict(image_helper='fixture'), state, entries, 'memories')
            self.assertEqual((stats['uniquePhotos'], stats['duplicatesRemoved'], len(frames)), (5, 2, 2))
            records = json.loads((state / 'collage-memories.json').read_text())
            members = [p['sourceSHA256'] for page in records.values() for p in page['members']]
            self.assertEqual(len(members), len(set(members)))
            self.assertEqual(sorted(page['photos'] for page in records.values()), [2, 3])
            self.assertTrue(all(sync.NAME.fullmatch(p.name) and p.name.endswith('_s.jpg') for p in frames))

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
                return dict(width=1920,height=1080,photos=len(manifest['photos']),frameFill='scrapbook')
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
            self.assertEqual(result['frameFill'],'scrapbook')
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

    def test_captions_use_existing_descriptions_or_factual_dates(self):
        for generic in ['SONY DSC', 'OLYMPUS DIGITAL CAMERA', 'IMG_0123.JPG', 'untitled',
                        'https://example.org/image', 'Copyright photographer', '12345']:
            self.assertEqual(collages.useful_description(generic), '')
        entry=dict(taken=dt.date(2010,11,5),fingerprint=dict(description='Hiking by the lake'))
        self.assertEqual(collages.photo_caption(entry,'memories'),'Hiking by the lake · 2010')
        entry['fingerprint']['description']='SONY DSC'
        self.assertEqual(collages.photo_caption(entry,'memories'),'2010')
        self.assertEqual(collages.page_title([entry,entry]),'November 5, 2010')
        self.assertEqual(collages.page_title([entry,dict(taken=dt.date(2008,11,5))]),
                         'November 5 · Through the years')

    def test_old_analysis_recomputes_without_invalidating_published_index(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory);entries=[]
            for i in range(2):
                path=state/str(i);path.write_text(str(i))
                entries.append(dict(source=path,taken=dt.date(2010,11,5),
                                    proof=dict(eligible=True,curationVersion=1)))
            collages.atomic_json(state/'collage-analysis.json',
                {collages.source_hash(e['source']):dict(fp(),version=1) for e in entries})
            manifests=[]
            def native(helper,*args):
                if args[0]=='--fingerprint':
                    i=int(Path(args[1]).read_text());return dict(fp(color=20+i*50,key=str(i)),orientationMode='pixels')
                value=json.loads(Path(args[0]).read_text());manifests.append(value);Path(args[1]).write_bytes(b'JPEG')
                return dict(width=1920,height=1080,photos=2,frameFill='scrapbook',layout=[dict(index=0)])
            with patch.object(collages,'native',side_effect=native) as render:
                frames,_=collages.prepare(dict(image_helper='fixture'),state,entries,'memories')
                self.assertEqual(render.call_count,3)
                # Existing pages and their geometry are reused, never silently reverting to grid output.
                collages.prepare(dict(image_helper='fixture'),state,entries,'memories')
                self.assertEqual(render.call_count,3)
            self.assertEqual(manifests[0]['version'],2)
            self.assertTrue(all(p['orientationMode']=='pixels' for p in manifests[0]['photos']))
            self.assertEqual(json.loads((state/'collage-memories.json').read_text())[frames[0].name]['layout'],[dict(index=0)])


@unittest.skipUnless(sys.platform=='darwin' and shutil.which('swiftc'), 'macOS native renderer')
class NativeCollageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:from PIL import Image
        except ImportError:raise unittest.SkipTest('Pillow is required only for synthetic native renderer checks')
        cls.Image=Image;cls.workspace=tempfile.TemporaryDirectory();cls.root=Path(cls.workspace.name);cls.helper=cls.root/'collage'
        shutil.copy(ROOT/'collage.swift', cls.root/'main.swift')
        subprocess.run(['swiftc','-O',str(cls.root/'main.swift'),str(ROOT/'PhotoLayout.swift'),'-o',str(cls.helper)],check=True,capture_output=True,timeout=60)
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

    def test_scrapbook_preserves_photo_shapes_corners_and_source_metadata_privacy(self):
        import math
        portrait=self.Image.new('RGB',(300,600),'red');landscape=self.Image.new('RGB',(600,300),'blue')
        for image in [portrait,landscape]:
            w,h=image.size
            for x,y,color in [(0,0,'lime'),(w-60,0,'yellow'),(0,h-60,'cyan'),(w-60,h-60,'magenta')]:
                image.paste(color,(x,y,x+60,y+60))
        sources=[self.root/'portrait.png',self.root/'landscape.png'];portrait.save(sources[0]);landscape.save(sources[1])
        for count in [2,3,4]:
            manifest=self.root/'scrapbook.json';output=self.root/('scrapbook'+str(count)+'.jpg')
            manifest.write_text(json.dumps(dict(version=2,seed='abcdef1234567890',title='November 5, 2008',
                photos=[dict(path=str(sources[i%2]),caption='2008',orientationMode='metadata') for i in range(count)])))
            result=collages.native(self.helper,manifest,output)
            self.assertEqual(result['frameFill'],'scrapbook')
            with self.Image.open(output) as image:
                self.assertEqual(image.size,(1920,1080))
                for tag in [34853,271,272,306,270]:self.assertNotIn(tag,image.getexif())
                for p in result['layout']:
                    w,h=p['width'],p['height'];index=p['index']
                    self.assertAlmostEqual((w-30)/(h-82),0.5 if index%2==0 else 2.0,places=5)
                    self.assertTrue(0.03<abs(p['angle'])<0.075)
                    # Check colored source corners through the real rotation and image coordinate transforms.
                    for u,v,color in [(0.04,0.04,(0,255,255)),(0.96,0.04,(255,0,255)),
                                      (0.04,0.96,(0,255,0)),(0.96,0.96,(255,255,0))]:
                        x=-w/2+15+(w-30)*u;y=-h/2+67+(h-82)*v
                        a=p['angle'];px=p['x']+x*math.cos(a)-y*math.sin(a)
                        py=1080-(p['y']+x*math.sin(a)+y*math.cos(a))
                        actual=image.getpixel((round(px),round(py)))
                        self.assertLess(max(abs(a-b) for a,b in zip(actual,color)),45)

    def test_orientation_repair_requires_strong_upright_evidence(self):
        main=self.root/'policy/main.swift';main.parent.mkdir(exist_ok=True)
        main.write_text('''
import Foundation
let upright = FacePose(confidence:0.85,area:0.03,roll:0.05)
let sideways = FacePose(confidence:0.85,area:0.03,roll:1.6)
let weak = FacePose(confidence:0.5,area:0.03,roll:0)
precondition(orientationMode(tag:6,raw:[upright],metadata:[sideways]) == "pixels")
precondition(orientationMode(tag:8,raw:[upright],metadata:[]) == "pixels")
precondition(orientationMode(tag:3,raw:[upright],metadata:[upright]) == "metadata")
precondition(orientationMode(tag:6,raw:[weak],metadata:[sideways]) == "metadata")
precondition(orientationMode(tag:8,raw:[],metadata:[]) == "metadata")
precondition(orientationMode(tag:2,raw:[upright],metadata:[]) == "metadata")
for aspects: [CGFloat] in [[0.5,0.7],[2,1.3],[0.5,0.6,1.7],[0.5,0.6,0.7,0.8],[2,1.4,1.6,1.5],[0.6,2,1.5,1.8]] {
    for seed in UInt64(0)..<100 {
        for p in scrapbookLayout(aspects, seed:seed) {
            precondition(p.bounds.minX >= 41.99 && p.bounds.maxX <= 1878.01)
            precondition(p.bounds.minY >= 39.99 && p.bounds.maxY <= 958.01)
        }
    }
}
''')
        executable=main.parent/'policy'
        subprocess.run(['swiftc',str(main),str(ROOT/'PhotoLayout.swift'),'-o',str(executable)],check=True,capture_output=True,timeout=60)
        subprocess.run([str(executable)],check=True,capture_output=True,timeout=30)

if __name__=='__main__':unittest.main()
