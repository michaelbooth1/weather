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
    request = {"candidate": str(ROOT), "trusted_root": str(trusted), "trusted_modules": pins,
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
