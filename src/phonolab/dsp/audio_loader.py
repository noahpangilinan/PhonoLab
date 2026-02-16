import librosa
import numpy as np


class AudioLoader:
    def __init__(self):
        self.signal = None
        self.sr = None
        self.duration = 0

    def load_file(self, file_path, target_sr=None):
        """
        Loads an audio file and returns the signal and sample rate.
        """
        try:
            signal, sr = librosa.load(file_path, sr=target_sr, mono=True)

            self.signal = signal
            self.sr = sr
            self.duration = librosa.get_duration(y=signal, sr=sr)

            return self.signal, self.sr
        except Exception as e:
            print(f"Error loading audio: {e}")
            return None, None

    def get_time_axis(self):
        """Returns a numpy array of time markers for plotting."""
        if self.signal is not None:
            return np.linspace(0, self.duration, len(self.signal))
        return None