import os
import json
import sqlite3
import numpy as np
from tqdm import tqdm
from scipy.signal import medfilt
import matplotlib.pyplot as plt

EXPORT_ROWS = 15

conn = sqlite3.connect('C:\\Users\\vbpoh\\Documents\\Dojo\\PhD\\Експерименти\\Стенд_1.7м\\sound_database_3p_1.7m.db')
result_dir = "data/captured"
result_audio_dir = os.path.join(result_dir, "audio", "0")
result_gt_dir = os.path.join(result_dir, "gt", "0")
result_cls_dir = os.path.join(result_dir, "cls", "0")
os.makedirs(result_audio_dir, exist_ok=True)
os.makedirs(result_gt_dir, exist_ok=True)
os.makedirs(result_cls_dir, exist_ok=True)
# Save array configuration
with open(os.path.join(result_dir, 'mics.json'), 'w') as mics_f:
    array_configuration = [( 0.0225, 0.00, 0.00),
                        ( 0.0075, 0.00, 0.00),
                        (-0.0075, 0.00, 0.00),
                        ( -0.0225, 0.00, 0.00)]
    mics_f.write(json.dumps(array_configuration, indent=2))

cur = conn.cursor()
print(cur.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall())
filtered_notes = ["'" + n[0] + "'" for n in cur.execute(f"SELECT note FROM captures GROUP BY note") if '2' in n[0] or '3' in n[0]]
print(filtered_notes)
out_idx = 0

def fix_outliers(arr):
    thresh = 1000
    arr = np.array(arr)
    arr_filt = medfilt(arr)
    arr_fixed = arr.copy()
    arr_fixed[np.abs(arr - arr_filt) >= thresh] = arr_filt[np.abs(arr - arr_filt) >= thresh]
    # plt.plot(arr)
    # plt.plot(arr_filt)
    # plt.plot(arr_fixed)
    # plt.show()
    return arr_fixed

with open(os.path.join(result_dir, "train_split.txt"), 'w') as split_f:
    pass # Create or erase the file
for note in filtered_notes:
    cap_rows = list(cur.execute(f"SELECT id, motor1Val, motor2Val, micsAngle, note FROM captures WHERE note = ({note}) \
                        AND motor1Val > 0.55 AND motor1Val < 0.85 AND motor2Val = 0"))
    cap_rows += list(cur.execute(f"SELECT id, motor1Val, motor2Val, micsAngle, note FROM captures WHERE note = ({note}) \
                        AND motor2Val > 0.55 AND motor2Val < 0.85 AND motor1Val = 0"))
    print(len(cap_rows))
    for row in tqdm(cap_rows):
        cap_id, motor1Val, motor2Val, micsAngle, note = row
        signal_cur = cur.execute(f"SELECT value1, value2, value3, value4 FROM sound_data WHERE captureId = {cap_id}")
        vs1, vs2, vs3, vs4 = [], [], [], []
        for row in signal_cur:
            v1, v2, v3, v4 = row
            vs1.append(v1)
            vs2.append(v2)
            vs3.append(v3)
            vs4.append(v4)
        if len(vs1) == 0:
            continue
        vs1 = np.array(vs1)
        vs2 = np.array(vs2)
        vs3 = np.array(vs3)
        vs4 = np.array(vs4)
        idx_skip = 2
        vs1[:idx_skip] = vs1[idx_skip + 1]
        vs2[:idx_skip] = vs2[idx_skip + 1]
        vs3[:idx_skip] = vs3[idx_skip + 1]
        vs4[:idx_skip] = vs4[idx_skip + 1]
        vs1 = fix_outliers(vs1)
        vs2 = fix_outliers(vs2)
        vs3 = fix_outliers(vs3)
        vs4 = fix_outliers(vs4)
        # category = '3_blades' if '3' in note else '2_blades'
        
        audio = np.stack([vs1, vs2, vs3, vs4])
        x = np.sin(micsAngle / 180 * np.pi)
        y = 0
        z = np.cos(micsAngle / 180 * np.pi)
        gt = [x, y, z]
        np.save(open(os.path.join(result_audio_dir, f"{str(out_idx).zfill(5)}.npy"), 'wb'), audio)
        np.save(open(os.path.join(result_gt_dir, f"{str(out_idx).zfill(5)}.npy"), 'wb'), gt)
        np.save(open(os.path.join(result_cls_dir, f"{str(out_idx).zfill(5)}.npy"), 'wb'), np.array([0]))
        out_idx += 1
        with open(os.path.join(result_dir, "train_split.txt"), 'a') as split_f:
            split_f.write(f"0/{str(out_idx).zfill(5)}.npy\n")
