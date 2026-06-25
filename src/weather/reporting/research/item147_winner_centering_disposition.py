"""Disposition report for the Item 147 early-hour winner-centering candidate."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("item147_winner_centering_disposition")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_REPLAY = DEFAULT_BACKTEST_ROOT / "item147_time_split_alpha_replay.json"
DEFAULT_HOURLY = DEFAULT_BACKTEST_ROOT / "item147_time_split_alpha_hourly_candidate_performance.json"
DEFAULT_EXACT_DISTANCE = DEFAULT_BACKTEST_ROOT / "item147_time_split_alpha_exact_band_distance_zero_calibration.json"
DEFAULT_MARKET_REPAIR = DEFAULT_BACKTEST_ROOT / "market_residual_repair_program.json"
DEFAULT_POSITIVE_DAILY_FIRST = DEFAULT_BACKTEST_ROOT / "early_hour_positive_daily_first_gate.json"
DEFAULT_NO_GO = DEFAULT_BACKTEST_ROOT / "item147_blocked_markets_variant_basket_no_go.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item147_winner_centering_disposition.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item147_winner_centering_disposition_report.md"
DEFAULT_MARKET_TOL = 0.003


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _passes(value: Any) -> bool:
    return str(value or "").upper() in {"PASS", "READY", "ALLOW", "ALLOWED"}


def _first_blocker(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    first = payload.get("first_blocker") or {}
    if isinstance(first, dict) and first.get("detail"):
        return str(first.get("detail"))
    blockers = payload.get("blockers") or []
    if blockers and isinstance(blockers[0], dict):
        return str(blockers[0].get("detail") or blockers[0].get("gate") or blockers[0].get("category") or "")
    return ""


def _gate(name: str, status: str, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "gate": name,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


def replay_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    aggregate = (payload or {}).get("aggregate") or {}
    daily = (payload or {}).get("daily_first") or {}
    shadow = (payload or {}).get("candidate_shadow_variants") or {}
    blocked_markets = []
    shadow_markets = []
    promote_markets = []
    for row in (payload or {}).get("market_rows") or []:
        verdict = row.get("verdict")
        market = row.get("market_id")
        if verdict == "PASS":
            promote_markets.append(market)
        elif verdict == "SHADOW":
            shadow_markets.append(market)
        elif market:
            blocked_markets.append(market)
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at": (payload or {}).get("generated_at"),
        "verdict": (payload or {}).get("verdict"),
        "candidate_market_verdict": (payload or {}).get("candidate_market_verdict"),
        "cutover_decision": (payload or {}).get("cutover_decision"),
        "uses_market_features": shadow.get("uses_market_features"),
        "variant_id": shadow.get("variant_id"),
        "aggregate_delta_vs_current": aggregate.get("delta_vs_current"),
        "aggregate_delta_vs_market": aggregate.get("delta_vs_market"),
        "daily_first_delta_vs_current": daily.get("delta_vs_current"),
        "daily_first_delta_vs_market": daily.get("delta_vs_market"),
        "promote_markets": sorted(m for m in promote_markets if m),
        "shadow_markets": sorted(m for m in shadow_markets if m),
        "blocked_markets": sorted(set(m for m in blocked_markets if m)),
    }


def hourly_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    gate = (payload or {}).get("candidate_hourly_gate") or {}
    early = gate.get("early_morning") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": gate.get("status"),
        "blocker_count": gate.get("blocker_count", len(gate.get("blockers") or [])),
        "first_blocker": _first_blocker(gate),
        "delta_vs_current": early.get("delta_vs_current"),
        "delta_vs_market": early.get("delta_vs_market"),
        "logloss_delta_vs_market": early.get("logloss_delta_vs_market"),
        "winner_variant_probability": early.get("winner_variant_probability"),
        "winner_market_probability": early.get("winner_market_probability"),
    }


def simple_gate_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": (payload or {}).get("status"),
        "blocker_count": (payload or {}).get("blocker_count", len((payload or {}).get("blockers") or [])),
        "first_blocker": _first_blocker(payload),
        "summary": (payload or {}).get("summary") or {},
    }


def no_go_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "status": (payload or {}).get("status"),
        "blocked_market_count": (payload or {}).get("blocked_market_count"),
        "blocked_markets": (payload or {}).get("blocked_markets") or [],
        "next_action": (payload or {}).get("next_action"),
    }


def build_gates(
    *,
    replay: dict[str, Any],
    hourly: dict[str, Any],
    exact_distance: dict[str, Any],
    market_repair: dict[str, Any],
    positive_daily_first: dict[str, Any],
    no_go: dict[str, Any],
    market_tol: float,
) -> list[dict[str, Any]]:
    gates = []
    gates.append(_gate(
        "early_hour_candidate_gate",
        "PASS" if _passes(hourly.get("status")) else "BLOCK",
        (
            "item147 candidate hourly early gate passed"
            if _passes(hourly.get("status"))
            else hourly.get("first_blocker") or "item147 candidate hourly early gate is not clear"
        ),
        hourly,
    ))
    daily_gap = _safe_float(replay.get("daily_first_delta_vs_market"))
    gates.append(_gate(
        "aggregate_daily_first_market_tolerance",
        "PASS" if daily_gap is not None and daily_gap <= market_tol else "BLOCK",
        (
            f"daily-first market gap {daily_gap:+.4f} <= {market_tol:.4f}"
            if daily_gap is not None and daily_gap <= market_tol
            else f"daily-first market gap {daily_gap if daily_gap is not None else 'missing'} exceeds tolerance"
        ),
        replay,
    ))
    blocked = replay.get("blocked_markets") or []
    gates.append(_gate(
        "per_market_promotion_gate",
        "PASS" if not blocked and replay.get("cutover_decision") != "PER_MARKET_ONLY" else "BLOCK",
        (
            "all markets are promotion-ready"
            if not blocked and replay.get("cutover_decision") != "PER_MARKET_ONLY"
            else "blocked markets remain: " + ", ".join(blocked or ["per-market-only cutover"])
        ),
        replay,
    ))
    gates.append(_gate(
        "exact_band_distance_zero_gate",
        "PASS" if _passes(exact_distance.get("status")) else "BLOCK",
        (
            "item147 exact-band and settlement-distance gate passed"
            if _passes(exact_distance.get("status"))
            else exact_distance.get("first_blocker") or "item147 exact-band/distance gate is not clear"
        ),
        exact_distance,
    ))
    gates.append(_gate(
        "market_residual_repair_gate",
        "PASS" if _passes(market_repair.get("status")) else "BLOCK",
        (
            "market residual repair program passed"
            if _passes(market_repair.get("status"))
            else f"market residual repair program is {market_repair.get('status') or 'missing'}"
        ),
        market_repair,
    ))
    gates.append(_gate(
        "positive_daily_first_gate",
        "PASS" if _passes(positive_daily_first.get("status")) and positive_daily_first.get("summary", {}).get("acceptance_passed") is not False else "BLOCK",
        (
            "positive daily-first gate passed"
            if _passes(positive_daily_first.get("status"))
            else positive_daily_first.get("first_blocker") or "positive daily-first gate is not clear"
        ),
        positive_daily_first,
    ))
    gates.append(_gate(
        "blocked_variant_basket_no_go",
        "PASS" if no_go.get("status") == "NO_GO" else "BLOCK",
        (
            "existing blocked-market variant basket is registered as no-go"
            if no_go.get("status") == "NO_GO"
            else "blocked-market no-go disposition is missing"
        ),
        no_go,
    ))
    gates.append(_gate(
        "lane_separation",
        "PASS" if replay.get("uses_market_features") is False else "BLOCK",
        (
            "item147 remains no-market weather-model evidence"
            if replay.get("uses_market_features") is False
            else "item147 replay uses market features or lacks lane metadata"
        ),
        replay,
    ))
    return gates


def build_payload(
    *,
    replay: str | Path = DEFAULT_REPLAY,
    hourly: str | Path = DEFAULT_HOURLY,
    exact_distance: str | Path = DEFAULT_EXACT_DISTANCE,
    market_repair: str | Path = DEFAULT_MARKET_REPAIR,
    positive_daily_first: str | Path = DEFAULT_POSITIVE_DAILY_FIRST,
    no_go: str | Path = DEFAULT_NO_GO,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    replay_payload = replay_summary(replay)
    hourly_payload = hourly_summary(hourly)
    exact_payload = simple_gate_summary(exact_distance)
    repair_payload = simple_gate_summary(market_repair)
    positive_payload = simple_gate_summary(positive_daily_first)
    no_go_payload = no_go_summary(no_go)
    gates = build_gates(
        replay=replay_payload,
        hourly=hourly_payload,
        exact_distance=exact_payload,
        market_repair=repair_payload,
        positive_daily_first=positive_payload,
        no_go=no_go_payload,
        market_tol=market_tol,
    )
    blockers = [gate for gate in gates if gate.get("status") == "BLOCK"]
    disposition = "KEEP_SHADOW_DIAGNOSTIC" if blockers else "PROMOTION_READY"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "disposition": disposition,
        "promotion_allowed": not blockers,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "inputs": {
            "replay": str(replay),
            "hourly": str(hourly),
            "exact_distance": str(exact_distance),
            "market_repair": str(market_repair),
            "positive_daily_first": str(positive_daily_first),
            "no_go": str(no_go),
        },
        "replay": replay_payload,
        "candidate_hourly": hourly_payload,
        "exact_band_distance_zero": exact_payload,
        "market_residual_repair": repair_payload,
        "positive_daily_first": positive_payload,
        "blocked_variant_basket_no_go": no_go_payload,
        "gates": gates,
        "blockers": blockers,
        "next_action": (
            "Do not rerun broad Item 147 forecast-centering. Keep it as the diagnostic early-hour baseline "
            "and move remaining work into active served-distribution and market-specific residual repair gates."
        ),
    }


def render_report(payload: dict[str, Any]) -> str:
    first = payload.get("first_blocker") or {}
    replay = payload.get("replay") or {}
    hourly = payload.get("candidate_hourly") or {}
    lines = [
        "# Item 147 Winner-Centering Disposition",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", payload.get("status")],
            ["Disposition", payload.get("disposition")],
            ["Promotion allowed", payload.get("promotion_allowed")],
            ["Blockers", payload.get("blocker_count")],
            ["First blocker", first.get("detail") or "-"],
            ["Replay verdict", replay.get("verdict")],
            ["Cutover decision", replay.get("cutover_decision")],
            ["Daily-first delta vs current", fmt_num(replay.get("daily_first_delta_vs_current"))],
            ["Daily-first delta vs market", fmt_num(replay.get("daily_first_delta_vs_market"))],
            ["Blocked markets", ", ".join(replay.get("blocked_markets") or []) or "-"],
            ["Candidate hourly status", hourly.get("status")],
            ["Early-hour delta vs market", fmt_num(hourly.get("delta_vs_market"))],
            ["Early winner candidate/market", f"{fmt_num(hourly.get('winner_variant_probability'))} / {fmt_num(hourly.get('winner_market_probability'))}"],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
    )
    lines += ["", "## Next Action", "", payload.get("next_action") or "-"]
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_OUT,
    report_out: str | Path = DEFAULT_REPORT,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Item 147 winner-centering candidate disposition.")
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY))
    parser.add_argument("--hourly", default=str(DEFAULT_HOURLY))
    parser.add_argument("--exact-distance", default=str(DEFAULT_EXACT_DISTANCE))
    parser.add_argument("--market-repair", default=str(DEFAULT_MARKET_REPAIR))
    parser.add_argument("--positive-daily-first", default=str(DEFAULT_POSITIVE_DAILY_FIRST))
    parser.add_argument("--no-go", default=str(DEFAULT_NO_GO))
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        replay=args.replay,
        hourly=args.hourly,
        exact_distance=args.exact_distance,
        market_repair=args.market_repair,
        positive_daily_first=args.positive_daily_first,
        no_go=args.no_go,
        market_tol=args.market_tol,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Item 147 winner-centering disposition: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
