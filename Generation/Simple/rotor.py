"""Analytic free-field sound of rotating blades: broadband (amiet) loading and thickness.

Each blade is n_span compact elements at radii (i+.5)/n_span*span, rotating about +z
through `center`. Blade i points along +y (start_angle 90 deg) at t=0 plus i*360/n_blades,
turning counter-clockwise - the same geometry CircularSignal/SourceDrawer draws for KWave.

  * Loading: the broadband pressure jump of noise.py (BladeNoise) integrated over chord
    is each element's force along +z (the blade normal, like KWave's +/- lobes).
  * Thickness: each element's share of the blade volume, as a compact moving volume.

Both use exact retarded times, compact Farassat formulation 1:
    4 pi p_L = (1/c) d/dt [F_r / (r (1-M_r))] + F_r / (r^2 (1-M_r))
    4 pi p_T = rho0 d^2/dt^2 [V / (r (1-M_r))]
Observer-time derivatives are taken by a small emission-time stencil, d/dt = d/dtau / (1-M_r).
Sources start at t=0 under a short fade-in; nothing is radiated before that.
"""
import numpy as np
from scipy.signal import resample_poly, butter, sosfiltfilt


class Rotor:
    def __init__(self, center, rpm, n_blades, span, n_span, sound_speed=343.0, density=1.225,
                 start_angle_deg=90.0, fade_s=0.005):
        self.center = np.asarray(center, dtype=np.float64)
        self.omega = 2*np.pi*float(rpm)/60
        self.n_blades, self.n_span = int(n_blades), int(n_span)
        self.radii = np.tile((np.arange(self.n_span)+.5)/self.n_span*float(span), self.n_blades)
        blade = np.repeat(np.arange(self.n_blades), self.n_span)
        self.phases = np.radians(start_angle_deg) + 2*np.pi*blade/self.n_blades
        self.c, self.rho = float(sound_speed), float(density)
        self.fade_s = float(fade_s)
        if not self.c > 0 or self.radii.max()*abs(self.omega) >= self.c:
            raise ValueError('Rotor must be subsonic')

    @property
    def n_elements(self):
        return len(self.radii)

    def fade(self, tau):
        if self.fade_s <= 0:
            return (tau >= 0).astype(np.float64)
        x = np.clip(tau/self.fade_s, 0, 1)
        return .5*(1-np.cos(np.pi*x))

    def trig(self, tau):
        phi = self.phases[:, None] + self.omega*tau
        return np.cos(phi), np.sin(phi)

    def shifted(self, trig, shift):
        """Element angles' cos/sin at tau+shift, from those at tau (angle addition, no trigonometry)."""
        cos_phi, sin_phi = trig
        c, s = np.cos(self.omega*shift), np.sin(self.omega*shift)
        return cos_phi*c - sin_phi*s, sin_phi*c + cos_phi*s

    def geometry(self, observer, tau, trig=None):
        """r (observer distance), M_r and r_z/r for elements at emission times tau (..., E, N)."""
        cos_phi, sin_phi = self.trig(tau) if trig is None else trig
        radius = self.radii[:, None]
        dx = observer[..., 0, None, None] - (self.center[0] + radius*cos_phi)
        dy = observer[..., 1, None, None] - (self.center[1] + radius*sin_phi)
        dz = observer[..., 2, None, None] - self.center[2]
        r = np.sqrt(dx*dx + dy*dy + dz*dz)
        # Velocity omega x position: radius*omega*(-sin, cos, 0)
        m_r = radius*self.omega*(-sin_phi*dx + cos_phi*dy)/(r*self.c)
        return r, m_r, dz/r

    def retarded(self, observer, t, iterations=4):
        """Emission times tau(t) for every element, solving t = tau + r(tau)/c by Newton's method."""
        tau = np.broadcast_to(t - np.linalg.norm(observer - self.center, axis=-1)[..., None, None]/self.c,
                              observer.shape[:-1] + (self.n_elements, len(t))).copy()
        for _ in range(iterations):
            r, m_r, _ = self.geometry(observer, tau)
            tau -= (tau + r/self.c - t)/(1 - m_r)    # d/dtau (tau + r/c) = 1 - M_r
        return tau


