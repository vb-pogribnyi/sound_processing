"""SRP-PHAT and MVDR azimuth/elevation maps for a single example exported by exporter.py.

Usage:
    python beamforming.py <experiment> <example_id> [--out DIR] [--fmin 300] [--fmax 3000]

Example ID is the index of the example in exported.pkl, enumerating positions and their rotations in stored order.
Maps are computed in the array's own (unrotated) frame: the plane of the array is XY, azimuth is measured in that
plane from +X towards +Y, elevation from the plane towards +Z. A planar array cannot tell +elevation from
-elevation, so the mirrored source direction is marked as well.
"""
import os
import json
import pickle
import argparse
import numpy as np
import yaml
from scipy.signal import stft
from scipy.spatial.transform import Rotation
from tqdm import tqdm
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def load_example(experiment, example_id):
    """Returns example's metadata and mic signals of shape (n_mics, n_samples)."""
    exp_path = os.path.join('/experiments', experiment)
    exp_descr = yaml.load(open(os.path.join(exp_path, 'experiment.yml')), Loader=yaml.FullLoader)
    export_path = os.path.join(exp_path, 'export')
    result = pickle.load(open(os.path.join(export_path, 'exported.pkl'), 'rb'))
    examples = [(position, rotation) for position in result for rotation in result[position]]
    assert 0 <= example_id < len(examples), f"Example ID must be in [0, {len(examples)})"
    position, rotation = examples[example_id]
    snapshot = result[position][rotation]

    # exported.pkl keeps indices of each mic's value in the simulation outputs - read them directly (fast, mmap)
    out_dir = os.path.join(exp_path, 'outputs')
    out_files = sorted([f.path for f in os.scandir(out_dir)]) if os.path.exists(out_dir) else []
    if len(out_files) > 0:
        idx = np.array([mic_value[0] for mic_value in snapshot['mic_values']])
        signals = np.stack([np.load(f, mmap_mode='r')[idx[:, 0], idx[:, 1], idx[:, 2]]
                            for f in tqdm(out_files, desc='Reading outputs')], axis=1)
    else:
        # Outputs removed - fall back to compiled values (slow: every file holds all exported examples)
        step_files = sorted([f.path for f in os.scandir(os.path.join(export_path, 'compiled_values'))])
        signals = np.stack([np.array(pickle.load(open(f, 'rb'))[position][rotation]['mic_values'], dtype=float)
                            for f in tqdm(step_files, desc='Reading compiled values')], axis=1)
    return exp_descr, position, rotation, snapshot, signals.astype(np.float64)


def example_geometry(exp_descr, position, rotation, snapshot):
    """Mic positions (meters) and unit source directions, both in the array's own frame."""
    # exporter.py rotates the array about Z first, then about X; rotation key is (angle_z, angle_x)
    array_rotation = Rotation.from_euler('x', rotation[1], degrees=True) * Rotation.from_euler('z', rotation[0], degrees=True)
    mesh_step = np.array([exp_descr['mesh'][f'd{c}'] for c in 'xyz'])
    # Grid points the signals were actually recorded at
    mics_world = np.array(snapshot['mic_positions'], dtype=float) * mesh_step
    mics_local = array_rotation.inv().apply(mics_world - mics_world.mean(axis=0))
    # Source direction - same as in exporter.py
    source_dirs = []
    for source in exp_descr['sources']:
        meta = json.load(open(os.path.join('/experiments/input_mesh', source['type'], 'meta.json')))
        source_dirs.append([(source[c] + meta[f'n{c}'] / 2 - position[i]) * meta[f'd{c}'] for i, c in enumerate('xyz')])
    source_dirs = array_rotation.inv().apply(np.array(source_dirs))
    return mics_local, source_dirs / np.linalg.norm(source_dirs, axis=1, keepdims=True)


def to_az_el(directions):
    return (np.degrees(np.arctan2(directions[..., 1], directions[..., 0])),
            np.degrees(np.arcsin(np.clip(directions[..., 2], -1, 1))))


def direction_grid(resolution):
    azimuths = np.arange(-180, 180 + resolution / 2, resolution)
    elevations = np.arange(-90, 90 + resolution / 2, resolution)
    az, el = np.radians(np.meshgrid(azimuths, elevations))
    return azimuths, elevations, np.stack([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)], axis=-1)


def steering_vectors(mics, directions, freq, c):
    # Plane wave from direction u reaches mic r earlier by r.u/c: x_m(f) = s(f) * exp(j*2*pi*f*r.u/c)
    return np.exp(2j * np.pi * freq * (directions @ mics.T) / c)


