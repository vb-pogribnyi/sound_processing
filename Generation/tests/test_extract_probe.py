"""Probe extraction tests using small synthetic experiment snapshots."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import yaml
from PIL import Image
from scipy.io import wavfile
from scipy.signal import sosfreqz

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from Generation.KWave.src.extract_probe import (extract_probe, exported_sample_rate,
                                                 save_listening_wav, a_weighting_sos)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.outputs = self.root/'outputs'
        self.outputs.mkdir()
        config = dict(sampling=16000, mesh=dict(dt=1e-7), export=dict(
            x_start=10, x_end=16, y_start=20, y_end=24, z_start=30, z_end=32))
        (self.root/'experiment.yml').write_text(yaml.safe_dump(config))
        self.base = np.arange(48, dtype=np.float32).reshape(2,4,6)-30
        # Unpadded names exercise numeric ordering past frame 9.
        for i in range(11):
            np.save(self.outputs/f'{i}.npy', self.base+i*100)

    def test_center_numeric_order_raw_values_and_spectrum(self):
        result = extract_probe(self.root)
        self.assertEqual(result['microphone'], (13,22,31))
        self.assertFalse(result['cached'])
        self.assertEqual(result['signal'].name, 'probe_x13_y22_z31.npy')
        signal = np.load(result['signal'])
        np.testing.assert_array_equal(signal, self.base[1,2,3]+np.arange(11)*100)
        self.assertEqual(signal.dtype, np.float32)
        self.assertEqual(result['spectrum'].read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        self.assertAlmostEqual(result['sample_rate'],16000)
        with Image.open(result['spectrum']) as full, Image.open(result['spectrum_detail']) as detail:
            self.assertEqual(full.size, (1600,800))
            self.assertEqual(detail.size, full.size)
        rate, audio = wavfile.read(result['wav'])
        self.assertEqual(rate,48000)
        self.assertEqual(len(audio),33)
        self.assertEqual(audio.dtype,np.int16)

    def test_explicit_coordinates_cache_without_outputs_and_refresh(self):
        with patch('Generation.KWave.src.extract_probe.save_spectrum') as plot:
            result = extract_probe(self.root,(10,21,30))
            np.testing.assert_array_equal(np.load(result['signal']),self.base[0,1,0]+np.arange(11)*100)
            saved = self.root/'saved_outputs'
            self.outputs.rename(saved)
            cached = extract_probe(self.root,(10,21,30))
            self.assertTrue(cached['cached'])
            self.assertEqual(plot.call_count,2)  # cached signal still regenerates plot
            saved.rename(self.outputs)
            np.save(self.outputs/'0.npy',np.full((2,4,6),-123,dtype=np.float32))
            refreshed = extract_probe(self.root,(10,21,30),refresh=True)
            self.assertFalse(refreshed['cached'])
            self.assertEqual(np.load(refreshed['signal'])[0],-123)

    def test_bounds_missing_frame_and_wrong_shape(self):
        for point in ((16,20,30),(10,19,30),(10,20,32)):
            with self.subTest(point=point),self.assertRaisesRegex(ValueError,'outside export'):
                extract_probe(self.root,point)
        (self.outputs/'5.npy').rename(self.outputs/'missing.npy')
        with self.assertRaisesRegex(ValueError,'consecutively'):
            extract_probe(self.root)
        (self.outputs/'missing.npy').rename(self.outputs/'5.npy')
        np.save(self.outputs/'5.npy',np.zeros((6,4,2),dtype=np.float32))
        with self.assertRaisesRegex(ValueError,'expected .* shape'):
            extract_probe(self.root)
        self.assertEqual(list((self.root/'probes').glob('*.npy')),[])

    def test_a_weighting_and_pcm_headroom_with_large_pressures(self):
        frequencies = np.array([125.,1000.,2000.])
        _, response = sosfreqz(a_weighting_sos(48000),worN=frequencies,fs=48000)
        np.testing.assert_allclose(20*np.log10(abs(response)),[-16.1,0.,1.2],atol=.15)
        fs = 16000
        t = np.arange(2*fs)/fs
        # DC and amplitudes vastly exceed int16; conversion must never wrap.
        signal = 2e300+1e300*(np.sin(2*np.pi*125*t)+np.sin(2*np.pi*1000*t))
        before = signal.copy()
        path = self.root/'listen.wav'
        save_listening_wav(path,signal,fs)
        np.testing.assert_array_equal(signal,before)
        rate, pcm = wavfile.read(path)
        self.assertEqual(rate,48000)
        self.assertEqual(pcm.dtype,np.int16)
        self.assertEqual(len(pcm),2*rate)
        peak = np.max(abs(pcm.astype(np.int32)))
        self.assertAlmostEqual(20*np.log10(peak/32767),-1.,places=3)
        # Analyze a settled one-second interval, clear of boundary transients.
        audio = pcm[rate//2:3*rate//2].astype(float)
        spectrum = abs(np.fft.rfft(audio))
        self.assertAlmostEqual(20*np.log10(spectrum[125]/spectrum[1000]),-16.1,delta=.2)

    def test_silent_and_fractional_rate_wav(self):
        for value in (0.,1e300,1e-300):
            with self.subTest(value=value):
                path = self.root/'silent.wav'
                save_listening_wav(path,np.full(100,value),16000)
                rate,pcm = wavfile.read(path)
                self.assertEqual(len(pcm),300)
                np.testing.assert_array_equal(pcm,0)
        fs = exported_sample_rate(dict(sampling=44000,mesh=dict(dt=1e-7)))
        save_listening_wav(path,np.zeros(1000),fs)
        rate,pcm = wavfile.read(path)
        self.assertEqual(len(pcm),round(1000*48000/fs))

    def test_actual_sampling_stride(self):
        self.assertAlmostEqual(exported_sample_rate(dict(sampling=44000,mesh=dict(dt=1e-7))),1/(227e-7))
        self.assertEqual(exported_sample_rate(dict(sampling=16000)),16000)


if __name__ == '__main__':
    unittest.main()
