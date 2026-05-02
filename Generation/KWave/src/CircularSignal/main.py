import os
import json
import numpy as np
from tqdm import tqdm
from Mesh import Mesh
from PlaneReader import PlaneReader
from SourceDrawer import SourceDrawer

profile = '01_sphere'
profiles = ['01_sphere', '02_cylinder', '03_diff_cylinder', '04_diff2_cylinder']

dt = 1e-7
rpm = 3500
rps = rpm / 60      # revolutions per second
nblades=1
nbladess = [1, 2, 3]
ndivs = 150
mesh_div = 0.002    # 2 mm mesh step
mesh_divs = [0.002, 0.02]
if rps == 0:
    tmax = 1e-5
else:
    tmax = 1 / rps / nblades / ndivs      # time of 1 revolution

for profile in profiles:
    for nblades in nbladess:
        for mesh_div in mesh_divs:
            print('Generating:', profile, nblades, mesh_div)
            plane_reader = PlaneReader(f'/app/src/CircularSignal/profiles/{profile}')
            nt = int(tmax / dt)
            print(dt, nt, ndivs)
            # The mesh step is given in meters. E.g. 
            # mesh 128x128 with step 0.00234 is 30x30 cm
            # dz of 0.000625 m gives 8 steps for the thickness of 0.005 m
            ncells_x = round(0.3 / mesh_div)
            ncells_y = round(0.3 / mesh_div)
            ncells_z = round(0.03 / mesh_div)
            mesh = Mesh(nx=ncells_x, ny=ncells_y, nz=ncells_z, nt=nt,
                        dx=mesh_div, dy=mesh_div, dz=mesh_div, dt=dt)
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
            mesh_path = os.path.join('input_mesh', profile, str(dt), str(nblades), str(mesh_div))
            os.makedirs(mesh_path, exist_ok=True)
            json.dump(meta, open(f'{mesh_path}/meta.json', 'w'), indent=4)
            source_drawer = SourceDrawer(
                mesh=mesh,
                plane_reader=plane_reader,
                nblades=nblades,
                blade_length=0.1,       # 10 cm
                blade_width=0.015,      # 1.5 cm
                blade_thickness=0.015   # 15 mm - whole plane; signal itself will be thinner
            )
            angle = 0
            for mesh_idx in tqdm(range(ndivs), position=0):
                mesh.mesh *= 0
                angle = source_drawer.draw(0.5, 0.5, 0.5, rpm=rpm, start_angle=angle)

                # current = np.nan_to_num(np.load(f'input_mesh/{str(mesh_idx).zfill(3)}.npz')['arr_0'])
                np.savez_compressed(os.path.join(mesh_path, f'{str(mesh_idx).zfill(3)}.npz'), mesh.mesh)

print('done')
