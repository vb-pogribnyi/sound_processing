import os
import sys
sys.path.append(os.path.dirname(__file__))
import torch
from NN.TAME.model.model import TFMamba

class ModelMock(TFMamba):
    def forward(self, x):
        pred_cls, pred_pos = super().forward(x)
        # TODO: That's nasty. (This was to make it compatible with the outputs from Conformer)
        result = pred_pos[:, :2].unsqueeze(1).repeat(1, 3, 1)
        return result

def get_model():
    return ModelMock(num_cls=1, mode="train")

if __name__ == '__main__':
    # Batch, channels (srp, max_coord, min_coord), res_phi, res_the
    dummy_input = torch.rand(64, 4, 224, 16) 
    model = get_model()
    cls_pred, pos_pred = model(dummy_input)
    print(pos_pred.shape)
