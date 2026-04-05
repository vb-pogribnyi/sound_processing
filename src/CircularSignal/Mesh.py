import numpy as np

class Mesh:
    def __init__(self, nx, ny, nz, nt, dx, dy, dz, dt):
        self.mesh = np.zeros([nx, ny, nz, nt], dtype=np.float16)
        self.dx = dx
        self.dy = dy
        self.dz = dz
        self.dt = dt
    
    def nt(self):
        return self.mesh.shape[-1]
    
    def sizex(self):
        return self.mesh.shape[0] * self.dx
    
    def sizey(self):
        return self.mesh.shape[1] * self.dy
    
    def sizez(self):
        return self.mesh.shape[2] * self.dz
    
    def coord2idx(self, x, y, z):
        idx_x = max(0, min(self.mesh.shape[0], int(x / self.dx)))
        idx_y = max(0, min(self.mesh.shape[1], int(y / self.dy)))
        idx_z = max(0, min(self.mesh.shape[2], int(z / self.dz)))

        return (idx_x, idx_y, idx_z)
    
    def idx2coord(self, idx_x, idx_y, idx_z):
        return idx_x * self.dx, idx_y * self.dy, idx_z * self.dz