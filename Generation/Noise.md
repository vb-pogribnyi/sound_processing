# Broadband propeller loading: research and implementation

`Generation/noise.py` generates a **blade-fixed equivalent pressure-jump field**
in Pascals, indexed `[span, chord, time]`. It combines an Amiet leading-edge
surface response with BPM-based equivalent trailing-edge and tip loading.
It does not load the k-Wave mesh, import `run_experiments.py`, or synthesize
rotation, BPF/tonal noise, Doppler, distance attenuation, or observer motion.
The k-Wave runner separately adds mesh-driven thickness displacement in
`load_source()` before acoustic propagation; see the final section below.

This is an inexpensive stochastic acoustic-source model, not a flow solver or
validated prediction of the actual wall pressure on an arbitrary airfoil.
In particular, the trailing-edge and tip spatial envelopes are equivalent
load distributions. Their local pressures are not uniquely determined by the
empirical far-field spectra used to construct them.

## Research findings

Noise mechanisms need different inputs and responses:

| Mechanism | Model | Principal information required |
| --- | --- | --- |
| Leading-edge turbulence interaction | Amiet incoming-gust response | Relative speed, chord, incident normal-velocity turbulence intensity and integral length scale |
| Turbulent-boundary-layer trailing-edge noise | Wall-pressure spectrum plus trailing-edge scattering; BPM when boundary-layer data are limited | Local speed, chord, angle relative to zero lift, boundary-layer displacement thicknesses |
| Tip-vortex formation noise | Empirical BPM tip spectrum | Local tip speed, chord, shape, effective loading angle and separation length |

NASA's [BPM report, RP-1218](https://ntrs.nasa.gov/citations/19890016302)
provides the self-noise fits and distinguishes boundary-layer, separated-flow,
laminar-shedding, blunt-edge and tip mechanisms. Incoming-turbulence leading-edge
noise is a separate model. For this implementation the laminar and blunt-edge
shedding models are omitted because they can be tonal. Tip *formation* noise
is distinct from blade-vortex encounters and downstream wake evolution.

