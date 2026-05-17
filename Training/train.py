import os
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
    elif model_name == "aumamba":
        from NN.TAME.get_model import get_model as get_aumamba      # This one has 'model' directory, so the file is renamed
        return get_aumamba()
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
    train_dl = get_dataloader(args.train_data, preproc=args.preproc, mode='train')
    val_dl = get_dataloader(args.val_data, preproc=args.preproc, mode='val')
    # print(model)
    mse = torch.nn.MSELoss()
    opt = torch.optim.Adam(model.parameters(), lr=1e-4)
    best_val_loss = np.inf
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
            val_losses = []
            for audio, doa in tqdm(val_dl):
                preds = model(audio.to(device))
                gt = doa.unsqueeze(1).repeat(1, preds.shape[1], 1).to(device)
                loss = mse(preds, gt.float())
                val_losses.append(loss.item())
                mean_val_loss = np.mean(val_losses)
                if mean_val_loss < best_val_loss:
                    best_val_loss = mean_val_loss
                    model_name = f'{epoch}ep_{args.model}_{args.train_data}_{args.val_data}_{args.preproc}.pth'
                    result_dir = 'trained_models'
                    os.makedirs(result_dir, exist_ok=True)
                    torch.save(model.state_dict(), os.path.join(result_dir, model_name))
            print(epoch, np.mean(losses), mean_val_loss)
    print('done')
