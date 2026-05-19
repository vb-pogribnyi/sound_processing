import os
import sys
sys.path.append(os.path.dirname(__file__))
import torch
from NN.TAME.model.model import TFMamba

class ModelMock(TFMamba):
    def forward(self, x):
        pred_cls, pred_pos = super().forward(x)
        # Make it compatible with the outputs from Conformer
        result = pred_pos[:, :2].unsqueeze(1)
        return result

def get_model(is_spec, ch_in):
    return ModelMock(num_cls=1, mode="train", cnn_region_feature=is_spec, ch_in=ch_in)

if __name__ == '__main__':
    # Batch, channels (srp, max_coord, min_coord), res_phi, res_the
    dummy_input = torch.rand(64, 4, 224, 16) 
    model = get_model(True)
    cls_pred, pos_pred = model(dummy_input)
    dummy_input = torch.rand(64, 3, 32, 64) 
    model = get_model(False)
    cls_pred, pos_pred = model(dummy_input)
    print(pos_pred.shape)
