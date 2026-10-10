"""Free-field rotor simulation, exported in the KWave export format.

Usage:
    python Generation/Simple/simulate.py <experiment> [--num_examples 2000] [--angle_step 5]
                                         [--space_step 20 5 5] [--export_dir export_simple]

Reads /experiments/<experiment>/experiment.yml (the same file KWave uses) and writes
/experiments/<experiment>/<export_dir>/ in exporter.py's layout: exported.pkl,
compiled_values/NNNNN.pkl, stats_*.png and the debug image. Candidates, balanced selection
(azimuth/elevation first, positions second) and labels come from exporter.export, so
examples, labels and mic positions match a KWave export of the same experiment; only the
mic signals come from the analytic rotor (rotor.py) instead of the solver outputs.

Not simulated: the medium (homogeneous, c and density from source.noise or air defaults -
sspeed_seed/dens_seed are ignored), reflections, pressure_noise bumps, and KWave's grid.
Source amplitude is physical (Pa); it is not calibrated to KWave's source.p scaling.
Each source needs /experiments/input_mesh/<type>/meta.json for its center, like the exporter.

Rotor parameters default to CircularSignal/main.py (3500 rpm, blades from the type path
<profile>/<dt>/<n_blades>/<cell>) and may be overridden per source:
    rotor: {rpm: 3500, n_blades: 2, start_angle_deg: 90, center: [x, y, z]}  # center in cells
Effective speed is rpm * source.speed, like KWave's mesh playback.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np
from tqdm import tqdm

REPO = Path(__file__).resolve().parents[2]
for path in (REPO, REPO/'Generation'/'KWave'/'src'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from Generation.noise import BladeConfig, BladeNoise
from Generation.Simple.rotor import Rotor, BroadbandForce, rotor_pressure
from experiment_effects import source_options
import exporter

# Mic positions in meters, array frame (as in exporter.py)
MICS = np.array([
    [-0.1,  0.00, 0.00],
    [-0.1,  -0.1, 0.00],
    [ 0.00, -0.1, 0.00],
    [ 0.00, 0.00, 0.00],
    [ 0.10, 0.00, 0.00],
    [ 0.00, 0.10, 0.00],
    [ 0.10, 0.10, 0.00],
])
SENSORS_DIRECTION = np.array([[0, -1, 0]])

DEFAULT_RPM = 3500.0          # CircularSignal/main.py
DEFAULT_BLADE_VOLUME_M3 = 1e-5


def output_times(exp_descr, duration=None):
    """Sample times of the KWave outputs: every int(1/(sampling*dt)) solver steps."""
    duration = float(exp_descr['time'] if duration is None else duration)
    dt = exp_descr.get('mesh', {}).get('dt')
    if dt is None:
        fs = float(exp_descr['sampling'])
        return np.arange(int(duration*fs))/fs, fs
    dt = float(dt)
    stride = int(1/float(exp_descr['sampling'])/dt)
    fs = 1/(stride*dt)
    return np.arange(int(duration/dt)//stride)/fs, fs


def source_rotor(source, exp_descr, mesh_meta):
    rotor_cfg = dict(source.get('rotor', {}))
    unknown = set(rotor_cfg) - {'rpm', 'n_blades', 'start_angle_deg', 'center'}
    if unknown:
        raise ValueError(f'Unknown rotor settings: {sorted(unknown)}')
    n_blades = rotor_cfg.get('n_blades')
    if n_blades is None:
        try:
            n_blades = int(str(source['type']).split('/')[-2])
        except (IndexError, ValueError):
            raise ValueError(f"Set rotor.n_blades for source type {source['type']!r}")
    noise = source.get('noise', {})
    step = np.array([float(exp_descr['mesh'][f'd{c}']) for c in 'xyz'])
    center = rotor_cfg.get('center') or [source[c] + mesh_meta[f'n{c}']/2 for c in 'xyz']
    return Rotor(np.asarray(center, dtype=np.float64)*step,
                 rpm=float(rotor_cfg.get('rpm', DEFAULT_RPM))*float(source.get('speed', 1.0)),
                 n_blades=n_blades,
                 span=float(noise.get('span', BladeConfig.span)),
                 n_span=int(noise.get('n_span', BladeConfig.n_span)),
                 sound_speed=float(noise.get('sound_speed', BladeConfig.sound_speed)),
                 density=float(noise.get('density', BladeConfig.density)),
                 start_angle_deg=float(rotor_cfg.get('start_angle_deg', 90.0)))


def blade_models(source, n_blades, fs_out):
    """One BladeNoise per blade, seeded like kwave_noise.MeshNoise; band limited for fs_out."""
    cfg = dict(source.get('noise', {}))
    identity = json.dumps([source.get(k) for k in ('type', 'x', 'y', 'z')])
    seed = cfg.pop('seed', int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], 'little'))
    # Leave headroom for the Doppler shift (up to 1/(1-M)) below the output Nyquist frequency
    cfg['f_max'] = min(float(cfg.get('f_max', BladeConfig.f_max)),
                       .45*float(cfg.get('sample_rate', BladeConfig.sample_rate)), .4*fs_out)
    return [BladeNoise(BladeConfig(**cfg, seed=int(np.random.SeedSequence([seed, blade]).generate_state(1, dtype=np.uint64)[0])))
            for blade in range(n_blades)]


def simulate_observers(exp_descr, observers, duration=None, block=256, progress=True):
    """Pressure [Pa] at observers (R, 3) in meters for every output time: (R, n_steps)."""
    t, fs = output_times(exp_descr, duration)
    total = np.zeros((len(observers), len(t)))
    for source in exp_descr['sources']:
        source = source_options(source, exp_descr.get('source_mode'))
        mode = source.get('mode', 'both')
        meta = json.load(open(os.path.join(exporter.EXPERIMENTS_ROOT, 'input_mesh', source['type'], 'meta.json')))
        rotor = source_rotor(source, exp_descr, meta)
        force = None
        if mode != 'loading':
            force = BroadbandForce(blade_models(source, rotor.n_blades, fs), float(source.get('amplitude', 1.0)),
                                   t[-1] + 1/fs if len(t) else 0.0)
        thickness = dict(source.get('thickness', {}))
        volume = 0.0
        if mode != 'amiet' and thickness.get('enabled', True):
            volume = float(thickness.get('volume_per_blade_m3', DEFAULT_BLADE_VOLUME_M3))/rotor.n_span
        blocks = range(0, len(observers), block)
        for lo in (tqdm(blocks, desc='Propagating') if progress else blocks):
            loading, thick = rotor_pressure(rotor, observers[lo:lo+block], t, force=force, volume_per_element=volume,
                                            thickness_f_max=float(thickness.get('f_max', 6000.)), fs=fs)
            total[lo:lo+block] += loading + thick
    return total


def simple_signal_source(duration=None):
    """signal_source for exporter.export: the rotor's sound at every exported mic."""
    def signals(result, exp_descr):
        keys = [(position, rotation) for position in result for rotation in result[position]]
        step = np.array([float(exp_descr['mesh'][f'd{c}']) for c in 'xyz'])
        # Grid-rounded mic positions, exactly where KWave records them
        mics = np.array([result[p][r]['mic_positions'] for p, r in keys], dtype=np.float64)*step
        started = time.time()
        pressure = simulate_observers(exp_descr, mics.reshape(-1, 3), duration)
        print(f"Simulated {len(keys)} examples x {mics.shape[1]} mics, {pressure.shape[1]} samples "
              f"in {time.time()-started:.0f} s")
        pressure = pressure.reshape(len(keys), mics.shape[1], -1)
        return {key: pressure[i] for i, key in enumerate(keys)}
    return signals


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('experiment')
    parser.add_argument('--num_examples', type=int, default=2000, help="0 exports every valid example")
    parser.add_argument('--angle_step', type=float, default=5)
    parser.add_argument('--space_step', type=int, nargs=3, default=[20, 5, 5], help="Grid points, x y z")
    parser.add_argument('--export_dir', default='export_simple')
    parser.add_argument('--debug_file', default='debug_img.png', help="Needs OpenCV; '' to skip")
    parser.add_argument('--duration', type=float, help="Seconds; default: experiment time")
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--experiments_root', default=exporter.EXPERIMENTS_ROOT)
    args = parser.parse_args()
    exporter.EXPERIMENTS_ROOT = args.experiments_root
    started = time.time()
    exporter.export(args.experiment, MICS, SENSORS_DIRECTION, args.angle_step, args.space_step,
                    args.debug_file or None, num_examples=args.num_examples or None, seed=args.seed,
                    export_dir=args.export_dir, signal_source=simple_signal_source(args.duration))
    print(f"Done in {time.time()-started:.0f} s")


if __name__ == '__main__':
    main()
