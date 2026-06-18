import json
from pathlib import Path


DEFAULT_PLAN_PATH = Path("data/backtest/historical_backfill_plan.json")


def main(path=DEFAULT_PLAN_PATH) -> int:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    for item in payload.get("queue", []):
        detail = item.get("detail", {})
        print(
            f"{item.get('market_id')} ({item.get('source')}): "
            f"missing {detail.get('missing_days')} days, {detail.get('missing_ranges')} ranges"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
