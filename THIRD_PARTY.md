# MusicPro Studio 1.8 — bundled components

MusicPro invokes FFmpeg/ffprobe as separate executable programs. Their binaries
are unmodified. Python configuration `python313._pth` adds `../app` to the
isolated module search path. MusicPro does not change system PATH or install
global Python packages. Source for the MusicPro application is in `app/`;
launcher and packaging source is in `developer/`.

The package runs on Windows x64 and on macOS (Apple Silicon). Each platform has
its own FFmpeg binaries in `app/bin/`; the macOS side uses the Python already
installed on the computer instead of an embedded runtime. Both are listed below.

## Python

- CPython 3.13.15 Windows embeddable distribution, AMD64, published by Python.org.
- Binary: https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip
- Release and checksum: https://www.python.org/downloads/release/python-31315/
- SHA-256: d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf
- License and bundled component notices: `runtime/LICENSE.txt`.
- Source: https://www.python.org/ftp/python/3.13.15/Python-3.13.15.tar.xz
- Embedding documentation: https://docs.python.org/3.13/using/windows.html#windows-embeddable

## FFmpeg

- FFmpeg 9.0.1 essentials build, AMD64, published by Gyan Doshi.
- Binary (permanent GitHub release asset; gyan.dev rotates its packages/ directory):
  https://github.com/GyanD/codexffmpeg/releases/download/9.0.1/ffmpeg-9.0.1-essentials_build.zip
- Original download: https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.1-essentials_build.zip
- SHA-256: fec81ae03971d9dd4be3ebe02e263bd2ec1d789483f931bdba5f5715e65da2e9
- Upstream download page: https://ffmpeg.org/download.html
- Build publisher: https://www.gyan.dev/ffmpeg/builds/
- GPL version 3 and build information are preserved in `licenses/ffmpeg/`.
- FFmpeg source revision: https://github.com/FFmpeg/FFmpeg/tree/bf1b838f2a
- Release source: https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz
- Exact configure options and external library version identifiers are listed in
  `licenses/ffmpeg/README.txt`. These external components retain their own licenses.
- Build publisher's source/build repository: https://github.com/GyanD/codexffmpeg
- FFmpeg license details: https://ffmpeg.org/legal.html

Keep license notices when sharing this package. Public redistribution of the GPL
binaries also requires providing corresponding source under their license; the
URLs above identify the upstream projects and do not replace that obligation.
No code-signing certificate has been applied to MusicPro.exe or Setup.exe.

## FFmpeg — macOS arm64

- FFmpeg 9.0 static build, Apple Silicon (arm64), published by OSXExperts.net,
  one of the macOS build sources listed on the upstream FFmpeg download page.
- Binaries: https://www.osxexperts.net/ffmpeg9arm.zip
  https://www.osxexperts.net/ffprobe9arm.zip
- Archive SHA-256:
  `d0c06c5c68ce48af3143b262f7a9118a7c9f67de1e237fcc24ffb14df9c67af9`  ffmpeg9arm.zip
  `0c94fbdd8917022f28115eca512196cf4648732bc9e5db9ec8896c7e519d02aa`  ffprobe9arm.zip
- Installed binaries `app/bin/ffmpeg`, `app/bin/ffprobe`; their SHA-256 values are
  recorded in `bundle.json` and verified by TEKSHIRISH.command.
- Built with `--enable-gpl --enable-libx264`, so the same GPL version 3 notice in
  `licenses/ffmpeg/` applies to this build as well. It is used unmodified and is
  invoked as a separate executable program, exactly like the Windows build.
- Upstream download page: https://ffmpeg.org/download.html
- Release source: https://ffmpeg.org/releases/ffmpeg-9.0.tar.xz
- FFmpeg license details: https://ffmpeg.org/legal.html
- These binaries are not code-signed or notarized by Apple. macOS marks files
  downloaded from a browser with a quarantine attribute; the launcher clears it
  for these two files only.

## Python — macOS

- The macOS package does not embed a Python runtime. It uses the Python 3.11 or
  newer already installed on the computer, published by Python.org or Homebrew.
- Official installers: https://www.python.org/downloads/macos/
- Python is licensed under the PSF License Agreement:
  https://docs.python.org/3/license.html

## Installer and launcher

- NSIS 3.09 builds the installer. https://nsis.sourceforge.io/
- NSIS license notices are in `licenses/nsis/`.
- Zig 0.15.2 is used only as a build tool, not required on the destination computer.
- Win32 launcher source is included. It requests the current user's privileges.
