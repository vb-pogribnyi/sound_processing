import os
import gc
import yaml
import json
import h5py
import shutil
import cv2 as cv
import numpy as np
from pathlib import Path
from PIL import Image
import sys
sys.path.append('/app/Generation/KWave/')
from utils import spheres_noise

from kwave.data import Vector
from kwave.kgrid import kWaveGrid
from kwave.kmedium import kWaveMedium
from kwave.ksensor import kSensor
from kwave.ksource import kSource
from kwave.kspaceFirstOrder3D import kspaceFirstOrder3D
from kwave.options.simulation_execution_options import SimulationExecutionOptions
from kwave.options.simulation_options import SimulationOptions
from CircularSignal.MeshReader import MeshReader

import atexit
import logging
import resource
from multiprocessing import Process, Queue
from multiprocessing.shared_memory import SharedMemory


Nt = 1024*8
def worker_gif(task_queue, logger):
    while True:
        dirnames = set()
        msg = task_queue.get()
        if msg is not None:
            dirnames.add(msg)
        while not task_queue.empty():
            msg = task_queue.get_nowait()
            if msg is not None:
                dirnames.add(msg)
        # Create the gif from images
        for dirname in dirnames:
            logger.info(f"Processing {dirname}")
            frames = sorted([f.path for f in os.scandir(os.path.join(dirname, 'frames'))])
            logger.info(f"Found {len(frames)} frames")
            frames = frames[-256:]
            frames = [Image.open(p).convert("RGBA") for p in frames]

            frames[0].save(
                os.path.join(dirname, 'slice.gif'),
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=30,       # milliseconds per frame
                loop=0,
                optimize=True,
                disposal=2,  # clear each frame before drawing the next
            )
        logger.info(f"GIFs saved")
        logger.info(f'Peak memory usage: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB')
        if msg is None:
            break

def worker_source(in_queue, out_queue, logger, shm_name, shm_shape, shm_dtype, mesh_readers, source_bounds):
    while True:
        msg = in_queue.get()
        if msg is None:
            break
        assert in_queue.empty(), "More than 1 request to generate source!"
        (time_start, time_end, sources_cfg) = msg
        logger.info(f"Started processing from {time_start} to {time_end}")
        shm = SharedMemory(name=shm_name)
        logger.info(f"Loaded shared memory")
        shm_array = np.ndarray(shm_shape, shm_dtype, shm.buf)
        shm_array *= 0
        for source in sources_cfg:
            logger.info(f"Loading source")
            shm_array += load_source(source, time_start, time_end, mesh_readers[source['type']], source_bounds, logger)
        logger.info(f"Source generation done.")
        logger.info(f'Peak memory usage: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB')
        out_queue.put(msg)


def save_slice_img(slice, dirname, out_idx, gif_task_queue):
    os.makedirs(os.path.join(dirname, 'frames'), exist_ok=True)
    slice = np.stack([slice, np.zeros_like(slice), slice], axis=-1)
    slice[:, :, 2] *= -1
    slice[slice < 0] = 0
    slice[slice < 1e-45] = 1e-45
    slice = (100 + np.log(slice)) * 1.5
    slice[slice < 0] = 0
    # slice[mic_position[0], mic_position[1], 1] = 255
    cv.imwrite(os.path.join(dirname, 'frames', f'{str(out_idx).zfill(5)}.png'), slice.astype(np.uint8))

    gif_task_queue.put(dirname)



