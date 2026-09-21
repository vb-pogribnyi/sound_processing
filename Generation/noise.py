#!/usr/bin/env python3
"""Standalone broadband blade pressure-jump generator. See Noise.md.

No k-Wave imports, mesh loading, blade rotation, BPF tones or Doppler.
Python API: model = BladeNoise(BladeConfig()); p = model.sample(24000)
Output p[span, chord, time] is an equivalent pressure jump in Pa. A symmetric
surface representation is +p/2 and -p/2; k-Wave injection needs calibration.
"""
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path
import argparse
import json
import time
import warnings

import numpy as np
from scipy.interpolate import interp1d
from scipy.signal import welch

if __package__:
    from .Amiet.airfoil_noise import AmT
    from .Amiet.bpm import displacement_thickness, trailing_edge_psd, tip_psd
else:
    from Amiet.airfoil_noise import AmT
    from Amiet.bpm import displacement_thickness, trailing_edge_psd, tip_psd


@dataclass
class BladeConfig:
    # Scalars or one value per span cell. All units SI except angle in degrees.
    flow_speed: object = 25.0
    chord: object = 0.035
    turbulence_intensity: object = 0.025  # u_rms / U, NOT percent
    angle_of_attack: object = 4.0         # relative to the zero-lift angle
    length_scale: object = 0.007
    span: float = 0.1                    # root-to-tip modeled blade length
    n_span: int = 8
    n_chord: int = 12
    sound_speed: float = 343.0
    density: float = 1.225
    viscosity: float = 1.5e-5
    # Supply measured/XFOIL displacement thicknesses when possible.
    delta_pressure: object = None
    delta_suction: object = None
    tripped: bool = True
    tip_shape: str = 'rounded'
    tip_loading_ratio: float = 1.0
    tip_separation_length: float = None
    # Synthesis controls; f_max must also fit the future acoustic mesh.
    sample_rate: float = 24000.0
    f_min: float = 80.0
    f_max: float = 8000.0
    block_samples: int = 4096
    model_frequencies: int = 128
    gust_modes: int = 48
    seed: int = 0
    leading_edge: bool = True
    trailing_edge: bool = True
    tip: bool = True
    te_chord_fraction: float = 0.15   # assumed equivalent-loading envelope
    span_coherence_decay: float = 0.7


def _integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')


def _positive(value, name):
    if not np.isscalar(value) or not np.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be finite and positive')


def _profile(value, name, size, allow_zero=False, signed=False):
    a = np.asarray(value, dtype=float)
    if a.ndim == 0:
        a = np.full(size, a)
    if a.shape != (size,) or not np.all(np.isfinite(a)):
        raise ValueError(f'{name} must be finite scalar or length n_span')
    if not signed and np.any(a < 0 if allow_zero else a <= 0):
        raise ValueError(f'{name} must be {"nonnegative" if allow_zero else "positive"}')
    return a.copy()


