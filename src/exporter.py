import os
import yaml
import shutil
import numpy as np
from scipy.spatial.transform import Rotation
import cv2 as cv

def export(experiment, mics, sensors_direction, angle_step, debub_file=None):
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
    mics_xz = np.stack([r.apply(mics_z.reshape(-1, 3)) for r in rot_x]).reshape(len(rot_x), len(rot_z), mics.shape[0], mics.shape[1])


    directions_z = np.stack([r.apply(sensors_direction) for r in rot_z])
    directions_x = np.stack([r.apply(sensors_direction) for r in rot_x])

    size_x = exp_descr['export']['x_end'] - exp_descr['export']['x_start']
    size_y = exp_descr['export']['y_end'] - exp_descr['export']['y_start']
    size_z = exp_descr['export']['z_end'] - exp_descr['export']['z_start']

    # TODO: do the following in the loop, iterate over all possible sensor origins
    sensors_origin_x = size_x / 1.6 + exp_descr['export']['x_start']
    sensors_origin_y = size_y / 2 + exp_descr['export']['y_start']
    sensors_origin_z = size_z / 1.4 + exp_descr['export']['z_start']
    source_directions = []
    for source in exp_descr['sources']:
        source_size = 128 # TODO: load from meta.json
        source_size_z = 16 # TODO: load from meta.json
        dx = source['x'] + source_size / 2 - sensors_origin_x
        dy = source['y'] + source_size / 2 - sensors_origin_y
        dz = source['z'] + source_size_z / 2 - sensors_origin_z
        source_directions.append((dx, dy, dz))

    if debub_file is not None:
        img_z = np.zeros((exp_descr['mesh']['size_y'], exp_descr['mesh']['size_x'], 3), np.uint8) + 25
        mics_z = mics_xz[mics_xz.shape[0] // 2].copy()
        mics_z -= np.expand_dims(np.mean(mics_z, axis=1), 1)
        assert np.all([len(np.unique(mics_z[:, i, 2].round(4))) == 1 for i in range(mics_z.shape[1])]), "Wrong rotation"
        for cidx, rot_i in enumerate([0, mics_z.shape[0]//4*3, mics_z.shape[0]//2]):
            print('-----------------------------------')
            rot_vectors = mics_z[rot_i]
            for v in rot_vectors:
                img_z[round(v[1] / exp_descr['mesh']['dy'] + sensors_origin_y), round(v[0] / exp_descr['mesh']['dx'] + sensors_origin_x), [cidx]] = 255
            # Draw general direction of the array
            line_color = [0, 0, 0]
            line_color[cidx] = 255
            sensor_direction_x = directions_z[rot_i][0][0]
            sensor_direction_y = directions_z[rot_i][0][1]
            cv.line(img_z, 
                    (int(sensors_origin_x), int(sensors_origin_y)), 
                    (int(sensors_origin_x + sensor_direction_x/exp_descr['mesh']['dx']), int(sensors_origin_y + sensor_direction_y/exp_descr['mesh']['dy'])), 
                    line_color, 2)
            for source in source_directions:
                cv.line(img_z, 
                        (int(sensors_origin_x), int(sensors_origin_y)), 
                        (int(sensors_origin_x + source[0]), int(sensors_origin_y + source[1])), 
                        line_color, 1)
                a = np.array([sensor_direction_x, sensor_direction_y, 0])
                b = np.array([source[0], source[1], 0])
                cos_angle = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
                angle = np.degrees(np.arccos(np.clip(cos_angle, -1.0, 1.0)))
                cross = np.cross(a, b)
                axis = [0, 0, 1]
                if np.dot(cross, axis) < 0:
                    angle = -angle
                print("Angle:", angle)
        # cv.imwrite(os.path.join(export_path, 'rots_z.png'), img_z)

        # TODO: Is this a dublication?
        img_x = np.zeros((exp_descr['mesh']['size_y'], exp_descr['mesh']['size_z'], 3), np.uint8) + 25
        mics_x = mics_xz[:, mics_xz.shape[0] // 2].copy()
        mics_x -= np.expand_dims(np.mean(mics_x, axis=1), 1)
        assert np.all([len(np.unique(mics_x[:, i, 0].round(4))) == 1 for i in range(mics_x.shape[1])]), "Wrong rotation"
        for cidx, rot_i in enumerate([mics_x.shape[0]//2-1, mics_x.shape[0]//2+1, mics_x.shape[0]//2]):
            print('-----------------------------------')
            rot_vectors = mics_x[rot_i]
            for v in rot_vectors:
                img_x[round(v[1] / exp_descr['mesh']['dy'] + sensors_origin_y), round(v[2] / exp_descr['mesh']['dz'] + sensors_origin_z), [cidx]] = 255
            # Draw general direction of the array
            line_color = [0, 0, 0]
            line_color[cidx] = 255
            sensor_direction_z = directions_x[rot_i][0][2]
            sensor_direction_y = directions_x[rot_i][0][1]
            cv.line(img_x, 
                    (int(sensors_origin_z), int(sensors_origin_y)), 
                    (int(sensors_origin_z + sensor_direction_z/exp_descr['mesh']['dz']), int(sensors_origin_y + sensor_direction_y/exp_descr['mesh']['dy'])), 
                    line_color, 2)
            for source in source_directions:
                cv.line(img_x, 
                        (int(sensors_origin_z), int(sensors_origin_y)), 
                        (int(sensors_origin_z + source[2]), int(sensors_origin_y + source[1])), 
                        line_color, 1)
                a = np.array([sensor_direction_z, sensor_direction_y, 0])
                b = np.array([source[2], source[1], 0])
                cos_angle = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
                angle = np.degrees(np.arccos(np.clip(cos_angle, -1.0, 1.0)))
                cross = np.cross(a, b)
                axis = [0, 0, 1]
                if np.dot(cross, axis) < 0:
                    angle = -angle
                print("Angle:", angle)
        
        debug_img = np.zeros((img_z.shape[0], img_z.shape[1] + img_x.shape[1] + 5, 3), np.uint8)
        debug_img[:, :img_z.shape[1]] = img_z
        debug_img[:, img_z.shape[1] + 5:] = img_x
        cv.imwrite(os.path.join(export_path, debub_file), debug_img)


if __name__ == "__main__":
    # Mics positions defined as x, y, z coordinates in METERS (not mesh positions)
    mics = np.array([
        [0.00, 0.00, 0.00],
        [0.05, 0.00, 0.00],
        [0.00, 0.07, 0.00],
        [0.05, 0.07, 0.00],
        [0.00, 0.00, 0.002],
        [0.05, 0.00, 0.002],
        [0.00, 0.07, 0.002],
        [0.05, 0.07, 0.002],
    ])
    sensors_direction = np.array([[0, -1, 0]])
    export('001', mics, sensors_direction, 5, 'debug_img.png')
