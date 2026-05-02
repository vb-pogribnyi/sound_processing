import os
import numpy as np
import matplotlib.pyplot as plt

sensor_data = np.load('sim_result.npy')
sensor_data = sensor_data.T.reshape(32, 153, 153, -1)
print('data loaded')
maxval = np.amax(np.abs(sensor_data))
print('maxval found')
Nz = sensor_data.shape[0]
for t in range(0, sensor_data.shape[-1]):
    if t % 1 != 0:
        continue
    
    figsize = (8, 6)
    plt.figure(figsize=figsize)
    
    # zmax = np.max(np.max(sensor_data[:, :, :, t], axis=0), axis=0)
    # zcoord = np.argmax(zmax)
    # print('zcoord', zcoord)
    # print(np.min(sensor_data[:, :, zcoord, t]), np.max(sensor_data[:, :, zcoord, t]))
    print(np.min(sensor_data[:, :, :, t]), np.max(sensor_data[:, :, :, t]))
    print('-----------------------------------------------')

    os.makedirs(f'slices/{str(t).zfill(2)}', exist_ok=True)
    for z in range(Nz):
        plt.imshow(
            sensor_data[z, :, :, t].T,
            cmap="RdBu_r",
            vmin=-maxval,
            vmax=maxval,
            interpolation="nearest",
            aspect="auto",
        )
        plt.colorbar()
        plt.title(f"Wave propagation at step {t}")
        plt.axis("off")
        plt.savefig(f'slices/{str(t).zfill(2)}/{str(z).zfill(2)}.png')
        plt.close()
        # plt.show()
