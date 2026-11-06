import numpy as np
import pytest

from phonolab.core import praat_engine
from phonolab.core.manipulation import Tier
from phonolab.core.tiers import SUFFIXES, TierFile, TierFileError, read_tier


def make(kind="PitchTier"):
    return TierFile(kind, 0.0, 2.0, Tier(np.array([0.5, 1.5]), np.array([100.0, 200.0])))


@pytest.mark.parametrize("kind", ["PitchTier", "DurationTier", "IntensityTier", "AmplitudeTier", "RealTier"])
def test_roundtrip(tmp_path, kind):
    path = tmp_path / f"t.{kind}"
    make(kind).save(path)
    back = read_tier(path)
    assert back.object_class == kind and back.xmax == 2.0 and back.tier == make(kind).tier


def test_suffixes_are_lower_case():
    assert ".pitchtier" in SUFFIXES


def test_bad_files_raise(tmp_path):
    path = tmp_path / "x.PitchTier"
    path.write_text("nonsense")
    with pytest.raises(TierFileError):
        read_tier(path)
    path.write_text('File type = "ooTextFile"\nObject class = "PitchTier"\n\n0\n1\n5\n0.1\n100\n')
    with pytest.raises(TierFileError, match="incomplete"):
        read_tier(path)


@pytest.mark.skipif(not praat_engine.available(), reason="run packaging/fetch_praat.py first")
@pytest.mark.parametrize("command", ["Save as text file", "Save as short text file"])
def test_reads_what_praat_writes_and_praat_reads_ours(tmp_path, command):
    theirs, ours = tmp_path / "praat.PitchTier", tmp_path / "ours.PitchTier"
    praat_engine.run_script(
        f'Create PitchTier: "t", 0, 2\nAdd point: 0.5, 100\nAdd point: 1.5, 200\n{command}: "{theirs.as_posix()}"\n'
    )
    tier = read_tier(theirs)
    assert tier.tier == make().tier and tier.xmax == 2
    tier.save(ours)
    out = praat_engine.run_script(f'Read from file: "{ours.as_posix()}"\nn = Get number of points\nwriteInfoLine: n\n')
    assert out.strip() == "2"
