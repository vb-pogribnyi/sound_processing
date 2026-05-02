import matplotlib.pyplot as plt
import numpy as np
import cv2
import os
import h5py
import shutil
from tqdm import tqdm
import sys
sys.path.append('/app')

from pathlib import Path
from kwave.data import Vector
from kwave.kgrid import kWaveGrid
from kwave.kmedium import kWaveMedium
from kwave.ksensor import kSensor
from kwave.ksource import kSource
from kwave.kspaceFirstOrder3D import kspaceFirstOrder3D
from kwave.options.simulation_execution_options import SimulationExecutionOptions
from kwave.options.simulation_options import SimulationOptions
import json
from utils import spheres_noise

SIM_BOX_RATIO_X = 5.0
SIM_BOX_RATIO_Y = 6.0
SAMPLING_RATE = 16000

def load_mesh(mesh_path, kgrid, N, Nt, tidx_start):
    mesh = np.load(mesh_path)['arr_0']
    source = kSource()
    source.p_mask = np.zeros([kgrid.Nx, kgrid.Ny, kgrid.Nz], dtype=bool)
    mesh_xstart = int(N.x // 2 - mesh.shape[0] // 2)
    mesh_xend = mesh_xstart + mesh.shape[0]
    # mesh_ystart = int(N.y // 2 - mesh.shape[1] // 2)
    # mesh_yend = mesh_ystart + mesh.shape[1]
    mesh_ystart = int(120 - mesh.shape[1] // 2)
    mesh_yend = mesh_ystart + mesh.shape[1]
    mesh_zstart = int(N.z // 2 - mesh.shape[2] // 2)
    mesh_zend = mesh_zstart + mesh.shape[2]
    source.p_mask[mesh_xstart:mesh_xend, mesh_ystart:mesh_yend, mesh_zstart:mesh_zend] = 1

    # Generate a sine signal, scale with the values being read, write as a source
    sf = 1000 # Generating 1 kHz signal
    duration = Nt * kgrid.dt
    tstart = tidx_start * kgrid.dt
    t = np.linspace(tstart, tstart + duration, mesh.shape[-1])
    y = 0.2*np.sin(2*np.pi * sf * t) + 1e-7
    result = np.nan_to_num(mesh.real)
    mesh_descr = mesh.imag.astype(int)

    blade_idx = mesh_descr % 10
    result[blade_idx != 0] = 0
    result[result < 0] = 0
    # mult = np.ones_like(result)[:, :, :, 0]
    result *= y[None, None, None, :]

    # source.p = np.transpose(mesh.real.astype(np.float16), [2, 1, 0, 3]).reshape(-1, Nt)
    source.p = np.transpose(result.astype(np.float64), [2, 1, 0, 3]).reshape(-1, Nt)

    return source

def main():
    mesh_meta = json.load(open('/app/input_mesh/meta.json'))
    # grid properties
    N = Vector([int(mesh_meta['nx']*SIM_BOX_RATIO_X), int(mesh_meta['ny']*SIM_BOX_RATIO_Y), int(mesh_meta['nz']*2)])
    d = Vector([mesh_meta['dx'], mesh_meta['dy'], mesh_meta['dz']])
    kgrid = kWaveGrid(N, d)
    kgrid.dt = mesh_meta['dt']
    Nt = mesh_meta['nt']
    kgrid.Nt = Nt * 1000
    sampling_period = int(1 / SAMPLING_RATE / kgrid.dt)

    medium = kWaveMedium(sound_speed=spheres_noise(kgrid, base_val=343, min_val=340, max_val=345, min_rad=5, max_rad=1024, seed=33, dbg_file='/app/c_noise.png'))
    medium.density = spheres_noise(kgrid, base_val=1.225, min_val=1.2, max_val=1.25, min_rad=5, max_rad=1024, seed=25, dbg_file='/app/density_noise.png')

    src_files = {}
    for f in os.scandir('input_mesh'):
        if f.name.split('.')[-1] == 'npz':
            src_files[f.name.split('.')[0]] = f.path

    fnames = sorted(list(src_files.keys()))

    sensor = kSensor()
    sensor.mask = np.ones([kgrid.Nx, kgrid.Ny, kgrid.Nz], dtype=bool)
    simulation_options = SimulationOptions(
        save_to_disk=True,
        data_cast="single",
    )

    execution_options = SimulationExecutionOptions(is_gpu_simulation=True)
    proc_dir = '/inputs/processing'
    bkp_proc_dir = '/app/processing'
    result_dir = os.path.join(proc_dir, '/app/outputs')
    os.makedirs(proc_dir, exist_ok=True)
    os.makedirs(bkp_proc_dir, exist_ok=True)
    os.makedirs(result_dir, exist_ok=True)
    execution_options.checkpoint_file = os.path.join(proc_dir, 'ckpt.h5')
    # Every mesh file processes at one go.
    execution_options.checkpoint_timesteps = Nt
    execution_options.output_file = os.path.join(proc_dir, 'output.h5')
    execution_options.binary_path = Path('/app/k-Wave-CPUGPU-src/kspaceFirstOrder-CUDA/kspaceFirstOrder-CUDA')
    execution_options.sampling_period = sampling_period
    
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
        source_idx = int(step_idx * execution_options.checkpoint_timesteps / Nt) % len(src_files)
        print("------------- Using source:", source_idx)
        execution_options.input_file = os.path.join(proc_dir, f'input_{source_idx}.h5')
        simulation_options.execution_options = execution_options
        source = load_mesh(src_files[fnames[source_idx]], kgrid, N, Nt, step_idx)
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
            out_n_samples_ready = len([f.name for f in os.scandir('/app/outputs')])
            expected_samples = int(out_ckpt_time / sampling_period) + 1 # +1 due to the output at 0s step
            assert expected_samples == out_n_samples_ready, "Number of samples number available does not match the expected number."
        if not os.path.exists(execution_options.checkpoint_file):
            break
        else:
            # If the outputs were saved successfully, save the checkpoint file in case if something goes wrong.
            shutil.copy(execution_options.checkpoint_file, bkp_ckpt_file)




if __name__ == "__main__":
    main()
