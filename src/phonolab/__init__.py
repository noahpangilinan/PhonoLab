"""PhonoLab: acoustic analysis and annotation for speech."""

__version__ = "0.4.0"


def main() -> None:
    from phonolab.app import run

    raise SystemExit(run())
