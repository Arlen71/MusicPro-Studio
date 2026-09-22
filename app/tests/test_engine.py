import sys, unittest, math, tempfile, threading, json, subprocess
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import *

def asset(name,duration): return dict(path=name,name=name,duration=duration,size=1,mtime=1)
def config(**kw):
    d=dict(fps=30,first_license=60,license_gap=12,license_count=3,mode='random',cut_min=2,cut_max=7,height=720,quality='economy',_render_budget=dict(segment_workers=2,encoder_threads=2,filter_threads=1,decode_threads=1));d.update(kw);return d

class PlannerTests(unittest.TestCase):
    def test_license_integrity_and_unique_cycles_across_seeds(self):
        clips=[asset(f'c{i}',i+3.1) for i in range(7)]
        licenses=[asset(f'l{i}',i+4.03) for i in range(4)]
        for mode in ('random','beat'):
            for seed in range(30):
                c=config(mode=mode);p=plan_one(clips,licenses,asset('song',182.123),c,seed,list(range(1,180)))
                self.assertEqual(sum(s['frames'] for s in p['segments']),math.ceil(182.123*30))
                licensed=[s for s in p['segments'] if s['kind']=='license'];self.assertEqual(len(licensed),3)
                self.assertGreaterEqual(licensed[0]['start'],60*30)
                for s in licensed:
                    self.assertGreaterEqual(s['frames'],5*30)
                    self.assertLessEqual(s['frames'],7*30)
                    self.assertGreaterEqual(s['source_start'],0)
                    self.assertLessEqual(s['source_start']+s['frames']/30,s['asset']['duration']+1e-6)
                    self.assertGreaterEqual(s['asset']['duration'],5)
                    idx=p['segments'].index(s);self.assertEqual(p['segments'][idx-1]['kind'],'clip')
                for a,b in zip(licensed,licensed[1:]):self.assertGreaterEqual(b['start']-a['start']-a['frames'],12*30)
                ordinary=[s for s in p['segments'] if s['kind']=='clip']
                for i in range(0,len(ordinary),len(clips)):
                    names=[s['asset']['path'] for s in ordinary[i:i+len(clips)]];self.assertEqual(len(names),len(set(names)))
                if mode=='random':
                    for s in ordinary[:-1]:self.assertEqual(s['frames'],math.ceil(s['asset']['duration']*30-1e-7))
    def test_impossible_rejected(self):
        with self.assertRaises(UserError):plan_one([asset('c',10)],[asset('l',20)],asset('m',65),config(),1)
    def test_no_license_and_short_final(self):
        p=plan_one([asset('c',10)],[],asset('m',3.1),config(license_count=0),1)
        self.assertEqual(p['total_frames'],93);self.assertEqual(len(p['segments']),1)
    def test_full_boundary_overrides_earliest(self):
        p=plan_one([asset('c',17)],[asset('l',8)],asset('m',80),config(license_count=1),2)
        s=next(s for s in p['segments'] if s['kind']=='license');self.assertEqual(s['start']/30,68)
    def test_reproducible(self):
        args=([asset('c1',5),asset('c2',7)],[asset('l',5)],asset('m',100),config(license_count=1),83)
        self.assertEqual(fingerprint(plan_one(*args)),fingerprint(plan_one(*args)))
    def test_invalid_config(self):
        for value in ('NaN',1.5,0):
            with self.assertRaises(UserError):validate(dict(clips='c',licenses='l',music='m',output='o',total=value))

class RenderTests(unittest.TestCase):
    def test_real_render_audio_geometry_and_license_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for name,color,dur,size in [('clip','blue',1,'160x90'),('license','red',9,'90x160')]:
                execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'color={color}:s={size}:r=25:d={dur}','-c:v','libx264',str(p/f'{name}.mp4')])
            execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=10.137',str(p/'song.wav')])
            c=config(fps=25,first_license=1,license_gap=.2,license_count=1)
            plan=plan_one([probe(p/'clip.mp4','video')],[probe(p/'license.mp4','video')],probe(p/'song.wav','audio'),c,19)
            real_execute=execute
            failed_once=[]
            def first_segment_error(args,*params,**kwargs):
                if '-vf' in args and not failed_once:
                    failed_once.append(True)
                    raise UserError('Simulated first-segment CPU initialization failure')
                return real_execute(args,*params,**kwargs)
            with patch('engine.execute',side_effect=first_segment_error):
                render(plan,c,p/'result','libx264',threading.Event(),lambda v:None)
            self.assertTrue(failed_once)
            self.assertIn('Urinish: 1',(p/'result/render_diagnostics.txt').read_text())
            v=probe(p/'result/video.mp4','video');a=probe(p/'result/video.mp4','audio')
            self.assertLess(abs(v['duration']-10.137),.05);self.assertLess(abs(a['duration']-10.137),.03)
            info=json.loads(execute([binary('ffprobe'),'-v','error','-show_streams','-of','json',str(p/'result/video.mp4')]))
            vs=next(s for s in info['streams'] if s['codec_type']=='video');self.assertEqual((vs['width'],vs['height']),(1280,720))
            lic=next(s for s in plan['segments'] if s['kind']=='license')
            # At center of licensed interval: red portrait center with black sidebars, not cropped.
            raw=subprocess.check_output([binary('ffmpeg'),'-v','error','-ss',str((lic['start']+lic['frames']/2)/25),'-i',str(p/'result/video.mp4'),'-frames:v','1','-vf','scale=16:9','-f','rawvideo','-pix_fmt','rgb24','-'])
            center=raw[(4*16+8)*3:(4*16+8)*3+3];side=raw[(4*16)*3:(4*16)*3+3]
            self.assertGreater(center[0],150);self.assertLess(center[2],60);self.assertLess(max(side),30)
            from reports import REPORT_NAME
            self.assertTrue((p/'result'/REPORT_NAME).is_file())
            self.assertFalse((p/'result/hisobot.txt').exists())
            self.assertFalse(list((p/'result').glob('_work_*')))
    def test_energy_onsets(self):
        import wave,struct
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'pulses.wav'
            with wave.open(str(p),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(8000)
                f.writeframes(b''.join(struct.pack('<h',int((18000 if i%8000<800 else 100)*math.sin(2*math.pi*440*i/8000))) for i in range(32000)))
            peaks=detect_accents(p)
            self.assertTrue(any(abs(t-1)<.15 for t in peaks),peaks)
    def test_cancel(self):
        e=threading.Event();e.set()
        with self.assertRaises(Cancelled):execute([sys.executable,'-c','import time;time.sleep(20)'],e)

if __name__=='__main__':unittest.main(verbosity=2)
