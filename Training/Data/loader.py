import os
import torch
import numpy as np
from torch.utils.data import Dataset, DataLoader

# from NN.Cross3D import data_processor
from NN.TAME.dataloader.data_process import audio_to_spectrogram
from NN.Cross3D import acousticTrackingModules as at_modules

# Stolen from Cross3D
def cart2sph(cart):
    xy2 = cart[:,0]**2 + cart[:,1]**2
    sph = np.zeros_like(cart)
    sph[:,0] = np.sqrt(xy2 + cart[:,2]**2)
    sph[:,1] = np.arctan2(np.sqrt(xy2), cart[:,2]) # Elevation angle defined from Z-axis down
    sph[:,2] = np.arctan2(cart[:,1], cart[:,0])
    return sph[:,1:3] # Omit R

class TransformSpectrogram:
    def __call__(self, x):
        return audio_to_spectrogram(x.T, hop_length=32, n_mels=256, is_post_resize=False)


class TransformSRP:
    def __init__(self, N, K, rn, fs, c=343.0, arrayType='planar', cat_maxCoor=False):
        res_the = 32  # Maps resolution (elevation)
        res_phi = 64  # Maps resolution (azimuth)

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

    def __call__(self, mic_sig_batch):
        mic_sig_batch = torch.from_numpy( mic_sig_batch.T.astype(np.float32) )
        mic_sig_batch.unsqueeze_(0).unsqueeze_(0)
        mic_sig_batch = mic_sig_batch.unsqueeze(1) # Add channel axis

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

        # DOAw_batch = torch.tensor(np.array([acoustic_scene_batch[i].astype(np.float32) for i in range(len(acoustic_scene_batch))]))
        # output += [ DOAw_batch ]
        return maps[0]# , DOAw_batch

        # return output[0] if len(output)==1 else output




class MMAUDDataset(Dataset):
    def __init__(self, annotation_path, gt_postion_path, audio_path, transforms, mode="train"):
        super(MMAUDDataset, self).__init__()
        if mode == "train":
            with open(annotation_path, "r") as f:
                self.annotation_lines = f.readlines()  # 727  0/100.npy
        elif mode == "test":
            with open(annotation_path, "r") as f:
                self.annotation_lines = f.readlines()
        self.gt_postion_path = gt_postion_path
        self.audio_path = audio_path
        self.transforms = transforms

    def __len__(self):
        return len(self.annotation_lines)
    
    def concat_audio(self, audio_path, file_name):
        audio_data = np.load(os.path.join(audio_path, file_name))  # current time data [3100 4]
        return audio_data

    def __getitem__(self, index):
        file_name = self.annotation_lines[index][:-1]

        # gt_cls_path = os.path.join(self.gt_cls_path, file_name)
        gt_position_path = os.path.join(self.gt_postion_path, file_name)

        # load audio data
        audio = self.concat_audio(self.audio_path, file_name).T  # mean=0 std=1  [15500 4]
        for transform in self.transforms:
            audio = transform(audio)
        # # load gt position data
        gt_position = np.array(np.load(gt_position_path))
        doa = cart2sph(np.array([gt_position]))

        return audio, doa[0]

def get_dataloader(dataset_name, preproc=""):
    if dataset_name == "mmaud":
        annotation_path = "data/mmaud/train_split.txt"
        gt_path = "data/mmaud/gt"
        audio_path = "data/mmaud/audio"
    else:
        raise Exception(f"Dataloader: unknown dataset {dataset_name}")
    transforms = []
    if preproc == "spec":
        transforms.append(TransformSpectrogram())
    if preproc == "srp":
        N = 4       # Number of microphones
        K = 4096    # Number of signal samples
        fs = 48000  # Sample rate
        mic_pos = np.array((( 0.96, 0.00, 0.00),
                            ( 0.00, 0.96, 0.00),
                            (-0.96, 0.00, 0.00),
                            ( 0.00,-0.96, 0.00)))
        transforms.append(TransformSRP(N, K, mic_pos, fs, cat_maxCoor=True))
    dataset = MMAUDDataset(annotation_path, gt_path, audio_path, transforms=transforms)
    return DataLoader(dataset, batch_size=6)
