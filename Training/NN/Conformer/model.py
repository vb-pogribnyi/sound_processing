import torch
import torch.nn as nn

import os
import sys
sys.path.append(os.path.dirname(__file__))
from conformer import Conformer
import torchvision.models as models

class ResNetConformer(torch.nn.Module):
    def __init__(self, in_ch=4, dim=256):
        super().__init__()
        resnet18 = models.resnet18(weights=None)
        self.pre_bb = nn.Conv2d(in_ch, list(resnet18.children())[0].out_channels, (1, 1))
        self.backbone = nn.Sequential(*list(resnet18.children())[1:-2])
        self.conformer = Conformer(num_classes=2, 
                    input_dim=dim//32, 
                    encoder_dim=4,
                    num_attention_heads=2, 
                    num_encoder_layers=2,
                    in_channels=512)    # ResNet outputs 512 channels

    def forward(self, x):
        bb_input = self.pre_bb(x)
        features = self.backbone(bb_input)
        input_lengths = [features.shape[-2] for _ in range(features.shape[0])]
        outputs = self.conformer(features, torch.tensor(input_lengths))

        return outputs


def get_model():
    model = ResNetConformer()
    return model

if __name__ == '__main__':
    batch_size, sequence_length, dim = 3, 4096, 256

    cuda = torch.cuda.is_available()  
    device = torch.device('cuda' if cuda else 'cpu')
    criterion = nn.CTCLoss().to(device)

    inputs = torch.rand(batch_size, sequence_length, dim).to(device)
    input_lengths = torch.LongTensor([sequence_length//32, sequence_length//32, sequence_length//32])
    # num_classes is number of outputs - 2 angles in our case.
    model = get_model().to(device)
    # Forward propagate
    outputs = model(inputs.unsqueeze(1).repeat(1, 4, 1, 1))

    print(outputs.shape)