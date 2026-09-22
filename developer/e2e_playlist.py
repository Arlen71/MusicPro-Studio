"""Real HTTP playlist recovery after inputs are damaged *after* planning.

Preserve size/mtime so metadata checks cannot conceal the decoder recovery path.
This executes real CPU FFmpeg renders; no production test hooks are used.
"""
import json
import array
import math
import os
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path

APP=Path(__file__).resolve().parents[1]/'app'
sys.path.insert(0,str(APP))
from engine import execute,binary,probe,validate_plan,fingerprint
from reports import REPORT_NAME,rows_from_plan
from playlist import audio_assets,text_from_plan,ORDER_KEYS


def damage(path, video):
    stat=path.stat();data=bytearray(path.read_bytes())
    if video:
        offset=0
        while offset+8<=len(data):
            size=int.from_bytes(data[offset:offset+4],'big');kind=data[offset+4:offset+8]
            header=8
            if size==1:size=int.from_bytes(data[offset+8:offset+16],'big');header=16
            if size==0:size=len(data)-offset
            if kind==b'mdat':
                data[offset+header:offset+size]=b'\0'*(size-header);break
            if size<header:raise AssertionError('Invalid fixture MP4')
            offset+=size
        else:raise AssertionError('No mdat in fixture')
    else:data[:64]=b'\0'*64
    path.write_bytes(data);os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    assert path.stat().st_size==stat.st_size and path.stat().st_mtime_ns==stat.st_mtime_ns


