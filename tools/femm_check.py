"""Quick check that FEMM can run the validation Lua script and produce the
results file (formerly ``_tmp_femm_check.py``).

Paths now resolve relative to this project instead of a hard-coded
machine-specific location.
"""

from pathlib import Path

import femm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LUA_SCRIPT = PROJECT_ROOT / 'femm_validation' / 'run_validation.lua'
RESULTS_FILE = PROJECT_ROOT / 'femm_validation' / 'validation_results.txt'


def main():
    try:
        femm.openfemm()
        lua_for_femm = str(LUA_SCRIPT).replace('\\', '/')
        femm.callfemm(f'dofile("{lua_for_femm}")')
    finally:
        try:
            femm.closefemm()
        except Exception:
            pass

    print("RESULT_FILE", RESULTS_FILE.exists())


if __name__ == '__main__':
    main()
