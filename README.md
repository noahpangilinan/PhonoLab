# PhonoLab

Acoustic analysis and annotation for speech — Praat's analyses with a modern, friendlier editor.

PhonoLab uses [Parselmouth](https://parselmouth.readthedocs.io) to run Praat's own algorithms, so
pitch, formant, intensity and spectrogram values match Praat exactly, and reads and writes
Praat-compatible TextGrids.

## Features

- **Sound + TextGrid editor** in tabs: overview strip, waveform (all channels), spectrogram with
  pitch, formant and intensity overlays, and annotation tiers, all on one time axis.
- **Fast on long recordings:** analyses run in background processes, the waveform is drawn as a
  screen-resolution envelope, and the spectrogram is recomputed for the visible window.
- **Annotation:** interval and point tiers, Enter or double-click to add boundaries, drag to move them,
  type to label, unlimited undo/redo. TextGrids are read and written in Praat's long and short text
  formats (UTF-8 and UTF-16). A `.TextGrid` next to the sound is loaded automatically.
- **Measurements:** a live readout under the mouse (time, amplitude, frequency, F0, F1–F4, intensity),
  selection statistics, and a Results panel for queries (F5 pitch, F1 formants, F8 intensity).
- **Settings** for each analysis, with a "Restore defaults" button that returns to Praat's values.
  Settings persist between sessions.
- **Export:** selection to WAV; pitch, formant, intensity and annotation tables to CSV; the view to PNG.
- Drag and drop sounds and TextGrids, recent files, and a prompt before unsaved annotations are lost.

## Getting started

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```sh
make setup          # create .venv and install dependencies
make run            # or: uv run phonolab [sound.wav ...]
```

Supported audio: WAV, FLAC, AIFF, OGG/Opus, and MP3 through libsndfile, plus M4A/AAC, MP4, WMA, WebM and anything
else FFmpeg decodes through PyAV, which bundles FFmpeg so nothing extra needs to be installed. Praat's reader is
the last fallback.

## Keyboard shortcuts

| Keys | Action |
| --- | --- |
| Space / Tab | Play the selection, or from the cursor to the end of the window; press again to stop |
| Esc | Stop |
| Ctrl+= / Ctrl+- | Zoom in / out |
| Ctrl+wheel | Zoom around the mouse |
| Wheel, Page Up/Down | Scroll |
| Ctrl+N / Ctrl+A | Zoom to selection / show all |
| Click, drag, Shift+click | Set cursor, select, extend selection |
| Enter / double-click in tier | Add a boundary (or point) |
| Delete / Alt+Backspace | Remove the boundary near the cursor |
| Alt+Left / Alt+Right, Up / Down | Previous/next interval, change tier |
| F5 / F1 / F8 / F2 | Query pitch / formants / intensity / duration |
| Ctrl+Z / Ctrl+Shift+Z | Undo / redo |

Help ▸ Keyboard shortcuts shows the same list in the app.

## Development

```sh
make test           # pytest (Qt runs offscreen)
make lint           # ruff check
make format         # ruff format
```

Code layout (`src/phonolab/`):

- `core/` — pure Python, no Qt: `sound.py`, `analysis.py` (settings dataclasses and compute
  functions), `queries.py`, `textgrid.py` (model and Praat file I/O), `settings.py`.
- `audio/player.py` — range playback through sounddevice.
- `ui/` — `main_window.py`, `document.py` (sound, TextGrid and undo stack), `workers.py` (process-pool
  analyses), docks, dialogs, and `editor/` (time axis controller, waveform, spectrogram and TextGrid panes).

Logs are written to the platform's user log directory (for example
`%LOCALAPPDATA%\PhonoLab\Logs\phonolab.log` on Windows).

## Roadmap

1. Voice analysis: pulses, voice report (jitter, shimmer, HNR), spectral slice, LTAS.
2. Manipulation: PSOLA pitch and duration editing with resynthesis.
3. Sound operations and synthesis: recording, filters, resampling, KlattGrid.
4. Scripting and batch: run `.praat` scripts, an embedded Python console, folder-wide batch analysis to CSV.
5. Publication-quality figures (SVG/PDF), a dark theme, and installers.

## License

GPL-3.0-or-later (required by Praat/Parselmouth). See [LICENSE](LICENSE).
