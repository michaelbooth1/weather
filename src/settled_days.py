"""Auto-discover settled, collection-present market-day folders.

This replaces the hand-maintained ``DEFAULT_SETTLED_SLUGS`` tuple that was
copy-pasted across five training modules (probability_calibration,
forecast_error_model, settlement_lag_model, model_ensemble, market_day_labels).
That duplication silently went stale once -- the list named three days while six
had settled, so the whole stack trained on half the data before anyone noticed.

A day is included when:
  * its slug parses to a target date (it is a Toronto temp-market folder), and
  * that date is strictly before ``as_of`` (the market has SETTLED -- the day is
    fully in the past; today's market is still resolving), and
  * the required tape file is present (collection produced something).

This self-maintains: a new day is picked up automatically the day after it
settles, with no code edit. ``as_of`` is injectable so the cutoff is testable and
so a backtest can reconstruct the training set as of any historical date.
"""
import sys
from datetime import date, datetime
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from market_config import date_from_event_slug
from model_constants import TORONTO_TZ

DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"


def _as_of_date(as_of):
    if as_of is None:
        return datetime.now(TORONTO_TZ).date()
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    # An ISO string is accepted for convenience.
    return datetime.fromisoformat(str(as_of)).date()


def discover_settled_folders(
    root=DEFAULT_SNAPSHOTS_ROOT,
    as_of=None,
    required_file="snapshots_long.csv",
):
    """Settled market-day folders under ``root`` with ``required_file`` present,
    in chronological order."""
    root = Path(root)
    if not root.exists():
        return []
    cutoff = _as_of_date(as_of)
    found = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        target_date = date_from_event_slug(child.name)
        if target_date is None:
            continue
        if target_date >= cutoff:          # today or future: not settled yet
            continue
        if not (child / required_file).exists():
            continue
        found.append((target_date, child))
    return [folder for _, folder in sorted(found, key=lambda item: item[0])]


def discover_settled_slugs(
    root=DEFAULT_SNAPSHOTS_ROOT,
    as_of=None,
    required_file="snapshots_long.csv",
):
    return [folder.name for folder in discover_settled_folders(root, as_of, required_file)]
