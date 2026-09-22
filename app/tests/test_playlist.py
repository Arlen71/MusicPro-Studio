"""Playlist selection, recovery, sample timing and exact user-facing TXT."""
import array
import copy
import json
import math
import random
import struct
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine import *
from batch import BatchRecovery
from playlist import SAMPLE_RATE, TAGS, audio_assets, clock_samples, compose, text_from_plan, write_playlist
from reports import rows_from_plan
from test_engine import asset, config


def analysis_for(asset):
    samples=round(asset['duration']*SAMPLE_RATE)
    return dict(decoded_duration=samples/SAMPLE_RATE,decoded_samples=samples,sample_rate=SAMPLE_RATE,
                cuts=list(range(1,int(asset['duration']))),strong=list(range(2,int(asset['duration']),3)))


def playlist_plan(assets,c,seed=9,clips=None,licenses=None):
    music,tracks,analysis=compose(assets,[analysis_for(a) for a in assets])
    plan=plan_one(clips or [asset('clip',1.7)],licenses or [],music,c,seed,analysis)
    plan.update(plan_version=5,tracks=tracks)
    return plan


class PlaylistFormatTests(unittest.TestCase):
    def test_exact_txt_header_titles_timestamps_and_literal_tags(self):
        expected_tags='music, music video, new music, hit songs, pop music, official video, trending music, top hits, best songs, viral music, edm, hip hop, rap, acoustic, live performance, music channel, new release, bass boosted, remix, chill vibes, party music, dance track, instrumental, lofi, beats, song of the day, top charts, 2026 hits, music playlist, daily music, good vibes, fresh tunes, audio, sound, popular songs, club mix, trap, indie music, rock, electronic, lo-fi beats, relax music, study music, chill,  '
        self.assertEqual(TAGS,expected_tags)
        names=['Black Eyed Peas – Just Can’t Get Enough.mp3','Kendrick Lamar – All the Stars.FLAC','Nicki Minaj – The Night Is Still Young.m4a','Sia – Elastic Heart.wav']
        assets=[asset(name,duration) for name,duration in zip(names,[218,3421,225,240])]
        music,tracks,_=compose(assets,[analysis_for(a) for a in assets])
        p={'music':music,'tracks':tracks}
        expected=('Music in the playlist/video:\n0:00 Black Eyed Peas – Just Can’t Get Enough\n'
                  '3:38 Kendrick Lamar – All the Stars\n1:00:39 Nicki Minaj – The Night Is Still Young\n'
                  '1:04:24 Sia – Elastic Heart\n\n'+expected_tags+'\n')
        self.assertEqual(text_from_plan(p),expected)
        with tempfile.TemporaryDirectory() as tmp:
            result=write_playlist(p,tmp)
            self.assertEqual(result.name,'Playlist.txt')
            self.assertEqual(result.read_bytes(),expected.encode('utf-8'))
            self.assertEqual([f.name for f in Path(tmp).iterdir()],['Playlist.txt'])
            self.assertIsNone(write_playlist({'music':assets[0]},tmp))

    def test_sample_offsets_are_accumulated_before_flooring_seconds(self):
        assets=[asset('first.mp3',59.75),asset('second.wav',.5),asset('third.flac',3600.25)]
        music,tracks,analysis=compose(assets,[analysis_for(a) for a in assets])
        self.assertEqual([clock_samples(t['start_sample']) for t in tracks],['0:00','0:59','1:00'])
        self.assertEqual(music['samples'],3660.5*SAMPLE_RATE)
        self.assertEqual(clock_samples(3600*SAMPLE_RATE-1),'59:59')
        self.assertEqual(clock_samples(3600*SAMPLE_RATE),'1:00:00')
        self.assertIn(62.25,analysis['strong'])  # third track 60.25 + local strong hit 2

    def test_modes_and_old_single_track_fingerprints_remain_compatible(self):
        raw=dict(clips='clips',licenses='licenses',music='music',output='output')
        self.assertEqual(validate(raw)['music_mode'],'single')
        for count in [0,-1,1.5,'NaN',1001]:
            with self.assertRaises(UserError): validate({**raw,'music_mode':'playlist','playlist_count':count})
        c=config(license_count=0,first_license=0)
        p=plan_one([asset('c',1)],[],asset('m',4),c,3)
        validate_plan(p,{**c,'music_mode':'single','playlist_count':5})
        rows=[(s['asset']['path'],s['start'],s['frames'],s['source_start'],s['kind']) for s in p['segments']]
        self.assertEqual(fingerprint(p),hashlib.sha256(json.dumps([p['music']['path'],rows],sort_keys=True).encode()).hexdigest())
        self.assertEqual(text_from_plan(p),'')
        with self.assertRaises(UserError): validate_plan(p,{**c,'music_mode':'playlist'})

    def test_playlist_plan_rejects_duplicates_wrong_counts_offsets_and_mode(self):
        c=config(music_mode='playlist',playlist_count=2,license_count=0,first_license=0)
        p=playlist_plan([asset('a.mp3',3.25),asset('b.mp3',4.5)],c)
        validate_plan(p,c)
        for mutate in [lambda x:x['tracks'][1].update(start_sample=0),
                       lambda x:x['tracks'][1].update(asset=x['tracks'][0]['asset']),
                       lambda x:x['music'].update(duration=8),
                       lambda x:x['tracks'].pop(),lambda x:x.update(plan_version=4)]:
            changed=copy.deepcopy(p);mutate(changed)
            with self.assertRaises(UserError):validate_plan(changed,c)
        with self.assertRaises(UserError):validate_plan(p,{**c,'music_mode':'single'})