with tempfile.TemporaryDirectory(prefix='MusicPro 1.7 Playlist Ўзбек ') as temp:
    # macOS hands out /var/... for a /private/var temp dir; the app resolves.
    root=Path(temp).resolve()
    for folder in ('clips','licenses','music','output','data'):(root/folder).mkdir()
    for name,duration,folder in [('clip_a',1.2,'clips'),('clip_b',1.7,'clips'),('CS00001 (1)',9.4,'licenses'),('CS00002 (2)',10.2,'licenses')]:
        execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'testsrc2=s=160x90:r=30:d={duration}',
                 '-threads','1','-c:v','libx264','-movflags','+faststart',str(root/folder/(name+'.mp4'))])
    song_specs=[('track_a',7.14,110),('track_b',8.15,220),('track_c',9.21,330),('Replacement – Ўзбек qo‘shiq',10.17,440)]
    for name,duration,frequency in song_specs:
        with wave.open(str(root/'music'/(name+'.wav')),'wb') as f:
            rate=12000;f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate)
            data=bytearray()
            for i in range(round(duration*rate)):
                t=i/rate;strong=any(0<=t-x<.12 for x in (2,5,8,11,14,17,20))
                data.extend(struct.pack('<h',int((15000 if strong else 150)*math.sin(2*math.pi*frequency*t))))
            f.writeframes(data)
    # These must be skipped during the initial scan without blocking planning.
    (root/'clips/broken_before_scan.mp4').write_bytes(b'not a video')
    (root/'music/broken_before_scan.mp3').write_bytes(b'not an audio file')
    env={**os.environ,'MUSICPRO_DATA_DIR':str(root/'data')}
    proc=subprocess.Popen([sys.executable,str(APP/'app.py'),'--no-browser'],env=env,stdout=subprocess.PIPE,text=True)
    try:
        address=proc.stdout.readline().strip().split('MusicPro: ')[1]
        def get(path):return json.load(urllib.request.urlopen(address+'/api/'+path,timeout=10))
        token=get('init')['token']
        def post(path,body=None):
            request=urllib.request.Request(address+'/api/'+path,data=json.dumps(body or {}).encode(),
                    headers={'Content-Type':'application/json','X-MusicPro-Token':token})
            return urllib.request.urlopen(request,timeout=30).read()
        def settled(timeout=600):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                state=get('state')
                if not state['busy']:return state
                time.sleep(.15)
            raise AssertionError('Timed out: '+str(get('state').get('message')))
        c={k:str(root/k) for k in ('clips','licenses','music','output')}
        choices=json.loads(post('music-list',{'music':c['music']}))['files']
        assert len(choices)==5
        assert any(a['name']=='Replacement – Ўзбек qo‘shiq.wav' for a in choices)
        (root/'output/track_a').mkdir()
        (root/'output/track_a/user.txt').write_text('existing user data')
        pins=[str(root/'music'/f'track_{letter}.wav') for letter in 'abc']
        c.update(playlist_order_enabled=True,**dict(zip(ORDER_KEYS,pins)))
        # Both license sources must be encountered even after music replanning.
        c.update(total=2,music_mode='playlist',playlist_count=3,license_count=2,first_license=1,license_gap=.5,fps=30,height=720,
                 quality='economy',mode='beat',cut_min=.5,cut_max=1,device='cpu',
                 resources='medium',effects='all',effect_strength='balanced',effect_gap=2)
        post('plan',c);state=settled();assert state['status']=='ready',state
        saved=json.loads((root/'data/session.json').read_text())
        assert [Path(j['dest']).name for j in saved['jobs']]==['track_a (2)','track_a (3)']
        assert all([t['asset']['path'] for t in j['plan']['tracks']]==pins for j in saved['jobs'])
        initial=saved['jobs'][0]['plan']
        broken_music=Path(initial['tracks'][0]['asset']['path'])
        broken_license=Path(next(s['asset']['path'] for s in initial['segments'] if s['kind']=='license'))
        broken_clip=Path(next(s['asset']['path'] for s in initial['segments'] if s['kind']=='clip'))
        damaged={str(broken_music),str(broken_license),str(broken_clip)}
        damage(broken_music,False);damage(broken_license,True);damage(broken_clip,True)
        print('Planning passed; damaged music, licensed video and ordinary clip after planning.',flush=True)
        # Exactly one start request. No resume/continue/confirmation request follows.
        post('run');state=settled()
        assert state['status']=='completed_issues',(state['message'],json.dumps(state['issues'],ensure_ascii=False))
        assert len(state['jobs'])==2 and all(j['status']=='done' for j in state['jobs']),state
        assert damaged<={r['path'] for r in state['issues']},state['issues']
        final=json.loads((root/'data/session.json').read_text())
        assert len({fingerprint(j['plan']) for j in final['jobs']})==2
        assert (root/'output/track_a/user.txt').read_text()=='existing user data'
        assert {Path(j['dest']).name for j in final['jobs']}=={'Replacement – Ўзбек qo‘shiq','Replacement – Ўзбек qo‘shiq (2)'}
        for job in final['jobs']:
            plan=job['plan'];validate_plan(plan,c)
            assert not damaged & {*(a['path'] for a in audio_assets(plan)),*(s['asset']['path'] for s in plan['segments'])}
            dest=Path(job['dest']);actual=json.loads((dest/'reja.json').read_text())
            assert fingerprint(plan)==fingerprint(actual)
            assert (dest/REPORT_NAME).is_file()
            assert rows_from_plan(plan)==rows_from_plan(actual)
            assert len(plan['tracks'])==len({a['path'] for a in audio_assets(plan)})==3
            assert [t['asset']['path'] for t in plan['tracks'][1:]]==pins[1:]
            assert plan['video_filename']==dest.name+'.mp4'
            assert (dest/plan['video_filename']).is_file() and not (dest/'video.mp4').exists()
            expected=text_from_plan(plan).encode('utf-8')
            assert (dest/'Playlist.txt').read_bytes()==expected
            assert urllib.request.urlopen(address+'/api/playlist/'+str(job['id'])).read()==expected
            visible=next(j for j in state['jobs'] if j['id']==job['id'])
            assert visible['playlist_ready'] and visible['music_count']==3
            assert visible['video_filename']==plan['video_filename']
            assert visible['playlist_text'].encode('utf-8')==expected
            assert abs(probe(dest/plan['video_filename'],'audio')['duration']-plan['music']['duration'])<.1
            assert abs(probe(dest/plan['video_filename'],'video')['duration']-plan['music']['duration'])<.1
            assert not list(dest.glob('_work_*'))
            assert all(s['start'] in plan['strong_frames'] for s in plan['segments'] if s.get('fx_in'))
            frequencies=[110,220,330,440]
            for track,expected_index in zip(plan['tracks'],[3,1,2]):
                raw=subprocess.check_output([binary('ffmpeg'),'-v','error','-ss',str(track['start_sample']/48000+.35),
                    '-i',str(dest/plan['video_filename']),'-t','0.1','-vn','-ar','12000','-ac','1','-f','s16le','-'])
                samples=array.array('h');samples.frombytes(raw)
                if sys.byteorder!='little':samples.byteswap()
                powers=[abs(sum(v*complex(math.cos(2*math.pi*hz*n/12000),math.sin(2*math.pi*hz*n/12000))
                    for n,v in enumerate(samples))) for hz in frequencies]
                assert powers.index(max(powers))==expected_index,powers
        csv=urllib.request.urlopen(address+'/api/issues/export').read().decode('utf-8-sig')
        assert broken_music.name in csv and broken_clip.name in csv and broken_license.name in csv
        assert Path(final['issues_path']).is_file()
        assert not list((root/'data').glob('worker_*'))
        post('shutdown');proc.wait(10)
        proc=subprocess.Popen([sys.executable,str(APP/'app.py'),'--no-browser'],env=env,stdout=subprocess.PIPE,text=True)
        address=proc.stdout.readline().strip().split('MusicPro: ')[1];token=get('init')['token']
        reopened=get('state');assert reopened['issues']==state['issues']
        assert all(j['status']=='done' and j['playlist_ready'] for j in reopened['jobs'])
        assert get('init')['config']['music_mode']=='playlist'
        assert get('init')['config']['playlist_count']==3
        assert get('init')['config']['playlist_order_enabled'] is True
        assert [get('init')['config'][key] for key in ORDER_KEYS]==pins
        assert [j['playlist_text'] for j in reopened['jobs']]==[j['playlist_text'] for j in state['jobs']]
        post('shutdown');proc.wait(10)
        print('PASS: 2 real named playlist outputs, 3 tracks each; first/second/third pinned; first replaced after decode failure; healthy slots and decoded audio order preserved; folders renamed safely; collision protection; exact TXT/XLSX; CSV; selected slots survive restart; one Run request.',flush=True)
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(10)
