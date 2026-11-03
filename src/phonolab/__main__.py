import multiprocessing

from phonolab import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # analysis workers in frozen builds
    main()
