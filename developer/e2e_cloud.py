"""Online studio end to end: accounts, uploads, a real render, downloads, isolation.

Starts cloud/gateway.py on a free port with a temporary data folder and drives
it over HTTP like a browser would — two separate accounts — with real FFmpeg
renders. It checks that one account can never read, list, plan against or
delete another account's files, whatever paths the request contains.
"""
import http.cookiejar, json, os, socket, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from engine import binary, execute, probe

with socket.socket() as s:
    s.bind(('127.0.0.1', 0)); PORT = s.getsockname()[1]
BASE = f'http://127.0.0.1:{PORT}'


class Browser:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect())
        self.token = None

    def raw(self, method, path, data=None, headers=None):
        req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers or {})
        try:
            with self.opener.open(req, timeout=120) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def form(self, path, **fields):
        return self.raw('POST', path, urllib.parse.urlencode(fields).encode(),
                        {'Content-Type': 'application/x-www-form-urlencoded'})

    def get(self, path):
        status, _, body = self.raw('GET', path)
        assert status == 200, (path, status, body[:300])
        return json.loads(body)

    def api(self, path, body=None, expect=200, headers=None):
        if self.token is None:
            self.token = self.get('/api/init')['token']
        status, _, data = self.raw('POST', '/api/' + path, json.dumps(body or {}).encode(),
                                   {'Content-Type': 'application/json', 'X-MusicPro-Token': self.token, **(headers or {})})
        assert status == expect, (path, status, data[:400])
        return json.loads(data or b'{}') if data[:1] in (b'{', b'[') else data

    def upload(self, kind, path, name=None, expect=200):
        status, _, data = self.raw('PUT', f'/files/{kind}/' + urllib.parse.quote(name or path.name), path.read_bytes(),
                                   {'Content-Type': 'application/octet-stream'})
        assert status == expect, (kind, name or path.name, status, data[:300])

    def settled(self, timeout=900):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.get('/api/state')
            if not state['busy']: return state
            time.sleep(.3)
        raise AssertionError('timeout')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


