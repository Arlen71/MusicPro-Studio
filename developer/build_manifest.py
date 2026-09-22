"""Regenerate bundle.json for the current bundle contents, on any platform.

build_release.py writes the same manifest while producing the Windows Setup and
portable ZIP, which needs Windows binaries and NSIS. This tool only refreshes the
SHA-256 manifest that portable_check.py verifies on the user's machine, so the
macOS side of the bundle can be maintained without a Windows release run.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_release import EXCLUDE

# Finder and editor droppings are not part of the delivered package.
IGNORED_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}
IGNORED_SUFFIXES = {'.pyc', '.pdb'}

METADATA = {
    'product': 'MusicPro Studio',
    'version': '1.8.0',
    'platform': 'windows-amd64 + macos-arm64',
    'launcher': '1.5.0 (unchanged) · macOS: MusicPro.command',
    'python': '3.13.15 embedded (Windows) · 3.11+ system (macOS)',
    'ffmpeg': '9.0.1-essentials (Windows) · 9.0 arm64 static (macOS)',
}


def bundle_files(bundle: Path):
    return sorted(p for p in bundle.rglob('*') if p.is_file()
                  and not any(s in EXCLUDE for s in p.relative_to(bundle).parts)
                  and p.name not in IGNORED_NAMES
                  and p.suffix not in IGNORED_SUFFIXES)


def build(bundle: Path) -> dict:
    manifest = {**METADATA, 'files': []}
    for path in bundle_files(bundle):
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        manifest['files'].append({'path': path.relative_to(bundle).as_posix(),
                                  'size': path.stat().st_size, 'sha256': digest})
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--check', action='store_true',
                        help='Report drift without rewriting bundle.json.')
    parser.add_argument('--ignore-missing', action='store_true',
                        help='With --check: files listed in bundle.json but absent on disk are reported, '
                             'not counted as drift. For checkouts without the fetched binaries (CI).')
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    manifest = build(bundle)
    target = bundle/'bundle.json'

    if args.check:
        try:
            current = json.loads(target.read_text(encoding='utf-8')).get('files', [])
        except (OSError, ValueError):
            current = []
        was = {f['path']: f['sha256'] for f in current}
        now = {f['path']: f['sha256'] for f in manifest['files']}
        added = sorted(now.keys() - was.keys())
        removed = sorted(was.keys() - now.keys())
        changed = sorted(p for p in now.keys() & was.keys() if now[p] != was[p])
        missing = [p for p in removed if not (bundle / p).exists()] if args.ignore_missing else []
        removed = [p for p in removed if p not in missing]
        for label, items in (('added', added), ('removed', removed), ('changed', changed), ('missing', missing)):
            for item in items:
                print(f'{label:8} {item}')
        print(f'{len(manifest["files"])} files; {len(added)} added, {len(removed)} removed, {len(changed)} changed'
              + (f', {len(missing)} missing (ignored)' if args.ignore_missing else ''))
        raise SystemExit(1 if added or removed or changed else 0)

    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{target}: {len(manifest["files"])} files')


if __name__ == '__main__':
    main()
