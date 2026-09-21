"""Standalone source tests. Never import the k-Wave runner or mesh readers."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import wave
import struct
import unittest
import warnings

import numpy as np
from scipy.integrate import quad
from scipy.io import wavfile
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Generation.noise import BladeConfig, BladeNoise, write_wav_preview
from Generation.Amiet.bpm import trailing_edge_psd, tip_psd
from Generation.Amiet.airfoil_noise import AmT


class NoiseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = BladeConfig(n_span=3, n_chord=5, model_frequencies=48,
                              gust_modes=24, block_samples=1024,
                              sample_rate=8000, f_min=100, f_max=3000,
                              flow_speed=50, chord=.05, seed=24)
        cls.model = BladeNoise(cls.cfg)

    def test_fresnel_against_independent_quadrature(self):
        z = np.array([0., 1e-7, .1, 1., 10., 100.])
        # Smooth variable substitution avoids the integrable singularity.
        reference = np.array([2/np.sqrt(2*np.pi)*(
            quad(lambda s: np.cos(s*s), 0, np.sqrt(v), epsabs=1e-11)[0]
            + 1j*quad(lambda s: np.sin(s*s), 0, np.sqrt(v), epsabs=1e-11)[0]) for v in z])
        np.testing.assert_allclose(AmT.fr_int(z), reference, atol=2e-12)
        np.testing.assert_allclose(AmT.fr_int_cc(z), reference.conj(), atol=2e-12)
        self.assertEqual(AmT.fr_int(0.), 0.)
        np.testing.assert_allclose(AmT.fr_int(z.reshape(2, 3)), reference.reshape(2, 3), atol=2e-12)

    def test_chunk_identity_restart_and_no_loop(self):
        m = self.model
        full = m.sample(3100)
        pieces = np.concatenate([m.sample(713), m.sample(1001, 713), m.sample(1386, 1714)], axis=-1)
        np.testing.assert_array_equal(full, pieces)
        m._block.cache_clear()
        np.testing.assert_array_equal(full[..., 1714:], m.sample(1386, 1714))
        self.assertFalse(np.array_equal(full[..., :1024], full[..., 1024:2048]))
        self.assertEqual(full.shape, (3, 5, 3100))
        self.assertEqual(full.dtype, np.float32)
        self.assertTrue(np.all(np.isfinite(full)))

    def test_one_sided_psd_energy(self):
        m = self.model
        parts = m.sample_components(32000)
        df = m.config.sample_rate/m.config.block_samples
        for name, values in parts.items():
            expected = np.sum(m.target_psd(name), axis=0)*df
            ratio = np.mean(values.astype(float)**2)/np.mean(expected)
            with self.subTest(component=name):
                self.assertTrue(.8 < ratio < 1.2, (name, ratio))
                self.assertLess(abs(values.mean()), np.sqrt(np.mean(values**2))*.05)

    def test_force_conservation_and_bpm_reference(self):
        m, c = self.model, self.cfg
        for name in ('trailing_edge', 'tip'):
            h = m._factors[name]
            force_factor = np.einsum('fsck,sc->fk', h, m.cell_area)
            measured = np.sum(abs(force_factor)**2, axis=-1)
            if name == 'tip':
                reference, _ = tip_psd(m.model_frequency, speed=50, chord=.05,
                                      alpha_deg=c.angle_of_attack)
            else:
                reference = sum(trailing_edge_psd(
                    m.model_frequency, speed=50, chord=.05, span=c.span/c.n_span,
                    alpha_deg=c.angle_of_attack, delta_pressure=m.delta_pressure[j],
                    delta_suction=m.delta_suction[j]) for j in range(c.n_span))
            target = reference*(4*np.pi*c.sound_speed/(2*np.pi*m.model_frequency))**2
            np.testing.assert_allclose(measured, target, rtol=1e-12)

    def test_le_intensity_scaling_and_component_independence(self):
        a = self.model.sample_components(300)
        m = BladeNoise(replace(self.cfg, turbulence_intensity=.05, tip=False))
        b = m.sample_components(300)
        np.testing.assert_allclose(b['leading_edge'], 2*a['leading_edge'], rtol=1e-6)
        np.testing.assert_array_equal(b['trailing_edge'], a['trailing_edge'])
        np.testing.assert_array_equal(b['tip'], 0)
        silent = BladeNoise(replace(self.cfg, leading_edge=False, trailing_edge=False, tip=False))
        np.testing.assert_array_equal(silent.sample(300), 0)

    def test_tip_geometry_and_spatial_localization(self):
        f = np.array([500., 1000., 3000.])
        rounded, lr = tip_psd(f, speed=50, chord=.05, alpha_deg=4)
        square, ls = tip_psd(f, speed=50, chord=.05, alpha_deg=4, shape='square')
        self.assertGreater(ls, lr)
        self.assertFalse(np.allclose(rounded, square, rtol=1e-6, atol=0))
        zero, _ = tip_psd(f, speed=50, chord=.05, alpha_deg=0)
        np.testing.assert_array_equal(zero, 0)
        variance = self.model.target_psd('tip').sum(axis=0)
        self.assertGreater(variance[-1, -1], variance[0, -1]*10)
        self.assertGreater(variance[-1, -1], variance[-1, 0]*10)

    def test_wav_five_seconds_and_same_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'preview.wav'
            info = write_wav_preview(self.model, path)
            fs, audio = wavfile.read(path)
            self.assertEqual(fs, 48000)
            self.assertEqual(audio.shape, (5*fs,))
            with wave.open(str(path), 'rb') as reader:
                self.assertEqual(reader.getparams()[:4], (1, 2, 48000, 240000))
                self.assertEqual(len(reader.readframes(reader.getnframes())), 480000)
            raw = path.read_bytes()
            self.assertEqual(raw[:4], b'RIFF')
            self.assertEqual(raw[8:12], b'WAVE')
            self.assertEqual(struct.unpack_from('<I', raw, 4)[0], len(raw)-8)
            self.assertEqual(struct.unpack_from('<HH', raw, 20), (1, 1))
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])
            self.assertEqual(audio.dtype, np.int16)
            self.assertLessEqual(np.max(abs(audio.astype(float))), 32767*10**(-1/20)+1)
            p = self.model.sample(300)
            expected = np.einsum('ij,ijt->t', self.model.cell_area/self.model.cell_area.sum(), p)
            expected = resample_poly(expected, 6, 1)[:1200]
            recovered = audio[:1200].astype(float)/32767/info['gain_per_pa']
            np.testing.assert_allclose(recovered, expected, atol=1/32767/info['gain_per_pa'])
            self.assertFalse(np.array_equal(audio[:fs], audio[fs:2*fs]))

    def test_profiles_and_invalid_inputs(self):
        m = BladeNoise(replace(self.cfg, flow_speed=[40, 50, 60], chord=[.05, .04, .03],
                              angle_of_attack=[-3, 4, 5], leading_edge=False,
                              delta_pressure=.0005, delta_suction=[.001, .0012, .0014]))
        self.assertTrue(np.all(np.isfinite(m.sample(10))))
        for changes in (dict(flow_speed=400), dict(chord=0), dict(n_span=2.5),
                        dict(f_max=4000), dict(flow_speed=[1, 2]), dict(seed=-1),
                        dict(tip_shape='invalid'), dict(block_samples=101),
                        dict(turbulence_intensity=-.1), dict(delta_suction=0)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                BladeNoise(replace(self.cfg, **changes))


if __name__ == '__main__':
    unittest.main()
