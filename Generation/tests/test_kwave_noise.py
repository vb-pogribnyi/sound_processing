"""Synthetic mesh integration only: never start the k-Wave solver."""
import ast
from pathlib import Path
import sys
import json
import logging
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'Generation/KWave/src'))
from Generation.kwave_noise import MeshNoise, decode_coordinates, _blade_model
from CircularSignal.MeshReader import MeshReader


class LinearPressure:
    config = SimpleNamespace(sample_rate=1000, n_span=10, n_chord=10)

    def __init__(self, seed=0):
        self.offset = seed % 17

    def sample(self, count, start_sample=0):
        s = (np.arange(10)+.5)/10
        c = (np.arange(10)+.5)/10
        t = np.arange(start_sample, start_sample+count)
        return self.offset+10*s[:, None, None]+c[None, :, None]+t[None, None, :]*.01


def tiny_reader(folder, data, nt=2):
    folder = Path(folder)
    meta = dict(nt=nt, dt=.001, dx=.001, dy=.001, dz=.001)
    (folder/'meta.json').write_text(json.dumps(meta))
    for i in range(data.shape[-1]//nt):
        np.savez(folder/f'{i:03}.npz', data[..., i*nt:(i+1)*nt])
    return MeshReader(folder)


class MappingTests(unittest.TestCase):
    def test_coordinates(self):
        b, s, c = decode_coordinates(np.array([100052, 907083, 1010109, 0]))
        np.testing.assert_array_equal(b, [2, 3, 9, 0])
        np.testing.assert_array_equal(s, [5, 8, 10, 0])
        np.testing.assert_array_equal(c, [1, 9, 10, 0])
        for invalid in (-1, np.nan, 100052.5, 1090000, 2000000):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                decode_coordinates([invalid])

    @patch('Generation.kwave_noise._blade_model', side_effect=lambda cfg, seed: LinearPressure(seed))
    def test_sign_coordinates_blades_and_ignored_t(self, factory):
        mapper = MeshNoise(dict(amplitude=2, noise=dict(seed=12)), dict(dt=.001))
        mesh = np.zeros((5, 1, 1, 3), dtype=np.complex64)
        mesh[0] = 255 + 100052j
        mesh[1] = -255 + 103052j  # same blade/span/chord, different transverse bin
        mesh[2] = 127.5 + 900052j  # different chord
        mesh[3] = 255 + 100053j    # different blade
        mesh[4] = complex(float('nan'), float('nan'))
        result = mapper(mesh, np.arange(10, 13))
        seed2 = int(np.random.SeedSequence([12, 2]).generate_state(1, dtype=np.uint64)[0])
        expected = seed2 % 17 + 5 + .1 + np.arange(10, 13)*.01
        np.testing.assert_allclose(result[0, 0, 0], expected, rtol=1e-6)
        np.testing.assert_array_equal(result[1], -result[0])
        np.testing.assert_allclose(result[2, 0, 0], (expected+.8)/2, rtol=1e-6)
        self.assertFalse(np.array_equal(result[3], result[0]))
        np.testing.assert_array_equal(result[4], 0)
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(result.dtype, np.float32)
        self.assertEqual(mesh[0, 0, 0, 0], 255+100052j)

    def test_pressure_before_interpolation(self):
        with tempfile.TemporaryDirectory() as folder:
            data = np.array([255+100052j, -255+900053j], dtype=np.complex64).reshape(1, 1, 1, 2)
            reader = tiny_reader(folder, data)
            calls = []
            def pressure(mesh, steps):
                calls.append(steps.copy())
                return mesh.real/255 * np.where(mesh.imag % 10 == 2, 2, 4)
            sampled = reader.sample(.5, 1, 2, transform=pressure)
            # Opposite weights cancel geometrically, but pressures from two
            # different blades must not disappear or inherit a blended label.
            np.testing.assert_array_equal(sampled, -1)
            for times in calls:
                np.testing.assert_array_equal(times, [1])
            raw = reader.sample(.5, 1, 2)
            self.assertIn(raw.imag.item(), [100052, 900053])

    def test_playback_wrap_fast_slow_and_chunk_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            data = np.array([1+0j, 2+100052j, 3+900053j, 4+500074j], dtype=np.complex64).reshape(1, 1, 1, 4)
            reader = tiny_reader(folder, data)
            for speed in (.25, .8, 1., 1.4, 2.5):
                def transform(mesh, steps):
                    decode_coordinates(mesh.imag)
                    return mesh.real + steps*.1
                whole = reader.sample(speed, 3, 140, transform=transform)
                joined = np.concatenate([reader.sample(speed, 3, 77, transform=transform),
                                         reader.sample(speed, 77, 140, transform=transform)], axis=-1)
                np.testing.assert_array_equal(whole, joined)
                positions = np.arange(3, 140)*speed
                lo = np.floor(positions).astype(int)
                alpha = positions-lo
                expected = (lo % 4+1)*(1-alpha)+((lo+1) % 4+1)*alpha+np.arange(3, 140)*.1
                np.testing.assert_allclose(whole.reshape(-1), expected, rtol=1e-6)

    def test_actual_noise_chunk_continuity_and_gain(self):
        cfg = dict(type='synthetic', amplitude=1, phase=.02,
                   noise=dict(seed=7, n_span=2, n_chord=3, model_frequencies=12,
                              gust_modes=8, block_samples=256, sample_rate=8000,
                              f_min=100, f_max=2000, flow_speed=50, chord=.05))
        mesh = np.full((2, 1, 1, 140), 255+100052j, dtype=np.complex64)
        mesh[1] = -255+103052j
        meta = dict(dt=1e-5, dx=.001, dy=.001, dz=.001)
        mapper = MeshNoise(cfg, meta)
        full = mapper(mesh, np.arange(140))
        halves = np.concatenate([mapper(mesh[..., :71], np.arange(71)),
                                 mapper(mesh[..., 71:], np.arange(71, 140))], axis=-1)
        np.testing.assert_array_equal(full, halves)
        np.testing.assert_array_equal(full[0], -full[1])
        restarted = MeshNoise(cfg, meta)(mesh, np.arange(140))
        np.testing.assert_array_equal(full, restarted)
        doubled = MeshNoise(dict(cfg, amplitude=2), meta)(mesh, np.arange(140))
        np.testing.assert_array_equal(doubled, full*2)
        self.assertTrue(np.all(np.isfinite(full)))
        self.assertTrue(np.any(full != 0))

    @patch('Generation.kwave_noise._blade_model', side_effect=lambda cfg, seed: LinearPressure(seed))
    def test_load_source_layout_and_bounds(self, factory):
        # Compile only load_source, never import runner or launch its workers.
        path = ROOT/'Generation/KWave/src/run_experiments.py'
        function = next(n for n in ast.parse(path.read_text()).body
                        if isinstance(n, ast.FunctionDef) and n.name == 'load_source')
        scope = dict(Path=Path, sys=sys, np=np, __file__=str(path))
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), scope)
        with tempfile.TemporaryDirectory() as folder:
            data = np.full((2, 1, 1, 2), 255+100052j, dtype=np.complex64)
            data[1] = -255+100052j
            reader = tiny_reader(folder, data)
            cfg = dict(type='test', x=12, y=22, z=31, speed=1, amplitude=1, noise=dict(seed=1))
            bounds = dict(x=(10, 14), y=(20, 24), z=(30, 32))
            result = scope['load_source'](cfg, 0, 2, reader, bounds, logging.getLogger())
            self.assertEqual(result.shape, (32, 2))
            array = result.reshape(2, 4, 4, 2)  # z, y, x, time
            np.testing.assert_array_equal(array[1, 2, 2], -array[1, 2, 3])
            self.assertEqual(np.count_nonzero(array[..., 0]), 2)
            with self.assertRaises(ValueError):
                scope['load_source'](dict(cfg, x=13), 0, 2, reader, bounds, None)


if __name__ == '__main__':
    unittest.main()
