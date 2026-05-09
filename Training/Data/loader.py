import os
import torch
import numpy as np
from torch.utils.data import Dataset, DataLoader

# from NN.Cross3D import data_processor

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
        return x

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
    dataset = MMAUDDataset(annotation_path, gt_path, audio_path, transforms=transforms)
    return DataLoader(dataset, batch_size=6)
