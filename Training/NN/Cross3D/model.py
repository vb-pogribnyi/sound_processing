import torch
import numpy as np
from torchvision.transforms import Resize
from NN.Cross3D import acousticTrackingModels as at_models


class Cross3DMock(at_models.Cross3D):
    def forward(self, x):
        self.resize = None
        if x.shape[-2] != self.res_the or x.shape[-1] != self.res_phi:
            if self.resize is None:
                self.resize = Resize((self.res_the, self.res_phi), antialias=True)
            x = self.resize(x)
        x = x.unsqueeze(2)
        return super(Cross3DMock, self).forward(x)

def get_model(ch_in):
    res_the = 32  # Maps resolution (elevation)
    res_phi = 64  # Maps resolution (azimuth)
    cr_deep = int(min(4, np.log2(min(res_the, res_phi))))  # For low resolution maps it is not possible to perform 4 cross layers
    net = Cross3DMock(res_the, res_phi, cr_deep=cr_deep, ch_in=ch_in)

    return net


if __name__ == '__main__':
    # Batch, channels (srp, max_coord, min_coord), res_phi, res_the
    dummy_input = torch.rand(5, 3, 1, 32, 64) 
    model = get_model()
    out = model(dummy_input)
    print(out.shape)
