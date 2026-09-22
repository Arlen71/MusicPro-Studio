"""Cross-platform task runner for MusicPro Studio. No dependencies.

    python3 developer/tasks.py <task> [arguments passed through]

The Makefile at the bundle root delegates here, so Unix developers can type
`make test` while Windows developers run the same tasks with `py`.
"""
from __future__ import annotations
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
DEVELOPER = ROOT / 'developer'
PY = sys.executable


def run(command, cwd=ROOT) -> int:
    print('$', ' '.join(str(c) for c in command), flush=True)
    return subprocess.call([str(c) for c in command], cwd=cwd)


def task_test(extra):
    """Unit tests: python -m unittest discover -s app/tests."""
    return run([PY, '-m', 'unittest', 'discover', '-s', 'tests', *extra], cwd=APP)


def task_e2e(extra):
    """Every developer/e2e_*.py in turn; macOS-only scripts are skipped elsewhere."""
    status = 0
    for script in sorted(DEVELOPER.glob('e2e_*.py')):
        if script.name == 'e2e_macos.py' and sys.platform != 'darwin':
            print(f'-- {script.name}: skipped, macOS only', flush=True)
            continue
        code = run([PY, script, *extra])
        print(f'-- {script.name}: {"PASS" if code == 0 else f"FAIL ({code})"}', flush=True)
        status = status or code
    return status


def task_check(extra):
    """On-device package diagnostics, the same report TEKSHIRISH writes."""
    code = ("import sys; sys.path.insert(0, 'app'); "
            "from portable_check import check; print(check())")
    return run([PY, '-X', 'utf8', '-B', '-c', code, *extra])


def task_manifest(extra):
    """Rewrite bundle.json, or report drift with --check."""
    return run([PY, DEVELOPER / 'build_manifest.py', *extra])


def task_lint(extra):
    """ruff check with the configuration in pyproject.toml."""
    if subprocess.call([PY, '-m', 'ruff', '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
        print('ruff is not installed. Install it once with:\n'
              f'  {PY} -m pip install ruff', file=sys.stderr)
        return 2
    return run([PY, '-m', 'ruff', 'check', '.', *extra])


def task_fetch(extra):
    """Download and verify the third-party binaries listed in THIRD_PARTY.md."""
    return run([PY, DEVELOPER / 'fetch_binaries.py', *extra])


def task_run(extra):
    """Start the application in the foreground, like the native launchers do."""
    return run([PY, '-X', 'utf8', '-B', APP / 'bootstrap.py', *extra])


def task_clean(extra):
    """Remove caches and editor droppings; user data and downloads are kept."""
    removed = 0
    for pattern in ('**/__pycache__', '**/.ruff_cache', '**/.pytest_cache'):
        for path in ROOT.glob(pattern):
            if 'runtime' in path.parts or '.git' in path.parts:
                continue
            shutil.rmtree(path, ignore_errors=True); removed += 1
    for pattern in ('**/.DS_Store', '**/*.pyc', '**/Thumbs.db'):
        for path in ROOT.glob(pattern):
            if '.git' in path.parts:
                continue
            path.unlink(missing_ok=True); removed += 1
    print(f'clean: {removed} removed')
    return 0


def task_ci(extra):
    """What a continuous-integration job runs: lint, unit tests, manifest drift."""
    for name in ('lint', 'test', 'manifest'):
        code = TASKS[name](['--check'] if name == 'manifest' else [])
        if code:
            print(f'ci: {name} failed ({code})', file=sys.stderr)
            return code
    print('ci: all passed')
    return 0


TASKS = {
    'test': task_test, 'e2e': task_e2e, 'check': task_check, 'manifest': task_manifest,
    'lint': task_lint, 'fetch': task_fetch, 'run': task_run, 'clean': task_clean, 'ci': task_ci,
}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='tasks:\n' + '\n'.join(f'  {name:9} {fn.__doc__}' for name, fn in TASKS.items()))
    parser.add_argument('task', choices=TASKS)
    parser.add_argument('extra', nargs=argparse.REMAINDER, help='passed through to the task')
    args = parser.parse_args()
    os.chdir(ROOT)
    raise SystemExit(TASKS[args.task](args.extra))


if __name__ == '__main__':
    main()
