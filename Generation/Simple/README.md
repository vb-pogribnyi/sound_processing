# Simple: free-field rotor simulation

Fast stand-in for the KWave pipeline. It computes the sound of the rotating blades
analytically at each exported microphone, and writes the result in the KWave export
format, so downstream tools (`Training/Processing/KWave/create_dataset.py`,
`beamforming.py`) read it unchanged.

```bash
python Generation/Simple/simulate.py 104 --num_examples 2000 --angle_step 5 --space_step 20 5 5
# -> /experiments/104/export_simple/{exported.pkl, compiled_values/, stats_*.png, debug_img.png}
```

## What is shared with the KWave export

`simulate.py` calls `exporter.export(..., signal_source=...)`. Everything except the mic
signals comes from the exporter:

- the candidate grid (`space_step`, `angle_step`) inside the experiment's `export` volume,
  with every mic inside it;
- balanced selection of `num_examples`: azimuth/elevation cells first, positions second;
- labels (`sources`, `source_relative`, sensor directions), grid-rounded `mic_positions`
  and the `mic_values` index tuples in `exported.pkl`;
- `compiled_values/NNNNN.pkl`, one per output sample (`sampling`, aligned to `mesh.dt`
  like the solver output), plus the statistics and debug images.

Signals are computed at the grid-rounded mic positions, where KWave records them. The mic
array (`MICS`, `SENSORS_DIRECTION`) is set at the top of `simulate.py`.

## Source model (`rotor.py`)

Same `experiment.yml` source entries as KWave (`type`, `x/y/z`, `speed`, `amplitude`,
`noise`, `thickness`, `mode` / `source_mode`):

- **Geometry**: as CircularSignal draws the meshes. Blades run from the hub center to `noise.span`
  (0.1 m) and turn counter-clockwise about +z at `rotor.rpm` (default 3500) times `speed`.
  Blade 0 points along +y at t=0. The center is the source mesh center (`meta.json`).
  Override per source with `rotor: {rpm, n_blades, start_angle_deg, center}`.
- **`amiet`** (broadband loading): `noise.py`'s BladeNoise pressure jump per span bin,
  integrated over chord, applied as a force along the rotor axis on `n_span` compact
  elements per blade.
- **`loading`** (thickness): each element's share of `thickness.volume_per_blade_m3` as a
  compact moving volume, low-passed at `thickness.f_max`.
- **`both`**: their sum.

Propagation is exact free field with retarded time (compact Farassat formulation 1), so
Doppler shift, convective amplification, distance and dipole directivity follow from the
motion. Sources fade in over 5 ms from t=0.

## Differences from KWave

- Homogeneous air (343 m/s, 1.225 kg/m^3 unless `noise.sound_speed/density`).
  `sspeed_seed`/`dens_seed` are ignored. No reflections or absorbing boundary.
- No grid: no voxel staircase in the source, no 8 mm spatial resolution limit.
- `pressure_noise` bumps are not simulated.
- Amplitudes are physical pressures (Pa), not calibrated to KWave's `source.p` scaling.
- The broadband noise uses the same seeds as KWave, but a different band limit
  (`f_max` <= 0.4 x output rate, leaving room for Doppler shift), so waveforms differ.

## Tests

`python -m unittest Generation.tests.test_simple_rotor`. These cover a static dipole
against the analytic field, the Doppler shift of a rotating tone, loading and thickness
against brute-force numerical derivatives, the retarded-time solver, and an end-to-end
export.
