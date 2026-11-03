"""Entry point for frozen builds (PyInstaller)."""

import multiprocessing

from phonolab import main

if __name__ == "__main__":
    # Analysis and batch workers are spawned processes; in a frozen app they re-enter here.
    multiprocessing.freeze_support()
    main()
