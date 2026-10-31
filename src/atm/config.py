import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data" / "raw"
LOG_DIR = ROOT / "logs"

MODEL = os.getenv("ATM_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("ATM_EFFORT", "low")
MAX_ROUNDS = int(os.getenv("ATM_MAX_ROUNDS", "3"))  # challenge: converge in < 3 turns
