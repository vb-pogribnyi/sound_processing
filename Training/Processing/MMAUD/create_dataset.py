# Having exported BAG audio and ground truth - synchronize this data 
# and save raw waveform along with GT location
import pickle
# import io
import os
import json
import numpy as np
from tqdm import tqdm
from scipy.io.wavfile import write
# from scipy.interpolate import interp1d
from tqdm import tqdm

import matplotlib.pyplot as plt

# f = interp1d(x_known, y_known, kind='linear')
# y_new = f(x_new)

AUDIO_WINDOW = 4096
AUDIO_HOP = 2048
IS_DEBUG = False
out_idx = 0;

def process_file(audio_file):
    global out_idx
    audio_data = pickle.load(open(audio_file, 'rb'))

    for t in audio_data['waveforms']:
        write(f"dbg_input{t.replace('/', '_')}.wav", 48000, audio_data['waveforms'][t])

    assert len(np.unique([len(audio_data['waveforms'][t]) for t in audio_data['waveforms']])) == 1
    time_start = int(min(audio_data['timestamps']['/audio1/audio']))

    result_dir = "data/mmaud"
    result_audio_dir = os.path.join(result_dir, "audio", "0")
    result_gt_dir = os.path.join(result_dir, "gt", "0")
    result_cls_dir = os.path.join(result_dir, "cls", "0")
    os.makedirs(result_audio_dir, exist_ok=True)
    os.makedirs(result_gt_dir, exist_ok=True)
    os.makedirs(result_cls_dir, exist_ok=True)
    # Save array configuration
    with open(os.path.join(result_dir, 'mics.json'), 'w') as mics_f:
        array_configuration = [( 0.43, 0.00, 0.00),
                            ( 0.00, 0.43, 0.00),
                            (-0.43, 0.00, 0.00),
                            ( 0.00,-0.43, 0.00)]
        mics_f.write(json.dumps(array_configuration, indent=2))
    for idx in tqdm(range(0, len(audio_data['waveforms']['/audio1/audio']) - AUDIO_WINDOW, AUDIO_HOP)):
        audio = np.stack([audio_data['waveforms'][t][idx:idx + AUDIO_WINDOW] for t in audio_data['waveforms']])
        gt = [
            audio_data['ground_truth']['x'][idx],
            audio_data['ground_truth']['y'][idx],
            audio_data['ground_truth']['z'][idx]
        ]
        np.save(open(os.path.join(result_audio_dir, f"{str(out_idx).zfill(5)}.npy"), 'wb'), audio)
        np.save(open(os.path.join(result_gt_dir, f"{str(out_idx).zfill(5)}.npy"), 'wb'), gt)
        np.save(open(os.path.join(result_cls_dir, f"{str(out_idx).zfill(5)}.npy"), 'wb'), np.array([0]))
        out_idx += 1
        if IS_DEBUG:
            time = int(audio_data['timestamps']['/audio1/audio'][idx]) - time_start
            time_ms = time // 1000000
            time_seconds = time_ms / 1000
            time_minutes = time_seconds // 60
            if time_seconds > 26:
                print(gt, time_minutes, time_seconds % 60)
                plt.title(f"Time: {time_minutes}:{time_seconds}")
                [plt.plot(audio_item) for audio_item in audio]
                plt.show()
    with open(os.path.join(result_dir, "train_split.txt"), 'w') as f:
        for idx in range(int(out_idx * 0.7)):
            f.write(f"0/{str(idx).zfill(5)}.npy\n")
    with open(os.path.join(result_dir, "val_split.txt"), 'w') as f:
        for idx in range(int(out_idx * 0.7), out_idx):
            f.write(f"0/{str(idx).zfill(5)}.npy\n")

if __name__ == '__main__':
    process_file('Mavic3_decoded.pkl')
    process_file('Mavic2_decoded.pkl')
    process_file('Pham4_decoded.pkl')
    process_file('Avata_decoded.pkl')
    process_file('M300_decoded.pkl')
