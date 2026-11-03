# PhonoLab

**Acoustic analysis and annotation for speech: Praat's algorithms with a modern editor.**

PhonoLab is a desktop application for phoneticians, speech scientists, linguists and clinicians. It runs
[Praat](https://www.fon.hum.uva.nl/praat/)'s own analysis code through
[Parselmouth](https://parselmouth.readthedocs.io), so pitch, formant, intensity, voice and spectral
measurements are the same numbers Praat produces. It wraps them in an editor built around everyday work:
tabs, drag and drop, one undo history, live readouts, background analysis, IPA input, search, batch
processing and publication figures.

TextGrids are read and written in Praat's own formats, so you can move between PhonoLab and Praat at any time.

---

## Contents

1. [Features at a glance](#features-at-a-glance)
2. [Installation](#installation)
3. [Quick start](#quick-start)
4. [The editor](#the-editor)
5. [Annotation (TextGrids)](#annotation-textgrids)
6. [Measurements and queries](#measurements-and-queries)
7. [Manipulation (PSOLA)](#manipulation-psola)
8. [Sound operations, recording and synthesis](#sound-operations-recording-and-synthesis)
9. [Batch measurement](#batch-measurement)
10. [Scripting (Praat and Python)](#scripting-praat-and-python)
11. [Publication figures](#publication-figures)
12. [Analysis settings and defaults](#analysis-settings-and-defaults)
13. [Keyboard shortcuts](#keyboard-shortcuts)
14. [Menu reference](#menu-reference)
15. [How results relate to Praat](#how-results-relate-to-praat)
16. [Files, formats and preferences](#files-formats-and-preferences)
17. [Architecture](#architecture)
18. [Development](#development)
19. [Troubleshooting](#troubleshooting)
20. [Not yet covered](#not-yet-covered)
21. [License](#license)

---

## Features at a glance

| Area | What you get |
| --- | --- |
| **Viewing** | Overview strip, multichannel waveform, spectrogram with pitch, formant and intensity overlays, glottal pulses, annotation tiers, all on one time axis |
| **Speed** | Analyses run in background processes, so the window never freezes. The waveform is drawn at screen resolution, and the spectrogram is recomputed for what you're looking at. Five-minute recordings stay smooth. |
| **Annotation** | Interval and point tiers, boundary editing by keyboard or mouse, type-to-label, IPA chart, Praat backslash codes shown as IPA, search, undo/redo |
| **Measurement** | Live readout under the mouse, selection statistics, pitch/formant/intensity queries, voice report (jitter, shimmer, HNR), spectral slice, LTAS, spectral moments, CPPS |
| **Methods** | Pitch by autocorrelation, cross-correlation or subharmonic summation; formants by Burg or robust LPC |
| **Manipulation** | Editable pitch contour and duration factors with PSOLA resynthesis |
| **Sound operations** | Record, generate tones and noise, Klatt vowel synthesis, extract, resample, filter, scale, reverse, mono, concatenate |
| **Automation** | Folder-wide batch measurement to CSV (whole files or per labelled interval), and a script window for Praat scripts or Python |
| **Output** | Publication figures (PDF/SVG/PNG), CSV tables, audio export in five formats |
| **Comfort** | Light and dark themes, recent files, settings that persist, prompts before unsaved work is lost, a crash log |

---

## Installation

### From source (all platforms)

Requirements: **Python 3.13** and [**uv**](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/noahpangilinan/PhonoLab.git
cd PhonoLab
make setup          # creates .venv and installs the locked dependencies
make run            # or: uv run phonolab
```

You can open files straight from the command line:

```sh
uv run phonolab recording.wav other.flac
```

Without `make`, use `uv sync` and then `uv run phonolab`.

### Standalone app

```sh
make package        # builds dist/PhonoLab/ with PyInstaller
```

The result is a self-contained folder (about 330 MB) containing `PhonoLab.exe` (or the platform
equivalent) that runs without Python. Build on the platform you want to ship to.

### Dependencies

Everything installs from PyPI; nothing else is needed. Notable packages:
- `praat-parselmouth`: the Praat engine (bundles Praat 6.1.38).
- `PyQt6` and `pyqtgraph`: the interface.
- `soundfile`: audio input/output through libsndfile.
- `av`: FFmpeg, for M4A/AAC and similar formats.
- `sounddevice`: playback and recording through PortAudio.
- `matplotlib`: figures.
- `platformdirs`: the log location.

---

## Quick start

1. **Open a sound.** Use *File ▸ Open Sound…* (Ctrl+O), drop a file on the window, or pick one from the
   recent list on the start page. If a `.TextGrid` with the same name sits next to it, it opens too.
2. **Look and listen.** Drag in the waveform or spectrogram to select, then press **Space** to play.
   Ctrl+wheel zooms around the mouse, and the plain wheel scrolls.
3. **Measure.** Hover to read F0, formants and intensity in the *Measurements* panel. Press **F5**, **F1**
   or **F8** to log pitch, formants or intensity at the cursor, or over the selection, to the *Results* panel.
4. **Annotate.** Use *File ▸ New TextGrid…* (Ctrl+Shift+N) and enter tier names (e.g. `words phones`).
   Put the cursor where a word ends, press **Enter** to add a boundary, click the interval and type its
   label. Save with Ctrl+S.
5. **Go further.** Press **F6** for the spectrum, **Ctrl+Shift+V** for a voice report, **Ctrl+M** to
   manipulate pitch, **Ctrl+P** for a figure, and **Ctrl+B** to measure a whole folder.

---

## The editor

Each open sound gets a tab. From top to bottom:

| Part | Purpose |
| --- | --- |
| **Overview strip** | The whole recording, with a box marking the visible window. Click or drag to jump. |
| **Waveform** | Every channel, stacked. It's drawn as a min/max envelope per screen pixel, so nothing aliases at any zoom level. Glottal pulses appear here as vertical marks when enabled. |
| **Spectrogram** | Recomputed for the visible window, so zooming in sharpens it. Overlays: **pitch** (blue line, right axis in Hz), **formants** (red dots, hidden in silence), **intensity** (yellow line). |
| **Manipulation** | The editable pitch contour (*Manipulation ▸ Show manipulation*, Ctrl+M). Hidden by default. |
| **Label field** | Edits the label of the selected interval or point. Its **IPA** button opens a clickable IPA chart. |
| **Tiers** | One row per TextGrid tier, aligned with the panes above. |
| **Scrollbar** | Scrolls through time. |

Docked panels (rearrange or close them; *View* shows them again):
- **Measurements:** live values under the mouse (or at the cursor) and statistics for the selection.
- **Spectrum:** a spectral slice or LTAS of the selection, or around the cursor.
- **Results:** a running log of every query, ready to copy.

**Mouse gestures** (the same in every pane)

| Gesture | Effect |
| --- | --- |
| Click | Set the cursor and clear the selection |
| Drag | Select a time range |
| Shift+click | Extend the selection to the click |
| Wheel | Scroll |
| Ctrl+wheel | Zoom around the mouse |

**Layers** are toggled under *View* (waveform, spectrogram, pitch, formants, intensity, pulses,
manipulation) and remembered between sessions. Hidden analyses aren't computed, so turning off what you
don't need makes long files open faster.

**Playback**: Space or Tab plays the selection. With no selection it plays from the cursor to the end of
the visible window, as Praat does. Esc or Space again stops. The playhead follows playback and pages the
view when needed.

---

## Annotation (TextGrids)

### Creating and opening

| Action | How |
| --- | --- |
| New TextGrid | *File ▸ New TextGrid…*: space-separated names of interval tiers and point tiers |
| Open existing | *File ▸ Open TextGrid…*, drag the file onto the window, or keep it next to the sound with the same name |
| Save | Ctrl+S, or *Save TextGrid As…* (Ctrl+Shift+S) to choose the long or short text format |

PhonoLab warns when a TextGrid's duration differs from its sound.

### Editing

| Task | How |
| --- | --- |
| Add a boundary (interval tier) or point (point tier) | **Enter** at the cursor, or **double-click** in the tier |
| Move a boundary or point | Drag it. The pointer changes when you're close enough to grab it. |
| Remove the boundary near the cursor | **Delete** or **Alt+Backspace** (the two intervals' labels are joined, as in Praat) |
| Select an interval | Click inside it. The selection becomes the interval, so Space plays it. |
| Label | Just start typing, or use the label field. Enter returns focus to the tiers. |
| Previous / next interval | Alt+Left / Alt+Right |
| Change tier | Up / Down |
| Tier management | Right-click a tier, or use the *Annotate* menu: add interval/point tier, rename, duplicate, move up/down, remove |
| Undo / redo | Ctrl+Z / Ctrl+Shift+Z (Ctrl+Y). A burst of typing undoes as one step. |

### IPA

- Praat's **backslash codes** display as symbols: `\ae` shows as æ, `\sw` as ə, `\ng` as ŋ, `\:f` as ː, and so on.
  The text you typed is stored unchanged, so files stay compatible with Praat. All 391 of Praat's symbol
  codes are supported. The table was generated from Praat itself, and a test checks it against Praat.
- The **IPA** button next to the label field opens a chart of vowels, consonants, suprasegmentals and
  diacritics. Hover a symbol to see its Unicode code point and Praat code; click to insert it.

### Search

Ctrl+F opens the find bar above the tiers:
- It searches every tier, in time order.
- **Enter** / **F3** jumps to the next match; **Shift+Enter** / **Shift+F3** to the previous one.
- Options: **Regex** and **Match case**.
- Searching for a symbol also finds its backslash code (and the other way round): `æ` finds `\ae`.

---

## Measurements and queries

### Live readout

The *Measurements* panel shows values **under the mouse**: time, amplitude, the frequency under the
pointer in the spectrogram, F0, F1–F4 and intensity. When the mouse isn't over a pane it shows values **at
the cursor**. Below that it gives the selection's start, end and duration, with mean pitch, F1, F2 and
intensity.

### Queries (logged to *Results*)

Each query works on the **selection** if there is one, otherwise **at the cursor**.

| Query | Key | At the cursor | Over a selection |
| --- | --- | --- | --- |
| Pitch | F5 | F0 in Hz and semitones re 100 Hz | Mean (Hz and st), median, sd, minimum and maximum with their times, mean absolute slope (Hz/s), number of voiced frames |
| Formants | F1 | F1–F4 with bandwidths B1–B4 | Mean F1–F4 |
| Intensity | F8 | dB | Energy-averaged mean, min, max (Praat's "Get mean (energy)") |
| Duration | F2 | Total duration | Selection duration |
| Spectrum | F6 | Opens the spectrum panel for a window around the cursor | Spectrum of the selection |
| Spectral moments | — | Centre of gravity, sd, skewness, kurtosis | Same |
| CPPS | — | Over the visible window | Over the selection |
| Voice report | Ctrl+Shift+V | Over the visible window | Over the selection |

Undefined values (unvoiced frames, silence) print as `--undefined--`, as Praat does.

### Voice report

The report is Praat's own *Voice report* text, unaltered. It covers pitch statistics, pulses and periods,
the voicing fraction and voice breaks, five jitter measures, six shimmer measures, and harmonicity
(autocorrelation, NHR, HNR). It uses the current pitch settings plus the *Voice* settings (maximum period
and amplitude factors).

### Spectrum panel

- **Spectral slice**: the Hanning-windowed spectrum of the selection, or of a window around the cursor
  (40 ms by default), as dB/Hz. It's limited to 30 s; use LTAS for longer stretches.
- **LTAS**: the long-term average spectrum over any range, in bands (100 Hz by default).
- Each spectrum lists its **spectral moments** (centre of gravity, standard deviation, skewness,
  kurtosis), with the power set in the spectrum settings. Moments are skipped for LTAS ranges over 30 s.
- **Measure CPPS** logs the smoothed cepstral peak prominence using Praat's standard parameters (see below).

---

## Manipulation (PSOLA)

Manipulation changes the pitch and timing of a recording while keeping its voice quality. This is Praat's
*Manipulation* object, with the pitch tier edited directly in the editor.

1. **Ctrl+M** shows the manipulation pane. PhonoLab analyses the pitch in the background. Green points
   are the editable pitch tier; the dashed grey line is the original contour.
2. Edit it:

   | Edit | How |
   | --- | --- |
   | Move a point | Drag it (zoom in until the dots appear; up to 2,000 visible points are editable) |
   | Add a point | **Ctrl+click**, or *Add pitch point at cursor* |
   | Remove points | Select a stretch, then *Remove pitch points in selection* |
   | Stylize | *Stylize pitch (2 semitones)* or *Stylize pitch…*: Praat's stylization, which keeps only the turning points |
   | Shift | *Shift pitch…* by semitones (the selection, or everything) |
   | Flatten | *Flatten pitch* sets the selection (or everything) to its mean, i.e. a monotone |
   | Lengthen or shorten | Select a stretch, then *Set duration of selection…* (for example 1.5 for 50 % longer). The pane labels it "duration ×1.5". |
   | Start over | *Reset manipulation* |

   Every edit can be undone with Ctrl+Z, in the same history as annotation edits. Manipulation edits never
   mark the TextGrid as unsaved.
3. **Shift+Space** plays the resynthesis of the selection (or window). *Open resynthesis in new tab* gives
   you a sound you can save, measure or annotate.

Resynthesis uses Praat's overlap-add (PSOLA) method and runs in the background. Until you change the
tiers again, repeated playback reuses the last result.

---

## Sound operations, recording and synthesis

Everything under the **Sound** menu creates a **new tab**; the original is never changed. New sounds are
marked unsaved (`*`) until you use *Save sound as…* (Ctrl+Alt+S: WAV, FLAC, AIFF, OGG Vorbis or MP3).

| Command | Notes |
| --- | --- |
| Record… (Ctrl+R) | Choose the input device, sampling rate (16–96 kHz) and mono/stereo. A level meter and a clipping warning are shown. |
| New tone or noise… | Sine, square, pulse train, white or pink noise, with frequency, amplitude, duration and rate |
| Synthesize vowel (Klatt)… | Praat's KlattGrid: duration, a pitch glide (start→end), F1–F4 and bandwidths |
| Extract selection to new tab (Ctrl+E) | |
| Convert to mono | Averages the channels |
| Resample… | Praat's sinc resampling, with a precision setting |
| Filter (pass band)… / (stop band)… | Praat's Hann-band filters: from, to, smoothing |
| Pre-emphasis… | Praat's pre-emphasis from a frequency |
| Scale peak… | Normalise to a new absolute peak |
| Reverse | |
| Concatenate open sounds | Joins every open tab in order (rates must match; channel counts are reconciled) |

Multichannel sounds are processed one channel at a time, so stereo stays stereo.

---

## Batch measurement

*File ▸ Batch measure folder…* (Ctrl+B) measures every sound in a folder (optionally including
subfolders) into a single CSV. Files are processed in parallel, one per CPU core minus one, with
progress, a per-file log and a Cancel button.

- **Whole files**: leave *Per interval of tier* empty, and you get one row per file.
- **Per interval**: enter a tier name such as `words`. Each sound needs a same-named `.TextGrid` next to
  it, and you get one row per **labelled** interval. Labels are written with backslash codes converted to IPA.

Choose any of the six measurement groups. The current analysis settings from the *Analysis* menu are used.

### Columns

| Column | Meaning |
| --- | --- |
| `file`, `folder` | Source file |
| `tier`, `label`, `start_s`, `end_s` | Per-interval mode only |
| `duration_s` | Duration of the file or interval |
| `f0_mean_hz`, `f0_median_hz`, `f0_sd_hz`, `f0_min_hz`, `f0_max_hz` | Pitch over voiced frames |
| `F1_mean_hz` … `F4_mean_hz` | Mean formants |
| `intensity_mean_db` | Energy-averaged intensity |
| `jitter_local_pct`, `jitter_rap_pct`, `shimmer_local_pct`, `shimmer_apq3_pct`, `hnr_db`, `unvoiced_fraction_pct`, `voice_breaks` | From Praat's voice report |
| `cpps_db` | Smoothed cepstral peak prominence |
| `cog_hz`, `spectral_sd_hz`, `skewness`, `kurtosis` | Spectral moments of the Hanning-windowed range |
| `error` | Why a file or measure failed (unreadable file, missing tier, interval too short…). The rest of the batch carries on. |

Empty cells mean undefined (for example, no voiced frames).

---

## Scripting (Praat and Python)

*Tools ▸ Script window…* (Ctrl+K) opens a non-modal script editor that runs on the **current sound**.
Scripts run in a separate worker process, so the editor stays responsive. **Stop** ends a runaway script.
**Examples** loads ready-made scripts. **Open…** and **Save…** handle `.praat` and `.py` files. Ctrl+Enter runs.

### Praat scripts

The current Sound is selected, and so is its TextGrid if it has one, as if you had selected them in
Praat's object list. Both objects are named after the sound. `writeInfoLine` / `appendInfoLine` output
appears in the output pane. If the script has a `form`, type its arguments in the *Arguments* field, for
example `1000 "some text"` (numbers become numbers; quote text that contains spaces).

When the script finishes:
- **Sounds** in the final selection open as new tabs, except the original sound when it's unchanged.
- A **TextGrid** in the final selection replaces the current annotations, as one undoable step.

```praat
form Low-pass
    positive Cutoff_(Hz) 1000
endform
Filter (pass Hann band): 0, cutoff, 100
Rename: "lowpass"
```

### Python

These names are available:

| Name | What it is |
| --- | --- |
| `sound` | The current sound: `.samples` (n × channels), `.sampling_rate`, `.duration`, `.mono`, `.praat` (a `parselmouth.Sound`) |
| `textgrid` | A copy of its TextGrid, or `None` (`.tiers`, each with `.intervals` or `.points`) |
| `np`, `parselmouth`, `call` | NumPy, Parselmouth, and `parselmouth.praat.call` |
| `Sound`, `TextGrid` | The constructors |

`print()` goes to the output pane. To send results back:
- assign `new_sounds = [Sound(...), ...]` to open new tabs;
- assign `new_textgrid = TextGrid(...)` to replace the annotations (undoable).

All of `phonolab.core` is importable too, e.g. `from phonolab.core import analysis, queries`.

```python
from phonolab.core import analysis, queries
f = analysis.compute_formants(sound, analysis.FormantSettings())
for tier in textgrid.tiers:
    for iv in getattr(tier, "intervals", []):
        if iv.text:
            st = queries.formant_stats(f, iv.xmin, iv.xmax)
            print(tier.name, iv.text, round(st[0].mean), round(st[1].mean))
```

Scripts run with your own permissions. Only run scripts you trust.

---

## Publication figures

*File ▸ Export ▸ Publication figure…* (Ctrl+P) composes a Praat-style picture with a live preview.

- **Panels**: waveform, spectrogram, pitch contour, and TextGrid (choose which tiers to include).
- **Time range**: the selection, the visible window, or the whole sound.
- **Spectrogram overlays**: formant dots, plus a pitch or intensity contour.
- **Style**: width and per-panel height in inches, font size and family, greyscale (Praat's look) or
  colour, and pitch in Hz or semitones.
- **Output**: **PDF** and **SVG** stay vector (the spectrogram is embedded as an image); **PNG** uses the
  DPI setting. *Copy image* puts a PNG on the clipboard.

Labels with backslash codes are drawn as IPA. The figure uses the same analysis settings as the editor,
and your style choices are remembered.

---

## Analysis settings and defaults

Every setting lives under *Analysis* (or the panel's own *Settings…* button), persists between sessions,
and has **Restore Defaults**, which returns it to the values below (Praat's, unless noted).

**Spectrogram**

| Setting | Default |
| --- | --- |
| Maximum frequency | 5000 Hz |
| Window length | 0.005 s (Gaussian, a broadband spectrogram) |
| Dynamic range | 50 dB |
| Time × frequency steps | 1000 × 250 |
| Colour map | Grey (Praat), Viridis, Magma or Inferno |

**Pitch**

| Setting | Default |
| --- | --- |
| Floor / ceiling | 75 / 500 Hz |
| Method | Autocorrelation, cross-correlation, or SHS |
| Maximum candidates | 15 |
| Very accurate | Off |
| Silence / voicing thresholds | 0.03 / 0.45 |
| Octave / octave-jump / voiced-unvoiced costs | 0.01 / 0.35 / 0.14 |

**Formants**

| Setting | Default |
| --- | --- |
| Method | Burg, or robust (iterative LPC: 1.5 sd, 5 iterations) |
| Formant ceiling | 5500 Hz (use about 5000 Hz for adult male voices) |
| Number of formants | 5 |
| Window length | 0.025 s |
| Pre-emphasis from | 50 Hz |
| Dot dynamic range | 30 dB (hides dots in silence) |

**Intensity**

| Setting | Default |
| --- | --- |
| Minimum pitch | 100 Hz |
| Subtract mean pressure | On |
| Display range | 50–100 dB |

**Voice**

| Setting | Default |
| --- | --- |
| Maximum period factor | 1.3 |
| Maximum amplitude factor | 1.6 |

**Spectrum** (PhonoLab defaults)

| Setting | Default |
| --- | --- |
| Maximum frequency | 5000 Hz |
| Window at the cursor | 0.04 s |
| LTAS bandwidth | 100 Hz |
| Moment power | 2 |

**Manipulation**

| Setting | Default |
| --- | --- |
| Time step | 0.01 s |
| Pitch range | 75–600 Hz |

Changing these discards the current manipulation.

**CPPS** (fixed parameters)
- PowerCepstrogram: 60 Hz, 0.002 s, 5000 Hz, pre-emphasis 50 Hz.
- CPPS: time and quefrency averaging 0.02 s / 0.0005 s; peak search 60–330 Hz, tolerance 0.05, parabolic
  interpolation; tilt line from 0.001 s to the end; straight line, robust fit.

---

## Keyboard shortcuts

| Keys | Action |
| --- | --- |
| Space / Tab | Play the selection, or from the cursor to the end of the window; press again to stop |
| Shift+Space | Play the resynthesis (manipulation) |
| Esc | Stop |
| Ctrl+= / Ctrl+- | Zoom in / out |
| Ctrl+wheel | Zoom around the mouse |
| Wheel, Page Up / Page Down | Scroll |
| Ctrl+N / Ctrl+A | Zoom to selection / show all |
| Ctrl+Shift+A | Select the whole sound |
| Enter / double-click in a tier | Add a boundary or point |
| Delete / Alt+Backspace | Remove the boundary or point near the cursor |
| Alt+Left / Alt+Right | Previous / next interval |
| Up / Down | Previous / next tier |
| Ctrl+F, F3 / Shift+F3 | Find labels, next / previous match |
| F5 / F1 / F8 / F2 | Pitch / formants / intensity / duration |
| F6 | Spectrum panel |
| Ctrl+Shift+V | Voice report |
| Ctrl+M | Show manipulation (Ctrl+click adds a pitch point) |
| Ctrl+E | Extract the selection to a new tab |
| Ctrl+R | Record |
| Ctrl+O / Ctrl+Shift+O | Open sound / open TextGrid |
| Ctrl+Shift+N | New TextGrid |
| Ctrl+S / Ctrl+Shift+S | Save TextGrid / save as |
| Ctrl+Alt+S | Save sound as |
| Ctrl+P / Ctrl+B / Ctrl+K | Figure / batch measure / script window |
| Ctrl+Z / Ctrl+Shift+Z (Ctrl+Y) | Undo / redo |
| Ctrl+W / Ctrl+Q | Close tab / quit |
| Ctrl+/ | Show the shortcut list |

The shortcuts follow Praat where possible: Tab plays, F1/F5/F8 query, and Ctrl+A shows everything. Typing
in the label field always types; it never triggers shortcuts.

---

## Menu reference

| Menu | Contents |
| --- | --- |
| **File** | Open sound, open recent, open TextGrid, new TextGrid, save TextGrid (as), Export ▸ (selection as WAV, pitch/formant/intensity/annotation tables as CSV, publication figure, view as PNG), batch measure, close, quit |
| **Edit** | Undo, redo, select all, find label, find next / previous |
| **View** | Zoom and scroll, show/hide each layer, Theme ▸ (System / Light / Dark), show/hide the panels |
| **Play** | Play/stop, stop, play the whole sound |
| **Sound** | Save sound as, record, new tone or noise, synthesize vowel, extract, mono, resample, filters, pre-emphasis, scale peak, reverse, concatenate |
| **Analysis** | Settings for the spectrogram, pitch, formants, intensity, voice and spectrum |
| **Manipulation** | Show, play resynthesis, open resynthesis, add/remove points, stylize, shift, flatten, set duration, reset, settings |
| **Query** | Pitch, formants, intensity, duration, spectral slice/LTAS, spectral moments, CPPS, voice report |
| **Annotate** | Add/remove a boundary at the cursor, previous/next interval, add interval/point tier, rename, duplicate, remove a tier |
| **Tools** | Script window, batch measure, figure |
| **Help** | Keyboard shortcuts, About |

---

## How results relate to Praat

- **The same algorithms.** Every analysis is a Praat command run by Parselmouth (pitch, formants,
  intensity, spectrogram, voice report, LTAS, spectral moments, CPPS, PSOLA, Klatt, filters, resampling).
  PhonoLab adds no measurement code of its own beyond simple statistics over Praat's frames: means,
  medians, extremes, slopes, and the energy-averaged intensity mean.
- **Whole-file analysis.** PhonoLab analyses pitch, formants and intensity over the **whole sound**, as
  Praat's commands on a Sound object do. Praat's *editor* analyses only the visible window, so its values
  can differ in the last digits near the window edges (pitch path-finding looks at the neighbouring frames).
  To reproduce a number exactly, run the same Praat command on the whole Sound; the script window makes
  that easy.
- **Voice reports** are computed on the selection plus a margin of 3 ÷ pitch floor on each side, so the
  pitch analysis has context at the edges.
- **Spectral slices** use a Hanning window over the selection.
- **Bundled Praat version: 6.1.38.** Commands added to Praat after that version aren't available.

---

## Files, formats and preferences

**Audio input**
- WAV, FLAC, AIFF, OGG/Opus and MP3 through libsndfile.
- M4A/AAC, MP4, WMA, WebM and anything else FFmpeg decodes, through PyAV. AAC encoder delay is trimmed,
  so annotation times line up.
- Praat's own reader as the last fallback.
- Multichannel files keep their channels. Analyses use the channel average.

**Audio output**: WAV, FLAC, AIFF, OGG Vorbis and MP3, with the format following the extension.

**TextGrids**
- Reading: Praat's long and short text formats, in UTF-8, UTF-16 (with byte-order mark) or Latin-1.
- Writing: the long (default) or short format, in UTF-8. Praat reads both.

**Tables**: CSV in UTF-8. Empty cells mean undefined.

**Preferences** are stored with Qt's `QSettings`: the registry on Windows, `~/Library/Preferences` on
macOS, `~/.config` on Linux. They cover analysis settings, visible layers, theme, recent files, window
layout and the last-used folder.

**Logs** go to the platform's user log folder, for example `%LOCALAPPDATA%\PhonoLab\Logs\phonolab.log`
on Windows. Unexpected errors show a dialog with details and are also written to the log.

---

## Architecture

```
src/phonolab/
  core/              pure Python, no Qt: everything here is unit-tested and usable from scripts
    sound.py         Sound: samples (n × channels), loading (libsndfile → FFmpeg → Praat), saving
    analysis.py      Settings dataclasses (with UI metadata) and compute_* for spectrogram/pitch/formants/intensity
    voice.py         Glottal pulses and Praat's voice report
    spectrum.py      Spectral slice, LTAS, spectral moments, CPPS
    queries.py       Values at a time, range statistics, slopes, bandwidths
    registry.py      Analyses the editor can show, and their dependencies (pulses depend on pitch)
    textgrid.py      TextGrid model, Praat long/short I/O, search
    ipa.py           Praat backslash codes ↔ Unicode (generated from Praat)
    manipulation.py  Pitch/duration tiers, PSOLA resynthesis, stylize/shift/flatten
    sound_ops.py     Non-destructive operations, tone/noise generation, Klatt vowels
    batch.py         Folder measurement to rows and CSV
    scripting.py     Running Praat scripts and Python, returning plain data
    figures.py       Matplotlib figures
    settings.py      Preferences over any QSettings-like store
  audio/player.py    Range playback (sounddevice), wall-clock playhead, one "finished" per play
  ui/
    main_window.py   Tabs, menus, docks, file handling, dialogs
    document.py      Sound, TextGrid and manipulation, with one QUndoStack per document
    workers.py       Process pools; each sound's samples are shared with the workers through shared memory
    editor/          TimeAxisController plus panes (waveform, spectrogram, manipulation, TextGrid, find bar)
    dialogs/         Settings forms (generated from the dataclasses), recording, batch, figure, new TextGrid
    …                Measurements, spectrum and results panels, IPA chart, script window, theme
```

Key design decisions:
- **Processes, not threads.** Parselmouth holds Python's interpreter lock (the GIL) while Praat computes,
  so analysis threads would freeze the interface. Each document puts its mono samples in shared memory
  once; long-lived worker processes attach to it. Spectrograms have their own worker so scrolling never
  waits behind a slow formant analysis. Stale results are dropped by token.
- **A single time axis.** One `TimeAxisController` (view, cursor, selection, hover) drives every pane, so
  they can't drift apart.
- **One undo history per document.** TextGrid edits are snapshots or merged label edits; manipulation
  edits are tier snapshots. Unsaved annotations are detected by comparing with the last saved copy, so
  undoing back to the saved state clears the `*`.
- **Settings are dataclasses.** Their field metadata (label, unit, range, choices) generates the settings
  dialogs and their persistence.

---

## Development

```sh
make setup          # install, including dev tools (pytest, pytest-qt, ruff, scipy, pyinstaller)
make test           # the test suite, with Qt offscreen
make lint           # ruff check
make format         # ruff format
make package        # PyInstaller build in dist/PhonoLab
```

About the tests:
- They synthesise their own signals: vowels from pulse trains through resonators, sines, harmonic
  complexes, AAC files.
- They compare against Praat wherever possible: TextGrids round-trip through Praat in both directions,
  and the IPA table is checked against Praat's own conversion.
- UI tests drive the real main window offscreen (pytest-qt): opening, querying, annotating with the
  keyboard, undo, manipulation and resynthesis, batch runs, the script window, figures, search and themes.

Code style is ruff with a 120-character line length. Commit messages are short subject lines.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| No sound when playing | Check the default output device. The status bar says "No audio output device available" if PortAudio found none. |
| Pitch octave jumps | Narrow the pitch floor and ceiling to the speaker's range (e.g. 60–300 Hz for low voices, 100–500 Hz for high voices). Try cross-correlation, or raise the octave-jump cost. |
| Formants look wrong | Set the formant ceiling to about 5000 Hz for adult males and 5500 Hz for adult females, higher for children. Try the robust method. |
| A file won't open | The error dialog gives FFmpeg's reason. Re-encode exotic formats to WAV or FLAC. |
| A TextGrid doesn't line up | PhonoLab warns when its duration differs from the sound's. Check that you opened the right pair. |
| The interface feels slow on very long files | Hide unneeded layers (formants are the slowest analysis) and zoom in. Analyses still run in the background. |
| Something crashed | See the log file (path above) and include it in a bug report. |

---

## Not yet covered

- Pitch methods newer than the bundled Praat 6.1.38 (e.g. filtered autocorrelation).
- Articulatory synthesis.
- Praat's statistics and learning tools (Table, PCA, discriminant analysis, OT grammars) and listening
  experiments (ExperimentMFC).
- Binary TextGrid files and Praat's other object types (e.g. editing a standalone PitchTier).

---

## License

PhonoLab is free software under the **GNU General Public License v3.0 or later**. Praat and Parselmouth
are GPL-licensed, so PhonoLab is too. See [LICENSE](LICENSE).

Praat is by Paul Boersma and David Weenink; Parselmouth is by Yannick Jadoul, Bill Thompson and Bart de
Boer. If you publish results obtained with PhonoLab, please cite Praat and Parselmouth.
