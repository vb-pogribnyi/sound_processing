## Sound Processing
This repository contains imlementation of sound localization methods. It contains parts such as:
- data generation ```Generation``` directory
- processing of open MMAUD dataset in ```Training/Processing/MMAUD```
- processing of the generated dataset(s) in  ```Training/Processing/KWave```
- implementations of top-performing models at the moment in ```Training/NN``` directory
- two most popular types of signal feature extractors: mel-spectrogram and SRP, with root file in ```Training/Data/loader.py```
- unified training pipeline in ```Training/train.py```