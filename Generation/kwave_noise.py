"""Map blade-fixed stochastic pressure jumps onto packed differential meshes.

No k-Wave imports. MeshReader calls MeshNoise on intact endpoint frames before
interpolating their pressures in time. Packed coordinate labels are never
interpolated. See Noise.md for the source gain and coordinate conventions.
"""
from functools import lru_cache
import hashlib
import json

import numpy as np

from .noise import BladeConfig, BladeNoise


def decode_coordinates(labels):
    """Return blade, span, chord indices. 100052 -> (2, 5, 1).

    l=(label//10)%100, t=(label//1000)%100, y=(label//100000)%100.
    Per the mesh contract, y is chordwise; t does not select the pressure.
    Index i means i/10. Accept 10 at the exact endpoint, which SourceDrawer's
    int(coordinate*10) can emit, in addition to the usual bins 0 through 9.
    """
    labels = np.asarray(labels)
    if not np.all(np.isfinite(labels)) or np.any(labels != np.rint(labels)):
        raise ValueError('Active mesh labels must be finite packed integers; do not interpolate mesh.imag')
    if np.any(labels < 0) or np.any(labels > 1010109):
        raise ValueError('Packed blade coordinates are outside the supported range')
    code = labels.astype(np.int64)
    blade = code % 10
    span = (code//10) % 100
    transverse = (code//1000) % 100
    chord = code//100000
    if np.any(span > 10) or np.any(transverse > 10) or np.any(chord > 10):
        raise ValueError('Mesh coordinates must be in bins 0..9 (or 10 at the endpoint)')
    return blade, span, chord


@lru_cache(maxsize=16)
def _blade_model(config_json, seed):
    cfg = json.loads(config_json)
    cfg['seed'] = seed
    return BladeNoise(BladeConfig(**cfg))


def _coordinate_weights(size):
    # Noise is evaluated at cell centers, while packed bins encode i/10.
    location = np.clip(np.arange(11)/10*size-.5, 0, size-1)
    lo = np.floor(location).astype(int)
    return lo, np.minimum(lo+1, size-1), location-lo


def _pressure_table(model, times):
    """Resample to [11 span bins, 11 chord bins, solver times].

    A local windowed-sinc interpolation avoids the high-frequency attenuation
    of linear interpolation from the acoustic clock to the much faster solver
    clock. Fixed tap selection also preserves chunk/restart reproducibility.
    """
    positions = times*model.config.sample_rate
    center = np.floor(positions).astype(np.int64)
    radius = 8
    taps = center[:, None] + np.arange(-radius+1, radius+1)
    distance = positions[:, None]-taps
    weights = np.sinc(distance)*np.sinc(distance/radius)
    weights /= weights.sum(axis=1, keepdims=True)
    # Constant extension only at the initial boundary; no noise-loop wrapping.
    taps = np.maximum(taps, 0)
    start, stop = int(taps.min()), int(taps.max())+1
    coarse = model.sample(stop-start, start_sample=start)
    sampled = np.zeros(coarse.shape[:2]+(len(times),), dtype=np.float64)
    for tap in range(taps.shape[1]):
        sampled += coarse[..., taps[:, tap]-start]*weights[:, tap]
    s0, s1, sa = _coordinate_weights(model.config.n_span)
    c0, c1, ca = _coordinate_weights(model.config.n_chord)
    span = sampled[s0]*(1-sa[:, None, None]) + sampled[s1]*sa[:, None, None]
    return (span[:, c0]*(1-ca[None, :, None]) + span[:, c1]*ca[None, :, None]).astype(np.float32)


class MeshNoise:
    """Callable pressure mapper for one source; model cache survives chunks."""
    def __init__(self, source_cfg, mesh_meta, logger=None):
        self.dt = float(mesh_meta['dt'])
        if not np.isfinite(self.dt) or self.dt <= 0:
            raise ValueError('Mesh dt must be finite and positive')
        self.gain = float(source_cfg.get('amplitude', 1.0))
        self.phase = float(source_cfg.get('phase', 0.0))
        if not np.isfinite(self.gain) or not np.isfinite(self.phase):
            raise ValueError('Source amplitude and phase must be finite')
        if source_cfg.get('amiet') and 'noise' not in source_cfg:
            raise ValueError('Use source.noise with BladeConfig options instead of the old source.amiet spectral proxy')
        cfg = dict(source_cfg.get('noise', {}))
        identity = json.dumps([source_cfg.get(k) for k in ('type', 'x', 'y', 'z')])
        default_seed = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], 'little')
        self.seed = cfg.pop('seed', default_seed)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError('noise.seed must be a nonnegative integer')
        # Four cells/wavelength is a conservative starting band limit. The
        # metadata spacing equals the solver spacing (checked by the runner).
        sound_speed = float(cfg.get('sound_speed', 343.0))
        fs = float(cfg.get('sample_rate', 24000.0))
        limits = [0.45/self.dt, 0.45*fs]
        spacings = [float(mesh_meta[k]) for k in ('dx', 'dy', 'dz') if k in mesh_meta]
        if spacings:
            if not all(np.isfinite(d) and d > 0 for d in spacings):
                raise ValueError('Mesh spacings must be finite and positive')
            limits.append(sound_speed/(4*max(spacings)))
        requested = float(cfg.get('f_max', 8000.0))
        if not all(np.isfinite(x) and x > 0 for x in [requested, sound_speed, fs]):
            raise ValueError('noise f_max, sound_speed and sample_rate must be finite and positive')
        cfg['f_max'] = min(requested, *limits)
        if cfg['f_max'] <= float(cfg.get('f_min', 80.0)):
            raise ValueError('No resolved noise band: decrease noise.f_min or refine the acoustic grid')
        if logger and cfg['f_max'] < requested:
            logger.info('Limiting source noise to %.1f Hz for the mesh/sampling clocks', cfg['f_max'])
        # Reject misspelled/unknown keys before loading mesh data or making models.
        BladeConfig(**cfg)
        self.config_json = json.dumps(cfg, sort_keys=True, allow_nan=False)
        self.logger = logger
        self._steps = None
        self._tables = {}

    def __call__(self, mesh, timesteps):
        timesteps = np.asarray(timesteps)
        if mesh.ndim != 4 or timesteps.shape != (mesh.shape[-1],):
            raise ValueError('Expected mesh[x,y,z,time] and one timestep per frame')
        times = timesteps.astype(np.float64)*self.dt+self.phase
        if np.any(~np.isfinite(times)) or np.any(times < 0):
            raise ValueError('Source phase must not shift noise sampling before time zero')
        if self._steps is None or not np.array_equal(timesteps, self._steps):
            self._steps = timesteps.copy()
            self._tables.clear()
        result = np.zeros(mesh.shape, dtype=np.float32)
        if self.gain == 0 or mesh.shape[-1] == 0:
            return result
        flat = mesh.reshape(-1)
        active = np.flatnonzero(np.isfinite(flat.real) & (flat.real != 0))
        if active.size == 0:
            return result
        blade, span, chord = decode_coordinates(flat.imag[active])
        time_index = active % mesh.shape[-1]
        for blade_id in np.unique(blade):
            blade_id = int(blade_id)
            if blade_id not in self._tables:
                seed = int(np.random.SeedSequence([self.seed, blade_id]).generate_state(1, dtype=np.uint64)[0])
                if self.logger:
                    self.logger.debug('Sampling broadband pressure for blade %d', blade_id)
                model = _blade_model(self.config_json, seed)
                self._tables[blade_id] = _pressure_table(model, times)
            selected = blade == blade_id
            ids = active[selected]
            jump = self._tables[blade_id][span[selected], chord[selected], time_index[selected]]
            # Opposite lobes represent +/- half of the same pressure jump.
            # Amplitude is a dimensionless source gain, not per-chunk RMS.
            result.reshape(-1)[ids] = flat.real[ids]/255 * (0.5*self.gain)*jump
        return result
