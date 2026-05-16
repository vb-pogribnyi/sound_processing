import torch
import numpy as np
from NN.Cross3D import acousticTrackingModels as at_models

def get_model():
    res_the = 32  # Maps resolution (elevation)
    res_phi = 64  # Maps resolution (azimuth)
    cr_deep = int(min(4, np.log2(min(res_the, res_phi))))  # For low resolution maps it is not possible to perform 4 cross layers
    net = at_models.Cross3D(res_the, res_phi, cr_deep=cr_deep)

    return net


if __name__ == '__main__':
    # Batch, channels (srp, max_coord, min_coord), res_phi, res_the
    dummy_input = torch.rand(5, 3, 1, 32, 64) 
    model = get_model()
    out = model(dummy_input)
    print(out.shape)
