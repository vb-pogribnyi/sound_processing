"""Displacement-source tests without launching the k-Wave GPU solver."""
import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'Generation/KWave/src'))
from CircularSignal.MeshReader import MeshReader
from Generation.kwave_thickness import MeshThickness, thickness_source


def reader_for(folder, data, dt=1e-4):
    folder = Path(folder)
    nt = 16
    meta = dict(dt=dt, dx=.01, dy=.01, dz=.01, nt=nt,
                nx=data.shape[0], ny=data.shape[1], nz=data.shape[2])
    (folder/'meta.json').write_text(json.dumps(meta))
    for i in range(data.shape[-1]//nt):
        np.savez(folder/f'{i:03d}.npz', data[..., i*nt:(i+1)*nt])
    return MeshReader(folder)


def translating_volume():
    phase = 2*np.pi*np.arange(64)/64
    # One blade moves volume between two cells without changing its volume.
    w = .5+.2*np.sin(phase)
    return (255*np.stack([w, 1-w])+100050j).astype(np.complex64).reshape(2,1,1,64)


class ThicknessTests(unittest.TestCase):
    def test_analytic_displacement_rate_conservation_and_streaming(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = reader_for(tmp, translating_volume())
            m = MeshThickness(reader, 1., 1e-6, 500.)
            rate = m.sample_volume_rate(0, 137)
            expected = .2*2*np.pi/(64e-4)*np.cos(2*np.pi*np.arange(137)/64)
            np.testing.assert_allclose(rate[0,0,0], expected, atol=2e-4, rtol=3e-6)
            np.testing.assert_allclose(rate.sum(axis=(0,1,2)), 0., atol=2e-4)
            joined = np.concatenate([m.sample_volume_rate(0, 27),
                                     m.sample_volume_rate(27, 69),
                                     m.sample_volume_rate(69, 137)], axis=-1)
            np.testing.assert_array_equal(rate, joined)
            np.testing.assert_array_equal(rate[..., :64], rate[..., 64:128])
            rebuilt = MeshThickness(reader, 1., 1e-6, 500.)
            np.testing.assert_array_equal(rate, rebuilt.sample_volume_rate(0, 137))

    def test_speed_volume_scaling_and_stationary_mesh(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = reader_for(tmp, translating_volume())
            a = MeshThickness(reader, 1., 1e-6, 500.).sample_volume_rate(0,128)
            fast = MeshThickness(reader, 2., 1e-6, 1000.).sample_volume_rate(0,64)
            np.testing.assert_allclose(fast, 2*a[..., ::2], atol=1e-5)
            large = MeshThickness(reader, 1., 2e-6, 500.).sample_volume_rate(0,128)
            np.testing.assert_array_equal(large, 2*a)
            stopped = MeshThickness(reader, 0., 1e-6, 500.)
            np.testing.assert_array_equal(stopped.sample_volume_rate(0,64), 0.)
            raw = reader.sample(0., 3, 10)
            np.testing.assert_array_equal(raw, np.broadcast_to(translating_volume()[..., :1], raw.shape))
        with tempfile.TemporaryDirectory() as tmp:
            constant = np.repeat(translating_volume()[..., :1],64,axis=-1)
            m = MeshThickness(reader_for(tmp,constant),1.,1e-6,500.)
            np.testing.assert_array_equal(m.sample_volume_rate(0,64),0.)

    def test_pressure_weights_do_not_set_blade_volume(self):
        data = translating_volume()
        brightness = (1.1+.5*np.sin(2*np.pi*np.arange(64)/64)).astype(np.float32)
        changed = data.copy()
        changed.real *= brightness
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            a = MeshThickness(reader_for(one,data),1.,1e-6,500.)
            b = MeshThickness(reader_for(two,changed),1.,1e-6,500.)
            np.testing.assert_allclose(a.sample_volume_rate(0,64), b.sample_volume_rate(0,64), atol=1e-4)

    def test_load_source_mass_units_actual_medium_and_opt_out(self):
        path = ROOT/'Generation/KWave/src/run_experiments.py'
        function = next(n for n in ast.parse(path.read_text()).body
                        if isinstance(n,ast.FunctionDef) and n.name=='load_source')
        scope = dict(Path=Path,sys=sys,np=np,__file__=str(path))
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(path),'exec'),scope)
        with tempfile.TemporaryDirectory() as tmp:
            reader = reader_for(tmp,translating_volume())
            cfg = dict(type='test',speed=1.,amplitude=0.,x=0,y=0,z=0,
                       thickness=dict(volume_per_blade_m3=1e-6,f_max=500.))
            bounds = dict(x=(0,2),y=(0,1),z=(0,1))
            density = np.array([1.1,1.3]).reshape(2,1,1)
            c = np.array([330.,350.]).reshape(2,1,1)
            raw = scope['load_source'](cfg,0,64,reader,bounds,None,density*c,16000.)
            rate = thickness_source(reader,cfg,16000.).sample_volume_rate(0,64).reshape(2,64)
            # Apply the vendored split-density source scaling and sum N=3
            # density components: injected mass must be rho * dphi/dt * dt.
            scaling_path = ROOT/'Generation/KWave/kwave/kWaveSimulation_helper/scale_source_terms_func.py'
            scaling_function = next(n for n in ast.parse(scaling_path.read_text()).body
                                    if isinstance(n,ast.FunctionDef) and n.name=='scale_pressure_source_uniform_grid')
            scale_scope = dict(np=np)
            exec(compile(ast.Module(body=[scaling_function],type_ignores=[]),str(scaling_path),'exec'),scale_scope)
            # Use actual one-based k-Wave indices, including the last medium cell.
            injected = 3*scale_scope['scale_pressure_source_uniform_grid'](
                raw.copy(), c, 3, .01, reader.meta['dt'], np.array([[1],[2]],dtype=np.uint64))
            np.testing.assert_allclose(injected,density.reshape(2,1)*rate*reader.meta['dt'],rtol=2e-7,atol=1e-9)
            cfg['thickness']['enabled']=False
            silent = scope['load_source'](cfg,0,64,reader,bounds,None)
            np.testing.assert_array_equal(silent,0.)

    def test_rotating_two_blade_mesh_produces_bpf_without_rpm_input(self):
        phase = 2*np.pi*np.arange(64)/64
        x, y = np.meshgrid(np.arange(9)*.01, np.arange(9)*.01, indexing='ij')
        blobs = []
        for offset in (0., np.pi):
            cx = .045+.02*np.cos(phase+offset)
            cy = .045+.02*np.sin(phase+offset)
            blobs.append(np.exp(-((x[...,None]-cx)**2+(y[...,None]-cy)**2)/(2*.006**2)))
        owner = np.argmax(blobs, axis=0)
        weight = np.maximum(*blobs)
        data = (255*weight+1j*(100050+owner))[:,:,None,:].astype(np.complex64)
        with tempfile.TemporaryDirectory() as tmp:
            reader = reader_for(tmp,data)
            model = thickness_source(reader,dict(speed=1.,thickness=dict(f_max=500.)))
            self.assertEqual(model.blades,(0,1))
            self.assertAlmostEqual(model.detected_rpm,60/(64e-4),delta=80.)
            rate = model.sample_volume_rate(0,64)
            power = np.sum(abs(np.fft.rfft(rate,axis=-1))**2,axis=(0,1,2))
            self.assertEqual(np.argmax(power),2)  # two passages per mesh revolution
            self.assertLess(power[1],power[2]*1e-10)
            other = thickness_source(reader,dict(speed=.5,thickness=dict(f_max=500.)))
            self.assertIsNot(model,other)
            self.assertIs(model,thickness_source(reader,dict(speed=1.,thickness=dict(f_max=500.))))

    def test_invalid_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = reader_for(tmp,translating_volume())
            for cfg in (dict(speed=1.,thickness=dict(volume_per_blade_m3=0)),
                        dict(speed=-1.),dict(speed=1.,thickness=dict(rpm=3000))):
                with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                    thickness_source(reader,cfg)


if __name__=='__main__':
    unittest.main()
