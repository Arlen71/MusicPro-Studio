"""Frame-preserving edit accents, confined to ordinary-to-ordinary boundaries.

No overlap/xfade: the music duration and the licensing timeline never move.
Only strong music anchors qualify. Mixes use fixed, complete effect cycles.
"""
from __future__ import annotations
EFFECTS = ('zoom', 'shake', 'vibration', 'whip', 'rgb', 'blur')
MOTION_EFFECTS = EFFECTS[:4]
PRESETS = ('off', 'edit', 'all', *EFFECTS)
STRENGTHS = {'soft': .65, 'balanced': 1.0, 'bold': 1.4}


def assign_effects(segments, preset, seed, strong_frames=(), fps=30, minimum_gap=2):
    for segment in segments:
        segment.pop('fx_in', None)
        segment.pop('fx_out', None)
    if preset == 'off':
        return
    anchors = set(strong_frames)
    previous_time = -10**12; previous_boundary = -2; count = 0
    cycle = EFFECTS if preset == 'all' else MOTION_EFFECTS if preset == 'edit' else (preset,)
    for index, (left, right) in enumerate(zip(segments, segments[1:])):
        if left['kind'] != 'clip' or right['kind'] != 'clip':
            continue
        if min(left['frames'], right['frames']) < 4:
            continue
        # Exact output-frame match only; never move an effect to an unrelated cut.
        if right['start'] not in anchors or right['start']-previous_time < minimum_gap*fps:
            continue
        if index == previous_boundary+1: continue  # leave a clean cut between hits
        effect = cycle[count % len(cycle)]
        left['fx_out'] = effect
        right['fx_in'] = effect
        previous_time = right['start']; previous_boundary = index; count += 1


def effect_filters(segment, fps, width, height, strength='balanced'):
    # Defense in depth: even a hand-edited plan cannot put FX on a license.
    if segment['kind'] != 'clip' or segment['frames'] < 4:
        return []
    gain = STRENGTHS[strength]
    frames = segment['frames']
    span = max(1, min(round(fps * .16 * gain), (frames - 1) // 3))
    filters = []
    motion = []
    for side, effect in (('in', segment.get('fx_in')), ('out', segment.get('fx_out'))):
        if not effect:
            continue
        start = 0 if side == 'in' else frames - 1 - span
        end = start + span
        window = f'between(n,{start},{end})'
        if effect == 'rgb':
            pixels = max(2, round(width * .007 * gain))
            filters.append(f"rgbashift=rh={pixels}:bh={-pixels}:edge=smear:enable='{window}'")
        elif effect == 'blur':
            # Two levels soften the entrance/exit without changing frame counts.
            filters.append(f"gblur=sigma={3.5*gain:.2f}:steps=2:enable='{window}'")
            inner = f'between(n,0,{span//2})' if side == 'in' else f'between(n,{frames-1-span//2},{frames-1})'
            filters.append(f"gblur=sigma={6*gain:.2f}:steps=2:enable='{inner}'")
        elif effect in ('zoom', 'shake', 'vibration', 'whip'):
            pulse = f'max(0,1-on/{span})' if side == 'in' else f'max(0,(on-{start})/{span})'
            motion.append((effect, pulse))
    if motion:
        amplitudes = {'zoom': .075, 'shake': .04, 'vibration': .025, 'whip': .10}
        zoom = '+'.join(f'{amplitudes[effect]*gain:.5f}*({pulse})' for effect,pulse in motion)
        shake = '+'.join(pulse for effect,pulse in motion if effect == 'shake')
        vibration = '+'.join(pulse for effect,pulse in motion if effect == 'vibration')
        whip = '+'.join(('1' if 'on-' in pulse else '-1')+'*('+pulse+')' for effect,pulse in motion if effect == 'whip')
        x = 'iw/2-iw/zoom/2'
        y = 'ih/2-ih/zoom/2'
        if shake:
            x += f'+(iw-iw/zoom)*.42*sin(on*2.4)*({shake})'
            y += f'+(ih-ih/zoom)*.35*cos(on*1.8)*({shake})'
        if vibration:
            x += f'+(iw-iw/zoom)*.40*sin(on*2.9)*({vibration})'
            y += f'+(ih-ih/zoom)*.40*sin(on*2.6)*({vibration})'
        if whip:
            x += f'+(iw-iw/zoom)*.45*({whip})'
        filters.insert(0, f"zoompan=z='1+{zoom}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps}")
    return filters
