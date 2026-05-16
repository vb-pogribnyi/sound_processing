import torch
from NN.TAME.model.model import TFMamba

def get_model():
    return TFMamba(num_cls=1, mode="train")

if __name__ == '__main__':
    # Batch, channels (srp, max_coord, min_coord), res_phi, res_the
    dummy_input = torch.rand(64, 4, 224, 16) 
    model = get_model()
    cls_pred, pos_pred = model(dummy_input)
    print(pos_pred.shape)
