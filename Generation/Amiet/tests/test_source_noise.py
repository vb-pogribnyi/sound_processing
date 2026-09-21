"""Small tests; never import or execute the k-Wave experiment runner."""
import ast
import json
import logging
from pathlib import Path
import sys
import tempfile
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

    def test_signed_mesh_and_layout(self):
        # Extract only the function definition. No runner imports, workers,
        # real mesh reads, or simulation code are executed.
        path = GENERATION / 'KWave/src/run_experiments.py'
        tree = ast.parse(path.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == 'load_source')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'test'
            folder.mkdir()
            (folder / 'meta.json').write_text(json.dumps(dict(dt=1e-5)))
            import os
            scope = dict(np=np, Path=Path, sys=sys, json=json, os=os,
                         __file__=str(path), mesh_basedir=tmp)
            exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), scope)
            mesh = np.zeros((2, 1, 2, 128), dtype=complex)
            mesh[0, 0, 0] = 255 + 1j
            mesh[1, 0, 0] = -255 + 2j
            mesh[0, 0, 1] = 127.5
            class Reader:
                def sample(self, *args):
                    return mesh
            result = scope['load_source'](
                dict(self.cfg, speed=1), 0, 128, Reader(),
                dict(x=(0, 2), y=(0, 1), z=(0, 2)), logging.getLogger())
            self.assertEqual(result.shape, (4, 128))
            self.assertEqual(result.dtype, np.float32)
            np.testing.assert_array_equal(result[0], -result[1])
            np.testing.assert_array_equal(result[2], result[0]/2)
            np.testing.assert_array_equal(result[3], 0)
            self.assertTrue(np.any(result[0]))
            self.assertEqual(mesh[0, 0, 0, 0], 255+1j)


if __name__ == '__main__':
    unittest.main()
