"""Sample-accurate playlist metadata and the exact requested TXT format.

No FFmpeg or UI dependencies: the renderer and the browser use the same
sample timeline, and a failed source replacement regenerates that timeline.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from failures import UserError

SAMPLE_RATE = 48000
ORDER_KEYS = ('playlist_first', 'playlist_second', 'playlist_third')
REPORT_NAME = 'Playlist.txt'
HEADER = 'Music in the playlist/video:'
TAGS = ('music, music video, new music, hit songs, pop music, official video, trending music, '
        'top hits, best songs, viral music, edm, hip hop, rap, acoustic, live performance, '
        'music channel, new release, bass boosted, remix, chill vibes, party music, dance track, '
        'instrumental, lofi, beats, song of the day, top charts, 2026 hits, music playlist, '
        'daily music, good vibes, fresh tunes, audio, sound, popular songs, club mix, trap, '
        'indie music, rock, electronic, lo-fi beats, relax music, study music, chill,  ')


def audio_assets(plan):
    return [t['asset'] for t in plan['tracks']] if plan.get('tracks') else [plan['music']]


def order_slots(config, job_id=None):
    if config.get('music_mode', 'single') != 'playlist':
        return {}
    if 'playlist_per_video' in config:
        entry=config['playlist_per_video'].get(str(job_id), {})
        if not entry.get('enabled', False): return {}
        return {i:path for i,path in enumerate(entry.get('tracks', [])[:config.get('playlist_count',5)]) if path}
    if not config.get('playlist_order_enabled', False): return {}
    return {i: config[key] for i, key in enumerate(ORDER_KEYS)
            if i < config.get('playlist_count', 5) and config.get(key)}


def validate_order_config(config):
    enabled = config.get('playlist_order_enabled', False)
    if enabled in (True, 1, 'true', '1', 'on'):
        config['playlist_order_enabled'] = True
    elif enabled in (False, 0, 'false', '0', '', None):
        config['playlist_order_enabled'] = False
    else:
        raise UserError('Playlist tartibi: yoqilgan yoki o‘chirilgan qiymat kerak.')
    for key in ORDER_KEYS:
        value = config.get(key, '')
        if not isinstance(value, str) or len(value) > 4000 or any(ord(c) < 32 for c in value):
            raise UserError('Tanlangan musiqa manzili noto‘g‘ri.')
        config[key] = str(Path(value).expanduser().resolve()) if value else ''
    if 'playlist_per_video' in config:
        mapping=config['playlist_per_video']
        if not isinstance(mapping,dict) or len(mapping)>10000:
            raise UserError('Har video uchun playlist ro‘yxati noto‘g‘ri.')
        normalized={}
        for key,entry in mapping.items():
            if not isinstance(key,str) or not key.isascii() or not key.isdecimal() or not 1<=int(key)<=10000 or str(int(key))!=key:
                raise UserError('Playlist uchun video raqami noto‘g‘ri.')
            if not isinstance(entry,dict) or type(entry.get('enabled',False)) is not bool:
                raise UserError(f'{key}-video uchun tanlash holati noto‘g‘ri.')
            tracks=entry.get('tracks',[])
            if not isinstance(tracks,list) or len(tracks)>1000:
                raise UserError(f'{key}-video uchun ko‘pi bilan 1000 ta musiqa o‘rni mumkin.')
            paths=[]
            for path in tracks:
                if not isinstance(path,str) or len(path)>4000 or any(ord(c)<32 for c in path):
                    raise UserError(f'{key}-video: musiqa manzili noto‘g‘ri.')
                paths.append(str(Path(path).expanduser().resolve()) if path else '')
            while paths and not paths[-1]: paths.pop()
            enabled=entry.get('enabled',False)
            active=paths[:config.get('playlist_count',5)]
            if enabled and int(key)<=config.get('total',10) and config.get('music_mode')=='playlist':
                chosen=[path for path in active if path]
                if len(chosen)!=len(set(chosen)):
                    raise UserError(f'{key}-video: bitta musiqani ikki o‘ringa tanlab bo‘lmaydi.')
                if any(Path(path).parent!=Path(config['music']) for path in chosen):
                    raise UserError(f'{key}-video: musiqalar joriy Musikalar papkasidan tanlansin.')
            normalized[key]=dict(enabled=enabled,tracks=paths)
        config['playlist_per_video']=normalized
    slots = order_slots(config)
    if len(set(slots.values())) != len(slots):
        raise UserError('Bitta playlistda bir musiqani ikki o‘ringa tanlab bo‘lmaydi.')
    for value in slots.values():
        if Path(value).parent != Path(config['music']):
            raise UserError('Tanlangan musiqalar joriy Musikalar papkasidan bo‘lishi kerak. Ro‘yxatni yangilang.')


def select_tracks(pool, count, rng, slots=None, preferred=(), longest=False):
    """Place healthy pinned slots first; shuffle only the unfilled slots."""
    if len(pool) < count:
        raise UserError(f'Playlist uchun {count} ta turli yaroqli musiqa kerak; hozir {len(pool)} ta mavjud. '
                        'Musiqa qo‘shing yoki har playlistdagi musiqa sonini kamaytiring.')
    by_path = {a['path']: a for a in pool}
    selected = [None] * count
    missing = {}
    for i, path in (slots or {}).items():
        if path in by_path:
            selected[i] = by_path[path]
        else:
            missing[str(i)] = path
    used = {a['path'] for a in selected if a}
    if len(preferred) == count:
        for i, track in enumerate(preferred):
            a = by_path.get(track['asset']['path'])
            if selected[i] is None and a and a['path'] not in used:
                selected[i] = a
                used.add(a['path'])
    remaining = [a for a in pool if a['path'] not in used]
    rng.shuffle(remaining)
    if longest:
        remaining.sort(key=lambda a: a['duration'], reverse=True)
    iterator = iter(remaining)
    return [a if a else next(iterator) for a in selected], missing


def title(asset):
    # Names come from source filenames, not inferred artist/title metadata.
    return ''.join(c if ord(c) >= 32 else ' ' for c in Path(asset['name']).stem).strip()


def clock_samples(samples):
    seconds = samples // SAMPLE_RATE
    hours, remaining = divmod(seconds, 3600)
    minutes, seconds = divmod(remaining, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


def compose(assets, analyses):
    """Build an ordered timeline from exact decoded 48 kHz stereo lengths."""
    if not assets or len(assets) != len(analyses):
        raise UserError('Playlist uchun musiqa va tahlil sonlari mos emas.')
    if len({a['path'] for a in assets}) != len(assets):
        raise UserError('Bitta playlist ichida musiqa takrorlanmaydi.')
    tracks = []; cuts = []; strong = []; offset = 0
    for asset, analysis in zip(assets, analyses):
        samples = analysis.get('decoded_samples')
        if type(samples) is not int or samples <= 0 or analysis.get('sample_rate') != SAMPLE_RATE:
            raise UserError('Playlist uchun aniq audio uzunligini qayta tahlil qilish kerak.')
        tracks.append(dict(asset=asset, start_sample=offset, samples=samples))
        for key, target in [('cuts', cuts), ('strong', strong)]:
            target.extend(offset/SAMPLE_RATE+t for t in analysis.get(key, [])
                          if math.isfinite(t) and 0 <= t < samples/SAMPLE_RATE)
        offset += samples
    identity = [(t['asset']['path'], t['asset']['size'], t['asset']['mtime'], t['samples']) for t in tracks]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode('utf-8')).hexdigest()
    music = dict(path='playlist:'+digest, name=f'Playlist · {len(tracks)} ta musiqa',
                 duration=offset/SAMPLE_RATE, samples=offset, sample_rate=SAMPLE_RATE)
    analysis = dict(cuts=sorted(set(cuts)), strong=sorted(set(strong)), method='playlist-energy-v2')
    return music, tracks, analysis


def validate_tracks(plan, config):
    tracks = plan.get('tracks')
    if config.get('music_mode', 'single') != 'playlist' or not isinstance(tracks, list):
        raise UserError('Playlist rejasi musiqa rejimiga mos emas.')
    if len(tracks) != config.get('playlist_count', 5):
        raise UserError('Playlistdagi musiqa soni sozlamaga mos emas.')
    cursor = 0; seen = set()
    try:
        for track in tracks:
            asset = track['asset']; count = track['samples']; start = track['start_sample']
            if type(count) is not int or count <= 0 or type(start) is not int or start != cursor:
                raise ValueError('sample timeline')
            if asset['path'] in seen: raise ValueError('repeated music')
            seen.add(asset['path']); cursor += count
        music = plan['music']
        if music.get('sample_rate') != SAMPLE_RATE or music.get('samples') != cursor or cursor <= 0:
            raise ValueError('total samples')
        if not math.isfinite(music['duration']) or abs(music['duration']-cursor/SAMPLE_RATE) > 1e-9:
            raise ValueError('duration')
        identity = [(t['asset']['path'], t['asset']['size'], t['asset']['mtime'], t['samples']) for t in tracks]
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode('utf-8')).hexdigest()
        if music['path'] != 'playlist:'+digest: raise ValueError('identity')
        fallbacks = plan.get('playlist_order_fallbacks', {})
        if not isinstance(fallbacks, dict): raise ValueError('playlist order fallback')
        job_id=plan.get('playlist_job_id')
        if 'playlist_per_video' in config and (type(job_id) is not int or not 1<=job_id<=config.get('total',10)):
            raise ValueError('playlist job identity')
        for index, requested in order_slots(config,job_id).items():
            if tracks[index]['asset']['path'] != requested and fallbacks.get(str(index)) != requested:
                raise ValueError('selected playlist order')
    except (KeyError, TypeError, ValueError) as e:
        raise UserError('Playlistning musiqa ketma-ketligi buzilgan. Rejani qayta tuzing.') from e


def text_from_plan(plan):
    if not plan.get('tracks'): return ''
    lines = [HEADER]
    lines.extend(f"{clock_samples(t['start_sample'])} {title(t['asset'])}" for t in plan['tracks'])
    return '\n'.join(lines)+'\n\n'+TAGS+'\n'


def write_playlist(plan, destination):
    payload = text_from_plan(plan)
    if not payload: return None
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='playlist_', suffix='.tmp', dir=destination, delete=False) as f:
        temp = Path(f.name)
        f.write(payload.encode('utf-8'))
    try:
        os.replace(temp, destination/REPORT_NAME)
    finally:
        temp.unlink(missing_ok=True)
    return destination/REPORT_NAME
