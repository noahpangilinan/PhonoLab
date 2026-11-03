"""Measure many sound files (optionally per labelled TextGrid interval) into one table."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from phonolab.core import analysis, queries, spectrum, voice
from phonolab.core.analysis import FormantSettings, IntensitySettings, PitchSettings
from phonolab.core.ipa import to_unicode
from phonolab.core.sound import SUPPORTED_EXTENSIONS, Sound
from phonolab.core.textgrid import IntervalTier, TextGrid

MEASURES = {
    "pitch": "Pitch (mean, median, sd, min, max)",
    "formants": "Formants (mean F1–F4)",
    "intensity": "Intensity (mean, energy-averaged)",
    "voice": "Voice report (jitter, shimmer, HNR)",
    "cpps": "CPPS",
    "moments": "Spectral moments",
}

# Voice report rows copied into the table, as (report label, column name).
VOICE_COLUMNS = [
    ("Jitter (local)", "jitter_local_pct"),
    ("Jitter (rap)", "jitter_rap_pct"),
    ("Shimmer (local)", "shimmer_local_pct"),
    ("Shimmer (apq3)", "shimmer_apq3_pct"),
    ("Mean harmonics-to-noise ratio", "hnr_db"),
    ("Fraction of locally unvoiced frames", "unvoiced_fraction_pct"),
    ("Number of voice breaks", "voice_breaks"),
]


@dataclass(frozen=True)
class BatchOptions:
    measures: frozenset[str] = frozenset(MEASURES)
    tier: str = ""  # measure each labelled interval of this tier; empty = whole files
    pitch: PitchSettings = field(default_factory=PitchSettings)
    formants: FormantSettings = field(default_factory=FormantSettings)
    intensity: IntensitySettings = field(default_factory=IntensitySettings)
    voice: voice.VoiceSettings = field(default_factory=voice.VoiceSettings)


def find_sounds(folder: Path, recursive: bool = True) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in folder.glob(pattern) if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS)


def _number(text: str | None) -> float:
    """First number in a voice-report value like '0.512%' or '12.3 dB'."""
    if not text:
        return float("nan")
    try:
        return float(text.split()[0].rstrip("%").split("(")[0])
    except ValueError:
        return float("nan")


def _ranges(sound: Sound, path: Path, tier_name: str) -> list[tuple[float, float, str]]:
    if not tier_name:
        return [(0.0, sound.duration, "")]
    tg_path = next((path.with_suffix(e) for e in (".TextGrid", ".textgrid") if path.with_suffix(e).exists()), None)
    if tg_path is None:
        raise FileNotFoundError(f"no TextGrid next to {path.name}")
    tier = next((t for t in TextGrid.read(tg_path).tiers if t.name == tier_name), None)
    if not isinstance(tier, IntervalTier):
        raise ValueError(f"{tg_path.name} has no interval tier named {tier_name!r}")
    return [(iv.xmin, iv.xmax, iv.text) for iv in tier.intervals if iv.text.strip()]


def measure_file(path: str | Path, options: BatchOptions) -> list[dict]:
    """One row per file (or per labelled interval). Errors become a row with an 'error' column."""
    path = Path(path)
    base = {"file": path.name, "folder": str(path.parent)}
    try:
        sound = Sound.from_file(path)
        ranges = _ranges(sound, path, options.tier)
        m = options.measures
        pitch = analysis.compute_pitch(sound, options.pitch) if "pitch" in m else None
        formants = analysis.compute_formants(sound, options.formants) if "formants" in m else None
        intensity = analysis.compute_intensity(sound, options.intensity) if "intensity" in m else None
    except Exception as e:  # unreadable file, missing tier: report it and carry on with the batch
        return [{**base, "error": str(e)}]

    rows = []
    for start, end, label in ranges:
        row = dict(base)
        if options.tier:
            row.update(tier=options.tier, label=to_unicode(label), start_s=round(start, 6), end_s=round(end, 6))
        row["duration_s"] = round(end - start, 6)
        errors = []
        if pitch is not None:
            st = queries.pitch_stats(pitch, start, end)
            row.update(f0_mean_hz=st.mean, f0_median_hz=st.median, f0_sd_hz=st.stdev,
                       f0_min_hz=st.minimum, f0_max_hz=st.maximum)  # fmt: skip
        if formants is not None:
            for i, st in enumerate(queries.formant_stats(formants, start, end)[:4]):
                row[f"F{i + 1}_mean_hz"] = st.mean
        if intensity is not None:
            row["intensity_mean_db"] = queries.intensity_stats(intensity, start, end).mean
        if "voice" in options.measures:
            try:
                report = voice.voice_report(sound, options.pitch, options.voice, start, end)
                for label_, column in VOICE_COLUMNS:
                    row[column] = _number(report.value(label_))
            except Exception as e:  # too short or unvoiced
                errors.append(f"voice: {e}")
        if "cpps" in options.measures:
            try:
                row["cpps_db"] = spectrum.cpps(sound, start, end)
            except Exception as e:
                errors.append(f"cpps: {e}")
        if "moments" in options.measures:
            try:
                r = spectrum.compute_slice(sound, spectrum.SpectrumSettings(max_frequency=sound.sampling_rate / 2),
                                           start, end)  # fmt: skip
                row.update(cog_hz=r.centre_of_gravity, spectral_sd_hz=r.standard_deviation,
                           skewness=r.skewness, kurtosis=r.kurtosis)  # fmt: skip
            except Exception as e:
                errors.append(f"moments: {e}")
        if errors:
            row["error"] = "; ".join(errors)
        rows.append(row)
    return rows


def write_csv(rows: Iterable[dict], path: str | Path) -> int:
    """Write rows with the union of their columns (in first-seen order). Returns the row count."""
    rows = list(rows)
    columns: list[str] = []
    for row in rows:
        columns += [k for k in row if k not in columns]
    if "error" in columns:  # keep the error column last
        columns.remove("error")
        columns.append("error")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        for row in rows:
            w.writerow({k: _cell(v) for k, v in row.items()})
    return len(rows)


def _cell(v):
    if isinstance(v, float | np.floating):
        return "" if np.isnan(v) else f"{v:.6g}"
    return v
