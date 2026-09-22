"""Release 1.3: duration boundaries, protected pixels and resource budgets."""
import copy
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import *
from effects import *
from resources import render_budget, automatic_cap, ResourceGovernor
from test_engine import asset, config


class LicenseExcerptTests(unittest.TestCase):
    def test_exact_limits_across_frame_rates_and_seeds(self):
        for fps in (25,30,60):
            c=config(fps=fps,first_license=0,license_gap=0,license_count=2)
            for length in (5,5.001,6.999,7,60):
                offsets=[]; durations=[]
                for seed in range(12):
                    p=plan_one([asset('clip',2)],[asset('license',length),asset('short',4.999)],asset('music',25.017),c,seed)
                    validate_plan(p,c)
                    for s in p['segments']:
                        if s['kind']=='license':
                            self.assertEqual(s['asset']['name'],'license')
                            self.assertTrue(5*fps<=s['frames']<=7*fps)
                            self.assertLessEqual(s['source_start']+s['frames']/fps,length+1e-6)
                            offsets.append(s['source_start']); durations.append(s['frames'])
                if length==60:
                    self.assertGreater(max(offsets),10)
                    self.assertGreater(len(set(durations)),5)

    def test_short_empty_and_tight_schedules(self):
        c=config(license_count=1,first_license=0,license_gap=0)
        for licenses in ([],[asset('short',4.999)]):
            with self.assertRaises(UserError): plan_one([asset('c',1)],licenses,asset('m',40),c,8)
        p=plan_one([asset('c',1)],[asset('l',12)],asset('m',6.034),c,8)
        validate_plan(p,c)
        self.assertEqual(next(s['frames'] for s in p['segments'] if s['kind']=='license'),150)

    def test_stale_or_tampered_plans_rejected(self):
        c=config(license_count=1,first_license=0)
        original=plan_one([asset('c',1)],[asset('l',20)],asset('m',10),c,12)
        for mutate in (lambda p:p.pop('plan_version'),lambda p:next(s for s in p['segments'] if s['kind']=='license').update(frames=1510),lambda p:next(s for s in p['segments'] if s['kind']=='license').update(source_start=19),lambda p:next(s for s in p['segments'] if s['kind']=='license').update(fx_in='flash')):
            p=copy.deepcopy(original); mutate(p)
            with self.assertRaises(UserError): validate_plan(p,c)


class ResourceTests(unittest.TestCase):
    def test_limits_and_memory_fallback(self):
        for cores in (1,2,4,8,16,64,256):
            for ram in (.2,2,4,32,256):
                for profile in ('auto','medium','high'):
                    p=render_budget(config(resources=profile),['cpu','gpu'],cores,ram)
                    for device,limits in p['lanes'].items():
                        self.assertTrue(1<=limits['segment_workers']<=(4 if device=='cpu' else 3))
                        self.assertTrue(1<=limits['encoder_threads']<=32)
                    if ram==.2: self.assertFalse(p['parallel_lanes'])
        low=render_budget(config(resources='auto'),['cpu','gpu'],32,32)
        high=render_budget(config(resources='high'),['cpu','gpu'],32,32)
        self.assertGreater(high['lanes']['cpu']['segment_workers'],low['lanes']['cpu']['segment_workers'])
        self.assertGreater(high['lanes']['gpu']['segment_workers'],low['lanes']['gpu']['segment_workers'])

    def test_auto_subtracts_own_work_and_reserves_headroom(self):
        self.assertEqual(automatic_cap((0,0,0),(0,100,80)),60)
        self.assertEqual(automatic_cap((0,0,0),(0,100,10)),15)
        self.assertEqual(automatic_cap((0,0,0),(20,100,40)),40)
        self.assertEqual(automatic_cap((0,0,0),(0,0,0)),40)

    def test_windows_governor_applies_aggregate_cap_and_clears(self):
        # Windows integration remains a native acceptance test; verify lifecycle here.
        from unittest.mock import Mock
        job=Mock();messages=[]
        with patch('resources.os.name','nt'),patch('resources._JOB',job):
            g=ResourceGovernor('medium',messages.append);g.start();g.close()
        self.assertEqual(job.cap.call_args_list[0].args,(60,))
        self.assertEqual(job.cap.call_args_list[-1].args,(None,))


