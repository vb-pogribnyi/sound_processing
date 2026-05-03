# Having exported BAG audio and ground truth - synchronize this data 
# and save raw waveform along with GT location
import pickle
import io
import numpy as np
from tqdm import tqdm
from pydub import AudioSegment  # pip install pydub audioop-lts
from scipy.io.wavfile import write
# AudioSegment.converter = 'C:\\Users\\vbpoh\\Documents\\Dojo\\PhD\\REPOS_mmaud_ros\\process\\ffmpeg-master-latest-win64-gpl-shared\\bin\\ffmpeg.exe'
# AudioSegment.ffprobe = 'C:\\Users\\vbpoh\\Documents\\Dojo\\PhD\\REPOS_mmaud_ros\\process\\ffmpeg-master-latest-win64-gpl-shared\\bin\\ffprobe.exe'

AUDIO_WINDOW = 4096
# AUDIO_HOP = 1

audio_topics = [
    '/audio1/audio',
    '/audio2/audio',
    '/audio3/audio',
    '/audio4/audio'
]

def process_file(audio_file, gt_file):
    audio_mp3 = pickle.load(open(audio_file, 'rb'))
    # gt = pickle.load(open(gt_file, 'rb'))['/leica/point/relative']
    np_buffers = {t: [] for t in audio_topics}
    timestamps = {t: [] for t in audio_topics}
    waveforms = {t: [] for t in audio_topics}
    samples_written = {t: 0 for t in audio_topics}
    # last_timestamp = 0
    # gt_i = 0
    # samples_written = 0
    # timestamp_start = max([audio_mp3[t][0]['timestamp'] for t in audio_topics])
    # timestamp_start = max(timestamp_start, gt[0]['timestamp'])
    # timestamp_end = min([audio_mp3[t][-1]['timestamp'] for t in audio_topics])
    # timestamp_end = min(timestamp_end, gt[-1]['timestamp'])
    idx_end = min([len(audio_mp3[t]) for t in audio_topics])

    for i in tqdm(range(idx_end)):
        for t in audio_topics:
            np_buffers[t].append(audio_mp3[t][i]['msg'])
        if i < 3:
            continue # That won't be able to read as mp3
        for t in audio_topics:
            buf = io.BytesIO(np.concatenate(np_buffers[t]).tobytes())
            buf.seek(0)
            audio = AudioSegment.from_file(buf, format='mp3')
            samples = np.array(audio.get_array_of_samples())

            # It produces 2-channel signal, but both channels are same:
            # ch1 = samples[0::2]
            # ch2 = samples[1::2]
            # any(ch1 != ch2)  # False
            # So I'm throwing away one channel
            samples = samples[0::2]
            waveforms[t].append(samples[samples_written[t]:])
            timestamps[t].append(audio_mp3[t][i]['timestamp'])
            print(audio_mp3[t][i]['timestamp'] // 1000000)
            samples_written[t] = len(samples)
    #     result[last_timestamp] = {
    #         'timestamp': last_timestamp,
    #         'samples': out_buffer,
    #         'window': window,
    #         'skips': n_timestamp_skips,
    #         'gt_x': gt[gt_i]['x'],
    #         'gt_y': gt[gt_i]['y'],
    #         'gt_z': gt[gt_i]['z']
    #     }
    # # A quick double-check. Write raw signals as WAV
    # wav_buffer = np.concatenate([result[item]['samples'] for item in result])
    # write("dbg.wav", 48000, wav_buffer)
    result = {
        "timestamps": timestamps,
        "waveforms": waveforms
    }
    pickle.dump(result, open(audio_file[:-4] + '_decoded.pkl', 'wb'))

if __name__ == '__main__':
    process_file('Mavic3.pkl', '2023-08-24-11-14-40_mavic3_gt.pkl')