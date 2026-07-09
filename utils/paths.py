"""Filesystem locations used across the application."""

from pathlib import Path

# Repository root = parent of the `utils` package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

FEMM_VALIDATION_DIR = PROJECT_ROOT / 'femm_validation'
FEMM_VALIDATION_SCRIPT = FEMM_VALIDATION_DIR / 'run_validation.lua'
FEMM_VALIDATION_RESULTS = FEMM_VALIDATION_DIR / 'validation_results.txt'
