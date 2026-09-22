# MusicPro Studio 1.8 packaging source

This release is delivered as a complete offline portable ZIP. Application code
and the UI are version 1.8.0. The native Windows launcher remains the exact
1.5.0 binary and source, since it only starts the embedded Python application.
Python 3.13.15 and FFmpeg 9.0.1 are also unchanged from the verified 1.5 bundle.
No new native binaries or Setup EXE were compiled in this build environment.

Build the portable archive from the populated bundle:

```
python build_release.py --bundle .. --portable-only --out ../../MusicPro_1_8_release
```

The script validates AMD64 PE files, generates a SHA-256 manifest, excludes
personal data/caches, and validates ZIP CRCs. It also generates explicit file
lists for an optional developer-built installer. The source for an installer
is retained, but an installer is not part of the delivered 1.8 release.

To build a Setup on a development computer with NSIS available:

```
python build_release.py --bundle .. --makensis makensis --out ../../dist
```

End users do not need NSIS, a compiler, Python, pip, or FFmpeg installations.
They extract the portable ZIP and launch MusicPro.exe. Installed 1.5 users can
copy their existing LOCALAPPDATA/MusicProStudio/data into the new portable
folder as described in BOSHLASH.html; the previous installation remains intact.

Run application tests from app with:

```
python -m unittest discover -s tests -v
```

The retained native launcher sources can be rebuilt with Zig 0.15.2 as before:

```
zig rc /fo launcher.res launcher.rc
zig cc -target x86_64-windows-gnu -municode -Wl,--subsystem,windows -O2 -s launcher.c launcher.res -o ../MusicPro.exe -luser32
```

Update native version metadata when changing the launcher itself. Native
Windows installation, GPU hardware compatibility, and CPU Job Object behavior
must be accepted on a real Windows machine before broader deployment. A Linux
cross-build or scheduler simulation is not that hardware test.

1.8 adds independent playlist selections for each output job, supporting all
playlist positions (Top 5, Top 10 and up to the existing 1000-track limit).
The per-video mapping overrides legacy global first/second/third selections.
Missing or disabled entries and blank slots use automatic random selection.
Legacy sessions without the new mapping keep their original behavior.
Run the focused HTTP/CPU integration check with:

```
python developer/e2e_per_video.py
```

Run this command from the bundle root. Tests use temporary media and data.
The unchanged native launcher starts the new Python/UI version 1.8.0.

## Repository tooling

The git repository does not carry the third-party binaries (about 320 MB).
A fresh clone is completed with:

```
python3 developer/fetch_binaries.py             # both platforms
python3 developer/fetch_binaries.py --platform windows
python3 developer/fetch_binaries.py --list      # sources, sizes, SHA-256
```

Every archive is verified against the SHA-256 in `THIRD_PARTY.md` before it is
opened, and every placed file against `bundle.json`. The Windows FFmpeg comes
from the permanent GitHub release of gyan.dev's build; the macOS binaries are
served from unversioned URLs, so a checksum failure there means the publisher
has moved to a newer build that must be verified deliberately. On a python.org
macOS interpreter without a CA bundle the script falls back to `certifi`, then
to the system `curl`.

Day-to-day tasks are collected in `developer/tasks.py` (`make <task>` on Unix,
`py developer\tasks.py <task>` on Windows): `test`, `e2e`, `check`, `manifest`,
`lint`, `fetch`, `run`, `clean`, `ci`. `ruff` configuration is in `pyproject.toml`;
only defect classes are enforced, the application's dense one-line style is not.

## macOS (Apple Silicon)

The same bundle runs on macOS. Nothing is compiled: `MusicPro.command` and
`TEKSHIRISH.command` are shell launchers, the application is the same `app/`
source, and the platform differences are guarded by `os.name`/`sys.platform`.
The Windows binaries, `runtime/` and `app/win_dialog.py` are untouched.

What the macOS side needs in the bundle:

- `app/bin/ffmpeg`, `app/bin/ffprobe` — FFmpeg 9.0 arm64 static, GPL with
  libx264. Sources and checksums are in `THIRD_PARTY.md`. Mark them executable
  and clear `com.apple.quarantine`; both launchers do this defensively.
- `app/folder_dialog.py` — picks the platform's folder panel. On Windows it
  delegates to the existing `win_dialog.py`; on macOS it drives the Finder panel
  through `osascript`. `app.py` spawns this module, not `win_dialog.py`.
- No Python runtime. The launchers look for Python 3.11+ in `MUSICPRO_PYTHON`,
  `PATH`, Homebrew, `/usr/local/bin` and the Python.framework, in that order.
  `/usr/bin/python3` is tried last because it can require the Xcode licence.

GPU encoding uses `h264_videotoolbox` with `-q:v` constant quality; the Windows
NVENC/QSV/AMF probe order is unchanged. macOS has no Job Object CPU rate cap, so
the `auto` profile lowers worker priority with `nice` instead, and the thread and
parallel-segment budget still applies. `available_memory_gb()` reads `vm_stat`,
because macOS does not expose `SC_AVPHYS_PAGES`.

After changing any packaged file, refresh the checksum manifest that
`portable_check.py` verifies on the user's machine — this runs on any platform,
unlike `build_release.py`, which needs the Windows binaries and NSIS:

```
python3 developer/build_manifest.py            # rewrite bundle.json
python3 developer/build_manifest.py --check    # report drift, exit 1 if any
```

Run the macOS-specific verification from the bundle root:

```
python3 developer/e2e_macos.py
```

It renders real videos through VideoToolbox and through a shared CPU+GPU queue,
and checks the Finder picker helper, the Application Support data directory and
the memory reading. Intel Macs are not covered: the bundled binaries are arm64.
