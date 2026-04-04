## Run container
``` bash
docker run --gpus all --name kwave -v /home/vitalii/Desktop/Projects/KWave:/app -it kwave:04apr2026-2 bash
```
Compile kwave as:
``` bash
cd /app/k-Wave-CPUGPU-src/kspaceFirstOrder-CUDA
make -j
```
