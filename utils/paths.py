"""Filesystem locations used across the application."""

import os
from pathlib import Path
import sys

# Repository root = parent of the `utils` package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Bundled templates are read-only. Keep validation evidence outside a one-file
# executable's temporary extraction directory so it survives app restarts.
APP_DATA_DIR = (Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
                / 'WindingFlux')
FEMM_VALIDATION_DIR = (APP_DATA_DIR / 'femm_validation' if getattr(sys, 'frozen', False)
                       else PROJECT_ROOT / 'femm_validation')
FEMM_VALIDATION_SCRIPT = PROJECT_ROOT / 'femm_validation' / 'run_validation.lua'
FEMM_VALIDATION_RESULTS = FEMM_VALIDATION_DIR / 'validation_results.txt'


def femm_worker_command():
    """Launch the same isolated worker in source and standalone builds."""
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--femm-worker']
    return [sys.executable, '-u', str(PROJECT_ROOT / 'tools' / 'femm_check.py')]
