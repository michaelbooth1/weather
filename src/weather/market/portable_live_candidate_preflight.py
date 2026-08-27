"""Fail-closed local audit of a portable live-candidate public substrate.

This command performs no network request, credential access, or exchange
mutation.  It revalidates the exact host-local inputs produced for one paper
market-harvest tick before the short-lived candidate selector is allowed to
contact the public CLOB book endpoint.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from weather.market.exchange_economics import load_exchange_economics_gate
from weather.market.market_config import config_for_date, ensure_date
from weather.market.market_making_run_support import (
    clob_token_discovery_health,
    latest_book_rows,
    market_harvest_clob_feature_rows,
    parse_time,
    preflight_book_audit,
    read_csv_rows,
    source_status_degradation_preflight,
    source_status_for_snapshot,
    source_status_is_current,
)
from weather.market.mm_live_candidate_cli import (
    _load_paper_quote_evidence,
    load_economics_acceptance_evidence,
)
from weather.market.mm_policy import load_observation_status, utc_now
from weather.operations import event_metadata_validation
from weather.operations.live_path_security import (
    assert_no_ambient_market_registry_override,
    validate_nonreparse_directory,
    validate_regular_nonreparse_file,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("portable_live_candidate_substrate_preflight")
MAX_PUBLIC_INPUT_AGE_SECONDS = 600.0
MAX_BOOK_AGE_SECONDS = 180.0


def _reject_duplicate_pairs(pairs):
    payload = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def _read_json(path: str | Path, label: str) -> dict:
    source = Path(path)
    try:
        payload = json.loads(
            source.read_bytes().decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(f"{label} is not readable JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return payload


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_new_json(path: Path, payload: dict) -> None:
    """Write one immutable receipt without a check-then-replace race."""

    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).resolve(strict=False) == Path(right).resolve(strict=False)
    except OSError:
        return False


def _age_seconds(value, now: datetime) -> float | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return (now - parsed).total_seconds()


def _latest_token_rows(folder: Path) -> list[dict]:
    rows = read_csv_rows(folder / "clob_tokens.csv")
    if not rows:
        return []
    latest = max(
        (parse_time(row.get("captured_at_utc")) for row in rows),
        default=None,
        key=lambda value: value or datetime.min.replace(tzinfo=timezone.utc),
    )
    if latest is None:
        return []
    return [row for row in rows if parse_time(row.get("captured_at_utc")) == latest]


def _selected_observation(payload: dict, market_id: str) -> dict:
    market_state = ((payload.get("markets") or {}).get(market_id) or {})
    observation = market_state.get("last_observation") or {}
    return observation if isinstance(observation, dict) else {}


def _economics_market(payload: dict, market_id: str, target_date: str) -> dict:
    matches = [
        row
        for row in payload.get("markets") or []
        if isinstance(row, dict)
        and row.get("location_id") == market_id
        and row.get("event_date") == target_date
    ]
    return matches[0] if len(matches) == 1 else {}


def _validation_content_is_intact(payload: dict) -> bool:
    observed = payload.get("validation_hash")
    if not isinstance(observed, str) or len(observed) != 64:
        return False
    candidate = copy.deepcopy(payload)
    candidate.pop("validation_hash", None)
    summary = candidate.get("summary")
    if isinstance(summary, dict):
        summary.pop("validation_hash", None)
    for row in candidate.get("market_rows") or []:
        if isinstance(row, dict):
            row.pop("validation_hash", None)
    return event_metadata_validation.stable_hash(candidate) == observed


def _metadata_matches_validation(
    metadata: dict,
    validation: dict,
    *,
    market_id: str,
    target_date: str,
    event_slug: str,
) -> bool:
    location = event_metadata_validation.generated_locations_by_id(metadata).get(
        market_id
    ) or {}
    candidates = event_metadata_validation._event_candidates(
        location,
        ensure_date(target_date),
        event_slug,
    )
    rows = [
        row
        for row in validation.get("market_rows") or []
        if isinstance(row, dict) and row.get("market_id") == market_id
    ]
    return (
        len(candidates) == 1
        and len(rows) == 1
        and event_metadata_validation.normalize_event(candidates[0])
        == rows[0].get("generated_event")
    )


def build_preflight(
    *,
    market_id: str,
    target_date: str,
    event_metadata_path: str | Path,
    event_metadata_validation_path: str | Path,
    snapshots_root: str | Path,
    observation_status_path: str | Path,
    economics_snapshot_path: str | Path,
    accepted_economics_snapshot_path: str | Path,
    economics_drift_report_path: str | Path,
    paper_run_config_path: str | Path,
    paper_preflight_path: str | Path,
    paper_quote_intents_path: str | Path,
    now=None,
) -> dict:
    assert_no_ambient_market_registry_override()
    current = utc_now(now)
    target = ensure_date(target_date).isoformat()
    config = config_for_date(target, market_id)
    # Validate the lexical path before resolving it so a junction or symlink
    # cannot disappear from the evidence boundary.
    root = validate_nonreparse_directory(snapshots_root)
    folder = validate_nonreparse_directory(root / config.event_slug)

    paths = {
        "event_metadata": Path(event_metadata_path),
        "event_metadata_validation": Path(event_metadata_validation_path),
        "snapshots_root": root,
        "event_folder": folder,
        "observation_status": Path(observation_status_path),
        "economics_snapshot": Path(economics_snapshot_path),
        "accepted_economics_snapshot": Path(accepted_economics_snapshot_path),
        "economics_drift_report": Path(economics_drift_report_path),
        "paper_run_config": Path(paper_run_config_path),
        "paper_preflight": Path(paper_preflight_path),
        "paper_quote_intents": Path(paper_quote_intents_path),
        "clob_tokens": folder / "clob_tokens.csv",
        "order_books_summary": folder / "order_books_summary.csv",
        "source_status_long": folder / "source_status_long.csv",
    }
    for name, path in tuple(paths.items()):
        if name not in {"snapshots_root", "event_folder"}:
            paths[name] = validate_regular_nonreparse_file(path)
    file_identity_keys = {
        os.path.normcase(str(path))
        for name, path in paths.items()
        if name not in {"snapshots_root", "event_folder"}
    }
    if len(file_identity_keys) != len(paths) - 2:
        raise RuntimeError("portable candidate substrate inputs must be distinct files")
    missing_paths: list[str] = []
    initial_file_hashes = {
        name: _sha256(path) for name, path in paths.items() if path.is_file()
    }

    metadata = _read_json(paths["event_metadata"], "event metadata")
    validation = _read_json(paths["event_metadata_validation"], "event metadata validation")
    validation_gate = event_metadata_validation.gate_for_market(
        validation,
        market_id,
    )
    validation_age = _age_seconds(validation.get("generated_at_utc"), current)

    token_rows = _latest_token_rows(folder)
    token_gate = clob_token_discovery_health(token_rows)
    source_rows = source_status_for_snapshot(folder, None)
    source_snapshot_ids = {
        str(row.get("snapshot_id") or "") for row in source_rows if row.get("snapshot_id")
    }
    source_snapshot_id = (
        next(iter(source_snapshot_ids)) if len(source_snapshot_ids) == 1 else None
    )
    source_degradation = source_status_degradation_preflight(
        folder,
        source_snapshot_id,
    )
    books = latest_book_rows(folder)
    book_audit = preflight_book_audit(
        folder,
        now=current,
        max_gap_seconds=MAX_BOOK_AGE_SECONDS,
        loop_status={},
    )
    projected_features = market_harvest_clob_feature_rows(books, now=current)

    observation_payload = _read_json(paths["observation_status"], "observation status")
    observation_gate = load_observation_status(paths["observation_status"], now=current)
    selected_observation = _selected_observation(observation_payload, market_id)

    economics_payload = _read_json(paths["economics_snapshot"], "economics snapshot")
    economics_gate = load_exchange_economics_gate(
        paths["economics_snapshot"],
        target,
        platform="polymarket_global",
        now=current,
        max_age_hours=2,
        required=True,
    )
    economics_market = _economics_market(economics_payload, market_id, target)
    acceptance = load_economics_acceptance_evidence(
        paths["economics_snapshot"],
        paths["accepted_economics_snapshot"],
        paths["economics_drift_report"],
        target,
        now=current,
    )

    paper_config = _read_json(paths["paper_run_config"], "paper run config")
    paper_preflight = _read_json(paths["paper_preflight"], "paper preflight")
    paper_evidence = _load_paper_quote_evidence(
        paths["paper_run_config"],
        paths["paper_quote_intents"],
        target_date=target,
        economics_snapshot_id=economics_gate.get("snapshot_id"),
        economics_hash=economics_gate.get("exchange_economics_hash"),
        now=current,
    )

    token_conditions = {
        str(row.get("condition_id") or "").lower()
        for row in token_rows
        if row.get("condition_id")
    }
    token_ids = {
        str(row.get("clob_token_id") or "")
        for row in token_rows
        if row.get("clob_token_id")
    }
    economics_condition = str(economics_market.get("condition_id") or "").lower()
    economics_tokens = {
        str(value) for value in economics_market.get("token_ids") or [] if value
    }
    paper_markets = paper_preflight.get("markets") or []
    paper_market = paper_markets[0] if len(paper_markets) == 1 else {}
    token_times = [
        parse_time(row.get("captured_at_utc")) for row in token_rows
    ]
    source_times = [
        parse_time(row.get("captured_at_utc") or row.get("fetched_at"))
        for row in source_rows
    ]
    token_times = [value for value in token_times if value is not None]
    source_times = [value for value in source_times if value is not None]
    token_age = (
        (current - max(token_times)).total_seconds() if token_times else None
    )
    source_age = (
        (current - max(source_times)).total_seconds() if source_times else None
    )

    checks = {
        "all_inputs_exist": not missing_paths,
        "validation_schema": (
            validation.get("schema_version")
            == event_metadata_validation.SCHEMA_VERSION
        ),
        "validation_content_hash": _validation_content_is_intact(validation),
        "validation_target": validation.get("target_date") == target,
        "validation_market": validation.get("markets") == [market_id],
        "validation_event_metadata_path": _same_path(
            validation.get("event_metadata_path") or "",
            paths["event_metadata"],
        ),
        "validation_pass": validation_gate.get("ok") is True,
        "validation_event_slug": validation_gate.get("event_slug") == config.event_slug,
        "event_metadata_matches_validation": _metadata_matches_validation(
            metadata,
            validation,
            market_id=market_id,
            target_date=target,
            event_slug=config.event_slug,
        ),
        "validation_fresh": (
            validation_age is not None
            and 0 <= validation_age <= MAX_PUBLIC_INPUT_AGE_SECONDS
        ),
        "event_folder_exact": folder.is_dir() and folder.parent == root,
        "token_discovery_pass": token_gate.get("ok") is True,
        "token_discovery_fresh": (
            token_age is not None
            and 0 <= token_age <= MAX_PUBLIC_INPUT_AGE_SECONDS
        ),
        "source_status_current": source_status_is_current(source_rows),
        "source_status_snapshot_exact": (
            source_snapshot_id is not None
            and source_degradation.get("snapshot_matches") is True
        ),
        "source_status_fresh": (
            source_age is not None
            and 0 <= source_age <= MAX_PUBLIC_INPUT_AGE_SECONDS
        ),
        "source_degradation_allows_trading_evidence": (
            source_degradation.get("ok") is True
            and source_degradation.get("trading_evidence_allowed") is True
        ),
        "current_books_present": bool(books),
        "book_tape_pass": book_audit.get("ok") is True,
        "market_harvest_features_derivable": bool(projected_features),
        "observation_heartbeat_fresh": observation_gate.get("fresh") is True,
        "observation_market_exact": selected_observation.get("market_id") == market_id,
        "observation_target_exact": selected_observation.get("target_date") == target,
        "observation_event_slug_exact": (
            selected_observation.get("event_slug") == config.event_slug
        ),
        "economics_gate_pass": economics_gate.get("ok") is True,
        "economics_market_exact": bool(economics_market),
        "economics_condition_matches_tokens": (
            bool(economics_condition)
            and token_conditions == {economics_condition}
        ),
        "economics_tokens_match_collector": (
            bool(economics_tokens) and economics_tokens == token_ids
        ),
        "economics_acceptance_pass": acceptance.get("drift_status") == "PASS",
        "paper_config_snapshot_root": _same_path(
            paper_config.get("snapshots_root") or "",
            root,
        ),
        "paper_config_observation_status": _same_path(
            paper_config.get("observation_status_path") or "",
            paths["observation_status"],
        ),
        "paper_config_market_and_date": (
            paper_config.get("markets") == [market_id]
            and paper_config.get("target_date") == target
            and paper_config.get("permission_profile") == "market_harvest"
            and paper_config.get("mode") == "paper-live-forward"
        ),
        "paper_preflight_pass": paper_preflight.get("status") == "PASS",
        "paper_preflight_market_exact": (
            paper_market.get("market_id") == market_id
            and paper_market.get("target_date") == target
            and paper_market.get("event_slug") == config.event_slug
            and _same_path(paper_market.get("folder") or "", folder)
            and all(gate.get("ok") is True for gate in paper_market.get("gates") or [])
        ),
        "paper_quote_evidence_current": (
            paper_evidence.get("market_id") == market_id
            and bool(paper_evidence.get("qualifying"))
        ),
        "consumed_files_stable": all(
            path.is_file() and _sha256(path) == initial_file_hashes.get(name)
            for name, path in paths.items()
            if name not in {"snapshots_root", "event_folder"}
        ),
    }
    blockers = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not blockers else "BLOCK",
        "checked_at_utc": current.isoformat(),
        "market_id": market_id,
        "target_date": target,
        "event_slug": config.event_slug,
        "snapshots_root": str(root),
        "event_folder": str(folder),
        "checks": checks,
        "blockers": blockers,
        "missing_paths": missing_paths,
        "artifact_paths": {
            name: str(path)
            for name, path in paths.items()
            if name not in {"snapshots_root", "event_folder"}
        },
        "artifact_sha256": initial_file_hashes,
        "validation_hash": validation.get("validation_hash"),
        "economics_snapshot_id": economics_gate.get("snapshot_id"),
        "economics_snapshot_sha256": economics_gate.get("exchange_economics_hash"),
        "accepted_snapshot_file_sha256": acceptance.get(
            "accepted_snapshot_file_sha256"
        ),
        "economics_drift_report_file_sha256": acceptance.get(
            "drift_report_file_sha256"
        ),
        "paper_quote_intents_sha256": paper_evidence.get(
            "quote_intents_sha256"
        ),
        "paper_quote_intents_row_count": paper_evidence.get(
            "quote_intents_row_count"
        ),
        "credential_access": False,
        "exchange_contact": False,
        "exchange_mutation": False,
        "network_access": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--event-metadata", required=True)
    parser.add_argument("--event-metadata-validation", required=True)
    parser.add_argument("--snapshots-root", required=True)
    parser.add_argument("--observation-status", required=True)
    parser.add_argument("--economics-snapshot", required=True)
    parser.add_argument("--accepted-economics-snapshot", required=True)
    parser.add_argument("--economics-drift-report", required=True)
    parser.add_argument("--paper-run-config", required=True)
    parser.add_argument("--paper-preflight", required=True)
    parser.add_argument("--paper-quote-intents", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--now", default=None, help="Testing-only UTC timestamp.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output_input = Path(args.json_out)
        if not output_input.is_absolute():
            raise RuntimeError("portable candidate substrate output must be absolute")
        output_parent = validate_nonreparse_directory(output_input.parent)
        output = output_parent / output_input.name
        if output.exists() or output.is_symlink():
            raise RuntimeError("portable candidate substrate preflight output must be new")
        payload = build_preflight(
            market_id=args.market,
            target_date=args.target_date,
            event_metadata_path=args.event_metadata,
            event_metadata_validation_path=args.event_metadata_validation,
            snapshots_root=args.snapshots_root,
            observation_status_path=args.observation_status,
            economics_snapshot_path=args.economics_snapshot,
            accepted_economics_snapshot_path=args.accepted_economics_snapshot,
            economics_drift_report_path=args.economics_drift_report,
            paper_run_config_path=args.paper_run_config,
            paper_preflight_path=args.paper_preflight,
            paper_quote_intents_path=args.paper_quote_intents,
            now=args.now,
        )
        _write_new_json(output, payload)
    except Exception as exc:  # fail closed without leaking artifact contents
        print(f"portable candidate substrate preflight failed: {type(exc).__name__}")
        return 2
    print(f"portable candidate substrate preflight {payload['status']}")
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