class BroadbandForce:
    """Per-element axial force [N] from noise.py, upsampled for interpolation at retarded times."""
    def __init__(self, models, amplitude, duration, upsample=8):
        forces = []
        self.rate = None
        for model in models:
            c = model.config
            count = int(np.ceil(duration*c.sample_rate)) + 4
            jump = model.sample(count).astype(np.float64)                  # [span, chord, time], Pa
            area = np.asarray(model.chord, dtype=np.float64)/c.n_chord*(c.span/c.n_span)
            forces.append(amplitude*np.einsum('sct,s->st', jump, area))   # integrate over chord
            rate = c.sample_rate*upsample
            if self.rate not in (None, rate):
                raise ValueError('All blade models need the same sample rate')
            self.rate = rate
        self.force = resample_poly(np.concatenate(forces), upsample, 1, axis=-1)   # (E, samples)

    def __call__(self, tau):
        """Linear interpolation at emission times tau (..., E, N); zero outside the synthesized range."""
        position = tau*self.rate
        lo = np.floor(position).astype(np.int64)
        alpha = position - lo
        valid = (lo >= 0) & (lo < self.force.shape[1]-1)
        lo = np.where(valid, lo, 0)
        element = np.arange(self.force.shape[0])[:, None]
        value = self.force[element, lo]*(1-alpha) + self.force[element, lo+1]*alpha
        return np.where(valid, value, 0.0)


def rotor_pressure(rotor, observers, t, force=None, volume_per_element=0.0, thickness_f_max=None,
                   fs=None, chunk=32, stencil_s=2e-6):
    """Pressure [Pa] at observers (R, 3) [m] for observer times t (N,) [s].

    Returns (loading, thickness), each (R, N). force: BroadbandForce or None (no loading);
    volume_per_element: compact volume [m^3] per element, 0 disables thickness.
    """
    observers = np.asarray(observers, dtype=np.float64)
    t = np.asarray(t, dtype=np.float64)
    loading = np.zeros((len(observers), len(t)))
    thickness = np.zeros((len(observers), len(t)))
    if force is None and volume_per_element == 0:
        return loading, thickness
    h = float(stencil_s)
    for lo in range(0, len(observers), chunk):
        obs = observers[lo:lo+chunk]
        tau = rotor.retarded(obs, t)
        trig = rotor.trig(tau)
        r, m_r, cos_z = rotor.geometry(obs, tau, trig)
        doppler = 1 - m_r
        # Stencil points tau + k*h share one trigonometric evaluation
        stencil = {}
        def at(k):
            if k not in stencil:
                stencil[k] = rotor.geometry(obs, tau, rotor.shifted(trig, k*h))
            return stencil[k]
        if force is not None:
            def a(k):
                rs, ms, cz = at(k)
                return force(tau+k*h)*rotor.fade(tau+k*h)*cz/(rs*(1-ms))
            da_dt = (a(1) - a(-1))/(2*h)/doppler
            f_r = force(tau)*rotor.fade(tau)*cos_z
            loading[lo:lo+chunk] = ((da_dt/rotor.c + f_r/(r*r*doppler))/(4*np.pi)).sum(axis=-2)
        if volume_per_element:
            def g(k):
                rs, ms, _ = at(k)
                return volume_per_element*rotor.fade(tau+k*h)/(rs*(1-ms))
            g_0 = volume_per_element*rotor.fade(tau)/(r*doppler)
            # d/dt = d/dtau / (1 - M_r), applied twice
            q_p = (g(2) - g_0)/(2*h)/(1-at(1)[1])
            q_m = (g_0 - g(-2))/(2*h)/(1-at(-1)[1])
            d2g = (q_p - q_m)/(2*h)/doppler
            thickness[lo:lo+chunk] = (rotor.rho*d2g/(4*np.pi)).sum(axis=-2)
    if thickness_f_max is not None and fs is not None and thickness_f_max < .5*fs and volume_per_element:
        thickness = sosfiltfilt(butter(4, thickness_f_max, fs=fs, output='sos'), thickness, axis=-1)
    return loading, thickness
