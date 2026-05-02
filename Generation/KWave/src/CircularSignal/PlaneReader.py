import os
import math
import cv2 as cv
import numpy as np
import matplotlib.pyplot as plt

class PlaneReader:
    def __init__(self, planes_source):
        self.profiles = []
        profile_idx = 1
        while True:
            profile_path = os.path.join(planes_source, str(profile_idx).zfill(3) + '.png')
            if not os.path.exists(profile_path):
                break
            self.profiles.append(255 - cv.imread(profile_path, cv.IMREAD_GRAYSCALE))
            profile_idx += 1
        self.nprofiles = profile_idx - 1
        print(f"PlaneReader loaded {self.nprofiles} profiles.")

    def sample(self, l, t, y, dt=0, dy=0, debug=False):
        # l is length-wise coordinate. Its value will be interpolated
        # over multiple profiles.
        # t is horizontal coordinate. A closest point will be taken, 
        # since the profile image is relatively high resolution.
        # y is vertical coordinate. Also, a closest point will be taken.
        profile_idx1 = math.floor(l * (self.nprofiles - 1))
        profile_idx2 = math.ceil(l * (self.nprofiles - 1))
        profile_alpha = l * (self.nprofiles - 1) - profile_idx1
        profile_row_start = int(y * self.profiles[profile_idx1].shape[0])
        profile_row_end = int((y + dy) * self.profiles[profile_idx1].shape[0])
        profile_col_start = int(t * self.profiles[profile_idx1].shape[1])
        profile_col_end = int((t + dt) * self.profiles[profile_idx1].shape[1])
        profile1_value = np.mean(self.profiles[profile_idx1][profile_row_start:profile_row_end+1, profile_col_start:profile_col_end+1])
        profile2_value = np.mean(self.profiles[profile_idx2][profile_row_start:profile_row_end+1, profile_col_start:profile_col_end+1])
        result = profile_alpha * profile2_value + (1 - profile_alpha) * profile1_value

        if debug:
            img1 = self.profiles[profile_idx1]
            img2 = self.profiles[profile_idx2]
            img1 = np.stack([img1, img1, img1], axis=-1)
            img2 = np.stack([img2, img2, img2], axis=-1)
            profile_col = int((profile_col_start + profile_col_end) / 2)
            profile_row = int((profile_row_start + profile_row_end) / 2)
            cv.circle(img1, center=(profile_col, profile_row), radius=5, color=(0, 255, 0), thickness=-1)
            cv.circle(img2, center=(profile_col, profile_row), radius=5, color=(0, 255, 0), thickness=-1)
            plt.subplot(2, 1, 1)
            plt.title("Profile 1")
            plt.imshow(img1)
            plt.subplot(2, 1, 2)
            plt.title(f"Profile 2. alpha: {profile_alpha}, result {result}")
            plt.imshow(img2)
        
            plt.gcf().set_size_inches(5, 6)
            plt.tight_layout()
            plt.show()

        return result
