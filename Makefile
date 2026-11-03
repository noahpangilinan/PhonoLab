.PHONY: help setup sync run test lint format clean

help:
	@echo "Available commands:"
	@echo "  make setup   - Create venv and install dependencies"
	@echo "  make sync    - Sync dependencies from lockfile"
	@echo "  make run     - Run the application"
	@echo "  make test    - Run tests"
	@echo "  make lint    - Run linter (ruff)"
	@echo "  make format  - Format code (ruff)"
	@echo "  make clean   - Remove virtual environment"

# First-time setup
setup:
	uv venv
	uv sync

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

clean:
	rm -rf .venv