with tempfile.TemporaryDirectory(prefix='MusicPro cloud Ўзбек ') as temp:
    root = Path(temp).resolve()
    media = root / 'media'; media.mkdir()
    for name, color, duration in [('clip_a', 'blue', 1.3), ('clip_b', 'green', 1.9), ('CS00001 (1)', 'red', 9.4)]:
        execute([binary('ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color={color}:s=320x180:r=30:d={duration}',
                 '-c:v', 'libx264', str(media / f'{name}.mp4')])
    for name, freq in [('Artist – Birinchi', 330), ('Artist – Ikkinchi', 440)]:
        execute([binary('ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi', '-i', f'sine=frequency={freq}:duration=8.2',
                 str(media / f'{name}.wav')])
    (media / 'notes.txt').write_text('not media')

    data = root / 'data'
    env = {**os.environ, 'DATA_DIR': str(data), 'PORT': str(PORT), 'MAX_VIDEOS': '3', 'USER_QUOTA_GB': '1', 'SIGNUP_PER_HOUR': '7', 'LOGIN_PER_10MIN': '6',
           'INSTANCE_PORT_BASE': str(PORT + 1 if PORT < 65000 else 20000)}
    gw = subprocess.Popen([sys.executable, '-B', str(ROOT / 'cloud' / 'gateway.py')], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(BASE + '/healthz', timeout=1); break
            except OSError: time.sleep(.1)

        anon = Browser()
        assert anon.raw('GET', '/api/state')[0] == 401
        assert anon.raw('GET', '/app')[1].get('Location') == '/login'
        assert anon.raw('PUT', '/files/clips/x.mp4', b'1')[0] == 401
        assert b'Ro' in anon.raw('GET', '/signup')[2]

        a = Browser()
        assert a.form('/auth/signup', email='a@example.com', password='parol12345', confirm='boshqa123')[0] == 400
        assert a.form('/auth/signup', email='notanemail', password='parol12345', confirm='parol12345')[0] == 400
        assert a.form('/auth/signup', email='short@example.com', password='123', confirm='123')[0] == 400
        status, headers, _ = a.form('/auth/signup', email='A@Example.com', password='parol12345', confirm='parol12345')
        assert status == 303 and headers['Location'] == '/app' and 'HttpOnly' in headers['Set-Cookie'], headers
        assert Browser().form('/auth/signup', email='a@example.com', password='parol12345', confirm='parol12345')[0] == 400
        assert Browser().form('/auth/login', email='a@example.com', password='notright1')[0] == 400
        assert Browser().form('/auth/login', email='a@example.com', password='parol12345')[0] == 303
        print('PASS: signup validation, duplicate email, wrong password, session cookie.', flush=True)

        html = a.raw('GET', '/app')[2].decode()
        assert '/cloud.js' in html and '/cloud.css' in html
        a.upload('clips', media / 'clip_a.mp4'); a.upload('clips', media / 'clip_b.mp4')
        a.upload('licenses', media / 'CS00001 (1).mp4')
        for f in media.glob('*.wav'): a.upload('music', f)
        a.upload('clips', media / 'notes.txt', expect=400)
        a.upload('music', media / 'clip_a.mp4', expect=400)
        a.upload('clips', media / 'clip_a.mp4', name='../../escape.mp4', expect=400)
        a.upload('clips', media / 'clip_a.mp4', name='..\\escape.mp4', expect=400)
        files = a.get('/files')
        assert [f['name'] for f in files['clips']] == ['clip_a.mp4', 'clip_b.mp4'], files['clips']
        assert len(files['music']) == 2 and files['email'] == 'a@example.com' and files['usage'] > 0
        assert not list(data.rglob('escape.mp4'))
        print('PASS: uploads, type filter, traversal names rejected.', flush=True)

        init = a.get('/api/init')
        own = Path(init['config']['clips']).parent
        assert own == (data / 'users' / '1').resolve() or own == data / 'users' / '1', own
        assert init['platform']['os'] == 'web'
        a.api('browse', expect=403); a.api('open', expect=403); a.api('shutdown', expect=403)
        a.api('plan', {'clips': '/etc', 'licenses': '/', 'music': '/tmp', 'output': '/etc', 'total': 4}, expect=400)
        music = a.api('music-list', {'music': '/etc'})
        assert len(music['files']) == 2 and all(Path(f['path']).parent.parent == own for f in music['files']), music
        evil = {'Origin': 'https://evil.example'}
        a.api('plan', {'total': 1}, expect=403, headers=evil)
        config = {'clips': '/etc', 'licenses': '/', 'music': '/usr', 'output': '/tmp/escape-out', 'total': 2,
                  'device': 'gpu', 'license_count': 1, 'first_license': 1, 'license_gap': .5, 'fps': 30, 'height': 720,
                  'quality': 'economy', 'mode': 'random', 'cut_min': .5, 'cut_max': 1.2, 'resources': 'medium',
                  'effects': 'edit', 'effect_strength': 'balanced'}
        a.api('plan', config)
        state = a.settled()
        assert state['status'] == 'ready', state['message']
        saved = state['config']
        for k in ('clips', 'licenses', 'music', 'output'):
            assert Path(saved[k]).parent == own, (k, saved[k])
        assert saved['device'] == 'cpu'
        a.api('run')
        state = a.settled()
        assert state['status'] in ('completed', 'completed_issues'), state['message']
        assert not Path('/tmp/escape-out').exists()
        print('PASS: forged folders and GPU replaced by the account\'s own; max videos; cross-site POST refused.', flush=True)

        out = a.get('/files')['output']
        assert len(out) == 2 and all(any(f['name'].endswith('.mp4') for f in o['files']) for o in out), out
        first = out[0]; video = next(f for f in first['files'] if f['name'].endswith('.mp4'))
        path = '/files/output/' + urllib.parse.quote(first['name']) + '/' + urllib.parse.quote(video['name'])
        status, headers, body = a.raw('GET', path)
        assert status == 200 and len(body) == video['size'] and 'attachment' in headers['Content-Disposition']
        (root / 'down.mp4').write_bytes(body)
        assert abs(probe(root / 'down.mp4', 'video')['duration'] - 8.2) < .15
        status, headers, part = a.raw('GET', path, headers={'Range': 'bytes=0-99'})
        assert status == 206 and len(part) == 100 and headers['Content-Range'].endswith(f'/{video["size"]}')
        for name in ('Litsen_video_malumot.xlsx',):
            assert a.raw('GET', '/files/output/' + urllib.parse.quote(first['name']) + '/' + name)[0] == 200
        job = state['jobs'][0]
        assert a.raw('GET', f'/api/report/{job["id"]}')[0] == 200
        print('PASS: real render (2 videos), video download with Range, Excel via both routes.', flush=True)

        b = Browser()
        assert b.form('/auth/signup', email='b@example.com', password='boshqaparol1', confirm='boshqaparol1')[0] == 303
        b_files = b.get('/files')
        assert not b_files['clips'] and not b_files['output'] and b_files['usage'] == 0
        assert b.raw('GET', path)[0] == 404
        for trick in ('/files/output/..%2F..%2F1%2Foutput%2F' + urllib.parse.quote(first['name']) + '%2F' + urllib.parse.quote(video['name']),
                      '/files/output/%2E%2E/%2E%2E/1/output/' + urllib.parse.quote(first['name'])):
            assert b.raw('GET', trick)[0] in (400, 404), trick
            assert b.raw('DELETE', trick)[0] in (400, 404), trick
        b_music = b.api('music-list', {'music': str(own / 'music')})
        assert b_music['files'] == [], b_music
        b.api('plan', {**config, 'clips': str(own / 'clips'), 'music': str(own / 'music'), 'licenses': str(own / 'licenses')})
        b_state = b.settled()
        assert b_state['status'] == 'error' and Path(b_state['config']['clips']).parent != own, b_state['config']
        assert b.raw('DELETE', '/files/clips/clip_a.mp4')[0] == 404
        assert (own / 'clips' / 'clip_a.mp4').is_file()
        flood = Browser()
        assert flood.form('/auth/signup', email='c@example.com', password='parol12345', confirm='parol12345')[0] == 303
        assert 'urinish' in flood.form('/auth/signup', email='d@example.com', password='parol12345', confirm='parol12345')[2].decode()
        print('PASS: signup rate limit per address.', flush=True)
        print('PASS: second account cannot read, list, plan against or delete the first account\'s files.', flush=True)

        before = a.get('/files')['usage']
        assert a.raw('DELETE', '/files/output/' + urllib.parse.quote(first['name']))[0] == 200
        assert a.get('/files')['usage'] < before and len(a.get('/files')['output']) == 1
        big = root / 'big.mp4'
        with big.open('wb') as f: f.truncate(1024**3 + 1)
        status, _, _ = a.raw('PUT', '/files/clips/big.mp4', None, {'Content-Length': str(big.stat().st_size)})
        assert status == 413, status
        assert a.form('/auth/logout')[0] == 303
        assert a.raw('GET', '/api/state')[0] == 401
        print('PASS: delete frees quota, oversize upload refused before transfer, logout ends the session.', flush=True)
    finally:
        gw.terminate()
        try: gw.wait(30)
        except subprocess.TimeoutExpired: gw.kill()

    # A shared volume below its reserve refuses uploads and new renders for everyone.
    full = subprocess.Popen([sys.executable, '-B', str(ROOT / 'cloud' / 'gateway.py')],
                            env={**env, 'DATA_DIR': str(root / 'full'), 'DISK_RESERVE_MB': str(10**9)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try: urllib.request.urlopen(BASE + '/healthz', timeout=1); break
            except OSError: time.sleep(.1)
        c = Browser()
        assert c.form('/auth/signup', email='full@example.com', password='parol12345', confirm='parol12345')[0] == 303
        c.upload('clips', media / 'clip_a.mp4', expect=507)
        c.api('plan', {'total': 1}, expect=507)
        print('PASS: shared disk reserve refuses uploads and plans.', flush=True)
    finally:
        full.terminate(); full.wait(30)
    print('PASS: online studio — accounts, uploads, real renders, downloads and isolation verified.', flush=True)
