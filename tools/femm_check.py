"""Isolated validation worker used by the app's asynchronous FEMM button."""

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.femm_runner import parse_validation_results, run_femm_script


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--keep-open', action='store_true',
                        help='Keep the solved FEMM field open for inspection.')
    args = parser.parse_args()
    try:
        backend = run_femm_script(args.script, args.results, args.timeout,
                                  keep_open=args.keep_open)
        print(json.dumps({'backend': backend,
                          'metrics': parse_validation_results(args.results)}))
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
