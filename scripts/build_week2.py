"""Reproducible week-two comparisons, export and held-out calibration audit."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')

from src.week2_training import run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke', action='store_true', help='Small real-data pipeline check; never overwrites deployable full artifacts')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--epochs', type=int, default=10)
    parser.add_argument('--rounds', type=int, default=140)
    args = parser.parse_args()
    if min(args.threads, args.epochs, args.rounds) < 1:
        parser.error('Training budgets must be positive')
    suffix = '-smoke' if args.smoke else ''
    run(ROOT, ROOT / f'artifacts/week2{suffix}', ROOT / ('docs/week2/smoke' if args.smoke else 'docs/week2'),
        smoke=args.smoke, threads=args.threads, epochs=args.epochs, rounds=args.rounds)


if __name__ == '__main__':
    main()
