"""Download and verify the third-party binaries that are not kept in git.

    python3 developer/fetch_binaries.py [--platform windows|macos|all] [--force]

Every archive is checked against the SHA-256 recorded in THIRD_PARTY.md before
anything is extracted, and every placed file is checked against bundle.json,
the package lockfile. A mismatch stops the run: it means the publisher replaced
the file, and the new build must be verified on purpose, not silently adopted.

Works from any platform: the Windows files are plain archive members, so a Mac
can assemble the complete dual-platform bundle for a Windows release.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PTH_CONTENT = 'python313.zip\n.\n../app\n'   # embedded Python finds app/ through this
USER_AGENT = 'MusicPro-fetch/1.0 (+https://github.com)'


@dataclass
class Source:
    key: str
    platform: str
    url: str
    sha256: str
    size: int
    # zip member -> destination relative to the bundle root. A member given as
    # a suffix ("/bin/ffmpeg.exe") matches the first archive entry ending so.
    members: dict = field(default_factory=dict)
    # Extract every member flat into this directory (embedded Python runtime).
    extract_all_into: str | None = None
    executable: bool = False


SOURCES = [
    Source('windows-python', 'windows',
           'https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip',
           'd1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf', 11_009_825,
           extract_all_into='runtime'),
    # gyan.dev rotates its packages/ directory; the GitHub release is permanent.
    Source('windows-ffmpeg', 'windows',
           'https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/ffmpeg-9.0.1-essentials_build.zip',
           'fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9', 111_253_802,
           members={'/bin/ffmpeg.exe': 'app/bin/ffmpeg.exe', '/bin/ffprobe.exe': 'app/bin/ffprobe.exe'}),
    # These URLs are not version-pinned. If the checksum fails, the publisher
    # has uploaded a newer build: verify it, then update THIRD_PARTY.md and
    # bundle.json together.
    Source('macos-ffmpeg', 'macos', 'https://www.osxexperts.net/ffmpeg9arm.zip',
           'd0c06c5c68ce48af3143b262f7a9118a7c9f67de1e237fcc24ffb14df9c67af9', 22_608_364,
           members={'ffmpeg': 'app/bin/ffmpeg'}, executable=True),
    Source('macos-ffprobe', 'macos', 'https://www.osxexperts.net/ffprobe9arm.zip',
           '0c94fbdd8917022f28115eca512196cf4648732bc9e5db9ec8896c7e519d02aa', 22_530_006,
           members={'ffprobe': 'app/bin/ffprobe'}, executable=True),
]


class FetchError(RuntimeError):
    pass


class CertificateProblem(FetchError):
    """The interpreter cannot verify HTTPS certificates with its own CA bundle."""


CERT_HELP = ('Python cannot verify HTTPS certificates: its OpenSSL has no CA bundle.\n'
             '    macOS python.org builds: run "/Applications/Python 3.x/Install Certificates.command"\n'
             '    or install a bundle with:  python3 -m pip install certifi')


def sha256_of(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def load_manifest(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    try:
        return {f['path']: f['sha256'] for f in json.loads(path.read_text(encoding='utf-8')).get('files', [])}
    except (ValueError, KeyError, TypeError) as error:
        raise FetchError(f'{path} is not a valid manifest: {error}') from error


def open_url(url: str):
    """urllib with the interpreter's CA bundle, then certifi's; else report why."""
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        return urllib.request.urlopen(request, timeout=60)
    except urllib.error.URLError as error:
        if not isinstance(error.reason, ssl.SSLCertVerificationError):
            raise
    try:
        import certifi
    except ImportError:
        raise CertificateProblem(CERT_HELP) from None
    context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.urlopen(request, timeout=60, context=context)


def stream_with_urllib(url: str, part: Path, expected_size: int):
    done = 0; last = time.monotonic()
    with open_url(url) as response, part.open('wb') as out:
        total = int(response.headers.get('Content-Length') or expected_size or 0)
        while chunk := response.read(1024 * 1024):
            out.write(chunk); done += len(chunk)
            if time.monotonic() - last > 2:
                pct = f' {done * 100 // total:3d}%' if total else ''
                print(f'    {done / 1024**2:7.1f} MB{pct}', flush=True); last = time.monotonic()
    return done


def stream_with_curl(curl: str, url: str, part: Path):
    # curl uses the operating system's trust store on macOS and Windows alike.
    subprocess.run([curl, '--location', '--fail', '--silent', '--show-error',
                    '--user-agent', USER_AGENT, '--output', str(part), url], check=True)
    return part.stat().st_size


def download(url: str, target: Path, expected_size: int):
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + '.part')
    print(f'  downloading {url}')
    try:
        try:
            done = stream_with_urllib(url, part, expected_size)
        except CertificateProblem as problem:
            curl = shutil.which('curl')
            if not curl:
                raise FetchError(str(problem)) from problem
            print(f'    {CERT_HELP.splitlines()[0]}\n    using {curl} instead', flush=True)
            done = stream_with_curl(curl, url, part)
    except (OSError, subprocess.SubprocessError) as error:
        part.unlink(missing_ok=True)
        raise FetchError(f'download failed: {error}') from error
    part.replace(target)
    print(f'    {done / 1024**2:7.1f} MB done')


def ensure_archive(source: Source, cache: Path) -> Path:
    archive = cache / source.url.rsplit('/', 1)[-1]
    if archive.is_file():
        if sha256_of(archive) == source.sha256:
            print(f'  cached archive verified: {archive.name}')
            return archive
        print(f'  cached archive has the wrong checksum, downloading again: {archive.name}')
        archive.unlink()
    download(source.url, archive, source.size)
    actual = sha256_of(archive)
    if actual != source.sha256:
        archive.unlink(missing_ok=True)
        raise FetchError(
            f'{archive.name}: SHA-256 mismatch.\n'
            f'    expected {source.sha256}\n    actual   {actual}\n'
            '    The publisher has replaced this file. Do not use it blindly: verify the new build,\n'
            '    then update THIRD_PARTY.md, this script and bundle.json together.')
    print(f'  archive verified: {archive.name}')
    return archive


def safe_destination(root: Path, relative: str) -> Path:
    destination = (root / relative).resolve()
    if root.resolve() not in destination.parents:
        raise FetchError(f'refusing to write outside the bundle: {relative}')
    return destination


def write_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + '.tmp')
    with archive.open(info) as inp, temp.open('wb') as out:
        while chunk := inp.read(1024 * 1024):
            out.write(chunk)
    temp.replace(destination)


def extract(source: Source, archive_path: Path, root: Path) -> list[str]:
    placed = []
    with zipfile.ZipFile(archive_path) as archive:
        entries = [i for i in archive.infolist() if not i.is_dir() and not i.filename.startswith('__MACOSX/')]
        if source.extract_all_into:
            for info in entries:
                relative = f'{source.extract_all_into}/{Path(info.filename).name}'
                write_member(archive, info, safe_destination(root, relative)); placed.append(relative)
        for member, relative in source.members.items():
            match = next((i for i in entries if i.filename == member or i.filename.endswith(member)), None)
            if match is None:
                raise FetchError(f'{archive_path.name} does not contain {member}')
            write_member(archive, match, safe_destination(root, relative)); placed.append(relative)
    return placed


def finish(source: Source, root: Path, placed: list[str]):
    if source.extract_all_into == 'runtime':
        (root / 'runtime' / 'python313._pth').write_text(PTH_CONTENT, encoding='ascii')
    if source.executable:
        for relative in placed:
            path = root / relative
            path.chmod(0o755)
            if sys.platform == 'darwin':
                subprocess.run(['/usr/bin/xattr', '-d', 'com.apple.quarantine', str(path)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def expected_targets(source: Source, root: Path, manifest: dict[str, str]) -> list[str]:
    if source.extract_all_into:
        listed = [p for p in manifest if p.startswith(source.extract_all_into + '/')]
        return listed or [f'{source.extract_all_into}/{n}' for n in ('python.exe', 'pythonw.exe', 'python313.dll', 'python313.zip')]
    return list(source.members.values())


def already_present(source: Source, root: Path, manifest: dict[str, str]) -> bool:
    for relative in expected_targets(source, root, manifest):
        path = root / relative
        if not path.is_file():
            return False
        if relative in manifest and sha256_of(path) != manifest[relative]:
            return False
    return True


def verify_against_manifest(root: Path, placed: list[str], manifest: dict[str, str], strict: bool) -> int:
    problems = 0
    for relative in placed:
        actual = sha256_of(root / relative)
        if relative not in manifest:
            print(f'    {relative}: {actual[:16]}… (not listed in bundle.json)')
            continue
        if actual == manifest[relative]:
            print(f'    {relative}: matches bundle.json')
        else:
            problems += 1
            print(f'    {relative}: DIFFERS from bundle.json ({actual[:16]}… vs {manifest[relative][:16]}…)')
    if problems and strict:
        raise FetchError(f'{problems} placed file(s) differ from bundle.json. Verify the build, then run '
                         'developer/build_manifest.py if the new files are intended.')
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--platform', choices=('windows', 'macos', 'all'), default='all')
    parser.add_argument('--only', action='append', metavar='KEY', help='limit to one source key (repeatable); see --list')
    parser.add_argument('--force', action='store_true', help='re-extract even when files are present and verified')
    parser.add_argument('--root', type=Path, default=ROOT, help='bundle root to populate')
    parser.add_argument('--cache', type=Path, default=ROOT / 'developer' / '.cache', help='where archives are kept')
    parser.add_argument('--manifest', type=Path, default=None, help='bundle.json to verify against (default: <root>/bundle.json)')
    parser.add_argument('--no-manifest-check', action='store_true', help='only report manifest differences')
    parser.add_argument('--list', action='store_true', help='print the sources and exit')
    args = parser.parse_args()

    if args.list:
        for s in SOURCES:
            print(f'{s.key:16} {s.platform:8} {s.size:>12,}  {s.sha256}  {s.url}')
        return 0

    root = args.root.resolve()
    manifest_path = args.manifest if args.manifest else root / 'bundle.json'
    manifest = load_manifest(manifest_path)
    if not manifest:
        print(f'note: no manifest at {manifest_path}; placed files are hashed but not verified against a lockfile')
    selected = [s for s in SOURCES if args.platform == 'all' or s.platform == args.platform]
    if args.only:
        unknown = set(args.only) - {s.key for s in SOURCES}
        if unknown:
            parser.error(f'unknown source key(s): {", ".join(sorted(unknown))}; see --list')
        selected = [s for s in selected if s.key in args.only]
    failures = 0
    for source in selected:
        print(f'{source.key}:')
        try:
            if not args.force and already_present(source, root, manifest):
                print('  already present' + (' and verified against bundle.json' if manifest else '') + ', skipped')
                continue
            archive = ensure_archive(source, args.cache)
            placed = extract(source, archive, root)
            finish(source, root, placed)
            print(f'  placed {len(placed)} file(s)')
            verify_against_manifest(root, placed, manifest, strict=not args.no_manifest_check)
        except (FetchError, zipfile.BadZipFile, OSError) as error:
            failures += 1
            print(f'  FAILED: {error}', file=sys.stderr)
    print(f'{len(selected) - failures}/{len(selected)} sources ready' + (f', {failures} failed' if failures else ''))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
