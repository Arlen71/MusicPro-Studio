"""Behavioral acceptance: strong-only FX and unattended substitution."""
import json
import math
import struct
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from engine import *
from failures import StorageError
from batch import BatchRecovery, issue_csv
from failures import error_record, raise_record
from test_engine import config, asset


class AccentTests(unittest.TestCase):
    def test_low_frame_rate_license_can_end_at_source_end_in_60fps_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,duration in [('clip',3),('license',9)]:
                execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'testsrc2=s=160x90:r=12:d={duration}',
                         '-threads','1','-c:v','libx264',str(root/(name+'.mp4'))])
            execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i','sine=frequency=330:duration=8.137',str(root/'song.wav')])
            clip=probe(root/'clip.mp4','video');licensed=probe(root/'license.mp4','video');music=probe(root/'song.wav','audio')
            c=config(fps=60,license_count=1,first_license=1,mode='beat')
            total=math.ceil(music['duration']*60)
            p=dict(plan_version=4,music=music,seed=1,fps=60,total_frames=total,strong_frames=[],segments=[
                dict(kind='clip',asset=clip,start=0,frames=60,source_start=0),
                dict(kind='license',asset=licensed,start=60,frames=304,source_start=round(236/60,6)),
                dict(kind='clip',asset=clip,start=364,frames=total-364,source_start=0)])
            render(p,c,root/'out','libx264',threading.Event(),lambda value:None)
            self.assertTrue((root/'out/video.mp4').exists())

    def test_clean_short_source_is_not_frozen_to_hide_missing_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=blue:s=160x90:r=25:d=1','-threads','1','-c:v','libx264',str(root/'short.mp4')])
            execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i','sine=frequency=330:duration=6',str(root/'song.wav')])
            clip=probe(root/'short.mp4','video');clip['duration']=4  # misleading container duration
            c=config(fps=25,license_count=0,first_license=0)
            p=plan_one([clip],[],probe(root/'song.wav','audio'),c,1)
            with self.assertRaises(SourceError) as caught:render(p,c,root/'out','libx264',threading.Event(),lambda value:None)
            self.assertEqual(caught.exception.role,'clip')
            self.assertFalse((root/'out/video.mp4').exists())

    def test_real_audio_strong_hits_only_not_weak_or_steady(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'weak_and_strong.wav';rate=12000
            with wave.open(str(path),'wb') as f:
                f.setnchannels(2);f.setsampwidth(2);f.setframerate(rate)
                data=bytearray()
                for i in range(10*rate):
                    t=i/rate
                    amplitude=14000 if any(0<=t-x<.12 for x in (1,4,7)) else 1800 if any(0<=t-x<.12 for x in (2,3,5,6,8)) else 150
                    sample=int(amplitude*math.sin(2*math.pi*110*t))
                    data.extend(struct.pack('<hh',sample,sample))
                f.writeframes(data)
            analysis=analyze_music(path)
            self.assertEqual(len(analysis['strong']),3,analysis)
            for actual,expected in zip(analysis['strong'],(1,4,7)):self.assertLess(abs(actual-expected),.05)
            self.assertGreater(len(analysis['cuts']),len(analysis['strong']))
            from audio_analysis import accents_from_envelopes
            for amplitude in (0,150,15000):
                self.assertEqual(accents_from_envelopes([amplitude]*500,[amplitude]*500)['strong'],[])

    def test_only_exact_strong_boundaries_and_clean_cut_between_effects(self):
        c=config(license_count=0,first_license=0,mode='beat',cut_min=.5,cut_max=1,effects='edit',effect_gap=.5)
        analysis={'cuts':[x for x in range(1,12)],'strong':[2,3,4,8]}
        p=plan_one([asset('clip',1)],[],asset('music',12),c,1,analysis)
        active=[s['start']/30 for s in p['segments'] if s.get('fx_in')]
        self.assertEqual(active,[2,4,8])
        for s in p['segments']:
            self.assertNotIn(s.get('fx_in'),('flash','black'))
            self.assertNotIn(s.get('fx_out'),('flash','black'))
        silent=plan_one([asset('clip',1)],[],asset('music',12),c,1,{'cuts':list(range(12)),'strong':[]})
        self.assertEqual(silent['effect_count'],0)
        p['strong_frames']=[]
        with self.assertRaises(UserError):validate_plan(p,c)

    def test_legacy_flash_migrates_to_motion(self):
        for old in ('flash','black'):
            c=validate(dict(clips='c',licenses='l',music='m',output='o',effects=old))
            self.assertEqual(c['effects'],'edit')


class BatchTests(unittest.TestCase):
    def setup_batch(self,root,total=1):
        c=config(total=total,license_count=1,first_license=2,license_gap=1,mode='beat',device='cpu',effects='edit',effect_gap=2)
        catalog={}
        for role,names in {'clip':[('bad_clip',1.1),('good_clip',1.7)],'license':[('bad_license',9),('good_license',11)],'music':[('bad_music',25),('good_music',31)]}.items():
            folder=root/role;folder.mkdir(); c[{'clip':'clips','license':'licenses','music':'music'}[role]]=str(folder)
            catalog[role]=[]
            for name,duration in names:
                path=folder/name;path.write_bytes(b'fixture')
                stat=path.stat();catalog[role].append(dict(path=str(path),name=name,duration=duration,size=stat.st_size,mtime=stat.st_mtime_ns))
        output=root/'output';output.mkdir();c['output']=str(output)
        jobs=[dict(id=i+1,music='',status='pending',progress=0,encoder='libx264',device='cpu',dest=str(output/str(i)),error='') for i in range(total)]
        state={'jobs':jobs,'batch':'test_batch','catalog':catalog}
        recovery=BatchRecovery(c,state,threading.RLock(),threading.Event(),lambda:None,lambda message:None)
        def analysis(path,stop=None):
            a=next(a for a in catalog['music'] if a['path']==path)
            return dict(cuts=list(range(1,int(a['duration']))),strong=list(range(2,int(a['duration']),3)),decoded_duration=a['duration'])
        return c,state,recovery,analysis

    def test_100_jobs_finish_after_bad_clip_license_and_music(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,state,r,analysis=self.setup_batch(Path(tmp),100)
            completed=[]; failures=[]
            with patch('batch.analyze_music',side_effect=analysis):
                for j in state['jobs']:r.prepare(j)
                def renderer(j,conf):
                    for role,a in [('music',j['plan']['music'])]+[(s['kind'],s['asset']) for s in j['plan']['segments']]:
                        if a['name'].startswith('bad_'):
                            failures.append((role,a['path']));raise SourceError(a,role,'Injected damaged media')
                    validate_plan(j['plan'],c);completed.append(j['id'])
                for j in state['jobs']:
                    r.run_job(j,renderer,c);r.completed(j);j['status']='done'
            self.assertEqual(completed,list(range(1,101)))
            self.assertEqual(len(failures),3)  # one exclusion per bad source, shared by the batch
            self.assertEqual(len({fingerprint(j['plan']) for j in state['jobs']}),100)
            self.assertTrue(all(j['plan']['music']['name']=='good_music' for j in state['jobs']))
            self.assertTrue(all(j['plan']['total_frames']==31*30 for j in state['jobs']))
            self.assertTrue(all(len([s for s in j['plan']['segments'] if s['kind']=='license'])==1 for j in state['jobs']))
            self.assertEqual({row['role'] for row in state['issues']},{'clip','license','music'})
            r.save_issues();self.assertTrue(Path(state['issues_path']).is_file())
            restored=json.loads(json.dumps(state))
            self.assertEqual(restored['issues'],state['issues'])

    def test_gpu_error_uses_cpu_without_blacklisting_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,state,r,analysis=self.setup_batch(Path(tmp))
            job=state['jobs'][0];job.update(encoder='h264_nvenc',device='gpu')
            calls=[]
            def renderer(j,conf):
                calls.append(j['encoder'])
                if j['encoder']!='libx264':raise EncoderError('NVENC session failed')
            with patch('batch.analyze_music',side_effect=analysis):r.run_job(job,renderer,c)
            self.assertEqual(calls,['h264_nvenc','libx264'])
            self.assertFalse(any(state['blocked'].values()))

    def test_exhausted_sources_terminate_and_identify_unfinished_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,state,r,analysis=self.setup_batch(Path(tmp))
            calls=[]
            def renderer(j,conf):
                a=next(s['asset'] for s in j['plan']['segments'] if s['kind']=='clip')
                calls.append(a['path']);raise SourceError(a,'clip','Invalid file')
            with patch('batch.analyze_music',side_effect=analysis):
                with self.assertRaisesRegex(UserError,'bo‘lak qolmadi'):r.run_job(state['jobs'][0],renderer,c)
            self.assertEqual(len(calls),2)

    def test_storage_problem_does_not_exclude_music_or_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,state,r,analysis=self.setup_batch(Path(tmp))
            with patch('batch.analyze_music',side_effect=analysis):
                with self.assertRaises(StorageError):r.run_job(state['jobs'][0],lambda j,c:(_ for _ in ()).throw(StorageError('Disk full')),c)
            self.assertFalse(any(state['blocked'].values()))

    def test_changed_source_replans_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,state,r,analysis=self.setup_batch(Path(tmp));job=state['jobs'][0]
            with patch('batch.analyze_music',side_effect=analysis):
                r.prepare(job);a=next(s['asset'] for s in job['plan']['segments'] if s['kind']=='clip')
                Path(a['path']).unlink()
                observed=[];r.run_job(job,lambda j,c:observed.extend(s['asset']['path'] for s in j['plan']['segments']),c)
                self.assertNotIn(a['path'],observed)

    def test_worker_failure_round_trip_and_csv_literal_cells(self):
        original=SourceError({'path':'/l.mp4','name':'l.mp4'},'license','bad frame')
        with self.assertRaises(SourceError) as caught:raise_record(json.loads(json.dumps(error_record(original))))
        self.assertEqual(caught.exception.role,'license')
        csv=issue_csv([dict(time='now',role='clip',name='=1+1',path='/video',reason='bad',action='skipped',jobs=[1])])
        self.assertIn("'=1+1",csv.decode('utf-8-sig'))

if __name__=='__main__':unittest.main(verbosity=2)
