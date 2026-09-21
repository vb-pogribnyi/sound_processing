"""Amiet-shaped excitation, not an absolute far-field-to-source inversion.

The gust model includes a trailing-edge correction, not boundary-layer
trailing-edge self-noise. k-Wave supplies propagation and moving geometry.
"""
from functools import lru_cache
import hashlib
import json

import numpy as np
from .airfoil_noise import (
    AmT, make_psd_evaluator, sweep_psd, target_psd_on_fft_grid, synthesize_block,
)


@lru_cache(maxsize=8)
def _noise_loop(config_json, solver_fs, seed):
    cfg = json.loads(config_json)
    p = dict(chord=0.035, span=0.1, wind_speed=25.0,
             turbulence_intensity=0.025, length_scale=0.007,
             speed_of_sound=343.0, air_density=1.225,
             turbulence_model='K', f_min=50.0, f_max=20000.0,
             loop_duration=1.0, n_freqs=40, grid_nx=20, grid_ny=21)
    unknown = set(cfg) - set(p)
    if unknown:
        raise ValueError(f'Unknown amiet options: {sorted(unknown)}')
    p.update(cfg)
    for key, value in p.items():
        if key != 'turbulence_model' and (not np.isfinite(value) or value <= 0):
            raise ValueError(f'amiet.{key} must be finite and positive')
    for key in ('n_freqs', 'grid_nx', 'grid_ny'):
        if int(p[key]) != p[key] or p[key] < 2:
            raise ValueError(f'amiet.{key} must be an integer >= 2')
    if p['turbulence_model'] not in ('K', 'L'):
        raise ValueError('amiet.turbulence_model must be K or L')
    if p['wind_speed'] >= p['speed_of_sound']:
        raise ValueError('Amiet requires subsonic wind_speed')
    # Oversample the noise band, not the potentially MHz solver clock.
    fs = min(solver_fs, 8 * p['f_max'])
    f_max = min(p['f_max'], fs / 2)
    if not p['f_min'] < f_max:
        raise ValueError('Amiet frequency band is empty at this sample rate')
    n = max(4, int(np.ceil(p['loop_duration'] * fs)))
    setup = AmT.TestSetup(
        c0=p['speed_of_sound'], rho0=p['air_density'], p_ref=20e-6,
        Ux=p['wind_speed'], turb_intensity=p['turbulence_intensity'],
        length_scale=p['length_scale'], z_sl=-1.2)
    geom = AmT.AirfoilGeom(b=p['chord']/2, d=p['span']/2,
                          Nx=int(p['grid_nx']), Ny=int(p['grid_ny']))
    # Fixed broadside reference. RMS normalization discards absolute SPL,
    # but the spectral shape still depends on this observer choice.
    obs = np.array([[0.0], [0.0], [-max(1.2, 10*p['span'], 10*p['chord'])]])
    evaluate = make_psd_evaluator(setup, geom, obs, turb_model=p['turbulence_model'])
    freqs, psd = sweep_psd(evaluate, p['f_min'], f_max,
                           int(p['n_freqs']), progress=False)
    if not np.all(np.isfinite(psd)) or np.any(psd < 0) or not np.any(psd > 0):
        raise ValueError('Amiet produced an invalid or silent spectrum')
    grid, target = target_psd_on_fft_grid(
        freqs, np.maximum(psd, np.finfo(float).tiny), n, fs, p['f_min'], f_max)
    # The shared interpolator clamps above f_max; explicitly band-limit here.
    target[grid > f_max] = 0
    signal = synthesize_block(target, grid, n, fs, p['f_min'], seed=seed)
    rms = np.sqrt(np.mean(signal**2))
    if not np.isfinite(rms) or rms == 0:
        raise ValueError('Amiet noise has no energy in the requested FFT bins')
    signal /= rms
    signal.setflags(write=False)
    return signal, fs


def sample_source_noise(source_cfg, dt, time_start, count):
    """Sample a deterministic periodic signal on the absolute solver clock.

    amiet.wind_speed is effective blade-relative flow in m/s, independent of
    the mesh playback speed. phase is in seconds; legacy freq is unused.
    """
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError('Mesh dt must be finite and positive')
    cfg = dict(source_cfg.get('amiet', {}))
    identity = json.dumps([source_cfg.get(k) for k in ('type', 'x', 'y', 'z')])
    default_seed = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], 'little')
    seed = cfg.pop('seed', default_seed)
    if not isinstance(seed, int) or seed < 0:
        raise ValueError('amiet.seed must be a nonnegative integer')
    phase = float(source_cfg.get('phase', 0.0))
    if not np.isfinite(phase):
        raise ValueError('Source phase must be finite')
    loop, fs = _noise_loop(json.dumps(cfg, sort_keys=True), 1/dt, seed)
    pos = ((time_start + np.arange(count, dtype=np.float64))*dt + phase)*fs
    pos %= loop.size
    idx = np.floor(pos).astype(np.int64)
    fraction = pos - idx
    return loop[idx]*(1-fraction) + loop[(idx+1) % loop.size]*fraction
