import os
import torch
import mlflow
import argparse
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt
from Data.loader import get_dataloader
from NN.Cross3D.utils import sph2cart

def load_model(model_name, is_spec, ch_in):
    if model_name == "conformer":
        from NN.Conformer.model import get_model as get_conformer
        return get_conformer(in_ch=ch_in)
    elif model_name == "cross3d":
        from NN.Cross3D.model import get_model as get_cross3d
        return get_cross3d(ch_in=ch_in)
    elif model_name == "aumamba":
        from NN.TAME.get_model import get_model as get_aumamba      # This one has 'model' directory, so the file is renamed
        return get_aumamba(is_spec, ch_in=ch_in)
    raise Exception(f"Unknown model {model_name}")

def do_train(train_ds_name, val_ds_name, preproc_name, model_name, run_name="SoundLocator"):
    device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    train_dl = get_dataloader(train_ds_name, preproc=preproc_name, mode='train', is_post_resize=(True if model_name == 'aumamba' else False))
    val_dl = get_dataloader(val_ds_name, preproc=preproc_name, mode='val', is_post_resize=(True if model_name == 'aumamba' else False))
    for audio, doa in train_dl:
        ch_in = audio.shape[1]
        break
    model = load_model(model_name, is_spec=(preproc_name == 'spec'), ch_in=ch_in).to(device)
    # print(model)
    mse = torch.nn.MSELoss()
    opt = torch.optim.Adam(model.parameters(), lr=1e-4)
    best_val_loss = np.inf
    params = {
        "model": model_name,
        "preproc": preproc_name,
        "train": train_ds_name,
        "val": val_ds_name,
    }
    with mlflow.start_run(run_name=run_name):
        mlflow.log_params(params)
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

                # break
            if epoch % 1 == 0:
                val_losses = []
                vis_gts, vis_preds = [], []
                for batch_id, (audio, doa) in enumerate(tqdm(val_dl)):
                    if batch_id == 0:
                        for example_id, vis_features in enumerate(audio):
                            vis_features = vis_features.cpu().detach().numpy()
                            if preproc_name == 'spec':
                                vis_features = np.log(vis_features+1e-7)
                            vis_features -= vis_features.min()
                            vis_features /= vis_features.max()
                            vis_features *= 255
                            vis_features = vis_features.astype(np.uint8)
                            for map_id, map in enumerate(vis_features):
                                mlflow.log_image(map, artifact_file=f"map_{example_id}_{map_id}.png")
                    preds = model(audio.to(device))
                    gt = doa.unsqueeze(1).repeat(1, preds.shape[1], 1).to(device)
                    for doa_item, pred_item in zip(gt, preds):
                        doa_item = sph2cart(doa_item[0])
                        pred_item = sph2cart(pred_item[0])
                        vis_gts.append(doa_item.detach().cpu().numpy())
                        vis_preds.append(pred_item.detach().cpu().numpy())
                    loss = mse(preds, gt.float())
                    val_losses.append(loss.item())
                    mean_val_loss = np.mean(val_losses)
                    if mean_val_loss < best_val_loss:
                        best_val_loss = mean_val_loss
                        model_name = f'{epoch}ep_{args.model}_{args.train_data}_{args.val_data}_{args.preproc}.pth'
                        result_dir = 'trained_models'
                        os.makedirs(result_dir, exist_ok=True)
                        torch.save(model.state_dict(), os.path.join(result_dir, model_name))
                        # AuMamba is not exported correctly, omitting mlflow model
                        # mlflow.pytorch.log_model(
                        #     pytorch_model=model,
                        #     artifact_path="model",
                        #     registered_model_name=f"{model_name}_{epoch}" # Optional: register directly to model registry
                        # )

                # Visualize predictions vs ground truth
                vis_gts = np.array(vis_gts).T
                vis_preds = np.array(vis_preds).T
                fig = plt.figure(figsize=(12, 12))
                ax = fig.add_subplot(111, projection='3d')
                ax.scatter(vis_gts[0], vis_gts[1], vis_gts[2], color='crimson', label='Ground Truth', s=2)
                ax.scatter(vis_preds[0], vis_preds[1], vis_preds[2], color='deepskyblue', label='Estimation', s=1)
                ax.set_title(f'Predictions - ep {epoch}')
                ax.grid(True)
                # plt.savefig('/app/preds.png')
                mlflow.log_figure(fig, f"preds_{epoch}.png")
                plt.close()



                print(epoch, np.mean(losses), mean_val_loss)
                mlflow.log_metric("train_loss", np.mean(losses), epoch)
                mlflow.log_metric("val_loss", mean_val_loss, epoch)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', help="[aumamba, conformer, cross3d]")
    parser.add_argument('--train_data', help="[mmaud, kwave, collected]")
    parser.add_argument('--val_data', help="[mmaud, kwave, collected]")
    parser.add_argument('--preproc', help="[spec, srp]")
    args = parser.parse_args()
    do_train(args.train_data, args.val_data, args.preproc, args.model)
    print('done')
