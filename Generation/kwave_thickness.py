"""Mesh-driven displaced-volume source, before k-Wave propagation.

The legacy complex mesh contains artificial signed pressure lobes. Their
absolute weights locate a *proxy* volume distribution, normalized independently
for each blade. They do not determine the physical blade volume. The temporary
default is 10 cm^3 per blade; replace it with measured geometry when available.

For volume fraction phi(x,t), mass injection is rho0 * dphi/dt. With the
vendored k-Wave additive source scaling, source.p = rho0*c0*dx/2 * dphi/dt.
No observer pressure, rotor WAV, or independently specified RPM is used here.
"""
import numpy as np
from scipy.fft import rfft, irfft, rfftfreq

from .kwave_noise import decode_coordinates

DEFAULT_BLADE_VOLUME_M3 = 1e-5


class MeshThickness:
    """Periodic, band-limited displaced-volume motion from labeled mesh frames.

    Precompute one geometry cycle once per reader/settings. Evaluate its cubic
    interpolant's derivative at absolute solver times, making chunk/restart
    boundaries independent of source-worker chunk size. Normalize each blade
    before filtering so rasterized area changes cannot create a breathing body.
    """
    def __init__(self, reader, speed, volume_per_blade_m3=DEFAULT_BLADE_VOLUME_M3,
                 f_max=6000., logger=None):
        self.dt = float(reader.meta['dt'])
        self.spacing = np.array([reader.meta[k] for k in ('dx', 'dy', 'dz')], dtype=float)
        self.speed = float(speed)
        self.volume_per_blade_m3 = float(volume_per_blade_m3)
        values = [self.dt, *self.spacing, self.volume_per_blade_m3, f_max]
        if not np.all(np.isfinite(values)) or min(values) <= 0:
            raise ValueError('Thickness dt, spacings, blade volume, and f_max must be finite and positive')
        if not np.isfinite(self.speed) or self.speed < 0:
            raise ValueError('Thickness playback speed must be finite and nonnegative')
        self.period_steps = len(reader.files)*int(reader.meta['nt'])
        self.period_seconds = self.period_steps*self.dt
        self.cell_volume = float(np.prod(self.spacing))
        self.blades = None
        self._centers = []
        self.stationary = self.speed == 0
        if self.stationary:
            frame = reader.sample_at(0., [0.])
            self.shape = frame.shape[:3]
            self._volume_proxy(frame, [0.])
            self.detected_rpm = 0.
            self.max_centroid_speed_m_s = 0.
            self.f_max = 0.
        else:
            # Bound by both solver and native mesh temporal Nyquist limits.
            self.f_max = min(float(f_max), .45/self.dt, .45*self.speed/self.dt)
            period = self.period_seconds/self.speed
            self.nphase = 2**int(np.ceil(np.log2(max(64, 4*self.f_max*period))))
            phases = np.arange(self.nphase)*self.period_steps/self.nphase
            volume = reader.sample_at(1., phases, logger, transform=self._volume_proxy)
            self.shape = volume.shape[:3]
            # Work in double precision: differentiating an almost constant
            # spatial integral otherwise magnifies float32 roundoff.
            volume = volume.astype(np.float64)
            total_fraction = len(self.blades)*self.volume_per_blade_m3/self.cell_volume
            volume *= total_fraction/volume.sum(axis=(0, 1, 2), keepdims=True)
            self.stationary = np.array_equal(volume, np.broadcast_to(volume[..., :1], volume.shape))
            self._measure_motion(phases)
            self.h = period/self.nphase
            frequency = rfftfreq(self.nphase, self.h)
            taper = .5*(1+np.cos(np.pi*np.clip((frequency-.8*self.f_max)/(.2*self.f_max), 0, 1)))
            spectrum = rfft(volume, axis=-1)
            spectrum *= taper
            self.volume = irfft(spectrum, n=self.nphase, axis=-1)
            self.rate = irfft(spectrum*(2j*np.pi*frequency), n=self.nphase, axis=-1)
        self._centers.clear()
        if logger:
            logger.info('Thickness proxy: %d blades, %.6g m^3/blade, mesh-derived RPM=%s, '
                        'max tracked centroid speed=%.3f m/s, cutoff=%.1f Hz',
                        len(self.blades), self.volume_per_blade_m3,
                        'unresolved' if self.detected_rpm is None else f'{self.detected_rpm:.2f}',
                        self.max_centroid_speed_m_s, self.f_max)

    def _volume_proxy(self, mesh, steps):
        weight = np.abs(mesh.real.astype(np.float64))
        active = weight > 0
        if not np.isfinite(weight).all():
            raise ValueError('Nonfinite mesh weight in thickness geometry')
        labels = np.zeros(mesh.shape, dtype=np.int8)
        labels[active] = decode_coordinates(mesh.imag[active])[0]
        blades = tuple(int(b) for b in np.unique(labels[active]))
        if not blades:
            raise ValueError('Thickness geometry has no active blade cells')
        if self.blades is None:
            self.blades = blades
        if blades != self.blades:
            raise ValueError('Blade IDs change over the mesh cycle; cannot conserve displaced volume')
        result = np.zeros(mesh.shape, dtype=np.float64)
        centers = []
        for blade in blades:
            w = np.where(active & (labels == blade), weight, 0.)
            total = w.sum(axis=(0, 1, 2))
            if np.any(total <= 0):
                raise ValueError(f'Blade {blade} disappears in a mesh frame')
            w /= total
            result += w*(self.volume_per_blade_m3/self.cell_volume)
            center = []
            for axis in range(3):
                shape = [1]*4
                shape[axis] = mesh.shape[axis]
                coordinate = (np.arange(mesh.shape[axis])*self.spacing[axis]).reshape(shape)
                center.append((w*coordinate).sum(axis=(0, 1, 2)))
            centers.append(np.stack(center, axis=-1))
        # sample_at can call the transform twice at fractional positions.
        # Motion diagnostics are computed separately from exact requested frames.
        self._centers.append((np.asarray(steps).copy(), np.stack(centers, axis=1)))
        return result

    def _measure_motion(self, phases):
        # Combine lower/upper diagnostics using sample_at's interpolation alpha.
        points = {}
        for steps, centers in self._centers:
            for step, center in zip(steps, centers):
                points.setdefault(float(step), []).append(center)
        centers = []
        for step in phases:
            values = points[float(step)]
            alpha = step-np.floor(step)
            centers.append(values[0] if len(values) == 1 else (1-alpha)*values[0]+alpha*values[1])
        centers = np.asarray(centers)
        h = self.period_seconds/self.speed/len(phases)
        velocity = (np.roll(centers, -1, axis=0)-np.roll(centers, 1, axis=0))/(2*h)
        self.max_centroid_speed_m_s = float(np.max(np.linalg.norm(velocity, axis=-1)))
        # Diagnostic only: rotation about the mesh center and z axis, as in
        # SourceDrawer. Injection uses volume changes and needs no axis or RPM.
        center = np.array(self.shape)*self.spacing/2
        offsets = centers[:, 0, :2]-center[:2]
        if np.max(np.linalg.norm(offsets, axis=-1)) < .25*min(self.spacing[:2]):
            self.detected_rpm = None
        else:
            angle = np.unwrap(np.arctan2(offsets[:, 1], offsets[:, 0]))
            self.detected_rpm = float(np.polyfit(phases*self.dt/self.speed, angle, 1)[0]*60/(2*np.pi))

    def sample_volume_rate(self, start, stop):
        """Return dphi/dt [1/s], xyz-time order; zero for stationary geometry."""
        if int(start) != start or int(stop) != stop or start < 0 or stop <= start:
            raise ValueError('Expected nonempty nonnegative integer timestep interval')
        result = np.zeros(self.shape+(int(stop-start),), dtype=np.float32)
        if self.stationary:
            return result
        for offset in range(0, int(stop-start), 64):
            steps = np.arange(int(start)+offset, min(int(start)+offset+64, int(stop)))
            position = np.remainder(steps.astype(float)*self.speed, self.period_steps)*self.nphase/self.period_steps
            lo = np.floor(position).astype(np.int64)
            a = position-lo
            lo %= self.nphase
            hi = (lo+1) % self.nphase
            # Derivative of the periodic cubic Hermite volume interpolant.
            block = ((6*a*a-6*a)*(self.volume[..., lo]-self.volume[..., hi])/self.h
                     +(3*a*a-4*a+1)*self.rate[..., lo]
                     +(3*a*a-2*a)*self.rate[..., hi])
            result[..., offset:offset+len(steps)] = block
        return result


