"""Rebuild offline deliverables from an already populated, verified bundle."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import struct
import subprocess
import zipfile
from pathlib import Path

EXCLUDE = {'data', '__pycache__', '.git', 'installed.flag', 'Uninstall.exe',
           'bundle.json', 'install_files.nsh', 'uninstall_files.nsh', 'launcher.res',
           # Repository and developer tooling; end users never need these.
           '.gitignore', '.gitattributes', '.editorconfig', 'pyproject.toml', 'Makefile',
           '.ruff_cache', '.pytest_cache', '.venv', '.cache', 'dist'}


def portable_files(bundle: Path):
    return sorted(p for p in bundle.rglob('*') if p.is_file()
                  and not any(s in EXCLUDE for s in p.relative_to(bundle).parts)
                  and p.suffix not in {'.pyc', '.pdb'})


def validate_pe(path: Path, gui=False):
    data = path.read_bytes()
    if data[:2] != b'MZ': raise RuntimeError('Not a Windows binary: ' + str(path))
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    if data[offset:offset+4] != b'PE\0\0': raise RuntimeError('Invalid PE: ' + str(path))
    if struct.unpack_from('<H', data, offset+4)[0] != 0x8664:
        raise RuntimeError('Expected AMD64: ' + str(path))
    if gui and struct.unpack_from('<H', data, offset+24+68)[0] != 2:
        raise RuntimeError('Launcher must use the GUI subsystem.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--makensis')
    parser.add_argument('--portable-only', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.portable_only and not args.makensis:
        parser.error('--makensis is required unless --portable-only is selected')
    bundle = args.bundle.resolve()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    developer = bundle/'developer'
    required = ['MusicPro.exe', 'runtime/python.exe', 'runtime/pythonw.exe',
                'runtime/python313.dll', 'runtime/python313.zip', 'runtime/python313._pth',
                'app/bin/ffmpeg.exe', 'app/bin/ffprobe.exe', 'app/bootstrap.py',
                'app/app.py', 'app/worker.py', 'app/win_dialog.py', 'app/effects.py', 'app/resources.py',
                'app/batch.py', 'app/audio_analysis.py', 'app/failures.py', 'app/playlist.py', 'app/output_names.py',
                'app/assets/report_template.xlsx', 'BOSHLASH.html']
    for name in required:
        if not (bundle/name).is_file(): raise RuntimeError('Missing: ' + name)
    for name in ['MusicPro.exe', 'runtime/python.exe', 'runtime/pythonw.exe',
                 'app/bin/ffmpeg.exe', 'app/bin/ffprobe.exe']:
        validate_pe(bundle/name, gui=name == 'MusicPro.exe')
    if '../app' not in (bundle/'runtime/python313._pth').read_text().splitlines():
        raise RuntimeError('Embedded Python cannot find the application.')
    files = portable_files(bundle)
    manifest = {'product':'MusicPro Studio','version':'1.8.0','platform':'windows-amd64',
                'launcher':'1.5.0 (unchanged)', 'python':'3.13.15','ffmpeg':'9.0.1-essentials','files':[]}
    for p in files:
        with p.open('rb') as f: digest = hashlib.file_digest(f, 'sha256').hexdigest()
        manifest['files'].append({'path':p.relative_to(bundle).as_posix(),
                                  'size':p.stat().st_size,'sha256':digest})
    (bundle/'bundle.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2),encoding='utf-8')
    files.append(bundle/'bundle.json');files.sort()
    install = []; uninstall = []; previous = None; directories = set()
    for file in files:
        rel = file.relative_to(bundle)
        dest = str(rel.parent).replace('/', '\\')
        dest = '' if dest == '.' else '\\' + dest
        if dest != previous:
            install.append('SetOutPath "$INSTDIR' + dest + '"')
            previous = dest
        rel_win = str(rel).replace('/', '\\')
        install.append('File "${APPDIR}/' + rel.as_posix() + '"')
        uninstall.append('Delete "$INSTDIR\\' + rel_win + '"')
        for parent in rel.parents:
            if str(parent) != '.': directories.add(str(parent).replace('/', '\\'))
    # Remove only named package files and directories that have become empty.
    uninstall += ['RMDir "$INSTDIR\\' + d + '"' for d in sorted(directories,key=lambda x:(x.count('\\'),x),reverse=True)]
    (developer/'install_files.nsh').write_text('\n'.join(install)+'\n',encoding='utf-8')
    (developer/'uninstall_files.nsh').write_text('\n'.join(uninstall)+'\n',encoding='utf-8')
    deliverables = []
    if not args.portable_only:
        setup = out/'MusicPro_Studio_1.8_Setup.exe'
        compiler = str(Path(args.makensis).resolve()) if Path(args.makensis).exists() else args.makensis
        prefix = '/' if os.name == 'nt' else '-'
        subprocess.run([compiler,prefix+'V2',prefix+'DAPPDIR='+str(bundle),
                        prefix+'DOUTFILE='+str(setup),'setup.nsi'], cwd=developer,check=True)
        deliverables.append(setup)
    archive = out/'MusicPro_Studio_1.8_Portable.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:
            z.write(p, 'MusicPro_Studio_1.8/' + p.relative_to(bundle).as_posix())
    with zipfile.ZipFile(archive) as z:
        bad = z.testzip()
        if bad: raise RuntimeError('ZIP damaged: '+bad)
    sums = []
    for p in [*deliverables,archive]:
        with p.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
        sums.append(digest+'  '+p.name)
        print(p.name, p.stat().st_size, 'bytes', digest, flush=True)
    (out/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n',encoding='ascii')


if __name__ == '__main__': main()
