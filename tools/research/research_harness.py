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
    "model_market_disagreement_analysis.py": {
        "status": "retired",
        "smoke": "compile_main_guard",
        "notes": "Compatibility wrapper; use weather.reporting.candidate_lifecycle.model_market_disagreement_analysis.",
    },
    "model_market_disagreement_audit.py": {
        "status": "retired",
        "smoke": "compile_main_guard",
        "notes": "Compatibility wrapper; use weather.reporting.candidate_lifecycle.model_market_disagreement_audit.",
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
    # Campaign mission scripts, kept as one block rather than scattered alphabetically so the
    # class is reviewable. Each is the executable evidence for one numbered mission and must not
    # be edited after its finding is accepted -- re-run it to reproduce, do not repurpose it.
    #
    # These went missing from the inventory because the 05:15 roll-free merge driver lands
    # branches without running the suite: on 2026-08-11 it merged six of these in forty minutes
    # and left master red from 05:55 until this was noticed. See the Codex audit 8.2.
    "b_only_screen_09_63a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-63a B-only integrity screen for decision 10; NO-GO at Gate 3, alpha unspent.",
    },
    "build_pit_feature_extract_09_61a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-61a frozen 12-field PIT feature extract; reproduces SHA-256 60b450f1.",
    },
    "interval_coverage_09_62a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-62a true-zero coverage simulation; produced amendment A1 (q=3.1098893).",
    },
    "audit_repaired_realized_band_zeros_09_64a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-64a repaired-vs-control realized band zeros; precise null, identical row-for-row.",
    },
    "build_pit_panel_floor_extract_09_65a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-65a panel floor extract; traced the Denver zero to a replay floor never served.",
    },
    "rescore_served_floor_09_66a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-66a rescore of B on the served floor rather than the replay floor.",
    },
    "audit_outcome_label_provenance_09_67a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-67a outcome-label provenance audit; FLAT, cite the ~13% ceiling not 1.5069%.",
    },
    "analyze_gate_3_satisfiability_09_68a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-68a Gate 3 satisfiability; a fail-on-any-row gate is a panel-size limit.",
    },
    "measure_high_so_far_population_09_70a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-70a/-09-71a high-so-far population and cutoff-direction evidence.",
    },
    "measure_observation_envelope_09_72a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-72a observation-envelope measurement for the recovery candidate.",
    },
    "measure_safe_observation_recovery_09_73a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-73a predeclared safe observation-recovery rule measurement.",
    },
    "measure_repair_ceiling_09_74a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-74a upper-bound measurement for the observation repair candidate.",
    },
    "measure_replay_trust_09_75a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-75a replay-trust audit for the candidate evaluation surface.",
    },
    "measure_identity_binding_09_76a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-76a runtime identity-binding reconstruction and audit.",
    },
    "measure_single_environment_repair_ceiling_09_77a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-77a single-environment repair-ceiling measurement.",
    },
    "measure_estimand_power_and_sign_09_78a.py": {
        "status": "fixture-only",
        "smoke": "compile_main_guard",
        "notes": "-09-78a estimand power and sign analysis; candidate closed unpowered.",
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
