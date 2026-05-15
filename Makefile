.PHONY: help install dev test test-unit test-integration lint fmt typecheck ui-install ui-dev ui-build clean

help:
	@echo "hal0 — common dev tasks"
	@echo ""
	@echo "  make install         Install python package in editable mode with dev extras"
	@echo "  make dev             Run hal0-api with --reload"
	@echo "  make test            Run unit tests"
	@echo "  make lint            Ruff check"
	@echo "  make fmt             Ruff format"
	@echo "  make typecheck       Mypy"
	@echo "  make ui-install      Install UI deps"
	@echo "  make ui-dev          Vite dev server"
	@echo "  make ui-build        Production UI build"
	@echo "  make clean           Remove caches"

install:
	pip install -e ".[dev]"

dev:
	uvicorn hal0.api:app --reload --host 127.0.0.1 --port 8080

test: test-unit

test-unit:
	pytest tests/ -v

lint:
	ruff check src tests

fmt:
	ruff format src tests
	ruff check --fix src tests

typecheck:
	mypy src

ui-install:
	cd ui && npm install

ui-dev:
	cd ui && npm run dev

ui-build:
	cd ui && npm run build

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf build dist *.egg-info
