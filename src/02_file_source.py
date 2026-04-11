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

SIM_BOX_RATIO_X = 5.0
SIM_BOX_RATIO_Y = 6.0
SAMPLING_RATE = 16000
# SAMPLING_PERIOD = 9

from kwave.utils.mapgen import make_disc
def add_source(source, grid, offset, signal, size=4):
    if source.p_mask is None:
        source.p_mask = np.zeros(Vector([grid.Nx, grid.Ny]))
    if source.p is None:
        source.p = [None for _ in range(source.p_mask.size)]
    signal_np = np.zeros(grid.Nt)
    signal = signal[:grid.Nt]
    signal_np[:len(signal)] = signal
    signal_mask = make_disc(Vector([grid.Nx, grid.Ny]), Vector([offset[0], offset[1]]), size)
    source.p_mask = np.logical_or(source.p_mask, signal_mask)
    source.p = [p if p is not None or not m else signal_np for p, m in zip(source.p, signal_mask.reshape(-1))]


def load_mesh(mesh_path, kgrid, N, Nt):
    mesh = np.load(mesh_path)
    # mesh = np.load('C:\\Users\\vbpoh\\Documents\\Dojo\\PhD\\REPOS\\00_MINE\\CircularSignal\\input_mesh\\000.npy')
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

    source.p = np.transpose(mesh, [2, 1, 0, 3]).reshape(-1, Nt)

    return source

def main():
    # mesh = np.load('C:\\Users\\vbpoh\\Documents\\Dojo\\PhD\\REPOS\\00_MINE\\CircularSignal\\draw_mesh.npy')
    mesh = np.load('/app/input_mesh//000.npy')
    mesh_meta = json.load(open('/app/input_mesh/meta.json'))
    # grid properties
    N = Vector([int(mesh.shape[0]*SIM_BOX_RATIO_X), int(mesh.shape[1]*SIM_BOX_RATIO_Y), int(mesh.shape[2]*2)])
    d = Vector([mesh_meta['dx'], mesh_meta['dy'], mesh_meta['dz']])
    kgrid = kWaveGrid(N, d)
    kgrid.dt = mesh_meta['dt']
    Nt = mesh.shape[3]
    kgrid.Nt = Nt * 1000
    sampling_period = int(1 / SAMPLING_RATE / kgrid.dt)

    # medium properties
    # medium = kWaveMedium(sound_speed=np.ones(kgrid.k.shape) * 343)
    # medium.density = np.ones(kgrid.k.shape) * 1000
    medium = kWaveMedium(sound_speed=343)
    medium.density = 1
    # kgrid.makeTime(np.min(medium.sound_speed))

    sources = []
    src_files = {}
    for f in os.scandir('input_mesh'):
        if f.name.split('.')[-1] == 'npy':
            src_files[f.name.split('.')[0]] = f.path

    fnames = sorted(list(src_files.keys()))
    for fname in tqdm(fnames):
        sources.append(load_mesh(src_files[fname], kgrid, N, Nt))

    sensor = kSensor()
    sensor.mask = np.ones([kgrid.Nx, kgrid.Ny, kgrid.Nz], dtype=bool)
    simulation_options = SimulationOptions(
        save_to_disk=True,
        data_cast="single",
    )

    execution_options = SimulationExecutionOptions(is_gpu_simulation=True)
    proc_dir = '/app/processing'
    result_dir = os.path.join(proc_dir, '/app/outputs')
    os.makedirs(proc_dir, exist_ok=True)
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
    if os.path.exists(execution_options.checkpoint_file):
        with h5py.File(str(execution_options.checkpoint_file) + '.bkp', 'r') as f:
            ckpt_time = f['t_index'][0][0, 0]
            start_step_idx = int(ckpt_time/execution_options.checkpoint_timesteps)
        shutil.copy(str(execution_options.checkpoint_file) + '.bkp', execution_options.checkpoint_file)
    if os.path.exists('/app/outputs'):
        n_samples_ready = len([f.name for f in os.scandir('/app/outputs')])
    out_idx = n_samples_ready
    for step_idx in range(start_step_idx, 1000000):
        # TODO: Open checkpoint file and read the time index it has stopped at.
        source_idx = int(step_idx * execution_options.checkpoint_timesteps / Nt) % len(sources)
        print("------------- Using source:", source_idx)
        execution_options.input_file = os.path.join(proc_dir, f'input_{source_idx}.h5')
        simulation_options.execution_options = execution_options
        output = kspaceFirstOrder3D(kgrid, sources[source_idx], sensor, medium, simulation_options, execution_options)
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
            shutil.copy(execution_options.checkpoint_file, str(execution_options.checkpoint_file) + '.bkp')




if __name__ == "__main__":
    main()
