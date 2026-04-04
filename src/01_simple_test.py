import matplotlib.pyplot as plt
import numpy as np
import cv2
import sys
sys.path.append('/app')

from kwave.data import Vector
from kwave.kgrid import kWaveGrid
from kwave.kmedium import kWaveMedium
from kwave.ksensor import kSensor
from kwave.ksource import kSource
from kwave.kspaceFirstOrder2D import kspaceFirstOrder2D
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
    # grid properties
    N = Vector([512, 512])
    d = Vector([0.5e-3, 0.25e-3])
    kgrid = kWaveGrid(N, d)

    # medium properties
    medium = kWaveMedium(sound_speed=np.ones(kgrid.k.shape) * 1500)
    # medium.sound_speed[100:200, 200:250] = 350
    medium.density = np.ones(kgrid.k.shape) * 1000
    medium.density[100:200, 200:250] = 2300
    kgrid.makeTime(np.min(medium.sound_speed))

    source = kSource()
    add_source(source, kgrid, (N.x / 4 + 20, N.y / 4), np.sin(np.linspace(0, 6, 100)))
    add_source(source, kgrid, (N.x * 3 / 4 - 20, N.y / 2), -np.cos(np.linspace(0, 6, 500)))
    source.p = np.array([p for p in source.p if p is not None])

    cv2.imwrite('source.png', (source.p_mask * 255).astype(np.uint8).T)

    sensor = kSensor()
    sensor.mask = np.ones_like(source.p_mask)
    simulation_options = SimulationOptions(
        save_to_disk=True,
        data_cast="single",
    )

    execution_options = SimulationExecutionOptions(is_gpu_simulation=True)
    output = kspaceFirstOrder2D(kgrid, source, sensor, medium, simulation_options, execution_options)
    sensor_data = output["p"].T.reshape(source.p_mask.shape[1], source.p_mask.shape[0], -1)

    # =========================================================================
    # VISUALIZATION
    # =========================================================================
    for t in range(sensor_data.shape[-1]):
        if t % 10 != 0:
            continue
        
        figsize = (8, 6)
        plt.figure(figsize=figsize)
        maxval = np.amax(np.abs(sensor_data))
        plt.imshow(
            sensor_data[:, :, t].T,
            cmap="RdBu_r",
            vmin=-maxval,
            vmax=maxval,
            interpolation="nearest",
            aspect="auto",
        )
        plt.colorbar()
        plt.title(f"Wave propagation at step {t}")
        plt.axis("off")
        plt.savefig(f"/app/step_{t}.png")
        plt.close()



if __name__ == "__main__":
    main()
