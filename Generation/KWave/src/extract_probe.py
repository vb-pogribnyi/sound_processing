#!/usr/bin/env python3
"""Extract a cached pressure probe from numbered k-Wave output snapshots.

Microphone coordinates are global integer grid indices (x, y, z), not metres
or indices relative to the export crop. Without --mic, use the crop's center.
"""
import argparse
import os
import sys
from pathlib import Path
import tempfile
import wave
from fractions import Fraction

import numpy as np
import yaml
from scipy.signal import (periodogram, resample_poly, bilinear_zpk, zpk2sos,
                          sosfreqz, sosfilt, sosfilt_zi)
from scipy.fft import next_fast_len
from tqdm import tqdm


def report(message):
    print(message, file=sys.stderr, flush=True)


def probe_geometry(config, microphone=None):
    export = config['export']
    starts = tuple(int(export[f'{axis}_start']) for axis in 'xyz')
    ends = tuple(int(export[f'{axis}_end']) for axis in 'xyz')
    if any(start < 0 or end <= start for start, end in zip(starts, ends)):
        raise ValueError('Export bounds must be nonempty, nonnegative grid intervals')
    if microphone is None:
        microphone = tuple(start+(end-start)//2 for start, end in zip(starts, ends))
    if len(microphone) != 3 or any(int(v) != v for v in microphone):
        raise ValueError('Microphone must contain three integer grid coordinates: X Y Z')
    microphone = tuple(int(v) for v in microphone)
    if any(not start <= value < end for value, start, end in zip(microphone, starts, ends)):
        raise ValueError(f'Microphone {microphone} lies outside export bounds {starts} <= (x,y,z) < {ends}')
    # np.save stores each crop in z, y, x order.
    local_index = tuple(value-start for value, start in zip(microphone, starts))[::-1]
    shape = tuple(end-start for start, end in zip(starts, ends))[::-1]
    return microphone, local_index, shape


def exported_sample_rate(config):
    requested = float(config['sampling'])
    if not np.isfinite(requested) or requested <= 0:
        raise ValueError('sampling must be finite and positive')
    dt = config.get('mesh', {}).get('dt')
    if dt is None:
        return requested
    dt = float(dt)
    if not np.isfinite(dt) or dt <= 0:
        raise ValueError('mesh.dt must be finite and positive')
    # Match run_experiments.py: export cadence is an integer number of steps.
    stride = int(1/requested/dt)
    if stride < 1:
        raise ValueError('sampling exceeds the solver timestep rate')
    return 1/(stride*dt)


def validate_signal(signal):
    if (signal.ndim != 1 or signal.size == 0
            or not np.issubdtype(signal.dtype, np.number)
            or np.iscomplexobj(signal) or not np.isfinite(signal).all()):
        raise ValueError('Probe must be a nonempty, finite, real one-dimensional array')


def collect_signal(outputs_dir, local_index, expected_shape):
    report(f'Scanning pressure snapshots: {outputs_dir}')
    files = sorted((p for p in outputs_dir.glob('*.npy') if p.stem.isdecimal()),
                   key=lambda p: int(p.stem))
    if not files:
        raise ValueError(f'No numbered .npy pressure snapshots found in {outputs_dir}')
    if any(int(path.stem) != index for index, path in enumerate(files)):
        raise ValueError('Output frames must be numbered consecutively from 0; gaps or duplicates would corrupt timing')
    signal = None
    report(f'Found {len(files)} frames; extracting one pressure sample per frame.')
    for index, path in enumerate(tqdm(files, desc='Extracting pressure', unit='frame', dynamic_ncols=True)):
        # Read only the requested voxel; do not load the whole 3D crop into RAM.
        frame = np.load(path, mmap_mode='r', allow_pickle=False)
        if frame.shape != expected_shape:
            raise ValueError(f'{path.name}: expected (z,y,x) shape {expected_shape}, got {frame.shape}')
        if not np.issubdtype(frame.dtype, np.number) or np.iscomplexobj(frame):
            raise ValueError(f'{path.name}: expected real numeric pressure values')
        if signal is None:
            signal = np.empty(len(files), dtype=frame.dtype)
        elif frame.dtype != signal.dtype:
            raise ValueError(f'{path.name}: pressure dtype changed between snapshots')
        signal[index] = frame[local_index]
        del frame
    validate_signal(signal)
    return signal


def save_signal(path, signal):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.npy.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            np.save(stream, signal, allow_pickle=False)
            os.fchmod(stream.fileno(), path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def save_spectrum(path, signal, sample_rate, microphone, detail_path=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MultipleLocator

    report('Calculating spectrum (full-record Hann periodogram)...')
    pressure = signal.astype(np.float64)
    frequency, psd = periodogram(pressure, fs=sample_rate, window='hann',
                                 detrend='constant', scaling='density')

    def draw(destination, frequency, psd, limit, detail=False):
        # Both images have exactly the same canvas size: 1600 x 800 pixels.
        fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
        selected = frequency <= limit
        ax.plot(frequency[selected], 10*np.log10(np.maximum(psd[selected], 1e-30)), linewidth=.8)
        spacing = frequency[1]-frequency[0] if len(frequency) > 1 else sample_rate
        title = (f'Probe (x,y,z) = {microphone}\n'
                 f'{len(signal)} samples; fs = {sample_rate:.6g} Hz; '
                 f'native Δf = {sample_rate/len(signal):.6g} Hz; Hann, DC removed')
        if detail:
            title += f'\n0–1500 Hz detail; zero-padded display spacing = {spacing:.6g} Hz'
            ax.xaxis.set_major_locator(MultipleLocator(100))
            ax.xaxis.set_minor_locator(MultipleLocator(50))
        ax.set(xlabel='Frequency [Hz]', ylabel='Pressure PSD [dB re 1 Pa²/Hz]',
               xlim=(0, limit), title=title)
        ax.grid(alpha=.25)
        if not np.any(psd > 0):
            ax.text(.5, .5, 'No varying pressure (display floor: −300 dB)',
                    transform=ax.transAxes, ha='center')
        try:
            report(f'Saving spectrum image: {destination}')
            fig.savefig(destination, dpi=160)
        finally:
            plt.close(fig)

    draw(path, frequency, psd, sample_rate/2)
    if detail_path is not None:
        report('Calculating detailed 0–1500 Hz spectrum...')
        # Interpolate the FFT curve more densely; this does not add independent
        # frequency resolution, which is still determined by record duration.
        frequency, psd = periodogram(pressure, fs=sample_rate, window='hann',
                                     detrend='constant', scaling='density',
                                     nfft=next_fast_len(4*len(signal)))
        draw(detail_path, frequency, psd, 1500., detail=True)


def a_weighting_sos(sample_rate):
    """Digital approximation to the IEC A-weighting curve, unity at 1 kHz.

    Analog poles follow IEC 61672's A-weighting transfer function:
    https://python-acoustics.github.io/python-acoustics/standards.html
    Bilinear discretization is used for listening, not certified metrology.
    """
    if not np.isfinite(sample_rate) or sample_rate <= 2000:
        raise ValueError('A-weighting requires a sample rate above 2000 Hz')
    poles = -2*np.pi*np.array([20.598997, 20.598997, 107.65265,
                              737.86223, 12194.217, 12194.217])
    zeros, poles, gain = bilinear_zpk(np.zeros(4), poles, (2*np.pi*12194.217)**2,
                                    fs=sample_rate)
    sos = zpk2sos(zeros, poles, gain)
    _, response = sosfreqz(sos, worN=[1000.], fs=sample_rate)
    sos[0, :3] /= abs(response[0])
    return sos


def save_listening_wav(path, signal, sample_rate, output_rate=48000):
    """DC-free, A-weighted, peak-normalized PCM16 listening preview."""
    validate_signal(signal)
    if not np.isfinite(sample_rate) or sample_rate <= 0:
        raise ValueError('WAV source sample rate must be finite and positive')
    if not isinstance(output_rate, int) or output_rate <= 0:
        raise ValueError('WAV output rate must be a positive integer')
    report('Preparing listening audio: removing DC and resampling to '
           f'{output_rate} Hz...')
    audio = signal.astype(np.float64)
    # Scale before taking the mean: even very large finite pressures must not
    # overflow during DC removal. Preserve one gain for the entire recording.
    peak = float(np.max(np.abs(audio)))
    if peak:
        audio /= peak
    audio -= audio.mean()
    if sample_rate != output_rate:
        ratio = Fraction(output_rate/sample_rate).limit_denominator(100000)
        audio = resample_poly(audio, ratio.numerator, ratio.denominator)
        audio = audio[:max(1, round(len(signal)*output_rate/sample_rate))]
    report('Applying A-weighting for listening (0 dB at 1 kHz)...')
    sos = a_weighting_sos(output_rate)
    audio, _ = sosfilt(sos, audio, zi=sosfilt_zi(sos)*audio[0])
    if not np.isfinite(audio).all():
        raise ValueError('Nonfinite audio after resampling and A-weighting')
    peak = float(np.max(np.abs(audio)))
    if peak:
        audio /= peak
    # Normalize AFTER resampling and A-weighting to account for overshoot, then clip
    # in floating point BEFORE conversion. No integer wraparound is possible.
    pcm = np.clip(np.rint(audio*10**(-1/20)*32767), -32768, 32767).astype('<i2')
    report(f'Saving listening WAV: {path} (mono PCM16, peak target −1 dBFS)')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.wav.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            with wave.open(stream, 'wb') as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(output_rate)
                writer.writeframes(pcm.tobytes())
            os.fchmod(stream.fileno(), path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def extract_probe(experiment, microphone=None, refresh=False):
    """Return output paths, selected coordinates, sample rate/count, and cache status."""
    experiment = Path(experiment)
    report(f'Reading experiment configuration: {experiment / "experiment.yml"}')
    with (experiment/'experiment.yml').open() as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError('experiment.yml must contain an experiment configuration')
    placement = 'center of export region' if microphone is None else 'requested position'
    microphone, index, shape = probe_geometry(config, microphone)
    report(f'Probe placement: {placement}')
    report(f'  Global grid coordinates (x, y, z): {microphone}')
    report(f'  Within export crop (x, y, z): {index[::-1]} of size {shape[::-1]}')
    sample_rate = exported_sample_rate(config)
    report(f'  Export sample rate: {sample_rate:.6g} Hz')
    probes = experiment/'probes'
    probes.mkdir(parents=True, exist_ok=True)
    stem = 'probe_x{}_y{}_z{}'.format(*microphone)
    signal_path, spectrum_path = probes/(stem+'.npy'), probes/(stem+'.png')
    detail_path = probes/(stem+'_0-1500Hz.png')
    wav_path = probes/(stem+'_A-weighted.wav')
    report(f'Checking probe cache: {signal_path}')
    cached = signal_path.exists() and not refresh
    if cached:
        report('Loading cached pressure signal...')
        signal = np.load(signal_path, allow_pickle=False)
        validate_signal(signal)
    else:
        report('Refreshing probe from current outputs...' if refresh else 'No cached probe found; reading outputs...')
        signal = collect_signal(experiment/'outputs', index, shape)
        report(f'Saving pressure cache: {signal_path}')
        save_signal(signal_path, signal)
    report(f'Pressure signal ready: {len(signal)} samples, {len(signal)/sample_rate:.6g} s. Preparing spectrum...')
    # Also repairs a missing image without rereading any output snapshots.
    save_spectrum(spectrum_path, signal, sample_rate, microphone, detail_path=detail_path)
    save_listening_wav(wav_path, signal, sample_rate)
    return dict(signal=signal_path, spectrum=spectrum_path, spectrum_detail=detail_path,
                wav=wav_path, microphone=microphone,
                sample_rate=sample_rate, samples=len(signal), cached=cached)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment', type=Path, help='Experiment directory, e.g. /experiments/102')
    parser.add_argument('--mic', '--microphone', type=int, nargs=3, metavar=('X', 'Y', 'Z'),
                        help='Global grid coordinates; default: center of export region')
    parser.add_argument('--refresh', action='store_true', help='Rebuild an existing cache from current outputs')
    args = parser.parse_args()
    try:
        result = extract_probe(args.experiment, args.mic, args.refresh)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        parser.exit(1, f'Error: {exc}\n')
    print(f"{'Loaded cached' if result['cached'] else 'Extracted'} probe {result['microphone']}: "
          f"{result['samples']} samples at {result['sample_rate']:.6g} Hz")
    print(f"Pressure: {result['signal']}")
    print(f"Spectrum: {result['spectrum']}")
    print(f"Spectrum (0–1500 Hz): {result['spectrum_detail']}")
    print(f"Listening WAV: {result['wav']}")


if __name__ == '__main__':
    main()
