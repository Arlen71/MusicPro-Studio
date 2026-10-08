"""MusicPro Studio online: accounts, uploads and one isolated studio per account.

The desktop application (app/app.py) is single-user by design: one queue, one
data folder, loopback only. Online, every account gets its own unmodified
instance of it — own data folder, own queue, own source and output folders —
started on demand on a private port and stopped when idle. This gateway is the
only public listener. It authenticates the person, proxies the studio's API to
*their* instance, and rewrites every request that names a folder so it can
only ever point at that account's own folders.

Standard library only. Configuration through environment variables (see CONFIG).
"""
from __future__ import annotations
import hashlib
import hmac
import http.client
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent / 'app'
STATIC = HERE / 'static'
sys.path.insert(0, str(APP))
from engine import AUDIO, VIDEO  # noqa: E402

CONFIG = dict(
    port=int(os.environ.get('PORT', '8080')),
    data=Path(os.environ.get('DATA_DIR', str(HERE.parent / 'cloud-data'))).resolve(),
    quota_gb=float(os.environ.get('USER_QUOTA_GB', '3')),
    max_file_mb=int(os.environ.get('MAX_FILE_MB', '1024')),
    max_videos=int(os.environ.get('MAX_VIDEOS', '10')),
    max_renders=int(os.environ.get('MAX_ACTIVE_RENDERS', '1')),
    idle_minutes=float(os.environ.get('IDLE_MINUTES', '20')),
    allow_signup=os.environ.get('ALLOW_SIGNUP', '1') not in ('0', 'false', 'no'),
    session_days=int(os.environ.get('SESSION_DAYS', '30')),
    reserve_mb=int(os.environ.get('DISK_RESERVE_MB', '500')),
    instance_ports=range(int(os.environ.get('INSTANCE_PORT_BASE', '9100')),
                         int(os.environ.get('INSTANCE_PORT_BASE', '9100')) + 200),
)
SOURCES = {'clips': VIDEO, 'licenses': VIDEO, 'music': AUDIO}
FOLDERS = ('clips', 'licenses', 'music', 'output')
COOKIE = 'mp_session'
EMAIL = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$')
BAD_NAME = re.compile(r'[\x00-\x1f/\\:*?"<>|]')


def log(*parts):
    print(time.strftime('%Y-%m-%d %H:%M:%S'), *parts, flush=True)


# --- accounts ---------------------------------------------------------------

