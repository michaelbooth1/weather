import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from weather.reporting.model_market_disagreement_audit import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