A higher-fidelity trailing-edge upgrade would use Goody's zero-pressure-gradient
wall-pressure spectrum, or an adverse-pressure-gradient extension, followed by
Amiet trailing-edge scattering. That requires trustworthy boundary-layer data;
Goody alone is not a radiating source model. See
[Rozenberg, Robert and Moreau (2012)](https://doi.org/10.2514/1.J051500) and
[Roger and Moreau (2005)](https://doi.org/10.1016/j.jsv.2004.10.054).
The latter also accounts for finite-chord back-scattering.

Generating stochastic blade-surface signals and propagating them separately
has precedent in [Barbarino and Casalino (2012)](https://doi.org/10.1260/1475-472X.11.2.157).
Spatial coherence is essential: neither one shared waveform for an entire
propeller nor independent noise per voxel is a satisfactory default.
[Hu (2021)](https://www.sciencedirect.com/science/article/pii/S0022460X21003771)
examines wall-pressure coherence and frequency-dependent correlation lengths.

Small propellers may have transitional boundary layers. Measurements at tip
Reynolds numbers approximately 43,000–100,000 show laminar-separation noise that
is not captured by an attached, fully turbulent model. See
[Grande et al. (2022)](https://iris.polito.it/handle/11583/2976883).
Excluding tonal mechanisms deliberately leaves out part of this signature.
The program warns for `Re < 100000`; this threshold is a practical diagnostic,
not a universal transition criterion.

## Implemented source models

### Leading edge

The existing vendored `amiet_tools.delta_p` and `Phi_2D` functions provide the
finite-chord response and von Karman turbulence spectrum. The response includes
a trailing-edge correction to incoming-gust scattering; that correction does
not supply boundary-layer trailing-edge self-noise.

For frequency `f` and spanwise gust wavenumber `ky`, the generator builds
complex pressure factors from `delta_p` weighted by `sqrt(4*pi*U*dky)`.
This follows the spectral convention used by the vendored
`calc_airfoil_Sqq` / `calc_radiated_Spp` combination: the latter carries the
additional `4*pi` factor. The resulting one-sided factors have units
`Pa/sqrt(Hz)`. No observer Green function is applied.

A tangent-mapped Gauss quadrature includes subcritical gusts to the vendored
surface-pressure cutoff. Span-cell averaging introduces a sinc factor.
Shared random gust coefficients preserve chordwise phase and spanwise
correlation. For varying chord or flow, responses are evaluated locally;
sharing gusts across dissimilar strips is a local-strip approximation, not
an exact solution for a twisted rotating blade. The flat-plate leading-edge
response does not add an empirical angle-of-attack gain.

### Trailing edge

`Generation/Amiet/bpm.py` expresses NASA RP-1218 Eqs. 24–49 and its boundary-layer
fits independently in NumPy. Both side contributions and the angle-dependent
contribution are included, with the original empirical separated-flow branch.
The default displacement thicknesses assume a tripped NACA0012-like section;
`delta_pressure` and `delta_suction` can override them with supplied profiles.
The original 12.5-degree branch and zero-lift-angle convention are retained.
These fits do not describe arbitrary cambered or stalled propellers precisely.

BPM gives third-octave band levels, not a narrowband pressure PSD. We evaluate
the fit continuously and divide band mean-square pressure by
`f*(2**(1/6) - 2**(-1/6))`. This is a smooth band-density approximation, not
an exact inversion of overlapping band integrals.

We calculate the stationary broadside reference with `r=1 m`, directivity
`D=1`, then convert reference pressure PSD to equivalent normal-force PSD:

```
S_force(f) = S_reference(f) * (4*pi*c0*r / (2*pi*f))**2
```

This inverts the stationary compact-force dipole transfer. It removes its
radiation weighting before subsequent propagation. It does **not** reproduce
the full noncompact Amiet/BPM angular directivity.

Strip forces have Corcos-type span coherence
`exp(-0.7 * 2*pi*f * abs(tau_i - tau_j))`, with travel coordinates estimated
using convection speed `0.7*U`. Both coefficients are approximate and the decay
coefficient is configurable. Cholesky factors generate correlated forces.
Their common scale is adjusted so the total integrated-force PSD retains the
sum of the BPM strip reference powers; correlations must not silently change
BPM's span scaling. An exponential chordwise envelope concentrates loading
near the trailing edge and is normalized by cell area to preserve force.
This envelope is a modeling choice, not the actual Amiet TE surface response.

### Tip

The tip model uses NASA Eqs. 61–67, with rounded/square geometry, an effective
loading-angle multiplier and optional supplied separation length. It uses the
`M**2 * Mmax**3` factor from Eq. 61 and the spectral term
`-30.5*(log10(St)+0.3)**2`. Some secondary descriptions have inconsistent Mach
exponents or parentheses; the implemented choice also agrees with the
[OpenFAST implementation](https://github.com/OpenFAST/openfast/blob/main/modules/aerodyn/src/AeroAcoustics.f90).
The empirical maximum local velocity remains a source-model parameter;
no motion-based acoustic resampling is performed.

Equivalent force is obtained by the same stationary conversion as above and
placed near the tip/trailing-edge intersection using an area-normalized
kernel. Deposition width is at least one span cell. Zero effective tip angle
gives zero tip contribution. This is an approximate dipole representation of
tip loading, not a volumetric quadrupole model of the vortex wake.

The BPM empirical levels assume air; a `(density/1.225)**2` power correction
is applied. No claim of validation for other fluids is made.

## Time synthesis and computational cost

`BladeNoise` precomputes complex spectral factors on a mixed frequency grid.
Linear interpolation of those factors retains their phase approximately.
The frequency spacing includes a chord-convection phase-resolution criterion.
Check convergence by increasing `model_frequencies`, `gust_modes`, `n_span`,
and `n_chord` for a new geometry, especially at high reduced frequency.

FFT coefficients have the one-sided PSD normalization
`sqrt(N*fs/2) * H(f) * z`, where complex Gaussian `z` has unit expected squared
magnitude. DC and Nyquist bins are zero; the selected band has smooth edges.
Independent blocks overlap by half a block and use sine windows whose squared
weights sum to one. They are **not repeated loops**. Windowing slightly broadens
the spectrum (scale `fs/N`) and modifies long-lag coherence; enlarge blocks
when resolving low frequencies. The ensemble mean is zero; individual finite
records need not have exactly zero sample mean.

Block seeds depend on the master seed, mechanism and absolute block index.
Chunked requests, out-of-order requests and restart queries return the same
samples. Different mechanisms are independent. Use different seeds for
independent blades. Cross-blade incoming-turbulence correlation is not modeled.
A bounded cache and frequency slabs avoid allocating a full
`all frequencies × all cells × all gusts` tensor during synthesis.

The vendored Fresnel evaluation now uses the equivalent vectorized SciPy
special function, `C(sqrt(2*z/pi)) + i*S(sqrt(2*z/pi))`, rather than repeated
numerical quadrature. This changes calculation cost, not the response model.

## Usage and outputs

Dependencies are listed in `Generation/requirements-noise.txt`: NumPy, SciPy
and Matplotlib; Pillow is used for the optional GIF. They were already available in the development environment's Python 3.10.

From the repository root:

```bash
python3.10 Generation/noise.py --duration 0.25 --gif
python3.10 Generation/noise.py --config Generation/noise_example.json --gif
```

Default output directory: `Generation/outputs/noise/` (ignored by Git).

- `pressure_jump.npy`: float32 array `[n_span, n_chord, n_time]`, Pascals.
- `pressure_field.npz`: total, separate mechanisms, coordinates, cell areas,
  and sample times. Load with `numpy.load`, without pickle.
- `pressure_field.png`: component RMS maps, a pressure snapshot, space-time
  pressure history and spatially averaged pressure spectra.
- `pressure_field.gif`: optional slowed consecutive-sample animation.
- `noise_5s.wav`: **five seconds of newly generated continuous noise**, mono
  signed little-endian PCM int16 at 48 kHz, using the same source process.
  The audio is resampled from the synthesis clock without changing pitch or
  duration and published atomically after its WAV header is finalized. The preview is the area-averaged
  pressure jump, peak-normalized to -1 dBFS. It is not a far-field recording
  and its playback volume does not represent SPL. Spatial averaging can
  cancel pressure fluctuations, so it is not a preview of every local cell.
- `metadata.json`: inputs, boundary-layer estimates, RMS values, axis/units
  descriptions, timing and WAV gain. Divide normalized audio by the recorded
  `gain_per_pa` to approximately recover the area-averaged source pressure.

`--duration` controls saved field duration; the WAV always covers five seconds.
The first samples of both products describe the same realization. No short
field array is tiled to fill the audio file.

Python API:

```python
from Generation.noise import BladeConfig, BladeNoise, generate_pressure

cfg = BladeConfig(flow_speed=30., chord=.035, turbulence_intensity=.03,
                  angle_of_attack=4., span=.1, tip_shape='rounded', seed=12)
model = BladeNoise(cfg)
p = model.sample(24000)                       # [8, 12, 24000], Pa
next_p = model.sample(24000, start_sample=24000)
parts = model.sample_components(24000)
upper_pressure = +0.5 * p
lower_pressure = -0.5 * p
# A convenience call creates a model and returns just a numpy array:
p_short = generate_pressure(cfg, duration=.1)
```

Flow speed, chord, intensity, angle, length scale and supplied displacement
thicknesses accept scalars or arrays of exactly `n_span` values. Coordinates
are cell centers: span increases root-to-tip, chord fraction increases LE-to-TE.
Physical chord coordinates in `x_m` are measured from each strip's leading edge.
Pressure is an unsteady jump, not static lift or an absolute pressure.

## Mapping to the signed k-Wave mesh

`load_source()` now uses `Generation/kwave_noise.py` and `BladeNoise` instead
of the earlier `Amiet/source_noise.py` far-field-shaped prototype. The mapper
has no solver dependencies. Full experiments still start only from the runner.

The packed imaginary coordinate is decoded as:

```python
blade = code % 10
span_index = (code // 10) % 100
transverse_index = (code // 1000) % 100
chord_index = code // 100000
```

**The supplied mesh contract uses `mesh_idx_y` for chord**, regardless of the
historical names in SourceDrawer. The `t` field does not select a pressure
channel. For example, `100052` selects blade 2, span 0.5 and chord 0.1.
Index `i` means `i/10`, not `i/9`: index 5 means the middle of the span and
index 1 means 10% chord. Normal bins are 0–9; the exact endpoint bin 10 is also
accepted because `int(coordinate*10)` in SourceDrawer can produce it.
The pressure field is bilinearly interpolated from its cell centers to those
coordinates, with constant extension at blade edges.

For a decoded pressure jump, the source value is:

```python
source_pressure = amplitude * (mesh.real / 255) * pressure_jump / 2
```

This represents equal and opposite surface pressures `+jump/2` and `-jump/2`.
The mesh supplies the sign exactly once. `amplitude` is now a dimensionless
source gain (default 1), **not** a desired RMS or sine-wave peak. No chunkwise
normalization removes the model's flow-speed or turbulence dependence.
Each blade has a deterministic independent seed derived from `noise.seed` and
its blade index. If no seed is supplied, source type and position determine
the master seed. Thus restarting or changing chunk sizes preserves the signal;
different blades and sources need not share one waveform.

`MeshReader.sample(..., transform=...)` evaluates the mapper on each intact
endpoint frame **at the same output simulation times**, then interpolates the
two resulting pressures. It never interpolates packed labels. Even when two
opposite weights would cancel, contributions from different blade regions
remain distinct. Playback handles periodic wrap and arbitrary positive speed
without rounding the source time axis. When no transform is supplied, the
reader returns linearly interpolated weights and nearest-frame labels; this
fallback is for raw mesh inspection, not the source-pressure mapping.
Temporary endpoint arrays are bounded to 64 frames, and two mesh files are
cached per sampling request. Noise models are cached across solver chunks.

Pressure is sampled on the absolute acoustic clock using a local 16-tap
windowed-sinc interpolator. This avoids synthesizing noise FFTs at the solver's
potentially MHz sample rate. `phase` remains a time offset in seconds and
must not shift a request before zero; initial interpolation taps use constant
extension before zero. `speed` changes mesh playback only: provide the actual
blade-relative flow in `noise.flow_speed` for the selected operating speed.
`freq` is unused. No BPF envelope, Doppler resampling or extra motion effects
are added by this mapper.

A source configuration can now contain all `BladeConfig` options under `noise`:

```yaml
sources:
  - type: test2
    x: 120
    y: 150
    z: 4
    speed: 1.0
    amplitude: 1.0
    phase: 0.0
    noise:
      seed: 42
      flow_speed: 25.0       # actual relative speed, m/s; scalar or n_span values
      chord: 0.035           # m; scalar or n_span values
      span: 0.1              # modeled blade length, m
      turbulence_intensity: 0.025
      length_scale: 0.007
      angle_of_attack: 4.0   # degrees relative to zero lift
      tip_shape: rounded
      n_span: 8
      n_chord: 12
      sample_rate: 24000
      f_min: 80
      f_max: 8000
```

Missing `noise` options use the documented generator defaults. An old
`source.amiet` configuration must be migrated to `source.noise`; it is rejected
rather than silently used with a different model. The upper band is limited
to the smallest of requested `f_max`, 0.45 times the solver rate, 0.45 times
the synthesis rate, and `sound_speed/(4*max(dx,dy,dz))`. The last bound uses
four cells per wavelength as a conservative starting point. Heterogeneous
media or a different actual sound speed still require a resolution check.

[k-Wave's dipole example](https://www.k-wave.org/documentation/example_tvsp_homogeneous_medium_dipole.php)
allows opposite pressure sources or a velocity source. Pressure-source lobes
must balance in volume-weighted sum, while the dipole moment must remain
consistent as the blade crosses grid cells. Image normalization by 255 alone
cannot establish force or radiated SPL. The implemented scaling is a
pressure-like source convention; calibrate the solver source operator and
lobe separation before interpreting far-field levels as absolute predictions.
A moving zero-mean noise map also does not by itself establish correct
steady-loading or thickness tones.

## Validation performed

Run only the standalone checks with:

```bash
python3.10 -m unittest discover -s Generation/tests -v
```

Fourteen tests cover numerical Fresnel equivalence to independent quadrature,
chunk/restart reproducibility and absence of repeated blocks, one-sided PSD
variance normalization, conservation of the BPM-equivalent force spectra,
leading-edge turbulence-intensity scaling, mechanism independence, tip
localization and geometry sensitivity, span-varying/invalid inputs, and WAV
length/normalization/source consistency. These are numerical checks, not
experimental acoustic validation. Mapping tests additionally check the packed
coordinate example, ignored transverse coordinate, opposite signs, independent
blades, interpolation before label mixing, periodic playback, chunk boundaries
and source ordering. They use tiny synthetic NPZ meshes. The runner is never
imported: only its `load_source` function definition is extracted for the
placement test. No solver, worker processes or real mesh are executed.

For the default blade, increasing gust quadrature from 48 to 96 modes changed
the mean integrated leading-edge pressure PSD by about 0.24%; chordwise
integrated differences remained below 0.7%. This check does not establish
convergence for other geometries or all cross-spectral quantities.
The saved demo contains 0.25 seconds (`8 × 12 × 6000`) of pressure and a
240,000-sample, 48 kHz, five-second WAV. No real mesh integration was tested.


## Mesh-driven thickness source in k-Wave

`load_source()` now combines the existing broadband pressure source with
`Generation/kwave_thickness.py`. Displacement is enabled by default. It uses
only the rotating mesh, its `dt`/spacing, and `source.speed`; no rotor-preview
configuration, observer position, RPM value, or prescribed BPF is involved.
`probe.wav` remains the sampled propagated field.

**Temporary geometry approximation, explicitly authorized for this stage:**
the old mesh's red/blue regions are artificial pressure lobes, not solid blade
cross-sections. Their absolute weights are used only to locate a smooth proxy
volume distribution for each labeled blade. Its integral is normalized to a
fixed **1e-5 m³ (10 cm³) per blade**. This is an assumed volume, not a volume
measured from the pressure raster. Replace it after calculating the airfoil
area and integrating along the span. A future solid-volume channel can replace
this spatial proxy without changing the acoustic mass-source equation.

Optional per-source configuration:

```yaml
sources:
  - type: 03_diff_airfoil/1e-07/2/0.008
    speed: 1.1
    # ... existing x/y/z, amplitude and noise configuration ...
    thickness:
      enabled: true
      volume_per_blade_m3: 1.0e-5
      f_max: 6000
```

Set `thickness.enabled: false` to reproduce the old broadband-only source.
`amplitude` continues to scale broadband loading only; it does not change the
physical displaced volume. Set volume or disable thickness independently.
`speed: 0` freezes geometry and gives zero displacement noise while the local
broadband source may remain active.

For volume fraction `phi(x,t)` (displaced m³ per grid-cell m³), use

```
mass injection per unit volume = rho0 * dphi/dt       [kg/(m³ s)]
source.p_thickness = rho0*c0*dx/2 * dphi/dt            [Pa]
```

This conversion matches the **vendored** additive k-Wave pressure-source
scaling `2*dt/(N*c0*dx)` into each of N split-density fields. Their sum receives
`rho0*dphi/dt*dt`. The heterogeneous additive-pressure scaler also now converts
one-based source indices to zero-based NumPy indices when looking up c0.
The source worker receives the actual local medium impedance
`rho0*c0`, including heterogeneous sound speed and density. This is a mass
source, not a pressure waveform already propagated to an observer. It is the
volume-displacement representation of the thickness mechanism in the
[FW-H source equation](https://ntrs.nasa.gov/api/citations/19980119846/downloads/19980119846.pdf).

One geometry cycle is sampled and cached per mesh/settings, with each blade's
volume held constant at every phase. A smooth temporal low-pass filter reduces
voxel rasterization jitter. The cutoff is the minimum of `f_max` (default
6000 Hz), the grid's conservative four-cells-per-wavelength limit, solver and
mesh-playback Nyquist margins, and 45% of the exported sample rate. The periodic
cubic volume interpolant is differentiated at **absolute solver time**, so
chunking, checkpoint restarts and periodic wrap do not reset the source.
The first use reads through a mesh cycle; subsequent chunks reuse the cache.

The worker logs the blade count, assumed volume, cutoff, tracked centroid speed,
and estimated RPM. RPM is a diagnostic from the labeled blade's centroid angle
about the mesh's z axis. It can be unresolved for centered or nonrotating
geometry; the injected source uses volume changes, not that RPM estimate.

Limitations: the spatial volume proxy and assumed volume are provisional, and
absolute acoustic levels are not validated. Rasterization artifacts below the
cutoff can remain. Steady aerodynamic loading is still a separate missing
source mechanism. Place sources outside the PML: the earlier supplied source
at z=4..8 lies inside the default 10-cell absorbing layer and will be distorted
there. Changing source physics requires a **fresh experiment**, not resuming
an old acoustic checkpoint.


## Extract a probe from existing experiment outputs

```bash
# Center of the experiment.yml export region:
python3.10 Generation/KWave/src/extract_probe.py /experiments/102

# Explicit global grid indices in x, y, z order (not metres):
python3.10 Generation/KWave/src/extract_probe.py /experiments/102 --mic 239 227 191
```

The script creates these files under the experiment's `probes/` directory
(with coordinates in each filename):

- `probe_x239_y227_z191.npy`: raw pressure samples in chronological order.
- `probe_x239_y227_z191.png`: full-range pressure spectrum.
- `probe_x239_y227_z191_0-1500Hz.png`: detailed spectrum from 0 to 1500 Hz,
  with the same 1600 × 800 pixel image size. Fourfold FFT zero-padding makes
  the displayed curve denser; the recording duration still determines the
  actual ability to resolve nearby frequencies.
- `probe_x239_y227_z191_A-weighted.wav`: mono 48 kHz, 16-bit PCM listening
  preview with DC removed, A-weighting applied, and peak normalization to
  −1 dBFS. Normalization happens after resampling and filtering. Samples are
  rounded and clipped before integer conversion to prevent 16-bit overflow.

An existing probe cache is reused without reading the 3D output frames.
Both images and the WAV are regenerated even when using the cache. Use
`--refresh` to rebuild the cache after an experiment produces additional samples.

Both images use a full-record Hann periodogram in dB re 1 Pa²/Hz, with DC
removed for analysis only. They show **unweighted pressure**, so the A-weighted,
normalized WAV will have a different spectrum and level. The WAV's digital
A-weighting approximation is for listening, not calibrated SPL measurement;
normalization removes absolute pressure level information. Saved `.npy`
pressure samples are unchanged.

The frequency axis uses the runner's integer solver-step sampling cadence when
`mesh.dt` is available, otherwise `sampling`. Missing or duplicate frame numbers
and microphones outside the exported region are rejected instead of silently
compressing the time axis or selecting another voxel.

## Experiment source modes and propagating pressure bumps

`Generation/KWave/experiment.yml` exposes these source-only controls:

```yaml
source_mode: both        # amiet | loading | both
pressure_noise:
  peak_pa: 0.01          # Peak source.p amplitude per event; 0 disables (default)
  seed: 57
  rate_hz: 20.0          # Mean events/second across the entire grid
  radius_cells: 1.0     # Gaussian spatial sigma, truncated at 3 sigma
  duration_s: 0.001     # Duration of each smooth bipolar pulse
  src_replica: false    # Replay captured source sound instead of the bipolar pulse
```

`amiet` selects the existing leading/trailing-edge broadband model and skips
thickness generation. Tip noise is disabled in this mode. `loading` selects
the existing mesh-driven **thickness/displacement** model and skips broadband
synthesis; it is not a separate aerodynamic lift-loading model. `both` sums
the two. A source's `mode` overrides `source_mode`; `noise.leading_edge`,
`noise.trailing_edge` and `thickness.enabled` retain their existing controls.
With an explicit mode, tip noise defaults off; `noise.tip: true` can enable it
in `both` mode. Omitting modes retains the previous source defaults.

Pressure bumps are **solver sources**, not export noise. A seeded Poisson
event count and random start times/centers define localized events throughout
the grid. Each event has a Gaussian spatial footprint and one sine cycle
under a Hann envelope, with random polarity. The temporal shape has smooth
endpoints and zero continuous-time integral. `peak_pa` controls the peak
per-event pressure-source input before k-Wave's usual source scaling; it does
not specify receiver RMS pressure. Overlapping events add. The event rate is
an expectation; a short run can have no events. Events near the end are
truncated by the simulation duration. Locations include the absorbing boundary
region, where the solver's normal absorption applies.

With `src_replica: true`, each event replays the sources' own **sound**
instead of the bipolar pulse: a Hann window (`duration_s` long) over a
segment of the captured source sound, taken from a random earlier time.

The capture is what a distant listener hears toward the center of the
exported area: every source cell's `source.p` (amiet and thickness, all
sources) summed with its plane-wave propagation delay toward that point
(`SourceCapture` in `experiment_effects.py`). This is the radiated field, not
the local source term. Summed without delays, the thickness term cancels
almost exactly (a rigid blade keeps its volume) and the amiet lobes cancel in
pairs; with delays, the capture contains the thickness tones, the blade
dipole's spectral tilt, and the Doppler/modulation imprint as seen from that
direction. A bump replays it from a fixed point, with the same strength in
every direction - no motion or directivity is simulated for it.

`peak_pa` is then a dimensionless gain. The footprint is normalised to unit
sum, so with gain 1 an event's total `source.p` equals the captured signal,
and at an equal distance it radiates the sources' sound at the sources' level.
Each event's segment is chosen by the same seed (drawn after the schedule, so
event times and places do not change) and ends, plus the capture's largest
propagation delay, before the event starts. Events earlier than that have no
history and stay silent. A random earlier segment, rather than the same time,
keeps bumps from being coherent echoes of the sources.

Segments are computed on demand: when an event is first reached, the worker
re-synthesises the sources for that segment (plus the propagation margin).
The source is deterministic in time, so this equals replaying from a rolling
capture, needs no saved state across restarts, and costs about one extra
source synthesis of `duration_s` per event.

The source mask is the union of the original blade bounding box and the event
footprints. The worker places blade pressure into its corresponding rows and
adds the current event pulses to `source.p`, in k-Wave's x-fastest ordering.
This allocates time histories only for selected source cells, rather than a
full-grid × time array. Memory still grows with the union of all event
footprints, so increasing rate or radius increases source-buffer memory.
The same seed/configuration reproduces events across chunks and restarts.
All NPY, WAV and GIF output comes from propagated solver pressure.

The medium construction, original requirement for both seeds, medium images,
pressure slice renderer, export logic and post-solver input-file deletion are
restored to the committed version. There is no added pre-solver deletion,
medium configuration extension or medium diagnostics output.

Read-only verification found that `spheres_noise` arrays are assigned to
`medium.sound_speed` and `medium.density`, retained as `c0` and `rho0`, and
serialized as full spatial HDF5 datasets consumed by the CUDA solver. A tiny
writer test checks both arrays and their storage order. The saved experiment
102 output has `c_ref = 299.230133 m/s`, rather than the uniform 343 m/s default;
this supports use of the varied speed field but is not a voxelwise record of
the historical medium. No propagation experiment or full real mesh was run.

The earlier thickness implementation's `MeshReader.sample_at()` extension
samples arbitrary mesh phases so a periodic, filtered volume field can be
constructed and differentiated. `sample()` delegates to it for ordinary
contiguous time intervals. Zero playback speed represents stationary geometry;
real-valued fields can be interpolated without treating them as packed labels.
These changes predate the source-mode/background-noise work and are retained.
In `loading` mode, geometry is read through `sample_at()` inside `MeshThickness`
and the cached derivative is evaluated by `sample_volume_rate()`, so no extra
`mesh_reader.sample()` call is needed for each chunk.

`source_impedance` is `rho0*c0` at the blade source cells. The thickness branch
uses it in `source.p = rho0*c0*dx/2 * dphi/dt`, matching the vendored pressure
source conversion to split-density increments. It supplies local medium
values for converting the displacement rate; it is not another pressure field
or modification to the propagation medium.
