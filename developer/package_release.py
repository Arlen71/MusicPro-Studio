"""Build the ready-to-run download ZIPs for one release, from any platform.

    python3 developer/package_release.py [--out dist]

Produces MusicPro_Studio_<version>_macOS.zip and ..._Windows.zip. Each contains
only its own platform's binaries and launchers, plus its own bundle.json, so
TEKSHIRISH verifies exactly what was shipped. Unix permissions are stored, so
MusicPro.command and the macOS FFmpeg stay executable after unzipping.
Run developer/fetch_binaries.py first: every binary must already be present.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'developer'))
sys.path.insert(0, str(ROOT / 'app'))
from build_manifest import bundle_files  # noqa: E402
from runtime_support import VERSION  # noqa: E402

WINDOWS_ONLY = ('MusicPro.exe', 'START.bat', 'TEKSHIRISH.bat', 'runtime/',
                'app/bin/ffmpeg.exe', 'app/bin/ffprobe.exe')
MACOS_ONLY = ('MusicPro.command', 'TEKSHIRISH.command', 'README_MAC.txt',
              'app/bin/ffmpeg', 'app/bin/ffprobe')
EXECUTABLE = {'MusicPro.command', 'TEKSHIRISH.command', 'app/bin/ffmpeg', 'app/bin/ffprobe'}

TARGETS = {
    'macOS': dict(drop=WINDOWS_ONLY, platform='macos-arm64',
                  launcher='MusicPro.command', python='3.11+ system (python.org)',
                  ffmpeg='9.0 arm64 static', need=('app/bin/ffmpeg', 'app/bin/ffprobe')),
    'Windows': dict(drop=MACOS_ONLY, platform='windows-amd64',
                    launcher='1.5.0 (unchanged)', python='3.13.15 embedded',
                    ffmpeg='9.0.1-essentials',
                    need=('MusicPro.exe', 'runtime/pythonw.exe', 'app/bin/ffmpeg.exe', 'app/bin/ffprobe.exe')),
}


def dropped(rel: str, patterns) -> bool:
    return any(rel == p or (p.endswith('/') and rel.startswith(p)) for p in patterns)


def sha256(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def build(name: str, spec: dict, out: Path) -> Path:
    for rel in spec['need']:
        if not (ROOT / rel).is_file():
            raise SystemExit(f'{rel} is missing — run developer/fetch_binaries.py first.')
    files = [p for p in bundle_files(ROOT)
             if not dropped(p.relative_to(ROOT).as_posix(), spec['drop'])
             and p.relative_to(ROOT).parts[0] not in ('site', 'dist')]
    manifest = {'product': 'MusicPro Studio', 'version': VERSION, 'platform': spec['platform'],
                'launcher': spec['launcher'], 'python': spec['python'], 'ffmpeg': spec['ffmpeg'],
                'files': [{'path': p.relative_to(ROOT).as_posix(), 'size': p.stat().st_size,
                           'sha256': sha256(p)} for p in files]}
    top = f'MusicPro_Studio_{VERSION}/'
    archive = out / f'MusicPro_Studio_{VERSION}_{name}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo.from_file(path, top + rel)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ((0o100755 if rel in EXECUTABLE else 0o100644) << 16)
            with path.open('rb') as src:
                z.writestr(info, src.read(), compresslevel=6)
        info = zipfile.ZipInfo(top + 'bundle.json', date_time=(2026, 1, 1, 0, 0, 0))
        info.external_attr = 0o100644 << 16
        z.writestr(info, json.dumps(manifest, ensure_ascii=False, indent=2), zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit(f'{archive.name}: damaged entry {bad}')
    print(f'{archive.name}: {len(files) + 1} files, {archive.stat().st_size / 1024**2:.1f} MB, sha256 {sha256(archive)}')
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist')
    parser.add_argument('--only', choices=list(TARGETS))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    built = [build(n, s, args.out) for n, s in TARGETS.items() if not args.only or n == args.only]
    (args.out / 'SHA256SUMS.txt').write_text(''.join(f'{sha256(a)}  {a.name}\n' for a in built), encoding='ascii')


if __name__ == '__main__':
    main()
