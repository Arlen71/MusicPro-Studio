"""Real macOS verification: VideoToolbox lane, mixed lanes and platform helpers.

The other e2e scripts only exercise the CPU encoder, which is identical on both
platforms. This one covers what is specific to the macOS build: hardware H.264
through VideoToolbox, a shared CPU+GPU queue, the Finder folder picker helper,
the Application Support data directory and the real memory reading.
"""
import json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

if sys.platform != 'darwin':
    raise SystemExit('Bu tekshiruv faqat macOS uchun.')

BASE = Path(__file__).resolve().parents[1]
APP = BASE/'app'
sys.path.insert(0, str(APP))
from engine import execute, binary, probe, encoding_args, GPU_ENCODERS
from reports import REPORT_NAME
from resources import available_memory_gb, macos_available_gb
from runtime_support import data_directory
import folder_dialog

# --- Platform helpers, before spending time on real renders ------------------
assert GPU_ENCODERS == ('h264_videotoolbox',), GPU_ENCODERS
assert encoding_args('h264_videotoolbox', 'balanced') == ['-c:v','h264_videotoolbox','-q:v','60','-allow_sw','1']

# A live reading drifts between calls; it must stay a plausible, real figure and
# never fall back to the hardcoded 4.0 GB that a missing SC_AVPHYS_PAGES gave.
total = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 1024**3
memory = available_memory_gb()
assert 0.25 < memory <= total, (memory, total)
assert abs(memory - macos_available_gb()) < max(.5, memory * .25), memory

assert folder_dialog.choose_folder.__module__ == 'folder_dialog'
assert 'choose folder with prompt' in folder_dialog.MAC_SCRIPT
# The AppleScript itself must parse, without ever showing a panel.
subprocess.run(['/usr/bin/osascript', '-e', folder_dialog.MAC_SCRIPT.replace('activate', 'return ""', 1)],
               capture_output=True, timeout=60, check=True)


class _Result:
    def __init__(self, stdout): self.returncode, self.stdout, self.stderr = 0, stdout, ''


def _picked(stdout):
    real = subprocess.run
    subprocess.run = lambda *a, **k: _Result(stdout)
    try: return folder_dialog.choose_folder_macos()
    finally: subprocess.run = real


# A chosen folder loses the AppleScript trailing separator; cancelling is empty,
# not an error, so the browse button behaves exactly like the Windows helper.
assert _picked('/Users/x/Mening papkam/\n') == '/Users/x/Mening papkam'
assert _picked('/\n') == '/'
assert _picked('\n') == ''

with tempfile.TemporaryDirectory(prefix='MusicPro macOS Ўзбек ') as temp:
    root = Path(temp).resolve()
    installed = root/'installed'
    (installed/'app').mkdir(parents=True)
    (installed/'bundle.json').write_text('{}')
    (installed/'installed.flag').write_text('installed')
    saved = os.environ.pop('MUSICPRO_DATA_DIR', None)
    try:
        assert data_directory(installed/'app') == Path.home()/'Library/Application Support/MusicProStudio/data'
    finally:
        if saved is not None: os.environ['MUSICPRO_DATA_DIR'] = saved
    print('PASS: VideoToolbox selection, memory reading, Finder picker helper, Application Support path.', flush=True)

    # --- Real renders through the HTTP server and isolated workers ------------
    for name in ('clips','licenses','music','output','data'): (root/name).mkdir()
    for name, color, duration, folder in [('a','blue',1.3,'clips'), ('b','green',1.9,'clips'),
                                          ('CS00652 (17)','red',9.4,'licenses')]:
        execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i',
                 f'color={color}:s=320x180:r=30:d={duration}','-c:v','libx264',
                 str(root/folder/(name+'.mp4'))])
    execute([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i',
             'sine=frequency=440:duration=8.4', str(root/'music/Ўзбек trek.wav')])

    env = {**os.environ, 'MUSICPRO_DATA_DIR': str(root/'data')}
    server = subprocess.Popen([sys.executable, str(APP/'app.py'), '--no-browser'],
                              env=env, stdout=subprocess.PIPE, text=True)
    try:
        address = server.stdout.readline().strip().split('MusicPro: ')[1]
        def get(path): return json.load(urllib.request.urlopen(address+'/api/'+path, timeout=10))
        token = get('init')['token']
        def post(path, body=None):
            request = urllib.request.Request(address+'/api/'+path, data=json.dumps(body or {}).encode(),
                                             headers={'Content-Type':'application/json','X-MusicPro-Token':token})
            return urllib.request.urlopen(request, timeout=30).read()
        def settled():
            for _ in range(3000):
                state = get('state')
                if not state['busy']: return state
                time.sleep(.1)
            raise AssertionError('Timeout')

        base = {k: str(root/k) for k in ('clips','licenses','music','output')}
        base.update(license_count=1, first_license=1, license_gap=.5, fps=30, height=720,
                    quality='balanced', mode='random', cut_min=.5, cut_max=1.2,
                    resources='medium', effects='edit', effect_strength='balanced')

        for device, expected in (('gpu', {'h264_videotoolbox'}), ('mixed', {'h264_videotoolbox','libx264'})):
            post('plan', {**base, 'device': device, 'total': 2})
            state = settled()
            assert state['status'] == 'ready', state['message']
            assert state['summary']['gpu'] == 'h264_videotoolbox', state['summary']
            post('run')
            state = settled()
            assert state['status'] == 'completed', state['message']
            used = {job['encoder'] for job in state['jobs']}
            assert used <= expected and used, (device, used)
            if device == 'gpu': assert used == {'h264_videotoolbox'}, used
            for job in state['jobs']:
                assert job['status'] == 'done', job
                folder = Path(job['dest'])
                video = folder/job['video_filename']
                assert abs(probe(video, 'audio')['duration'] - 8.4) < .07, video
                assert abs(probe(video, 'video')['duration'] - 8.4) < .12, video
                assert (folder/REPORT_NAME).is_file(), folder
                for licensed in job['licenses']:
                    assert 5-1e-6 <= licensed['end']-licensed['start'] <= 7+1e-6, licensed
                notes = (folder/'render_diagnostics.txt').read_text(encoding='utf-8')
                assert job['encoder'] in notes, notes[:400]
            print(f'PASS: device={device} — {len(state["jobs"])} real videos, encoders {sorted(used)}.', flush=True)

        post('shutdown'); server.wait(timeout=20)
        assert server.returncode == 0
        print('PASS: macOS VideoToolbox and shared CPU+GPU queue produce verified real outputs.', flush=True)
    finally:
        if server.poll() is None:
            server.terminate(); server.wait(timeout=10)
