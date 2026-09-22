"""Conservative energy accents, separate from ordinary cut candidates.

20 ms stereo RMS windows and a low-pass bass envelope. This detects loud
attacks, not musical key or pitch. Quiet changes and steady loud tones do not
qualify as strong events. The result is deterministic and has no random input.
"""
import array
import math
import statistics
import sys
from failures import Cancelled

HOP_SECONDS = .02


def analyze_pcm(path, stop=None):
    energies = []; bass = []; low = [0., 0.]
    with path.open('rb') as handle:
        while data := handle.read(960):  # 240 samples/channel, stereo, 12000 Hz
            if stop and stop.is_set(): raise Cancelled()
            samples = array.array('h'); samples.frombytes(data[:len(data)//4*4])
            if sys.byteorder != 'little': samples.byteswap()
            if not samples: continue
            power = 0.; low_power = 0.
            for i, sample in enumerate(samples):
                channel = i % 2
                low[channel] += .12 * (sample-low[channel])
                power += sample*sample; low_power += low[channel]*low[channel]
            energies.append(math.sqrt(power/len(samples)))
            bass.append(math.sqrt(low_power/len(samples)))
    return accents_from_envelopes(energies, bass)


def accents_from_envelopes(energies, bass):
    if not energies or max(energies) < 250:
        return {'cuts': [], 'strong': [], 'method': 'energy-v2'}
    ordered = sorted(energies)
    q95 = ordered[min(len(ordered)-1, int(len(ordered)*.95))]
    loud_floor = max(400, max(energies)*.45, q95*.65)
    cuts = []; strong = []
    for i in range(5, len(energies)-3):
        energy = energies[i]
        if energy < 200: continue
        base = max(80, statistics.median(energies[max(0,i-30):i-2]))
        previous = max(80, statistics.median(energies[i-3:i]))
        bass_base = max(60, statistics.median(bass[max(0,i-30):i-2]))
        rise = energy/base; attack = energy/previous; bass_rise = bass[i]/bass_base
        if rise < 1.18 or attack < 1.08: continue
        # Anchor on the rising edge. Waiting for a plateau maximum can miss
        # percussive attacks whose carrier period does not divide the RMS hop.
        onset = i
        while onset > max(0,i-3) and energies[onset-1] >= energy*.8: onset -= 1
        time = round(onset*HOP_SECONDS, 3)
        if not cuts or time-cuts[-1] >= .24: cuts.append(time)
        is_strong = energy >= loud_floor and ((rise >= 1.65 and attack >= 1.2) or (bass_rise >= 2.0 and rise >= 1.18 and attack >= 1.12))
        if is_strong and (not strong or time-strong[-1] >= .9): strong.append(time)
    return {'cuts': cuts, 'strong': strong, 'method': 'energy-v2'}