class Accounts:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.lock = threading.Lock()
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                salt BLOB NOT NULL, hash BLOB NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                expires REAL NOT NULL);''')

    @staticmethod
    def _hash(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)

    def create(self, email: str, password: str) -> int:
        salt = secrets.token_bytes(16)
        with self.lock:
            cur = self.db.execute('INSERT INTO users(email,salt,hash,created) VALUES(?,?,?,?)',
                                  (email, salt, self._hash(password, salt), time.time()))
        return cur.lastrowid

    def verify(self, email: str, password: str):
        with self.lock:
            row = self.db.execute('SELECT id,salt,hash FROM users WHERE email=?', (email,)).fetchone()
        if not row:
            self._hash(password, b'0' * 16)  # same cost whether or not the account exists
            return None
        return row[0] if hmac.compare_digest(self._hash(password, row[1]), row[2]) else None

    def email(self, user_id: int) -> str:
        with self.lock:
            row = self.db.execute('SELECT email FROM users WHERE id=?', (user_id,)).fetchone()
        return row[0] if row else ''

    def open_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            self.db.execute('INSERT INTO sessions VALUES(?,?,?)',
                            (hashlib.sha256(token.encode()).hexdigest(), user_id,
                             time.time() + CONFIG['session_days'] * 86400))
        return token

    def session_user(self, token: str):
        if not token:
            return None
        with self.lock:
            row = self.db.execute('SELECT user_id,expires FROM sessions WHERE token=?',
                                  (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return row[0] if row and row[1] > time.time() else None

    def close_session(self, token: str):
        with self.lock:
            self.db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))


class RateLimit:
    """At most `count` attempts per `window` seconds per key (client address)."""
    def __init__(self, count, window):
        self.count, self.window, self.hits, self.lock = count, window, defaultdict(deque), threading.Lock()

    def allow(self, key) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.count:
                return False
            q.append(now)
            return True


# --- per-account studio instances --------------------------------------------

def user_root(user_id: int) -> Path:
    return CONFIG['data'] / 'users' / str(int(user_id))


def folders(user_id: int) -> dict:
    root = user_root(user_id)
    result = {k: root / k for k in FOLDERS}
    for p in result.values():
        p.mkdir(parents=True, exist_ok=True)
    return result


def disk_full(extra: int = 0) -> bool:
    """The shared volume must keep a reserve for renders already under way."""
    return shutil.disk_usage(CONFIG['data']).free - extra < CONFIG['reserve_mb'] * 1024**2


DISK_FULL = 'Server diski vaqtincha to‘lgan. Birozdan keyin urinib ko‘ring.'


def usage_bytes(user_id: int) -> int:
    total = 0
    for dirpath, _, files in os.walk(user_root(user_id)):
        for f in files:
            try: total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError: pass
    return total


class Instance:
    def __init__(self, user_id, port, proc):
        self.user_id, self.port, self.proc = user_id, port, proc
        self.last_seen = time.monotonic()
        self.token = None

    def alive(self):
        return self.proc.poll() is None

    def call(self, method, path, body=None, headers=None, timeout=60):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        try:
            h = {'Host': f'127.0.0.1:{self.port}', **(headers or {})}
            conn.request(method, path, body=body, headers=h)
            r = conn.getresponse()
            return r.status, r.getheaders(), r.read()
        finally:
            conn.close()

    def state(self):
        status, _, data = self.call('GET', '/api/state', timeout=10)
        return json.loads(data) if status == 200 else {}

    def shutdown(self):
        try:
            if not self.token:
                self.token = json.loads(self.call('GET', '/api/init', timeout=10)[2])['token']
            self.call('POST', '/api/shutdown', b'{}', {'X-MusicPro-Token': self.token,
                                                         'Content-Type': 'application/json'}, timeout=10)
            self.proc.wait(20)
        except Exception:
            self.proc.terminate()
            try: self.proc.wait(10)
            except subprocess.TimeoutExpired: self.proc.kill()


class Studios:
    def __init__(self):
        self.lock = threading.Lock()
        self.instances: dict[int, Instance] = {}
        threading.Thread(target=self._reaper, daemon=True).start()

    def _free_port(self):
        used = {i.port for i in self.instances.values()}
        for port in CONFIG['instance_ports']:
            if port in used:
                continue
            with socket.socket() as s:
                try: s.bind(('127.0.0.1', port)); return port
                except OSError: continue
        raise RuntimeError('Server band: bo‘sh port qolmadi. Birozdan keyin urinib ko‘ring.')

    def get(self, user_id) -> Instance:
        with self.lock:
            inst = self.instances.get(user_id)
            if inst and inst.alive():
                inst.last_seen = time.monotonic()
                return inst
            port = self._free_port()
            data = user_root(user_id) / 'data'
            data.mkdir(parents=True, exist_ok=True)
            folders(user_id)
            env = {**os.environ, 'MUSICPRO_DATA_DIR': str(data), 'MUSICPRO_PORT': str(port),
                   'PYTHONIOENCODING': 'utf-8'}
            for secret in ('DATABASE_URL',):
                env.pop(secret, None)
            proc = subprocess.Popen([sys.executable, '-X', 'utf8', '-B', str(APP / 'app.py'), '--no-browser'],
                                    env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding='utf-8')
            line = ''
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and proc.poll() is None:
                line = proc.stdout.readline()
                if 'MusicPro:' in line or 'already running' in line:
                    break
            if 'MusicPro:' not in line:
                proc.kill()
                raise RuntimeError('Studiya ishga tushmadi: ' + line.strip()[-300:])
            threading.Thread(target=self._drain, args=(proc, user_id), daemon=True).start()
            inst = Instance(user_id, port, proc)
            self.instances[user_id] = inst
            log('studio started', user_id, port)
            return inst

    @staticmethod
    def _drain(proc, user_id):
        for line in proc.stdout:
            log(f'[studio {user_id}]', line.rstrip()[:500])

    def busy_count(self, exclude=None):
        n = 0
        for inst in list(self.instances.values()):
            if inst.user_id == exclude or not inst.alive():
                continue
            try:
                if inst.state().get('busy'): n += 1
            except OSError:
                pass
        return n

    def _reaper(self):
        while True:
            time.sleep(60)
            limit = CONFIG['idle_minutes'] * 60
            for inst in list(self.instances.values()):
                if not inst.alive():
                    self.instances.pop(inst.user_id, None); continue
                if time.monotonic() - inst.last_seen < limit:
                    continue
                try:
                    if inst.state().get('busy'): continue
                except OSError:
                    pass
                log('studio idle, stopping', inst.user_id)
                inst.shutdown()
                with self.lock:
                    if self.instances.get(inst.user_id) is inst:
                        self.instances.pop(inst.user_id, None)

    def stop_all(self):
        for inst in list(self.instances.values()):
            inst.shutdown()


# --- HTTP --------------------------------------------------------------------

ACCOUNTS: Accounts
STUDIOS: Studios
AUTH_LIMIT = RateLimit(int(os.environ.get('LOGIN_PER_10MIN', '10')), 600)
SIGNUP_LIMIT = RateLimit(int(os.environ.get('SIGNUP_PER_HOUR', '5')), 3600)
PAGE_CACHE: dict = {}


def page(name: str) -> str:
    if name not in PAGE_CACHE or os.environ.get('CLOUD_DEV'):
        PAGE_CACHE[name] = (STATIC / name).read_text(encoding='utf-8')
    return PAGE_CACHE[name]


def safe_name(name: str) -> str:
    name = urllib.parse.unquote(name).strip()
    if not name or name in ('.', '..') or BAD_NAME.search(name) or len(name.encode()) > 200:
        raise ValueError('Fayl nomi noto‘g‘ri.')
    return name


class Handler(BaseHTTPRequestHandler):
    server_version = 'MusicPro'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        if os.environ.get('CLOUD_ACCESS_LOG'):
            log(self.client(), fmt % args)

    # -- helpers
    def client(self):
        return (self.headers.get('X-Forwarded-For') or self.client_address[0]).split(',')[0].strip()

    def secure(self):
        return self.headers.get('X-Forwarded-Proto') == 'https'

    def cookie(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == COOKIE:
                return v
        return ''

    def user(self):
        return ACCOUNTS.session_user(self.cookie())

    def same_origin(self):
        origin = self.headers.get('Origin')
        if not origin:
            return True
        return urllib.parse.urlsplit(origin).netloc == self.headers.get('Host')

    def respond(self, status, body=b'', ctype='text/plain; charset=utf-8', headers=None):
        if isinstance(body, str): body = body.encode()
        if isinstance(body, (dict, list)): body = json.dumps(body, ensure_ascii=False).encode(); ctype = 'application/json; charset=utf-8'
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'same-origin')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            try: self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError): pass

    def error(self, status, message):
        self.respond(status, {'error': message})

    def redirect(self, location, headers=None):
        self.respond(303, b'', headers={'Location': location, **(headers or {})})

    def read_body(self, limit=2 * 1024 * 1024) -> bytes:
        size = int(self.headers.get('Content-Length') or 0)
        if size < 0 or size > limit:
            raise ValueError('So‘rov juda katta.')
        return self.rfile.read(size) if size else b''

    # -- routing
    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/healthz':
            return self.respond(200, 'ok')
        if path.startswith('/assets/') or path in ('/cloud.js', '/cloud.css', '/favicon.svg'):
            return self.static(path)
        uid = self.user()
        if path == '/':
            return self.redirect('/app') if uid else self.respond(200, page('index.html'), 'text/html; charset=utf-8',
                                                                     {'Cache-Control': 'no-cache'})
        if path in ('/login', '/signup'):
            if uid: return self.redirect('/app')
            return self.auth_page(path[1:])
        if not uid:
            if path in ('/app', '/app/'): return self.redirect('/login')
            return self.error(401, 'Avval tizimga kiring.')
        if path == '/files':
            return self.list_files(uid)
        if path.startswith('/files/output/'):
            return self.download(uid, path[len('/files/output/'):])
        if path in ('/app', '/app/'):
            return self.proxy(uid, '/', inject=True)
        if path in ('/style.css', '/app.js', '/help') or path.startswith('/api/'):
            return self.proxy(uid, self.path)
        self.error(404, 'Topilmadi.')

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if not self.same_origin():
            return self.error(403, 'So‘rov rad etildi.')
        if path in ('/auth/login', '/auth/signup'):
            return self.auth_submit(path.rsplit('/', 1)[1])
        if path == '/auth/logout':
            token = self.cookie()
            if token: ACCOUNTS.close_session(token)
            return self.redirect('/', {'Set-Cookie': f'{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax'})
        uid = self.user()
        if not uid:
            return self.error(401, 'Avval tizimga kiring.')
        if path.startswith('/api/'):
            return self.proxy(uid, self.path)
        self.error(404, 'Topilmadi.')

    def do_PUT(self):
        path = urllib.parse.urlsplit(self.path).path
        uid = self.user()
        if not uid: return self.error(401, 'Avval tizimga kiring.')
        if not self.same_origin(): return self.error(403, 'So‘rov rad etildi.')
        m = re.fullmatch(r'/files/(clips|licenses|music)/(.+)', path)
        if not m: return self.error(404, 'Topilmadi.')
        return self.upload(uid, m.group(1), m.group(2))

    def do_DELETE(self):
        path = urllib.parse.urlsplit(self.path).path
        uid = self.user()
        if not uid: return self.error(401, 'Avval tizimga kiring.')
        if not self.same_origin(): return self.error(403, 'So‘rov rad etildi.')
        m = re.fullmatch(r'/files/(clips|licenses|music|output)/(.+)', path)
        if not m: return self.error(404, 'Topilmadi.')
        return self.delete(uid, m.group(1), m.group(2))

    # -- pages
    def static(self, path):
        target = (STATIC / path.lstrip('/')).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            return self.error(404, 'Topilmadi.')
        ctype = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype.endswith('javascript'): ctype += '; charset=utf-8'
        self.respond(200, target.read_bytes(), ctype, {'Cache-Control': 'public, max-age=3600'})

    def auth_page(self, mode, message='', email=''):
        html = page('auth.html')
        signup = mode == 'signup'
        values = {
            '{{TITLE}}': 'Ro‘yxatdan o‘tish' if signup else 'Kirish',
            '{{ACTION}}': '/auth/' + mode,
            '{{BUTTON}}': 'Hisob yaratish' if signup else 'Kirish',
            '{{SWITCH}}': ('Hisobingiz bormi? <a href="/login">Kirish</a>' if signup
                           else ('Hisobingiz yo‘qmi? <a href="/signup">Ro‘yxatdan o‘tish</a>'
                                 if CONFIG['allow_signup'] else '')),
            '{{MESSAGE}}': f'<p class="msg" role="alert">{message}</p>' if message else '',
            '{{EMAIL}}': email.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;'),
            '{{AUTOCOMPLETE}}': 'new-password' if signup else 'current-password',
            '{{CONFIRM}}': ('<label>Parolni takrorlang<input name="confirm" type="password" required '
                            'minlength="8" autocomplete="new-password"></label>') if signup else '',
        }
        for k, v in values.items():
            html = html.replace(k, v)
        self.respond(400 if message else 200, html, 'text/html; charset=utf-8', {'Cache-Control': 'no-store'})

    def auth_submit(self, mode):
        try:
            form = urllib.parse.parse_qs(self.read_body(16 * 1024).decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return self.auth_page(mode, 'So‘rov noto‘g‘ri.')
        email = (form.get('email', [''])[0]).strip().lower()
        password = form.get('password', [''])[0]
        limiter = SIGNUP_LIMIT if mode == 'signup' else AUTH_LIMIT
        if not limiter.allow(self.client()):
            return self.auth_page(mode, 'Juda ko‘p urinish. Birozdan keyin qayta urinib ko‘ring.', email)
        if mode == 'signup':
            if not CONFIG['allow_signup']:
                return self.auth_page('login', 'Ro‘yxatdan o‘tish hozircha yopiq.', email)
            if not EMAIL.match(email):
                return self.auth_page(mode, 'Email manzilini to‘g‘ri kiriting.', email)
            if len(password) < 8 or len(password) > 200:
                return self.auth_page(mode, 'Parol kamida 8 belgidan iborat bo‘lsin.', email)
            if password != form.get('confirm', [''])[0]:
                return self.auth_page(mode, 'Parollar bir xil emas.', email)
            try:
                uid = ACCOUNTS.create(email, password)
            except sqlite3.IntegrityError:
                return self.auth_page(mode, 'Bu email bilan hisob allaqachon bor. Kirib ko‘ring.', email)
            log('signup', uid)
        else:
            uid = ACCOUNTS.verify(email, password)
            if not uid:
                return self.auth_page(mode, 'Email yoki parol noto‘g‘ri.', email)
        token = ACCOUNTS.open_session(uid)
        flags = 'HttpOnly; SameSite=Lax; Path=/' + ('; Secure' if self.secure() else '')
        self.redirect('/app', {'Set-Cookie': f'{COOKIE}={token}; Max-Age={CONFIG["session_days"] * 86400}; {flags}'})

    # -- files
    def list_files(self, uid):
        f = folders(uid)
        result = {}
        for kind in SOURCES:
            result[kind] = sorted(({'name': p.name, 'size': p.stat().st_size} for p in f[kind].iterdir()
                                   if p.is_file() and not p.name.startswith('.')), key=lambda x: x['name'].casefold())
        outputs = []
        for d in sorted(f['output'].iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if d.is_dir() and not d.name.startswith('.'):
                outputs.append({'name': d.name, 'files': [{'name': p.name, 'size': p.stat().st_size}
                                                          for p in sorted(d.iterdir()) if p.is_file() and not p.name.startswith(('.', '_'))]})
        result['output'] = outputs
        result.update(usage=usage_bytes(uid), quota=int(CONFIG['quota_gb'] * 1024**3),
                      max_file=CONFIG['max_file_mb'] * 1024**2, max_videos=CONFIG['max_videos'],
                      email=ACCOUNTS.email(uid))
        self.respond(200, result)

    def upload(self, uid, kind, raw_name):
        try:
            name = safe_name(raw_name)
        except ValueError as e:
            return self.error(400, str(e))
        if Path(name).suffix.lower() not in SOURCES[kind]:
            return self.error(400, f'{name}: bu papka uchun fayl turi mos emas ({", ".join(sorted(SOURCES[kind]))}).')
        size = int(self.headers.get('Content-Length') or -1)
        if size <= 0:
            return self.error(411, 'Fayl hajmi noma’lum.')
        if size > CONFIG['max_file_mb'] * 1024**2:
            return self.error(413, f'Fayl {CONFIG["max_file_mb"]} MB dan katta bo‘lmasin.')
        if usage_bytes(uid) + size > CONFIG['quota_gb'] * 1024**3:
            return self.error(413, f'Disk kvotasi ({CONFIG["quota_gb"]:g} GB) to‘ladi. Eski fayl yoki natijalarni o‘chiring.')
        if disk_full(size):
            return self.error(507, DISK_FULL)
        folder = folders(uid)[kind]
        target = folder / name
        temp = folder / f'.upload-{secrets.token_hex(8)}'
        remaining = size
        try:
            with temp.open('wb') as out:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk: raise ConnectionError('Yuklash uzildi.')
                    out.write(chunk); remaining -= len(chunk)
            os.replace(temp, target)
        except (OSError, ConnectionError) as e:
            temp.unlink(missing_ok=True)
            self.close_connection = True
            return self.error(400, str(e))
        self.respond(200, {'ok': True, 'name': name, 'size': size})

    def delete(self, uid, kind, raw):
        base = folders(uid)[kind].resolve()
        try:
            parts = [safe_name(p) for p in raw.split('/') if p]
        except ValueError as e:
            return self.error(400, str(e))
        target = base.joinpath(*parts).resolve()
        if base not in target.parents or target.is_symlink():
            return self.error(400, 'Yo‘l noto‘g‘ri.')
        inst = STUDIOS.instances.get(uid)
        if inst and inst.alive():
            try:
                if inst.state().get('busy'): return self.error(409, 'Jarayon ishlamoqda. Avval to‘xtating yoki tugashini kuting.')
            except OSError: pass
        if target.is_dir() and kind == 'output':
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
        else:
            return self.error(404, 'Topilmadi.')
        self.respond(200, {'ok': True})

    def download(self, uid, raw):
        base = folders(uid)['output'].resolve()
        try:
            parts = [safe_name(p) for p in raw.split('/') if p]
        except ValueError as e:
            return self.error(400, str(e))
        target = base.joinpath(*parts).resolve()
        if base not in target.parents or not target.is_file():
            return self.error(404, 'Topilmadi.')
        size = target.stat().st_size
        start, end = 0, size - 1
        rng = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers.get('Range') or '')
        status = 200
        if rng and size:
            a, b = rng.groups()
            if a: start, end = int(a), min(int(b) if b else size - 1, size - 1)
            elif b: start = max(0, size - int(b))
            if start > end:
                return self.respond(416, b'', headers={'Content-Range': f'bytes */{size}'})
            status = 206
        ctype = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        quoted = urllib.parse.quote(target.name)
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Disposition', f"{'inline' if self.headers.get('Range') else 'attachment'}; filename*=UTF-8''{quoted}")
        self.send_header('Cache-Control', 'private, no-store')
        if status == 206: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD': return
        with target.open('rb') as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(1024 * 1024, left))
                    if not chunk: break
                    self.wfile.write(chunk); left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    # -- studio proxy
    def proxy(self, uid, path, inject=False):
        route = urllib.parse.urlsplit(path).path
        if route in ('/api/browse', '/api/open', '/api/shutdown'):
            return self.error(403, 'Bu amal onlayn studiyada mavjud emas.')
        try:
            body = self.read_body() if self.command == 'POST' else None
            own = folders(uid)
            if self.command == 'POST' and route in ('/api/plan', '/api/music-list', '/api/run'):
                data = json.loads(body or b'{}')
                if route == '/api/plan':
                    # Every folder is the account's own, whatever the page sent.
                    data.update({k: str(own[k]) for k in FOLDERS})
                    data['device'] = 'cpu'
                    try: total = int(float(data.get('total', 1)))
                    except (TypeError, ValueError): total = 1
                    if total > CONFIG['max_videos']:
                        return self.error(400, f'Onlayn studiyada bir martada ko‘pi bilan {CONFIG["max_videos"]} ta video.')
                if route == '/api/music-list':
                    data['music'] = str(own['music'])
                if route in ('/api/plan', '/api/run'):
                    if usage_bytes(uid) >= CONFIG['quota_gb'] * 1024**3:
                        return self.error(413, f'Disk kvotasi ({CONFIG["quota_gb"]:g} GB) to‘lgan. Eski natijalarni o‘chiring.')
                if route in ('/api/plan', '/api/run') and disk_full():
                    return self.error(507, DISK_FULL)
                if route == '/api/run' and STUDIOS.busy_count(exclude=uid) >= CONFIG['max_renders']:
                    return self.error(429, 'Server hozir boshqa montajni bajaryapti. Bir necha daqiqadan keyin qayta urinib ko‘ring.')
                body = json.dumps(data, ensure_ascii=False).encode()
            inst = STUDIOS.get(uid)
            headers = {k: v for k, v in (('Content-Type', self.headers.get('Content-Type')),
                                         ('X-MusicPro-Token', self.headers.get('X-MusicPro-Token'))) if v}
            if body is not None: headers['Content-Length'] = str(len(body))
            status, resp_headers, data = inst.call(self.command, path, body, headers,
                                                   timeout=120 if route == '/api/browse' else 60)
        except (ValueError, json.JSONDecodeError):
            return self.error(400, 'So‘rov noto‘g‘ri.')
        except (RuntimeError, OSError) as e:
            return self.error(503, str(e) or 'Studiya javob bermadi.')
        h = {k: v for k, v in resp_headers if k.lower() in ('content-type', 'content-disposition', 'cache-control')}
        if route == '/api/init' and status == 200:
            info = json.loads(data)
            info['config'] = {**info.get('config', {}), **{k: str(own[k]) for k in FOLDERS}, 'device': 'cpu'}
            info['platform'] = {'os': 'web', 'package': 'Onlayn studiya', 'launcher': 'sahifani',
                                'gpu_label': 'GPU', 'gpu_note': 'Onlayn studiyada render CPU orqali.'}
            data = json.dumps(info, ensure_ascii=False).encode()
        if inject and status == 200:
            html = data.decode('utf-8')
            html = html.replace('</head>', '<link rel="stylesheet" href="/cloud.css"></head>', 1)
            html = html.replace('</body>', '<script src="/cloud.js"></script></body>', 1)
            data = html.encode()
        ctype = h.pop('Content-Type', h.pop('content-type', 'application/octet-stream'))
        self.respond(status, data, ctype, {k: v for k, v in h.items()})


def main():
    global ACCOUNTS, STUDIOS
    CONFIG['data'].mkdir(parents=True, exist_ok=True)
    ACCOUNTS = Accounts(CONFIG['data'] / 'accounts.sqlite3')
    STUDIOS = Studios()
    server = ThreadingHTTPServer(('0.0.0.0', CONFIG['port']), Handler)
    server.daemon_threads = True
    log(f'MusicPro online on :{CONFIG["port"]} · data {CONFIG["data"]} · quota {CONFIG["quota_gb"]:g} GB · '
        f'max {CONFIG["max_videos"]} videos · {CONFIG["max_renders"]} concurrent render(s)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STUDIOS.stop_all()


if __name__ == '__main__':
    main()
