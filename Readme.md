## Run container
``` bash
docker run --gpus all --name kwave --shm-size=512M -v /home/vitalii/Desktop/Projects/KWave:/app --tmpfs /inputs:size=4G -it kwave:05apr2026 bash
```
Compile kwave as:
``` bash
cd /app/k-Wave-CPUGPU-src/kspaceFirstOrder-CUDA
make -j
```
