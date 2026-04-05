import os
import numpy as np
import cv2 as cv
from tqdm import tqdm

z_idx = 8
files = {}
os.makedirs('slices_in', exist_ok=True)
src = 'input_mesh/001.npy'
src = np.load(src)

for tidx in tqdm(range(src.shape[-1])):
    slice = src[:, :, z_idx, tidx]
    slice = np.stack([slice, np.zeros_like(slice), slice], axis=-1)
    slice[:, :, 2] *= -1
    cv.imwrite(os.path.join('slices_in', f'{str(tidx).zfill(3)}_.png'), slice*10)

