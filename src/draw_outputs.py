import os
import numpy as np
import cv2 as cv
from tqdm import tqdm

z_idx = 16
files = {}
os.makedirs('slices', exist_ok=True)
for f in os.scandir('/app/outputs'):
    files[f.name.split('.')[0]] = f.path

fnames = sorted(list(files.keys()))
for fname in tqdm(fnames):
    timestep_output = np.load(files[fname])
    slice = timestep_output[z_idx]
    slice = np.stack([slice, np.zeros_like(slice), slice], axis=-1)
    slice[:, :, 2] *= -1
    cv.imwrite(os.path.join('slices', f'{fname}.png'), slice*250)

