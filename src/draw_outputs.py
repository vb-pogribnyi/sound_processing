import os
import numpy as np
import cv2 as cv
from tqdm import tqdm
import matplotlib.pyplot as plt
from scipy.fft import fft, fftfreq
from scipy.signal import stft, istft
from scipy.io.wavfile import write

z_idx = 16
sig_length = 1024*8
start_point = 0
sample_rate = 44000
end_point = start_point + sig_length
IS_DRAW = True
files = {}
mic_position = [256, 0]
os.makedirs('slices', exist_ok=True)
for f in os.scandir('/app/outputs'):
    files[f.name.split('.')[0]] = f.path

mic_values = []
fnames = sorted(list(files.keys()))
for fname in tqdm(fnames):
    if start_point is not None:
        fidx = int(fname)
        if fidx < start_point:
            continue
        if end_point > 0 and fidx > end_point:
            continue
    timestep_output = np.load(files[fname])
    # slice = timestep_output[z_idx]
    slice = timestep_output
    mic_values.append(slice[mic_position[0], mic_position[1]])
    if IS_DRAW:
        slice = np.stack([slice, np.zeros_like(slice), slice], axis=-1)
        slice[:, :, 2] *= -1
        slice[slice < 0] = 0
        slice[slice < 1e-45] = 1e-45
        slice = (100 + np.log(slice)) * 1.5
        slice[slice < 0] = 0
        slice[mic_position[0], mic_position[1], 1] = 255
        cv.imwrite(os.path.join('slices', f'{fname}.png'), slice.astype(np.uint8))

N = end_point - start_point
T = 1 / sample_rate
x = np.linspace(0.0, N*T, N, endpoint=False)
yf = fft(mic_values)
xf = fftfreq(N, T)[:N//2]


plt.subplot(2, 1, 1)
plt.plot(mic_values)
plt.subplot(2, 1, 2)
plt.plot(xf, 2.0/N * np.abs(yf[0:N//2]))
plt.savefig('/app/mic_sample.png')
plt.close()

# Extend the signal
f, t, Zxx = stft(mic_values, nperseg=256)
Zxx_ext = np.tile(Zxx[:, 1:-2], (1, 20))
_, y = istft(Zxx_ext)

plt.subplot(2, 1, 1)
plt.pcolormesh(t, f, 20*np.log10(np.abs(Zxx) + 1e-12))
plt.subplot(2, 1, 2)
plt.pcolormesh(20*np.log10(np.abs(Zxx_ext) + 1e-12))
plt.savefig('/app/spec.png')
plt.close()

sig_norm = y / np.max(np.abs(y))
sig_int16 = (sig_norm * 1024*8).astype(np.int16)
write("/app/output.wav", sample_rate, sig_int16)

ext_start = 5568
mic_values = np.real(y[ext_start:ext_start + sig_length*4])
yf = fft(mic_values)

plt.subplot(2, 1, 1)
plt.plot(mic_values)
plt.subplot(2, 1, 2)
plt.plot(xf, 2.0/N * np.abs(yf[0:N//2]))
plt.savefig('/app/mic_sample_ext.png')
plt.close()
