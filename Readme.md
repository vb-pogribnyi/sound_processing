## Run container
``` bash
docker run --gpus all --name kwave --shm-size=512M -v /home/vitalii/Desktop/Projects/KWave:/app -v /media/vitalii/Data/Experiments:/experiments --tmpfs /inputs:size=4G -it kwave:25apr2026 bash
```
Compile kwave as:
``` bash
cd /app/k-Wave-CPUGPU-src/kspaceFirstOrder-CUDA
make -j
```
