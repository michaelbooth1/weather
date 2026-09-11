"""Fresh bounded source-protection review for the approved detail-file archive.

This reads settlement and dependency metadata only. The reclaim owner validates
the evidence again and holds native source pins before any original deletion.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from weather.operations import production_cold_archive_stage as archive
from weather.operations.storage_recovery_inventory import event_date
from weather.schema_registry import schema_version

MIB = 1024**2
FAMILIES = re.compile(
    r"(?:clob_tokens[.]jsonl|market_ws[.]jsonl|order_books[.]jsonl|order_books_long[.]csv(?:[.]gz)?|"
    r"price_history[.]csv|variant_predictions[.]jsonl)")


class Observations:
    def __init__(self):
        self.specs = {}

    def text(self, path, maximum=2 * MIB):
        path = archive._safe_path(Path(path))
        with path.open("rb") as stream:
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError("source review metadata exceeds bound")
        self.specs[str(path)] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
        return raw.decode("utf-8-sig")

    def json(self, path, maximum=2 * MIB):
        return json.loads(self.text(path, maximum), object_pairs_hook=archive._pairs)

    def spec(self, path):
        return self.specs[str(Path(path))]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def review_sources(*, production_root, entry, entry_sha256, output_root, now=None):
    root, out = Path(production_root), Path(output_root)
    current = now or datetime.now(timezone.utc)
    archive._require_sha256(entry_sha256)
    require(Path(entry["source_root"]) == root / "data", "review source root differs")
    require(not out.exists(), "source review attempt is spent")
    obs = Observations()
    events = sorted({archive._relative(row["path"]).split("/")[1] for row in entry["files"]})
    require(1 <= len(events) <= 16, "source review event bound")
    for row in entry["files"]:
        parts = row["path"].split("/")
        require(len(parts) == 3 and parts[0] == "snapshots" and FAMILIES.fullmatch(parts[2]),
                "unreviewed detail file family")
    rows, settlements, all_countable = [], [], True
    for event in events:
        date = event_date(event).isoformat()
        require("2026-06-15" <= date <= "2026-07-30", "source date outside approved primary")
        path = root / "data" / "snapshots" / event / "settlement.json"
        value = obs.json(path)
        reconciliation = value["polymarket_reconciliation"]
        winners = reconciliation["winning_markets"]
        require(value["target_date"] == date and reconciliation["event_closed"] is True
                and reconciliation["status"] == "match" and isinstance(winners, list)
                and 1 <= len(winners) <= 256 and all(
                    row["closed"] is True and row["resolved"] is True for row in winners),
                "final market settlement unproved")
        all_countable &= value["quality_grade"] in ("complete", "manual_override")
        settlements.append(obs.spec(path))
        rows.append({"event_slug": event, "target_date": date, "settlement": obs.spec(path)})
    backtest = root / "data" / "backtest"
    barrier_path = backtest / "settled_day_analysis_barrier.json"
    barrier = obs.json(barrier_path)
    barrier_text = json.dumps(barrier)
    require(all(barrier.get("target_date") != row["target_date"]
                and row["event_slug"] not in barrier_text for row in rows),
            "barrier references a selected event")
    queue_path = backtest / "model_market_disagreement_review_queue.json"
    queue = obs.json(queue_path)
    audit_path = backtest / "model_market_disagreement_audit.jsonl"
    require(Path(queue["source_audit_log_path"]) == audit_path, "queue audit source changed")
    audit = {}
    for line in obs.text(audit_path).splitlines():
        if line.strip():
            value = json.loads(line, object_pairs_hook=archive._pairs)
            require(value.get("audit_key") and value.get("event_slug"), "queue audit lacks identity")
            audit[value["audit_key"]] = value
    protected = set()
    for row in queue["rows"]:
        keys = row["sample_audit_keys"]
        require(isinstance(keys, list) and len(keys) == row["case_count"], "queue samples incomplete")
        for key in keys:
            require(key in audit, "queue audit key absent")
            protected.add(audit[key]["event_slug"])
    require(not protected.intersection(events), "review queue protects selected event")
    learning_path = backtest / "daily_learning.json"
    learning = obs.json(learning_path, 8 * MIB)
    experiments = learning["experiment_queue"]
    require(experiments["status"] == "EMPTY"
            and experiments["summary"]["eligible_count"] == 0
            and experiments["summary"]["materialized_executable_count"] == 0
            and all(row["eligible"] is False for row in experiments["items"]),
            "executable experiments remain")
    triggered = []
    for state in ("pending", "inflight"):
        path = archive._safe_path(root / "data" / "snapshots" / "triggered_snapshot_queue" / state,
                                  directory=True)
        require(next(path.iterdir(), None) is None, "triggered snapshot queue is not empty")
        triggered.append({"path": str(path), "entry_count": 0})
    corpus_path = backtest / "active_variant_shadow_window_corpus.json"
    corpus = obs.json(corpus_path, 8 * MIB)
    retained, corpus_events = [], []
    for event in events:
        folder = root / "data" / "snapshots" / event
        matches = [row for row in corpus["entries"] if row["event_slug"] == event]
        require(len(matches) <= 1 and (not matches or
                Path(matches[0]["snapshot_tape_path"]) == folder / "snapshots_long.csv"),
                "unexpected protected corpus dependency")
        names = ("snapshots_long.csv", "replay_inputs.jsonl", "settlement.json") if matches else (
            "settlement.json",)
        if matches:
            corpus_events.append(event)
        for name in names:
            path = archive._safe_path(folder / name)
            size = path.stat().st_size
            require(size > 0, "required retained corpus input missing")
            retained.append({"path": str(path), "bytes": size, "retained": True})
    pit_path = backtest / "point_in_time_validation_plan.json"
    pit = obs.json(pit_path)
    require(pit["status"] == "PASS", "PIT plan unavailable")
    reserved_path = root / "docs" / "operations" / "reserved-confirmation-window.md"
    require("NONE ARE CURRENTLY RESERVED." in obs.text(reserved_path), "reserved dates changed")
    release = root / "artifacts" / "releases" / "current_release.json"
    require(not release.parent.exists(), "active release graph now requires explicit review")
    contracts = []
    for relative in (
            "src/weather/reporting/promotion/promotion_corpus.py",
            "src/weather/reporting/validation/point_in_time_evaluation.py",
            "src/weather/backtesting/replay.py", "src/weather/operations/closed_market_day_archive.py",
            "docs/operations/reserved-confirmation-window.md"):
        path = root / relative
        obs.text(path)
        contracts.append(obs.spec(path))
    observations = {
        "observed_at_utc": current.isoformat(), "selected_events": rows,
        "exact_sources": [{"path": row["path"], "sha256": row["sha256"]} for row in entry["files"]],
        "barrier": {"source": obs.spec(barrier_path), "selected_market_day_referenced": False},
        "queues": {"review_queue": obs.spec(queue_path), "audit_source": obs.spec(audit_path),
                   "protected_market_days": sorted(protected), "daily_learning": obs.spec(learning_path),
                   "triggered_snapshot_queues": triggered},
        "point_in_time": {"validation_plan": obs.spec(pit_path), "corpus": obs.spec(corpus_path),
                          "historical_corpus_events": corpus_events,
                          "required_retained_inputs": retained, "required_artifact_family": "snapshots_long",
                          "historical_dates_in_plan": sorted(
                              {row["target_date"] for row in rows if row["target_date"] in pit["fleet_dates"]}),
                          "selected_detail_file_is_corpus_input": False, "currently_reserved_dates": []},
        "protected_release": {"active_release_pointer": str(release), "release_root_absent": True,
                              "selected_detail_file_is_replay_record_input": False},
        "reviewed_source_contracts": contracts}
    out.mkdir()
    archive._write(out / "observations.json", observations)
    observed_spec = {"path": str(out / "observations.json"),
                     "sha256": archive._load(out / "observations.json")[1]}
    checks = {
        "market_day_closed": {"status": "PASS", "closed": True, "evidence": settlements},
        "settlement_final": {"status": "PASS", "settled": True,
                            "settlement_state": "settled_countable" if all_countable else "settled_non_countable",
                            "evidence": settlements}}
    for name, evidence in (
            ("barriers_clear", [obs.spec(barrier_path), observed_spec]),
            ("queues_clear", [obs.spec(queue_path), observed_spec]),
            ("point_in_time_windows_clear", [obs.spec(pit_path), observed_spec]),
            ("protected_release_replay_inputs_clear", [observed_spec])):
        checks[name] = {"status": "PASS", "open_references": [], "evidence": evidence}
    review = archive._seal({
        "schema_version": schema_version("cold_archive_source_review"), "status": "PASS",
        "entry_sha256": entry_sha256, "archive_id": entry["archive_id"],
        "files": observations["exact_sources"], "market_days": rows,
        "checked_at_utc": current.isoformat(),
        "expires_at_utc": (current + timedelta(minutes=5)).isoformat(), "checks": checks}, "receipt_hash")
    archive._write(out / "review.json", review)
    return {"path": str(out / "review.json"), "sha256": archive._load(out / "review.json")[1]}
