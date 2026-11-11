"""Evaluate, never train or calibrate, the fixed week-two model on 2025."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.final_evaluation import run

if __name__ == '__main__':
    run(ROOT, ROOT / 'docs/week3')
