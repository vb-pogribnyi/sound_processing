import torch
import torch.nn as nn
from conformer import Conformer
import torchvision.models as models

batch_size, sequence_length, dim = 3, 4096, 256

cuda = torch.cuda.is_available()  
device = torch.device('cuda' if cuda else 'cpu')

resnet18 = models.resnet18(weights=None).to(device)
backbone = nn.Sequential(*list(resnet18.children())[:-2])

criterion = nn.CTCLoss().to(device)

inputs = torch.rand(batch_size, sequence_length, dim).to(device)
input_lengths = torch.LongTensor([sequence_length//32, sequence_length//32, sequence_length//32])
targets = torch.LongTensor([[1, 3, 3, 3, 3, 3, 4, 5, 6, 2],
                            [1, 3, 3, 3, 3, 3, 4, 5, 2, 0],
                            [1, 3, 3, 3, 3, 3, 4, 2, 0, 0]]).to(device)
target_lengths = torch.LongTensor([9, 8, 7])

# num_classes is number of outputs - 2 angles in our case.
model = Conformer(num_classes=2, 
                  input_dim=dim//32, 
                  encoder_dim=4,
                  num_attention_heads=2, 
                  num_encoder_layers=2,
                  in_channels=512).to(device)

# Forward propagate
features = backbone(inputs.unsqueeze(1).repeat(1, 3, 1, 1))
outputs = model(features, input_lengths)

# Calculate CTC Loss
loss = criterion(outputs.transpose(0, 1), targets, output_lengths, target_lengths)