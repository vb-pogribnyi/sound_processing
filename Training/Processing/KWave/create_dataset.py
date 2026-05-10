import os
import json
import pickle
import numpy as np
from tqdm import tqdm

result = {}
src = 'D:\\CircularSignal\\sine_verify_2\\compiled_values'
dst = 'data/kwave'
window = 350
hop = 50
dummy_class = '0'
audio_dir = os.path.join(dst, 'audio', dummy_class)
gt_dir = os.path.join(dst, 'gt', dummy_class)
os.makedirs(audio_dir, exist_ok=True)
# os.makedirs(os.path.join(dst, 'cls'), exist_ok=True)
os.makedirs(gt_dir, exist_ok=True)

print('Reading data...')
for f_i, f in enumerate(tqdm(sorted([v.path for v in os.scandir(src)]))):
    # if f_i > 16:
    #     break


    timestep_value = pickle.load(open(f, 'rb'))

    # Figure out the array configuration.
    # Find at any location that the array is not rotated
    for pos in timestep_value:
        rot = (0, 0)
        if not rot in timestep_value[pos]:
            continue
        array_configuration = timestep_value[pos][rot]['mic_positions']
        cell_size = np.array([0.002, 0.002, 0.000625])
        array_configuration *= cell_size
        array_configuration = [list(c) for c in array_configuration]
        with open(os.path.join(dst, 'mics.json'), 'w') as mics_f:
            mics_f.write(json.dumps(array_configuration, indent=2))
        break


    for pos in timestep_value:
        if not pos in result:
            result[pos] = {}
        for rot in timestep_value[pos]:
            sensor_value = timestep_value[pos][rot]
            if not rot in result[pos]:
                result[pos][rot] = {
                    'positions': sensor_value['mic_positions'],
                    'waveform': [[] for mic in sensor_value['mic_positions']],
                    'sources': sensor_value['sources']
                }
            for id, value in enumerate(sensor_value['mic_values']):
                result[pos][rot]['waveform'][id].append(value)

result_idx = 0
split_txt = []
print('Writing dataset...')
for pos in tqdm(result):
    for rot in tqdm(result[pos], position=1, leave=0):
        ds_item = result[pos][rot]
        wf_lens = [len(wf) for wf in ds_item['waveform']]
        assert len(np.unique(wf_lens)) == 1
        wf_len = wf_lens[0]
        assert wf_len >= window
        signals = np.array(ds_item['waveform'])
        for start_idx in range(0, wf_len - window, hop):
            signal = signals[:, start_idx:start_idx+window]
            assert signal.shape[1] == window
            angles_x = [s['angle_x'] for s in ds_item['sources']]
            angles_z = [s['angle_z'] for s in ds_item['sources']]
            gt = np.array([
                np.mean(angles_x),
                np.mean(angles_z)
            ]) / 180 * np.pi
            np.save(os.path.join(audio_dir, f'{str(result_idx).zfill(6)}.npy'), signal.astype(np.float32))
            np.save(os.path.join(gt_dir, f'{str(result_idx).zfill(6)}.npy'), gt.astype(np.float32))
            split_txt.append(f"{dummy_class}/{str(result_idx).zfill(6)}.npy")
            result_idx += 1
with open(os.path.join(dst, 'train_split.txt'), 'w') as split_f:
    split_f.write('\n'.join(split_txt))

print('done')
