"""Source selection and sparse pressure pulses; no medium or export changes."""
import numpy as np


def source_options(source, default_mode=None):
    """Resolve source selection without mutating YAML dictionaries.

    `loading` selects the existing displacement/thickness implementation;
    it is not a new steady aerodynamic lift model. Missing mode preserves
    legacy settings (including the optional tip source).
    """
    result = dict(source)
    mode = result.get('mode', default_mode)
    if mode is not None and mode not in ('amiet', 'loading', 'both'):
        raise ValueError('source_mode / source.mode must be amiet, loading, or both')
    if mode is not None:
        result['mode'] = mode
        noise = dict(result.get('noise', {}))
        noise.setdefault('tip', False)
        if mode == 'amiet':
            noise['tip'] = False
        result['noise'] = noise
    return result



class PressureBumps:
    """Sparse, randomly placed pressure-source pulses on the solver clock.

    Each event has a Gaussian spatial footprint and a compact bipolar pulse.
    peak_pa is its peak source.p amplitude, before k-Wave source scaling.
    The event schedule is seeded once and reused across chunks/restarts.
    """
    def __init__(self, settings, shape, dt, duration):
        settings = dict(settings or {})
        unknown = settings.keys() - {'peak_pa', 'seed', 'rate_hz', 'radius_cells', 'duration_s'}
        if unknown:
            raise ValueError(f'Unknown pressure_noise settings: {sorted(unknown)}')
        self.peak = float(settings.get('peak_pa', 0.))
        rate = float(settings.get('rate_hz', 20.))
        radius = float(settings.get('radius_cells', 1.))
        pulse_duration = float(settings.get('duration_s', .001))
        seed = settings.get('seed', 0)
        if (not np.isfinite([self.peak, rate, radius, pulse_duration, dt, duration]).all()
                or min(self.peak, rate) < 0 or min(radius, pulse_duration, dt, duration) <= 0):
            raise ValueError('Pressure bump magnitude/rate must be nonnegative; radius and times must be positive')
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError('pressure_noise.seed must be a nonnegative integer')
        self.events = []
        self.pulse_steps = pulse_duration / dt
        if self.peak == 0 or rate == 0:
            return
        if self.pulse_steps < 4:
            raise ValueError('pressure_noise.duration_s must span at least four solver steps')
        rng = np.random.default_rng(seed)
        count = rng.poisson(rate * duration)
        starts = rng.integers(0, max(1, int(duration/dt)), count)
        centers = rng.integers(0, shape, size=(count, 3))
        signs = rng.choice([-1., 1.], count)
        extent = int(np.ceil(3*radius))
        for start, center, sign in zip(starts, centers, signs):
            axes = [np.arange(max(0, c-extent), min(size, c+extent+1))
                    for c, size in zip(center, shape)]
            x, y, z = np.meshgrid(*axes, indexing='ij')
            distance2 = (x-center[0])**2 + (y-center[1])**2 + (z-center[2])**2
            active = distance2 <= (3*radius)**2
            indices = np.ravel_multi_index((x[active], y[active], z[active]), shape, order='F')
            weights = (sign*self.peak*np.exp(-.5*distance2[active]/radius**2)).astype(np.float32)
            self.events.append((int(start), indices, weights))

    def add_to_mask(self, mask):
        """Extend the existing blade mask with all scheduled event footprints."""
        for _, indices, _ in self.events:
            mask[np.unravel_index(indices, mask.shape, order='F')] = True
        indices = np.flatnonzero(mask.ravel(order='F'))
        self.rows = [(start, np.searchsorted(indices, event_indices), weights)
                     for start, event_indices, weights in self.events]

    def add_to_source(self, source_p, start, stop):
        """Add the current chunk's events to source.p; never modify sensors."""
        # HDF5 uint64 timesteps can promote mixed integer arithmetic to float64.
        if int(start) != start or int(stop) != stop:
            raise ValueError('Pressure bump timesteps must be integers')
        start, stop = int(start), int(stop)
        for event_start, rows, weights in self.rows:
            lo = max(start, event_start)
            hi = min(stop, event_start + int(np.ceil(self.pulse_steps)))
            if hi <= lo:
                continue
            phase = (np.arange(lo, hi)-event_start)/self.pulse_steps
            # One sine cycle under a Hann window: smooth endpoints, zero integral,
            # and unit analytic peak. Random polarity avoids systematic bias.
            pulse = (np.sin(2*np.pi*phase)*np.sin(np.pi*phase)**2/(3*np.sqrt(3)/8)).astype(np.float32)
            source_p[rows, lo-start:hi-start] += weights[:, None]*pulse
