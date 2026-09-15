# Amiet airfoil-noise sound generator

Simulates the broadband sound produced by a **flat-plate airfoil in a turbulent
stream** using **Amiet's analytical model**, and turns the predicted spectrum
into an actual audio waveform that **loops seamlessly**.

The acoustic physics is provided by the third-party
[`amiet_tools`](https://github.com/fchirono/amiet_tools) package
(BSD-3-Clause), which is **vendored** in [`amiet_tools/`](amiet_tools/) so the
whole tool is self-contained in this folder (upstream commit `49a1717`).

## Why this approach

`amiet_tools` predicts a **power spectral density** `S_pp(f)` (Pa²/Hz) at an
observer — a *frequency distribution*, not a time signal. To get audio we:

1. **Predict** `S_pp(f)` on a log-spaced frequency grid (Amiet model).
2. **Interpolate** it onto the FFT-bin grid of an `N`-sample block.
3. **Shape white noise**: filter white Gaussian noise, in the DFT domain, by
   `H(f) = sqrt(S_pp(f)·fs/2)`, then inverse-FFT. This is exactly the
   "generate wide-band white noise, then filter to the target spectrum" idea.
   Because the filtering is *circular* (periodic over `N` samples), the block is
   **inherently periodic** → tiling it produces no click. The synthesised
   periodogram matches the target PSD to <1 % in-band.

Validated properties (see `--help` and the module docstring):
- Correct absolute scaling (variance = ∫S df).
- Seamless loop: the wrap-around step is the same size as ordinary
  sample-to-sample steps.

## Requirements

`numpy` and `scipy` (already present in the project's conda env). Nothing is
installed by the script. See [requirements.txt](requirements.txt).

## Usage

```bash
# Generate a 4096-sample seamless loop block AND a ~10 s looped WAV
python airfoil_noise.py --num-samples 4096 --export-wav --seed 0
```

Key parameters (all have defaults; run `python airfoil_noise.py --help`):

| Parameter | Meaning |
|-----------|---------|
| `--chord` | airfoil chord = **streamwise length** [m] |
| `--span`  | airfoil span = **lateral width** [m] |
| `--wind-speed` | mean flow velocity `Ux` [m/s] |
| `--turbulence-intensity` | `u_rms/Ux` [-] |
| `--length-scale` | turbulence integral length scale [m] |
| `--turbulence-model` | `K` (von Kármán) or `L` (Liepmann) |
| `--observer-distance` | observer distance normal to the plate [m] |
| `--sample-rate` | audio rate [Hz] (default 44100) |
| `--num-samples` | length of the seamless loop block (default 4096) |
| `--export-wav` / `--wav-duration` | export a looped demo WAV (default 10 s) |
| `--wav-format` | `int16` or `float32` |
| `--no-normalize` / `--peak-dbfs` | audio level control |
| `--engine` | `fast` (default) or `exact` (both numerically identical) |

### Airfoil "material properties"

Amiet's model treats the airfoil as a **rigid thin flat plate**, so material
properties (density, Young's modulus, …) **do not affect the predicted
sound**. `--material-name`, `--material-density`, `--youngs-modulus` are
accepted for interface completeness and stored in the metadata JSON only.

## Outputs (written to [`output/`](output/), git-ignored)

- `<prefix>_block.wav` — the `N`-sample seamless loop block.
- `<prefix>_block.npy` — the same block as raw `float64` **Pascals** (for exact
  numeric reuse; recover from WAV via `x_pa = x_unit / audio_gain`).
- `<prefix>_loop_10s.wav` — the block tiled to ~10 s (with `--export-wav`).
- `<prefix>_metadata.json` — all parameters plus the true RMS/SPL.

## VS Code

Launch config **"Amiet Airfoil Noise (4096 + 10s WAV)"** runs the command above.

## Reference

R. K. Amiet, "Acoustic radiation from an airfoil in a turbulent stream",
*Journal of Sound and Vibration*, 41(4):407–420, 1975.
