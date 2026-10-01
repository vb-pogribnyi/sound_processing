"""Physics and streaming checks for the standalone observer preview."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Generation.noise import BladeConfig, BladeNoise, write_wav_preview
from Generation.rotor_noise import RotorConfig, RotorNoise


class RotorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blade = BladeNoise(BladeConfig(n_span=3, n_chord=4, sample_rate=8000,
            f_min=80, f_max=3000, block_samples=512, leading_edge=False,
            trailing_edge=False, tip=True, flow_speed=50, chord=.035))
        cls.config = RotorConfig(rpm=3600, thrust_n=2., torque_nm=.01,
                                 observer_m=(1., 0., 1.))
        cls.model = RotorNoise(cls.blade, cls.config)

    def test_bpf_and_absolute_sample_continuity(self):
        m = self.model
        self.assertEqual(m.bpf, 120)
        parts = m.sample_components(2100)
        for key, full in parts.items():
            joined = np.concatenate([m.sample_components(703)[key],
                                     m.sample_components(1397, 703)[key]])
            np.testing.assert_allclose(full, joined, atol=1e-14, rtol=1e-11)
            self.assertTrue(np.isfinite(full).all())
        tones = m.sample_tones(8000)
        for name, signal in tones.items():
            power = abs(np.fft.rfft(signal))**2
            self.assertEqual(np.argmax(power), 120, name)
            off = np.ones(len(power), dtype=bool)
            off[np.arange(120, len(power), 120)] = False
            self.assertLess(power[off].sum(), power.sum()*1e-20)
        self.assertNotEqual(m.models[0].config.seed, m.models[1].config.seed)
        self.assertEqual(self.blade.config.seed, 0)

    def test_rpm_blade_count_and_far_field_spreading(self):
        for changes, expected in ((dict(rpm=7200), 240), (dict(blades=3), 180)):
            model = RotorNoise(self.blade, replace(self.config, **changes))
            loading = model.sample_tones(8000)['loading']
            self.assertEqual(np.argmax(abs(np.fft.rfft(loading))), expected)
        # Use the asymptotic far field: axial and torque radiation can
        # partly cancel, leaving appreciable near-field pressure even at 10 m.
        near = RotorNoise(self.blade, replace(self.config, observer_m=(100., 0., 100.)))
        far = RotorNoise(self.blade, replace(self.config, observer_m=(200., 0., 200.)))
        for name in ('loading', 'thickness'):
            ratio = abs(near.coefficients[name][0])/abs(far.coefficients[name][0])
            self.assertAlmostEqual(ratio, 2., delta=.02)

    def test_force_and_volume_scaling_and_switches(self):
        doubled = RotorNoise(self.blade, replace(self.config,
            thrust_n=4., torque_nm=.02, thickness_ratio=.24))
        for name in ('loading', 'thickness'):
            np.testing.assert_allclose(doubled.coefficients[name],
                                       2*self.model.coefficients[name], rtol=1e-8, atol=1e-13)
        zero = RotorNoise(self.blade, replace(self.config,
            thrust_n=0., torque_nm=0., thickness_ratio=0., broadband=False))
        for values in zero.sample_components(50).values():
            np.testing.assert_array_equal(values, 0.)
        disabled = RotorNoise(self.blade, replace(self.config, loading=False, thickness=False))
        for values in disabled.sample_tones(10).values():
            np.testing.assert_array_equal(values, 0.)

    def test_axisymmetry_and_azimuth_quadrature_convergence(self):
        axial = RotorNoise(self.blade, replace(self.config, observer_m=(0., 0., 2.)))
        for name in ('loading', 'thickness'):
            self.assertLess(np.max(abs(axial.coefficients[name])), 1e-10)
        fine = RotorNoise(self.blade, replace(self.config, azimuth_samples=4096))
        for name in ('loading', 'thickness'):
            np.testing.assert_allclose(fine.coefficients[name][:4],
                                       self.model.coefficients[name][:4], rtol=1e-5, atol=1e-12)

    def test_loading_against_independent_green_function_gradient(self):
        # p = -div_x sum F(tau)/[4*pi*R*(1-Mr)]. This finite-difference
        # reference tests the analytic loading formula without copying it.
        m = self.model
        times = np.arange(101)/m.fs
        exact = sum(m._force_pressure(m._geometry(times, blade),
                    m.lift[:, None], 0., m.drag[:, None])
                    for blade in range(m.config.blades))
        reference = np.zeros(len(times))
        original = m.observer.copy()
        eps = 1e-5
        try:
            for axis in range(3):
                values = []
                for sign in (-1, 1):
                    m.observer = original.copy()
                    m.observer[axis] += sign*eps
                    potential = np.zeros(len(times))
                    for blade in range(m.config.blades):
                        g = m._geometry(times, blade)
                        force = (m.drag[:, None]*g[11], -m.drag[:, None]*g[10], m.lift[:, None])[axis]
                        potential += np.sum(force/(g[1]*(1-g[9])), axis=0)/(4*np.pi)
                    values.append(potential)
                reference -= (values[1]-values[0])/(2*eps)
        finally:
            m.observer = original
        np.testing.assert_allclose(exact, reference, rtol=1e-5, atol=1e-10)

    def test_wav_mix_metadata_and_raw_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'rotor.wav'
            info = write_wav_preview(self.blade, path, duration=.2,
                                     output_rate=8000, rotor=self.config)
            rate, pcm = wavfile.read(path)
            self.assertEqual(rate, 8000)
            self.assertEqual(len(pcm), 1600)
            self.assertEqual(info['rotor']['bpf_hz'], 120)
            with np.load(Path(tmp)/'rotor_components.npz') as archive:
                total = archive['loading']+archive['thickness']+archive['broadband']
                np.testing.assert_array_equal(total, archive['total'])
                recovered = pcm.astype(float)/32767/info['gain_per_pa']
                np.testing.assert_allclose(recovered, total, atol=1/32767/info['gain_per_pa'])
                for name in ('loading', 'thickness', 'broadband'):
                    self.assertGreater(np.sqrt(np.mean(archive[name]**2)), 0.)
                    _, stem = wavfile.read(Path(tmp)/f'rotor_{name}.wav')
                    np.testing.assert_allclose(stem.astype(float)/32767/info['gain_per_pa'],
                                               archive[name], atol=1/32767/info['gain_per_pa'])

    def test_invalid_geometry(self):
        for changes in (dict(rpm=0), dict(blades=0), dict(thickness_ratio=-1),
                        dict(observer_m=(0.,0.,0.)), dict(rpm=100000),
                        dict(thrust_n=float('nan')), dict(azimuth_samples=128), dict(rpm=10000)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                RotorNoise(self.blade, replace(self.config, **changes))


if __name__ == '__main__':
    unittest.main()
