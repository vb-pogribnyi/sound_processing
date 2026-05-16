# Tools for training Source Localization methods
## Modules
The toolbox consists of 3 submodules:
- Processing. Converts given data into a format supported by the dataloader and the toolbox overall. The target data format matches MMAUD input. Audio, ground truth location and class are stored in separate .npy files. Audio is stored as raw waveform of shape [window_size, n_microphones] with window size being 4096 and n_microphones = 4 for MMAUD. The dataset contains a .txt file that lists all files that will participate in training (separate .txt for train and val dataset)
- NN contains models to be tested. Each given model may accept as input either a spectrogram or raw waveform and should output 2 angular coordinates.
- Data. Contains a dataloader for the models along with augmentation methods. The dataloader is given a .txt dataset description along with paths to directories containing audio signals and ground truths.
## Pipeline
The ```train.py``` script is designed to run a single training iteration. It can be configured to use a specific model with specific parameters; a spcecifiv train/test datasets with specific augmentations.