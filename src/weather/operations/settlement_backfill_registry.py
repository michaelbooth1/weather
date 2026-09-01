"""Emit the authoritative market inventory for one-date settlement backfills."""

from __future__ import annotations

import json

from weather.market import market_registry


def build_payload() -> dict[str, object]:
    """Return a small deterministic inventory from the canonical registry."""

    market_ids = sorted(spec.id for spec in market_registry.all_specs())
    if not market_ids or len(market_ids) != len(set(market_ids)):
        raise RuntimeError("authoritative market registry is empty or duplicated")
    return {
        "contract": "settlement_backfill_market_registry_discovery",
        "module_file": market_registry.__file__,
        "market_ids": market_ids,
    }


def main() -> int:
    print(json.dumps(build_payload(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
