"""Workers must not outlive the app, even when it crashes."""

import os
import subprocess
import sys
import time
from pathlib import Path

CRASHING_APP = """
import os, sys, time
from pathlib import Path
from phonolab.ui import workers
from tests.worker_probe import heartbeat

if __name__ == "__main__":
    workers.run_in_worker("analysis", heartbeat, sys.argv[1])
    while not Path(sys.argv[1]).exists():
        time.sleep(0.02)
    os._exit(1)  # a crash: nothing gets to clean up
"""


def test_workers_exit_when_the_app_crashes(tmp_path):
    beat = tmp_path / "beat.txt"
    script = tmp_path / "app.py"
    script.write_text(CRASHING_APP)
    root = Path(__file__).parent.parent
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(root), str(root / "src")]), QT_QPA_PLATFORM="offscreen")
    log = tmp_path / "log.txt"
    with log.open("w") as out:  # not a pipe: a surviving worker would hold it open, and the test would hang
        done = subprocess.run([sys.executable, str(script), str(beat)], env=env, timeout=60, stdout=out, stderr=out)
    assert done.returncode == 1, log.read_text()
    time.sleep(1.5)  # the worker's watcher has had time to notice
    first = beat.read_text()
    time.sleep(0.5)
    assert beat.read_text() == first, "the worker is still running"
