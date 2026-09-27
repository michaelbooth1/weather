"""Bound Stage-A label work while retaining authoritative historical labels."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.backtesting import settlement_ledger as ledger
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug


def retained_resolved_event(label):
    """Project terminal venue evidence back through the existing reconciler.

    This is retained evidence, never a fresh venue response. Reconciliation is
    still computed against today's local bucket; a changed label can mismatch.
    """
    evidence = (label or {}).get("polymarket_reconciliation") or {}
    winners = evidence.get("winning_markets") or []
    if evidence.get("status") != "match" or not evidence.get("event_closed") or not winners:
        return None
    return {"closed": True, "markets": [
        {"groupItemTitle": row["label"], "question": row.get("question"),
         "conditionId": row.get("condition_id"), "closed": row.get("closed"),
         "umaResolutionStatus": "resolved" if row.get("resolved") else "",
         "outcomes": ["Yes", "No"], "outcomePrices": [row["yes_price"], row.get("no_price")]}
        for row in winners]}


def finalize_incremental(folders, *, as_of_date, recent_days=7, daily_summary_path=None,
                         labels_csv=ledger.DEFAULT_LABELS_CSV, overrides=None,
                         interval_minutes=10.0, gap_tolerance=1.5,
                         reconcile_polymarket=False, ledger_root=None):
    if recent_days < 0:
        raise ValueError("recent_days must be non-negative")
    labels, failures, daily_indexes, histories = [], [], {}, {}
    ledger_root = ledger.resolve_ledger_root(ledger_root)
    ledger.write_resolution_specs(ledger_root / "resolution_specs.json")
    finalized_at = datetime.now(timezone.utc)
    cutoff = as_of_date - timedelta(days=recent_days)
    for folder in map(Path, folders):
        try:
            spec = spec_for_slug(folder.name)
            if spec is None:
                continue
            target = date_from_event_slug(folder.name)
            if spec.id not in histories:
                history = ledger.read_jsonl(ledger.ledger_path_for_market(spec.id, ledger_root))
                if ledger.verify_ledger_history(history)["status"] != "PASS":
                    raise RuntimeError("refusing to reuse corrupt settlement ledger")
                histories[spec.id] = history
            previous = ledger.current_ledger_label(histories[spec.id], folder.name)
            if previous and recent_days and target < cutoff and not overrides:
                labels.append(previous)
                continue
            summary_path = Path(daily_summary_path) if daily_summary_path else ledger.daily_summary_path_for_spec(spec)
            summary_key = str(summary_path.resolve())
            if summary_key not in daily_indexes:
                daily_indexes[summary_key] = ledger.load_daily_summary(summary_path)
            label = ledger._finalize_folder_with_retry(
                folder, daily_summary_path=summary_path, daily_index=daily_indexes[summary_key],
                overrides=overrides, finalized_at=finalized_at,
                interval_minutes=interval_minutes, gap_tolerance=gap_tolerance,
                reconcile_polymarket=reconcile_polymarket,
                polymarket_event=retained_resolved_event(previous) if reconcile_polymarket else None,
                ledger_root=ledger_root)
            if label:
                labels.append(label)
        except Exception as exc:  # retain successful labels, then fail loudly
            failures.append((str(folder), f"{type(exc).__name__}: {exc}"))
    ledger.merge_labels_csv(labels_csv, labels)
    if failures:
        raise ledger.FolderFinalizationError(failures, labels=labels)
    return labels
