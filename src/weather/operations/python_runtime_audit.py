"""Focused Python runtime regression gate for roadmap item 313."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from weather.io import write_json_atomic
from weather.operations import daily_refresh_steps
from weather.operations import daily_roll_log_hygiene
from weather.operations.daily_refresh_cli import _DEPENDENCY_NAMES as DAILY_REFRESH_CLI_DEPENDENCY_NAMES
from weather.paths import REPO_ROOT, data_path, docs_path
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("python_runtime_audit")
BASELINE_SCHEMA_VERSION = "python_runtime_audit_baseline_v0.1"
DEFAULT_JSON_OUT = data_path("backtest", "python_runtime_audit.json")
DEFAULT_BASELINE_PATH = docs_path("operations", "python-runtime-audit-baseline.json")
RUFF_RULES = ("F821", "F822", "F823", "F811", "F841", "E9", "B012")
DEFAULT_RUFF_TARGETS = (
    "app",
    "src/weather",
    "tests",
    "tools",
    "scripts",
    "weather",
)
RUFF_EXCLUDES = ("venv", "artifacts", "data")
DAILY_REFRESH_SMOKE_STEPS = {
    "reanalysis_recent_refresh": ("utc_now", "ReanalysisClient", "ReanalysisStore", "all_specs"),
    "event_metadata_validation": ("utc_now", "event_metadata_validation"),
}
DEFAULT_SIGNATURE_ROUTES = (
    {
        "loop": "streamlit",
        "category": "console_error",
        "pattern": r"Traceback \(most recent call last\):",
        "roadmap_owner": "item 313",
        "disposition": "traceback_envelope",
        "detail": "Streamlit traceback envelope; final exception signature is routed separately.",
    },
    {
        "loop": "maker",
        "category": "console_error",
        "pattern": r"Traceback \(most recent call last\):",
        "roadmap_owner": "item 306",
        "disposition": "traceback_envelope",
        "detail": "Maker console traceback envelope; final exception signature is routed separately.",
    },
    {
        "loop": "taker",
        "category": "console_error",
        "pattern": r"Traceback \(most recent call last\):",
        "roadmap_owner": "item 306",
        "disposition": "traceback_envelope",
        "detail": "Taker console traceback envelope; final exception signature is routed separately.",
    },
    {
        "loop": "streamlit",
        "category": "console_error",
        "pattern": r"UnboundLocalError: cannot access local variable 'pd'",
        "roadmap_owner": "item 313",
        "disposition": "known_dashboard_regression",
        "detail": "Single-market dashboard pandas local-shadowing regression.",
    },
    {
        "loop": "maker",
        "category": "encoding_error",
        "pattern": r"codec can't decode byte",
        "roadmap_owner": "item 306",
        "disposition": "historical_console_noise",
        "detail": "Historical maker console encoding traceback; current-window health is handled by structured daily-roll status.",
    },
    {
        "loop": "maker",
        "category": "blocked_by_disk",
        "pattern": r"No space left on device",
        "roadmap_owner": "item 306",
        "disposition": "historical_console_noise",
        "detail": "Historical maker console disk-full traceback; current-window health is handled by structured daily-roll status.",
    },
    {
        "loop": "taker",
        "category": "blocked_by_disk",
        "pattern": r"No space left on device",
        "roadmap_owner": "item 306",
        "disposition": "historical_console_noise",
        "detail": "Historical taker console disk-full traceback; current-window health is handled by structured daily-roll status.",
    },
)
BACKTICK_RE = re.compile(r"`([^`]+)`")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_relative(path: str | Path) -> str:
    candidate = Path(path)
    try:
        candidate = candidate.resolve()
        return candidate.relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path).replace("\\", "/")


def _finding_key(finding: dict[str, Any]) -> tuple[str, str, str]:
    normalized = normalize_ruff_finding(finding)
    return (
        str(normalized.get("path") or ""),
        str(normalized.get("code") or ""),
        str(normalized.get("symbol") or ""),
    )


def load_baseline(path: str | Path = DEFAULT_BASELINE_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {
            "schema_version": BASELINE_SCHEMA_VERSION,
            "ruff_baseline": [],
            "log_signature_routes": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def ruff_baseline_entries(*, baseline_path: str | Path = DEFAULT_BASELINE_PATH) -> list[dict[str, Any]]:
    entries = []
    payload = load_baseline(baseline_path)
    for raw in payload.get("ruff_baseline") or []:
        symbols = list(raw.get("symbols") or [])
        if not symbols:
            entries.append(dict(raw))
            continue
        for symbol in symbols:
            entries.append(
                {
                    **raw,
                    "symbol": symbol,
                    "symbols": [symbol],
                }
            )
    for name in sorted(DAILY_REFRESH_CLI_DEPENDENCY_NAMES):
        entries.append(
            {
                "path": "src/weather/operations/daily_refresh_cli.py",
                "code": "F821",
                "symbol": name,
                "message": f"Undefined name `{name}`",
                "owner": "item 313",
                "disposition": "dependency_injected_cli_global",
                "reason": "daily_refresh_cli.configure() validates and injects this facade dependency before CLI parser use.",
            }
        )
    return entries


def _baseline_map(entries: list[dict[str, Any]] | None = None) -> dict[tuple[str, str, str], dict[str, Any]]:
    baseline = entries if entries is not None else ruff_baseline_entries()
    return {
        (str(entry["path"]), str(entry["code"]), str(entry.get("symbol") or "")): dict(entry)
        for entry in baseline
    }


def normalize_ruff_finding(finding: dict[str, Any]) -> dict[str, Any]:
    location = finding.get("location") or {}
    end_location = finding.get("end_location") or {}
    symbols = BACKTICK_RE.findall(str(finding.get("message") or ""))
    return {
        "path": _repo_relative(finding.get("filename") or ""),
        "code": finding.get("code"),
        "symbol": symbols[0] if symbols else "",
        "message": finding.get("message"),
        "row": location.get("row"),
        "column": location.get("column"),
        "end_row": end_location.get("row"),
        "end_column": end_location.get("column"),
    }


def classify_ruff_findings(
    findings: list[dict[str, Any]],
    *,
    baseline_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    baseline = _baseline_map(baseline_entries)
    baselined = []
    unowned = []
    for raw in findings:
        normalized = normalize_ruff_finding(raw)
        key = _finding_key(raw)
        owner = baseline.get(key)
        if owner:
            normalized["baseline"] = owner
            baselined.append(normalized)
        else:
            unowned.append(normalized)
    return {
        "status": "PASS" if not unowned else "BLOCK",
        "finding_count": len(findings),
        "baselined_count": len(baselined),
        "unowned_count": len(unowned),
        "baselined_findings": baselined,
        "unowned_findings": unowned,
        "baseline_count": len(baseline),
    }


def run_ruff_audit(
    *,
    targets: list[str] | tuple[str, ...] | None = None,
    python_executable: str | None = None,
    baseline_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target_args = list(targets or DEFAULT_RUFF_TARGETS)
    command = [
        python_executable or sys.executable,
        "-m",
        "ruff",
        "check",
        *target_args,
        "--select",
        ",".join(RUFF_RULES),
        "--output-format=json",
    ]
    for excluded in RUFF_EXCLUDES:
        command.extend(["--exclude", excluded])
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        return {
            "status": "ERROR",
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "finding_count": 0,
            "baselined_count": 0,
            "unowned_count": 0,
            "unowned_findings": [],
            "baselined_findings": [],
        }
    try:
        findings = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        return {
            "status": "ERROR",
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": f"{result.stderr}\nJSON parse error: {exc}",
            "finding_count": 0,
            "baselined_count": 0,
            "unowned_count": 0,
            "unowned_findings": [],
            "baselined_findings": [],
        }
    classified = classify_ruff_findings(findings, baseline_entries=baseline_entries)
    return {
        **classified,
        "command": command,
        "returncode": result.returncode,
        "targets": target_args,
        "rules": list(RUFF_RULES),
    }


def daily_refresh_step_smoke() -> dict[str, Any]:
    runner_map = {name: runner for name, runner in daily_refresh_steps.DEFAULT_RUNNERS}
    rows = []
    for step_name, required_globals in DAILY_REFRESH_SMOKE_STEPS.items():
        runner = runner_map.get(step_name)
        missing_globals = []
        if runner is None:
            status = "BLOCK"
        else:
            missing_globals = [
                name for name in required_globals if name not in getattr(runner, "__globals__", {})
            ]
            status = "PASS" if not missing_globals else "BLOCK"
        rows.append(
            {
                "step": step_name,
                "registered": runner is not None,
                "runner": getattr(runner, "__name__", None),
                "required_globals": list(required_globals),
                "missing_globals": missing_globals,
                "status": status,
            }
        )
    blockers = [row for row in rows if row["status"] != "PASS"]
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "checked_step_count": len(rows),
        "blocker_count": len(blockers),
        "steps": rows,
        "blockers": blockers,
    }


def _write_streamlit_smoke_snapshot(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "snapshot_id,captured_at_local,range_label,model_probability,market_yes,edge,top_temp_c,top_probability",
                "s1,2026-06-24T12:00:00,70 F,0.60,0.50,0.10,70,0.60",
                "s2,2026-06-24T12:10:00,70 F,0.62,0.50,0.12,70,0.62",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _streamlit_smoke_classes(snapshot_csv: Path):
    class SmokeSnapshotStore:
        def __init__(self, event_slug: str | None = None):
            self.event_slug = event_slug
            self.long_path = snapshot_csv
            self.wide_path = snapshot_csv.parent / "snapshots_wide.csv"
            self.forecasts_long_path = snapshot_csv.parent / "forecasts_long.csv"
            self.jsonl_path = snapshot_csv.parent / "snapshots.jsonl"

        def maybe_write(self, *_args, **_kwargs):
            return {"written": False, "status": "not_due", "next_due_at": "smoke"}

    class SmokePolymarketClient:
        def __init__(self, market_id: str | None = None):
            self.market_id = market_id

        def get_event(self):
            return {
                "active": True,
                "liquidity": 1000,
                "volume": 2000,
                "openInterest": 300,
                "updatedAt": "2026-06-24T12:00:00Z",
                "slug": "highest-temperature-in-nyc-on-june-24",
                "title": "Smoke NYC high temperature market",
                "description": "Smoke route fixture.",
                "resolutionSource": "",
            }

        def event_market_rows(self, _event):
            return [{"Range": "70 F", "Yes": "50.0%", "No": "50.0%"}]

    class SmokeModel:
        target_date = date(2026, 6, 24)

        def __init__(self, market_id: str | None = None):
            self.market_id = market_id

        def clear_historical_cache(self):
            return None

        def fetch_historical_sources(self):
            return {}

        def fetch_live_sources(self):
            return {}

        def source_cache_ttl_minutes(self, _name):
            return 5

        def market_bins(self, _event):
            return [{"label": "70 F", "market_yes": 0.50}]

        def bin_probability(self, distribution, bin_data):
            return float(distribution.get(70) or bin_data.get("market_yes") or 0.0)

        def build(self, _event, historical_sources=None, live_sources=None):
            return {
                "sources": {
                    "wu_current": {
                        "ok": True,
                        "stale": False,
                        "fetched_at": "2026-06-24T12:00:00-04:00",
                    }
                },
                "source_rows": [{"Source": "Smoke", "Status": "Live"}],
                "forecast_rows": [],
                "top_temp": 70,
                "distribution": {70: 0.60},
                "model_version": "route-smoke",
                "model_rows": [{"Range": "70 F", "Probability": "60.0%"}],
                "deep_dive_rows": [{"Metric": "Smoke", "Value": "ok"}],
                "notes": ["Route smoke fixture"],
                "analog_search": None,
            }

    return SmokeSnapshotStore, SmokePolymarketClient, SmokeModel


def streamlit_route_smoke() -> dict[str, Any]:
    try:
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        import app.views.single_market as single_market
    except Exception as exc:  # noqa: BLE001 - audit should report missing optional test surface
        return {
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "route": "single_market",
        }

    with tempfile.TemporaryDirectory() as tmp:
        snapshot_csv = Path(tmp) / "snapshots_long.csv"
        _write_streamlit_smoke_snapshot(snapshot_csv)
        store_cls, client_cls, model_cls = _streamlit_smoke_classes(snapshot_csv)
        st.cache_data.clear()
        st.cache_resource.clear()
        with (
            patch.object(single_market, "SnapshotStore", store_cls),
            patch.object(single_market, "PolymarketClient", client_cls),
            patch.object(single_market, "TorontoHighTempModel", model_cls),
            patch(
                "weather.reporting.location_trust.score_market",
                lambda _market_id: {
                    "trust_score": 100,
                    "grade": "Strong",
                    "settled_days": 1,
                    "model_ece": 0.0,
                    "rationale": "Route smoke fixture.",
                },
            ),
        ):
            app_test = AppTest.from_file(str(REPO_ROOT / "app" / "streamlit_app.py"))
            app_test.query_params["market"] = "nyc"
            app_test.run()
            exceptions = [str(item) for item in app_test.exception]
    return {
        "status": "PASS" if not exceptions else "BLOCK",
        "route": "single_market",
        "query_params": {"market": "nyc"},
        "exception_count": len(exceptions),
        "exceptions": exceptions,
    }


def _route_for_signature(
    signature: dict[str, Any],
    routes: tuple[dict[str, str], ...] | list[dict[str, str]] = DEFAULT_SIGNATURE_ROUTES,
) -> dict[str, Any] | None:
    loop = str(signature.get("loop") or "")
    category = str(signature.get("category") or "")
    message = str(signature.get("normalized_message") or signature.get("detail") or "")
    for route in routes:
        if route.get("loop") and route["loop"] != loop:
            continue
        if route.get("category") and route["category"] != category:
            continue
        if re.search(route.get("pattern") or "", message):
            return dict(route)
    return None


def signature_routes(*, baseline_path: str | Path = DEFAULT_BASELINE_PATH) -> list[dict[str, Any]]:
    return list(load_baseline(baseline_path).get("log_signature_routes") or DEFAULT_SIGNATURE_ROUTES)


def _is_python_runtime_signature(signature: dict[str, Any]) -> bool:
    message = str(signature.get("normalized_message") or signature.get("detail") or "").strip()
    lowered = message.casefold()
    if message.startswith("{") and "traceback" not in lowered:
        return False
    return any(
        token in lowered
        for token in (
            "traceback (most recent call last)",
            "error:",
            "exception:",
            "unboundlocalerror",
            "unicodedecodeerror",
            "oserror",
            "nameerror",
            "modulenotfounderror",
            "importerror",
        )
    )


def log_signature_audit(
    *,
    log_sources: dict[str, str | Path] | None = None,
    incidents_path: str | Path | None = None,
    current_window_hours: float = daily_roll_log_hygiene.DEFAULT_CURRENT_WINDOW_HOURS,
    as_of: str | datetime | None = None,
    routes: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    log_payload = daily_roll_log_hygiene.build_payload(
        log_sources=log_sources,
        incidents_path=incidents_path or data_path("backtest", "python_runtime_log_incidents.jsonl"),
        current_window_hours=current_window_hours,
        as_of=as_of,
    )
    routed = []
    unowned = []
    signature_groups = [
        signature
        for signature in log_payload.get("current_signature_groups") or []
        if _is_python_runtime_signature(signature)
    ]
    for signature in signature_groups:
        route = _route_for_signature(signature, routes or signature_routes())
        row = {**signature, "route": route}
        if route:
            routed.append(row)
        else:
            unowned.append(row)
    return {
        "status": "PASS" if not unowned else "BLOCK",
        "runtime_log_status": log_payload.get("status"),
        "current_signature_count": len(signature_groups),
        "ignored_structured_status_count": max(
            0,
            len(log_payload.get("current_signature_groups") or []) - len(signature_groups),
        ),
        "routed_signature_count": len(routed),
        "unowned_signature_count": len(unowned),
        "routed_signatures": routed,
        "unowned_signatures": unowned,
        "log_summary": log_payload.get("summary") or {},
        "current_window": log_payload.get("current_window") or {},
        "sources": log_payload.get("sources") or [],
    }


def build_payload(
    *,
    ruff_targets: list[str] | tuple[str, ...] | None = None,
    python_executable: str | None = None,
    log_sources: dict[str, str | Path] | None = None,
    log_incidents_path: str | Path | None = None,
    log_window_hours: float = daily_roll_log_hygiene.DEFAULT_CURRENT_WINDOW_HOURS,
    as_of: str | datetime | None = None,
    include_ruff: bool = True,
    include_streamlit_route: bool = True,
    include_log_signatures: bool = True,
) -> dict[str, Any]:
    components = {}
    if include_ruff:
        components["ruff"] = run_ruff_audit(targets=ruff_targets, python_executable=python_executable)
    components["daily_refresh_step_smoke"] = daily_refresh_step_smoke()
    if include_streamlit_route:
        components["streamlit_route_smoke"] = streamlit_route_smoke()
    if include_log_signatures:
        components["log_signature_ownership"] = log_signature_audit(
            log_sources=log_sources,
            incidents_path=log_incidents_path,
            current_window_hours=log_window_hours,
            as_of=as_of,
        )
    blockers = {
        name: component
        for name, component in components.items()
        if component.get("status") != "PASS"
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "summary": {
            "component_count": len(components),
            "blocker_count": len(blockers),
            "blocked_components": sorted(blockers),
        },
        "components": components,
    }


def parse_log_sources(value: str | None) -> dict[str, Path]:
    return daily_roll_log_hygiene.parse_log_sources(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the focused Python runtime audit regression gate.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--as-of", default=None)
    parser.add_argument(
        "--log-window-hours",
        type=float,
        default=daily_roll_log_hygiene.DEFAULT_CURRENT_WINDOW_HOURS,
    )
    parser.add_argument("--log-sources", default="")
    parser.add_argument("--log-incidents", default="")
    parser.add_argument("--ruff-target", action="append", default=[])
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--skip-ruff", action="store_true")
    parser.add_argument("--skip-streamlit-route-smoke", action="store_true")
    parser.add_argument("--skip-log-signatures", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Exit 2 when any component blocks.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(
        ruff_targets=args.ruff_target or None,
        python_executable=args.python_executable,
        log_sources=parse_log_sources(args.log_sources),
        log_incidents_path=args.log_incidents or None,
        log_window_hours=args.log_window_hours,
        as_of=args.as_of,
        include_ruff=not args.skip_ruff,
        include_streamlit_route=not args.skip_streamlit_route_smoke,
        include_log_signatures=not args.skip_log_signatures,
    )
    out_path = write_json_atomic(args.json_out, payload, trailing_newline=True)
    print(f"Python runtime audit: {payload['status']}")
    print(f"Wrote {out_path}")
    if args.strict and payload["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
