import math
import json
import numpy as np
from tqdm import tqdm

from Data.loader import get_dataloader

def do_permutation(index: int, size: int):
    """
    Return the index-th unique permutation
    of [0, 1, ..., size-1].

    Permutations are ordered lexicographically.

    Total permutations = size!
    """

    total = math.factorial(size)

    if not (0 <= index < total):
        raise ValueError(f"index must be in [0, {total})")

    items = list(range(size))
    result = []

    # Factoradic / Lehmer code decoding
    for i in range(size, 0, -1):
        fact = math.factorial(i - 1)

        pos = index // fact
        index %= fact

        result.append(items.pop(pos))

    return result

if __name__ == '__main__':
    mics_path = "data/mmaud/mics.json"
    mic_pos_orig = np.array(json.load(open(mics_path)))
    for permutation in range(24):
        mic_pos = mic_pos_orig[do_permutation(permutation, mic_pos_orig.shape[0])]
        train_dl = get_dataloader('mmaud', preproc='srp', mic_pos=mic_pos, debug_name=f"{do_permutation(permutation, mic_pos.shape[0])}")
        for audio, doa in tqdm(train_dl):
            pass