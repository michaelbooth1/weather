"""Forward-only paper companion for International market-harvest evidence.

The companion consumes objects already loaded by the ordinary market-making
tick.  It owns a distinct artifact family and never grants live permission or
contributes evidence to the model/promotion lane.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path

from weather.io import (
    write_csv_rows_atomic,
    write_json_atomic,
)
from weather.market.market_making_run_constants import SCHEMA_VERSION as RUN_SCHEMA_VERSION
from weather.market.market_making_run_support import (
    apply_run_budget,
    lifecycle_fill_transition,
)
from weather.market.mm_scoring_projection import SCORING_COLUMNS
from weather.market.mm_paper_constants import FILL_COLUMNS
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("market_harvest_paper_companion")
ARTIFACT_DIRECTORY = "market_harvest_companion"
PLATFORM_ID = "polymarket_global"
EVIDENCE_MODE = "market_harvest_forward_only_paper"
DEFAULT_REPORT_NAME = "market_harvest_companion_report.json"
DEFAULT_REPORT_MD_NAME = "market_harvest_companion_report.md"
DEFAULT_FILLS_NAME = "market_harvest_companion_simulated_fills.csv"
DEFAULT_QUEUE_NAME = "market_harvest_companion_queue.csv"
PENDING_TICK_NAME = "pending_tick.json"
MAX_PROCESSED_TICK_IDS = 2048

COMPANION_COLUMNS = tuple(SCORING_COLUMNS) + (
    "companion_tick_id",
    "companion_row_id",
    "companion_schema_version",
    "evidence_class",
    "evidence_surface",
    "platform_id",
    "parent_run_id",
    "policy_opportunity",
    "condition_id",
    "snapshot_id",
    "book_capture_ids",
    "book_captured_at_utc",
    "book_rows_sha256",
    "token_rows_sha256",
    "source_status_rows_sha256",
    "source_hashes_sha256",
    "exchange_economics_snapshot_id",
    "exchange_economics_hash",
    "exchange_economics_evidence_basis",
    "exchange_economics_platform",
    "quote_ttl_seconds",
    "authenticated_fill",
    "realized_pnl_eligible",
)


def _canonical_hash(value):
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _require_international_identity(*row_groups):
    """Refuse any explicit non-International platform identity."""

    identity_keys = {
        "platform",
        "platform_id",
        "exchange_platform",
        "exchange_economics_platform",
    }

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if item not in (None, ""):
                    text = str(item).strip().lower()
                    if text.startswith("polymarket_us"):
                        raise ValueError(
                            "market-harvest companion accepts International Polymarket only"
                        )
                    if str(key).lower() in identity_keys and text != PLATFORM_ID:
                        raise ValueError(
                            "market-harvest companion accepts International Polymarket only"
                        )
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    for rows in row_groups:
        visit(rows)


def _truthy(value):
    return value is True or str(value).strip().lower() in {"1", "true", "yes"}


def _require_paper_only_flags(*row_groups):
    prohibited = {
        "live_trade_permission",
        "live_trade_permission_allowed",
        "authenticated_fill",
        "authenticated_execution_evidence",
        "realized_pnl_eligible",
        "reward_eligible",
        "release_eligible",
        "promotion_eligible",
        "serving_eligible",
        "counts_toward_model_promotion",
        "counts_toward_live_forward_gate",
        "counts_toward_authenticated_account_economics",
    }

    def visit(value):
        if isinstance(value, dict):
            if any(_truthy(value.get(key)) for key in prohibited):
                raise ValueError(
                    "market-harvest companion artifact claims prohibited eligibility"
                )
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    for rows in row_groups:
        visit(rows)


def _row_with_transaction_identity(row, tick_id, surface, ordinal):
    out = {
        **row,
        "companion_tick_id": tick_id,
    }
    out["companion_row_id"] = _canonical_hash({
        "tick_id": tick_id,
        "surface": surface,
        "ordinal": int(ordinal),
        "row": out,
    })
    return out


def _source_hashes(rows):
    values = []
    for row in rows or []:
        for key, value in row.items():
            if "hash" in str(key).lower() and value not in (None, ""):
                values.append({"field": str(key), "value": str(value)})
    return sorted(values, key=lambda item: (item["field"], item["value"]))


def input_binding(book_rows, token_rows, source_rows, exchange_economics_fields):
    """Bind a companion decision to the exact already-loaded public inputs."""

    _require_international_identity(
        book_rows,
        token_rows,
        source_rows,
        exchange_economics_fields,
    )
    capture_ids = sorted({
        str(row.get("capture_id") or row.get("snapshot_id") or "")
        for row in book_rows or []
        if row.get("capture_id") or row.get("snapshot_id")
    })
    captured_times = sorted({
        str(row.get("captured_at_utc") or row.get("book_time_utc") or "")
        for row in book_rows or []
        if row.get("captured_at_utc") or row.get("book_time_utc")
    })
    source_hashes = _source_hashes(source_rows)
    economics = {
        key: exchange_economics_fields.get(key)
        for key in (
            "exchange_economics_snapshot_id",
            "exchange_economics_hash",
            "exchange_economics_evidence_basis",
        )
    }
    return {
        "book_capture_ids": capture_ids,
        "book_captured_at_utc": captured_times,
        "book_rows_sha256": _canonical_hash(book_rows or []),
        "token_rows_sha256": _canonical_hash(token_rows or []),
        "source_status_rows_sha256": _canonical_hash(source_rows or []),
        "source_hashes": source_hashes,
        "source_hashes_sha256": _canonical_hash(source_hashes),
        **economics,
        "exchange_economics_platform": exchange_economics_fields.get(
            "exchange_economics_platform"
        ),
    }


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _state_after_events(previous_open_orders, events):
    open_orders = dict(previous_open_orders or {})
    for event in events:
        key = event.get("lifecycle_key")
        transition = event.get("transition")
        if not key:
            continue
        if transition == "paper_posted":
            open_orders[key] = dict(event)
        elif transition == "filled" and key in open_orders:
            updated = lifecycle_fill_transition(open_orders[key], event)
            if updated is None:
                open_orders.pop(key, None)
            else:
                open_orders[key] = updated
        elif transition in {"canceled", "expired", "replaced", "released", "blocked_by_preflight"}:
            open_orders.pop(key, None)
    return open_orders


def _tick_id(parent_run_id, now, rows, bindings):
    return _canonical_hash({
        "parent_run_id": parent_run_id,
        "generated_at_utc": now.isoformat(),
        "policy_hashes": sorted({str(row.get("policy_hash") or "") for row in rows}),
        "markets": bindings,
    })


def _binding_columns(binding):
    return {
        "book_capture_ids": ";".join(binding.get("book_capture_ids") or []),
        "book_captured_at_utc": ";".join(binding.get("book_captured_at_utc") or []),
        "book_rows_sha256": binding.get("book_rows_sha256"),
        "token_rows_sha256": binding.get("token_rows_sha256"),
        "source_status_rows_sha256": binding.get("source_status_rows_sha256"),
        "source_hashes_sha256": binding.get("source_hashes_sha256"),
        "exchange_economics_snapshot_id": binding.get("exchange_economics_snapshot_id"),
        "exchange_economics_hash": binding.get("exchange_economics_hash"),
        "exchange_economics_evidence_basis": binding.get("exchange_economics_evidence_basis"),
        "exchange_economics_platform": binding.get("exchange_economics_platform"),
    }


def _ensure_economics_capture(parent_run_folder, folder, capture):
    capture = dict(capture or {})
    if capture.get("captured") is not True:
        return capture
    source = Path(parent_run_folder) / "exchange_economics_snapshot.json"
    destination = Path(folder) / "exchange_economics_snapshot.json"
    if not source.is_file():
        raise FileNotFoundError(source)
    if not destination.exists():
        try:
            os.link(source, destination)
        except OSError:
            temporary = destination.with_name(
                f"{destination.name}.{os.getpid()}.{time.time_ns()}.tmp"
            )
            try:
                shutil.copyfile(source, temporary)
                temporary.replace(destination)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
    observed = hashlib.sha256(destination.read_bytes()).hexdigest()
    if observed != capture.get("file_sha256"):
        raise RuntimeError("companion exchange-economics capture hash mismatch")
    return {**capture, "path": str(destination)}


def _read_json_checkpoint(path, *, label):
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"market-harvest companion {label} is corrupt") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"market-harvest companion {label} is corrupt")
    return payload


def _existing_csv_rows(path, columns, *, allow_partial_tail=False):
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != tuple(columns):
                raise RuntimeError(
                    f"market-harvest companion CSV header mismatch: {path.name}"
                )
            rows = list(reader)
            invalid = [
                index
                for index, row in enumerate(rows)
                if not str(row.get("companion_row_id") or "")
            ]
            if invalid:
                if allow_partial_tail and invalid == [len(rows) - 1]:
                    rows.pop()
                else:
                    raise RuntimeError(
                        f"market-harvest companion CSV row identity is corrupt: {path.name}"
                    )
            return rows
    except (csv.Error, OSError) as exc:
        raise RuntimeError(
            f"market-harvest companion CSV is corrupt: {path.name}"
        ) from exc


def _merge_rows_by_id(existing, incoming, *, label):
    merged = list(existing)
    seen = {}
    for row in existing:
        row_id = str(row.get("companion_row_id") or "")
        if not row_id or row_id in seen:
            raise RuntimeError(
                f"market-harvest companion {label} has missing or duplicate row identity"
            )
        seen[row_id] = row
    changed = False
    for row in incoming:
        row_id = str(row.get("companion_row_id") or "")
        if not row_id:
            raise RuntimeError(
                f"market-harvest companion {label} row identity is missing"
            )
        if row_id in seen:
            continue
        seen[row_id] = row
        merged.append(row)
        changed = True
    return merged, changed


def _merge_csv_rows_atomic(path, columns, rows):
    existing = _existing_csv_rows(path, columns, allow_partial_tail=True)
    merged, changed = _merge_rows_by_id(existing, rows, label=Path(path).name)
    if changed or not Path(path).exists():
        write_csv_rows_atomic(path, columns, merged)


def _append_csv_rows_durable(path, columns, rows):
    path = Path(path)
    if not path.exists():
        write_csv_rows_atomic(path, columns, rows)
        return
    if not rows:
        return
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl_strict(path, *, allow_partial_tail=False):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                if allow_partial_tail and line_number == len(lines):
                    break
                raise
            if not isinstance(row, dict):
                raise ValueError(f"row {line_number} is not an object")
            rows.append(row)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise RuntimeError(
            f"market-harvest companion JSONL is corrupt: {path.name}"
        ) from exc
    return rows


def _write_jsonl_rows_atomic(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _merge_jsonl_rows_atomic(path, rows):
    existing = _read_jsonl_strict(path, allow_partial_tail=True)
    merged, changed = _merge_rows_by_id(existing, rows, label=Path(path).name)
    if changed or not Path(path).exists():
        _write_jsonl_rows_atomic(path, merged)


def _append_jsonl_rows_durable(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _commit_pending_tick(folder, pending, *, recovering):
    folder = Path(folder)
    tick_id = str(pending.get("tick_id") or "")
    next_state = pending.get("next_state") or {}
    processed = list(next_state.get("processed_tick_ids") or [])
    pending_rows = (
        list(pending.get("quote_rows") or [])
        + list(pending.get("lifecycle_rows") or [])
        + list(pending.get("ledger_rows") or [])
    )
    if (
        len(tick_id) != 64
        or any(character not in "0123456789abcdef" for character in tick_id)
        or next_state.get("parent_run_id") != pending.get("parent_run_id")
        or not processed
        or processed[-1] != tick_id
        or len(processed) > MAX_PROCESSED_TICK_IDS
        or any(row.get("companion_tick_id") != tick_id for row in pending_rows)
    ):
        raise RuntimeError("market-harvest companion pending tick identity is invalid")
    _require_international_identity(
        pending.get("quote_rows") or [],
        pending.get("lifecycle_rows") or [],
        pending.get("run_config") or {},
    )
    _require_paper_only_flags(
        pending.get("quote_rows") or [],
        pending.get("lifecycle_rows") or [],
        pending.get("run_config") or {},
        pending.get("live_gate") or {},
    )
    pending_path = folder / PENDING_TICK_NAME
    completed = set(pending.get("completed_surfaces") or [])
    allowed_surfaces = {"quote", "lifecycle", "budget"}
    if not completed <= allowed_surfaces:
        raise RuntimeError("market-harvest companion pending tick phases are invalid")

    def mark_completed(surface):
        completed.add(surface)
        pending["completed_surfaces"] = sorted(completed)
        write_json_atomic(pending_path, pending)

    quote_path = folder / "quote_intents_long.csv"
    variant_path = folder / "model_variant_quote_intents_long.csv"
    if "quote" not in completed:
        if recovering:
            _merge_csv_rows_atomic(
                quote_path,
                COMPANION_COLUMNS,
                pending.get("quote_rows") or [],
            )
        else:
            _append_csv_rows_durable(
                quote_path,
                COMPANION_COLUMNS,
                pending.get("quote_rows") or [],
            )
        if not variant_path.exists():
            write_csv_rows_atomic(variant_path, COMPANION_COLUMNS, [])
        else:
            existing_variants = _existing_csv_rows(variant_path, COMPANION_COLUMNS)
            if existing_variants:
                raise RuntimeError("companion model-variant tape must remain empty")
        mark_completed("quote")
    elif not quote_path.exists() or not variant_path.exists():
        raise RuntimeError("market-harvest companion completed quote phase is missing")

    lifecycle_path = folder / "order_lifecycle.jsonl"
    if "lifecycle" not in completed:
        if recovering:
            _merge_jsonl_rows_atomic(
                lifecycle_path,
                pending.get("lifecycle_rows") or [],
            )
        else:
            _append_jsonl_rows_durable(
                lifecycle_path,
                pending.get("lifecycle_rows") or [],
            )
        mark_completed("lifecycle")
    elif not lifecycle_path.exists():
        raise RuntimeError("market-harvest companion completed lifecycle phase is missing")

    budget_path = folder / "budget_ledger.jsonl"
    if "budget" not in completed:
        if recovering:
            _merge_jsonl_rows_atomic(
                budget_path,
                pending.get("ledger_rows") or [],
            )
        else:
            _append_jsonl_rows_durable(
                budget_path,
                pending.get("ledger_rows") or [],
            )
        mark_completed("budget")
    elif not budget_path.exists():
        raise RuntimeError("market-harvest companion completed budget phase is missing")

    write_json_atomic(folder / "run_config.json", pending["run_config"])
    write_json_atomic(folder / "live_forward_gate.json", pending["live_gate"])
    write_json_atomic(folder / "run_summary.json", pending["summary"])
    write_json_atomic(folder / "companion_state.json", pending["next_state"])
    pending_path.unlink(missing_ok=True)
    return pending["summary"]


def write_tick(
    parent_run_folder,
    parent_run_id,
    target_date,
    mode,
    budget_usdc,
    now,
    raw_rows,
    preflight_rows,
    input_bindings,
    policy_config,
    *,
    exchange_economics_capture=None,
    append=False,
):
    """Publish one idempotent companion tick beneath the parent run folder."""

    if mode not in {"shadow", "paper-live-forward"}:
        raise ValueError("market-harvest companion is paper-only")
    folder = Path(parent_run_folder) / ARTIFACT_DIRECTORY
    state_path = folder / "companion_state.json"
    pending_path = folder / PENDING_TICK_NAME
    state = _read_json_checkpoint(state_path, label="checkpoint") or {}
    pending = _read_json_checkpoint(pending_path, label="pending tick")
    if not state and pending is None and any(
        (folder / name).exists()
        for name in (
            "quote_intents_long.csv",
            "order_lifecycle.jsonl",
            "budget_ledger.jsonl",
            "run_summary.json",
        )
    ):
        raise RuntimeError(
            "market-harvest companion has evidence without a recoverable checkpoint"
        )
    if state and state.get("parent_run_id") != parent_run_id:
        raise RuntimeError("market-harvest companion checkpoint parent-run mismatch")
    if pending is not None:
        if pending.get("parent_run_id") != parent_run_id:
            raise RuntimeError("market-harvest companion pending tick parent-run mismatch")
        _commit_pending_tick(folder, pending, recovering=True)
        state = pending.get("next_state") or {}

    processed = list(state.get("processed_tick_ids") or [])
    if (
        len(processed) > MAX_PROCESSED_TICK_IDS
        or len(set(processed)) != len(processed)
        or any(
            len(str(value)) != 64
            or any(character not in "0123456789abcdef" for character in str(value))
            for value in processed
        )
    ):
        raise RuntimeError("market-harvest companion checkpoint tick identities are invalid")
    tick_id = _tick_id(parent_run_id, now, raw_rows, input_bindings)
    if tick_id in processed:
        summary = _read_json_checkpoint(
            folder / "run_summary.json",
            label="run summary",
        ) or {}
        return {**summary, "status": "DUPLICATE_SKIPPED", "tick_id": tick_id}
    if processed and not append:
        raise RuntimeError(
            "market-harvest companion existing run requires append mode"
        )
    if len(processed) >= MAX_PROCESSED_TICK_IDS:
        raise RuntimeError("market-harvest companion processed-tick cap reached")

    folder.mkdir(parents=True, exist_ok=True)
    companion_economics_capture = _ensure_economics_capture(
        parent_run_folder,
        folder,
        exchange_economics_capture,
    )

    companion_run_id = f"{parent_run_id}--market-harvest"
    ttl = float(policy_config.get("quote_ttl_seconds") or 120.0)
    companion_budget = min(
        float(budget_usdc),
        float(policy_config.get("max_daily_loss") or budget_usdc),
    )
    preflight_by_market = {row["market_id"]: row for row in preflight_rows}
    annotated_raw_rows = [
        {**row, "policy_opportunity": bool(row.get("quote_permission"))}
        for row in raw_rows
    ]
    quote_rows, ledger, _risks, lifecycle_events, lifecycle = apply_run_budget(
        annotated_raw_rows,
        companion_budget,
        companion_run_id,
        target_date,
        mode,
        now,
        preflight_by_market,
        previous_open_orders=state.get("open_orders") or {},
        quote_ttl_seconds=ttl,
    )
    for row in quote_rows:
        binding = input_bindings.get(row.get("market_id") or "", {})
        row.update({
            "companion_schema_version": SCHEMA_VERSION,
            "evidence_class": "quote_opportunity",
            "evidence_surface": "public_market_data_counterfactual",
            "platform_id": PLATFORM_ID,
            "parent_run_id": parent_run_id,
            "authenticated_fill": False,
            "realized_pnl_eligible": False,
            **_binding_columns(binding),
        })
        row["live_trade_permission"] = False
    if any(row.get("live_trade_permission") for row in quote_rows):
        raise RuntimeError("market-harvest companion attempted to grant live permission")
    persisted_quote_rows = [
        _row_with_transaction_identity(row, tick_id, "quote", ordinal)
        for ordinal, row in enumerate(quote_rows)
        if row.get("quote_permission")
    ]

    lifecycle_rows = []
    for event in lifecycle_events:
        if event.get("transition") == "blocked_by_budget":
            continue
        binding = input_bindings.get(event.get("market_id") or "", {})
        lifecycle_rows.append({
            **event,
            "companion_schema_version": SCHEMA_VERSION,
            "evidence_class": "simulated_lifecycle",
            "evidence_surface": "paper_counterfactual",
            "platform_id": PLATFORM_ID,
            "parent_run_id": parent_run_id,
            "authenticated_fill": False,
            "realized_pnl_eligible": False,
            **_binding_columns(binding),
        })
    lifecycle_rows = [
        _row_with_transaction_identity(row, tick_id, "lifecycle", ordinal)
        for ordinal, row in enumerate(lifecycle_rows)
    ]
    retained_ledger = [
        row for row in ledger if row.get("event") != "budget_exhausted"
    ]
    retained_ledger = [
        _row_with_transaction_identity(row, tick_id, "budget", ordinal)
        for ordinal, row in enumerate(retained_ledger)
    ]

    cumulative = Counter(state.get("cumulative_counts") or {})
    cumulative.update({
        "ticks": 1,
        "opportunities": sum(bool(row.get("policy_opportunity")) for row in quote_rows),
        "simulated_posted_quotes": sum(bool(row.get("quote_permission")) for row in quote_rows),
        "coverage_gaps": sum(not bool(row.get("quote_permission")) for row in quote_rows),
        "simulated_posted_legs": sum(
            event.get("transition") == "paper_posted" for event in lifecycle_rows
        ),
    })
    open_orders = _state_after_events(state.get("open_orders") or {}, lifecycle_events)
    processed.append(tick_id)
    next_state = {
        "schema_version": SCHEMA_VERSION,
        "parent_run_id": parent_run_id,
        "processed_tick_ids": processed,
        "open_orders": open_orders,
        "cumulative_counts": dict(cumulative),
    }

    run_config = {
        "schema_version": RUN_SCHEMA_VERSION,
        "companion_schema_version": SCHEMA_VERSION,
        "run_id": companion_run_id,
        "parent_run_id": parent_run_id,
        "target_date": str(target_date),
        "mode": mode,
        "permission_profile": "market_harvest",
        "platform_id": PLATFORM_ID,
        "evidence_mode": EVIDENCE_MODE,
        "policy_config": policy_config,
        "quote_ttl_seconds": ttl,
        "run_budget_usdc": companion_budget,
        "input_bindings_by_market": input_bindings,
        "exchange_economics_capture": companion_economics_capture,
        "live_trade_permission_allowed": False,
        "authenticated_execution_evidence": False,
        "realized_pnl_eligible": False,
    }
    live_gate = {
        "schema_version": SCHEMA_VERSION,
        "status": "PAPER_ONLY",
        "counts_toward_live_forward_gate": False,
        "live_trade_permission": False,
        "reason": "market-harvest companion is isolated counterfactual paper evidence",
    }
    quote_path = folder / "quote_intents_long.csv"
    summary = {
        "schema_version": RUN_SCHEMA_VERSION,
        "companion_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "run_id": companion_run_id,
        "parent_run_id": parent_run_id,
        "target_date": str(target_date),
        "mode": mode,
        "generated_at_utc": now.isoformat(),
        "evidence_mode": EVIDENCE_MODE,
        "artifact_family": ARTIFACT_DIRECTORY,
        "run_folder": str(folder),
        "tick_id": tick_id,
        "latest_tick": {
            "opportunities": sum(bool(row.get("policy_opportunity")) for row in quote_rows),
            "simulated_posted_quotes": sum(bool(row.get("quote_permission")) for row in quote_rows),
            "coverage_gaps": sum(not bool(row.get("quote_permission")) for row in quote_rows),
            "simulated_posted_legs": sum(
                event.get("transition") == "paper_posted" for event in lifecycle_rows
            ),
            "reason_counts": dict(sorted(Counter(
                str(row.get("reason_code") or "unknown") for row in quote_rows
            ).items())),
            "preflight_status_counts": dict(sorted(Counter(
                str(row.get("status") or "UNKNOWN") for row in preflight_rows
            ).items())),
        },
        "cumulative": dict(cumulative),
        "open_order_count": lifecycle.get("current_open_order_count", 0),
        "budget_reserved_usdc": lifecycle.get("current_reserved_usdc", 0.0),
        "quote_intents_path": str(quote_path),
        "order_lifecycle_path": str(folder / "order_lifecycle.jsonl"),
        "run_config_path": str(folder / "run_config.json"),
        "live_forward_gate": live_gate,
        "counts_toward_live_forward_gate": False,
        "live_trade_permission_rows": 0,
        "authenticated_fill_count": 0,
        "realized_pnl_count": 0,
    }
    pending = {
        "schema_version": SCHEMA_VERSION,
        "parent_run_id": parent_run_id,
        "tick_id": tick_id,
        "quote_rows": persisted_quote_rows,
        "lifecycle_rows": lifecycle_rows,
        "ledger_rows": retained_ledger,
        "run_config": run_config,
        "live_gate": live_gate,
        "summary": summary,
        "next_state": next_state,
        "completed_surfaces": [],
    }
    write_json_atomic(pending_path, pending)
    committed = _commit_pending_tick(folder, pending, recovering=False)
    return {**committed, "run_folder": str(folder)}


COMPANION_FILL_COLUMNS = tuple(FILL_COLUMNS) + (
    "companion_schema_version",
    "evidence_class",
    "public_execution_evidence_class",
    "evidence_surface",
    "platform_id",
    "configured_fee_equivalent_estimate_usdc",
    "configured_maker_rebate_estimate_usdc",
    "configured_liquidity_reward_estimate_usdc",
    "authoritative_fee_usdc",
    "authoritative_rebate_usdc",
    "authoritative_incentive_usdc",
    "simulated_settlement_pnl_usdc",
    "simulated_net_pnl_after_fees_incentives_usdc",
    "authenticated_fill",
    "realized_pnl_eligible",
    "realized_pnl_usdc",
    "settlement_countable",
)

COMPANION_QUEUE_COLUMNS = (
    "companion_schema_version",
    "evidence_class",
    "evidence_surface",
    "platform_id",
    "leg_id",
    "status",
    "estimated_fill_size",
    "initial_queue_ahead",
    "depleted_ahead",
    "reason",
    "authenticated_fill",
    "realized_pnl_eligible",
)


def discover_run_folders(runs_root):
    root = Path(runs_root)
    if not root.exists():
        return []
    return sorted(
        path.parent
        for path in root.glob(f"*/*/{ARTIFACT_DIRECTORY}/quote_intents_long.csv")
        if path.is_file()
    )


def _companion_fill(row, *, settlement_countable):
    out = dict(row)
    out.update({
        "companion_schema_version": SCHEMA_VERSION,
        "evidence_class": "simulated_fill",
        "public_execution_evidence_class": "public_trade",
        "evidence_surface": "strict_public_trade_through_counterfactual",
        "platform_id": PLATFORM_ID,
        "configured_fee_equivalent_estimate_usdc": row.get("maker_fee_equivalent_usdc") or 0.0,
        "configured_maker_rebate_estimate_usdc": row.get("maker_rebate_estimate_usdc") or 0.0,
        "configured_liquidity_reward_estimate_usdc": row.get("liquidity_reward_estimate_usdc") or 0.0,
        "authoritative_fee_usdc": 0.0,
        "authoritative_rebate_usdc": 0.0,
        "authoritative_incentive_usdc": 0.0,
        "simulated_settlement_pnl_usdc": row.get("settlement_pnl_usdc"),
        "simulated_net_pnl_after_fees_incentives_usdc": row.get(
            "net_pnl_after_fees_incentives_usdc"
        ),
        "maker_rebate_accepted_usdc": 0.0,
        "liquidity_reward_accepted_usdc": 0.0,
        "authenticated_fill": False,
        "realized_pnl_eligible": False,
        "realized_pnl_usdc": 0.0,
        "settlement_countable": bool(settlement_countable),
    })
    if not settlement_countable:
        for field in (
            "settlement_outcome",
            "settlement_markout_per_share",
            "settlement_pnl_usdc",
            "simulated_settlement_pnl_usdc",
            "net_pnl_after_fees_incentives_usdc",
            "simulated_net_pnl_after_fees_incentives_usdc",
        ):
            out[field] = None
    return out


def _companion_queue(row):
    return {
        **row,
        "companion_schema_version": SCHEMA_VERSION,
        "evidence_class": "simulated_queue",
        "evidence_surface": "public_book_queue_counterfactual",
        "platform_id": PLATFORM_ID,
        "authenticated_fill": False,
        "realized_pnl_eligible": False,
    }


def _render_score_report(payload):
    summary = payload["summary"]
    return "\n".join([
        "# International Market-Harvest Paper Companion",
        "",
        "This report is counterfactual paper evidence. It contains no authenticated fills, realized P&L, or live permission.",
        "",
        f"- Opportunities: `{summary['opportunities']}`",
        f"- Simulated posted quotes: `{summary['simulated_posted_quotes']}`",
        f"- Simulated posted legs: `{summary['simulated_posted_legs']}`",
        f"- Strict conservative fills: `{summary['conservative_fills']}`",
        f"- Unresolved legs: `{summary['unresolved_legs']}`",
        f"- Coverage gaps: `{summary['coverage_gaps']}`",
        "- Public-counterfactual countable market-days: "
        f"`{summary['public_counterfactual_countable_market_days']}`",
        "- Authenticated-account countable market-days: "
        f"`{summary['authenticated_account_countable_market_days']}`",
        f"- Authenticated fills: `{summary['authenticated_fill_count']}`",
        f"- Realized-P&L rows: `{summary['realized_pnl_count']}`",
        "",
    ])


def _validated_companion_quote_rows(folders):
    rows = []
    for folder in folders:
        config = _read_json_checkpoint(
            Path(folder) / "run_config.json",
            label="run config",
        ) or {}
        _require_international_identity(config)
        _require_paper_only_flags(config)
        if (
            config.get("companion_schema_version") != SCHEMA_VERSION
            or config.get("permission_profile") != "market_harvest"
            or config.get("platform_id") != PLATFORM_ID
            or config.get("evidence_mode") != EVIDENCE_MODE
            or config.get("mode") not in {"shadow", "paper-live-forward"}
        ):
            raise ValueError("companion run config identity is invalid")
        bindings = config.get("input_bindings_by_market") or {}
        folder_rows = _read_companion_rows(Path(folder) / "quote_intents_long.csv")
        _require_international_identity(folder_rows)
        _require_paper_only_flags(folder_rows)
        for row in folder_rows:
            market_id = str(row.get("market_id") or "")
            binding = bindings.get(market_id) or {}
            expected_binding = _binding_columns(binding)
            identity_values = (
                row.get("companion_tick_id"),
                row.get("companion_row_id"),
            )
            if any(
                len(str(value or "")) != 64
                or any(character not in "0123456789abcdef" for character in str(value))
                for value in identity_values
            ):
                raise ValueError("companion quote transaction identity is invalid")
            if (
                row.get("companion_schema_version") != SCHEMA_VERSION
                or row.get("evidence_class") != "quote_opportunity"
                or row.get("evidence_surface") != "public_market_data_counterfactual"
                or row.get("platform_id") != PLATFORM_ID
                or row.get("run_id") != config.get("run_id")
                or row.get("parent_run_id") != config.get("parent_run_id")
                or row.get("target_date") != str(config.get("target_date") or "")
                or not market_id
                or not row.get("event_slug")
                or not row.get("condition_id")
                or not row.get("clob_token_id")
            ):
                raise ValueError("companion quote artifact identity is invalid")
            for key, expected in expected_binding.items():
                if str(row.get(key) or "") != str(expected or ""):
                    raise ValueError("companion quote input binding is invalid")
        rows.extend(folder_rows)
    return rows


def _settlement_countability_gate(quote_rows, snapshots_root, ledger_root):
    from weather.backtesting.settlement_ledger import ledger_label_for_slug
    from weather.market.market_registry import spec_for_slug

    market_days = sorted({
        (
            str(row.get("target_date") or ""),
            str(row.get("market_id") or ""),
            str(row.get("event_slug") or ""),
        )
        for row in quote_rows
        if str(row.get("quote_permission") or "").lower() in {"true", "1", "yes"}
    })
    blockers = []
    rows = []
    valid_keys = []
    for target_date, market_id, event_slug in market_days:
        row_blockers = []
        label = None
        try:
            if ledger_root is not None:
                label = ledger_label_for_slug(event_slug, ledger_root=ledger_root)
            else:
                label = _read_json_checkpoint(
                    Path(snapshots_root) / event_slug / "settlement.json",
                    label=f"settlement for {event_slug}",
                )
        except RuntimeError as exc:
            row_blockers.append("settlement_revision_ambiguous_or_invalid")
            label_error = str(exc)
        else:
            label_error = None
        spec = spec_for_slug(event_slug)
        if not label:
            row_blockers.append("settlement_missing")
        else:
            if label.get("promotion_countable") is not True:
                row_blockers.append("settlement_not_promotion_countable")
            if str(label.get("target_date") or "") != target_date:
                row_blockers.append("settlement_target_date_mismatch")
            if str(label.get("market_id") or "") != market_id:
                row_blockers.append("settlement_market_mismatch")
            if str(label.get("event_slug") or event_slug) != event_slug:
                row_blockers.append("settlement_event_mismatch")
            expected_unit = str(getattr(spec, "display_unit", "") or "").upper()
            observed_unit = str(label.get("settlement_unit") or "").upper()
            if not expected_unit or observed_unit != expected_unit:
                row_blockers.append("settlement_unit_mismatch")
            try:
                float(label.get("settlement_bucket"))
            except (TypeError, ValueError):
                row_blockers.append("settlement_bucket_missing")
        row_blockers = sorted(set(row_blockers))
        if not row_blockers:
            valid_keys.append((target_date, market_id))
        blockers.extend(row_blockers)
        rows.append({
            "target_date": target_date,
            "market_id": market_id,
            "event_slug": event_slug,
            "status": "PASS" if not row_blockers else "BLOCK",
            "blockers": row_blockers,
            "error": label_error,
            "settlement_unit": (label or {}).get("settlement_unit"),
            "promotion_countable": (label or {}).get("promotion_countable"),
        })
    if not market_days:
        blockers.append("no_quote_market_days")
    blockers = sorted(set(blockers))
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "blockers": blockers,
        "market_day_count": len(market_days),
        "countable_market_day_count": len(valid_keys),
        "valid_market_day_keys": [list(key) for key in valid_keys],
        "rows": rows,
    }


def score_runs(
    runs_root,
    snapshots_root,
    backtest_root,
    *,
    selected_run_folders=None,
    latest_n=14,
    now=None,
    casebook_path=None,
    ledger_root=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_target_date=None,
    exchange_economics_platform=PLATFORM_ID,
    exchange_economics_required=True,
    clob_recon_path=None,
):
    """Score only companion folders through the canonical strict paper scorer."""

    if str(exchange_economics_platform) != PLATFORM_ID:
        raise ValueError(
            "market-harvest companion accepts International Polymarket only"
        )
    from weather.market import mm_paper

    runs_root = Path(runs_root).resolve()
    folders = [
        Path(path).resolve()
        for path in (selected_run_folders or discover_run_folders(runs_root))
    ]
    for folder in folders:
        try:
            relative = folder.relative_to(runs_root)
        except ValueError as exc:
            raise ValueError("companion run folder escapes the runs root") from exc
        if len(relative.parts) != 3 or relative.parts[-1] != ARTIFACT_DIRECTORY:
            raise ValueError("selected run folder is not a companion artifact folder")
    if latest_n is not None:
        folders = folders[-max(0, int(latest_n)):]
    if not folders:
        return {
            "status": "SKIPPED",
            "reason": "no_market_harvest_companion_runs",
            "selected_run_count": 0,
        }
    companion_quote_rows = _validated_companion_quote_rows(folders)
    payload = mm_paper.build_paper_payload(
        runs_root=runs_root,
        snapshots_root=snapshots_root,
        backtest_root=backtest_root,
        selected_run_folders=folders,
        casebook_path=casebook_path or Path(backtest_root) / "disagreement_casebook.json",
        promotion_refresh=Path(backtest_root) / "f_family_promotion_refresh.json",
        now=now,
        ledger_root=ledger_root,
        exchange_economics_snapshot_path=exchange_economics_snapshot_path,
        exchange_economics_target_date=exchange_economics_target_date,
        exchange_economics_platform=exchange_economics_platform,
        exchange_economics_required=exchange_economics_required,
        clob_recon_path=clob_recon_path or Path(backtest_root) / "clob_book_recon.json",
        include_model_variants=False,
        stream_run_inputs=True,
        materialize_output_rows=True,
    )
    queue = [_companion_queue(row) for row in payload.get("queue_companion") or []]
    strict_summary = payload.get("summary") or {}
    completeness = payload.get("fill_evidence_completeness") or {}
    quote_market_days = {
        (str(row.get("target_date") or ""), str(row.get("market_id") or ""))
        for row in companion_quote_rows
        if str(row.get("quote_permission") or "").lower() in {"true", "1", "yes"}
        and row.get("target_date")
        and row.get("market_id")
    }
    settlement_gate = _settlement_countability_gate(
        companion_quote_rows,
        snapshots_root,
        ledger_root,
    )
    conditions_by_token = {}
    for row in companion_quote_rows:
        conditions_by_token.setdefault(str(row.get("clob_token_id") or ""), set()).add(
            str(row.get("condition_id") or "")
        )
    valid_payload_fills = []
    execution_identity_rows = []
    for row in payload.get("fills") or []:
        token = str(row.get("clob_token_id") or "")
        expected = sorted(conditions_by_token.get(token) or [])
        observed = str(row.get("execution_condition_id") or "")
        row_blockers = []
        if len(expected) != 1:
            row_blockers.append("ambiguous_quote_condition_binding")
        elif observed != expected[0]:
            row_blockers.append("execution_condition_mismatch")
        if row_blockers:
            execution_identity_rows.append({
                "clob_token_id": token,
                "expected_condition_ids": expected,
                "execution_condition_id": observed,
                "blockers": row_blockers,
            })
        else:
            valid_payload_fills.append(row)
    execution_identity_blockers = sorted({
        blocker
        for row in execution_identity_rows
        for blocker in row["blockers"]
    })
    execution_identity_gate = {
        "status": "PASS" if not execution_identity_blockers else "BLOCK",
        "blockers": execution_identity_blockers,
        "rejected_fill_count": len(execution_identity_rows),
        "rows": execution_identity_rows,
    }
    valid_settlement_keys = {
        tuple(key) for key in settlement_gate.get("valid_market_day_keys") or []
    }
    fills = [
        _companion_fill(
            row,
            settlement_countable=(
                str(row.get("target_date") or ""),
                str(row.get("market_id") or ""),
            ) in valid_settlement_keys,
        )
        for row in valid_payload_fills
    ]
    blockers = sorted(set(
        list(completeness.get("blockers") or [])
        + execution_identity_blockers
    ))
    unresolved = int(completeness.get("unresolved_resting_quote_count") or 0)
    coverage_gaps = (
        len(blockers)
        + int(completeness.get("missing_size_trade_rows") or 0)
        + int(completeness.get("rejected_execution_evidence_rows") or 0)
        + int(completeness.get("conflicting_execution_evidence_rows") or 0)
        + int(completeness.get("missing_book_queue_legs") or 0)
        + int(completeness.get("missing_trade_size_queue_legs") or 0)
    )
    fallback_opportunities = sum(
        str(
            row.get("policy_opportunity")
            if row.get("policy_opportunity") not in (None, "")
            else row.get("quote_permission")
        ).lower() in {"true", "1", "yes"}
        for row in companion_quote_rows
    )
    recorded_opportunities = sum(
        int(
            (((_read_json_checkpoint(
                folder / "run_summary.json",
                label="run summary",
            ) or {}).get("cumulative") or {}).get(
                "opportunities"
            ) or 0)
        )
        for folder in folders
    )
    summary = {
        "opportunities": recorded_opportunities or fallback_opportunities,
        "simulated_posted_quotes": int(strict_summary.get("quote_permission_rows") or 0),
        "simulated_posted_legs": int(strict_summary.get("quote_legs") or 0),
        "conservative_fills": len(fills),
        "unresolved_legs": unresolved,
        "coverage_gaps": coverage_gaps,
        "public_counterfactual_countable_market_days": (
            len(quote_market_days & valid_settlement_keys)
            if completeness.get("status") == "PASS"
            and settlement_gate.get("status") == "PASS"
            and execution_identity_gate.get("status") == "PASS"
            else 0
        ),
        "authenticated_account_countable_market_days": 0,
        "queue_companion_legs": len(queue),
        "queue_estimated_fill_legs": int(strict_summary.get("queue_estimated_fill_legs") or 0),
        "fill_evidence_completeness_status": completeness.get("status"),
        "fill_evidence_blockers": blockers,
        "authenticated_fill_count": 0,
        "realized_pnl_count": 0,
        "live_trade_permission_rows": 0,
        "counts_toward_model_promotion": False,
        "counts_toward_live_forward_gate": False,
        "counts_toward_authenticated_account_economics": False,
    }
    report_status = (
        "PASS"
        if completeness.get("status") == "PASS"
        and settlement_gate.get("status") == "PASS"
        and execution_identity_gate.get("status") == "PASS"
        else "BLOCK"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": report_status,
        "generated_at_utc": payload.get("generated_at_utc"),
        "platform_id": PLATFORM_ID,
        "evidence_mode": EVIDENCE_MODE,
        "selected_run_folders": [str(folder) for folder in folders],
        "summary": summary,
        "strict_scorer_schema_version": payload.get("schema_version"),
        "strict_fill_rule": "strict_trade_through_price_and_recorded_size",
        "fill_evidence_completeness": completeness,
        "event_diagnostics": payload.get("event_diagnostics") or {},
        "exchange_economics_gate": payload.get("exchange_economics_gate") or {},
        "settlement_countability_gate": settlement_gate,
        "execution_identity_gate": execution_identity_gate,
        "authoritative_economics": {
            "fees_usdc": 0.0,
            "rebates_usdc": 0.0,
            "incentives_usdc": 0.0,
            "reason": "no authenticated account-level payout or fee evidence",
        },
    }
    out_root = Path(backtest_root)
    write_json_atomic(out_root / DEFAULT_REPORT_NAME, report)
    (out_root / DEFAULT_REPORT_MD_NAME).write_text(
        _render_score_report(report),
        encoding="utf-8",
    )
    write_csv_rows_atomic(out_root / DEFAULT_FILLS_NAME, COMPANION_FILL_COLUMNS, fills)
    write_csv_rows_atomic(out_root / DEFAULT_QUEUE_NAME, COMPANION_QUEUE_COLUMNS, queue)
    return {
        "status": report_status,
        "selected_run_count": len(folders),
        "report_path": str(out_root / DEFAULT_REPORT_NAME),
        "report_markdown_path": str(out_root / DEFAULT_REPORT_MD_NAME),
        "fills_path": str(out_root / DEFAULT_FILLS_NAME),
        "queue_path": str(out_root / DEFAULT_QUEUE_NAME),
        "summary": summary,
    }


def _read_companion_rows(path):
    from weather.io import read_csv_rows

    return read_csv_rows(path)


__all__ = [
    "ARTIFACT_DIRECTORY",
    "COMPANION_COLUMNS",
    "EVIDENCE_MODE",
    "SCHEMA_VERSION",
    "input_binding",
    "discover_run_folders",
    "score_runs",
    "write_tick",
]
