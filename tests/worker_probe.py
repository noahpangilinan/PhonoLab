"""A job for worker processes that shows whether they are still alive."""

import time
from pathlib import Path


def heartbeat(path: str) -> None:
    beats = 0
    while True:
        beats += 1
        Path(path).write_text(str(beats))
        time.sleep(0.05)
