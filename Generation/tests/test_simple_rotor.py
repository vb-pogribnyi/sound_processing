"""Physics checks of Generation/Simple/rotor.py against independent references."""
from pathlib import Path
import os
import sys
import unittest

import numpy as np
from scipy.signal import hilbert

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from Generation.Simple.rotor import Rotor, rotor_pressure


class Tone:
    """Force callable: same tone on every element (tau may be any shape)."""
    def __init__(self, frequency, amplitude=1.0):
        self.f, self.a = frequency, amplitude

    def __call__(self, tau):
        return np.where(tau >= 0, self.a*np.sin(2*np.pi*self.f*tau), 0.0)


def fine_observer_derivative(rotor, observer, quantity, t_fine):
    """Brute force: evaluate quantity(r, M_r, cos_z, tau) on a fine observer grid, d/dt by np.gradient."""
    tau = rotor.retarded(observer[None], t_fine)
    r, m_r, cos_z = rotor.geometry(observer[None], tau)
    values = quantity(r, m_r, cos_z, tau)
    return tau, r, m_r, values


class SimpleRotorTests(unittest.TestCase):
    def test_static_dipole(self):
        rotor = Rotor((0, 0, 0), rpm=0, n_blades=1, span=.02, n_span=1, fade_s=0)
        observer = np.array([[.3, .4, 1.2]])
        f = 900.
        t = np.arange(.01, .03, 1/16000)
        loading, thickness = rotor_pressure(rotor, observer, t, force=Tone(f))
        np.testing.assert_array_equal(thickness, 0)
        source = np.array([rotor.radii[0]*np.cos(rotor.phases[0]), rotor.radii[0]*np.sin(rotor.phases[0]), 0])
        d = observer[0]-source
        r = np.linalg.norm(d)
        cos_z = d[2]/r
        te = t-r/343.
        expected = cos_z/(4*np.pi)*(2*np.pi*f*np.cos(2*np.pi*f*te)/(343.*r) + np.sin(2*np.pi*f*te)/r**2)
        np.testing.assert_allclose(loading[0], expected, rtol=1e-4, atol=1e-6*abs(expected).max())

    def test_doppler_of_rotating_tone(self):
        rpm, span = 6000., .1
        rotor = Rotor((0, 0, 0), rpm=rpm, n_blades=1, span=span*2, n_span=2, fade_s=0)
        # keep only the outer element: tip at radius .15 m
        rotor.radii, rotor.phases = rotor.radii[1:], rotor.phases[1:]
        # Far away, just off the rotor plane (a z-force radiates nothing exactly in-plane)
        observer = np.array([[20., 0, 2.]])
        fs, f0 = 96000., 3000.
        t = np.arange(.07, .07+4*60/rpm, 1/fs)
        loading, _ = rotor_pressure(rotor, observer, t, force=Tone(f0))
        inst = np.diff(np.unwrap(np.angle(hilbert(loading[0]))))*fs/(2*np.pi)
        inst = inst[200:-200]
        mach = rotor.radii[0]*rotor.omega/343.*20/np.hypot(20, 2)   # in-plane component towards observer
        self.assertAlmostEqual(inst.max(), f0/(1-mach), delta=.01*f0)
        self.assertAlmostEqual(inst.min(), f0/(1+mach), delta=.01*f0)

    def test_loading_and_thickness_match_brute_force(self):
        rotor = Rotor((.1, -.2, .05), rpm=5000, n_blades=2, span=.12, n_span=3, fade_s=.002)
        observer = np.array([.9, .5, .7])
        volume = 2e-6
        force = Tone(1500., 3.)
        t = np.arange(.012, .03, 1/16000)
        loading, thickness = rotor_pressure(rotor, observer[None], t, force=force, volume_per_element=volume)
        t_fine = np.arange(.0115, .0305, 1/4e6)
        tau, r, m_r, a = fine_observer_derivative(
            rotor, observer, lambda r, m, cz, tau: force(tau)*rotor.fade(tau)*cz/(r*(1-m)), t_fine)
        cos_z = rotor.geometry(observer[None], tau)[2]
        p_l = (np.gradient(a, t_fine, axis=-1)/343. + force(tau)*rotor.fade(tau)*cos_z/(r*r*(1-m_r)))/(4*np.pi)
        g = volume*rotor.fade(tau)/(r*(1-m_r))
        p_t = 1.225*np.gradient(np.gradient(g, t_fine, axis=-1), t_fine, axis=-1)/(4*np.pi)
        idx = np.rint((t-t_fine[0])*4e6).astype(int)
        for name, ours, reference in (('loading', loading[0], p_l.sum(axis=1)[0][idx]),
                                      ('thickness', thickness[0], p_t.sum(axis=1)[0][idx])):
            with self.subTest(part=name):
                self.assertTrue(np.any(reference != 0))
                np.testing.assert_allclose(ours, reference, rtol=0, atol=2e-3*abs(reference).max())

    def test_retarded_time_solves_emission_equation(self):
        # Fast rotor (tip Mach ~0.45) close to the observers: hardest case for the solver
        rotor = Rotor((0, 0, 0), rpm=15000, n_blades=3, span=.1, n_span=4, fade_s=0)
        observers = np.array([[.3, .1, .05], [2., -1., 1.], [.05, .2, -.1]])
        t = np.linspace(.01, .05, 2000)
        tau = rotor.retarded(observers, t)
        r, _, _ = rotor.geometry(observers, tau)
        np.testing.assert_allclose(tau + r/343., np.broadcast_to(t, tau.shape), rtol=0, atol=1e-12)
        # Angle-addition shift equals direct evaluation
        for got, want in zip(rotor.shifted(rotor.trig(tau), 3e-6), rotor.trig(tau+3e-6)):
            np.testing.assert_allclose(got, want, rtol=0, atol=1e-12)

    def test_stationary_rotor_has_no_thickness_noise(self):
        rotor = Rotor((0, 0, 0), rpm=0, n_blades=2, span=.1, n_span=4, fade_s=0)
        t = np.arange(.01, .02, 1/16000)
        _, thickness = rotor_pressure(rotor, np.array([[1., 1., 1.]]), t, volume_per_element=1e-6)
        np.testing.assert_allclose(thickness, 0, atol=1e-12)


