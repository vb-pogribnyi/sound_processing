#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
airfoil_noise.py -- Turbulence-airfoil interaction noise simulator.

This tool predicts the broadband sound radiated by a flat-plate airfoil immersed
in a turbulent stream using Amiet's analytical model (Amiet, JSV 41(4):407-420,
1975), as implemented by the vendored third-party ``amiet_tools`` package
(https://github.com/fchirono/amiet_tools, BSD-3-Clause). It then turns the
predicted power spectral density (PSD) into an actual, seamlessly loopable
audio waveform.

Pipeline
--------
1.  Amiet's model gives a far-field acoustic PSD  S_pp(f)  [Pa^2/Hz] at a single
    observer, evaluated on a log-spaced frequency grid (this is a *spectrum*, not
    a waveform).
2.  That spectrum is interpolated onto the FFT-bin grid of an N-sample block.
3.  The waveform is synthesised by *shaping white noise*: white Gaussian noise is
    transformed to the frequency domain, its spectrum is multiplied by the
    shaping filter  H(f) = sqrt(S_pp(f) * fs / 2), and transformed back. This is
    the randomized-phase / circular-filtering method. Because the operation is a
    circular (periodic) filtering of a length-N sequence, the resulting block is
    *inherently periodic*: concatenating copies produces no discontinuity, so it
    loops seamlessly by construction.
4.  Optionally, the block is tiled to build a ~10 s WAV demo (the same block
    looped), which is therefore also seamless.

Note on "airfoil material properties"
-------------------------------------
Amiet's turbulence-interaction model treats the airfoil as a *rigid, thin flat
plate*. Material properties (density, Young's modulus, ...) therefore do NOT
enter the acoustic prediction. Such parameters are accepted on the command line
for interface completeness and are recorded in the output metadata, but they do
not change the generated spectrum. (Structural vibration / material-dependent
radiation would require a different, aeroelastic model.)

Author: generated for the sound_processing project.
"""

import argparse
import datetime
import json
import os
import sys

import numpy as np
from scipy.io import wavfile

# --- Import the vendored third-party Amiet library -------------------------
# All third-party code lives next to this script (Generation/Amiet/amiet_tools),
# so make sure that directory is importable regardless of the current working
# directory, and that it takes precedence over any globally installed copy.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import amiet_tools as AmT  # noqa: E402


# ---------------------------------------------------------------------------
# Amiet far-field PSD evaluation
# ---------------------------------------------------------------------------
def make_psd_evaluator(setup, geom, obs_xyz, turb_model="K", engine="fast"):
    """Return a function ``psd_at(f0) -> S_pp`` [Pa^2/Hz] at a single observer.

    Two numerically identical engines are provided:

    ``exact``
        Uses the library wrapper ``amiet_tools.calc_radiated_Spp`` which forms
        the full (Nx*Ny)x(Nx*Ny) surface-pressure cross-spectral matrix.

    ``fast`` (default)
        For a *single* observer the radiated PSD collapses to

            S_pp = 4*pi * Ux * dKy * sum_ky | sum_n g_n * a_n * dp_ky,n |^2

        where ``g`` is the dipole Green's function row, ``a`` the per-point
        surface-area weights and ``dp_ky`` the single-gust pressure jump. This
        avoids ever forming the dense source CSM. It has been verified to match
        the ``exact`` engine to ~1e-15 relative error.
    """
    (c0, rho0, p_ref, Ux, turb_intensity, length_scale, z_sl, Mach, beta,
     flow_param, dipole_axis) = setup.export_values()
    (b, d, Nx, Ny, XYZ_airfoil, dx, dy) = geom.export_values()

    XYZ_calc = XYZ_airfoil.reshape(3, Nx * Ny)
    # per-point surface area weight, flattened in the same (Ny, Nx) C-order as
    # amiet_tools uses internally
    area = (np.ones((Ny, Nx)) * dx[np.newaxis, :] * dy).reshape(Nx * Ny)

    def psd_at(f0):
        freq_vars = AmT.FrequencyVars(f0, setup)
        (k0, Kx, Ky_crit) = freq_vars.export_values()

        # spanwise gust wavenumbers relevant for acoustic radiation, and the
        # matching turbulent velocity (von Karman 'K' or Liepmann 'L') spectrum
        Ky = AmT.ky_vector(b, d, k0, Mach, beta, method="AcRad")
        Phi = AmT.Phi_2D(Kx, Ky, Ux, turb_intensity, length_scale,
                         model=turb_model)[0]

        if engine == "exact":
            G = AmT.dipole3D(XYZ_calc, obs_xyz, k0, dipole_axis, flow_param)
            Spp = AmT.calc_radiated_Spp(setup, geom, freq_vars, Ky, Phi, G)
            return float(np.real(Spp[0, 0]))

        # fast single-observer path
        g = AmT.dipole3D(XYZ_calc, obs_xyz, k0, dipole_axis, flow_param)[0]
        ga = g * area
        dky = Ky[1] - Ky[0]
        acc = 0.0
        for i in range(Ky.size):
            w0 = np.sqrt(Phi[i])
            dp = AmT.delta_p(rho0, b, w0, Kx, Ky[i], XYZ_airfoil[0:2],
                             Mach).reshape(Nx * Ny)
            acc += abs(np.dot(ga, dp)) ** 2
        return 4.0 * np.pi * Ux * dky * acc

    return psd_at


def sweep_psd(psd_at, f_min, f_max, n_freqs, progress=True):
    """Evaluate the Amiet PSD on a log-spaced frequency grid."""
    freqs = np.logspace(np.log10(f_min), np.log10(f_max), n_freqs)
    psd = np.empty(n_freqs)
    for i, f0 in enumerate(freqs):
        psd[i] = psd_at(f0)
        if progress:
            pct = 100.0 * (i + 1) / n_freqs
            print("\r  Amiet sweep: %3.0f%%  (f = %8.1f Hz, %d/%d)"
                  % (pct, f0, i + 1, n_freqs), end="", flush=True)
    if progress:
        print()
    return freqs, psd


# ---------------------------------------------------------------------------
# Spectrum -> waveform (white-noise shaping, seamless loop)
# ---------------------------------------------------------------------------
def target_psd_on_fft_grid(freqs, psd, n_samples, fs, f_min, f_max):
    """Interpolate the sampled Amiet PSD onto the rFFT-bin grid.

    Interpolation is done in log-frequency / decibel space for a smooth shape.
    Bins below ``f_min`` are set to zero (removes sub-audio rumble / DC); bins
    above the evaluated range are clamped to the last value.
    """
    f_grid = np.fft.rfftfreq(n_samples, d=1.0 / fs)
    f_clip = np.clip(f_grid, freqs[0], freqs[-1])
    db = np.interp(np.log10(f_clip), np.log10(freqs), 10.0 * np.log10(psd))
    S = 10.0 ** (db / 10.0)
    S[f_grid < f_min] = 0.0
    return f_grid, S


def synthesize_block(S_target, f_grid, n_samples, fs, f_min, seed=None):
    """Synthesise one seamlessly-loopable block of length ``n_samples`` (in Pa).

    White Gaussian noise is filtered (circularly, i.e. in the DFT domain) by the
    shaping filter ``H = sqrt(S_target * fs / 2)``. The result is an inherently
    periodic real sequence, so tiling it produces no seam.
    """
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n_samples)
    W = np.fft.rfft(white)

    H = np.sqrt(np.maximum(S_target, 0.0) * fs / 2.0)
    H[f_grid < f_min] = 0.0
    H[0] = 0.0  # no DC offset

    x = np.fft.irfft(W * H, n=n_samples)
    return x


# ---------------------------------------------------------------------------
# Audio output helpers
# ---------------------------------------------------------------------------
def to_unit_scale(x_pa, normalize, peak_dbfs):
    """Map the physical Pa waveform to the [-1, 1] audio range.

    Returns (x_unit, gain) so the physical signal can be recovered as
    ``x_pa = x_unit / gain``.
    """
    peak = float(np.max(np.abs(x_pa))) or 1.0
    if normalize:
        gain = (10.0 ** (peak_dbfs / 20.0)) / peak
    else:
        gain = 1.0
    return x_pa * gain, gain


def write_wav(path, x_unit, fs, fmt):
    """Write a mono WAV in int16 or float32."""
    x_clipped = np.clip(x_unit, -1.0, 1.0)
    if fmt == "int16":
        data = np.int16(np.round(x_clipped * 32767.0))
    else:  # float32
        data = x_clipped.astype(np.float32)
    wavfile.write(path, int(fs), data)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        description="Simulate turbulence-airfoil interaction noise (Amiet "
                    "model) and synthesise a seamlessly loopable waveform.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    g = p.add_argument_group("airfoil geometry")
    g.add_argument("--chord", type=float, default=0.15,
                   help="airfoil chord = streamwise LENGTH [m]")
    g.add_argument("--span", type=float, default=0.45,
                   help="airfoil span = lateral WIDTH [m]")

    f = p.add_argument_group("flow & turbulence")
    f.add_argument("--wind-speed", type=float, default=60.0,
                   help="mean flow velocity Ux [m/s]")
    f.add_argument("--turbulence-intensity", type=float, default=0.025,
                   help="turbulence intensity u_rms/Ux [-]")
    f.add_argument("--length-scale", type=float, default=0.007,
                   help="turbulence integral length scale [m]")
    f.add_argument("--turbulence-model", choices=["K", "L"], default="K",
                   help="turbulent velocity spectrum: K=von Karman, L=Liepmann")
    f.add_argument("--speed-of-sound", type=float, default=340.0,
                   help="speed of sound c0 [m/s]")
    f.add_argument("--air-density", type=float, default=1.2,
                   help="air density rho0 [kg/m^3]")

    o = p.add_argument_group("observer")
    o.add_argument("--observer-distance", type=float, default=1.2,
                   help="observer distance below the plate (along dipole axis) [m]")
    o.add_argument("--observer-x", type=float, default=0.0,
                   help="observer chordwise offset x [m]")
    o.add_argument("--observer-y", type=float, default=0.0,
                   help="observer spanwise offset y [m]")
    o.add_argument("--p-ref", type=float, default=20e-6,
                   help="reference pressure for SPL [Pa RMS]")

    m = p.add_argument_group("airfoil material (recorded only; see module doc)")
    m.add_argument("--material-name", type=str, default=None,
                   help="informational; does NOT affect the Amiet prediction")
    m.add_argument("--material-density", type=float, default=None,
                   help="informational; does NOT affect the Amiet prediction")
    m.add_argument("--youngs-modulus", type=float, default=None,
                   help="informational; does NOT affect the Amiet prediction")

    s = p.add_argument_group("spectrum evaluation")
    s.add_argument("--grid-nx", type=int, default=20,
                   help="chordwise mesh points on the airfoil")
    s.add_argument("--grid-ny", type=int, default=21,
                   help="spanwise mesh points on the airfoil")
    s.add_argument("--n-freqs", type=int, default=40,
                   help="number of log-spaced frequencies for the Amiet sweep")
    s.add_argument("--f-min", type=float, default=50.0,
                   help="lowest frequency evaluated / synthesised [Hz]")
    s.add_argument("--f-max", type=float, default=None,
                   help="highest frequency evaluated [Hz] (default: Nyquist)")
    s.add_argument("--engine", choices=["fast", "exact"], default="fast",
                   help="single-observer PSD engine (numerically identical)")

    y = p.add_argument_group("synthesis & output")
    y.add_argument("--sample-rate", type=int, default=44100,
                   help="audio sample rate [Hz]")
    y.add_argument("--num-samples", type=int, default=4096,
                   help="length of the seamless loop block [samples]")
    y.add_argument("--seed", type=int, default=None,
                   help="RNG seed for reproducible noise realisation")
    y.add_argument("--wav-format", choices=["int16", "float32"],
                   default="int16", help="WAV sample format")
    y.add_argument("--no-normalize", dest="normalize", action="store_false",
                   help="do NOT peak-normalise (write raw physical scaling)")
    y.add_argument("--peak-dbfs", type=float, default=-3.0,
                   help="peak level when normalising [dBFS]")
    y.add_argument("--export-wav", action="store_true",
                   help="also export a looped ~N-second WAV demo")
    y.add_argument("--wav-duration", type=float, default=10.0,
                   help="target duration of the looped WAV demo [s]")
    y.add_argument("--out-dir", type=str, default=os.path.join(_HERE, "output"),
                   help="directory for generated files")
    y.add_argument("--prefix", type=str, default="amiet_airfoil",
                   help="output filename prefix")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    fs = args.sample_rate
    N = args.num_samples
    f_max = args.f_max if args.f_max is not None else fs / 2.0
    if f_max > fs / 2.0:
        raise SystemExit("--f-max cannot exceed Nyquist (%.1f Hz)" % (fs / 2.0))
    os.makedirs(args.out_dir, exist_ok=True)

    # --- Build the Amiet model setup from CLI parameters -------------------
    # amiet_tools uses semichord (b) and semispan (d)
    setup = AmT.TestSetup(
        c0=args.speed_of_sound, rho0=args.air_density, p_ref=args.p_ref,
        Ux=args.wind_speed, turb_intensity=args.turbulence_intensity,
        length_scale=args.length_scale, z_sl=-max(args.observer_distance, 0.075))
    geom = AmT.AirfoilGeom(b=args.chord / 2.0, d=args.span / 2.0,
                           Nx=args.grid_nx, Ny=args.grid_ny)
    obs = np.array([[args.observer_x], [args.observer_y],
                    [-abs(args.observer_distance)]])

    print("Amiet turbulence-airfoil noise simulation")
    print("  chord (length) = %.4f m   span (width) = %.4f m"
          % (args.chord, args.span))
    print("  Ux = %.1f m/s   Mach = %.3f   turb.I = %.3f   Lambda = %.4f m"
          % (args.wind_speed, setup.Mach, args.turbulence_intensity,
             args.length_scale))
    print("  observer = (%.3f, %.3f, %.3f) m   fs = %d Hz   block = %d samples"
          % (obs[0, 0], obs[1, 0], obs[2, 0], fs, N))
    if args.material_name or args.material_density or args.youngs_modulus:
        print("  NOTE: material properties are recorded only; Amiet's rigid "
              "flat-plate model ignores them.")

    # --- 1) Predict the far-field PSD spectrum -----------------------------
    psd_at = make_psd_evaluator(setup, geom, obs,
                                turb_model=args.turbulence_model,
                                engine=args.engine)
    freqs, psd = sweep_psd(psd_at, args.f_min, f_max, args.n_freqs)

    # --- 2) & 3) shape white noise into a seamless block -------------------
    f_grid, S_target = target_psd_on_fft_grid(freqs, psd, N, fs,
                                              args.f_min, f_max)
    x_pa = synthesize_block(S_target, f_grid, N, fs, args.f_min, seed=args.seed)

    rms = float(np.sqrt(np.mean(x_pa ** 2)))
    spl = 20.0 * np.log10(rms / args.p_ref) if rms > 0 else float("-inf")
    peak_pa = float(np.max(np.abs(x_pa)))
    print("  synthesised block: RMS = %.4e Pa  =>  SPL = %.1f dB re 20 uPa "
          "(peak %.4e Pa)" % (rms, spl, peak_pa))

    x_unit, gain = to_unit_scale(x_pa, args.normalize, args.peak_dbfs)

    # --- Write outputs -----------------------------------------------------
    base = os.path.join(args.out_dir, args.prefix)
    block_wav = base + "_block.wav"
    block_npy = base + "_block.npy"
    write_wav(block_wav, x_unit, fs, args.wav_format)
    np.save(block_npy, x_pa)  # physical Pa, for exact reuse
    print("  wrote loop block : %s  (%d samples, %.1f ms)"
          % (block_wav, N, 1000.0 * N / fs))
    print("  wrote raw block  : %s  (float64 Pa)" % block_npy)

    loop_info = None
    if args.export_wav:
        n_blocks = max(1, int(round(args.wav_duration * fs / N)))
        loop = np.tile(x_unit, n_blocks)  # identical copies => perfectly seamless
        actual_dur = loop.size / fs
        loop_wav = base + "_loop_%gs.wav" % args.wav_duration
        write_wav(loop_wav, loop, fs, args.wav_format)
        loop_info = {"path": loop_wav, "n_blocks": n_blocks,
                     "n_samples": int(loop.size), "duration_s": actual_dur}
        print("  wrote looped WAV : %s  (%d x block = %.3f s)"
              % (loop_wav, n_blocks, actual_dur))

    # --- Metadata sidecar --------------------------------------------------
    meta = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "model": "Amiet turbulence-airfoil interaction (amiet_tools, BSD-3)",
        "geometry": {"chord_m": args.chord, "span_m": args.span},
        "flow": {"wind_speed_ms": args.wind_speed, "mach": setup.Mach,
                 "turbulence_intensity": args.turbulence_intensity,
                 "length_scale_m": args.length_scale,
                 "turbulence_model": args.turbulence_model,
                 "speed_of_sound_ms": args.speed_of_sound,
                 "air_density_kgm3": args.air_density},
        "observer": {"x_m": args.observer_x, "y_m": args.observer_y,
                     "distance_m": args.observer_distance},
        "material_informational_only": {
            "name": args.material_name, "density": args.material_density,
            "youngs_modulus": args.youngs_modulus},
        "synthesis": {"sample_rate_hz": fs, "num_samples": N,
                      "f_min_hz": args.f_min, "f_max_hz": f_max,
                      "n_freqs": args.n_freqs, "engine": args.engine,
                      "grid_nx": args.grid_nx, "grid_ny": args.grid_ny,
                      "seed": args.seed},
        "levels": {"rms_pa": rms, "spl_db": spl, "peak_pa": peak_pa,
                   "audio_gain": gain, "normalized": args.normalize,
                   "peak_dbfs": args.peak_dbfs if args.normalize else None},
        "outputs": {"block_wav": block_wav, "block_npy": block_npy,
                    "loop_wav": loop_info},
    }
    meta_path = base + "_metadata.json"
    with open(meta_path, "w") as fh:
        json.dump(meta, fh, indent=2)
    print("  wrote metadata   : %s" % meta_path)
    print("Done.")


if __name__ == "__main__":
    main()
