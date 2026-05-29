import numpy as np

# Accoustic channel swap. Update microphones positions
# and features array so that the source should appear
# from the other side.
class AugACS:
    def __call__(self, mics_pos, inputs, labels):
        # Given microphones positions, find (if any) combinations that corresponds to X or Y swap
        x_swaps = np.ones(mics_pos.shape[0]) * -1
        y_swaps = np.ones(mics_pos.shape[0]) * -1
        for mic_idx1 in range(mics_pos.shape[0]):
            for mic_idx2 in range(mics_pos.shape[0]):
                if mic_idx1 == mic_idx2:
                    continue
                if np.abs(mics_pos[mic_idx1][0]) > 0 and np.abs(mics_pos[mic_idx1][0] - (-1 * mics_pos[mic_idx2][0])) < 0.001:
                    # Record as X-swap possibility
                    x_swaps[mic_idx1] = mic_idx2
                if np.abs(mics_pos[mic_idx1][1]) > 0 and np.abs(mics_pos[mic_idx1][1] - (-1 * mics_pos[mic_idx2][1])) < 0.001:
                    # Record as Y-swap possibility
                    y_swaps[mic_idx1] = mic_idx2
        aug_options = [(mics_pos, inputs, labels)]
        if all(x_swaps >= 0):
            x_swap_labels = labels.copy()
            x_swap_labels[0] *= -1
            aug_options.append((mics_pos[x_swaps], inputs[x_swaps], x_swap_labels))
        if all(y_swaps >= 0):
            y_swap_labels = labels.copy()
            y_swap_labels[1] *= -1
            aug_options.append((mics_pos[y_swaps], inputs[y_swaps], y_swap_labels))

        return np.random.choice(aug_options)
