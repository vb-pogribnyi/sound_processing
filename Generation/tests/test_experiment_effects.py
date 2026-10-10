"""Small regression checks: no runner import, real mesh, or solver execution."""
import ast
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import h5py
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'Generation/KWave/src'))
from experiment_effects import source_options, PressureBumps, SourceCapture
from utils import spheres_noise
from Generation.tests.test_kwave_thickness import reader_for, translating_volume


def extract(path, names, scope):
    nodes = [n for n in ast.parse(path.read_text()).body
             if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)


class EffectsTests(unittest.TestCase):
    def test_pressure_bumps_propagating_source_layout_and_chunk_continuity(self):
        shape = (12,11,10)
        cfg = dict(peak_pa=.02,seed=57,rate_hz=100.,radius_cells=1.,duration_s=.004)
        bumps = PressureBumps(cfg,shape,.0001,.1)
        mask = np.zeros(shape,dtype=bool)
        mask[3:5,4:6,2:4] = True
        blade_indices = np.flatnonzero(mask.ravel(order='F'))
        bumps.add_to_mask(mask)
        indices = np.flatnonzero(mask.ravel(order='F'))
        blade_rows = np.searchsorted(indices,blade_indices)
        full = np.zeros((len(indices),1000),dtype=np.float32)
        bumps.add_to_source(full,0,1000)
        self.assertGreater(len(bumps.events),1)
        self.assertTrue(np.any(full[np.setdiff1d(np.arange(len(indices)),blade_rows)]))
        chunks = []
        for lo,hi in ((0,19),(19,450),(450,1000)):
            chunk = np.zeros((len(indices),hi-lo),dtype=np.float32)
            bumps.add_to_source(chunk,lo,hi)
            chunks.append(chunk)
        np.testing.assert_array_equal(full,np.concatenate(chunks,axis=1))
        for multiplier in (1,2):
            repeated = PressureBumps(dict(cfg,peak_pa=cfg['peak_pa']*multiplier),shape,.0001,.1)
            repeated.add_to_mask(mask.copy())
            other = np.zeros_like(full)
            repeated.add_to_source(other,0,1000)
            np.testing.assert_array_equal(other,full*multiplier)
        # The generated events are local spatial bumps, at multiple positions.
        self.assertGreater(len({int(event[1][np.argmax(abs(event[2]))]) for event in bumps.events}),1)
        for start,rows,weights in bumps.rows:
            self.assertLessEqual(len(rows),123) # radius 3 sphere on the integer grid
            self.assertAlmostEqual(float(max(abs(weights))),cfg['peak_pa'],places=7)

        # Exercise the actual worker with an in-memory shared buffer and tiny
        # source. No subprocess, actual mesh files, solver, or runner import.
        path = ROOT/'Generation/KWave/src/run_experiments.py'
        buffer = bytearray(full.nbytes)
        task_queue = Mock()
        task_queue.get.side_effect = [(0,1000,[{'type':'tiny'}]),None]
        task_queue.empty.return_value = True
        mesh_pressure = np.arange(8,dtype=np.float32)[:,None]*np.ones((1,1000),dtype=np.float32)
        scope = dict(np=np,SharedMemory=lambda **kw:SimpleNamespace(buf=buffer),
                     load_source=Mock(return_value=mesh_pressure),
                     resource=SimpleNamespace(RUSAGE_SELF=0,getrusage=lambda _:SimpleNamespace(ru_maxrss=0)))
        extract(path,{'worker_source'},scope)
        scope['worker_source'](task_queue,Mock(),Mock(),'test',full.shape,np.float32,
                               {'tiny':None},{},None,None,bumps,blade_rows)
        actual = np.ndarray(full.shape,np.float32,buffer)
        expected = np.zeros_like(full)
        expected[blade_rows] = mesh_pressure
        bumps.add_to_source(expected,0,1000)
        np.testing.assert_array_equal(actual,expected)

    def test_source_capture_matches_brute_force(self):
        bounds = dict(x=(2,5),y=(1,3),z=(4,6))
        capture = SourceCapture(bounds,(40,1,5),.01,1e-5,delay_resolution=1,chunk=7)
        n = capture.n_cells
        def load(a,b):
            t = np.arange(a,b)
            return np.sin(.37*np.arange(n)[:,None]+.11*t[None])+.01*t[None]
        # Cell order follows load_source: z, y, x with x fastest; nearer the target (+x) is heard earlier
        z,y,x = np.meshgrid(np.arange(4,6),np.arange(1,3),np.arange(2,5),indexing='ij')
        cells = np.stack([x.ravel(),y.ravel(),z.ravel()],1)*.01
        direction = np.array([40,1,5])*.01-cells.mean(0)
        delays = np.rint((cells-cells.mean(0))@(direction/np.linalg.norm(direction))/343./1e-5).astype(int)
        self.assertGreater(delays[2],delays[0])     # x=4 vs x=2 in the same row
        self.assertEqual(capture.margin,abs(delays).max())
        for start,length in ((50,40),(0,30),(3,1)):
            expected = np.zeros(length)
            for t in range(start,start+length):
                for v in range(n):
                    u = t+delays[v]
                    if u >= 0:     # sources are silent before step 0
                        expected[t-start] += load(u,u+1)[v,0]
            np.testing.assert_allclose(capture.segment(load,start,length),expected,rtol=1e-5,atol=1e-5)
        with self.assertRaises(ValueError):
            capture.segment(lambda a,b:np.zeros((n+1,b-a)),10,5)

    def test_pressure_bumps_src_replica(self):
        shape = (12,11,10)
        cfg = dict(peak_pa=.5,seed=57,rate_hz=100.,radius_cells=1.,duration_s=.004,src_replica=True)
        bumps = PressureBumps(cfg,shape,.0001,.1)
        plain = PressureBumps(dict(cfg,src_replica=False),shape,.0001,.1)
        # Same schedule with or without replica
        self.assertEqual([(e[0],list(e[1])) for e in bumps.events],[(e[0],list(e[1])) for e in plain.events])
        mask = np.zeros(shape,dtype=bool)
        bumps.add_to_mask(mask)
        full = np.zeros((int(mask.sum()),1000),dtype=np.float32)
        with self.assertRaises(ValueError):
            bumps.add_to_source(full,0,1000)
        calls = []
        def segment(a,n):
            calls.append((a,n))
            return np.cos(.05*np.arange(a,a+n))
        margin = 30
        bumps.set_replica_source(segment,margin)
        bumps.add_to_source(full,0,1000)
        length = int(np.ceil(bumps.pulse_steps))
        expected = np.zeros_like(full)
        replayed = 0
        for i,(start,rows,weights) in enumerate(bumps.rows):
            self.assertAlmostEqual(abs(float(weights.sum())),cfg['peak_pa'],places=5)
            source_start = bumps.replica_start(i)
            if start-length-margin < 0:
                self.assertIsNone(source_start)    # no history yet: silent event
                continue
            # Random earlier segment that ends, with margin, before the event starts
            self.assertTrue(0 <= source_start <= start-length-margin)
            hi = min(1000,start+length)
            phase = (np.arange(start,hi)-start)/bumps.pulse_steps
            pulse = np.sin(np.pi*phase)**2*np.cos(.05*np.arange(source_start,source_start+hi-start))
            expected[rows,start:hi] += weights[:,None]*pulse.astype(np.float32)
            replayed += 1
        self.assertGreater(replayed,1)
        np.testing.assert_allclose(full,expected,rtol=1e-5,atol=1e-8)
        self.assertEqual(len(calls),len(set(calls)))    # each event's segment computed once
        self.assertTrue(all(n == length for _,n in calls))
        chunks = []
        for lo,hi in ((0,19),(19,450),(450,1000)):
            chunk = np.zeros((full.shape[0],hi-lo),dtype=np.float32)
            bumps.add_to_source(chunk,lo,hi)
            chunks.append(chunk)
        np.testing.assert_array_equal(full,np.concatenate(chunks,axis=1))
        with self.assertRaises(ValueError):
            PressureBumps(dict(cfg,src_replica='yes'),shape,.0001,.1)

        # The worker wires the capture to the actual sources
        path = ROOT/'Generation/KWave/src/run_experiments.py'
        mesh_mask = np.zeros(shape,dtype=bool)
        mesh_mask[3:5,4:6,2:4] = True
        bounds = dict(x=(3,5),y=(4,6),z=(2,4))
        blade_rows = np.searchsorted(np.flatnonzero(mask.ravel(order='F')),np.flatnonzero(mesh_mask.ravel(order='F')))
        capture = SourceCapture(bounds,(11,10,9),.001,.0001,delay_resolution=1)
        def fake_load(source,a,b,*args):
            return np.sin(.02*np.arange(a,b))[None]*np.arange(1,9,dtype=np.float32)[:,None]*source['gain']
        sources = [{'type':'tiny','gain':1.},{'type':'tiny','gain':2.}]
        buffer = bytearray(full.nbytes)
        task_queue = Mock()
        task_queue.get.side_effect = [(0,1000,sources),None]
        task_queue.empty.return_value = True
        worker_bumps = PressureBumps(cfg,shape,.0001,.1)
        worker_bumps.add_to_mask(np.zeros(shape,dtype=bool))
        scope = dict(np=np,SharedMemory=lambda **kw:SimpleNamespace(buf=buffer),load_source=fake_load,
                     resource=SimpleNamespace(RUSAGE_SELF=0,getrusage=lambda _:SimpleNamespace(ru_maxrss=0)))
        extract(path,{'worker_source'},scope)
        scope['worker_source'](task_queue,Mock(),Mock(),'test',full.shape,np.float32,
                               {'tiny':None},bounds,None,None,worker_bumps,blade_rows,capture)
        reference = PressureBumps(cfg,shape,.0001,.1)
        reference.add_to_mask(np.zeros(shape,dtype=bool))
        reference.set_replica_source(lambda a,n:capture.segment(lambda u0,u1:3*fake_load({'gain':1.},u0,u1),a,n),
                                     capture.margin)
        expected = np.zeros_like(full)
        expected[blade_rows] = fake_load({'gain':3.},0,1000)
        reference.add_to_source(expected,0,1000)
        self.assertTrue(np.any(expected[np.setdiff1d(np.arange(len(expected)),blade_rows)]))
        np.testing.assert_allclose(np.ndarray(full.shape,np.float32,buffer),expected,rtol=1e-5,atol=1e-7)

    def test_pressure_bumps_hdf5_timestep_types(self):
        bumps = PressureBumps({},(1,1,1),1e-7,.3)
        # Include pulses crossing either chunk boundary and an interior pulse.
        bumps.rows = [(step,np.array([0]),np.array([1.],dtype=np.float32))
                      for step in (8188,8210,8250)]
        bumps.pulse_steps = 16.
        expected = np.zeros((1,64),dtype=np.float32)
        bumps.add_to_source(expected,8192,8256)
        self.assertTrue(np.any(expected))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'checkpoint.h5'
            with h5py.File(path,'w') as f:
                f['t_index'] = np.array([[[8192]]],dtype=np.uint64)
            with h5py.File(path,'r') as f:
                checkpoint_step = f['t_index'][0][0,0]
                solver_step = f['t_index'][:].squeeze()
            for start,stop in ((checkpoint_step,checkpoint_step+64),
                               (solver_step,solver_step+64),
                               (np.uint64(8192),np.uint64(8256)),
                               (np.float64(8192),np.float64(8256))):
                with self.subTest(start_type=type(start),stop_type=type(stop)):
                    actual = np.zeros_like(expected)
                    bumps.add_to_source(actual,start,stop)
                    np.testing.assert_array_equal(actual,expected)

        for start,stop in ((8192.5,8256),(8192,8256.5)):
            with self.assertRaises(ValueError):
                bumps.add_to_source(np.zeros_like(expected),start,stop)

    def test_pressure_bumps_disabled_and_validation(self):
        self.assertEqual(PressureBumps({},(8,8,8),1e-4,.1).events,[])
        for cfg in ({'peak_pa':-1},{'rate_hz':-1},{'radius_cells':0},
                    {'seed':-1},{'peak_pa':1,'duration_s':1e-5},{'rms_pa':1}):
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                PressureBumps(cfg,(8,8,8),1e-4,.1)

    def test_source_modes_sum_and_skip_disabled_generators(self):
        path = ROOT/'Generation/KWave/src/run_experiments.py'
        scope = dict(np=np, Path=Path, sys=sys, __file__=str(path))
        extract(path, {'load_source'}, scope)
        cfg = dict(type='tiny', x=0,y=0,z=0,speed=1.,amplitude=1.,
                   thickness=dict(volume_per_blade_m3=1e-6,f_max=500.))
        bounds = dict(x=(0,2),y=(0,1),z=(0,1))
        with tempfile.TemporaryDirectory() as folder:
            reader = reader_for(folder, translating_volume())
            def load(mode):
                return scope['load_source'](dict(cfg,mode=mode),0,32,reader,bounds,None,343.,16000.)
            with patch('Generation.kwave_noise.MeshNoise', return_value=lambda m,t: m.real.astype(np.float32)/255):
                with patch('Generation.kwave_thickness.thickness_source', side_effect=AssertionError('disabled')):
                    amiet = load('amiet')
                both = load('both')
            with patch('Generation.kwave_noise.MeshNoise', side_effect=AssertionError('disabled')):
                loading = load('loading')
            np.testing.assert_array_equal(both, amiet+loading)
            self.assertTrue(np.any(amiet) and np.any(loading))
        self.assertEqual(source_options({'mode':'loading'}, 'amiet')['mode'], 'loading')
        self.assertFalse(source_options({'noise':{'tip':True}}, 'amiet')['noise']['tip'])
        for mode in ('', 'typo', False):
            with self.assertRaises(ValueError):
                source_options({}, mode)

    def test_actual_hdf_medium_writer_preserves_both_maps(self):
        # Compile vendored serialization functions only: no kwave package import
        # (which can download binaries) and no execution of run_experiments.
        class DotDict(dict):
            __getattr__ = dict.__getitem__
        scope = dict(np=np,h5py=h5py,dotdict=DotDict)
        extract(ROOT/'Generation/KWave/kwave/utils/io.py',
                {'get_h5_literals','write_matrix','assign_str_attr'},scope)
        extract(ROOT/'Generation/KWave/kwave/kWaveSimulation_helper/save_to_disk_func.py',
                {'grab_float_variables'},scope)
        grid = SimpleNamespace(Nx=8,Ny=7,Nz=6,dx=.01,dy=.01,dz=.01)
        c = spheres_noise(grid,343.,220.,420.,5.,1024.,0)
        rho = spheres_noise(grid,.9,1.,1.8,5.,1024.,2)
        values = SimpleNamespace(c0=c,rho0=rho,c_ref=float(c.max()),dt=1e-6,
                                 rho0_sgx=rho,rho0_sgy=rho,rho0_sgz=rho)
        arrays = {}
        scope['grab_float_variables'](arrays,grid,SimpleNamespace(pml_x_alpha=2,pml_y_alpha=2,pml_z_alpha=2),values,False,False)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/'input.h5')
            for name in ('c0','rho0'):
                scope['write_matrix'](path,np.asarray(arrays[name],dtype=np.float32),name)
            with h5py.File(path,'r') as f:
                for name,expected in (('c0',c),('rho0',rho)):
                    self.assertEqual(f[name].shape,(6,7,8))
                    np.testing.assert_array_equal(f[name][()],expected.transpose(2,1,0).astype(np.float32))


if __name__ == '__main__':
    unittest.main()
