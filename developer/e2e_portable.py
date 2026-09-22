"""Exercise server lifecycle and a real worker after packaging-related changes."""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
APP = BASE/'app' if (BASE/'app/app.py').is_file() else BASE/'MusicPro_v1_4/app'
sys.path.insert(0, str(APP))
from engine import execute, binary, probe
from reports import REPORT_NAME

with tempfile.TemporaryDirectory(prefix='MusicPro E2E Ўзбек ') as temp:
    # macOS hands out /var/... for a /private/var temp dir; the app resolves.
    root = Path(temp).resolve()
    for name in ('clips','licenses','music','output','data'): (root/name).mkdir()
    for name,color,duration,folder in [('a','blue',1.2,'clips'),('b','green',1.7,'clips'),('CS00652 (17)','red',9.4,'licenses')]:
        execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'color={color}:s=160x90:r=30:d={duration}', '-c:v','libx264',str(root/folder/(name+'.mp4'))])
    execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=10.14',str(root/'music/Ўзбек trek.wav')])
    env={**os.environ,'MUSICPRO_DATA_DIR':str(root/'data')}
    p=subprocess.Popen([sys.executable,str(APP/'app.py'),'--no-browser'],env=env,stdout=subprocess.PIPE,text=True)
    try:
        address=p.stdout.readline().strip().split('MusicPro: ')[1]
        def get(path): return json.load(urllib.request.urlopen(address+'/api/'+path,timeout=10))
        init=get('init'); assert init['version']=='1.8.0'
        token=init['token']
        def post(path,body=None,key=None):
            req=urllib.request.Request(address+'/api/'+path,data=json.dumps(body or {}).encode(),headers={'Content-Type':'application/json','X-MusicPro-Token':token if key is None else key})
            return urllib.request.urlopen(req,timeout=30).read()
        # A second launcher uses the same queue and immediately returns.
        second=subprocess.run([sys.executable,str(APP/'app.py'),'--no-browser'],env=env,capture_output=True,text=True,timeout=10)
        assert second.returncode==0 and 'already running' in second.stdout,second
        try: post('shutdown',key='bad-token'); raise AssertionError('Unauthenticated shutdown accepted')
        except urllib.error.HTTPError as error: assert error.code==403
        def settled():
            for _ in range(1200):
                state=get('state')
                if not state['busy']: return state
                time.sleep(.1)
            raise AssertionError('Timeout')
        config={k:str(root/k) for k in ('clips','licenses','music','output')}
        config.update(total=2,license_count=1,first_license=1,license_gap=.5,fps=30,height=720,quality='economy',mode='beat',cut_min=.5,cut_max=1.2,device='cpu',resources='medium',effects='edit',effect_strength='balanced')
        post('plan',config);assert settled()['status']=='ready'
        post('run')
        try: post('shutdown'); raise AssertionError('Active render was closed')
        except urllib.error.HTTPError as error: assert error.code==400
        state=settled();assert state['status']=='completed',state['message']
        video=Path(state['jobs'][0]['dest'])/state['jobs'][0]['video_filename']
        assert abs(probe(video,'audio')['duration']-10.14)<.07
        for job in state['jobs']:
            for licensed in job['licenses']: assert 5-1e-6<=licensed['end']-licensed['start']<=7+1e-6
        assert (video.parent/REPORT_NAME).is_file()
        saved=(root/'data/session.json').read_bytes()
        post('shutdown');p.wait(timeout=10)
        assert p.returncode==0 and not (root/'data/instance.json').exists()
        p=subprocess.Popen([sys.executable,str(APP/'app.py'),'--no-browser'],env=env,stdout=subprocess.PIPE,text=True)
        address=p.stdout.readline().strip().split('MusicPro: ')[1]
        token=get('init')['token']
        assert get('state')['jobs'][0]['status']=='done'
        assert get('init')['config']['music_mode']=='single'
        assert not any(j['playlist_ready'] or j['playlist_text'] for j in get('state')['jobs'])
        assert not list((root/'output').rglob('Playlist.txt'))
        assert (root/'data/session.json').read_bytes()==saved
        post('shutdown');p.wait(timeout=10)
        print('PASS: Unicode paths; second launch; protected shutdown; active-render guard; real isolated CPU worker/audio/XLSX; quit/reopen with queue preserved.')
    finally:
        if p.poll() is None: p.terminate();p.wait(timeout=10)
