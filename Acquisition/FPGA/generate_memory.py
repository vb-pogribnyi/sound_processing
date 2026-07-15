import numpy as np
import matplotlib.pyplot as plt

N = 256
N_CYCLES = 10
AMPLITUDE = 32767
with open("sine.hex", "w") as f:
  xs = np.linspace(0, 2 * np.pi * N_CYCLES, N * N_CYCLES)
  sine2 = np.sin(np.linspace(0, 2 * np.pi, N * N_CYCLES))
  values1 = (AMPLITUDE * 1.0 * np.sin(xs) * sine2).astype(int)
  values2 = (AMPLITUDE * 0.8 * np.sin(xs) * sine2).astype(int)
  values3 = (AMPLITUDE * 0.6 * np.sin(xs) * sine2).astype(int)
  values4 = (AMPLITUDE * 0.4 * np.sin(xs) * sine2).astype(int)
  values1[values1 < 0] = (1 << 16) + values1[values1 < 0]
  values2[values2 < 0] = (1 << 16) + values2[values2 < 0]
  values3[values3 < 0] = (1 << 16) + values3[values3 < 0]
  values4[values4 < 0] = (1 << 16) + values4[values4 < 0]

  plt.plot(values1)
  plt.show()

  for v1, v2, v3, v4 in zip(values1, values2, values3, values4):
    f.write(f"{v1:04X}{v2:04X}{v3:04X}{v4:04X}\n")
