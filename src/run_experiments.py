import os
import yaml
import json
import h5py
import shutil
import numpy as np
from pathlib import Path
import sys
sys.path.append('/app')
from utils import spheres_noise

from kwave.data import Vector
from kwave.kgrid import kWaveGrid
from kwave.kmedium import kWaveMedium
from kwave.ksensor import kSensor
from kwave.ksource import kSource
from kwave.kspaceFirstOrder3D import kspaceFirstOrder3D
from kwave.options.simulation_execution_options import SimulationExecutionOptions
from kwave.options.simulation_options import SimulationOptions


def load_source(source, source_cfg, source_idx, tidx_start, source_bounds):
    src_files = {}
    mesh_meta = json.load(open(os.path.join('/app/input_mesh', source_cfg['type'], 'meta.json')))
    dt = float(mesh_meta['dt'])
    for f in os.scandir(os.path.join('/app/input_mesh', source_cfg['type'])):
        if f.name.split('.')[-1] == 'npz':
            src_files[f.name.split('.')[0]] = f.path
    fnames = sorted(list(src_files.keys()))
    mesh_path = src_files[fnames[source_idx]]

    mesh = np.load(mesh_path)['arr_0']
    mesh_xstart = int(source_cfg['x'] - source_bounds['x'][0])
    mesh_xend = mesh_xstart + mesh.shape[0]
    mesh_ystart = int(source_cfg['y'] - source_bounds['y'][0])
    mesh_yend = mesh_ystart + mesh.shape[1]
    mesh_zstart = int(source_cfg['z'] - source_bounds['z'][0])
    mesh_zend = mesh_zstart + mesh.shape[2]
    Nt = mesh.shape[-1]
    source_p = np.zeros([
        source_bounds['x'][1] - source_bounds['x'][0],
        source_bounds['y'][1] - source_bounds['y'][0],
        source_bounds['z'][1] - source_bounds['z'][0],
        Nt
    ], dtype=np.float64)

    # Generate a sine signal, scale with the values being read, write as a source
    sf = source_cfg['freq']
    duration = Nt * dt
    tstart = tidx_start * dt
    t = np.linspace(tstart, tstart + duration, mesh.shape[-1]) + source_cfg['phase']
    y = source_cfg['amplitude'] * np.sin(2 * np.pi * sf * t) + 1e-7
    result = np.nan_to_num(mesh.real)
    mesh_descr = mesh.imag.astype(int)

    blade_idx = mesh_descr % 10
    result[blade_idx != 0] = 0
    result[result < 0] = 0
    result *= y[None, None, None, :]
    source_p[mesh_xstart:mesh_xend, mesh_ystart:mesh_yend, mesh_zstart:mesh_zend] = result

    source.p += np.transpose(source_p, [2, 1, 0, 3]).reshape(-1, Nt)

def get_mesh_bounds(vmin, vmax, source, mesh_meta, key, nkey):
    if vmin is None:
        vmin = source[key]
    vmin = min(vmin, source[key])
    if vmax is None:
        vmax = source[key] + mesh_meta[nkey]
    vmax = max(vmax, source[key] + mesh_meta[nkey])

    return vmin, vmax

