# Having exported BAG audio and ground truth - synchronize this data 
# and save raw waveform along with GT location
import pickle
import io
import numpy as np
from tqdm import tqdm
from scipy.io.wavfile import write
from scipy.interpolate import interp1d

# f = interp1d(x_known, y_known, kind='linear')
# y_new = f(x_new)

AUDIO_WINDOW = 4096
AUDIO_HOP = 128

def process_file(audio_file, gt_file):
    audio_data = pickle.load(open(audio_file, 'rb'))
    gt = pickle.load(open(gt_file, 'rb'))['/leica/point/relative']
    gt_t = np.array([i['timestamp'] for i in gt])
    gt_x = np.array([i['x'] for i in gt])
    gt_y = np.array([i['y'] for i in gt])
    gt_z = np.array([i['z'] for i in gt])
    audio_fs = {}
    # Provide timestamp for each point in each waveform
    audio_waveforms = {}
    audio_timestamps = {}
    audio_time_min = 0
    audio_time_max = np.inf
    for topic in audio_data['waveforms']:
        timestamps_interp = []
        for chunk_idx in range(len(audio_data['waveforms'][topic]) - 1):
            time_start = audio_data['timestamps'][topic][chunk_idx]
            time_end = audio_data['timestamps'][topic][chunk_idx + 1]
            chunk_timestamps = np.linspace(time_start, time_end, len(audio_data['waveforms'][topic][chunk_idx])).astype(np.int64)
            timestamps_interp.append(chunk_timestamps)
        audio_waveforms[topic] = np.concatenate(audio_data['waveforms'][topic][:-1])
        audio_timestamps[topic] = np.concatenate(timestamps_interp)
        assert len(audio_waveforms[topic]) == len(audio_timestamps[topic])
        audio_fs[topic] = interp1d(audio_timestamps[topic], audio_waveforms[topic], kind='linear')
        audio_time_min = max(audio_time_min, audio_timestamps[topic][0])
        audio_time_max = min(audio_time_max, audio_timestamps[topic][-1])

    label_available_idxs1 = audio_time_min <= gt_t
    label_available_idxs2 = gt_t <= audio_time_max
    label_available_idxs = np.logical_and(label_available_idxs1, label_available_idxs2)
    gt_t = gt_t[label_available_idxs]
    gt_x = gt_x[label_available_idxs]
    gt_y = gt_y[label_available_idxs]
    gt_z = gt_z[label_available_idxs]
    f_gtx = interp1d(gt_t, gt_x, kind='linear')
    f_gty = interp1d(gt_t, gt_y, kind='linear')
    f_gtz = interp1d(gt_t, gt_z, kind='linear')

    # We're moving to time space now
    sr = 48000
    ns_per_sample = 1e9 / sr # Timestamp-compatible step for single sample
    window_duration = ns_per_sample * AUDIO_WINDOW
    hop_duration = ns_per_sample * AUDIO_HOP

    # Quick sanity check, try and export the data as wav
    for topic_idx, topic in enumerate(audio_data['waveforms']):
        waveform = []
        for timestep_start in range(int(audio_time_min), int(audio_time_max - window_duration), int(window_duration)):
            hop_times = np.linspace(timestep_start, timestep_start + window_duration, AUDIO_WINDOW)
            waveform.append(audio_fs[topic](hop_times))
        write(f"dbg_{topic_idx}.wav", 48000, np.concatenate(waveform))

    # Fetch real data with its GT
    for topic in audio_data['waveforms']:
        for timestep_start in range(int(audio_time_min), int(audio_time_max - window_duration), int(hop_duration)):
            hop_times = np.linspace(timestep_start, timestep_start + window_duration, AUDIO_WINDOW)
            hop_waveform = audio_fs[topic](hop_times)
            hop_x = f_gtx(timestep_start)
            hop_y = f_gty(timestep_start)
            hop_z = f_gtz(timestep_start)





    # np_buffers = {t: [] for t in audio_topics}
    # timestamps = {t: [] for t in audio_topics}
    # waveforms = {t: [] for t in audio_topics}
    # samples_written = {t: 0 for t in audio_topics}
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
    process_file('Mavic3_decoded.pkl', '2023-08-24-11-14-40_mavic3_gt.pkl')