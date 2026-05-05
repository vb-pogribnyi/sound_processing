# Having exported BAG audio and ground truth - synchronize this data 
# and save raw waveform along with GT location
import pickle
import io
import numpy as np
from tqdm import tqdm
from scipy.io.wavfile import write
from scipy.interpolate import interp1d

import matplotlib.pyplot as plt

# f = interp1d(x_known, y_known, kind='linear')
# y_new = f(x_new)

AUDIO_WINDOW = 4096
AUDIO_HOP = 128
IS_DEBUG = True

def process_file(audio_file):
    audio_data = pickle.load(open(audio_file, 'rb'))

    for t in audio_data['waveforms']:
        write(f"dbg_input{t.replace('/', '_')}.wav", 48000, audio_data['waveforms'][t])

    assert len(np.unique([len(audio_data['waveforms'][t]) for t in audio_data['waveforms']])) == 1
    time_start = int(min(audio_data['timestamps']['/audio1/audio']))

    for idx in range(0, len(audio_data['waveforms']['/audio1/audio']) - AUDIO_WINDOW, AUDIO_HOP):
        audio = np.stack([audio_data['waveforms'][t][idx:idx + AUDIO_WINDOW] for t in audio_data['waveforms']])
        gt = [
            audio_data['ground_truth']['x'][idx],
            audio_data['ground_truth']['y'][idx],
            audio_data['ground_truth']['z'][idx]
        ]
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

if __name__ == '__main__':
    process_file('Mavic3_decoded.pkl')