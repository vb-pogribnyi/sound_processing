import os
import yaml
import json
import shutil
import numpy as np
from scipy.spatial.transform import Rotation
import cv2 as cv
from tqdm import tqdm
import pickle
import copy

def export(experiment, mics, sensors_direction, angle_step, space_step, debug_file=None):
    exp_descr_path = os.path.join('/experiments', experiment, 'experiment.yml')
    exp_output_path = os.path.join('/experiments', experiment, 'outputs')
    assert os.path.exists(exp_descr_path), "Invalid experiment"
    assert os.path.exists(exp_output_path), "Invalid experiment"
    out_files = sorted([f.path for f in os.scandir(exp_output_path)])
    assert len(out_files) > 0, "Invalid experiment"
    exp_descr = yaml.load(open(exp_descr_path), Loader=yaml.FullLoader)
    export_path = os.path.join('/experiments', experiment, 'export')
    exp_result_dir = os.path.join(export_path, 'compiled_values')
    exp_result_path = os.path.join(export_path, 'exported.pkl')
    if os.path.exists(export_path):
        shutil.rmtree(export_path)
    os.makedirs(export_path)
    angles = np.arange(-90, 90, angle_step)
    rotations_z = Rotation.from_euler('z', angles, degrees=True)
    rotations_x = Rotation.from_euler('x', angles, degrees=True)
    os.makedirs(exp_result_dir, exist_ok=True)
    mics_z = np.stack([r.apply(mics) for r in rotations_z])
    mics_xz = np.stack([r.apply(mics_z.reshape(-1, 3)) for r in rotations_x]).reshape(len(rotations_x), len(rotations_z), mics.shape[0], mics.shape[1])


    directions_z = np.stack([r.apply(sensors_direction) for r in rotations_z])
    directions_x = np.stack([r.apply(sensors_direction) for r in rotations_x])

    mics_xz -= np.expand_dims(np.mean(mics_xz, axis=2), 2)
    result = {}

    for sensors_origin_x in tqdm(np.arange(exp_descr['export']['x_start'], exp_descr['export']['x_end'], space_step[0]), position=0):
        for sensors_origin_y in tqdm(np.arange(exp_descr['export']['y_start'], exp_descr['export']['y_end'], space_step[1]), position=1, leave=False):
            for sensors_origin_z in tqdm(np.arange(exp_descr['export']['z_start'], exp_descr['export']['z_end'], space_step[2]), position=2, leave=False):
                key_position = (sensors_origin_x, sensors_origin_y, sensors_origin_z)
                result[key_position] = {}
                source_directions = []
                for source in exp_descr['sources']:
                    mesh_meta = json.load(open(os.path.join('/app/input_mesh', source['type'], 'meta.json'))) 
                    dx = source['x'] + mesh_meta['nx'] / 2 - sensors_origin_x
                    dy = source['y'] + mesh_meta['ny'] / 2 - sensors_origin_y
                    dz = source['z'] + mesh_meta['nz'] / 2 - sensors_origin_z
                    source_directions.append((dx * mesh_meta['dx'], dy * mesh_meta['dy'], dz * mesh_meta['dz']))
                avg_direction = np.mean(source_directions, axis=0)
                directions_relative_x = np.stack([r.inv().apply(avg_direction) for r in rotations_x])
                directions_relative_xz = np.stack([r.inv().apply(directions_relative_x) for r in rotations_z])
                
                for rot_z in range(len(angles)):
                    for rot_x in range(len(angles)):
                        key_rotation = (angles[rot_z], angles[rot_x])
                        array_snapshot = {}
                        array_snapshot['sensor_direction_zx'] = directions_z[rot_z][0][0]
                        array_snapshot['sensor_direction_zy'] = directions_z[rot_z][0][1]
                        array_snapshot['sensor_direction_xz'] = directions_x[rot_x][0][2]
                        array_snapshot['sensor_direction_xy'] = directions_x[rot_x][0][1]
                        array_snapshot['mic_positions'] = []
                        array_snapshot['mic_values'] = [[] for _ in mics_xz[rot_x, rot_z]]
                        is_positions_valid = True
                        for mic_idx, mic in enumerate(mics_xz[rot_x, rot_z]):
                            # Check if sensor data at this position/rotation is supposed to be present at all
                            mic_out_idx_x = round(mic[0] / exp_descr['mesh']['dx'] + sensors_origin_x)
                            mic_out_idx_y = round(mic[1] / exp_descr['mesh']['dy'] + sensors_origin_y)
                            mic_out_idx_z = round(mic[2] / exp_descr['mesh']['dz'] + sensors_origin_z)
                            if mic_out_idx_x < exp_descr['export']['x_start'] or mic_out_idx_x >= exp_descr['export']['x_end']:
                                is_positions_valid = False
                            if mic_out_idx_y < exp_descr['export']['y_start'] or mic_out_idx_y >= exp_descr['export']['y_end']:
                                is_positions_valid = False
                            if mic_out_idx_z < exp_descr['export']['z_start'] or mic_out_idx_z >= exp_descr['export']['z_end']:
                                is_positions_valid = False
                            if not is_positions_valid:
                                break
                            mic_out_idx_x -= exp_descr['export']['x_start']
                            mic_out_idx_y -= exp_descr['export']['y_start']
                            mic_out_idx_z -= exp_descr['export']['z_start']

                            mic_pos_x = round(mic[0] / exp_descr['mesh']['dx'] + sensors_origin_x)
                            mic_pos_y = round(mic[1] / exp_descr['mesh']['dy'] + sensors_origin_y)
                            mic_pos_z = round(mic[2] / exp_descr['mesh']['dz'] + sensors_origin_z)
                            assert mic_pos_x >= exp_descr['export']['x_start']
                            assert mic_pos_x < exp_descr['export']['x_end']
                            assert mic_pos_y >= exp_descr['export']['y_start']
                            assert mic_pos_y < exp_descr['export']['y_end']
                            assert mic_pos_z >= exp_descr['export']['z_start']
                            assert mic_pos_z < exp_descr['export']['z_end']
                            array_snapshot['mic_positions'].append([mic_pos_x, mic_pos_y, mic_pos_z])
                            # Indices of the data items in out_files. To be filled with actual data later - to reduce file reads
                            array_snapshot['mic_values'][mic_idx].append((
                                mic_out_idx_z,
                                mic_out_idx_y,
                                mic_out_idx_x
                            ))
                        array_snapshot['source_relative'] = directions_relative_xz[rot_z, rot_x]
                        array_snapshot['source_relative'][2] *= -1
                        if not is_positions_valid:
                            continue
                            
                        array_snapshot['sources'] = []
                        for source in source_directions:
                            xa = np.array([array_snapshot['sensor_direction_xz'], array_snapshot['sensor_direction_xy'], 0])
                            xb = np.array([source[2], source[1], 0])
                            cos_anglex = np.dot(xa, xb) / (np.linalg.norm(xa) * np.linalg.norm(xb))
                            anglex = np.degrees(np.arccos(np.clip(cos_anglex, -1.0, 1.0)))
                            crossx = np.cross(xa, xb)
                            axis = [0, 0, 1]
                            if np.dot(crossx, axis) < 0:
                                anglex = -anglex
                            
                            za = np.array([array_snapshot['sensor_direction_zx'], array_snapshot['sensor_direction_zy'], 0])
                            zb = np.array([source[0], source[1], 0])
                            cos_anglez = np.dot(za, zb) / (np.linalg.norm(za) * np.linalg.norm(zb))
                            anglez = np.degrees(np.arccos(np.clip(cos_anglez, -1.0, 1.0)))
                            crossz = np.cross(za, zb)
                            if np.dot(crossz, axis) < 0:
                                anglez = -anglez
                            array_snapshot['sources'].append({
                                'angle_x': anglex,
                                'angle_z': anglez
                            })

                        result[key_position][key_rotation] = array_snapshot

    print("Filling with data...")
    result = {r: result[r] for r in result if len(result[r]) > 0}
    step_result = copy.deepcopy(result)
    for out_file_idx, out_file in tqdm(enumerate(out_files), position=0):
        # if out_file_idx > 4:
        #     continue
        out_data = np.load(out_file)
        for position in tqdm(result, position=1, leave=False):
            for rotation in tqdm(result[position], position=2, leave=False):
                for mic_id, mic_value in enumerate(result[position][rotation]['mic_values']):
                    step_result[position][rotation]['mic_values'][mic_id] = out_data[mic_value[0]]
        pickle.dump(step_result, open(os.path.join(exp_result_dir, f'{str(out_file_idx).zfill(5)}.pkl'), 'wb'))
    print('Dumping into file...')
    pickle.dump(result, open(exp_result_path, 'wb'))

    print("Creating debug image.")
    if debug_file is not None:
        text_coord = 5
        angles_z = [-70, 0, 30]
        angles_x = [-5, 0, 5]
        sensors_origin = None
        for rkey in result:
            angle_z_keys = [(angle_z, 0) for angle_z in angles_z]
            angle_x_keys = [(0, angle_x) for angle_x in angles_x]
            if np.all([akey in result[rkey] for akey in angle_z_keys]) and np.all([akey in result[rkey] for akey in angle_x_keys]):
                sensors_origin = rkey
                break
        assert sensors_origin is not None, "Unable to find origin suitable for debug image."
        # sensors_origin = list(result.keys())[0]
        result_item = result[sensors_origin]
        img_z = np.zeros((exp_descr['mesh']['size_y'], exp_descr['mesh']['size_x'], 3), np.uint8) + 25
        for cidx, angle_z in enumerate(angles_z):
            array_snapshot = result_item[(angle_z, 0)]
            for v in array_snapshot['mic_positions']:
                img_z[v[1], v[0], [cidx]] = 255

            # Draw general direction of the array
            line_color = [0, 0, 0]
            line_color[cidx] = 255
            sensors_direction = [
                array_snapshot['sensor_direction_zx'],
                array_snapshot['sensor_direction_zy'],
                0
            ]
            cv.line(img_z, 
                    (int(sensors_origin[0]), int(sensors_origin[1])), 
                    (int(sensors_origin[0] + sensors_direction[0]/exp_descr['mesh']['dx']), int(sensors_origin[1] + sensors_direction[1]/exp_descr['mesh']['dy'])), 
                    line_color, 2)
            # Draw directions to the sources
            for source in array_snapshot['sources']:
                r = Rotation.from_euler('z', source['angle_z'], degrees=True)
                rotated = r.apply(sensors_direction)*1000
                cv.line(img_z, 
                        (int(sensors_origin[0]), int(sensors_origin[1])), 
                        (int(sensors_origin[0] + rotated[0]), int(sensors_origin[1] + rotated[1])), 
                        line_color, 1)
                cv.putText(img_z, str(int(source['angle_z'] * 10) / 10), (10, img_z.shape[0] - text_coord), cv.FONT_HERSHEY_SIMPLEX, 0.3, line_color, 1)
                text_coord += 12
                print("AngleZ:", source['angle_z'])
            source_relative = f"{int(array_snapshot['source_relative'][0] * 100) / 100} {int(array_snapshot['source_relative'][1] * 100) / 100} {int(array_snapshot['source_relative'][2] * 100) / 100}"
            cv.putText(img_z, source_relative, (50, img_z.shape[0] - text_coord+12), cv.FONT_HERSHEY_SIMPLEX, 0.3, (255, 255, 255), 1)


        print('-----------------------------')
        text_coord = 5
        # # TODO: Is this a dublication?
        img_x = np.zeros((exp_descr['mesh']['size_y'], exp_descr['mesh']['size_z'], 3), np.uint8) + 25

        for cidx, angle_x in enumerate(angles_x):
            array_snapshot = result_item[(0, angle_x)]
            for v in array_snapshot['mic_positions']:
                img_x[v[1], v[2], [cidx]] = 255

            # Draw general direction of the array
            line_color = [0, 0, 0]
            line_color[cidx] = 255
            sensors_direction = [
                0,
                array_snapshot['sensor_direction_zy'],
                array_snapshot['sensor_direction_xz']
            ]
            cv.line(img_x, 
                    (int(sensors_origin[2]), int(sensors_origin[1])), 
                    (int(sensors_origin[2] + sensors_direction[2]/exp_descr['mesh']['dz']), int(sensors_origin[1] + sensors_direction[1]/exp_descr['mesh']['dy'])), 
                    line_color, 2)
            # Draw directions to the sources
            for source in array_snapshot['sources']:
                r = Rotation.from_euler('x', -source['angle_x'], degrees=True)
                rotated = r.apply(sensors_direction)*1000
                cv.line(img_x, 
                        (int(sensors_origin[2]), int(sensors_origin[1])), 
                        (int(sensors_origin[2] + rotated[2]), int(sensors_origin[1] + rotated[1])), 
                        line_color, 1)
                cv.putText(img_x, str(int(source['angle_x'] * 10) / 10), (0, img_x.shape[0] - text_coord), cv.FONT_HERSHEY_SIMPLEX, 0.3, line_color, 1)
                text_coord += 12
                print("AngleX:", source['angle_x'])
        
        debug_img = np.zeros((img_z.shape[0], img_z.shape[1] + img_x.shape[1] + 5, 3), np.uint8)
        debug_img[:, :img_z.shape[1]] = img_z
        debug_img[:, img_z.shape[1] + 5:] = img_x
        cv.imwrite(os.path.join(export_path, debug_file), debug_img)


if __name__ == "__main__":
    # Mics positions defined as x, y, z coordinates in METERS (not mesh positions)
    mics = np.array([   # MMAUD-compatible configuration
        [-0.0467,   0.00, 0.00],
        [  0.00, -0.0467, 0.00],
        [ 0.0467,   0.00, 0.00],
        [  0.00,  0.0467, 0.00],
    ])
    sensors_direction = np.array([[0, -1, 0]])
    # export('001', mics, sensors_direction, 5, [100, 100, 5], 'debug_img.png')
    export('004', mics, sensors_direction, 15, [50, 15, 5], 'debug_img.png')
    # export('008', mics, sensors_direction, 5, [30, 15, 5], 'debug_img.png')