class BladeNoise:
    """Precomputed spatial spectral factors; random-access, nonrepeating output.

    sample(n, start_sample=k) agrees with slicing a longer sample at k. Blocks
    are independently seeded, overlap by 50%, and use sine windows whose
    squared weights sum to one. No resetting or tiling of a short noise loop.
    Operating conditions are fixed for the lifetime of this model.
    """
    def __init__(self, config=None):
        self.config = config or BladeConfig()
        c = self.config
        for key in ('n_span', 'n_chord', 'model_frequencies', 'gust_modes'):
            _integer(getattr(c, key), key, 2)
        _integer(c.block_samples, 'block_samples', 32)
        _integer(c.seed, 'seed')
        if c.block_samples % 2:
            raise ValueError('block_samples must be even')
        for key in ('span', 'sound_speed', 'density', 'viscosity', 'sample_rate',
                    'f_min', 'f_max', 'te_chord_fraction', 'span_coherence_decay'):
            _positive(getattr(c, key), key)
        if not 0 < c.f_min < c.f_max < c.sample_rate/2:
            raise ValueError('Require 0 < f_min < f_max < sample_rate/2')
        if c.f_max-c.f_min < 4*c.sample_rate/c.block_samples:
            raise ValueError('Frequency band needs at least four block FFT intervals')
        if c.te_chord_fraction > 1:
            raise ValueError('te_chord_fraction must be <= 1')
        _positive(c.tip_loading_ratio, 'tip_loading_ratio')
        if c.tip_shape not in ('rounded', 'square'):
            raise ValueError('tip_shape must be rounded or square')
        if c.tip_separation_length is not None:
            _positive(c.tip_separation_length, 'tip_separation_length')
            if c.tip_separation_length > c.span:
                raise ValueError('tip_separation_length cannot exceed span')
        self.speed = _profile(c.flow_speed, 'flow_speed', c.n_span)
        self.chord = _profile(c.chord, 'chord', c.n_span)
        self.intensity = _profile(c.turbulence_intensity, 'turbulence_intensity', c.n_span, True)
        self.alpha = _profile(c.angle_of_attack, 'angle_of_attack', c.n_span, signed=True)
        self.length = _profile(c.length_scale, 'length_scale', c.n_span)
        if np.any(self.speed >= c.sound_speed):
            raise ValueError('Only subsonic relative flow is supported')
        if np.any(self.intensity > 1) or np.any(abs(self.alpha) > 25):
            raise ValueError('Require turbulence_intensity <= 1 and |angle_of_attack| <= 25 degrees')
        self.reynolds = self.speed*self.chord/c.viscosity
        if c.trailing_edge and np.any(self.reynolds < 1e5):
            warnings.warn('Low Reynolds number: BPM turbulent-boundary-layer estimates may miss transition/laminar separation.', stacklevel=2)
        self.x_fraction = (np.arange(c.n_chord)+.5)/c.n_chord
        self.span_m = (np.arange(c.n_span)+.5)*c.span/c.n_span
        self.x_m = self.chord[:, None]*self.x_fraction[None, :]
        self.cell_area = np.broadcast_to(
            self.chord[:, None]/c.n_chord*c.span/c.n_span, self.x_m.shape).copy()
        estimates = np.array([displacement_thickness(ch, re, a, c.tripped)
                              for ch, re, a in zip(self.chord, self.reynolds, self.alpha)])
        self.delta_pressure = (estimates[:, 0] if c.delta_pressure is None else
                               _profile(c.delta_pressure, 'delta_pressure', c.n_span))
        self.delta_suction = (estimates[:, 1] if c.delta_suction is None else
                              _profile(c.delta_suction, 'delta_suction', c.n_span))
        # Sample both spectral shape and chordwise complex phase. Increase
        # model_frequencies/gust_modes to check convergence for a new blade.
        phase_points = int(np.ceil(8*(c.f_max-c.f_min)*np.max(self.chord/self.speed)))+1
        self.model_frequency = np.unique(np.r_[
            np.geomspace(c.f_min, c.f_max, c.model_frequencies),
            np.linspace(c.f_min, c.f_max, max(2, phase_points))])
        self.frequency = np.fft.rfftfreq(c.block_samples, 1/c.sample_rate)
        self.window = np.sin(np.pi*(np.arange(c.block_samples)+.5)/c.block_samples)
        self._factors = {}
        self._interpolators = {}
        self._build_models()
        # Per-instance bounded cache; does not keep other model instances alive.
        self._block = lru_cache(maxsize=12)(self._make_block)

    def _build_models(self):
        c = self.config
        nf, ns, nx = len(self.model_frequency), c.n_span, c.n_chord
        dy = c.span/ns
        if c.leading_edge:
            factor = np.empty((nf, ns, nx, c.gust_modes), dtype=complex)
            nodes, weights = np.polynomial.legendre.leggauss(c.gust_modes)
            scale = 1/np.mean(self.length)
            for fi, f in enumerate(self.model_frequency):
                # Surface-pressure cutoff, including subcritical gusts. The
                # tangent quadrature resolves low ky as well as the long tail.
                cutoff = max(1.25*AmT.ky_att(self.x_m[j, 0]-self.chord[j]/2,
                             self.chord[j]/2, self.speed[j]/c.sound_speed,
                             2*np.pi*f/c.sound_speed, Att=-20) for j in range(ns))
                angle = np.arctan(cutoff/scale)
                theta = angle*nodes
                ky = scale*np.tan(theta)
                dky = weights*angle*scale/np.cos(theta)**2
                for j in range(ns):
                    u, b = self.speed[j], self.chord[j]/2
                    phi = AmT.Phi_2D(2*np.pi*f/u, ky, u, self.intensity[j], self.length[j])[0]
                    xy = np.array([self.x_m[j]-b, np.full(nx, self.span_m[j])])
                    for k in range(c.gust_modes):
                        dp = AmT.delta_p(c.density, b, np.sqrt(phi[k]), 2*np.pi*f/u,
                                         ky[k], xy, u/c.sound_speed)
                        # Same 4*pi convention as vendored calc_radiated_Spp;
                        # no acoustic Green function is applied here.
                        factor[fi, j, :, k] = dp*np.sqrt(4*np.pi*u*dky[k]) * np.sinc(ky[k]*dy/(2*np.pi))
            self._factors['leading_edge'] = factor
        if c.trailing_edge:
            factor = np.empty((nf, ns, nx, ns), dtype=complex)
            envelope = np.exp(-(1-self.x_fraction)/c.te_chord_fraction)
            # Each row integrates to unit force over that span strip.
            pressure_per_force = envelope[None, :]/np.sum(self.cell_area*envelope, axis=1)[:, None]
            travel = np.cumsum(dy/(.7*self.speed))
            travel -= travel[0]
            for fi, f in enumerate(self.model_frequency):
                reference = np.array([trailing_edge_psd(
                    f, speed=self.speed[j], chord=self.chord[j], span=dy,
                    alpha_deg=self.alpha[j], delta_pressure=self.delta_pressure[j],
                    delta_suction=self.delta_suction[j], sound_speed=c.sound_speed,
                    density=c.density, viscosity=c.viscosity) for j in range(ns)])
                force_psd = reference*(4*np.pi*c.sound_speed/(2*np.pi*f))**2
                coherence = np.exp(-c.span_coherence_decay*2*np.pi*f*abs(travel[:, None]-travel))
                force_factor = np.sqrt(force_psd)[:, None]*np.linalg.cholesky(coherence)
                # BPM already scales band power with strip span. Preserve its
                # total broadside level when introducing correlated strips.
                coherent_power = np.sum(abs(force_factor.sum(axis=0))**2)
                if coherent_power > 0:
                    force_factor *= np.sqrt(force_psd.sum()/coherent_power)
                factor[fi] = pressure_per_force[:, :, None]*force_factor[:, None, :]
            self._factors['trailing_edge'] = factor
        if c.tip:
            reference, length = tip_psd(
                self.model_frequency, speed=self.speed[-1], chord=self.chord[-1],
                alpha_deg=self.alpha[-1], shape=c.tip_shape, loading_ratio=c.tip_loading_ratio,
                separation_length=c.tip_separation_length, sound_speed=c.sound_speed, density=c.density)
            self.tip_length = float(length)
            # Area-normalized equivalent tip force. The core may be smaller
            # than a cell; use at least a cell-wide deposition kernel.
            width = max(length, dy)
            envelope = np.exp(-.5*((c.span-self.span_m)/width)**2)[:, None] * np.exp(-(1-self.x_fraction)/c.te_chord_fraction)
            envelope /= np.sum(envelope*self.cell_area)
            amplitude = np.sqrt(reference)*4*np.pi*c.sound_speed/(2*np.pi*self.model_frequency)
            self._factors['tip'] = amplitude[:, None, None, None]*envelope[None, :, :, None]
        for name, factor in self._factors.items():
            if not np.all(np.isfinite(factor)):
                raise ValueError(f'Nonfinite {name} spectrum; check model inputs')
            self._interpolators[name] = interp1d(self.model_frequency, factor, axis=0,
                                                bounds_error=False, fill_value=0.)

    def _band_window(self, frequency):
        c = self.config
        width = min(.1*(c.f_max-c.f_min), max(2*c.sample_rate/c.block_samples, .05*c.f_max))
        left = np.clip((frequency-c.f_min)/width, 0, 1)
        right = np.clip((c.f_max-frequency)/width, 0, 1)
        return np.sin(np.pi*left/2)*np.sin(np.pi*right/2)

    def _make_block(self, index, component):
        c = self.config
        # Signed index -1 is required for the overlap preceding time zero.
        encoded = 2*index if index >= 0 else -2*index-1
        stream = ('leading_edge', 'trailing_edge', 'tip').index(component)
        rng = np.random.default_rng(np.random.SeedSequence([c.seed, stream, encoded]))
        modes = self._factors[component].shape[-1]
        nf = len(self.frequency)
        white = (rng.standard_normal((nf, modes))+1j*rng.standard_normal((nf, modes)))/np.sqrt(2)
        spectrum = np.zeros((nf, c.n_span, c.n_chord), dtype=complex)
        # Only transient small frequency slabs; never allocate frequency x
        # every output cell x every stochastic mode for a full FFT.
        for start in range(1, nf-1, 64):
            stop = min(start+64, nf-1)
            frequency = self.frequency[start:stop]
            h = self._interpolators[component](frequency)
            spectrum[start:stop] = np.einsum('fijk,fk->fij', h, white[start:stop]) * self._band_window(frequency)[:, None, None]
        spectrum *= np.sqrt(c.block_samples*c.sample_rate/2)
        block = np.fft.irfft(spectrum, n=c.block_samples, axis=0).transpose(1, 2, 0)
        block *= self.window
        block.setflags(write=False)
        return block

    def sample_components(self, count, start_sample=0):
        """Return dict of three float32 arrays [span, chord, time], in Pa.

        Disabled mechanisms return zeros. Absolute sample indexing makes
        arbitrary chunk sizes, restarts and repeated queries reproducible.
        """
        _integer(count, 'count')
        _integer(start_sample, 'start_sample')
        c = self.config
        shape = (c.n_span, c.n_chord, count)
        hop = c.block_samples//2
        result = {}
        for name in ('leading_edge', 'trailing_edge', 'tip'):
            out = np.zeros(shape, dtype=np.float64)
            if name in self._factors and count:
                first = start_sample//hop-1
                last = (start_sample+count-1)//hop
                for index in range(first, last+1):
                    origin = index*hop
                    lo = max(start_sample, origin)
                    hi = min(start_sample+count, origin+c.block_samples)
                    out[..., lo-start_sample:hi-start_sample] += self._block(index, name)[..., lo-origin:hi-origin]
            result[name] = out.astype(np.float32)
        return result

    def sample(self, count, start_sample=0):
        """Return total equivalent pressure jump [span, chord, time], Pa."""
        parts = self.sample_components(count, start_sample)
        return parts['leading_edge'] + parts['trailing_edge'] + parts['tip']

    def target_psd(self, component):
        """One-sided pressure PSD at cells, before finite-block window broadening."""
        c = self.config
        out = np.zeros((len(self.frequency), c.n_span, c.n_chord))
        if component not in self._interpolators:
            return out
        for i in range(1, len(self.frequency)-1, 64):
            f = self.frequency[i:i+64]
            out[i:i+64] = np.sum(abs(self._interpolators[component](f))**2, axis=-1)*self._band_window(f)[:, None, None]**2
        out[-1] = 0
        return out


