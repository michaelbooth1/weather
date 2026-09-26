"""Differential fixtures against the frozen integration verifiers."""
import ast
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess

import pytest

from weather import point_in_time_contract as contract
from weather.reporting.validation import point_in_time_evaluation as reporting
from tests.operations.test_release_candidate_contract import _fixture, _production_evidence

ROOT = Path(__file__).resolve().parents[2]
BASE = "8180404a0e588f73dab3c83a171538f8a89c9705"
SHARED = (
    "ContractViolation", "_parse_date", "_parse_utc", "_verify_candidate_training_graph",
    "_verify_self_hash", "canonical_json", "collect_parquet_fleet_dates", "sha256_text",
    "verify_materialization_manifest", "verify_production_point_in_time_artifacts",
    "verify_streaming_evaluation_payload", "verify_validation_plan_payload",
)


def frozen(module, relative):
    source = subprocess.check_output(["git", "show", f"{BASE}:{relative}"], cwd=ROOT, text=True, encoding="utf-8")
    tree = ast.parse(source)
    tree.body = [node for node in tree.body if
                 isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in SHARED]
    namespace = dict(vars(module))
    exec(compile(tree, str(relative), "exec"), namespace)
    return namespace


@pytest.fixture(scope="module")
def packet(tmp_path_factory):
    paths = _fixture(tmp_path_factory.mktemp("pit-differential"))
    evidence = _production_evidence(paths)
    payloads = {name: json.loads(path.read_text()) for name, path in evidence.items() if path.suffix == ".json"}
    return evidence, payloads


def call_case(name, namespace, packet):
    evidence, payloads = packet
    manifest = payloads["point_in_time_materialization_manifest"]
    plan = payloads["point_in_time_validation_plan"]
    evaluation = payloads["point_in_time_streaming_evaluation"]
    graph = manifest["candidate_training_graph"]
    function = namespace[name]
    if name == "ContractViolation":
        error = function("fixture", "fixture message")
        return error.code, str(error), isinstance(error, ValueError)
    if name == "_parse_date":
        return function("2026-09-26", "fixture_date")
    if name == "_parse_utc":
        return function("2026-09-26T12:00:00Z", "fixture_time")
    if name == "canonical_json":
        return function({"unicode": "°", "nested": [None, True, 0, -2, 0.5]})
    if name == "sha256_text":
        return function("fixture °")
    if name == "_verify_self_hash":
        payload = {"a": 1}
        payload["hash"] = contract.sha256_text(contract.canonical_json(payload))
        return function(payload, "hash", "fixture_hash")
    if name == "collect_parquet_fleet_dates":
        return function(evidence["point_in_time_corpus"])
    if name == "verify_materialization_manifest":
        return function(evidence["point_in_time_corpus"], evidence["point_in_time_materialization_manifest"])
    if name == "verify_validation_plan_payload":
        return function(plan, require_fit_receipts=True)
    if name == "verify_streaming_evaluation_payload":
        return function(evaluation, expected_candidate_id="r1", expected_release_id="r1",
                        expected_selection_universe_sha256=graph["selection_universe_sha256"],
                        require_production_window=True)
    if name == "_verify_candidate_training_graph":
        import inspect
        kwargs = {"selection_universe_sha256": graph["selection_universe_sha256"]}
        if "selection_universe_sha256" not in inspect.signature(function).parameters:
            kwargs = {"selection_universe": {"sha256": graph["selection_universe_sha256"]}}
        return function(graph, manifest=manifest, plan=plan, evaluation=evaluation,
                        expected_candidate_id="r1", expected_release_id="r1", **kwargs)
    return function(corpus_path=evidence["point_in_time_corpus"],
                    materialization_manifest_path=evidence["point_in_time_materialization_manifest"],
                    validation_plan_path=evidence["point_in_time_validation_plan"],
                    streaming_evaluation_path=evidence["point_in_time_streaming_evaluation"],
                    expected_candidate_id="r1", expected_release_id="r1")


@pytest.fixture(scope="module")
def old_contract():
    return frozen(contract, "src/weather/point_in_time_contract.py")


@pytest.fixture(scope="module")
def old_reporting():
    return frozen(reporting, "src/weather/reporting/validation/point_in_time_evaluation.py")


@pytest.mark.parametrize("name", SHARED)
def test_twelve_contract_names_preserve_frozen_fixture_behavior(name, packet, old_contract, old_reporting):
    before = call_case(name, old_contract, packet)
    after = call_case(name, vars(contract), packet)
    assert after == before
    reported_before = call_case(name, old_reporting, packet)
    reported_after = call_case(name, vars(reporting), packet)
    if name == "verify_production_point_in_time_artifacts":
        # Shared verifier additionally exposes existing release-proof metadata.
        assert {key: reported_after[key] for key in reported_before} == reported_before
    else:
        assert reported_after == reported_before


