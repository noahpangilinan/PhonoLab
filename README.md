# PhonoLab

Acoustic analysis and annotation for speech: Praat's analyses with a modern, friendlier editor.

PhonoLab uses [Parselmouth](https://parselmouth.readthedocs.io) to run Praat's own algorithms, so
measurements match Praat exactly, and it reads and writes Praat-compatible TextGrids.

## Features

**Editor**
- Sounds open in tabs. Each shows an overview strip, the waveform (all channels), a spectrogram with
  pitch, formant and intensity overlays, optional glottal pulses, and annotation tiers, all on one time axis.
- Fast on long recordings: analyses run in background processes, the waveform is drawn at screen
  resolution, and the spectrogram is recomputed for the visible window.
- Light and dark themes (View ▸ Theme), drag and drop, recent files, and prompts before unsaved work is lost.

**Annotation**
- Interval and point tiers. Enter or double-click adds a boundary, dragging moves it, and you type to label.
  Undo/redo covers everything.
- Praat backslash codes (`\ae`, `\sw`, …) display as IPA, and an IPA chart button inserts symbols.
- Find labels (Ctrl+F, F3) by text or regex. Searching for a symbol also matches its backslash code.
- Reads and writes Praat's long and short text formats (UTF-8 and UTF-16). A `.TextGrid` next to the
  sound loads automatically.

**Measurement**
- Live readout under the mouse (time, amplitude, frequency, F0, F1–F4, intensity) and selection statistics.
- Queries (results go to the Results panel):
  - Pitch: mean, median, sd, min and max with their times, mean absolute slope, and semitones.
  - Formants with bandwidths.
  - Intensity (energy-averaged).
- Voice report (jitter, shimmer, HNR) exactly as Praat prints it.
- Spectrum panel: a spectral slice or LTAS, spectral moments, and CPPS.
- Pitch methods: autocorrelation, cross-correlation and SHS. Formant methods: Burg and robust.
  Every setting has a "Restore defaults" button that returns it to Praat's value.

**Manipulation and sound operations**
- PSOLA manipulation: drag pitch points, stylize, shift or flatten the pitch, change durations, then play
  the resynthesis or open it in a new tab.
- Record from a microphone, generate tones and noise, and synthesize vowels (Klatt).
- Extract, resample, filter (pass band, stop band, pre-emphasis), scale, reverse, convert to mono and
  concatenate. Results open in new tabs; the original is never changed.

**Output and automation**
- Publication figures (Ctrl+P): waveform, spectrogram, pitch and TextGrid panels as PDF, SVG or PNG,
  in greyscale or colour.
- Batch measurement (Ctrl+B): measure every sound in a folder, or each labelled interval of a tier,
  into one CSV, in parallel.
- Script window (Ctrl+K): run Praat scripts (with form arguments) or Python on the current sound.
  New sounds and TextGrids come back into the editor.
- Export: the selection or whole sound (WAV, FLAC, AIFF, OGG, MP3), plus pitch, formant, intensity and
  annotation tables (CSV).

## Getting started

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```sh
make setup          # create .venv and install dependencies
make run            # or: uv run phonolab [sound.wav ...]
make package        # standalone app in dist/PhonoLab (PyInstaller)
```

Supported audio:
- WAV, FLAC, AIFF, OGG/Opus and MP3 through libsndfile.
- M4A/AAC, MP4, WMA, WebM and anything else FFmpeg decodes, through PyAV (which bundles FFmpeg, so
  there's nothing extra to install).
- Praat's own reader as the last fallback.

## Keyboard shortcuts

| Keys | Action |
| --- | --- |
| Space / Tab | Play the selection, or from the cursor to the end of the window; press again to stop |
| Shift+Space | Play the manipulated (resynthesised) sound |
| Esc | Stop |
| Ctrl+= / Ctrl+- | Zoom in / out |
| Ctrl+wheel | Zoom around the mouse |
| Wheel, Page Up/Down | Scroll |
| Ctrl+N / Ctrl+A | Zoom to selection / show all |
| Click, drag, Shift+click | Set cursor, select, extend selection |
| Enter / double-click in tier | Add a boundary (or point) |
| Delete / Alt+Backspace | Remove the boundary near the cursor |
| Alt+Left / Alt+Right, Up / Down | Previous/next interval, change tier |
| Ctrl+F, F3 / Shift+F3 | Find labels, next / previous match |
| F5 / F1 / F8 / F2 | Query pitch / formants / intensity / duration |
| F6 | Spectrum panel |
| Ctrl+Shift+V | Voice report |
| Ctrl+M | Show manipulation (Ctrl+click adds a pitch point) |
| Ctrl+E | Extract the selection to a new tab |
| Ctrl+R | Record |
| Ctrl+P / Ctrl+B / Ctrl+K | Figure / batch measure / script window |
| Ctrl+Z / Ctrl+Shift+Z | Undo / redo |

Help ▸ Keyboard shortcuts shows these in the app.

## Development

```sh
make test           # pytest (Qt runs offscreen)
make lint           # ruff check
make format         # ruff format
```

Code layout (`src/phonolab/`):

- `core/` is pure Python with no Qt. Analyses (`analysis.py`, `voice.py`, `spectrum.py`), queries, the
  analysis `registry.py`, `textgrid.py` with Praat I/O and search, `ipa.py`, `manipulation.py`,
  `sound_ops.py`, `batch.py`, `scripting.py` and `figures.py`.
- `audio/player.py` handles range playback through sounddevice.
- `ui/` holds the main window, the document model (sound, TextGrid, manipulation, one undo history),
  `workers.py` (process-pool analyses over shared memory), docks, dialogs, and `editor/` (time axis
  controller and panes).

Logs are written to the platform's user log directory (for example
`%LOCALAPPDATA%\PhonoLab\Logs\phonolab.log` on Windows).

## Not yet covered

- Pitch methods newer than the bundled Praat 6.1.38, such as filtered autocorrelation.
- Articulatory synthesis.
- Praat's statistics and learning tools (Table, PCA, OT grammars) and listening experiments.
- Binary TextGrid files.

## License

GPL-3.0-or-later (required by Praat/Parselmouth). See [LICENSE](LICENSE).
