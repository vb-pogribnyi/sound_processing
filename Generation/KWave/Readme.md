## Run container
``` bash
docker run --gpus all --name kwave --shm-size=8G -v /home/vitalii/Desktop/Projects/KWave:/app -v /media/vitalii/Data/Experiments:/experiments --tmpfs /inputs:size=8G -it kwave:25apr2026 bash
docker run --gpus all --name kwave --shm-size=8G -v /home/vitalii/Desktop/Projects/KWave:/app -v /media/vitalii/Data/Experiments:/experiments --tmpfs /inputs:size=24G -it kwave:25apr2026 bash
```
Compile kwave as:
``` bash
cd /app/k-Wave-CPUGPU-src/kspaceFirstOrder-CUDA
make -j
```

## Training
``` bash
docker run --gpus all --name training --shm-size=8G -v /home/vitalii/Desktop/Projects/KWave:/app -v /media/vitalii/Data/Experiments:/experiments -p 5000:5000 -it training:17may2026 bash
```
