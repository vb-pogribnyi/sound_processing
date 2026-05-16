import torch
import argparse
import numpy as np
from tqdm import tqdm
from Data.loader import get_dataloader

def load_model(model_name):
    if model_name == "conformer":
        from NN.Conformer.model import get_model as get_conformer
        return get_conformer()
    elif model_name == "cross3d":
        from NN.Cross3D.model import get_model as get_cross3d
        return get_cross3d()
    raise Exception(f"Unknown model {model_name}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', help="[aumamba, conformer, cross3d]")
    parser.add_argument('--train_data', help="[mmaud, kwave, collected]")
    parser.add_argument('--val_data', help="[mmaud, kwave, collected]")
    parser.add_argument('--preproc', help="[spec, srp]")
    args = parser.parse_args()
    device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    model = load_model(args.model).to(device)
    train_dl = get_dataloader(args.train_data, preproc=args.preproc)
    # val_dl = get_dataloader(args.val_data, preproc=args.preproc)
    # print(model)
    mse = torch.nn.MSELoss()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    for epoch in range(100):
        losses = []
        for audio, doa in tqdm(train_dl):
            opt.zero_grad()
            preds = model(audio.to(device))
            gt = doa.unsqueeze(1).repeat(1, preds.shape[1], 1).to(device)
            # print(audio.shape, doa.shape, preds.shape)
            loss = mse(preds, gt.float())
            loss.backward()
            opt.step()
            losses.append(loss.item())
        if epoch % 1 == 0:
            print(epoch, np.mean(losses))
    print('done')
