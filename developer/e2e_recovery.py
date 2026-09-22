"""Real HTTP/worker recovery after inputs are damaged *after* planning.

Preserve size/mtime so metadata checks cannot conceal the decoder recovery path.
This executes real CPU FFmpeg renders; no production test hooks are used.
"""
import json
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


with tempfile.TemporaryDirectory(prefix='MusicPro 1.7 Ўзбек ') as temp:
    # macOS hands out /var/... for a /private/var temp dir; the app resolves.
    root=Path(temp).resolve()
    for folder in ('clips','licenses','music','output','data'):(root/folder).mkdir()
    for name,duration,folder in [('clip_a',1.2,'clips'),('clip_b',1.7,'clips'),('CS00001 (1)',9.4,'licenses'),('CS00002 (2)',10.2,'licenses')]:
        execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'testsrc2=s=160x90:r=30:d={duration}',
                 '-threads','1','-c:v','libx264','-movflags','+faststart',str(root/folder/(name+'.mp4'))])
    for name,duration in [('track_a',20.14),('track_b',23.15)]:
        with wave.open(str(root/'music'/(name+'.wav')),'wb') as f:
            rate=12000;f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate)
            data=bytearray()
            for i in range(round(duration*rate)):
                t=i/rate;strong=any(0<=t-x<.12 for x in (2,5,8,11,14,17,20))
                data.extend(struct.pack('<h',int((15000 if strong else 150)*math.sin(2*math.pi*110*t))))
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
        c.update(total=3,license_count=1,first_license=1,license_gap=.5,fps=30,height=720,
                 quality='economy',mode='beat',cut_min=.5,cut_max=1,device='cpu',
                 resources='medium',effects='edit',effect_strength='balanced',effect_gap=2)
        post('plan',c);state=settled();assert state['status']=='ready',state
        saved=json.loads((root/'data/session.json').read_text())
        initial=saved['jobs'][0]['plan']
        broken_music=Path(initial['music']['path'])
        broken_license=Path(next(s['asset']['path'] for s in initial['segments'] if s['kind']=='license'))
        broken_clip=Path(next(s['asset']['path'] for s in initial['segments'] if s['kind']=='clip'))
        damaged={str(broken_music),str(broken_license),str(broken_clip)}
        damage(broken_music,False);damage(broken_license,True);damage(broken_clip,True)
        print('Planning passed; damaged music, licensed video and ordinary clip after planning.',flush=True)
        # Exactly one start request. No resume/continue/confirmation request follows.
        post('run');state=settled()
        assert state['status']=='completed_issues',state['message']
        assert len(state['jobs'])==3 and all(j['status']=='done' for j in state['jobs']),state
        assert damaged<={r['path'] for r in state['issues']},state['issues']
        final=json.loads((root/'data/session.json').read_text())
        assert len({fingerprint(j['plan']) for j in final['jobs']})==3
        for job in final['jobs']:
            plan=job['plan'];validate_plan(plan,c)
            assert not damaged & {plan['music']['path'],*(s['asset']['path'] for s in plan['segments'])}
            dest=Path(job['dest']);actual=json.loads((dest/'reja.json').read_text())
            assert fingerprint(plan)==fingerprint(actual)
            assert (dest/REPORT_NAME).is_file()
            assert rows_from_plan(plan)==rows_from_plan(actual)
            assert abs(probe(dest/plan['video_filename'],'audio')['duration']-plan['music']['duration'])<.1
            assert abs(probe(dest/plan['video_filename'],'video')['duration']-plan['music']['duration'])<.1
            assert not list(dest.glob('_work_*'))
            assert all(s['start'] in plan['strong_frames'] for s in plan['segments'] if s.get('fx_in'))
        csv=urllib.request.urlopen(address+'/api/issues/export').read().decode('utf-8-sig')
        assert broken_music.name in csv and broken_clip.name in csv and broken_license.name in csv
        assert Path(final['issues_path']).is_file()
        assert not list((root/'data').glob('worker_*'))
        post('shutdown');proc.wait(10)
        proc=subprocess.Popen([sys.executable,str(APP/'app.py'),'--no-browser'],env=env,stdout=subprocess.PIPE,text=True)
        address=proc.stdout.readline().strip().split('MusicPro: ')[1];token=get('init')['token']
        reopened=get('state');assert reopened['issues']==state['issues']
        assert all(j['status']=='done' for j in reopened['jobs'])
        post('shutdown');proc.wait(10)
        print('PASS: 3 real outputs; bad scan inputs skipped; corrupted clip/license/music replaced; no continuation request; exact final plans/reports/audio; CSV; warnings survive restart.',flush=True)
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(10)
