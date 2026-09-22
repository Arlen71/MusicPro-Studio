"""Entry point for the native Windows launcher, with persistent startup logs."""
from __future__ import annotations
import os
import sys
import traceback
from pathlib import Path
from runtime_support import data_directory, installation_guard, VERSION

ROOT = Path(__file__).resolve().parent


def message(text: str, error: bool = False):
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, 'MusicPro Studio ' + VERSION, 0x10 if error else 0x40)
        return
    if sys.platform == 'darwin':
        # stdout/stderr are already the startup log, so the panel is the only
        # channel the person actually sees when launched from Finder.
        import subprocess
        body = text[:1500].replace('\\', '\\\\').replace('"', '\\"').replace('\r', '').replace('\n', '\\n')
        try:
            subprocess.run(['/usr/bin/osascript', '-e',
                            f'display dialog "{body}" with title "MusicPro Studio {VERSION}" '
                            f'buttons {{"OK"}} default button "OK" '
                            f'with icon {"stop" if error else "note"}'],
                           capture_output=True, timeout=600)
            return
        except (OSError, subprocess.SubprocessError):
            pass
    if sys.stderr:
        print(text, file=sys.stderr)


def run() -> int:
    log_file = None
    try:
        data = data_directory(ROOT)
        data.mkdir(parents=True, exist_ok=True)
        os.environ['MUSICPRO_DATA_DIR'] = str(data)
        guard = installation_guard(ROOT)  # noqa: F841  # keep the mutex handle referenced for the process lifetime
        log_path = data / 'startup.log'
        if log_path.exists() and log_path.stat().st_size > 2_000_000:
            try: log_path.replace(data / 'startup.previous.log')
            except OSError: pass
        log_file = log_path.open('a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stderr = log_file
        print('\nMusicPro Studio', VERSION)
        if os.name != 'nt' and sys.platform != 'darwin' and '--allow-non-windows' not in sys.argv:
            raise RuntimeError('Ushbu paket Windows 10/11 yoki macOS 12+ uchun.')
        required = ['app.py', 'worker.py', 'reports.py', 'web/studio.html',
                    'web/studio.css', 'web/studio.js', 'assets/report_template.xlsx']
        if os.name == 'nt':
            required += ['bin/ffmpeg.exe', 'bin/ffprobe.exe']
        elif sys.platform == 'darwin':
            required += ['bin/ffmpeg', 'bin/ffprobe', 'folder_dialog.py']
        missing = [name for name in required if not (ROOT/name).is_file()]
        if missing:
            raise RuntimeError('Paket to‘liq emas: ' + ', '.join(missing) + '\nZIPni to‘liq oching yoki Setupni qayta ishga tushiring.')
        if '--check' in sys.argv:
            from portable_check import check
            report = check()
            target = data / 'diagnostics.txt'
            target.write_text(report, encoding='utf-8')
            if os.name == 'nt': os.startfile(str(target))
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.run(['/usr/bin/open', str(target)], check=False)
            return 0
        import app
        app.main()
        return 0
    except Exception:
        details = traceback.format_exc()
        if log_file:
            print(details, file=log_file)
        text = 'MusicPro ishga tushmadi.\n\n' + str(sys.exc_info()[1])
        if log_file: text += '\n\nBatafsil: ' + str(log_file.name)
        message(text, True)
        return 1


if __name__ == '__main__':
    raise SystemExit(run())
