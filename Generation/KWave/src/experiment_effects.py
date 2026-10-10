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
    With src_replica the pulse is instead a Hann-windowed segment of the
    sources' captured sound (see SourceCapture in run_experiments.py), taken
    from a random earlier time. peak_pa is then a dimensionless gain: the
    footprint sums to peak_pa, so gain 1 matches the sources' level.
    The event schedule is seeded once and reused across chunks/restarts.
    """
    def __init__(self, settings, shape, dt, duration):
        settings = dict(settings or {})
        unknown = settings.keys() - {'peak_pa', 'seed', 'rate_hz', 'radius_cells', 'duration_s', 'src_replica'}
        if unknown:
            raise ValueError(f'Unknown pressure_noise settings: {sorted(unknown)}')
        self.peak = float(settings.get('peak_pa', 0.))
        rate = float(settings.get('rate_hz', 20.))
        radius = float(settings.get('radius_cells', 1.))
        pulse_duration = float(settings.get('duration_s', .001))
        seed = settings.get('seed', 0)
        self.src_replica = settings.get('src_replica', False)
        if not isinstance(self.src_replica, bool):
            raise ValueError('pressure_noise.src_replica must be true or false')
        self.replica_source = None
        self.replica_fractions = None
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
            footprint = np.exp(-.5*distance2[active]/radius**2)
            if self.src_replica:
                # Gain relative to the captured source sound: unit-sum footprint
                footprint /= footprint.sum()
            weights = (sign*self.peak*footprint).astype(np.float32)
            self.events.append((int(start), indices, weights))
        # Drawn after the schedule, so src_replica does not change event times/places
        self.replica_fractions = rng.random(len(self.events)) if self.src_replica else None

    def add_to_mask(self, mask):
        """Extend the existing blade mask with all scheduled event footprints."""
        for _, indices, _ in self.events:
            mask[np.unravel_index(indices, mask.shape, order='F')] = True
        indices = np.flatnonzero(mask.ravel(order='F'))
        self.rows = [(start, np.searchsorted(indices, event_indices), weights)
                     for start, event_indices, weights in self.events]

    def set_replica_source(self, segment, margin):
        """segment(start, length) returns the captured source sound for solver steps
        [start, start+length); margin is how far the capture reaches past a source
        step (its largest propagation delay), in steps."""
        self.replica_source = (segment, int(margin))
        self._replica_cache = {}

    def replica_start(self, event_idx):
        """Capture step an event replays from: uniformly random among the segments
        that end, with margin, before the event starts. None when there is no such
        history yet (an early event) - that event then stays silent."""
        event_start = self.events[event_idx][0]
        latest = event_start - int(np.ceil(self.pulse_steps)) - self.replica_source[1]
        if latest < 0:
            return None
        return int(self.replica_fractions[event_idx]*(latest+1))

    def _replica_segment(self, event_idx):
        if event_idx not in self._replica_cache:
            start = self.replica_start(event_idx)
            self._replica_cache[event_idx] = (None if start is None else np.asarray(
                self.replica_source[0](start, int(np.ceil(self.pulse_steps))), dtype=np.float64))
        return self._replica_cache[event_idx]

    def add_to_source(self, source_p, start, stop):
        """Add the current chunk's events to source.p; never modify sensors."""
        # HDF5 uint64 timesteps can promote mixed integer arithmetic to float64.
        if int(start) != start or int(stop) != stop:
            raise ValueError('Pressure bump timesteps must be integers')
        start, stop = int(start), int(stop)
        if self.src_replica and self.replica_source is None:
            raise ValueError('src_replica pressure bumps need set_replica_source() first')
        for event_idx, (event_start, rows, weights) in enumerate(self.rows):
            lo = max(start, event_start)
            hi = min(stop, event_start + int(np.ceil(self.pulse_steps)))
            if hi <= lo:
                continue
            phase = (np.arange(lo, hi)-event_start)/self.pulse_steps
            if self.src_replica:
                segment = self._replica_segment(event_idx)
                if segment is None:
                    continue
                # Hann window over the replayed segment
                pulse = (np.sin(np.pi*phase)**2*segment[lo-event_start:hi-event_start]).astype(np.float32)
                source_p[rows, lo-start:hi-start] += weights[:, None]*pulse
                continue
            # One sine cycle under a Hann window: smooth endpoints, zero integral,
            # and unit analytic peak. Random polarity avoids systematic bias.
            pulse = (np.sin(2*np.pi*phase)*np.sin(np.pi*phase)**2/(3*np.sqrt(3)/8)).astype(np.float32)
            source_p[rows, lo-start:hi-start] += weights[:, None]*pulse


class SourceCapture:
    """Far-field sound of the sources toward one direction, computed without the solver.

    Sums every source cell's source.p with its plane-wave propagation delay toward
    `target`: what a distant listener in that direction hears, up to a constant delay
    and 1/r - thickness tones, the blade dipole's spectral tilt and the motion imprint
    as seen from there. A stationary monopole with the same total source.p radiates,
    at an equal distance, the same waveform, but without motion or directivity.
    Rows follow load_source's layout: the source bounds box in z, y, x order, x fastest.
    """
    def __init__(self, source_bounds, target, spacing, dt, sound_speed=343.0, delay_resolution=10, chunk=4096):
        spacing = np.broadcast_to(np.asarray(spacing, dtype=np.float64), (3,))
        z, y, x = np.meshgrid(*[np.arange(*source_bounds[c]) for c in 'zyx'], indexing='ij')
        cells = np.stack([x.ravel(), y.ravel(), z.ravel()], axis=1)*spacing
        center = cells.mean(axis=0)
        direction = np.asarray(target, dtype=np.float64)*spacing - center
        if not np.linalg.norm(direction) > 0:
            raise ValueError('Capture target must differ from the source center')
        direction /= np.linalg.norm(direction)
        # A cell nearer the listener is heard earlier: capture(t) = sum_v s_v(t + d_v).
        # Delays are rounded to delay_resolution steps (1 us at dt=0.1 us) to bound the work.
        steps = (cells-center) @ direction/sound_speed/dt
        delays = np.rint(steps/delay_resolution).astype(np.int64)*delay_resolution
        self.order = np.argsort(delays, kind='stable')
        self.delays, self.group_starts = np.unique(delays[self.order], return_index=True)
        self.margin = int(np.abs(delays).max())
        self.n_cells = len(cells)
        self.chunk = int(chunk)

    def segment(self, load, start, length):
        """Captured sound for solver steps [start, start+length).

        load(a, b) returns the summed source.p rows (n_cells, b-a) of all sources for
        steps [a, b). Sources are silent before step 0.
        """
        out = np.zeros(int(length), dtype=np.float64)
        first = max(0, start+int(self.delays[0]))
        last = start+length+int(self.delays[-1])
        for a in range(first, last, self.chunk):
            b = min(a+self.chunk, last)
            rows = np.asarray(load(a, b), dtype=np.float32)
            if rows.shape != (self.n_cells, b-a):
                raise ValueError('Source rows do not match the capture geometry')
            grouped = np.add.reduceat(rows[self.order], self.group_starts, axis=0)
            for delay, signal in zip(self.delays, grouped):
                # Source step u contributes to capture step u - delay
                t0, t1 = max(a-delay, start), min(b-delay, start+length)
                if t1 > t0:
                    out[t0-start:t1-start] += signal[t0+delay-a:t1+delay-a]
        return out
