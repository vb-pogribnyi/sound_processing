import torch
import argparse
from Data.loader import get_dataloader

def load_model(model_name):
    if model_name == "conformer":
        from NN.Conformer.model import get_model as get_conformer
        return get_conformer()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', help="[aumamba, conformer, cross3d]")
    parser.add_argument('--train_data', help="[mmaud, kwave, collected]")
    parser.add_argument('--val_data', help="[mmaud, kwave, collected]")
    parser.add_argument('--preproc', help="[spec, srp]")
    args = parser.parse_args()
    model = load_model(args.model)
    train_dl = get_dataloader(args.train_data, preproc=args.preproc)
    # val_dl = get_dataloader(args.val_data, preproc=args.preproc)
    print(model)
    for audio, doa in train_dl:
        print(audio.shape, doa.shape)
    print('done')
