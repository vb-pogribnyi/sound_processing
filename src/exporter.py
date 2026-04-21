import os
import yaml
import shutil
import numpy as np
from scipy.spatial.transform import Rotation

DEBUG = True
if DEBUG:
    import cv2 as cv

def export(experiment, mics, angle_step):
    exp_descr_path = os.path.join('/app/Experiments', experiment, 'experiment.yml')
    exp_output_path = os.path.join('/app/Experiments', experiment, 'outputs')
    assert os.path.exists(exp_descr_path), "Invalid experiment"
    assert os.path.exists(exp_output_path), "Invalid experiment"
    out_files = [f.path for f in os.scandir(exp_output_path)]
    assert len(out_files) > 0, "Invalid experiment"
    exp_descr = yaml.load(open(exp_descr_path), Loader=yaml.FullLoader)
    export_path = os.path.join('/app/Experiments', experiment, 'export')
    if os.path.exists(export_path):
        shutil.rmtree(export_path)
    os.makedirs(export_path)
    angles = np.arange(-90, 90, angle_step)
    rot_z = Rotation.from_euler('z', angles, degrees=True)
    rot_x = Rotation.from_euler('x', angles, degrees=True)
    mics_z = np.stack([r.apply(mics) for r in rot_z])
    mics_x = np.stack([r.apply(mics) for r in rot_x])

    if DEBUG:
        imgsz = 256
        scale = imgsz / (np.max(mics) * 4)
        img_z = np.zeros((imgsz, imgsz, 3))
        mics_z -= np.min(mics_z)
        assert np.all([len(np.unique(mics_z[:, i, 2].round(4))) == 1 for i in range(mics_z.shape[1])]), "Wrong rotation"
        for cidx, rot_i in enumerate([0, 15, 25]):
            rot_vectors = mics_z[rot_i]
            # rot_vectors = mics
            for v in rot_vectors:
                img_z[int(v[0] * scale), int(v[1] * scale), [cidx]] = 255
        cv.imwrite(os.path.join(export_path, 'rots_z.png'), img_z)


if __name__ == "__main__":
    # Mics positions defined as x, y, z coordinates in METERS (not mesh positions)
    mics = np.array([
        [0.00, 0.00, 0.00],
        [0.05, 0.00, 0.00],
        [0.00, 0.07, 0.00],
        [0.05, 0.07, 0.00],
        [0.00, 0.00, 0.02],
        [0.05, 0.00, 0.02],
        [0.00, 0.07, 0.02],
        [0.05, 0.07, 0.02],
    ])
    export('001', mics, 5)
