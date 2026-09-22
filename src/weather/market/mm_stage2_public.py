"""Pure shared RE-1 public evidence helpers; no order or account imports."""
from datetime import datetime, timezone
import hashlib
import json

from weather.market.reward_quote import price_reward_quote
from weather.schema_registry import schema_version

SCHEMA_VERSION = schema_version("mm_stage2_hold")


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False, default=str) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def utc(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("session times must be timezone-aware")
    return result.astimezone(timezone.utc)


class HoldEnd(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def public_quote(snapshot, *, now, condition_id, token_ids):
    if (snapshot.get("condition_id") != condition_id
            or tuple(snapshot.get("token_ids", ())) != tuple(token_ids)
            or not 0 <= (utc(now) - utc(snapshot.get("observed_at_utc"))).total_seconds() <= 60):
        raise HoldEnd("public_scope_or_freshness")
    return price_reward_quote(**snapshot["quote_inputs"])


