"""Run from any working directory: python /path/to/badminton_reservation/run.py list."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from badminton_reservation.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
