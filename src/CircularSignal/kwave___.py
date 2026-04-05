import h5py
import numpy as np
from datetime import datetime
import cv2 as cv

kwave_input = {
    # 1. Simulation flags

    'ux_source_flag': 0,
    'uy_source_flag': 0,
    'uz_source_flag': 0,
    'p_source_flag': 0,         # <--- N source timesteps
    'p0_source_flag': 0,
    'transducer_source_flag': 0,
    'nonuniform_grid_flag': 0,
    'nonlinear_flag': 0,
    'absorbing_flag': 0,
    'axisymmetric_flag': 0,

    # 2. Grid properties

    'Nx': 128,
    'Ny': 256,
    'Nz': 1,
    'Nt': 500,
    'dx': 0.001,
    'dy': 0.001,
    'dz': 0.001,
    'dt': 1e-7,

    # 3. Medium properties

    'rho0': None,               # <--- (Nx, Ny, Nz)
    'rho0_sgx': None,               # <--- (Nx, Ny, Nz)
    'rho0_sgy': None,               # <--- (Nx, Ny, Nz)
    'rho0_sgz': None,               # <--- (Nx, Ny, Nz)
    'c0': None,               # <--- (Nx, Ny, Nz)
    'c_ref': 360.0,               # Base speed of sound
    # # Nonlinear properties
    # 'BonA': None,               # <--- (Nx, Ny, Nz)
    # # Absorbing properties
    # 'alpha_coef': None,               # <--- (Nx, Ny, Nz)
    # 'alpha_power': 0.8,

    # 4. Sensor Variables

    'sensor_mask_type': 0,
    'sensor_mask_index': None,               # <--- (Nsens, 1, 1)
    # 'sensor_mask_corners': None,               # <--- (Nsens, 6, 1)

    # 5. Source properties

    # 'u_source_mode': 0,
    # 'u_source_many': 0,
    # 'u_source_index': 0,               # <--- (Nsrc, 1, 1)
    # 'ux_source_input': 0,               # <--- (1, Nt_src, 1)
    # 'uy_source_input': 0,               # <--- (1, Nt_src, 1)
    # 'uz_source_input': 0,               # <--- (1, Nt_src, 1)
    'p_source_mode': 2,
    'p_source_many': 1,
    'p_source_index': [],               # <--- (Nsrc, 1, 1)
    'p_source_input': [],               # <--- (Nsrc, Nt_src, 1)

    # 6. <Skipping>

    # 7. PML Variables

    'pml_x_size': 20,
    'pml_y_size': 20,
    'pml_z_size': 20,
    'pml_x_alpha': 2,
    'pml_y_alpha': 2,
    'pml_z_alpha': 2,
}

kwave_output = {
    # 1. Simulation flags

    'ux_source_flag': 0,
    'uy_source_flag': 0,
    # 'uz_source_flag': 0,
    'p0_source_flag': 0,
    'transducer_source_flag': 0,
    'nonuniform_grid_flag': 0,
    'nonlinear_flag': 0,
    'absorbing_flag': 0,
    'axisymmetric_flag': 0,
    # 'u_source_mode': 0,
    # 'u_source_many': 0,
    # 'p_source_mode': 0,
    # 'p_source_many': 0,

    # 2. Grid properties

    'Nx': 256,
    'Ny': 256,
    'Nz': 1,
    # 't_index': 1,
    'Nt': 1024,
    'dx': 0.001,
    'dy': 0.001,
    # 'dz': 0.001,

    # 3. PML Variables

    'pml_x_size': 20,
    'pml_y_size': 20,
    # 'pml_z_size': 20,
    'pml_x_alpha': 2,
    'pml_y_alpha': 2,
    # 'pml_z_alpha': 2,
    'sensor_mask_type': 0,
    'sensor_mask_index': [],
    # 'sensor_mask_corners': [],
}



# h5literals =         {
#     # data type
#     "DATA_TYPE_ATT_NAME": "data_type",
#     "MATRIX_DATA_TYPE_MATLAB": "single",
#     "MATRIX_DATA_TYPE_C": "float",
#     "INTEGER_DATA_TYPE_MATLAB": "uint64",
#     "INTEGER_DATA_TYPE_C": "long",
#     # real / complex
#     "DOMAIN_TYPE_ATT_NAME": "domain_type",
#     "DOMAIN_TYPE_REAL": "real",
#     "DOMAIN_TYPE_COMPLEX": "complex",
#     # file descriptors
#     "FILE_MAJOR_VER_ATT_NAME": "major_version",
#     "FILE_MINOR_VER_ATT_NAME": "minor_version",
#     "FILE_DESCR_ATT_NAME": "file_description",
#     "FILE_CREATION_DATE_ATT_NAME": "creation_date",
#     "CREATED_BY_ATT_NAME": "created_by",
#     # file type
#     "FILE_TYPE_ATT_NAME": "file_type",
#     "HDF_INPUT_FILE": "input",
#     "HDF_OUTPUT_FILE": "output",
#     "HDF_CHECKPOINT_FILE": "checkpoint",
#     # file version information
#     "HDF_FILE_MAJOR_VERSION": "1",
#     "HDF_FILE_MINOR_VERSION": "2",
#     # compression level
#     "HDF_COMPRESSION_LEVEL": 0,
# }


