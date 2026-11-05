.PHONY: help setup sync run test lint format praat package clean

help:
	@echo "Available commands:"
	@echo "  make setup   - Create venv and install dependencies"
	@echo "  make sync    - Sync dependencies from lockfile"
	@echo "  make run     - Run the application"
	@echo "  make test    - Run tests"
	@echo "  make lint    - Run linter (ruff)"
	@echo "  make format  - Format code (ruff)"
	@echo "  make praat   - Download the pinned Praat program (needed once)"
	@echo "  make package - Build a single standalone dist/PhonoLab.exe"
	@echo "  make clean   - Remove virtual environment"

# First-time setup
setup:
	uv venv
	uv sync
	uv run python packaging/fetch_praat.py

sync:
	uv sync

run:
	uv run phonolab

test:
	QT_QPA_PLATFORM=offscreen uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

praat:
	uv run python packaging/fetch_praat.py

package:
	cd packaging && uv run pyinstaller --noconfirm --distpath ../dist --workpath ../build phonolab.spec

clean:
	rm -rf .venv
