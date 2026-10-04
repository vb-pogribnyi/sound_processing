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
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def export_statistics(result, output_dir, space_step, angle_bin=5):
    """Saves histograms describing exported samples: source azimuth/elevation (relative to the array),
    their 2D distribution and distribution of array positions."""
    # Azimuth - angle to the source in XY plane (angle_z), elevation - in ZY plane (angle_x). One entry per source.
    azimuths = np.array([s['angle_z'] for p in result for r in result[p] for s in result[p][r]['sources']])
    elevations = np.array([s['angle_x'] for p in result for r in result[p] for s in result[p][r]['sources']])
    # Array origin of every exported sample
    positions = np.array([p for p in result for _ in result[p]]).reshape(-1, 3)
    if len(positions) == 0:
        print("No samples exported - skipping statistics.")
        return
    print(f"Exported {len(positions)} samples at {len(result)} positions.")

    def angle_edges(values):
        lo = np.floor(values.min() / angle_bin) * angle_bin
        hi = np.ceil(values.max() / angle_bin) * angle_bin
        return np.arange(lo, max(hi, lo + angle_bin) + angle_bin / 2, angle_bin)
    az_edges, el_edges = angle_edges(azimuths), angle_edges(elevations)
    bar_style = dict(color='#4a72b8', edgecolor='white', linewidth=1)

    # Azimuth/elevation histograms
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for ax, values, edges, name in zip(axes, [azimuths, elevations], [az_edges, el_edges], ['Azimuth', 'Elevation']):
        ax.hist(values, bins=edges, **bar_style)
        ax.set_title(f'{name} of sources relative to the array')
        ax.set_xlabel(f'{name}, degrees')
        ax.set_ylabel('Samples')
        ax.grid(axis='y', alpha=0.3)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, 'stats_angles.png'), dpi=120)
    plt.close(fig)

    # Azimuth (columns) / elevation (rows) matrix
    matrix, _, _ = np.histogram2d(elevations, azimuths, bins=[el_edges, az_edges])
    fig, ax = plt.subplots(figsize=(min(16, max(6, len(az_edges) * 0.3 + 2)), min(12, max(4, len(el_edges) * 0.3 + 1.5))))
    im = ax.imshow(matrix, cmap='coolwarm', origin='lower', aspect='auto', interpolation='nearest',
                   extent=[az_edges[0], az_edges[-1], el_edges[0], el_edges[-1]])
    fig.colorbar(im, ax=ax, label='Samples')
    ax.set_title('Samples per azimuth/elevation')
    ax.set_xlabel('Azimuth, degrees')
    ax.set_ylabel('Elevation, degrees')
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, 'stats_angles_matrix.png'), dpi=120)
    plt.close(fig)

    # Spatial distribution of the array origin. Positions lie on a grid, so count samples per grid value.
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    for axis_idx, (ax, name) in enumerate(zip(axes, 'XYZ')):
        values, counts = np.unique(positions[:, axis_idx], return_counts=True)
        ax.bar(values, counts, width=space_step[axis_idx] * 0.9, **bar_style)
        ax.set_title(f'Array position, {name}')
        ax.set_xlabel(f'{name}, grid points')
        ax.set_ylabel('Samples')
        ax.grid(axis='y', alpha=0.3)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, 'stats_positions.png'), dpi=120)
    plt.close(fig)


def signed_angle(a, b):
    """Angle (degrees) from 2D vectors a (..., 2) to 2D vector b, negative when clockwise."""
    cos_angle = (a @ b) / (np.linalg.norm(a, axis=-1) * np.linalg.norm(b))
    angle = np.degrees(np.arccos(np.clip(cos_angle, -1.0, 1.0)))
    cross = a[..., 0] * b[1] - a[..., 1] * b[0]
    return np.where(cross < 0, -angle, angle)