class SimpleExportTests(unittest.TestCase):
    def test_export_layout_and_signals(self):
        import json, pickle, tempfile, yaml
        sys.path.insert(0, str(ROOT/'Generation/KWave/src'))
        import exporter
        from Generation.Simple import simulate
        source_type = 'airfoil/1e-07/2/0.008'
        descr = dict(sampling=16000, time=.004, source_mode='both',
                     export=dict(x_start=0, x_end=60, y_start=40, y_end=70, z_start=20, z_end=50),
                     mesh=dict(size_x=64, size_y=72, size_z=56, dx=.008, dy=.008, dz=.008, dt=1e-7),
                     sources=[dict(type=source_type, speed=1.1, x=10, y=5, z=2, amplitude=.2,
                                   noise=dict(block_samples=256), thickness=dict(volume_per_blade_m3=1e-5))])
        root = exporter.EXPERIMENTS_ROOT
        with tempfile.TemporaryDirectory() as folder:
            try:
                exporter.EXPERIMENTS_ROOT = folder
                os.makedirs(os.path.join(folder, 'exp'))
                os.makedirs(os.path.join(folder, 'input_mesh', source_type))
                yaml.safe_dump(descr, open(os.path.join(folder, 'exp', 'experiment.yml'), 'w'))
                json.dump(dict(nx=38, ny=38, nz=5, dx=.008, dy=.008, dz=.008, dt=1e-7), open(os.path.join(folder, 'input_mesh', source_type, 'meta.json'), 'w'))
                exporter.export('exp', simulate.MICS, simulate.SENSORS_DIRECTION, 30, [20, 10, 10], None,
                                num_examples=6, export_dir='export_simple', signal_source=simulate.simple_signal_source())
                out = os.path.join(folder, 'exp', 'export_simple')
                result = pickle.load(open(os.path.join(out, 'exported.pkl'), 'rb'))
                steps = sorted(os.listdir(os.path.join(out, 'compiled_values')))
                t, fs = simulate.output_times(descr)
                self.assertEqual(len(steps), len(t))
                self.assertEqual(len(t), 64)          # 40000 solver steps of 1e-7 s, one output every 625
                keys = [(p, r) for p in result for r in result[p]]
                self.assertEqual(len(keys), 6)
                snapshot = result[keys[0][0]][keys[0][1]]
                self.assertEqual(set(snapshot), {'sensor_direction_zx', 'sensor_direction_zy', 'sensor_direction_xz',
                                                 'sensor_direction_xy', 'mic_positions', 'mic_values',
                                                 'source_relative', 'sources'})
                series = np.array([[pickle.load(open(os.path.join(out, 'compiled_values', s), 'rb'))[keys[0][0]][keys[0][1]]['mic_values']
                                    for s in steps]]).squeeze(0).T
                mics = np.array(snapshot['mic_positions'], dtype=float)*.008
                expected = simulate.simulate_observers(yaml.safe_load(open(os.path.join(folder, 'exp', 'experiment.yml'))),
                                                       mics, progress=False)
                self.assertEqual(series.shape, (7, 64))
                np.testing.assert_allclose(series, expected, rtol=1e-5, atol=1e-6*abs(expected).max())
                self.assertTrue(np.any(series != 0))
            finally:
                exporter.EXPERIMENTS_ROOT = root


if __name__ == '__main__':
    unittest.main()
