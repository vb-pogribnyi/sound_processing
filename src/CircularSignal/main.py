import os
import json
import numpy as np
from Mesh import Mesh
from PlaneReader import PlaneReader
from SourceDrawer import SourceDrawer

plane_reader = PlaneReader('/app/src/CircularSignal/profiles/00_test')

dt = 1e-6
rpm = 3700
rps = rpm / 60      # revolutions per second
nblades=3
ndivs = 10
tmax = 1 / rps / nblades / ndivs      # time of 1 revolution
nt = int(tmax / dt)
print(dt, nt, ndivs)
# The mesh step is given in meters. E.g. 
# mesh 128x128 with step 0.00234 is 30x30 cm
# dz of 0.000625 m gives 8 steps for the thickness of 0.005 m
mesh = Mesh(nx=128, ny=128, nz=16, nt=nt,
            dx=0.00234, dy=0.00234, dz=0.000625, dt=dt)
meta = {
    'dt': dt,
    'dx': mesh.dx,
    'dy': mesh.dy,
    'dz': mesh.dz,
    'nx': mesh.mesh.shape[0],
    'ny': mesh.mesh.shape[1],
    'nz': mesh.mesh.shape[2],
    'nt': mesh.mesh.shape[3]
}
os.makedirs('input_mesh', exist_ok=True)
json.dump(meta, open('input_mesh/meta.json', 'w'), indent=4)
source_drawer = SourceDrawer(
    mesh=mesh,
    plane_reader=plane_reader,
    nblades=nblades,
    blade_length=0.1,       # 10 cm
    blade_width=0.015,      # 1.5 cm
    blade_thickness=0.005   # 5 mm
)
os.makedirs('input_mesh', exist_ok=True)
angle = 0
for mesh_idx in range(ndivs):
    mesh.mesh *= 0
    angle = source_drawer.draw(0.5, 0.5, 0.5, rpm=rpm, start_angle=angle)

    # current = np.nan_to_num(np.load(f'input_mesh/{str(mesh_idx).zfill(3)}.npz')['arr_0'])
    np.savez_compressed(f'input_mesh/{str(mesh_idx).zfill(3)}.npz', mesh.mesh)

print('done')