class PlaylistRecoveryTests(unittest.TestCase):
    def fixture(self,root,count=3,total=1):
        c=config(music_mode='playlist',playlist_count=count,license_count=1,first_license=1,
                 mode='beat',cut_min=.5,cut_max=1,effects='all')
        catalog={}
        for role,names in {'clip':[('clip',1.7)],'license':[('license',9)],
                           'music':[('bad.mp3',7.25),('good1.wav',8.75),('good2.flac',9.125),('replacement.wav',11.625)]}.items():
            folder=root/role;folder.mkdir();c[{'clip':'clips','license':'licenses','music':'music'}[role]]=str(folder)
            catalog[role]=[]
            for name,duration in names:
                path=folder/name;path.write_bytes(b'fixture');stat=path.stat()
                catalog[role].append(dict(path=str(path),name=name,duration=duration,size=stat.st_size,mtime=stat.st_mtime_ns))
        output=root/'output';output.mkdir();c['output']=str(output)
        jobs=[dict(id=i+1,status='pending',device='cpu',encoder='libx264',music='',dest=str(output/str(i))) for i in range(total)]
        state=dict(jobs=jobs,batch='playlist_test',catalog=catalog)
        r=BatchRecovery(c,state,threading.RLock(),threading.Event(),lambda:None,lambda msg:None)
        r.rng=random.Random(21)
        def analyze(path,stop=None):return analysis_for(next(a for a in catalog['music'] if a['path']==path))
        return c,state,r,analyze

    def test_multiple_videos_have_random_nonrepeating_tracks_and_unique_plans(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,state,r,analyze=self.fixture(Path(tmp),total=12)
            with patch('batch.analyze_playlist_music',side_effect=analyze):
                for job in state['jobs']:r.prepare(job)
            orders=[tuple(a['path'] for a in audio_assets(j['plan'])) for j in state['jobs']]
            self.assertTrue(all(len(order)==len(set(order))==3 for order in orders))
            self.assertGreater(len(set(orders)),4)
            self.assertEqual(len({fingerprint(j['plan']) for j in state['jobs']}),12)
            for j in state['jobs']:validate_plan(j['plan'],c)

    def test_failed_music_is_replaced_in_its_slot_and_timestamps_are_recomputed(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,state,r,analyze=self.fixture(Path(tmp))
            job=state['jobs'][0];original=r.catalog['music'][:3]
            job['plan']=playlist_plan(original,c,clips=r.catalog['clip'],licenses=r.catalog['license'])
            old_text=text_from_plan(job['plan']);calls=[]
            def render(job,config):
                paths=[a['path'] for a in audio_assets(job['plan'])];calls.append(paths)
                if original[0]['path'] in paths:raise SourceError(original[0],'music','Damaged during render')
            with patch('batch.analyze_playlist_music',side_effect=analyze):r.run_job(job,render,c)
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[1][1:],calls[0][1:])
            self.assertEqual(calls[1][0],r.catalog['music'][3]['path'])
            self.assertEqual(state['blocked']['music'],[original[0]['path']])
            validate_plan(job['plan'],c)
            self.assertNotEqual(text_from_plan(job['plan']),old_text)
            self.assertEqual(clock_samples(job['plan']['tracks'][1]['start_sample']),'0:11')
            self.assertTrue(all(t['asset']['path'] not in state['blocked']['music'] for t in job['plan']['tracks']))
            self.assertTrue(all(5*c['fps']<=s['frames']<=7*c['fps'] and not s.get('fx_in') and not s.get('fx_out')
                                for s in job['plan']['segments'] if s['kind']=='license'))

    def test_missing_track_and_insufficient_music_never_silently_shorten_playlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,state,r,analyze=self.fixture(Path(tmp),count=4)
            with patch('batch.analyze_playlist_music',side_effect=analyze):r.prepare(state['jobs'][0])
            missing=audio_assets(state['jobs'][0]['plan'])[1]
            Path(missing['path']).unlink()
            self.assertFalse(r.plan_current(state['jobs'][0]))
            with patch('batch.analyze_playlist_music',side_effect=analyze):
                with self.assertRaisesRegex(UserError,'4 ta.*3 ta'):r.prepare(state['jobs'][0])
            self.assertEqual(len(state['jobs'][0]['plan']['tracks']),4)


class PlaylistRenderTests(unittest.TestCase):
    def test_real_mixed_audio_formats_order_duration_effect_anchors_and_reports(self):
        with tempfile.TemporaryDirectory(prefix='Playlist Ўзбек ') as tmp:
            root=Path(tmp);tracks=[];frequencies=[330,550,770]
            for i,(rate,length,suffix) in enumerate([(44100,7.137,'mp3'),(48000,8.239,'wav'),(22050,9.061,'flac')]):
                wav=root/f'input_{i}.wav'
                with wave.open(str(wav),'wb') as f:
                    f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate)
                    data=bytearray()
                    for n in range(round(length*rate)):
                        t=n/rate;gain=12000 if any(0<=t-x<.18 for x in (1,4,7)) else 900
                        data.extend(struct.pack('<h',round(gain*math.sin(2*math.pi*frequencies[i]*t))))
                    f.writeframes(data)
                path=root/f'Artist {i+1} – Qo‘shiq.{suffix}'
                execute([binary('ffmpeg'),'-v','error','-y','-i',str(wav),str(path)])
                tracks.append(probe(path,'audio'))
            analyses=[analyze_playlist_music(a['path']) for a in tracks]
            music,timeline,accents=compose(tracks,analyses)
            for name,duration in [('clip',1.4),('license',9)]:
                execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'testsrc2=s=160x90:r=25:d={duration}',
                         '-threads','1','-c:v','libx264',str(root/(name+'.mp4'))])
            c=config(fps=25,music_mode='playlist',playlist_count=3,license_count=1,first_license=1,
                     mode='beat',cut_min=.5,cut_max=1.2,effects='all',effect_gap=.5)
            plan=plan_one([probe(root/'clip.mp4','video')],[probe(root/'license.mp4','video')],music,c,9,accents)
            plan.update(plan_version=5,tracks=timeline)
            dest=root/'output';values=[];render(plan,c,dest,'libx264',threading.Event(),values.append)
            self.assertEqual(values[-1],1);self.assertEqual(values,sorted(values))
            self.assertLess(abs(probe(dest/'video.mp4','audio')['duration']-music['duration']),.04)
            self.assertLess(abs(probe(dest/'video.mp4','video')['duration']-music['duration']),.08)
            self.assertEqual((dest/'Playlist.txt').read_text(encoding='utf-8'),text_from_plan(plan))
            saved=json.loads((dest/'reja.json').read_text())
            self.assertEqual(saved['tracks'],timeline);self.assertEqual(rows_from_plan(saved),rows_from_plan(plan))
            self.assertTrue((dest/'Litsen_video_malumot.xlsx').is_file())
            self.assertFalse(list(dest.glob('_work_*')))
            self.assertGreater(plan['effect_count'],0)
            self.assertTrue(all(s['start'] in plan['strong_frames'] for s in plan['segments'] if s.get('fx_in')))
            decoded=root/'decoded.pcm'
            execute([binary('ffmpeg'),'-v','error','-y','-i',str(dest/'video.mp4'),'-vn','-ar',str(SAMPLE_RATE),'-ac','1','-f','s16le',str(decoded)])
            audio=array.array('h');audio.frombytes(decoded.read_bytes())
            if sys.byteorder!='little':audio.byteswap()
            # Verify actual encoded song order on both sides of each join, to
            # near each join. The full duration is checked independently above.
            for index,track in enumerate(timeline):
                for offset in [.08,track['samples']/SAMPLE_RATE-.16]:
                    start=track['start_sample']+round(offset*SAMPLE_RATE)
                    samples=audio[start:start+2400]
                    power=[abs(sum(v*complex(math.cos(2*math.pi*hz*n/SAMPLE_RATE),math.sin(2*math.pi*hz*n/SAMPLE_RATE))
                                   for n,v in enumerate(samples))) for hz in frequencies]
                    self.assertEqual(power.index(max(power)),index)


if __name__=='__main__':unittest.main(verbosity=2)
