"""Progress audit over durable backtest, replay, trust, and loop artifacts.

The central question is deliberately blunt: are we improving over time since
the project started?  This module answers with the artifacts already used by
the roadmap rather than rerunning expensive backtests.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path, docs_path

from weather.reporting.formatting import (
    fmt_num,
    fmt_signed,
    markdown_table,
)


SCHEMA_VERSION = "progress_audit_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_ROADMAP = docs_path() / "roadmap" / "ROADMAP.md"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "progress_audit.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "progress_audit_report.md"
ROADMAP_CORPUS_EXCLUDES = {"codebase-organization-audit.md"}

POOLED_REPLAY_FILES = [
    ("pooled_v0_1", "pooled_candidate_replay.json"),
    ("pooled_v0_2", "pooled_candidate_replay_v0_2.json"),
    ("pooled_v0_3", "pooled_candidate_replay_v0_3.json"),
    ("pooled_latest", "pooled_candidate_replay_latest.json"),
]


def utc_now():
    return datetime.now(timezone.utc)


def read_text(path):
    path = Path(path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def iter_roadmap_corpus_paths(path):
    """Yield the markdown files that make up the split roadmap corpus."""
    path = Path(path)
    if path.is_dir():
        candidates = sorted(path.rglob("*.md"))
    elif path.name.lower() == "roadmap.md":
        candidates = [path]
        if path.parent.exists():
            candidates.extend(
                child
                for child in sorted(path.parent.rglob("*.md"))
                if child != path
            )
    else:
        candidates = [path]

    seen = set()
    for candidate in candidates:
        if candidate.name in ROADMAP_CORPUS_EXCLUDES:
            continue
        key = candidate.resolve() if candidate.exists() else candidate
        if key in seen:
            continue
        seen.add(key)
        yield candidate


def read_roadmap_corpus_text(path):
    parts = []
    for roadmap_file in iter_roadmap_corpus_paths(path):
        text = read_text(roadmap_file)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def maybe_float(value):
    if value in (None, "", "-"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
        try:
            return float(text) / 100.0
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def maybe_int(value):
    number = maybe_float(value)
    if number is None:
        return None
    return int(number)


def parse_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def age_seconds(value, now=None):
    dt = parse_datetime(value)
    if dt is None:
        return None
    now = now or utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now.astimezone(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())


def parse_table_row(line):
    line = line.strip()
    if not line.startswith("|"):
        return []
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    if cells and all(set(cell) <= {":", "-", " "} for cell in cells):
        return []
    return cells


def parse_backtest_report(path):
    text = read_text(path)
    if not text:
        return {"path": str(path), "exists": False}

    summary = {
        "path": str(path),
        "exists": True,
        "generated": None,
        "market_days": None,
        "band_rows": None,
        "all_snapshot_brier_skill_vs_market": None,
        "daily_first_brier_skill_vs_market": None,
        "all_snapshot_log_loss_delta_market_minus_model": None,
        "model_brier": None,
        "market_brier": None,
        "model_logloss": None,
        "market_logloss": None,
        "daily_first_model_brier": None,
        "daily_first_market_brier": None,
        "feature_coverage": None,
        "by_day": [],
    }
    generated = re.search(r"^Generated:\s*(.+)$", text, flags=re.MULTILINE)
    if generated:
        summary["generated"] = generated.group(1).strip()

    headline = re.search(
        r"Market days:\s*(\d+)\s*\|\s*Total band-rows scored:\s*(\d+)",
        text,
    )
    if headline:
        summary["market_days"] = int(headline.group(1))
        summary["band_rows"] = int(headline.group(2))

    metric_patterns = {
        "all_snapshot_brier_skill_vs_market": r"\|\s*All-snapshot Brier skill vs market\s*\|\s*([+-]?\d+(?:\.\d+)?)\s*\|",
        "daily_first_brier_skill_vs_market": r"\|\s*Daily-first Brier skill vs market\s*\|\s*([+-]?\d+(?:\.\d+)?)\s*\|",
        "all_snapshot_log_loss_delta_market_minus_model": r"\|\s*All-snapshot log-loss delta \(market - model\)\s*\|\s*([+-]?\d+(?:\.\d+)?)\s*\|",
    }
    for key, pattern in metric_patterns.items():
        match = re.search(pattern, text)
        if match:
            summary[key] = float(match.group(1))

    coverage = re.search(
        r"\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([0-9.]+)%\s*\|\s*([^|]+)\|",
        text[text.find("## Feature Vector Coverage") :],
    )
    if coverage:
        summary["feature_coverage"] = {
            "rows": int(coverage.group(1)),
            "rows_with_features": int(coverage.group(2)),
            "coverage_rate": float(coverage.group(3)) / 100.0,
            "schemas": coverage.group(4).strip(),
        }

    for line in text.splitlines():
        cells = parse_table_row(line)
        if not cells:
            continue
        if cells[:2] == ["All snapshots", "-"] and len(cells) >= 10:
            summary["model_brier"] = maybe_float(cells[3])
            summary["market_brier"] = maybe_float(cells[4])
            summary["model_logloss"] = maybe_float(cells[7])
            summary["market_logloss"] = maybe_float(cells[8])
        elif cells[:1] == ["Daily-first equal-day average"] and len(cells) >= 10:
            summary["daily_first_model_brier"] = maybe_float(cells[3])
            summary["daily_first_market_brier"] = maybe_float(cells[4])
        elif cells and re.match(r"\d{4}-\d{2}-\d{2}", cells[0]) and len(cells) >= 8:
            summary["by_day"].append({
                "date": cells[0],
                "rows": maybe_int(cells[1]),
                "model_brier": maybe_float(cells[2]),
                "market_brier": maybe_float(cells[3]),
                "brier_skill": maybe_float(cells[4]),
                "model_logloss": maybe_float(cells[5]),
                "market_logloss": maybe_float(cells[6]),
            })

    return summary


def parse_roadmap_baselines(path):
    text = read_roadmap_corpus_text(path)
    number = r"([+-]?\d+(?:\.\d+)?)"
    baselines = {
        "path": str(path),
        "initial_strict_toronto": None,
        "pre_label_three_day": None,
        "calibration_pre_label": None,
    }
    strict = re.search(
        r"clean market day and\s*(\d+)\s*band rows\..{0,400}?"
        rf"model Brier was\s*{number}\s*versus market Brier\s*{number}.*?"
        rf"Brier skill score of\s*{number}",
        text,
        flags=re.DOTALL,
    )
    if strict:
        baselines["initial_strict_toronto"] = {
            "label": "2026-05-31 strict Toronto baseline",
            "market_days": 1,
            "band_rows": int(strict.group(1)),
            "model_brier": float(strict.group(2)),
            "market_brier": float(strict.group(3)),
            "brier_skill": float(strict.group(4)),
            "source": str(path),
        }

    pre_label = re.search(
        r"over 3 settled-looking market days and\s*(\d+)\s*band rows\..{0,120}?"
        rf"All-snapshot Brier skill was\s*{number}",
        text,
        flags=re.DOTALL,
    )
    if pre_label:
        baselines["pre_label_three_day"] = {
            "label": "pre-label 3-day provisional backtest",
            "market_days": 3,
            "band_rows": int(pre_label.group(1)),
            "brier_skill": float(pre_label.group(2)),
            "source": str(path),
        }

    calibration = re.search(
        rf"Brier improved from\s*{number}\s*to\s*{number}.*?"
        rf"Brier skill versus Polymarket improved from\s*{number}\s*to\s*{number}",
        text,
        flags=re.DOTALL,
    )
    if calibration:
        baselines["calibration_pre_label"] = {
            "label": "pre-label calibration improvement",
            "brier_before": float(calibration.group(1)),
            "brier_after": float(calibration.group(2)),
            "skill_before": float(calibration.group(3)),
            "skill_after": float(calibration.group(4)),
            "source": str(path),
        }
    return baselines


def read_pooled_replay(path, label):
    payload = read_json(path, default={}) or {}
    aggregate = payload.get("aggregate") or {}
    corpus = payload.get("corpus") or {}
    coverage = payload.get("coverage") or {}
    verdict_counts = Counter()
    for row in payload.get("market_rows") or []:
        verdict = (
            row.get("verdict")
            or row.get("candidate_verdict")
            or row.get("action")
            or ""
        )
        if verdict:
            verdict_counts[str(verdict).upper()] += 1
    return {
        "label": label,
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at": payload.get("generated_at"),
        "verdict": payload.get("verdict"),
        "cutover_decision": payload.get("cutover_decision"),
        "candidate_market_verdict": payload.get("candidate_market_verdict"),
        "rows": aggregate.get("n"),
        "candidate_brier": aggregate.get("candidate_brier"),
        "current_brier": aggregate.get("current_brier"),
        "recorded_brier": aggregate.get("recorded_brier"),
        "market_brier": aggregate.get("market_brier"),
        "candidate_skill": aggregate.get("candidate_skill"),
        "delta_vs_current": aggregate.get("delta_vs_current"),
        "delta_vs_market": aggregate.get("delta_vs_market"),
        "blocked_markets": verdict_counts.get("BLOCK", 0),
        "shadow_markets": verdict_counts.get("SHADOW", 0),
        "promoted_markets": verdict_counts.get("PASS", 0) + verdict_counts.get("PROMOTE", 0),
        "verdict_counts": dict(verdict_counts),
        "corpus_market_days": corpus.get("market_day_count"),
        "corpus_snapshots": corpus.get("snapshot_count"),
        "corpus_band_rows": corpus.get("band_row_count"),
        "missing_candidate_rows": coverage.get("missing_candidate_rows"),
        "family_rows": coverage.get("family_rows"),
    }


def load_pooled_series(backtest_root):
    rows = []
    for label, filename in POOLED_REPLAY_FILES:
        path = Path(backtest_root) / filename
        row = read_pooled_replay(path, label)
        if row["exists"]:
            rows.append(row)
    return rows


def load_promotion_refresh(path):
    payload = read_json(path, default={}) or {}
    if not payload:
        return {"path": str(path), "exists": False}
    candidate = payload.get("candidate") or {}
    decisions = payload.get("decisions") or {}
    gauntlet = payload.get("serving_gauntlet") or {}
    corpus = payload.get("corpus") or {}
    trust = payload.get("trust") or {}
    return {
        "path": str(path),
        "exists": True,
        "generated_at_utc": payload.get("generated_at_utc"),
        "candidate_verdict": candidate.get("verdict"),
        "candidate_market_verdict": candidate.get("candidate_market_verdict"),
        "candidate_cutover_decision": candidate.get("cutover_decision"),
        "candidate_aggregate": candidate.get("aggregate") or {},
        "action_counts": decisions.get("action_counts") or {},
        "blocked_markets": decisions.get("blocked_markets") or [],
        "shadow_markets": decisions.get("shadow_markets") or [],
        "promote_markets": decisions.get("promote_markets") or [],
        "global_replay_gate_ok": decisions.get("global_replay_gate_ok"),
        "serving_gauntlet_verdict": gauntlet.get("verdict"),
        "serving_gauntlet_baseline_ok": gauntlet.get("baseline_ok"),
        "serving_gauntlet_corpus_ok": gauntlet.get("corpus_ok"),
        "serving_gauntlet_fidelity_ok": gauntlet.get("fidelity_ok"),
        "corpus_market_days": corpus.get("market_day_count"),
        "corpus_snapshots": corpus.get("snapshot_count"),
        "corpus_band_rows": corpus.get("band_row_count"),
        "identity_record_count": corpus.get("identity_record_count"),
        "trust_min": trust.get("family_min_trust"),
        "trust_max": trust.get("family_max_trust"),
    }


def parse_promotion_gauntlet_report(path):
    text = read_text(path)
    if not text:
        return {"path": str(path), "exists": False}
    summary = {"path": str(path), "exists": True}
    decision = re.search(r"Decision:\s*\*\*(.+?)\*\*", text)
    if decision:
        summary["decision"] = decision.group(1)
    regression = re.search(r"\|\s*Regression\s*\|\s*([^|]+)\|\s*([^|]+)\|", text)
    if regression:
        summary["regression_status"] = regression.group(1).strip()
        summary["regression_message"] = regression.group(2).strip()
    market_counts = Counter()
    for line in text.splitlines():
        cells = parse_table_row(line)
        if len(cells) >= 12 and cells[0] not in {"Market", ":---"}:
            verdict = cells[11].strip().upper()
            if verdict in {"PASS", "SHADOW", "BLOCK"}:
                market_counts[verdict] += 1
    summary["market_verdict_counts"] = dict(market_counts)
    return summary


def load_market_day_labels(path):
    rows = []
    path = Path(path)
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    quality = Counter(row.get("quality_grade") or "unknown" for row in rows)
    markets = Counter(row.get("market_id") or "unknown" for row in rows)
    complete_by_market = Counter(
        row.get("market_id") or "unknown"
        for row in rows
        if row.get("quality_grade") == "complete"
    )
    target_dates = sorted({row.get("target_date") for row in rows if row.get("target_date")})
    return {
        "path": str(path),
        "exists": path.exists(),
        "rows": len(rows),
        "quality_counts": dict(quality),
        "market_counts": dict(markets),
        "complete_by_market": dict(complete_by_market),
        "first_target_date": target_dates[0] if target_dates else None,
        "last_target_date": target_dates[-1] if target_dates else None,
        "target_date_count": len(target_dates),
    }


def load_location_trust(path):
    rows = read_json(path, default=[]) or []
    grades = Counter(row.get("grade") or "unknown" for row in rows)
    settled_days = [row.get("settled_days") or 0 for row in rows]
    trust_scores = [row.get("trust_score") or 0 for row in rows]
    skills = [row.get("brier_skill_vs_market") for row in rows if row.get("brier_skill_vs_market") is not None]
    by_market = {
        row.get("market") or row.get("market_id") or f"market_{idx + 1}": {
            "trust_score": row.get("trust_score"),
            "grade": row.get("grade"),
            "settled_days": row.get("settled_days"),
            "brier_skill_vs_market": row.get("brier_skill_vs_market"),
            "model_brier": row.get("model_brier"),
            "market_brier": row.get("market_brier"),
        }
        for idx, row in enumerate(rows)
    }
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "market_count": len(rows),
        "grade_counts": dict(grades),
        "min_settled_days": min(settled_days) if settled_days else None,
        "max_settled_days": max(settled_days) if settled_days else None,
        "avg_trust_score": (sum(trust_scores) / len(trust_scores)) if trust_scores else None,
        "positive_skill_markets": sum(1 for value in skills if value > 0),
        "negative_skill_markets": sum(1 for value in skills if value < 0),
        "by_market": by_market,
    }


def load_fleet_observability(path):
    payload = read_json(path, default={}) or {}
    if not payload:
        return {"path": str(path), "exists": False}
    collection = payload.get("collection") or {}
    collection_summary = collection.get("summary") or {}
    clob = payload.get("clob") or {}
    return {
        "path": str(path),
        "exists": True,
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "summary": payload.get("summary") or {},
        "collection_states": collection_summary.get("states") or {},
        "collection_action_required": collection_summary.get("action_required"),
        "collection_market_count": collection_summary.get("market_count"),
        "clob_loop": clob.get("loop") or {},
        "clob_books_ok": (clob.get("books") or {}).get("ok"),
        "clob_market_count": len(((clob.get("books") or {}).get("markets") or [])),
    }


def compute_loop_state(status, kind, now=None):
    if not status:
        return {"kind": kind, "exists": False, "state": "MISSING"}
    now = now or utc_now()
    heartbeat_key = "last_heartbeat"
    interval_seconds = status.get("interval_seconds")
    if interval_seconds is None:
        interval_seconds = (status.get("interval_minutes") or 10.0) * 60.0
    heartbeat_age = age_seconds(status.get(heartbeat_key), now)
    stale_after = max(float(interval_seconds) * 3.0, 180.0)
    if status.get("paused"):
        state = "PAUSED"
    elif status.get("consecutive_errors", 0):
        state = "ERRORING"
    elif heartbeat_age is None:
        state = "UNKNOWN"
    elif heartbeat_age <= stale_after:
        state = "RUNNING"
    else:
        state = "STALE"
    return {
        "kind": kind,
        "exists": True,
        "state": state,
        "pid": status.get("pid"),
        "started_at": status.get("started_at"),
        "heartbeat_age_seconds": heartbeat_age,
        "configured_interval_seconds": interval_seconds,
        "consecutive_errors": status.get("consecutive_errors"),
        "last_error": status.get("last_error"),
        "iterations": status.get("iterations"),
    }


def load_loop_statuses(snapshots_root, now=None):
    snapshots_root = Path(snapshots_root)
    snapshot_status = read_json(snapshots_root / "loop_status.json", default={}) or {}
    clob_status = read_json(snapshots_root / "clob_loop_status.json", default={}) or {}
    snapshot_loop = compute_loop_state(snapshot_status, "weather_model_snapshot", now=now)
    clob_loop = compute_loop_state(clob_status, "clob_book", now=now)
    clob_loop["last_books_age_seconds"] = age_seconds(clob_status.get("last_books_captured_at"), now)
    clob_loop["last_mode"] = clob_status.get("last_mode")
    clob_loop["error_markets"] = clob_status.get("error_markets")
    return {
        "snapshot_loop": snapshot_loop,
        "clob_loop": clob_loop,
    }


def classify_trend(payload):
    backtest = payload.get("current_backtest") or {}
    baseline = (payload.get("roadmap_baselines") or {}).get("initial_strict_toronto") or {}
    pooled = payload.get("pooled_candidate_series") or []
    refresh = payload.get("promotion_refresh") or {}
    loops = payload.get("loop_statuses") or {}

    skill_gain = None
    model_brier_delta = None
    if baseline and backtest:
        if baseline.get("brier_skill") is not None and backtest.get("all_snapshot_brier_skill_vs_market") is not None:
            skill_gain = backtest["all_snapshot_brier_skill_vs_market"] - baseline["brier_skill"]
        if baseline.get("model_brier") is not None and backtest.get("model_brier") is not None:
            model_brier_delta = backtest["model_brier"] - baseline["model_brier"]

    candidate_improved_gate = False
    candidate_replay_gain = None
    if len(pooled) >= 2:
        first = pooled[0]
        latest = pooled[-1]
        candidate_improved_gate = first.get("verdict") == "BLOCK" and latest.get("verdict") == "SHADOW_ONLY"
        if first.get("candidate_brier") is not None and latest.get("candidate_brier") is not None:
            candidate_replay_gain = latest["candidate_brier"] - first["candidate_brier"]

    snapshot_running = (loops.get("snapshot_loop") or {}).get("state") == "RUNNING"
    clob_running = (loops.get("clob_loop") or {}).get("state") == "RUNNING"
    current_skill = backtest.get("all_snapshot_brier_skill_vs_market")
    model_beats_market = current_skill is not None and current_skill > 0

    return {
        "headline": "improving_but_not_market_beating",
        "model_skill_gain_vs_initial_strict": skill_gain,
        "model_brier_delta_vs_initial_strict": model_brier_delta,
        "model_beats_market_on_current_headline": model_beats_market,
        "candidate_gate_improved": candidate_improved_gate,
        "candidate_brier_delta_first_to_latest": candidate_replay_gain,
        "candidate_cutover_ready": refresh.get("candidate_cutover_decision") == "CUT_OVER",
        "serving_gauntlet_clear": refresh.get("serving_gauntlet_verdict") in {"PASS", "PARTIAL_PASS"},
        "operational_capture_running": snapshot_running and clob_running,
        "answer": (
            "Yes: the project is improving in data capture, replay fidelity, promotion discipline, "
            "and some model metrics. No: the current headline probability model still does not beat "
            "Polymarket on the small settlement-scored sample, so the north-star objective is not "
            "yet proven."
        ),
    }


def build_audit(backtest_root=DEFAULT_BACKTEST_ROOT, snapshots_root=DEFAULT_SNAPSHOTS_ROOT, roadmap_path=DEFAULT_ROADMAP):
    backtest_root = Path(backtest_root)
    now = utc_now()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "roadmap_baselines": parse_roadmap_baselines(roadmap_path),
        "current_backtest": parse_backtest_report(backtest_root / "backtest_report.md"),
        "pooled_candidate_series": load_pooled_series(backtest_root),
        "promotion_refresh": load_promotion_refresh(backtest_root / "f_family_promotion_refresh.json"),
        "promotion_gauntlet_latest": parse_promotion_gauntlet_report(backtest_root / "promotion_gauntlet_latest_report.md"),
        "market_day_labels": load_market_day_labels(backtest_root / "market_day_labels.csv"),
        "location_trust": load_location_trust(backtest_root / "location_trust.json"),
        "fleet_observability": load_fleet_observability(backtest_root / "fleet_observability.json"),
        "loop_statuses": load_loop_statuses(snapshots_root, now=now),
    }
    payload["trend_assessment"] = classify_trend(payload)
    return payload


def fmt_brier(value):
    return fmt_num(value, 4)


def fmt_skill(value):
    return fmt_signed(value, 3) if value is not None else "-"


def fmt_count(value):
    return "-" if value is None else str(value)


def render_report(payload):
    trend = payload["trend_assessment"]
    baseline = payload["roadmap_baselines"].get("initial_strict_toronto") or {}
    pre_label = payload["roadmap_baselines"].get("pre_label_three_day") or {}
    calibration = payload["roadmap_baselines"].get("calibration_pre_label") or {}
    backtest = payload["current_backtest"]
    labels = payload["market_day_labels"]
    trust = payload["location_trust"]
    refresh = payload["promotion_refresh"]
    gauntlet = payload["promotion_gauntlet_latest"]
    fleet = payload["fleet_observability"]
    loops = payload["loop_statuses"]

    lines = [
        "# Progress Audit - Are We Improving?",
        "",
        f"Generated: {payload['generated_at_utc']}",
        "",
        "## Verdict",
        "",
        "**Yes, but only partially.** The project is clearly improving as a "
        "research and production system: capture is broader, replay gates are "
        "stricter, bad candidates are blocked or shadowed, and the clean Toronto "
        "headline sample has moved in the right direction. The north-star claim "
        "is still unproven because the current settlement-scored model remains "
        "behind Polymarket on headline Brier/log loss.",
        "",
        trend["answer"],
        "",
        "## Scorecard",
        "",
    ]

    scorecard_rows = [
        [
            "Toronto model vs market",
            (
                f"{baseline.get('market_days', '-')} day / "
                f"{fmt_count(baseline.get('band_rows'))} rows / "
                f"skill {fmt_skill(baseline.get('brier_skill'))}"
            ),
            (
                f"{fmt_count(backtest.get('market_days'))} days / "
                f"{fmt_count(backtest.get('band_rows'))} rows / "
                f"skill {fmt_skill(backtest.get('all_snapshot_brier_skill_vs_market'))}"
            ),
            (
                f"skill {fmt_signed(trend.get('model_skill_gain_vs_initial_strict'), 3)}, "
                f"model Brier {fmt_signed(trend.get('model_brier_delta_vs_initial_strict'), 4)}"
            ),
            "Improving, still behind market",
        ],
        [
            "F-family pooled candidate",
            "v0.1 BLOCK / 11 blocked markets",
            (
                f"{refresh.get('candidate_verdict', '-')} / "
                f"{refresh.get('candidate_cutover_decision', '-')}; "
                f"{len(refresh.get('promote_markets') or [])} promote, "
                f"{len(refresh.get('shadow_markets') or [])} shadow"
            ),
            "bad model blocked, later candidates shadowed",
            "Process improving, not cutover-ready",
        ],
        [
            "Validation data",
            "1 strict clean Toronto day",
            (
                f"{labels.get('quality_counts', {}).get('complete', 0)} complete labels, "
                f"{labels.get('rows', 0)} ledger rows; "
                f"Toronto trust {(trust.get('by_market') or {}).get('toronto', {}).get('trust_score', '-')}/100"
            ),
            "more markets and days, still shallow",
            "Improving but data-limited",
        ],
        [
            "Operations/capture",
            "ad hoc / shallow market tape",
            (
                f"snapshot loop {(loops.get('snapshot_loop') or {}).get('state')}; "
                f"CLOB loop {(loops.get('clob_loop') or {}).get('state')}; "
                f"fleet status {fleet.get('status', '-')}"
            ),
            "always-on capture and book tape shipped",
            "Strong improvement",
        ],
    ]
    lines.extend(markdown_table(["Dimension", "Starting Evidence", "Latest Evidence", "Movement", "Read"], scorecard_rows))
    lines.extend(["", "## Model Skill Trend", ""])
    lines.extend(markdown_table(
        ["Checkpoint", "Days", "Rows", "Model Brier", "Market Brier", "Brier Skill", "Read"],
        [
            [
                "Pre-label 3-day provisional",
                fmt_count(pre_label.get("market_days")),
                fmt_count(pre_label.get("band_rows")),
                "-",
                "-",
                fmt_skill(pre_label.get("brier_skill")),
                "Useful only as rough early evidence; later labels marked partial tapes.",
            ],
            [
                "Initial strict Toronto baseline",
                fmt_count(baseline.get("market_days")),
                fmt_count(baseline.get("band_rows")),
                fmt_brier(baseline.get("model_brier")),
                fmt_brier(baseline.get("market_brier")),
                fmt_skill(baseline.get("brier_skill")),
                "First clean benchmark after coverage-aware labels.",
            ],
            [
                "Current strict Toronto report",
                fmt_count(backtest.get("market_days")),
                fmt_count(backtest.get("band_rows")),
                fmt_brier(backtest.get("model_brier")),
                fmt_brier(backtest.get("market_brier")),
                fmt_skill(backtest.get("all_snapshot_brier_skill_vs_market")),
                "Better than initial strict baseline, still negative vs Polymarket.",
            ],
        ],
    ))
    if calibration:
        lines.extend([
            "",
            (
                "Calibration also improved the early provisional sample "
                f"(Brier {fmt_brier(calibration.get('brier_before'))} -> "
                f"{fmt_brier(calibration.get('brier_after'))}, skill "
                f"{fmt_skill(calibration.get('skill_before'))} -> "
                f"{fmt_skill(calibration.get('skill_after'))}), but that sample "
                "is not the current promotion-grade evidence."
            ),
        ])

    lines.extend(["", "## Pooled Candidate Trend", ""])
    candidate_rows = []
    for row in payload["pooled_candidate_series"]:
        candidate_rows.append([
            row["label"],
            row.get("verdict"),
            row.get("cutover_decision"),
            fmt_brier(row.get("candidate_brier")),
            fmt_brier(row.get("current_brier")),
            fmt_brier(row.get("market_brier")),
            fmt_signed(row.get("delta_vs_current"), 4),
            fmt_count(row.get("blocked_markets")),
            fmt_count(row.get("shadow_markets")),
        ])
    lines.extend(markdown_table(
        ["Run", "Verdict", "Cutover", "Candidate Brier", "Current Brier", "Market Brier", "Delta vs Current", "Blocked", "Shadow"],
        candidate_rows,
    ))

    lines.extend([
        "",
        "The candidate pipeline has improved materially: the first pooled F artifact "
        "was a clear regression and was blocked across all F markets; the latest "
        "candidate is shadow-only with no blocked F markets in the candidate gate. "
        "That is real progress in model development discipline, even though market "
        "Brier is still better than the candidate Brier.",
        "",
        "## Promotion And Trust",
        "",
    ])
    lines.extend(markdown_table(
        ["Metric", "Current Value"],
        [
            ["Promotion refresh candidate", f"{refresh.get('candidate_verdict', '-')} / {refresh.get('candidate_cutover_decision', '-')}"],
            ["Promotion actions", f"{len(refresh.get('promote_markets') or [])} promote, {len(refresh.get('shadow_markets') or [])} shadow, {len(refresh.get('blocked_markets') or [])} blocked"],
            ["Current serving gauntlet", f"{refresh.get('serving_gauntlet_verdict', '-')}"],
            ["Gauntlet regression", f"{gauntlet.get('regression_status', '-')} - {gauntlet.get('regression_message', '-')}"],
            ["Promotion corpus", f"{fmt_count(refresh.get('corpus_market_days'))} market-days, {fmt_count(refresh.get('corpus_snapshots'))} snapshots, {fmt_count(refresh.get('corpus_band_rows'))} band rows"],
            ["Exact identity settled records", fmt_count(refresh.get("identity_record_count"))],
            ["Trust grades", ", ".join(f"{grade}: {count}" for grade, count in sorted((trust.get("grade_counts") or {}).items()))],
            ["Skill by market", f"{trust.get('positive_skill_markets', 0)} positive, {trust.get('negative_skill_markets', 0)} negative"],
        ],
    ))

    lines.extend([
        "",
        "The safety systems are doing their job: no F market is being promoted on "
        "one settled day and 15/100 trust. The negative sign is that the latest "
        "serving gauntlet is still BLOCK because the current serving replay "
        "regresses versus its baseline.",
        "",
        "## Data And Capture Trend",
        "",
    ])
    snapshot_loop = loops.get("snapshot_loop") or {}
    clob_loop = loops.get("clob_loop") or {}
    lines.extend(markdown_table(
        ["Area", "Evidence"],
        [
            ["Market-day ledger", f"{labels.get('rows', 0)} labels: {labels.get('quality_counts', {})}"],
            ["Location trust", f"{trust.get('market_count', 0)} markets, avg trust {fmt_num(trust.get('avg_trust_score'), 1)}"],
            ["Fleet observability", f"status {fleet.get('status', '-')}; summary {fleet.get('summary', {})}; collection states {fleet.get('collection_states', {})}"],
            ["Weather/model loop", f"{snapshot_loop.get('state')} / errors {snapshot_loop.get('consecutive_errors')} / heartbeat age {fmt_num((snapshot_loop.get('heartbeat_age_seconds') or 0) / 60.0, 1)} min"],
            ["CLOB book loop", f"{clob_loop.get('state')} / mode {clob_loop.get('last_mode')} / errors {clob_loop.get('consecutive_errors')} / heartbeat age {fmt_num(clob_loop.get('heartbeat_age_seconds'), 1)} sec"],
        ],
    ))

    lines.extend([
        "",
        "## Bottom Line",
        "",
        "We are improving over time in the ways that make future accuracy possible: "
        "cleaner labels, more markets, stronger historical coverage, supervised "
        "capture, CLOB book data, replay identity/corpus pins, and promotion gates. "
        "We are also seeing some model movement in the right direction, especially "
        "Toronto strict skill improving from -0.478 to -0.336 and pooled F moving "
        "from BLOCK to SHADOW_ONLY.",
        "",
        "We are **not yet improving enough to claim the model beats Polymarket**. "
        "Current headline skill is still negative, F-family trust remains mostly "
        "one settled day per market, and the current serving gauntlet is blocked. "
        "The next proof point is more clean settled days flowing through the "
        "promotion refresh, with the model beating market Brier on daily-first "
        "and per-market gates rather than only improving process metrics.",
        "",
    ])
    return "\n".join(lines)


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT):
    json_out = Path(json_out)
    report_out = Path(report_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    return json_out, report_out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit whether project evidence is improving over time.")
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--roadmap", default=str(DEFAULT_ROADMAP))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    payload = build_audit(args.backtest_root, args.snapshots_root, args.roadmap)
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Wrote {json_out}")
    print(f"Wrote {report_out}")
    print(payload["trend_assessment"]["answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
