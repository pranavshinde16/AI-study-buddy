"""Run with the backend's venv from the repo root:  backend/.venv/Scripts/python -m pytest finetune/tests -q
(macOS/Linux: backend/.venv/bin/python -m pytest finetune/tests -q). No network, no GPU."""

import sys
from pathlib import Path

FT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FT))
sys.path.insert(1, str(FT.parent / "backend"))