def generate_pressure(config=None, duration=0.25, start_time=0.0):
    """Convenience API returning a numpy array in Pa. Reuse BladeNoise for chunks."""
    _positive(duration, 'duration')
    if not np.isfinite(start_time) or start_time < 0:
        raise ValueError('start_time must be finite and nonnegative')
    model = BladeNoise(config)
    count = round(duration*model.config.sample_rate)
    if count < 1:
        raise ValueError('duration is shorter than one sample')
    return model.sample(count, round(start_time*model.config.sample_rate))


def visualize(model, parts, path, gif_path=None):
    """Save field, history and PSD diagnostics without a GUI or mesh imports."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    c = model.config
    pressure = sum(parts.values())
    if pressure.shape[-1] < 2:
        raise ValueError('Visualization requires at least two samples')
    extent = (0, 1, 0, c.span)
    fig, axes = plt.subplots(2, 3, figsize=(14, 8), constrained_layout=True)
    for ax, (name, data) in zip(axes[0], parts.items()):
        rms = np.sqrt(np.mean(data.astype(float)**2, axis=-1))
        im = ax.imshow(rms, origin='lower', aspect='auto', extent=extent, cmap='magma')
        ax.set(title=name.replace('_', ' ').title()+' RMS', xlabel='Chord fraction (LE → TE)', ylabel='Span from root [m]')
        fig.colorbar(im, ax=ax, label='Equivalent pressure jump [Pa RMS]')
    t = np.arange(pressure.shape[-1])/c.sample_rate
    idx = pressure.shape[-1]//2
    limit = max(float(np.max(abs(pressure[..., idx]))), 1e-12)
    im = axes[1, 0].imshow(pressure[..., idx], origin='lower', aspect='auto', extent=extent, cmap='RdBu_r', vmin=-limit, vmax=limit)
    axes[1, 0].set(title=f'Total jump at t={t[idx]:.4f} s', xlabel='Chord fraction', ylabel='Span from root [m]')
    fig.colorbar(im, ax=axes[1, 0], label='Equivalent pressure jump [Pa]')
    near_te = pressure[:, -1, :]
    im = axes[1, 1].imshow(near_te, origin='lower', aspect='auto', extent=(0, t[-1], 0, c.span), cmap='RdBu_r')
    axes[1, 1].set(title='Near trailing edge: span versus time', xlabel='Time [s]', ylabel='Span from root [m]')
    fig.colorbar(im, ax=axes[1, 1], label='Equivalent pressure jump [Pa]')
    for name, data in parts.items():
        f, psd = welch(data.astype(float), fs=c.sample_rate, nperseg=min(1024, len(t)), axis=-1)
        mean_psd = np.mean(psd, axis=(0, 1))
        if np.any(mean_psd > 0):
            axes[1, 2].loglog(f[1:], mean_psd[1:], label=name.replace('_', ' '))
    axes[1, 2].set(title='Spatially averaged pressure PSD', xlabel='Frequency [Hz]', ylabel='Pa²/Hz')
    axes[1, 2].legend()
    axes[1, 2].grid(alpha=.2)
    fig.suptitle('Broadband equivalent blade loading — no motion or tonal synthesis')
    fig.savefig(path, dpi=150)
    plt.close(fig)
    if gif_path:
        from matplotlib.animation import FuncAnimation, PillowWriter
        fig, ax = plt.subplots(figsize=(8, 4))
        bound = max(float(np.quantile(abs(pressure), .995)), 1e-12)
        im = ax.imshow(pressure[..., 0], origin='lower', aspect='auto', extent=extent,
                       cmap='RdBu_r', vmin=-bound, vmax=bound)
        fig.colorbar(im, ax=ax, label='Equivalent pressure jump [Pa]')
        ax.set(xlabel='Chord fraction (LE → TE)', ylabel='Span from root [m]')
        # Consecutive acoustic samples, slowed for visual inspection.
        frames = np.arange(min(80, len(t)))
        def update(frame):
            im.set_data(pressure[..., frame])
            ax.set_title(f'Blade pressure jump: t = {t[frame]*1000:.3f} ms (slow motion)')
            return (im,)
        ani = FuncAnimation(fig, update, frames=frames)
        ani.save(gif_path, writer=PillowWriter(fps=15))
        plt.close(fig)


def write_wav_preview(model, path, duration=5.0, output_rate=48000):
    """Normalize area-averaged equivalent loading for listening, not SPL.

    Generates fresh continuation of the same process; never tiles a record.
    Export a conventional little-endian, mono, signed 16-bit PCM WAV.
    Resampling changes the audio clock without changing pitch or duration.
    Publish the completed file atomically so readers cannot see a partial WAV.
    """
    import math
    import os
    import tempfile
    import wave
    from scipy.signal import resample_poly
    _positive(duration, 'WAV duration')
    _integer(output_rate, 'output_rate', 1)
    fs = model.config.sample_rate
    if int(fs) != fs:
        raise ValueError('WAV output requires an integer sample_rate')
    count = round(duration*fs)
    if count < 1:
        raise ValueError('WAV duration must cover at least one sample')
    audio = np.empty(count, dtype=float)
    weights = model.cell_area/model.cell_area.sum()
    for start in range(0, count, model.config.block_samples):
        stop = min(count, start+model.config.block_samples)
        pressure = model.sample(stop-start, start_sample=start)
        audio[start:stop] = np.einsum('ij,ijt->t', weights, pressure)
    if int(fs) != output_rate:
        divisor = math.gcd(int(fs), output_rate)
        audio = resample_poly(audio, output_rate//divisor, int(fs)//divisor)
        audio = audio[:round(count/fs*output_rate)]
    if audio.size == 0 or not np.all(np.isfinite(audio)):
        raise ValueError('WAV preview must contain finite audio samples')
    peak = float(np.max(abs(audio)))
    gain = 10**(-1/20)/peak if peak else 1.0
    pcm = np.round(np.clip(audio*gain, -1, 1)*32767).astype('<i2')
    path = Path(path)
    temporary = None
    try:
        # Keep the temporary file in the destination directory for atomic rename.
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+'.',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            with wave.open(stream, 'wb') as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(output_rate)
                writer.writeframes(pcm.tobytes())
            stream.flush()
            os.fsync(stream.fileno())
            # Preserve normal generated-file readability across users/containers.
            os.fchmod(stream.fileno(), path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return dict(duration_s=len(pcm)/output_rate, sample_rate_hz=output_rate,
                source_sample_rate_hz=fs, samples=len(pcm), encoding='PCM_S16LE', channels=1,
                quantity='area-averaged equivalent blade pressure jump; source listening preview, not microphone audio',
                normalized=True, gain_per_pa=gain, peak_dbfs=-1.0 if peak else None,
                rms_pa=float(np.sqrt(np.mean(audio**2))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='JSON object matching BladeConfig; profiles may be arrays')
    parser.add_argument('--duration', type=float, default=.25)
    parser.add_argument('--out-dir', type=Path, default=Path(__file__).resolve().parent/'outputs/noise')
    parser.add_argument('--gif', action='store_true')
    args = parser.parse_args()
    _positive(args.duration, 'duration')
    config = BladeConfig(**json.loads(args.config.read_text())) if args.config else BladeConfig()
    start = time.perf_counter()
    model = BladeNoise(config)
    count = round(args.duration*config.sample_rate)
    if count < 2:
        parser.error('duration must cover at least two samples')
    parts = model.sample_components(count)
    pressure = sum(parts.values())
    args.out_dir.mkdir(parents=True, exist_ok=True)
    np.save(args.out_dir/'pressure_jump.npy', pressure)
    np.savez_compressed(args.out_dir/'pressure_field.npz', pressure_jump=pressure,
                        **parts, x_m=model.x_m, span_m=model.span_m,
                        chord_fraction=model.x_fraction, cell_area=model.cell_area,
                        time_s=np.arange(count)/config.sample_rate)
    metadata = dict(config=asdict(config), units='Pa', axes=['span', 'chord', 'time'],
                    quantity='equivalent pressure jump; not calibrated k-Wave input',
                    actual_duration_s=count/config.sample_rate,
                    delta_pressure_m=model.delta_pressure.tolist(),
                    delta_suction_m=model.delta_suction.tolist(),
                    reynolds=model.reynolds.tolist(),
                    synthesis_seconds=time.perf_counter()-start,
                    rms_pa={k: float(np.sqrt(np.mean(v.astype(float)**2))) for k, v in parts.items()})
    metadata['wav_preview'] = write_wav_preview(model, args.out_dir/'noise_5s.wav')
    (args.out_dir/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    visualize(model, parts, args.out_dir/'pressure_field.png',
              args.out_dir/'pressure_field.gif' if args.gif else None)
    print(json.dumps(metadata, indent=2))
    print(f'Saved {pressure.shape} float32 pressure field and visualization to {args.out_dir}')


if __name__ == '__main__':
    main()
