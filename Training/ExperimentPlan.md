# Experimenting roadmap

## TODO:

1. Convert the exported samples into NN-friendly form, describe the process.
2. Make split-wise SRP/Beamformer, decide for sub-sample size.
3. Launch NN training.
4. Automate metrics calculation, create experiment-results table.
5. Proceed with pre- and post-processing patches.

## Description

These experiments are meant to simulate moving emitter (propeller blade). To make sure that the neural network distinguishes the moving target, static noise similar to the one emitted by the moving source, is simulated in the volume.
# The experimentation is meant to be performed in the following way:
## Prepare experiments

Create experiment folder in the /experiments directory, describe configuration in the experiment.yaml. The configuration may contain following variations:
-  Noise type. Either broadband noise simulating leading/trailing edges and tip vortex, or tonal thickness (loading) noise. Configured by ```source_mode``` field.
- Noise magnitude. Controlled by ```peak_pa``` field. 0.0 translates to no noise; 1.0 - similar strength as the source.
- Noise frequency, duration, bump size.
In every experiment the simulated blade is generated from the same mesh, of same size and rotation speed, located in same spot. Overall mesh size/resolution stays static over the experiments.

Example of the experiment yaml is as follows:
```
description: Amiet noise
sampling: 16000         # 16 kHz sampling rate
time: 0.3               # overall time, in seconds
homogenous: 1
export:
  x_start: 0
  x_end: 479
  y_start: 200
  y_end: 255
  z_start: 128
  z_end: 255
mesh:
  size_x: 512
  size_y: 256
  size_z: 256
  dx: 0.008
  dy: 0.008
  dz: 0.008
  dt: 1e-07
slices:
  - axis: z
    position: 12
  - axis: z
    position: 120
  - axis: x
    position: 350
  - axis: y
    position: 150
source_mode: amiet  # amiet | loading | both
pressure_noise:
  peak_pa: 0.00
  seed: 57
  rate_hz: 0.2
  radius_cells: 3
  duration_s: 0.01
sources:
  - type: 03_diff_airfoil/1e-07/2/0.008
    speed: 0.8
    x: 120
    y: 100
    z: 16
    freq: 1000
    amplitude: 0.2
    phase: 0
    thickness:
      enabled: true
      volume_per_blade_m3: 1.0e-5
      f_max: 6000
```

## Export data
Call exporter.py to create the dataset. The script simulates signals captured by a microphone array of given configuration (defined in ```mics``` variable) in certain position and certain orientation relative to the source (azimuth and elevation). The script is designed to balance the samples by position and orientation, it takes the number of generated samples as parameter. 

## Check with conventional methods.
Run ```beamforming.py``` with the exported experiment to check how the conventional methods (SRP and MVDR Beamformer) would perform on the simulated data.

**TODO:** Make piece-wise script to include the noise bumps into consideration

This step defines limitations of the convensional method. Pieces of signal of similar length are to be fed into the NN models for comparison.

## NN methods
Either existing (legacy) or new architectures can be tested on the exported dataset. The dataset needs to be converted to the common dataset format.

**TODO:** describe the process.

### Legacy methods
Commonly used methods such as Conformer, AuMamba and Cross3D are tested, as they are described in their papers.

### Neural pre-processing
A sequence-to-sequence architecture to filter the incoming signal is proposed to filter the correct signal coming into the array. The conventional SRP/Beamformer is applied afterwards.

### Neural post-processing
A sequence-is split into smaller sub-pieces; SRP/Beamformer features (weighted FFTs) are calculated, then passed through a neural network for processing. The processed pieces are then aggregated for the final inference.