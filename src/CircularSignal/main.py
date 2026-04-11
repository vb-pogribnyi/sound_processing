import os
import json
import numpy as np
from Mesh import Mesh
from PlaneReader import PlaneReader
from SourceDrawer import SourceDrawer

plane_reader = PlaneReader('/app/src/CircularSignal/profiles/00_test')

# plane_reader.sample(0.1, 0.1, 0.42, debug=True)
# plane_reader.sample(0.3, 0.1, 0.42, debug=True)
# plane_reader.sample(0.45, 0.1, 0.42, debug=True)
# plane_reader.sample(0.45, 0.1, 0.43, debug=True)
# plane_reader.sample(0.45, 0.1, 0.44, debug=True)
# plane_reader.sample(0.45, 0.15, 0.44, debug=True)
# plane_reader.sample(0.45, 0.25, 0.44, debug=True)

dt = 1e-6
rpm = 3700
rps = rpm / 60      # revolutions per second
nblades=3
ndivs = 10
tmax = 1 / rps / nblades / ndivs      # time of 1 revolution
nt = int(tmax / dt)
print(dt, nt, ndivs)
# mesh = Mesh(nx=700, ny=700, nz=30, nt=nt,
#             dx=0.001, dy=0.001, dz=0.0003, dt=dt)
mesh = Mesh(nx=128, ny=128, nz=16, nt=nt,
            dx=0.001, dy=0.001, dz=0.0003, dt=dt)
meta = {
    'dt': dt,
    'dx': mesh.dx,
    'dy': mesh.dy,
    'dz': mesh.dz
}
json.dump(meta, open('input_mesh/meta.json', 'w'), indent=4)
source_drawer = SourceDrawer(
    mesh=mesh,
    plane_reader=plane_reader,
    nblades=nblades,
    blade_length=0.03,       # 10 cm
    blade_width=0.005,      # 1.5 cm
    blade_thickness=0.0015   # 5 mm
)
os.makedirs('input_mesh', exist_ok=True)
angle = 0
for mesh_idx in range(ndivs):
    mesh.mesh *= 0
    angle = source_drawer.draw(0.5, 0.5, 0.5, rpm=rpm, start_angle=angle)

    np.save(f'input_mesh/{str(mesh_idx).zfill(3)}.npy', mesh.mesh)

print('done')
