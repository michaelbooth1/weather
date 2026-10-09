"""Read-only watcher freshness and high normalization shared by quote consumers."""
from __future__ import annotations
import json
from pathlib import Path
from weather.paths import data_path
from weather.market.live_observation_normalization import normalized_high_for_market
from weather.time import evidence_age_seconds, utc_now
DEFAULT_OBSERVATION_STATUS = data_path() / "snapshots" / "observation_trigger_status.json"
from weather.market.quote_policy_defaults import DEFAULT_POLICY_CONFIG

def load_observation_status(path=DEFAULT_OBSERVATION_STATUS, now=None, config=None):
    config = {**DEFAULT_POLICY_CONFIG, **(config or {})}
    now = utc_now(now)
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "fresh": False,
            "heartbeat_ok": False,
            "watcher_age_seconds": None,
            "reason": "missing observation watcher status",
        }
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    watcher_age = evidence_age_seconds(now, timestamp=payload.get("last_heartbeat"))
    consecutive_errors = int(payload.get("consecutive_errors") or 0)
    fresh = (
        watcher_age is not None
        and watcher_age <= float(config["max_watcher_age_seconds"])
        and consecutive_errors == 0
    )
    markets = payload.get("markets") or {}
    market_normalization = {
        market_id: normalized_high_for_market({"markets": markets}, market_id)
        for market_id in markets
    }
    return {
        "path": str(path),
        "exists": True,
        "fresh": fresh,
        "heartbeat_ok": fresh,
        "watcher_age_seconds": watcher_age,
        "last_heartbeat": payload.get("last_heartbeat"),
        "consecutive_errors": consecutive_errors,
        "markets": markets,
        "market_normalization": market_normalization,
        "reason": "fresh" if fresh else "stale or erroring observation watcher",
    }