def spectra(signals, fs, nfft, fmin, fmax):
    freqs, _, X = stft(signals, fs=fs, nperseg=nfft, noverlap=nfft // 2)  # (mics, freqs, frames)
    band = (freqs >= fmin) & (freqs <= fmax)
    assert np.any(band), "No frequency bins in the requested band"
    return freqs[band], X[:, band]


def srp_phat_map(signals, mics, directions, fs, c, nfft, fmin, fmax):
    """Steered response power with PHAT weighting, summed over frequency bins."""
    freqs, X = spectra(signals, fs, nfft, fmin, fmax)
    X = X / (np.abs(X) + 1e-12)
    power = np.zeros(directions.shape[:-1])
    for f_idx, freq in enumerate(freqs):
        cov = X[:, f_idx] @ X[:, f_idx].conj().T / X.shape[2]
        a = steering_vectors(mics, directions, freq, c)
        power += np.real(np.einsum('...m,mn,...n->...', a.conj(), cov, a))
    return power


def mvdr_map(signals, mics, directions, fs, c, nfft, fmin, fmax, diag_loading):
    """MVDR (Capon) spatial spectrum 1 / (a^H R^-1 a), summed over frequency bins."""
    freqs, X = spectra(signals, fs, nfft, fmin, fmax)
    power = np.zeros(directions.shape[:-1])
    n_mics = X.shape[0]
    for f_idx, freq in enumerate(freqs):
        cov = X[:, f_idx] @ X[:, f_idx].conj().T / X.shape[2]
        cov += diag_loading * np.real(np.trace(cov)) / n_mics * np.eye(n_mics)
        a = steering_vectors(mics, directions, freq, c)
        power += 1 / np.maximum(np.real(np.einsum('...m,mn,...n->...', a.conj(), np.linalg.inv(cov), a)), 1e-30)
    return power


def angular_error(az_el_a, az_el_b):
    a, b = [np.array([np.cos(np.radians(el)) * np.cos(np.radians(az)), np.cos(np.radians(el)) * np.sin(np.radians(az)),
                      np.sin(np.radians(el))]) for az, el in [az_el_a, az_el_b]]
    return np.degrees(np.arccos(np.clip(a @ b, -1, 1)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('experiment')
    parser.add_argument('example_id', type=int)
    parser.add_argument('--out', help="Output directory, default: /experiments/<experiment>/export/beamforming")
    parser.add_argument('--fmin', type=float, default=300, help="Lowest frequency used, Hz")
    parser.add_argument('--fmax', type=float, default=3000, help="Highest frequency used, Hz")
    parser.add_argument('--nfft', type=int, default=512, help="STFT window, samples")
    parser.add_argument('--skip', type=float, default=0.01, help="Seconds skipped at the start (wave not arrived yet)")
    parser.add_argument('--c', type=float, default=343.0, help="Speed of sound, m/s")
    parser.add_argument('--resolution', type=float, default=2.0, help="Map resolution, degrees")
    parser.add_argument('--diag_loading', type=float, default=1e-3, help="MVDR diagonal loading, relative to mean power")
    args = parser.parse_args()

    exp_descr, position, rotation, snapshot, signals = load_example(args.experiment, args.example_id)
    fs = float(exp_descr['sampling'])
    signals = signals[:, int(args.skip * fs):]
    signals -= signals.mean(axis=1, keepdims=True)
    mics, source_dirs = example_geometry(exp_descr, position, rotation, snapshot)
    azimuths, elevations, directions = direction_grid(args.resolution)
    common = dict(fs=fs, c=args.c, nfft=args.nfft, fmin=args.fmin, fmax=args.fmax)
    maps = {
        'SRP-PHAT': srp_phat_map(signals, mics, directions, **common),
        'MVDR': mvdr_map(signals, mics, directions, diag_loading=args.diag_loading, **common),
    }

    true_az, true_el = to_az_el(source_dirs)
    print(f"Example {args.example_id}: position {tuple(int(v) for v in position)}, rotation (z, x) {rotation}, "
          f"{signals.shape[0]} mics, {signals.shape[1]} samples at {fs:g} Hz")
    for i, (az, el) in enumerate(zip(true_az, true_el)):
        print(f"  Source {i}: azimuth {az:.1f}, elevation {el:.1f} (exporter labels: angle_z "
              f"{snapshot['sources'][i]['angle_z']:.1f}, angle_x {snapshot['sources'][i]['angle_x']:.1f})")

    fig, axes = plt.subplots(1, len(maps), figsize=(7 * len(maps), 4.2))
    for ax, (name, power) in zip(axes, maps.items()):
        power_db = 10 * np.log10(power / power.max())
        peak = np.unravel_index(np.argmax(power), power.shape)
        peak_az, peak_el = azimuths[peak[1]], elevations[peak[0]]
        # Planar array: the mirrored direction is equally valid
        error = min(min(angular_error((peak_az, peak_el), (az, el)), angular_error((peak_az, peak_el), (az, -el)))
                    for az, el in zip(true_az, true_el))
        print(f"  {name}: peak azimuth {peak_az:.1f}, elevation {peak_el:.1f}, error {error:.1f} deg (up to mirror)")

        im = ax.imshow(power_db, origin='lower', aspect='auto', cmap='viridis', vmin=max(power_db.min(), -20), vmax=0,
                       extent=[azimuths[0] - args.resolution / 2, azimuths[-1] + args.resolution / 2,
                               elevations[0] - args.resolution / 2, elevations[-1] + args.resolution / 2])
        fig.colorbar(im, ax=ax, label='Power, dB (re. max)')
        ax.scatter(true_az, true_el, marker='X', s=140, c='#e8432e', edgecolors='white', linewidths=1.5, label='True source')
        ax.scatter(true_az, -true_el, marker='X', s=110, facecolors='none', edgecolors='#e8432e', linewidths=1.5,
                   label='Mirror (planar ambiguity)')
        ax.scatter([peak_az], [peak_el], marker='o', s=90, facecolors='none', edgecolors='white', linewidths=2,
                   label='Map peak')
        ax.set_title(f'{name}, error {error:.1f}°')
        ax.set_xlabel('Azimuth, degrees')
        ax.set_ylabel('Elevation, degrees')
        ax.set_xlim(-180, 180)
        ax.set_ylim(-90, 90)
    axes[0].legend(loc='lower left', fontsize=8, framealpha=0.8)
    fig.suptitle(f'Experiment {args.experiment}, example {args.example_id}, {args.fmin:g}-{args.fmax:g} Hz')
    fig.tight_layout()

    out_dir = args.out or os.path.join('/experiments', args.experiment, 'export', 'beamforming')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f'example_{str(args.example_id).zfill(5)}.png')
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"Saved {out_path}")


if __name__ == '__main__':
    main()