def select_balanced(cells, positions, num_examples, rng):
    """Selects num_examples unique candidates (indices), spreading them equally over azimuth/elevation cells.
    Within a cell, candidates at the least used positions are taken first, so positions get used equally too."""
    # Shuffle, so that ties are broken randomly
    order = rng.permutation(len(cells))
    cells, positions = cells[order], positions[order]
    num_cells = cells.max() + 1
    cell_counts = np.bincount(cells, minlength=num_cells)
    # Equal quota per cell. Cells with fewer candidates than their share give the rest to the others.
    quota = np.zeros(num_cells, int)
    remaining = num_examples
    for k, cell in enumerate(np.argsort(cell_counts)):
        quota[cell] = min(cell_counts[cell], remaining // (num_cells - k))
        remaining -= quota[cell]
    cell_members = np.split(np.argsort(cells, kind='stable'), np.cumsum(cell_counts)[:-1])
    position_usage = np.zeros(positions.max() + 1, int)
    taken = [np.zeros(len(m), bool) for m in cell_members]
    num_taken = np.zeros(num_cells, int)
    selected = []
    active = np.flatnonzero(quota > 0)
    with tqdm(total=num_examples, desc='Selecting') as progress:
        while len(active) > 0:
            # Cells take turns, so that position usage stays balanced across all of them
            for cell in rng.permutation(active):
                members = cell_members[cell]
                usage = np.where(taken[cell], np.iinfo(int).max, position_usage[positions[members]])
                pick = np.argmin(usage)
                taken[cell][pick] = True
                position_usage[positions[members[pick]]] += 1
                num_taken[cell] += 1
                selected.append(order[members[pick]])
            progress.update(len(active))
            active = active[num_taken[active] < quota[active]]
    return np.array(selected)


def export(experiment, mics, sensors_direction, angle_step, space_step, debug_file=None,
           num_examples=None, angle_bin=5, seed=0):
    # num_examples: number of examples to export, balanced over source azimuth/elevation (angle_bin cells) and
    # array positions; None exports every valid example.
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

    meshes_meta = [json.load(open(os.path.join('/experiments/input_mesh', source['type'], 'meta.json'))) for source in exp_descr['sources']]

    def compute_source_directions(sensors_origin):
        source_directions = []
        for source, mesh_meta in zip(exp_descr['sources'], meshes_meta):
            dx = source['x'] + mesh_meta['nx'] / 2 - sensors_origin[0]
            dy = source['y'] + mesh_meta['ny'] / 2 - sensors_origin[1]
            dz = source['z'] + mesh_meta['nz'] / 2 - sensors_origin[2]
            source_directions.append((dx * mesh_meta['dx'], dy * mesh_meta['dy'], dz * mesh_meta['dz']))
        avg_direction = np.mean(source_directions, axis=0)
        directions_relative_x = np.stack([r.inv().apply(avg_direction) for r in rotations_x])
        directions_relative_xz = np.stack([r.inv().apply(directions_relative_x) for r in rotations_z])
        return source_directions, directions_relative_xz

    def compute_snapshot(sensors_origin, source_directions, directions_relative_xz, rot_z, rot_x, check_bounds=True):
        # Returns None if any mic falls outside of the exported area. With check_bounds=False the snapshot
        # is built anyway - used to manually create snapshots for the debug image.
        sensors_origin_x, sensors_origin_y, sensors_origin_z = sensors_origin
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
            if not is_positions_valid and check_bounds:
                return None
            mic_out_idx_x -= exp_descr['export']['x_start']
            mic_out_idx_y -= exp_descr['export']['y_start']
            mic_out_idx_z -= exp_descr['export']['z_start']

            mic_pos_x = round(mic[0] / exp_descr['mesh']['dx'] + sensors_origin_x)
            mic_pos_y = round(mic[1] / exp_descr['mesh']['dy'] + sensors_origin_y)
            mic_pos_z = round(mic[2] / exp_descr['mesh']['dz'] + sensors_origin_z)
            if check_bounds:
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
        array_snapshot['source_relative'] = directions_relative_xz[rot_z, rot_x].copy()
        array_snapshot['source_relative'][2] *= -1
            
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
        return array_snapshot

    # Candidates: every (position, rotation) pair at which all mics stay inside the exported area. Validity and
    # source angles are computed vectorized here - full snapshots are built only for the selected candidates.
    export_start = np.array([exp_descr['export'][f'{c}_start'] for c in 'xyz'])
    export_end = np.array([exp_descr['export'][f'{c}_end'] for c in 'xyz'])
    mesh_step = np.array([exp_descr['mesh'][f'd{c}'] for c in 'xyz'])
    grids = [np.arange(export_start[i], export_end[i], space_step[i]) for i in range(3)]
    positions = np.stack(np.meshgrid(*grids, indexing='ij'), axis=-1).reshape(-1, 3)
    mic_offsets = mics_xz / mesh_step   # (rot_x, rot_z, mic, 3), in grid points
    cand_position, cand_rot_z, cand_rot_x, cand_azimuth, cand_elevation = [], [], [], [], []
    for position_idx, position in enumerate(tqdm(positions, desc='Candidates')):
        mic_idx = np.round(mic_offsets + position)
        valid = np.all((mic_idx >= export_start) & (mic_idx < export_end), axis=(2, 3))
        rot_x, rot_z = np.nonzero(valid)
        if len(rot_x) == 0:
            continue
        # Angles to the average source direction - same formulas as 'sources' in compute_snapshot
        source = np.mean(compute_source_directions(position)[0], axis=0)
        elevation = signed_angle(directions_x[:, 0, [2, 1]], source[[2, 1]])
        azimuth = signed_angle(directions_z[:, 0, [0, 1]], source[[0, 1]])
        cand_position.append(np.full(len(rot_x), position_idx))
        cand_rot_z.append(rot_z)
        cand_rot_x.append(rot_x)
        cand_azimuth.append(azimuth[rot_z])
        cand_elevation.append(elevation[rot_x])
    assert len(cand_position) > 0, "No valid array positions/rotations - check export area, space_step and mics."
    cand_position, cand_rot_z, cand_rot_x, cand_azimuth, cand_elevation = [
        np.concatenate(c) for c in [cand_position, cand_rot_z, cand_rot_x, cand_azimuth, cand_elevation]]
    print(f"{len(cand_position)} candidate examples at {len(np.unique(cand_position))} positions.")

    if num_examples is None:
        selected = np.arange(len(cand_position))
    else:
        if num_examples > len(cand_position):
            print(f"WARNING: requested {num_examples} examples, only {len(cand_position)} available - exporting all. "
                  "Use smaller angle_step/space_step to get more candidates.")
            num_examples = len(cand_position)
        # Azimuth/elevation cell of each candidate - these are balanced
        cand_cell = np.stack([np.floor(cand_azimuth / angle_bin), np.floor(cand_elevation / angle_bin)], axis=1)
        _, cand_cell = np.unique(cand_cell, axis=0, return_inverse=True)
        selected = select_balanced(cand_cell.reshape(-1), cand_position, num_examples, np.random.default_rng(seed))

    for position_idx in tqdm(np.unique(cand_position[selected]), desc='Snapshots'):
        key_position = tuple(positions[position_idx])
        result[key_position] = {}
        source_directions, directions_relative_xz = compute_source_directions(key_position)
        for cand_idx in selected[cand_position[selected] == position_idx]:
            rot_z, rot_x = cand_rot_z[cand_idx], cand_rot_x[cand_idx]
            key_rotation = (angles[rot_z], angles[rot_x])
            array_snapshot = compute_snapshot(key_position, source_directions, directions_relative_xz, rot_z, rot_x)
            assert array_snapshot is not None, "Candidate validity does not match compute_snapshot"
            result[key_position][key_rotation] = array_snapshot
    num_exported = sum(len(result[p]) for p in result)
    assert num_exported == len(selected), "Duplicate examples selected"
    print(f"Selected {num_exported} examples at {len(result)} positions.")

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

    print("Exporting statistics...")
    stats_dir = os.path.dirname(os.path.join(export_path, debug_file if debug_file is not None else ''))
    os.makedirs(stats_dir, exist_ok=True)
    export_statistics(result, stats_dir, space_step, angle_bin)

    print("Creating debug image.")
    if debug_file is not None:
        text_coord = 5
        # Desired debug angles may be absent from the angle grid (depends on angle_step) - snap them to the closest
        # available ones, keeping them distinct. Angles closest to zero are snapped first, so zero stays the reference.
        def snap_angles(desired):
            snapped = {}
            for a in sorted(desired, key=abs):
                candidates = [g for g in sorted(angles, key=lambda g: abs(g - a)) if g not in snapped.values()]
                snapped[a] = candidates[0] if len(candidates) > 0 else angles[np.argmin(np.abs(angles - a))]
            return [snapped[a] for a in desired]
        angle_zero = snap_angles([0])[0]
        angles_z = snap_angles([-70, 0, 30])
        angles_x = snap_angles([-5, 0, 5])
        debug_keys = [(angle_z, angle_zero) for angle_z in angles_z] + [(angle_zero, angle_x) for angle_x in angles_x]

        # Pick the exported origin covering most of the debug rotations (ideally all of them)
        sensors_origin = None
        if len(result) > 0:
            sensors_origin = max(result, key=lambda rkey: sum(akey in result[rkey] for akey in debug_keys))
        else:
            # Nothing exported at all - use the grid origin closest to the center of the exported area
            sensors_origin = tuple(
                grid[np.argmin(np.abs(grid - (exp_descr['export'][f'{c}_start'] + exp_descr['export'][f'{c}_end']) / 2))]
                for c, grid in zip('xyz', [
                    np.arange(exp_descr['export'][f'{c}_start'], exp_descr['export'][f'{c}_end'], space_step[i])
                    for i, c in enumerate('xyz')])
            )
        assert sensors_origin is not None, "Unable to find origin suitable for debug image."
        # Copy, so that manually created snapshots do not end up in the exported data
        result_item = dict(result.get(sensors_origin, {}))
        missing_keys = [akey for akey in debug_keys if akey not in result_item]
        if len(missing_keys) > 0:
            print(f"Debug image: rotations {missing_keys} are not exported at {sensors_origin}, creating them manually.")
            source_directions, directions_relative_xz = compute_source_directions(sensors_origin)
            for akey in missing_keys:
                rot_z, rot_x = int(np.argmin(np.abs(angles - akey[0]))), int(np.argmin(np.abs(angles - akey[1])))
                result_item[akey] = compute_snapshot(sensors_origin, source_directions, directions_relative_xz, rot_z, rot_x, check_bounds=False)
        img_z = np.zeros((exp_descr['mesh']['size_y'], exp_descr['mesh']['size_x'], 3), np.uint8) + 25
        for cidx, angle_z in enumerate(angles_z):
            array_snapshot = result_item[(angle_z, angle_zero)]
            for v in array_snapshot['mic_positions']:
                if 0 <= v[1] < img_z.shape[0] and 0 <= v[0] < img_z.shape[1]:
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
            array_snapshot = result_item[(angle_zero, angle_x)]
            for v in array_snapshot['mic_positions']:
                if 0 <= v[1] < img_x.shape[0] and 0 <= v[2] < img_x.shape[1]:
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
    # # Mics positions defined as x, y, z coordinates in METERS (not mesh positions)
    # mics = np.array([   # MMAUD-compatible configuration
    #     [-0.0467,   0.00, 0.00],
    #     [  0.00, -0.0467, 0.00],
    #     [ 0.0467,   0.00, 0.00],
    #     [  0.00,  0.0467, 0.00],
    # ])
    mics = np.array([
        [-0.1,  0.00, 0.00],
        [-0.1,  -0.1, 0.00],
        [ 0.00, -0.1, 0.00],
        [ 0.00, 0.00, 0.00],
        [ 0.10, 0.00, 0.00],
        [ 0.00, 0.10, 0.00],
        [ 0.10, 0.10, 0.00],
    ])
    sensors_direction = np.array([[0, -1, 0]])


    # def export(experiment, mics, sensors_direction, angle_step, space_step, debug_file=None,
    #            num_examples=None, angle_bin=5, seed=0):

    # export('001', mics, sensors_direction, 5, [100, 100, 5], 'debug_img.png')
    # export('104', mics, sensors_direction, 15, [100, 25, 15], 'debug_img.png')
    # export('008', mics, sensors_direction, 5, [30, 15, 5], 'debug_img.png')
    export('102', mics, sensors_direction, 5, [20, 5, 5], 'debug_img.png', num_examples=500)
