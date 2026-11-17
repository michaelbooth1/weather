"""Unattended sealed snapshot writer. Neither stdout nor errors contain trial values."""

from __future__ import annotations

import argparse
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from weather.paths import repo_path

from .contracts import (CAPS, FREEZE_BEFORE, LOOK, UTC, canonical, digest, exact,
                        instant, iso, json_bytes, number, require, sha, timezone_fingerprint)
from .core import simulate
from .isolation import assert_no_order_path
from .pack import bounded_bytes, load_pack, safe_file
from .seal import read_public_key, seal_payload


def code_paths() -> list[Path]:
    root = Path(__file__).parent
    return sorted(root.glob("*.py")) + [repo_path(p) for p in (
        "src/weather/market/metar_reports.py", "src/weather/market/venue_settlement_rules.py",
        "src/weather/market/__init__.py", "src/weather/backtesting/__init__.py",
        "src/weather/__init__.py", "src/weather/paths.py", "sitecustomize.py", "weather/__init__.py")]


def code_hashes() -> dict:
    return {p.relative_to(repo_path()).as_posix(): digest(p.read_bytes()) for p in code_paths()}


def validate_freeze(freeze: dict, expected_sha: str, now: datetime) -> None:
    exact(freeze, "schema_version trial frozen_utc code_sha256 prereg_sha256 input_contract_sha256 producer_id reader_sha256 "
          "transform_sha256 timezone_sha256 timezone_version latency_receipt capital public_key_sha256 gates calibration claimants state_root")
    require(digest(canonical(freeze)) == sha(expected_sha), "freeze_hash")
    require(freeze["schema_version"] == "low_ask_freeze_v1", "freeze_schema")
    require(freeze["trial"] == "LOW-ASK-1", "freeze_trial")
    frozen = instant(freeze["frozen_utc"])
    require(frozen < FREEZE_BEFORE and frozen <= now, "freeze_deadline")
    require(freeze["code_sha256"] == code_hashes(), "code_binding")
    require(freeze["capital"] == CAPS, "capital_binding")
    require(freeze["reader_sha256"] == freeze["code_sha256"]["src/weather/backtesting/low_ask/pack.py"], "reader_code_binding")
    require(freeze["timezone_sha256"] == timezone_fingerprint(), "timezone_binding")
    require(isinstance(freeze["timezone_version"], str) and bool(freeze["timezone_version"]), "timezone_version")
    require(isinstance(freeze["state_root"], str) and Path(freeze["state_root"]).is_absolute(), "state_root")
    require(isinstance(freeze["claimants"], list) and 2 <= len(freeze["claimants"]) <= 4
            and len(freeze["claimants"]) == len(set(freeze["claimants"]))
            and "LOW-ASK-1" in freeze["claimants"] and "F3-SIM-1" in freeze["claimants"], "claimants")
    for key in ("prereg_sha256", "input_contract_sha256", "reader_sha256", "transform_sha256",
                "timezone_sha256", "public_key_sha256"):
        sha(freeze[key])
    require(digest(repo_path("docs/research/low-ask-1/PREREG_LOW_ASK_1.md").read_bytes()) == freeze["prereg_sha256"], "prereg_binding")
    require(digest(repo_path("docs/research/low-ask-1/INPUT_CONTRACT.md").read_bytes()) == freeze["input_contract_sha256"], "contract_binding")
    exact(freeze["gates"], "foundations_landed capture_verified scoped_pack_verified latency_verified "
          "authority_amendment claimant_scope_zero_exposure master_defaults_confirmed two_replays_match")
    require(all(value is True for value in freeze["gates"].values()), "freeze_prerequisites")
    exact(freeze["calibration"], "status receipt_sha256 critical_value power_lower")
    require(freeze["calibration"]["status"] in {"SCREEN_ONLY", "CALIBRATED"}, "calibration_status")
    if freeze["calibration"]["status"] == "CALIBRATED":
        sha(freeze["calibration"]["receipt_sha256"])
        require(number(freeze["calibration"]["critical_value"]) >= number("2.241402727604947")
                and number(freeze["calibration"]["power_lower"]) >= number("0.80"), "calibration_gate")


def create_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def state_lock(root: Path):
    """Kernel-owned byte lock: crash releases the lock without deleting evidence."""
    require(os.name == "nt", "windows_state_lock")
    import msvcrt
    root.mkdir(parents=True, exist_ok=True)
    with (root / "snapshot.lock").open("a+b") as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def accrue(manifest_path: Path, freeze_path: Path, freeze_sha: str, key_path: Path,
           output: Path, *, now: datetime, previous_path: Path | None = None,
           look: bool = False, family_path: Path | None = None) -> dict:
    assert_no_order_path()
    freeze = json_bytes(bounded_bytes(freeze_path, 2 * 1024 * 1024))
    validate_freeze(freeze, freeze_sha, now)
    require(now >= LOOK if look else now < LOOK, "look_clock")
    key = read_public_key(key_path)
    require(digest(canonical(key)) == freeze["public_key_sha256"], "seal_key_binding")
    root = Path(freeze["state_root"])
    require(output.resolve().is_relative_to(root.resolve()) and output.resolve() != root.resolve(), "output_scope")
    with state_lock(root):
        head = root / "HEAD.json"
        previous = json_bytes(bounded_bytes(head, 4 * 1024 * 1024)) if head.exists() else None
        if previous is not None:
            require(previous["schema_version"] == "low_ask_receipt_v1", "receipt_schema")
            require(previous["freeze_sha256"] == freeze_sha, "previous_freeze")
            prior_seal = bounded_bytes(safe_file(root, previous["snapshot"] + "/ledger.sealed"), 6 * 1024 * 1024)
            require(digest(prior_seal) == previous["seal"]["ciphertext_sha256"], "prior_seal_integrity")
        if previous_path is not None:
            supplied = json_bytes(bounded_bytes(previous_path, 4 * 1024 * 1024))
            require(supplied == previous, "previous_head")
        if look:
            require(family_path is not None, "family_file")
            require(family_path.is_file() and manifest_path.is_file(), "look_files_missing")
            require(family_path.stat().st_size <= 64*1024, "family_bytes")
            # Consume exactly once, before the final manifest or economic data.
            create_exclusive(root / "LOOK_CONSUMED", canonical({"freeze_sha256": freeze_sha, "look_utc": iso(now)}))
        return process_snapshot(manifest_path, freeze, freeze_sha, key, output, now=now,
                                previous=previous, look=look, family_path=family_path)


