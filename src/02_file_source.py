import matplotlib.pyplot as plt
import numpy as np
import cv2

from kwave.data import Vector
from kwave.kgrid import kWaveGrid
from kwave.kmedium import kWaveMedium
from kwave.ksensor import kSensor
from kwave.ksource import kSource
from kwave.kspaceFirstOrder3D import kspaceFirstOrder3D
from kwave.options.simulation_execution_options import SimulationExecutionOptions
from kwave.options.simulation_options import SimulationOptions

# import KWave.utils

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


def main():
    mesh = np.load('C:\\Users\\vbpoh\\Documents\\Dojo\\PhD\\REPOS\\00_MINE\\CircularSignal\\draw_mesh.npy')
    # grid properties
    # N = Vector([mesh.shape[0], mesh.shape[1], mesh.shape[2]])
    N = Vector([int(mesh.shape[0]*1.2), int(mesh.shape[1]*1.2), int(mesh.shape[2]*2)])
    d = Vector([0.001, 0.001, 0.0003])
    kgrid = kWaveGrid(N, d)
    kgrid.dt = 1e-7
    kgrid.Nt = mesh.shape[3]

    # medium properties
    # medium = kWaveMedium(sound_speed=np.ones(kgrid.k.shape) * 343)
    # medium.density = np.ones(kgrid.k.shape) * 1000
    medium = kWaveMedium(sound_speed=343)
    medium.density = 1000
    # kgrid.makeTime(np.min(medium.sound_speed))

    source = kSource()
    # add_source(source, kgrid, (N.x / 4 + 20, N.y / 4), np.sin(np.linspace(0, 6, 100)))
    # add_source(source, kgrid, (N.x * 3 / 4 - 20, N.y / 2), -np.cos(np.linspace(0, 6, 500)))
    source.p_mask = np.zeros([kgrid.Nx, kgrid.Ny, kgrid.Nz], dtype=bool)
    mesh_xstart = int(N.x // 2 - mesh.shape[0] // 2)
    mesh_xend = mesh_xstart + mesh.shape[0]
    mesh_ystart = int(N.y // 2 - mesh.shape[1] // 2)
    mesh_yend = mesh_ystart + mesh.shape[1]
    mesh_zstart = int(N.z // 2 - mesh.shape[2] // 2)
    mesh_zend = mesh_zstart + mesh.shape[2]
    source.p_mask[mesh_xstart:mesh_xend, mesh_ystart:mesh_yend, mesh_zstart:mesh_zend] = 1

    # source.p_mask = np.permute_dims(source.p_mask, (2, 1, 0))
    # source.p = np.permute_dims(mesh, [3, 0, 1, 2]).reshape(kgrid.Nt, -1)


    # signal_np = np.cos(np.linspace(0, 25, kgrid.Nt))
    # source.p = np.array([signal_np for m in source.p_mask.reshape(-1) if m > 0])
    # source.p = mesh.reshape(-1, kgrid.Nt)
    source.p = np.permute_dims(mesh, [2, 1, 0, 3]).reshape(-1, kgrid.Nt)

    # cv2.imwrite('source.png', (source.p_mask * 255).astype(np.uint8).T)

    sensor = kSensor()
    sensor.mask = np.ones_like(source.p_mask)
    simulation_options = SimulationOptions(
        save_to_disk=True,
        data_cast="single",
    )

    execution_options = SimulationExecutionOptions(is_gpu_simulation=True)
    output = kspaceFirstOrder3D(kgrid, source, sensor, medium, simulation_options, execution_options)
    sensor_data = output["p"].T.reshape(source.p_mask.shape[0], source.p_mask.shape[1], source.p_mask.shape[2], -1)

    np.save('sim_result.npy', output["p"])
    # =========================================================================
    # VISUALIZATION
    # =========================================================================
    for t in range(sensor_data.shape[-1]):
        if t % 1 != 0:
            continue
        
        figsize = (8, 6)
        plt.figure(figsize=figsize)
        maxval = np.amax(np.abs(sensor_data))
        print(np.min(sensor_data[kgrid.Nz // 2, :, :, t]), np.max(sensor_data[kgrid.Nz // 2, :, :, t]))
        print(np.min(sensor_data[:, :, :, t]), np.max(sensor_data[:, :, :, t]))
        print('-----------------------------------------------')
        plt.imshow(
            sensor_data[:, :, kgrid.Nz // 2, t].T,
            cmap="RdBu_r",
            vmin=-maxval,
            vmax=maxval,
            interpolation="nearest",
            aspect="auto",
        )
        plt.colorbar()
        plt.title(f"Wave propagation at step {t}")
        plt.axis("off")
        plt.show()



if __name__ == "__main__":
    main()
