"""Complete host input/audit phases and the actual isolated native child."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from weather.operations.qualification import environment, host_audit, process, runner
from weather.operations.qualification.contracts import Graph
from weather.operations.qualification.records import publish
from weather.reporting.source_gates import settlement_source_audit as audit


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def staged(tmp_path):
    tmp_path = tmp_path.resolve()
    production, inputs, output = (tmp_path / name for name in ("production", "inputs", "output"))
    ledger = production / "data/settlements/market/ledger.jsonl"
    labels = production / "data/labels.csv"
    ledger.parent.mkdir(parents=True)
    inputs.mkdir()
    output.mkdir()
    rows = [{"event_slug": slug, "market_id": "market", "target_date": date,
             "settlement_bucket": 21, "quality_grade": "complete", "reconciliation_status": "mismatch"}
            for slug, date in (("a", "2026-09-01"), ("z-tail", "2026-09-02"))]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    labels.write_text("event_slug,market_id\na,market\nz-tail,market\n", encoding="utf-8")
    roots = {"roots": {"production": str(production)}, "prefixes": {"production": ["data"]}, "relative_root": "production"}
    maximum = {"read_bytes": 64 * 1024**2, "staged_bytes": 1024**2, "files": 16, "seconds": 120}
    ref = host_audit.stage(output=inputs, roots=roots, labels=str(labels), ledgers=str(ledger.parent.parent),
                           markets=["market"], maximum=maximum)
    return {"root": tmp_path, "inputs": inputs, "output": output, "roots": roots,
            "maximum": maximum, "ref": ref, "ledger": ledger}


def compute(fixture):
    return host_audit.run(input_graph=Graph(fixture["inputs"]), preparation_ref=fixture["ref"],
                          roots=fixture["roots"], output=fixture["output"], maximum=fixture["maximum"], candidate_audit=audit)


def test_actual_audit_and_full_tail_consumer_preserve_truth_blocks(staged):
    ref = compute(staged)
    result = Graph(staged["output"]).get(ref)
    assert result["counts"] == {"row_count": 2, "semantic_status": "BLOCK", "blocked_rows": 2}
    assert result["current_validation_required"] is True
    consumer = json.loads((staged["output"] / "consumer.json").read_text())
    assert consumer["status"] == "BLOCK"
    assert consumer["blocked_target_dates"] == ["2026-09-01", "2026-09-02"]
    final = host_audit.revalidate(input_graph=Graph(staged["inputs"]), preparation_ref=staged["ref"],
        roots=staged["roots"], maximum=staged["maximum"], previously_read=result["read_bytes"])
    assert final["read_bytes"] > result["read_bytes"]
    with pytest.raises(FileExistsError):
        compute(staged)


def test_successful_computation_cannot_hide_changed_current_generation(staged):
    result = Graph(staged["output"]).get(compute(staged))
    with staged["ledger"].open("a") as handle:
        handle.write('{"event_slug":"new"}\n')
    with pytest.raises(ValueError, match="drift"):
        host_audit.revalidate(input_graph=Graph(staged["inputs"]), preparation_ref=staged["ref"],
            roots=staged["roots"], maximum=staged["maximum"], previously_read=result["read_bytes"])


def test_computation_refuses_read_budget_instead_of_partial_success(staged):
    initial = Graph(staged["inputs"]).get(staged["ref"])["read_bytes"]
    staged["maximum"]["read_bytes"] = initial + 1
    with pytest.raises(ValueError, match="byte budget"):
        compute(staged)
    assert not (staged["output"] / "audit-computation.json").exists()


@pytest.mark.parametrize("mutation", ["omit_tail", "summary", "status", "duplicate"])
def test_complete_result_check_rejects_omission_and_semantic_rewrites(staged, mutation):
    compute(staged)
    payload = json.loads((staged["output"] / "audit.json").read_text())
    if mutation == "omit_tail":
        payload["rows"].pop()
    elif mutation == "summary":
        payload["summary"]["promotion_blocked_label_count"] = 0
    elif mutation == "status":
        payload["status"] = "PASS"
    else:
        payload["rows"][1]["event_slug"] = "a"
    with pytest.raises(ValueError):
        host_audit.validate_counts(payload, 2)


def test_real_isolated_candidate_audit_under_native_containment(staged, monkeypatch):
    trusted = staged["root"] / "trusted"
    trusted.mkdir()
    modules = ("__init__", "contracts", "records", "inputs", "settlement_inputs", "host_audit", "offline_guard")
    pins = {}
    for name in modules:
        raw = (ROOT / "src/weather/operations/qualification" / (name + ".py")).read_bytes()
        (trusted / (name + ".py")).write_bytes(raw)
        pins[name] = hashlib.sha256(raw).hexdigest()
    child = trusted / "qualification_host_child.py"
    shutil.copyfile(ROOT / "scripts/ops/qualification_host_child.py", child)
    authority = staged["root"] / "authority"
    authority.mkdir()
    paths = sorted(path.relative_to(ROOT).as_posix() for directory in (ROOT / "src/weather", ROOT / "weather")
                   for path in directory.rglob("*.py"))
    files = environment.files_manifest(ROOT, paths)["files"]
    source_ref = publish(authority, "source.json", {"schema": "qualification_source_inventory_v2", "files": files})
    request = {"phase": "audit", "candidate": str(ROOT), "trusted_root": str(trusted), "trusted_modules": pins,
        "sites": [str(Path(pytest.__file__).resolve().parents[1])], "authority_root": str(authority),
        "source_inventory": source_ref, "inputs_root": str(staged["inputs"]), "preparation": staged["ref"],
        "roots": staged["roots"], "output": str(staged["output"]), "maximum": staged["maximum"]}
    request_ref = publish(trusted, "request.json", request)
    python = Path(sys.executable).resolve()
    argv = [str(python), "-I", "-S", "-B", str(child), str(trusted / "request.json"), request_ref["sha256"]]
    env = process.clean_environment(scratch=staged["output"], executable_paths=[python])
    options = {"cwd": ROOT, "env": env, "transcript": staged["root"] / "native.log", "seconds": 120,
               "teardown_seconds": 30, "memory_bytes": 1024**3, "output_bytes": 1024**2, "minimum_disk_bytes": 1}
    if os.name == "nt":
        for path in runner.TRUSTED_WINDOWS:
            target = trusted / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
        native = process.windows_run(argv, powershell=Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe",
            dispatcher=trusted / runner.TRUSTED_WINDOWS[0], scratch=trusted, **options)
    else:
        native = process.linux_run(argv, **options)
    assert native["completed"] and native["teardown_proved"], (native, options["transcript"].read_text(errors="replace"))
    witness = json.loads((staged["output"] / "candidate-audit-imports.json").read_text())
    assert witness["source_inventory_sha256"] == source_ref["sha256"]
    assert any(row["module"] == "weather.reporting.source_gates.settlement_source_audit" for row in witness["after"])
    result = Graph(staged["output"]).get(witness["computation"])
    assert result["counts"]["semantic_status"] == "BLOCK"


def test_complete_native_audit_pipeline_shares_deadline_and_read_budget(staged, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from weather.operations.qualification import host

    trusted = staged["root"] / "pipeline-trusted"
    module_root = trusted / "src/weather/operations/qualification"
    module_root.mkdir(parents=True)
    modules = (*host.AUDIT_MODULES, "host")
    pins = {}
    for name in modules:
        raw = (ROOT / "src/weather/operations/qualification" / (name + ".py")).read_bytes()
        (module_root / (name + ".py")).write_bytes(raw)
        pins[name] = hashlib.sha256(raw).hexdigest()
    scripts = trusted / "scripts/ops"
    scripts.mkdir(parents=True)
    for name in ("qualification_host_child.py", "qualification_host_pipeline.py"):
        shutil.copyfile(ROOT / "scripts/ops" / name, scripts / name)
    authority, inputs, output, scratch, receipts = [staged["root"] / ("pipeline-" + name) for name in
                                                   ("authority", "inputs", "output", "scratch", "receipts")]
    for directory in (authority, inputs, output, scratch, receipts):
        directory.mkdir()
    paths = sorted(path.relative_to(ROOT).as_posix() for directory in (ROOT / "src/weather", ROOT / "weather")
                   for path in directory.rglob("*.py"))
    source_ref = publish(authority, "source.json", {"schema": "qualification_source_inventory_v2",
        "files": environment.files_manifest(ROOT, paths)["files"]})
    plan = {"schema": "qualification_host_audit_plan_v2", "candidate": str(ROOT), "trusted_root": str(trusted),
        "trusted_modules": {key: pins[key] for key in host.AUDIT_MODULES},
        "sites": [str(Path(pytest.__file__).resolve().parents[1])], "authority_root": str(authority),
        "source_inventory": source_ref, "inputs_root": str(inputs), "roots": staged["roots"], "output": str(output),
        "receipt_root": str(receipts),
        "maximum": staged["maximum"], "labels": str(staged["ledger"].parents[2] / "labels.csv"),
        "ledgers": str(staged["ledger"].parent.parent), "markets": ["market"],
        "deadline": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
        "child_sha256": hashlib.sha256((scripts / "qualification_host_child.py").read_bytes()).hexdigest()}
    for unsafe in (output, inputs, output.parent):
        with pytest.raises(ValueError, match="overlap"):
            host.audit_plan({**plan, "receipt_root": str(unsafe)})
    request = {"plan": plan, "controller_modules": pins, "scratch": str(scratch)}
    request_ref = publish(authority, "pipeline-request.json", request)
    python = Path(sys.executable).resolve()
    argv = [str(python), "-I", "-S", "-B", str(scripts / "qualification_host_pipeline.py"),
            str(authority / request_ref["path"]), request_ref["sha256"]]
    env = process.clean_environment(scratch=scratch, executable_paths=[python])
    options = {"cwd": trusted, "env": env, "transcript": staged["root"] / "pipeline-native.log", "seconds": 120,
               "teardown_seconds": 30, "memory_bytes": 2 * 1024**3, "output_bytes": 1024**2, "minimum_disk_bytes": 1}
    if os.name == "nt":
        for path in runner.TRUSTED_WINDOWS:
            target = trusted / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
        try:
            native = process.windows_run(argv, powershell=Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe",
                dispatcher=trusted / runner.TRUSTED_WINDOWS[0], scratch=scratch, **options)
        except Exception:
            # Only this disposable offline fixture's bounded child transcript.
            if options["transcript"].exists():
                print(options["transcript"].read_text(errors="replace")[-16384:])
            for path in scratch.glob("*result*.json"):
                print(path.read_text(errors="replace")[:4096])
            raise
    else:
        native = process.linux_run(argv, **options)
    assert native["completed"] and native["teardown_proved"], (native, options["transcript"].read_text(errors="replace"))
    result = json.loads((receipts / "audit-pipeline.json").read_text())
    assert not (output / "audit-current.json").exists()
    assert not (output / "audit-pipeline.json").exists()
    assert result["counts"]["semantic_status"] == "BLOCK"
    assert result["integration_eligible"] is False
    computed = Graph(output).get(result["computation"])
    assert result["read_bytes"] > computed["read_bytes"]
    assert result["completed_at"] <= plan["deadline"]
    assert Graph(receipts).get(result["current"])["computation_sha256"] == result["computation"]["sha256"]
    # A receipt cannot be replayed into another plan or extend its budget.
    with pytest.raises(ValueError, match="deadline|envelope"):
        host.audit_completion({**plan, "maximum": {**plan["maximum"], "seconds": 1},
                               "deadline": result["started_at"]}, result["preparation"], result["computation"], result["current"])
    with pytest.raises(ValueError, match="integer"):
        host.audit_completion({**plan, "maximum": {**plan["maximum"], "read_bytes": 1}},
                              result["preparation"], result["computation"], result["current"])
    with staged["ledger"].open("a") as handle:
        handle.write('{"event_slug":"changed-after-completion"}\n')
    with pytest.raises(ValueError, match="drift"):
        host_audit.revalidate(input_graph=Graph(inputs), preparation_ref=result["preparation"], roots=plan["roots"],
                             maximum=plan["maximum"], previously_read=result["read_bytes"])
