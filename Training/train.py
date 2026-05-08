import torch
import argparse

def load_model(model_name):
    if model_name == "conformer":
        from NN.Conformer.model import get_model as get_conformer
        return get_conformer()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', help="[aumamba, conformer, cross3d]")
    args = parser.parse_args()
    model = load_model(args.model)
    print(model)
    print('done')
