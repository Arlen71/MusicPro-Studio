# MusicPro Studio 1.8 — validation

Target: Windows 10/11 x64. Application/UI version: 1.8.0.
Executed on Linux with Python 3.12 and local FFmpeg.

## Executed for this release

- 79 automated tests passed in 43.518 seconds: all 72 previous tests and
  7 new per-video playlist selection/recovery tests.
- Separate complete Top 10 orders and sparse selected slots (including the
  fifth and tenth positions) retain their positions across 20 random seeds.
  Random gaps vary and do not steal songs selected in later positions.
- An absent video entry, a disabled entry, or all blank slots use automatic
  selection. Single-music mode ignores the playlist editor. Legacy global
  first/second/third settings remain supported when the new mapping is absent.
- Duplicate active selections are rejected within a video; the same songs
  can be used across different videos. Invalid payloads and folder mismatches
  are rejected. JSON roundtrip and reducing/restoring counts retain choices.
- Each new playlist plan is bound to its output job. A plan from another job
  cannot silently override that video's selections.
- Selected damaged music is replaced automatically in its own position;
  other healthy positions and the other video's independent order remain.
  First-track replacement still updates names and Playlist TXT.
- A real HTTP/isolated-worker test completed THREE 720p CPU videos with five
  tracks each: two different complete Top 5 orders and one automatic playlist.
  All 15 actual decoded audio positions matched the respective planned song.
- That integration test verifies output naming, collision-compatible names,
  exact Playlist TXT bytes and download, report existence, audio/video duration,
  and preservation of all per-video selections and completed jobs after restart.
- JavaScript syntax, all literal DOM element references, unique HTML IDs and
  presence of the per-video editor controls passed static checks.
- The two HTML guides match. 41 protected Windows/native/runtime files remain
  byte-identical to version 1.7, including the launcher and native sources,
  embedded Python and FFmpeg binaries.
- Rendering engine, audio analysis, effects, resources, Excel reports, worker,
  folder picker, output naming and HTTP/scheduler application modules remain
  byte-identical to 1.7. Changes are limited to playlist configuration/selection,
  per-job plan validation, the editor, app version, docs and tests/build metadata.

## macOS (Apple Silicon) — executed for the macOS port

Host: macOS 26.6.1, Apple M1 Pro (arm64), 16 GB, Python 3.14.7,
bundled FFmpeg/ffprobe 9.0 arm64 static (GPL, libx264) in `app/bin/`.

- All 79 automated tests pass unchanged. Three earlier failures were test-only
  assumptions that a temp directory equals its resolved path; macOS resolves
  `/var` to `/private/var`, so those tests now resolve their own temp root.
  No application path handling was changed.
- The four existing end-to-end scripts pass: `e2e_portable`, `e2e_playlist`,
  `e2e_recovery` and `e2e_per_video` — real HTTP server, isolated workers,
  real encoded video/audio, damaged-source recovery, exact Playlist TXT and
  Excel bytes, Unicode paths, quit/reopen with the queue preserved.
- `TEKSHIRISH.command` passes: SHA-256 manifest of all 134 bundle files, real
  CPU H.264 720p + AAC render, all 6 edit effects through the real encoder,
  and the Excel report.
- New `developer/e2e_macos.py` passes: two real videos encoded by
  `h264_videotoolbox`, then two more with `device=mixed` where the shared queue
  used both `h264_videotoolbox` and `libx264`. Audio and video durations,
  licensed 5–7 second excerpts, reports and per-job diagnostics were verified
  for every output. It also covers the Finder picker helper's trailing-separator
  and cancel handling, the Application Support data directory, and the live
  memory reading that replaces the missing `SC_AVPHYS_PAGES`.
- `MusicPro.command` was launched for real: it finds Python 3.11+, starts the
  server detached, reports the address, serves the UI, and the in-page Exit
  button shuts it down cleanly. The page reports the macOS launcher name,
  package label and VideoToolbox wording from `/api/init`.
- The `/api/browse` chain was verified end to end up to the open Finder panel:
  the request spawns `folder_dialog.py`, which spawns `osascript` with the
  folder prompt. The panel's own click-through was not automated.

Not executed on macOS: Intel (x86_64) Macs, since the bundled binaries are
arm64-only; the Gatekeeper first-open flow for a quarantined download; and a
real click inside the Finder folder panel.

## Continuous integration (GitHub Actions, `.github/workflows/ci.yml`)

- Linux (ubuntu-latest, Python 3.11 and 3.13, system FFmpeg): ruff, the 79 unit
  tests, the bundle.json consistency check and the four CPU end-to-end suites.
- Windows (windows-latest, Python 3.13): `fetch_binaries.py` restores the exact
  embedded Python 3.13.15 and FFmpeg 9.0.1 (every file matches bundle.json), then
  the 79 unit tests run against the packaged FFmpeg — **79/79 pass**. This was the
  first run of the suite on Windows; it exposed one POSIX-only assumption in
  `test_portable` (reading a byte while a mandatory Windows lock is held), fixed
  in the test. The Windows Job Object CPU cap, the native launcher and the Setup
  are still not exercised by CI.
- macOS (macos-latest, Apple Silicon, Python 3.13): the packaged arm64 FFmpeg,
  the 79 unit tests, and `e2e_macos.py` (VideoToolbox) as a non-blocking step,
  which has passed on hosted runners so far.

CI found one real defect in the rendering engine. `e2e_playlist.py` failed on
Linux with "Tayyor: 0/2" and eight issues; with the issues list added to the
assertion, the cause was `clip_a.mp4: Invalid duration for option ss: 3.1e-05`.
Beat-mode clip offsets are random floats, and any value below 1e-4 s reached
ffmpeg in Python's exponent notation, which its time parser rejects; after two
failed attempts the healthy clip was excluded as unreadable, and with the other
clip deliberately damaged no ordinary source remained. Reproduced locally in 2
of 16 runs with one segment worker (the 4-core runner's budget). Fixed by
passing `-ss` as a fixed-point string; `SourceOffsetTests` renders such offsets
with the real encoder. The suite is now 80 tests.

## Commands

From app: `python3 -m unittest discover -s tests -v`
From bundle root: `python3 developer/e2e_per_video.py`
On macOS, from bundle root: `python3 developer/e2e_macos.py`
After changing packaged files: `python3 developer/build_manifest.py`
All of the above through the task runner: `make test`, `make e2e`, `make check`,
`make manifest`, `make ci` (or `python3 developer/tasks.py <task>`).

The existing automated suite includes real media renders plus simulations.
Its 100-job recovery scenario and CPU/GPU lane tests use controlled simulations;
these are not 100 real encoded videos or measured GPU utilization.

## Packaging and limits

The full offline portable ZIP includes Python/FFmpeg, application sources,
SHA-256 file manifest and checksum. Build validates AMD64 PE headers and ZIP
CRCs, and excludes personal data and caches. No new native launcher or Setup
EXE is built. Native launcher metadata remains 1.5.0; it starts app/UI 1.8.0.
The optional installer build sources are retained for developers.

Native Windows launch, live browser interaction, Windows Job Object controls
and real GPU/driver compatibility were not executed in this Linux environment.
The new editor has static verification, not an automated browser interaction test.
Existing completed videos are unchanged by upgrading. Unrecoverable source or
storage failures continue to be reported without falsely marking success.