def process_snapshot(manifest_path: Path, freeze: dict, freeze_sha: str, key: dict,
                     output: Path, *, now: datetime, previous: dict | None,
                     look: bool, family_path: Path | None) -> dict:
    if previous is not None:
        require(previous["freeze_sha256"] == freeze_sha, "previous_freeze")
    preflight = json_bytes(bounded_bytes(manifest_path, 2 * 1024 * 1024))
    require(instant(freeze["frozen_utc"]) <= instant(preflight["as_of_utc"]) <= now, "as_of_clock")
    if look:
        require(instant(preflight["as_of_utc"]) <= LOOK, "look_frontier")
    manifest, loaded = load_pack(manifest_path, previous)
    as_of = instant(manifest["as_of_utc"])
    require(instant(freeze["frozen_utc"]) <= as_of <= now, "as_of_clock")
    if look:
        require(as_of <= LOOK, "look_frontier")
    for field in ("producer_id", "reader_sha256", "transform_sha256", "timezone_sha256", "timezone_version", "latency_receipt", "capital"):
        require(manifest[field] == freeze[field], "manifest_freeze_binding")
    for event in loaded["rows"]["events"]:
        if event["source"] == "metar_routine":
            require(event["parser_sha256"] == freeze["code_sha256"]["src/weather/market/metar_reports.py"], "metar_parser_binding")
    result = simulate(loaded["rows"], as_of=as_of,
                      latency_seconds=number(freeze["latency_receipt"]["frozen_L_seconds"]))
    # An independent second replay is compared inside the seal, never displayed.
    second = simulate(loaded["rows"], as_of=as_of,
                      latency_seconds=number(freeze["latency_receipt"]["frozen_L_seconds"]))
    require(result == second, "replay_mismatch")
    report = None
    if look:
        from .inference import evaluate
        family = json_bytes(bounded_bytes(family_path, 64 * 1024))
        exact(family, "claimants pvalues")
        require(family["claimants"] == freeze["claimants"], "family_binding")
        report = evaluate(result, calibration=freeze["calibration"], family_pvalues=family["pvalues"],
                          claimants=freeze["claimants"])
        report.update(schema_version="low_ask_result_v1", trial="LOW-ASK-1", freeze_sha256=freeze_sha,
                      manifest_sha256=loaded["receipt"]["manifest_sha256"], look_utc=iso(now), as_of_utc=manifest["as_of_utc"],
                      recorded_cash=result["cash"], recorded_locked_cost=result["locked"],
                      unresolved_max_payout=str(5*result["unresolved"]), conservative_net=result["net_lower"],
                      replay_sha256=result["replay_sha256"])
    ciphertext, seal_receipt = seal_payload({"ledger": result, "input_receipt": loaded["receipt"],
                                          "freeze_sha256": freeze_sha}, key)
    receipt = dict(loaded["receipt"], schema_version="low_ask_receipt_v1", freeze_sha256=freeze_sha, seal=seal_receipt,
                   snapshot=output.relative_to(Path(freeze["state_root"])).as_posix(),
                   previous_receipt_sha256=manifest["previous_receipt_sha256"],
                   integrity_defect_count=sum(not r["ok"] for r in loaded["rows"]["integrity"]))
    # No fill counts, selected bands, skip reasons, prices or economic digest.
    output.mkdir(parents=True, exist_ok=False)
    create_exclusive(output / "ledger.sealed", ciphertext)
    create_exclusive(output / "receipt.json", canonical(receipt))
    if report is not None:
        create_exclusive(output / "final_report.json", canonical(report))
    root = Path(freeze["state_root"])
    temporary = root / "HEAD.pending"
    with temporary.open("wb") as handle:
        handle.write(canonical(receipt))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, root / "HEAD.json")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="LOW-ASK-1 offline paper-only sealed accrual")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--freeze-sha", required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--previous-receipt", type=Path)
    parser.add_argument("--look", action="store_true", help="single final look, time-gated and consumed once")
    parser.add_argument("--family-file", type=Path, help="complete frozen claimant list and other final p-values")
    args = parser.parse_args(argv)
    try:
        receipt = accrue(args.manifest, args.freeze, args.freeze_sha, args.public_key,
                         args.out, now=datetime.now(UTC), previous_path=args.previous_receipt,
                         look=args.look, family_path=args.family_file)
    except Exception:
        # Do not print exception messages, reprs, file content or traceback locals.
        print('{"status":"REFUSED","integrity_failure_count":1}')
        return 2
    print(canonical({"status": "SEALED", "receipt_sha256": digest(canonical(receipt)),
                     "row_counts": receipt["row_counts"]}).decode("ascii"))
    return 0