def thickness_source(reader, source_cfg, output_sample_rate=None, logger=None):
    """Get the cached source. Enabled by default; set thickness.enabled=false to opt out."""
    settings = source_cfg.get('thickness', {})
    if not isinstance(settings, dict):
        raise ValueError('source.thickness must be a mapping')
    unknown = set(settings)-{'enabled', 'volume_per_blade_m3', 'f_max'}
    if unknown:
        raise ValueError(f'Unknown thickness settings: {sorted(unknown)}')
    if not settings.get('enabled', True):
        return None
    c = float(source_cfg.get('noise', {}).get('sound_speed', 343.))
    cutoff = min(float(settings.get('f_max', 6000.)), c/(4*max(float(reader.meta[k]) for k in ('dx','dy','dz'))))
    if output_sample_rate is not None:
        cutoff = min(cutoff, .45*float(output_sample_rate))
    key = (float(source_cfg['speed']), float(settings.get('volume_per_blade_m3', DEFAULT_BLADE_VOLUME_M3)), cutoff)
    # One reader can serve several sources with different playback speeds.
    # Keep each configured cycle so alternating sources do not rebuild it.
    if not hasattr(reader, '_thickness_sources'):
        reader._thickness_sources = {}
    if key not in reader._thickness_sources:
        reader._thickness_sources[key] = MeshThickness(reader, *key, logger=logger)
    return reader._thickness_sources[key]
