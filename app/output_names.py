"""Windows-safe music names and exclusive, per-job output reservations."""
from __future__ import annotations
import json
import re
from pathlib import Path
from failures import StorageError, UserError

MARKER = '.musicpro_output.json'


def music_title(plan):
    asset = plan['tracks'][0]['asset'] if plan.get('tracks') else plan['music']
    return Path(asset['name']).stem


def safe_title(title):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip().rstrip('. ')
    # Leave room for suffixes and worker filenames, including UTF-16 characters.
    value = value.encode('utf-16-le')[:160].decode('utf-16-le', errors='ignore').rstrip('. ')
    value = value or 'Musiqa'
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])', value.split('.')[0], re.I):
        value = '_' + value
    return value


def video_filename(plan):
    # Legacy/direct render callers remain readable; every new batch sets this.
    value = plan.get('video_filename', 'video.mp4')
    if not isinstance(value, str) or not value.lower().endswith('.mp4') or \
            any(c in value for c in '<>:"/\\|?*') or any(ord(c)<32 for c in value) or value.endswith(' '):
        raise UserError('Natija video nomi noto‘g‘ri. Rejani qayta tuzing.')
    return value


def owned(directory, owner):
    try:
        return not directory.is_symlink() and not (directory/MARKER).is_symlink() and \
            json.loads((directory/MARKER).read_text(encoding='utf-8')).get('owner') == owner
    except (OSError, ValueError, AttributeError):
        return False


def prepare_output(job, plan, config, batch):
    """Reserve atomically, without overwriting existing user files or folders.

    A source replacement may change the first song. Move only this job's known
    diagnostics from its previous reservation; preserve any unexpected files.
    """
    root = Path(config['output']).resolve()
    base = safe_title(music_title(plan))
    owner = f'{batch}:{job["id"]}'
    previous = Path(job['dest']) if job.get('dest') else None
    try:
        root.mkdir(parents=True, exist_ok=True)
        if previous and previous.parent == root and job.get('name_base') == base and owned(previous, owner):
            destination = previous
        else:
            occupied = {p.name.casefold() for p in root.iterdir()}
            for index in range(1, 100001):
                name = base if index == 1 else f'{base} ({index})'
                if name.casefold() in occupied:
                    continue
                destination = root/name
                try:
                    destination.mkdir()
                except FileExistsError:
                    occupied.add(name.casefold())
                    continue
                try:
                    (destination/MARKER).write_text(json.dumps({'owner':owner}, ensure_ascii=False), encoding='utf-8')
                except OSError:
                    destination.rmdir()
                    raise
                break
            else:
                raise StorageError('Musiqa nomi uchun bo‘sh natija papkasi topilmadi.')
            if previous and previous.parent == root and owned(previous, owner):
                # Failed decode attempts only leave a diagnostic log. Never
                # remove arbitrary contents, completed videos or old exports.
                children = {p.name for p in previous.iterdir()}
                if children <= {MARKER, 'render_diagnostics.txt'}:
                    log = previous/'render_diagnostics.txt'
                    if log.is_file() and not log.is_symlink():
                        (destination/log.name).write_bytes(log.read_bytes())
                        log.unlink()
                    if not log.exists() and not log.is_symlink():
                        (previous/MARKER).unlink()
                        previous.rmdir()
        plan['video_filename'] = destination.name + '.mp4'
        video_filename(plan)
        job.update(dest=str(destination), name_base=base, output_name=destination.name,
                   video_filename=plan['video_filename'])
    except OSError as e:
        raise StorageError('Natija papkasini tayyorlab bo‘lmadi: '+str(e)) from e
    return destination
