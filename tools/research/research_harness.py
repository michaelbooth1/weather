"""Manifest-backed harness for research audit scripts."""

from __future__ import annotations

import argparse
import py_compile
import subprocess
import sys
from pathlib import Path


VALID_STATUSES = {"supported", "fixture-only", "retired"}
SCRIPT_INVENTORY = {
    "analyze_boundaries.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "Historical Toronto boundary analysis over local archived WU rows.",
    },
    "analyze_late_day.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "Historical Toronto late-day analysis over local archived WU rows.",
    },
    "audit_band.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Live Toronto one-off; use snapshot evaluation or disagreement casebook.",
    },
    "audit_data.py": {
        "status": "fixture-only",
        "smoke": "compile",
        "notes": "Local data-count summary; no live model claim.",
    },
    "audit_lowend.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Live Toronto one-off; stale source-field assumptions.",
    },
    "audit_responsiveness.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Live Toronto one-off; superseded by observation trigger replay.",
    },
    "audit_toronto.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Live Toronto one-off; use canonical reporting modules.",
    },
    "check_chicago_history.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Ad-hoc Chicago history probe with stale unit assumptions.",
    },
    "chicago_audit.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Retired broken live Chicago audit; no current diagnostic authority.",
    },
    "decompose_1314.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "Pinned local replay slice decomposition for a historical Toronto case.",
    },
    "fix_app.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Obsolete local app patch helper.",
    },
    "full_audit.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Live all-market probe; use promotion refresh and fleet reports.",
    },
    "inspect_data.py": {
        "status": "fixture-only",
        "smoke": "compile",
        "notes": "Local schema inspection of archived files.",
    },
    "input_variable_significance.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "Historical local input-importance audit; durable outputs feed items 134-138.",
    },
    "nyc_audit.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Retired broken live NYC audit; no current diagnostic authority.",
    },
    "project_high.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "Historical local projection analysis.",
    },
    "research_harness.py": {
        "status": "supported",
        "smoke": "help",
        "notes": "Maintained manifest, validation, and smoke runner for this directory.",
    },
    "run_live_model.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Live default-market one-off; use package CLIs or dashboard.",
    },
    "summary.py": {
        "status": "fixture-only",
        "smoke": "compile",
        "notes": "Local historical backfill queue summary.",
    },
    "ten_minute_performance_audit.py": {
        "status": "retired",
        "smoke": "compile_main_guard",
        "notes": "Compatibility wrapper; use weather.reporting.hourly.ten_minute_model_performance.",
    },
    "retired_analogs_live.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Live default-market one-off; analog diagnostics moved to model reports.",
    },
    "retired_continuation.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Live continuation one-off; use late-day continuation report.",
    },
    "retired_feature_model_live.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Live default-market one-off; use promotion gauntlet/replay.",
    },
    "retired_freshness.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Live source freshness one-off; use fleet observability.",
    },
    "train_all.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Obsolete bulk training wrapper; use nightly retrain/daily refresh.",
    },
    "train_all2.py": {
        "status": "retired",
        "smoke": "help",
        "notes": "Obsolete bulk training wrapper; use nightly retrain/daily refresh.",
    },
}


def research_dir():
    return Path(__file__).resolve().parent


def research_scripts(root=None):
    root = Path(root) if root else research_dir()
    return sorted(path.name for path in root.glob("*.py"))


def validate_inventory(root=None):
    root = Path(root) if root else research_dir()
    scripts = set(research_scripts(root))
    inventory = set(SCRIPT_INVENTORY)
    errors = []
    missing = sorted(scripts - inventory)
    extra = sorted(inventory - scripts)
    if missing:
        errors.append(f"missing inventory rows: {', '.join(missing)}")
    if extra:
        errors.append(f"inventory rows without files: {', '.join(extra)}")
    for name, meta in sorted(SCRIPT_INVENTORY.items()):
        status = meta.get("status")
        if status not in VALID_STATUSES:
            errors.append(f"{name}: invalid status {status!r}")
        if status == "supported" and meta.get("smoke") != "help":
            errors.append(f"{name}: supported scripts must expose --help smoke")
        if not meta.get("notes"):
            errors.append(f"{name}: missing notes")
    return errors


def _has_main_guard(path):
    return 'if __name__ == "__main__"' in path.read_text(encoding="utf-8")


def smoke_script(path, smoke):
    path = Path(path)
    if smoke in {"compile", "compile_main_guard"}:
        py_compile.compile(str(path), doraise=True)
        if smoke == "compile_main_guard" and not _has_main_guard(path):
            raise AssertionError(f"{path} is missing a main guard")
        return {"script": path.name, "smoke": smoke, "ok": True}
    if smoke == "help":
        result = subprocess.run(
            [sys.executable, str(path), "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(f"{path} --help failed: {result.stderr or result.stdout}")
        return {"script": path.name, "smoke": smoke, "ok": True}
    raise ValueError(f"unknown smoke mode {smoke!r}")


def smoke_inventory(root=None, statuses=("supported",)):
    root = Path(root) if root else research_dir()
    selected = []
    for name, meta in sorted(SCRIPT_INVENTORY.items()):
        if meta.get("status") not in set(statuses):
            continue
        selected.append(smoke_script(root / name, meta.get("smoke") or "compile"))
    return selected


def retired_main(script_name):
    meta = SCRIPT_INVENTORY.get(Path(script_name).name) or {}
    replacement = meta.get("notes") or "Use maintained weather.reporting and weather.operations entrypoints."
    print(f"{Path(script_name).name} is retired. {replacement}")
    return 2


def retired_stub_main(script_name, argv=None, description=None):
    parser = argparse.ArgumentParser(description=description or f"Retired {Path(script_name).name}.")
    parser.parse_args(argv)
    return retired_main(script_name)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate and smoke-test tools/research scripts.")
    parser.add_argument("--list", action="store_true", help="Print script classification inventory.")
    parser.add_argument("--validate", action="store_true", help="Validate the script inventory.")
    parser.add_argument("--smoke", action="store_true", help="Run network-free smoke checks for supported scripts.")
    parser.add_argument(
        "--include-fixtures",
        action="store_true",
        help="Also compile fixture-only scripts during --smoke.",
    )
    args = parser.parse_args(argv)

    if args.list:
        for name, meta in sorted(SCRIPT_INVENTORY.items()):
            print(f"{name}\t{meta['status']}\t{meta.get('smoke', '-')}\t{meta.get('notes', '')}")
    if args.validate:
        errors = validate_inventory()
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print("research inventory OK")
    if args.smoke:
        statuses = ("supported", "fixture-only") if args.include_fixtures else ("supported",)
        results = smoke_inventory(statuses=statuses)
        for result in results:
            print(f"OK {result['script']} [{result['smoke']}]")
    if not (args.list or args.validate or args.smoke):
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
