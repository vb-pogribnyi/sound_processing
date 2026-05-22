import json
import numpy as np
from tqdm import tqdm

from Data.loader import get_dataloader, do_permutation

if __name__ == '__main__':
    mics_path = "data/mmaud/mics.json"
    mic_pos_orig = np.array(json.load(open(mics_path)))
    for permutation in range(24):
        mic_pos = mic_pos_orig[do_permutation(permutation, mic_pos_orig.shape[0])]
        train_dl = get_dataloader('mmaud', preproc='srp', mic_pos=mic_pos, debug_name=f"{do_permutation(permutation, mic_pos.shape[0])}")
        for audio, doa in tqdm(train_dl):
            pass