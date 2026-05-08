import torch
import torch.nn as nn
from conformer import Conformer

batch_size, sequence_length, dim = 3, 4096, 8

cuda = torch.cuda.is_available()  
device = torch.device('cuda' if cuda else 'cpu')

criterion = nn.CTCLoss().to(device)

inputs = torch.rand(batch_size, sequence_length, dim).to(device)
input_lengths = torch.LongTensor([4096, 4096, 4096])
targets = torch.LongTensor([[1, 3, 3, 3, 3, 3, 4, 5, 6, 2],
                            [1, 3, 3, 3, 3, 3, 4, 5, 2, 0],
                            [1, 3, 3, 3, 3, 3, 4, 2, 0, 0]]).to(device)
target_lengths = torch.LongTensor([9, 8, 7])

model = Conformer(num_classes=10, 
                  input_dim=dim, 
                  encoder_dim=4,
                  num_attention_heads=2, 
                  num_encoder_layers=2).to(device)

# Forward propagate
outputs, output_lengths = model(inputs, input_lengths)

# Calculate CTC Loss
loss = criterion(outputs.transpose(0, 1), targets, output_lengths, target_lengths)