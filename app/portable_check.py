"""On-device diagnostics for an offline bundle. Leaves user media untouched."""
from __future__ import annotations
import hashlib
import json
import platform
import sys
import tempfile
import zipfile
from pathlib import Path
from runtime_support import VERSION


def check() -> str:
    from engine import binary, execute
    from reports import workbook_bytes
    from effects import EFFECTS, effect_filters
    from resources import ResourceGovernor, render_budget
    root = Path(__file__).resolve().parent
    lines = ['MusicPro Studio ' + VERSION, platform.platform(), sys.version, '']
    manifest = root.parent / 'bundle.json'
    if manifest.is_file():
        for item in json.loads(manifest.read_text(encoding='utf-8')).get('files', []):
            file = root.parent / item['path']
            with file.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            if digest != item['sha256']:
                raise RuntimeError('Paket fayli o‘zgargan yoki buzilgan: ' + item['path'])
        lines.append('PASS: paket fayllari SHA-256 bilan tekshirildi.')
    for name in ('ffmpeg', 'ffprobe'):
        version = execute([binary(name), '-version'], timeout=30).splitlines()[0]
        lines.append(version)
    with tempfile.TemporaryDirectory(prefix='MusicPro_check_') as folder:
        video = Path(folder)/'test.mp4'
        execute([binary('ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                 'color=c=0x30cfa0:s=1280x720:r=30', '-f', 'lavfi', '-i',
                 'sine=frequency=440:sample_rate=48000', '-t', '1', '-c:v', 'libx264',
                 '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(video)], timeout=120)
        parsed = json.loads(execute([binary('ffprobe'), '-v', 'error', '-show_streams',
                                     '-of', 'json', str(video)], timeout=30))
        kinds = {s['codec_type'] for s in parsed['streams']}
        if not {'audio', 'video'} <= kinds:
            raise RuntimeError('Sinov videosida audio yoki video oqimi yo‘q.')
        lines.append('PASS: CPU H.264 720p + AAC audio sinov videosi.')
        for preset in EFFECTS:
            filters=effect_filters(dict(kind='clip',frames=12,fx_in=preset,fx_out=preset),30,1280,720)
            execute([binary('ffmpeg'),'-v','error','-filter_threads','1','-f','lavfi','-i',
                     'testsrc2=s=1280x720:r=30','-vf',','.join(filters+['format=yuv420p']),
                     '-frames:v','12','-c:v','libx264','-threads','1','-f','null','-'],timeout=120)
        lines.append('PASS: 6 ta edit effekti haqiqiy CPU kodlovchisida tekshirildi.')
        xlsx = Path(folder)/'test.xlsx'
        xlsx.write_bytes(workbook_bytes([["VIDEO LINKI NI QO'YING", 'CS00001 (1)', '01:01', '01:10']]))
        with zipfile.ZipFile(xlsx) as z:
            if z.testzip() is not None: raise RuntimeError('Excel shabloni buzilgan.')
        lines.append('PASS: Excel hisoboti.')
    governor=ResourceGovernor('medium',lines.append)
    try: governor.start()
    finally: governor.close()
    for profile in ('auto','medium','high'):
        limits=render_budget(dict(resources=profile,height=1080),['cpu','gpu'])
        lines.append('Resurs hisob-kitobi: '+json.dumps(limits,ensure_ascii=False))
    lines += ['', 'Bu tekshiruv GPU drayveri va papka tanlash oynasini sinamaydi.',
              'GPU ishlatilsa, loyiha rejasini tuzishda kodlovchi alohida tekshiriladi.']
    return '\n'.join(lines)


if __name__ == '__main__':
    print(check())
