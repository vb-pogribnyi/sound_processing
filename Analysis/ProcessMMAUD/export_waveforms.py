# Having exported BAG audio and ground truth - synchronize this data 
# and save raw waveform along with GT location
import pickle
import io
import numpy as np
from tqdm import tqdm
from pydub import AudioSegment  # pip install pydub audioop-lts
from scipy.io.wavfile import write
from scipy.interpolate import interp1d
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
    gt = pickle.load(open(gt_file, 'rb'))['/leica/point/relative']
    gt_t = np.array([i['timestamp'] for i in gt])
    gt_x = np.array([i['x'] for i in gt])
    gt_y = np.array([i['y'] for i in gt])
    gt_z = np.array([i['z'] for i in gt])
    f_gtx = interp1d(gt_t, gt_x, kind='linear')
    f_gty = interp1d(gt_t, gt_y, kind='linear')
    f_gtz = interp1d(gt_t, gt_z, kind='linear')
    np_buffers = {t: [] for t in audio_topics}
    timestamps = {t: [] for t in audio_topics}
    waveforms = {t: [] for t in audio_topics}
    idx_end = min([len(audio_mp3[t]) for t in audio_topics])

    for i in tqdm(range(idx_end)):
        for t in audio_topics:
            np_buffers[t].append(audio_mp3[t][i]['msg'])
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
        # samples = samples[0::2]
        waveforms[t] = samples[0::2]
        timestamps[t] = np.linspace(audio_mp3[t][0]['timestamp'], audio_mp3[t][-1]['timestamp'], len(waveforms[t]))
        
    # The audio timestamps are not really synchronized, so I have to assume that first signal is correct 
    # and the timestamps for the other ones match the first one.
    gt_available = timestamps['/audio1/audio'] > min(gt_t)
    gt_available = np.logical_and(gt_available, timestamps['/audio1/audio'] < max(gt_t))
    for t in audio_topics:
        waveforms[t] = waveforms[t][gt_available]
        timestamps[t] = timestamps[t][gt_available]
    gts = {
        'x': f_gtx(timestamps['/audio1/audio']),
        'y': f_gty(timestamps['/audio1/audio']),
        'z': f_gtz(timestamps['/audio1/audio'])
    }
    result = {
        "timestamps": timestamps,
        "waveforms": waveforms,
        "ground_truth": gts
    }
    pickle.dump(result, open(audio_file[:-4] + '_decoded.pkl', 'wb'))

if __name__ == '__main__':
    process_file('Mavic3.pkl', '2023-08-24-11-14-40_mavic3_gt.pkl')