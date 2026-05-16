import torch
import numpy as np

import os
import sys
sys.path.append(os.path.dirname(__file__))
import acousticTrackingModules as at_modules

class OneSourceTrackingFromMapsLearner:
    """ Learner for models which use SRP-PHAT maps as input
    """
    def __init__(self, N, K, res_the, res_phi, rn, fs, c=343.0, arrayType='planar', cat_maxCoor=False):
        """
        N: Number of microphones in the array
        K: Window size for the SRP-PHAT map computation
        res_the: Resolution of the maps in the elevation axis
        res_phi: Resolution of the maps in the azimuth axis
        rn: Position of each microphone relative to te center of the array
        fs: Sampling frequency
        c: Speed of the sound [default: 343.0]
        arrayType: 'planar' or '3D' whether all the microphones are in the same plane (and the maximum DOA elevation is pi/2) or not [default: 'planar']
        cat_maxCoor: Include to the network input tow addition channels with the normalized coordinates of each map maximum [default: False]
        """
        
        self.N = N
        self.K = K
        self.fs = fs
        self.res_the = res_the
        self.res_phi = res_phi

        self.cat_maxCoor = cat_maxCoor

        dist_max = np.max([np.max([np.linalg.norm(rn[n, :] - rn[m, :]) for m in range(N)]) for n in range(N)])
        tau_max = int(np.ceil(dist_max / c * fs))
        self.gcc = at_modules.GCC(N, K, tau_max=tau_max, transform='PHAT')
        self.srp = at_modules.SRP_map(N, K, res_the, res_phi, rn, fs,
                                      thetaMax=np.pi / 2 if arrayType == 'planar' else np.pi)


    def data_transformation(self, mic_sig_batch=None, acoustic_scene_batch=None, vad_batch=None):
        """ Compute the SRP-PHAT maps from the microphone signals and extract the DoA groundtruth from the AcousticScene
        """
        # output = []

        mic_sig_batch = torch.from_numpy( mic_sig_batch.astype(np.float32) )
        mic_sig_batch = mic_sig_batch.unsqueeze(1) # Add channel axis

        if self.cuda_activated:
            mic_sig_batch = mic_sig_batch.cuda()

        maps = self.srp(self.gcc(mic_sig_batch))
        maximums = maps.view(list(maps.shape[:-2]) + [-1]).argmax(dim=-1)

        if self.cat_maxCoor:
            max_the = (maximums / self.res_phi).float() / maps.shape[-2]
            max_phi = (maximums % self.res_phi).float() / maps.shape[-1]
            repeat_factor = np.array(maps.shape)
            repeat_factor[:-2] = 1
            maps = torch.cat((maps,
                                max_the[..., None, None].repeat(repeat_factor.tolist()),
                                max_phi[..., None, None].repeat(repeat_factor.tolist())
                                ), 1)

        # output += [ maps ]

        DOAw_batch = torch.tensor(np.array([acoustic_scene_batch[i].astype(np.float32) for i in range(len(acoustic_scene_batch))]))
        if self.cuda_activated:
            DOAw_batch = DOAw_batch.cuda()
        # output += [ DOAw_batch ]

        # return output
        return maps, DOAw_batch