def run_experiment(base_path, config):
    os.makedirs(os.path.join(base_path, 'outputs'), exist_ok=True)
    os.makedirs(os.path.join(base_path, 'slices'), exist_ok=True)
    for i, _ in enumerate(config['slices']):
        os.makedirs(os.path.join(base_path, 'slices', str(i).zfill(3)), exist_ok=True)

    # Load sources
    Nt = None
    nsources = None
    xmin, xmax = None, None
    ymin, ymax = None, None
    zmin, zmax = None, None
    for source in config['sources']:
        src_files = {}
        mesh_meta = json.load(open(os.path.join('/app/input_mesh', source['type'], 'meta.json')))
        for f in os.scandir(os.path.join('/app/input_mesh', source['type'])):
            if Nt == None:
                Nt = mesh_meta['nt']
            assert mesh_meta['nt'] == Nt, "Number of timesteps must match for each mesh"
            assert mesh_meta['dx'] == config['mesh']['dx'], "DX for source mesh must match computational mesh"
            assert mesh_meta['dy'] == config['mesh']['dy'], "DY for source mesh must match computational mesh"
            assert mesh_meta['dz'] == config['mesh']['dz'], "DZ for source mesh must match computational mesh"
            xmin, xmax = get_mesh_bounds(xmin, xmax, source, mesh_meta, 'x', 'nx')
            ymin, ymax = get_mesh_bounds(ymin, ymax, source, mesh_meta, 'y', 'ny')
            zmin, zmax = get_mesh_bounds(zmin, zmax, source, mesh_meta, 'z', 'nz')
            if f.name.split('.')[-1] == 'npz':
                src_files[f.name.split('.')[0]] = f.path
        # fnames = sorted(list(src_files.keys()))
        if nsources is None:
            nsources = len(src_files)
        assert nsources == len(src_files), "Number of mesh files must match across sources."
    assert xmin is not None and xmax is not None, "No sources loaded!"
    assert ymin is not None and ymax is not None, "No sources loaded!"
    assert zmin is not None and zmax is not None, "No sources loaded!"
    source_bounds = {
        'x': (xmin, xmax),
        'y': (ymin, ymax),
        'z': (zmin, zmax),
    }

    # Setup mesh & medium
    N = Vector([int(config['mesh']['size_x']), int(config['mesh']['size_y']), int(config['mesh']['size_z'])])
    d = Vector([config['mesh']['dx'], config['mesh']['dy'], config['mesh']['dz']])
    kgrid = kWaveGrid(N, d)
    kgrid.dt = float(config['mesh']['dt'])
    kgrid.Nt = int(config['time'] / float(config['mesh']['dt']))
    sampling_period = int(1 / config['sampling'] / kgrid.dt)

    medium = kWaveMedium(sound_speed=spheres_noise(kgrid, base_val=343, min_val=340, max_val=345, min_rad=5, max_rad=1024, seed=33, dbg_file='/app/c_noise.png'))
    medium.density = spheres_noise(kgrid, base_val=1.225, min_val=1.2, max_val=1.25, min_rad=5, max_rad=1024, seed=25, dbg_file='/app/density_noise.png')

    # Execution configuration
    sensor = kSensor()
    sensor.mask = np.ones([kgrid.Nx, kgrid.Ny, kgrid.Nz], dtype=bool)
    simulation_options = SimulationOptions(
        save_to_disk=True,
        data_cast="single",
    )
    execution_options = SimulationExecutionOptions(is_gpu_simulation=True)
    proc_dir = '/inputs/processing'
    bkp_proc_dir = os.path.join(base_path, 'processing')
    result_dir = os.path.join(base_path, 'outputs')
    os.makedirs(proc_dir, exist_ok=True)
    os.makedirs(bkp_proc_dir, exist_ok=True)
    os.makedirs(result_dir, exist_ok=True)
    execution_options.checkpoint_file = os.path.join(proc_dir, 'ckpt.h5')
    execution_options.checkpoint_timesteps = Nt
    execution_options.output_file = os.path.join(proc_dir, 'output.h5')
    execution_options.binary_path = Path('/app/k-Wave-CPUGPU-src/kspaceFirstOrder-CUDA/kspaceFirstOrder-CUDA')
    execution_options.sampling_period = sampling_period

    # The Execution
    ckpt_time = 0
    n_samples_ready = 0
    start_step_idx = 0
    bkp_ckpt_file = str(execution_options.checkpoint_file).replace(proc_dir, bkp_proc_dir) + '.bkp'
    if os.path.exists(execution_options.checkpoint_file):
        with h5py.File(bkp_ckpt_file, 'r') as f:
            ckpt_time = f['t_index'][0][0, 0]
            start_step_idx = int(ckpt_time/execution_options.checkpoint_timesteps)
        shutil.copy(bkp_ckpt_file, execution_options.checkpoint_file)
    if os.path.exists('/app/outputs'):
        n_samples_ready = len([f.name for f in os.scandir('/app/outputs')])
    out_idx = n_samples_ready
    for step_idx in range(start_step_idx, 1000000):
        source_idx = int(step_idx * execution_options.checkpoint_timesteps / Nt) % nsources
        print("------------- Using source:", source_idx)
        execution_options.input_file = os.path.join(proc_dir, f'input_{source_idx}.h5')
        simulation_options.execution_options = execution_options
        # source = load_mesh(src_files[fnames[source_idx]], kgrid, N, Nt, step_idx)
        source = kSource()
        source.p_mask = np.zeros([kgrid.Nx, kgrid.Ny, kgrid.Nz], dtype=bool)
        source.p_mask[xmin:xmax, ymin:ymax, zmin:zmax] = 1
        n_src_points = (xmax - xmin) * (ymax - ymin) * (zmax - zmin)
        assert n_src_points == source.p_mask.sum(), "Something wrong with source mask"
        source.p = np.zeros([n_src_points, Nt], dtype=np.float64)
        for source_cfg in config['sources']:
            load_source(source, source_cfg, source_idx, step_idx, source_bounds)
        output = kspaceFirstOrder3D(kgrid, source, sensor, medium, simulation_options, execution_options)
        os.remove(execution_options.input_file)
        sensor_data = output["p"].T.reshape(kgrid.Nz, kgrid.Ny, kgrid.Nx, -1)
        start_idx = 0
        if np.sum(sensor_data[:, :, :, 0]) == 0:
            start_idx = 1
        
        # +1 due to the output at 0s step
        n_samples_prepared = int(output['t_index'] / sampling_period) + 1 - n_samples_ready
        assert start_idx + n_samples_prepared <= sensor_data.shape[-1], "Wrong number of samples prepared"
        # assert np.sum(np.abs(sensor_data[:, :, :, start_idx + n_samples_prepared:])) == 0, "Skipping nonempty samples."
        n_samples_ready += n_samples_prepared
        for timestep_idx in range(start_idx, start_idx + n_samples_prepared):
            np.save(os.path.join(result_dir, f'{str(out_idx).zfill(5)}.npy'), sensor_data[16, :, :, timestep_idx])
            assert np.sum(sensor_data[16, :, :, timestep_idx]) != 0, "Something has gone wrong."
            out_idx += 1
        # Check if the number of files generated matches the one recorded in checkpoint
        with h5py.File(str(execution_options.checkpoint_file), 'r') as f:
            out_ckpt_time = f['t_index'][0][0, 0]
            out_n_samples_ready = len([f.name for f in os.scandir(result_dir)])
            expected_samples = int(out_ckpt_time / sampling_period) + 1 # +1 due to the output at 0s step
            assert expected_samples == out_n_samples_ready, "Number of samples number available does not match the expected number."
        if not os.path.exists(execution_options.checkpoint_file):
            break
        else:
            # If the outputs were saved successfully, save the checkpoint file in case if something goes wrong.
            shutil.copy(execution_options.checkpoint_file, bkp_ckpt_file)

if __name__ == '__main__':
    experiments_base = '/app/Experiments'
    for exp_f in os.scandir(experiments_base):
        if not os.path.isdir(exp_f):
            continue
        descr = os.path.join(exp_f.path, 'experiment.yml')
        if not os.path.exists(descr):
            print('--------------------------------- Experiment yml is not found!', exp_f.path)
            continue
        if os.path.exists(os.path.join(exp_f.path, 'done.flag')):
            print('Experiment done, skipping.', exp_f.path)
            continue
        with open(descr, 'r') as descr_f:
            config = yaml.load(descr_f, Loader=yaml.FullLoader)
            run_experiment(exp_f.path, config)
