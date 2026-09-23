"""Small tests; never import or execute the k-Wave experiment runner."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np

GENERATION = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(GENERATION))
from Amiet.source_noise import sample_source_noise, _noise_loop


class SourceNoiseTests(unittest.TestCase):
    cfg = dict(type='test', x=0, y=0, z=0, amplitude=2.0,
               amiet=dict(seed=42, n_freqs=8, grid_nx=8, grid_ny=9,
                          f_min=100.0, f_max=1500.0, loop_duration=0.1))

    def test_chunks_and_restart(self):
        whole = sample_source_noise(self.cfg, 1e-5, 9000, 3000)
        chunks = np.concatenate([
            sample_source_noise(self.cfg, 1e-5, 9000, 1301),
            sample_source_noise(self.cfg, 1e-5, 10301, 1699)])
        np.testing.assert_array_equal(whole, chunks)
        _noise_loop.cache_clear()
        np.testing.assert_array_equal(
            whole, sample_source_noise(self.cfg, 1e-5, 9000, 3000))

    def test_spectrum_and_level(self):
        cfg = dict(self.cfg['amiet'])
        seed = cfg.pop('seed')
        loop, fs = _noise_loop(json.dumps(cfg, sort_keys=True), 100000.0, seed)
        self.assertAlmostEqual(float(np.sqrt(np.mean(loop**2))), 1.0)
        self.assertAlmostEqual(float(loop.mean()), 0.0)
        power = abs(np.fft.rfft(loop))**2
        freq = np.fft.rfftfreq(len(loop), 1/fs)
        self.assertLess(power[(freq < 100) | (freq > 1500)].sum(), power.sum()*1e-20)
        self.assertGreater(np.count_nonzero(power > power.max()*0.001), 20)
        different = dict(self.cfg, amiet=dict(self.cfg['amiet'], seed=43))
        self.assertFalse(np.array_equal(
            sample_source_noise(self.cfg, 1e-5, 0, 1000),
            sample_source_noise(different, 1e-5, 0, 1000)))

    def test_invalid_parameters(self):
        for opts in (dict(wind_speed=400), dict(f_min=2000, f_max=1000),
                     dict(seed=-1), dict(chord=0), dict(typo=1)):
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                sample_source_noise(dict(self.cfg, amiet=opts), 1e-5, 0, 10)



if __name__ == '__main__':
    unittest.main()
