import os
import yaml
import cv2 as cv
import numpy as np

req_idx = 64
src = '/experiments/002'
os.makedirs(os.path.join(src, 'export_slices'), exist_ok=True)
meta = yaml.load(open(os.path.join(src, 'experiment.yml')), Loader=yaml.FullLoader)


# phase 1 - locad data, calculate min&max
slices = []
for slice_idx, f in enumerate(sorted([src_f.path for src_f in os.scandir(os.path.join(src, 'outputs'))])):
    z_idx = req_idx - meta['export']['z_start']
    data = np.load(f)
    slice = data[z_idx]
    # cv.imwrite(os.path.join(src, 'export_slices', f'slice_{slice_idx}.png'), slice)
    slices.append(slice)
    print(data.shape)
slices = np.array(slices)
negatives = slices.copy()
negatives[negatives > 0] = 0
negatives *= -1
positives = slices.copy()
positives[positives < 0] = 0

max_val = max([positives.max(), negatives.max()])
positives /= max_val
negatives /= max_val
img_data = np.stack([(positives * 255).astype(np.uint8), np.zeros_like(positives).astype(np.uint8), (negatives * 255).astype(np.uint8)], axis=-1)

for slice_idx, img in enumerate(img_data):
    cv.imwrite(os.path.join(src, 'export_slices', f'slice_{slice_idx}.png'), img)