@pytest.mark.parametrize("name,args", [
    ("_parse_date", ("", "date")), ("_parse_date", ("bad", "date")),
    ("_parse_utc", ("", "time")), ("_parse_utc", ("bad", "time")),
    ("_parse_utc", ("2026-09-26T12:00:00", "time")),
    ("verify_validation_plan_payload", ({},)), ("verify_streaming_evaluation_payload", ({},)),
    ("_verify_self_hash", ({"hash": "bad"}, "hash", "bad_hash")),
])
def test_rejections_keep_exception_codes(name, args, old_contract, old_reporting):
    for before, after in ((old_contract, vars(contract)), (old_reporting, vars(reporting))):
        errors = []
        for namespace in (before, after):
            with pytest.raises(ValueError) as caught:
                namespace[name](*args)
            errors.append(caught.value.code)
        assert errors[0] == errors[1]


def test_reporting_normalization_stays_outside_neutral_hashing(old_reporting):
    import numpy as np
    import pandas as pd
    payload = {"date": date(2026, 9, 26), "time": datetime(2026, 9, 26, tzinfo=timezone.utc),
               "missing": pd.NA, "nan": float("nan"), "scalar": np.int64(3), "set": {"b", "a"}}
    assert reporting.canonical_json(payload) == old_reporting["canonical_json"](payload)
    with pytest.raises(ValueError):
        contract.canonical_json({"nan": float("nan")})


def test_release_hash_mismatch_and_partial_binding_do_not_admit_a_production_window(packet):
    evaluation = deepcopy(packet[1]["point_in_time_streaming_evaluation"])
    for field in ("manifest_sha256", "candidate_artifact_sha256"):
        with pytest.raises(contract.ContractViolation) as caught:
            contract.verify_streaming_evaluation_payload(evaluation, **{f"expected_{field}": "0" * 64})
        assert caught.value.code == "streaming_evaluation_identity_mismatch"
    with pytest.raises(contract.ContractViolation):
        contract.verify_streaming_evaluation_payload(evaluation, require_production_window=True,
            expected_candidate_id="r1", expected_release_id="r1", expected_manifest_sha256=None)


def test_reporting_has_no_duplicate_verifier_definitions():
    tree = ast.parse(Path(reporting.__file__).read_text(encoding="utf-8-sig"))
    assert not {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))} & set(SHARED)


def test_lazy_import_closure_excludes_reporting_verifier(tmp_path):
    """Static upper bound includes imports inside functions and literal import_module calls."""
    import importlib.util
    modules = {}
    for path in (ROOT / "src/weather").rglob("*.py"):
        parts = path.relative_to(ROOT / "src").with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        modules[name] = path
    changed = {
        "weather.point_in_time_contract", "weather.residual_distribution_release",
        "weather.reporting.validation.point_in_time_evaluation",
    }
    sources = {name: path.read_text(encoding="utf-8-sig") for name, path in modules.items()}
    old_sources = dict(sources)
    for name in changed:
        old_sources[name] = subprocess.check_output(
            ["git", "show", f"{BASE}:{modules[name].relative_to(ROOT).as_posix()}"],
            cwd=ROOT, text=True, encoding="utf-8",
        )

    def graph(texts):
        result = {}
        for name, source in texts.items():
            dependencies = set()
            package = name if modules[name].name == "__init__.py" else name.rpartition(".")[0]
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    dependencies.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    target = node.module or ""
                    if node.level:
                        target = importlib.util.resolve_name("." * node.level + target, package)
                    dependencies.add(target)
                    dependencies.update(target + "." + alias.name for alias in node.names)
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and (
                    node.func.attr == "import_module" and node.args and
                    isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                ):
                    dependencies.add(node.args[0].value)
            result[name] = dependencies & modules.keys()
        return result

    def closure(edges, root):
        seen, pending = set(), [root]
        while pending:
            name = pending.pop()
            if name not in seen:
                seen.add(name)
                pending.extend(edges.get(name, ()) - seen)
        return seen

    old_graph, new_graph = graph(old_sources), graph(sources)
    rows = {}
    for root in ("weather.residual_distribution_release", "weather.market.market_microstructure",
                 "weather.collection.snapshot_tracker", "weather.operations.observation_trigger"):
        before, after = closure(old_graph, root), closure(new_graph, root)
        rows[root] = {"before": len(before), "after": len(after),
                      "removed": sorted(before - after), "added": sorted(after - before),
                      "removed_lines": sum(len(old_sources[name].splitlines()) for name in before - after)}
    (tmp_path / "closure.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    assert "weather.reporting.validation.point_in_time_evaluation" not in new_graph["weather.residual_distribution_release"]
    assert "weather.reporting.validation.point_in_time_evaluation" in old_graph["weather.residual_distribution_release"]