class EffectTests(unittest.TestCase):
    def test_all_effects_cycle_covers_six_and_preserves_legacy_motion_mix(self):
        c=config(license_count=1,first_license=3,mode='beat',cut_min=.5,cut_max=1,effect_gap=.5)
        analysis={'cuts':list(range(1,40)), 'strong':list(range(1,40))}
        original=plan_one([asset('clip',1)],[asset('license',7)],asset('music',40),c,9,analysis)
        for preset,expected in [('all',EFFECTS),('edit',MOTION_EFFECTS)]:
            plan=copy.deepcopy(original)
            assign_effects(plan['segments'],preset,9,plan['strong_frames'],30,.5)
            validate_plan(plan,c)
            used=[s['fx_in'] for s in plan['segments'] if s.get('fx_in')]
            self.assertGreaterEqual(len(used),len(expected)*2)
            self.assertEqual(used,list(expected)*(len(used)//len(expected))+list(expected)[:len(used)%len(expected)])
            self.assertEqual(fingerprint(plan),fingerprint(original))
            self.assertTrue(all(s['start'] in plan['strong_frames'] for s in plan['segments'] if s.get('fx_in')))
            for i,s in enumerate(plan['segments']):
                if s['kind']=='license':
                    self.assertNotIn('fx_in',s);self.assertNotIn('fx_out',s)
                    self.assertNotIn('fx_out',plan['segments'][i-1])
                    if i+1<len(plan['segments']):self.assertNotIn('fx_in',plan['segments'][i+1])
        validated=validate(dict(clips='c',licenses='l',music='m',output='o',effects='all'))
        self.assertEqual(validated['effects'],'all')
        self.assertEqual(validate(dict(clips='c',licenses='l',music='m',output='o'))['effects'],'off')

    def test_effect_assignment_preserves_timing_and_protects_license_boundaries(self):
        for mode in ('random','beat'):
            c=config(license_count=1,first_license=3,mode=mode)
            p=plan_one([asset('a',1),asset('b',2)],[asset('l',20)],asset('m',25),c,8,list(range(25)))
            old=fingerprint(p)
            for preset in PRESETS:
                p['strong_frames']=list(range(30,750,30))
                assign_effects(p['segments'],preset,p['seed'],p['strong_frames'],30,2);validate_plan(p,c)
                self.assertEqual(old,fingerprint(p))
                for s in p['segments']:
                    if s['kind']=='license':
                        self.assertNotIn('fx_in',s);self.assertNotIn('fx_out',s)
                        self.assertEqual(effect_filters({**s,'fx_in':'flash','fx_out':'zoom'},30,1280,720),[])

    def test_real_effects_leave_every_licensed_frame_identical(self):
        """Decode every licensed frame, not just its midpoint, and compare hashes."""
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); fps=25
            execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i','testsrc2=s=160x90:r=25:d=1','-threads','1','-c:v','libx264',str(root/'clip.mp4')])
            execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i','testsrc2=s=90x160:r=25:d=9','-threads','1','-c:v','libx264',str(root/'license.mp4')])
            execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i','sine=frequency=330:duration=24',str(root/'song.wav')])
            c=config(fps=fps,license_count=1,first_license=3)
            original=plan_one([probe(root/'clip.mp4','video')],[probe(root/'license.mp4','video')],probe(root/'song.wav','audio'),c,14)
            # The all-effects preset covers every filter, with licenses mid-video.
            ordinary=original['segments']; chosen=[]
            for a,b in zip(ordinary,ordinary[1:]):
                if a['kind']==b['kind']=='clip' and min(a['frames'],b['frames'])>=4: chosen.append((a,b))
            self.assertGreaterEqual(len(chosen),6)
            changed=copy.deepcopy(original)
            boundaries=[(a,b) for a,b in zip(changed['segments'],changed['segments'][1:]) if a['kind']==b['kind']=='clip' and min(a['frames'],b['frames'])>=4]
            changed['strong_frames']=[b['start'] for a,b in boundaries]
            assign_effects(changed['segments'],'all',changed['seed'],changed['strong_frames'],fps,.5)
            active=[(a,b) for a,b in boundaries if b.get('fx_in')]
            self.assertEqual({b['fx_in'] for a,b in active},set(EFFECTS))
            validate_plan(changed,c)
            for name,plan in [('off',original),('on',changed)]:
                values=[];render(plan,c,root/name,'libx264',threading.Event(),values.append)
                self.assertEqual(values[-1],1);self.assertEqual(values,sorted(values))
                self.assertFalse(list((root/name).glob('_work_*')))
            def frame_hashes(path):
                data=execute([binary('ffmpeg'),'-v','error','-threads','1','-i',str(path),'-map','0:v','-an','-f','framemd5','-'])
                return [s.rsplit(',',1)[-1].strip() for s in data.splitlines() if s and not s.startswith('#')]
            before=frame_hashes(root/'off/video.mp4');after=frame_hashes(root/'on/video.mp4')
            self.assertEqual(len(before),len(after));self.assertEqual(len(before),600)
            lic=next(s for s in original['segments'] if s['kind']=='license')
            start=lic['start'];end=start+lic['frames']
            self.assertEqual(before[start:end],after[start:end])
            for left,right in active:
                effect=right['fx_in']
                index=right['start']
                self.assertNotEqual(before[index-3:index+4],after[index-3:index+4],effect)
            self.assertEqual((root/'off/Litsen_video_malumot.xlsx').read_bytes(),(root/'on/Litsen_video_malumot.xlsx').read_bytes())

    def test_parallel_failure_cancels_active_children_and_cleans_work(self):
        c=config(license_count=0,first_license=0)
        p=plan_one([asset('clip',1)],[],asset('music',6),c,1)
        running=threading.Event();cancelled=threading.Event()
        def execute_fake(args,stop=None,**kwargs):
            if '-vf' not in args:return ''
            if args[-1].endswith('00000.mp4'):
                running.wait(2);raise UserError('bad input')
            running.set()
            while not stop.wait(.01):pass
            cancelled.set();raise Cancelled()
        with tempfile.TemporaryDirectory() as tmp,patch('engine.execute',side_effect=execute_fake),patch('engine.probe',return_value={'duration':6}),patch('engine.verify_input'):
            with self.assertRaises(UserError):render(p,c,tmp,'libx264',threading.Event(),lambda value:None)
            self.assertTrue(cancelled.is_set());self.assertFalse(list(Path(tmp).glob('_work_*')))


if __name__=='__main__':unittest.main(verbosity=2)
