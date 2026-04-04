import numpy as np
from kwave.data import Vector
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