def load_source(source_cfg, time_start, time_end, mesh_reader, source_bounds, logger):
    src_files = {}
    mesh_meta = json.load(open(os.path.join('/app/Generation/KWave/input_mesh', source_cfg['type'], 'meta.json')))
    dt = float(mesh_meta['dt'])
    for f in os.scandir(os.path.join('/app/Generation/KWave/input_mesh', source_cfg['type'])):
        if f.name.split('.')[-1] == 'npz':
            src_files[f.name.split('.')[0]] = f.path

    mesh = mesh_reader.sample(source_cfg['speed'], time_start, time_end, logger)
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
    ], dtype=np.float32)

    # Generate a sine signal, scale with the values being read, write as a source
    sf = source_cfg['freq']
    duration = Nt * dt
    tstart = time_start * dt
    t = np.linspace(tstart, tstart + duration, mesh.shape[-1]) + source_cfg['phase']
    y = source_cfg['amplitude'] * np.sin(2 * np.pi * sf * t) + 1e-7
    result = np.nan_to_num(mesh.real)
    mesh_descr = mesh.imag.astype(int)

    blade_idx = mesh_descr % 10
    result[blade_idx != 0] = 0
    result[result < 0] = 0
    result *= y[None, None, None, :]
    source_p[mesh_xstart:mesh_xend, mesh_ystart:mesh_yend, mesh_zstart:mesh_zend] = result

    return np.transpose(source_p, [2, 1, 0, 3]).reshape(-1, Nt)

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
    proc_dir = '/inputs/processing'
    bkp_proc_dir = os.path.join(base_path, 'processing')
    os.makedirs(bkp_proc_dir, exist_ok=True)
    result_dir = os.path.join(base_path, 'outputs')

    for i, _ in enumerate(config['slices']):
        os.makedirs(os.path.join(base_path, 'slices', str(i).zfill(3)), exist_ok=True)

    # Load sources
    # nsources = None
    xmin, xmax = None, None
    ymin, ymax = None, None
    zmin, zmax = None, None
    mesh_readers = {}
    for source in config['sources']:
        mesh_meta = json.load(open(os.path.join('/app/Generation/KWave/input_mesh', source['type'], 'meta.json')))
        # assert mesh_meta['nt'] == Nt, "Number of timesteps must match for each mesh"
        assert mesh_meta['dx'] == config['mesh']['dx'], "DX for source mesh must match computational mesh"
        assert mesh_meta['dy'] == config['mesh']['dy'], "DY for source mesh must match computational mesh"
        assert mesh_meta['dz'] == config['mesh']['dz'], "DZ for source mesh must match computational mesh"
        assert mesh_meta['dt'] == float(config['mesh']['dt']), "DT for source mesh must match computational mesh"
        xmin, xmax = get_mesh_bounds(xmin, xmax, source, mesh_meta, 'x', 'nx')
        ymin, ymax = get_mesh_bounds(ymin, ymax, source, mesh_meta, 'y', 'ny')
        zmin, zmax = get_mesh_bounds(zmin, zmax, source, mesh_meta, 'z', 'nz')
        if not source['type'] in mesh_readers:
            mesh_readers[source['type']] = MeshReader(os.path.join('/app/Generation/KWave/input_mesh', source['type']))
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

    # These functions consume lot of ram. gc.collect() is supposed to free that ram after it's not needed.
    if 'homogenous' in config and config['homogenous']:
        medium = kWaveMedium(sound_speed=343)
        medium.density = 1
    else:
        sound_speed = spheres_noise(kgrid, base_val=343, min_val=340, max_val=345, min_rad=5, max_rad=1024, seed=33, dbg_file='/app/Generation/KWave/c_noise.png')
        density_map = spheres_noise(kgrid, base_val=1.225, min_val=1.2, max_val=1.25, min_rad=5, max_rad=1024, seed=25, dbg_file='/app/Generation/KWave/density_noise.png')
        medium = kWaveMedium(sound_speed=sound_speed)
        gc.collect()
        medium.density = density_map
        gc.collect()
        for i, slice in enumerate(config['slices']):
            dirname = os.path.join(base_path, 'slices', str(i).zfill(3))
            if slice['axis'] == 'x':
                assert int(slice['position']) < sound_speed.shape[0]
                assert int(slice['position']) < density_map.shape[0]
                s_slice_data = sound_speed[int(slice['position']), :, :].copy()
                d_slice_data = density_map[int(slice['position']), :, :].copy()
            elif slice['axis'] == 'y':
                assert int(slice['position']) < sound_speed.shape[1]
                assert int(slice['position']) < density_map.shape[1]
                s_slice_data = sound_speed[:, int(slice['position']), :].copy()
                d_slice_data = density_map[:, int(slice['position']), :].copy()
            elif slice['axis'] == 'z':
                assert int(slice['position']) < sound_speed.shape[2]
                assert int(slice['position']) < density_map.shape[2]
                s_slice_data = sound_speed[:, :, int(slice['position'])].copy()
                d_slice_data = density_map[:, :, int(slice['position'])].copy()
            else:
                assert False, "Invalid export slice!"
            s_slice_data -= s_slice_data.min()
            s_slice_data /= s_slice_data.max()
            d_slice_data -= d_slice_data.min()
            d_slice_data /= d_slice_data.max()
            cv.imwrite(os.path.join(dirname, 'sound_speed.png'), (s_slice_data * 255).astype(np.uint8))
            cv.imwrite(os.path.join(dirname, 'density_map.png'), (d_slice_data * 255).astype(np.uint8))


    # Start GIF and MeshReader processes
    source = kSource()
    source.p_mask = np.zeros([kgrid.Nx, kgrid.Ny, kgrid.Nz], dtype=bool)
    source.p_mask[xmin:xmax, ymin:ymax, zmin:zmax] = 1
    n_src_points = (xmax - xmin) * (ymax - ymin) * (zmax - zmin)
    assert n_src_points == source.p_mask.sum(), "Something wrong with source mask"
    source.p = np.zeros([n_src_points, Nt], dtype=np.float32)
    try:
        old_shm = SharedMemory(name="source_p_shm")
        old_shm.close()
        old_shm.unlink()
    except Exception as e:
        pass
    source_p_shm = SharedMemory(name="source_p_shm", create=True, size=source.p.nbytes)
    shared_p = np.ndarray(source.p.shape, source.p.dtype, buffer=source_p_shm.buf)
    source_task_queue = Queue()
    source_task_out_queue = Queue()
    source_logger = logging.getLogger("source_worker")
    source_logger.setLevel(logging.DEBUG)
    source_log_handler = logging.FileHandler(os.path.join(bkp_proc_dir, 'source_worker.log'))
    source_log_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    ))
    source_logger.addHandler(source_log_handler)
    source_process = Process(target=worker_source, args=(
        source_task_queue, source_task_out_queue, source_logger, source_p_shm.name, shared_p.shape, shared_p.dtype, mesh_readers, source_bounds
    ))
    source_process.start()
    
    gif_task_queue = Queue()
    gif_logger = logging.getLogger("gif_worker")
    gif_logger.setLevel(logging.DEBUG)
    gif_log_handler = logging.FileHandler(os.path.join(bkp_proc_dir, 'gif_worker.log'))
    gif_log_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    ))
    gif_logger.addHandler(gif_log_handler)
    gif_process = Process(target=worker_gif, args=(gif_task_queue, gif_logger))
    gif_process.start()


    general_logger = logging.getLogger("general")
    general_logger.setLevel(logging.DEBUG)
    general_log_handler = logging.FileHandler(os.path.join(bkp_proc_dir, 'general.log'))
    general_log_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    ))
    general_logger.addHandler(general_log_handler)

    def cleanup():
        print("Terminating...")
        gif_task_queue.put(None)
        gif_process.join(timeout=15)
        if gif_process.is_alive():
            gif_process.terminate()
        source_task_queue.put(None)
        source_process.join(timeout=15)
        if source_process.is_alive():
            source_process.terminate()
        source_p_shm.unlink()
    atexit.register(cleanup)

    # Execution configuration
    sensor = kSensor()
    sensor.mask = np.ones([kgrid.Nx, kgrid.Ny, kgrid.Nz], dtype=bool)
    simulation_options = SimulationOptions(
        save_to_disk=True,
        data_cast="single",
    )
    execution_options = SimulationExecutionOptions(is_gpu_simulation=True)
    os.makedirs(proc_dir, exist_ok=True)
    os.makedirs(bkp_proc_dir, exist_ok=True)
    os.makedirs(result_dir, exist_ok=True)
    execution_options.checkpoint_file = os.path.join(proc_dir, 'ckpt.h5')
    execution_options.checkpoint_timesteps = Nt
    execution_options.output_file = os.path.join(proc_dir, 'output.h5')
    execution_options.binary_path = Path('/app/Generation/KWave/k-Wave-CPUGPU-src/kspaceFirstOrder-CUDA/kspaceFirstOrder-CUDA')
    execution_options.sampling_period = sampling_period

    # The Execution
    ckpt_time = 0
    n_samples_ready = 0
    start_step_idx = 0
    bkp_ckpt_file = str(execution_options.checkpoint_file).replace(proc_dir, bkp_proc_dir) + '.bkp'
    bkp_output_file = str(execution_options.output_file).replace(proc_dir, bkp_proc_dir) + '.bkp'
    if os.path.exists(bkp_ckpt_file):
        with h5py.File(bkp_ckpt_file, 'r') as f:
            ckpt_time = f['t_index'][0][0, 0]
            start_step_idx = int(ckpt_time/execution_options.checkpoint_timesteps)
        shutil.copy(bkp_ckpt_file, execution_options.checkpoint_file)
        shutil.copy(bkp_output_file, execution_options.output_file)
    if os.path.exists(result_dir):
        n_samples_ready = len([f.name for f in os.scandir(result_dir)])
    out_idx = n_samples_ready
    current_time = ckpt_time
    source_task_queue.put((current_time, current_time + Nt, config['sources']))
    general_logger.info(f"Putting source input from {current_time} to {current_time + Nt}")

    iteration = 0
    for step_idx in range(start_step_idx, 1000000):
        general_logger.info(f'Peak memory at step {iteration}: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB')
        iteration += 1
        execution_options.input_file = os.path.join(proc_dir, f'input_{step_idx}.h5')
        simulation_options.execution_options = execution_options
        curr_source_p = source_task_out_queue.get()
        assert source_task_out_queue.empty(), "Souce task result has not been processed!"
        assert curr_source_p[0] == current_time, "Wrong source time"
        assert curr_source_p[1] == current_time + Nt, "Wrong source time"
        source.p = shared_p.copy()
        source_task_queue.put((current_time + Nt, current_time + 2*Nt, config['sources']))
        general_logger.info(f"Putting source input from {current_time} to {current_time + Nt}")
        output = kspaceFirstOrder3D(kgrid, source, sensor, medium, simulation_options, execution_options)
        os.remove(execution_options.input_file)
        current_time = output['t_index']
        sensor_data = output["p"].T.reshape(kgrid.Nz, kgrid.Ny, kgrid.Nx, -1)
        start_idx = 0
        if np.sum(sensor_data[:, :, :, 0]) == 0:
            start_idx = 1
        
        # +1 due to the output at 0s step
        n_samples_prepared = int(output['t_index'] / sampling_period) - n_samples_ready
        if output['t_index'] % sampling_period > 0:
            n_samples_prepared += 1
        assert start_idx + n_samples_prepared <= sensor_data.shape[-1], "Wrong number of samples prepared"
        # assert np.sum(np.abs(sensor_data[:, :, :, start_idx + n_samples_prepared:])) == 0, "Skipping nonempty samples."
        n_samples_ready += n_samples_prepared
        for timestep_idx in range(start_idx, start_idx + n_samples_prepared):
            exported_sources = sensor_data[
                config['export']['z_start']:config['export']['z_end'], 
                config['export']['y_start']:config['export']['y_end'], 
                config['export']['x_start']:config['export']['x_end'], 
                timestep_idx
            ]
            np.save(os.path.join(result_dir, f'{str(out_idx).zfill(5)}.npy'), exported_sources)
            assert np.sum(exported_sources) != 0, "Something has gone wrong."
            for i, slice in enumerate(config['slices']):
                dirname = os.path.join(base_path, 'slices', str(i).zfill(3))
                if slice['axis'] == 'x':
                    assert int(slice['position']) < sensor_data.shape[2]
                    slice_data = sensor_data[:, :, int(slice['position']), timestep_idx]
                elif slice['axis'] == 'y':
                    assert int(slice['position']) < sensor_data.shape[1]
                    slice_data = sensor_data[:, int(slice['position']), :, timestep_idx]
                elif slice['axis'] == 'z':
                    assert int(slice['position']) < sensor_data.shape[0]
                    slice_data = sensor_data[int(slice['position']), :, :, timestep_idx]
                else:
                    assert False, "Invalid export slice!"
                save_slice_img(slice_data, dirname, out_idx, gif_task_queue)
            out_idx += 1
        if not os.path.exists(execution_options.checkpoint_file):
            with open(os.path.join(base_path, 'done.flag'), 'w') as fp:
                pass
            break
        # Check if the number of files generated matches the one recorded in checkpoint
        with h5py.File(str(execution_options.checkpoint_file), 'r') as f:
            out_ckpt_time = f['t_index'][0][0, 0]
            out_n_samples_ready = len([f.name for f in os.scandir(result_dir)])
            expected_samples = int(out_ckpt_time / sampling_period)
            # +1 due to the output at 0s step
            if out_ckpt_time % sampling_period > 0:
                expected_samples += 1
            assert expected_samples == out_n_samples_ready, "Number of samples number available does not match the expected number."

        if os.path.exists(execution_options.checkpoint_file):
            # If the outputs were saved successfully, save the checkpoint file in case if something goes wrong.
            shutil.copy(execution_options.checkpoint_file, bkp_ckpt_file)
            shutil.copy(execution_options.output_file, bkp_output_file)

if __name__ == '__main__':
    experiments_base = '/experiments'
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