h5attributes = {
    'file_type': 'input',
    'created_by': 'k-Wave',
    'creation_date': datetime.now().strftime("%d-%b-%Y-%H-%M-%S"),
    'file_description': "Drawed source simulation",
    'major_version': '1',
    'minor_version': '2'
}

def save_file(filename):
    global kwave_input

    with h5py.File(filename, "w") as f:
        for matrix_name in kwave_input:


            # if 'sensor_mask_index' in matrix_name:
            #     d = 0


            if type(kwave_input[matrix_name]).__name__ == 'int' or (
                        'ndarray' in type(kwave_input[matrix_name]).__name__ and 
                        'int' in str(kwave_input[matrix_name].dtype)
                ):
                data_type = 'long'
                value = np.array(kwave_input[matrix_name], dtype=np.int64)
            else:
                data_type = 'float'
                value = np.array(kwave_input[matrix_name], dtype=np.float32)

            dims = len(value.shape)

            if dims == 3:
                value = np.transpose(value, [2, 1, 0])  # C <=> Fortran ordering
            if dims == 2:
                value = np.transpose(value)  # C <=> Fortran ordering

            for _ in range(dims, 3):
                value = np.expand_dims(value, -1)
            ds = f.create_dataset(f"/{matrix_name}", value.shape, data=value)
            ds.attrs.create(f"data_type", data_type, None, dtype=f"<S{len(data_type)}")
            ds.attrs.create(f"domain_type", 'real', None, dtype=f"<S{len('real')}")
        for attr_name in h5attributes:
            f.attrs.create(attr_name, h5attributes[attr_name], None, dtype=f"<S{len(h5attributes[attr_name])}")

def show_result(filename):
    with h5py.File(filename, "r") as f:
        print("Keys in the file:", list(f.keys()))
        # Access the dataset object
        dset = f['p']

        # Print some dataset properties
        print(f"Dataset shape: {dset.shape}")
        print(f"Dataset dtype: {dset.dtype}")
        imgs = dset[0]
        nsteps = 100
        for i in range(nsteps):
            step = imgs.shape[0] // nsteps * i
            img = imgs[step].reshape([kwave_input['Nz'], kwave_input['Ny'], kwave_input['Nx']])
            img[0][0] = 0

            print(f'Step {step}/{imgs.shape[0]}, {img.max()}-{img.min()}')
            disp_img = np.stack([img[0, :, :], img[0, :, :], img[0, :, :]], axis=-1)
            disp_img[:, :, 0][disp_img[:, :, 0] < 0] = 0
            disp_img[:, :, 1] = np.abs(disp_img[:, :, 1])
            disp_img[:, :, 2][disp_img[:, :, 2] > 0] = 0
            disp_img[:, :, 2] *= -1
            # img = img - img.min()
            # disp_img = disp_img / (disp_img.max() + 1e-15) 
            disp_img = disp_img / 1e-5   
            cv.imshow('', cv.resize(disp_img, (disp_img.shape[1] * 3, disp_img.shape[0] * 3)))
            cv.waitKey()
            

        # Read the entire dataset into a NumPy array
        # data_array = dset[:]
        # print(f"Data array content:\n{data_array}")


if __name__ == '__main__':
    kwave_input['rho0'] = np.ones([kwave_input['Nx'], kwave_input['Ny'], kwave_input['Nz']], dtype=float) * 1000

    
        # k_sim.rho0_sgx = interpolate2d(grid_points, k_sim.rho0, [k_sim.kgrid.x + k_sim.kgrid.dx / 2, k_sim.kgrid.y])
        # k_sim.rho0_sgy = interpolate2d(grid_points, k_sim.rho0, [k_sim.kgrid.x, k_sim.kgrid.y + k_sim.kgrid.dy / 2])
    # kwave_input['rho0_sgx'] = interpolate2d(grid_points, kwave_input['rho0'], [k_sim.kgrid.x + k_sim.kgrid.dx / 2, k_sim.kgrid.y])
    # kwave_input['rho0_sgy'] = np.ones([kwave_input['Nx'], kwave_input['Ny'], kwave_input['Nz']], dtype=float)

    kwave_input['rho0_sgx'] = kwave_input['rho0']
    kwave_input['rho0_sgy'] = kwave_input['rho0']
    kwave_input['rho0_sgz'] = np.ones([kwave_input['Nx'], kwave_input['Ny'], kwave_input['Nz']], dtype=float)
    kwave_input['c0'] = np.ones([kwave_input['Nx'], kwave_input['Ny'], kwave_input['Nz']], dtype=float)

    nsens = kwave_input['Nx'] * kwave_input['Ny'] * kwave_input['Nz']
    nsrc = 4
    ntsrc = 250
    kwave_input['sensor_mask_index'] = np.arange(0, nsens, dtype=np.int64).reshape([nsens, 1, 1])
    kwave_input['p_source_index'] = np.arange(0, nsrc, dtype=np.int64).reshape([nsrc, 1, 1])
    kwave_input['p_source_input'] = np.zeros([nsrc, ntsrc, 1], dtype=float)

    signal = np.sin(np.linspace(0, 6, ntsrc)) * 1e-2
    kwave_input['p_source_input'][0, :, 0] += signal
    kwave_input['p_source_input'][1, :, 0] += signal
    kwave_input['p_source_input'][2, :, 0] += signal
    kwave_input['p_source_input'][3, :, 0] += signal

    kwave_input['p_source_flag'] = ntsrc
    
    save_file('input_brad.h5')

    show_result('delme.h5')
