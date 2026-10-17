"""Synthetic three-day/two-market envelope fixture; no captured market evidence."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import FORMAT, sha256


def seal(root: Path, manifest: dict, records: list[dict]) -> None:
    raw = b"".join(canonical_bytes(record) for record in records)
    (root / "records.jsonl").write_bytes(raw)
    manifest["streams"] = [{"path": "records.jsonl", "sha256": sha256(raw),
                            "bytes": len(raw), "records": len(records)}]
    (root / "bundle.json").write_bytes(canonical_bytes(manifest))


def write_day(root: Path, day: date = date(2020, 1, 1)) -> tuple[dict, list[dict]]:
    root.mkdir()
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    conditions, records = [], []

    def add(cid, kind, seconds, payload):
        records.append({"sequence": len(records), "captured_at": (start + timedelta(seconds=seconds)).isoformat(),
                        "condition_id": cid, "kind": kind, "payload": payload,
                        "payload_sha256": sha256(canonical_bytes(payload)),
                        "source_hashes": {"synthetic-generator": sha256(b"110l-fixture-only")}})

    for market in ("fictional-a", "fictional-b"):
        cid = f"{market}-{day.isoformat()}"
        conditions.append({"condition_id": cid, "market_id": market, "domain_id": "fictional",
                           "active_from": start.isoformat(),
                           "active_until": (start + timedelta(minutes=4)).isoformat()})
        add(cid, "descriptor", 0, {"name": market})
        add(cid, "plugin_input", 1, {"p_yes": 0.5})
        add(cid, "terms", 1, {"reward_rate_per_day": "100", "min_size": "20", "max_spread_cents": "3"})
        for minute in range(4):
            if market == "fictional-a" and minute == 1:
                continue  # An actual absent capture, not a zero-valued book.
            add(cid, "book", 60 * minute + 5,
                {"yes_bids": [["0.49", "100"]], "yes_asks": [["0.51", "100"]],
                 "no_bids": [["0.49", "100"]], "no_asks": [["0.51", "100"]]})
        add(cid, "plugin_input", 181, {"p_yes": 0.8})
        add(cid, "info_event", 182, {"kind": "count_update", "action_hint": "pull"})
        add(cid, "trade", 183, {"outcome": "YES", "price": "0.48", "size": "10"})
        add(cid, "settlement", 86399, {"payout_yes": 1})
    manifest = {"format": FORMAT, "day": day.isoformat(),
                "sealed_at": (start + timedelta(days=1)).isoformat(),
                "provenance": "synthetic", "conditions": conditions, "streams": []}
    # Intentionally not chronological on disk; the reader owns ordering.
    seal(root, manifest, list(reversed(records)))
    return manifest, records


def write_three_days(root: Path) -> tuple[Path, ...]:
    directories = tuple(root / f"2020-01-0{i}" for i in (1, 2, 3))
    for directory in directories:
        write_day(directory, date.fromisoformat(directory.name))
    return directories
