"""Real HTTP/CPU verification of separate Top 5 playlists and an automatic video."""
import array
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
from engine import binary,execute,probe,validate_plan
from playlist import text_from_plan
from reports import REPORT_NAME


with tempfile.TemporaryDirectory(prefix='MusicPro 1.8 Per Video Ўзбек ') as temp:
    # macOS hands out /var/... for a /private/var temp dir; the app resolves.
    root=Path(temp).resolve()
    for folder in ('clips','licenses','music','output','data'):(root/folder).mkdir()
    for name,color,duration in [('clip_a','blue',.8),('clip_b','green',1.1)]:
        execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i',
                 f'color={color}:s=160x90:r=30:d={duration}','-threads','1',
                 '-c:v','libx264',str(root/'clips'/(name+'.mp4'))])
    paths=[];frequencies=[220,330,440,550,660,770]
    for i,frequency in enumerate(frequencies):
        path=root/'music'/f'Artist {i+1} – Qo‘shiq.wav';paths.append(str(path))
        with wave.open(str(path),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(12000)
            f.writeframes(b''.join(struct.pack('<h',round(12000*math.sin(2*math.pi*frequency*n/12000)))
                                   for n in range(15600+i*1200)))
    choices={'1':dict(enabled=True,tracks=paths[:5]),
             '2':dict(enabled=True,tracks=paths[1:][::-1]),
             '3':dict(enabled=False,tracks=paths[:5])}
    env={**os.environ,'MUSICPRO_DATA_DIR':str(root/'data')}
    def launch():
        process=subprocess.Popen([sys.executable,str(APP/'app.py'),'--no-browser'],env=env,
                                 stdout=subprocess.PIPE,text=True)
        return process,process.stdout.readline().strip().split('MusicPro: ')[1]
    proc,address=launch()
    try:
        def get(path):return json.load(urllib.request.urlopen(address+'/api/'+path,timeout=10))
        token=get('init')['token'];assert get('init')['version']=='1.8.0'
        def post(path,body=None):
            request=urllib.request.Request(address+'/api/'+path,data=json.dumps(body or {}).encode(),
                    headers={'Content-Type':'application/json','X-MusicPro-Token':token})
            return urllib.request.urlopen(request,timeout=30).read()
        def settled(timeout=180):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                state=get('state')
                if not state['busy']:return state
                time.sleep(.1)
            raise AssertionError('Timed out: '+str(get('state').get('message')))
        config={k:str(root/k) for k in ('clips','licenses','music','output')}
        config.update(total=3,music_mode='playlist',playlist_count=5,playlist_per_video=choices,
                      license_count=0,first_license=60,license_gap=15,fps=30,height=720,
                      quality='economy',mode='random',device='cpu',resources='medium',effects='off')
        assert len(json.loads(post('music-list',{'music':config['music']}))['files'])==6
        post('plan',config);state=settled();assert state['status']=='ready',state
        session=json.loads((root/'data/session.json').read_text())
        plans=[j['plan'] for j in session['jobs']]
        for i in range(2):
            assert [t['asset']['path'] for t in plans[i]['tracks']]==choices[str(i+1)]['tracks']
        for i,plan in enumerate(plans,1):
            assert plan['playlist_job_id']==i
            assert len({t['asset']['path'] for t in plan['tracks']})==5
        print('PASS: independent Top 5 orders and five distinct automatic tracks planned.',flush=True)
        post('run');state=settled()
        assert state['status']=='completed',state
        assert len(state['jobs'])==3 and all(j['status']=='done' for j in state['jobs'])
        session=json.loads((root/'data/session.json').read_text())
        for job,initial in zip(session['jobs'],plans):
            plan=job['plan'];validate_plan(plan,config)
            assert plan['tracks']==initial['tracks']
            dest=Path(job['dest']);video=dest/plan['video_filename']
            assert video.is_file() and plan['video_filename']==dest.name+'.mp4'
            first=Path(plan['tracks'][0]['asset']['path']).stem
            assert dest.name==first or dest.name.startswith(first+' (')
            assert (dest/REPORT_NAME).is_file()
            expected=text_from_plan(plan).encode('utf-8')
            assert (dest/'Playlist.txt').read_bytes()==expected
            assert urllib.request.urlopen(address+'/api/playlist/'+str(job['id'])).read()==expected
            assert abs(probe(video,'audio')['duration']-plan['music']['duration'])<.1
            assert abs(probe(video,'video')['duration']-plan['music']['duration'])<.1
            for track in plan['tracks']:
                raw=subprocess.check_output([binary('ffmpeg'),'-v','error','-ss',
                    str(track['start_sample']/48000+.3),'-i',str(video),'-t','0.1','-vn',
                    '-ar','12000','-ac','1','-f','s16le','-'])
                samples=array.array('h');samples.frombytes(raw)
                if sys.byteorder!='little':samples.byteswap()
                powers=[abs(sum(v*complex(math.cos(2*math.pi*hz*n/12000),math.sin(2*math.pi*hz*n/12000))
                               for n,v in enumerate(samples))) for hz in frequencies]
                assert powers.index(max(powers))==paths.index(track['asset']['path'])
        post('shutdown');proc.wait(10)
        proc,address=launch();token=get('init')['token']
        assert get('init')['config']['playlist_per_video']==choices
        assert all(j['status']=='done' and j['playlist_ready'] for j in get('state')['jobs'])
        post('shutdown');proc.wait(10)
        print('PASS: three real 720p CPU videos; all 15 decoded audio slots match their own plan; '
              'video/folder names, exact TXT, reports, durations and selections after restart verified.',flush=True)
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(10)
