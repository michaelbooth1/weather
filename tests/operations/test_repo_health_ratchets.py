"""110m growth limits: exceptions can shrink, never silently widen."""
import ast
import json
from pathlib import Path
import re
import subprocess
import tomllib

import pytest

from tests.operations import repo_health_support as health

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / health.BASELINE_PATH
SHRINK_FIELDS = ("max_lines", "orphans", "retired", "c_names", "unsigned_band_regex", "large_files", "undeclared_imports", "report_exceptions")


@pytest.fixture(scope="module")
def observed():
    return health.inventory(ROOT)


@pytest.fixture(scope="module")
def baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_allowances_can_only_shrink_from_reviewed_seed(baseline):
    assert re.fullmatch(r"[0-9a-f]{40}", health.ALLOWANCE_SEED_SHA)
    seed = json.loads(subprocess.check_output(
        ["git", "show", f"{health.ALLOWANCE_SEED_SHA}:{health.BASELINE_PATH}"], cwd=ROOT, text=True, encoding="utf-8"))
    assert not {field: errors for field in SHRINK_FIELDS if (errors := health.growth(baseline[field], seed[field]))}
    revisions = subprocess.check_output(
        ["git", "log", "-2", "--format=%H", "--", health.BASELINE_PATH], cwd=ROOT, text=True).splitlines()
    if revisions:
        latest = json.loads(subprocess.check_output(
            ["git", "show", f"{revisions[0]}:{health.BASELINE_PATH}"], cwd=ROOT, text=True, encoding="utf-8"))
        prior = latest
        if latest == baseline and len(revisions) > 1:
            prior = json.loads(subprocess.check_output(
                ["git", "show", f"{revisions[1]}:{health.BASELINE_PATH}"], cwd=ROOT, text=True, encoding="utf-8"))
        assert not {field: errors for field in SHRINK_FIELDS if (errors := health.growth(baseline[field], prior[field]))}


def test_every_module_obeys_its_line_cap_including_tests_and_maker_core(observed, baseline):
    errors = {p: (n, baseline["max_lines"].get(p, health.MODULE_LIMIT))
              for p, n in observed["module_lines"].items() if n > baseline["max_lines"].get(p, health.MODULE_LIMIT)}
    assert not errors, errors


@pytest.mark.parametrize("field", ["orphans", "retired", "c_names", "unsigned_band_regex", "large_files"])
def test_no_growth_in_reviewed_debt(field, observed, baseline):
    assert not (errors := health.growth(observed[field], baseline[field])), errors


def test_large_roadmap_data_carries_a_mission_id(observed):
    assert not [p for p in observed["roadmap_data"] if not re.search(r"20\d{2}-\d{2}-(\d+[a-z])\b", p)]


def test_runtime_import_roots_are_declared_or_explicitly_reviewed(observed, baseline):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    requirements = list(project["dependencies"])
    for values in project.get("optional-dependencies", {}).values():
        requirements.extend(values)
    distributions = {re.split(r"[<>=!~\[; ]", value)[0].lower().replace("_", "-") for value in requirements}
    missing = {p: [name for name in roots if health.IMPORT_DISTRIBUTIONS.get(name, name.lower().replace("_", "-")) not in distributions]
               for p, roots in observed["imports"].items()}
    missing = {p: names for p, names in missing.items() if names}
    assert not (errors := health.growth(missing, baseline["undeclared_imports"])), errors
    for name in {n for roots in missing.values() for n in roots}:
        assert baseline["dependency_reasons"].get(name)


def test_every_daily_promotion_scoreboard_json_has_a_producer_contract(observed, baseline):
    contracts = baseline["report_contracts"]
    scheduled = health.reachable(observed["graph"], {"weather.operations.daily_refresh"})
    wrapper = (ROOT / "scripts/ops/daily_refresh_contract.ps1").read_text()
    assert "weather.operations.daily_refresh" in wrapper
    for consumer, filenames in observed["report_references"].items():
        for filename in filenames:
            assert filename in contracts, (consumer, filename, "unclassified JSON input/output")
            contract = contracts[filename]
            assert contract["reason"].strip()
            assert contract["mode"] in {"scheduled", "explicit", "caller_input", "output"}
            producer = contract.get("producer")
            if contract["mode"] in {"scheduled", "explicit", "output"}:
                assert producer in observed["graph"], (filename, producer)
                owner_closure = health.reachable(observed["graph"], {producer})
                assert owner_closure & set(observed["producer_candidates"].get(filename, [])), (filename, producer)
            if contract["mode"] == "scheduled":
                assert producer in scheduled, (filename, producer, "not on daily-refresh dependency path")
            if contract["mode"] == "explicit":
                assert contract.get("owner") and contract.get("disposition")
            if contract["mode"] != "scheduled":
                assert filename in baseline["report_exceptions"], filename
    assert set(baseline["known_unwired_producers"]) <= {
        value.get("producer") for value in contracts.values() if value["mode"] == "explicit"
    }


def test_controls_reject_growth_replacement_and_allow_reduction():
    assert health.growth({"file": 11}, {"file": 10})
    assert health.growth({"new": 10}, {"old": 10})
    assert health.growth(["new"], ["old"])
    assert not health.growth({"file": 9}, {"file": 10, "removed": 8})
    assert not health.growth([], ["removed"])
    assert health.c_names(ast.parse("new_native_c = 1")) == ["new_native_c"]
    assert not health.c_names(ast.parse("native_temperature = 1"))
    unsafe = ast.parse("def band_key(label):\n return re.findall(r'\\d+', label)")
    signed = ast.parse("def band_key(label):\n return re.findall(r'-?\\d+', label)")
    assert health.unsigned_band_patterns(unsafe)
    assert not health.unsigned_band_patterns(signed)
    assert health.unsigned_band_patterns(ast.parse("import re as rx\nBAND_PATTERN = rx.compile(r'\\d+')"))
    assert health.unsigned_band_patterns(ast.parse("from re import findall as find\ndef band_key(label):\n return find(r'\\d+', label)"))
    graph = {"scheduled": {"reader"}, "reader": set(), "orphan": {"orphan"}}
    assert health.reachable(graph, {"scheduled"}) == {"scheduled", "reader"}
    assert "undeclared_demo" in health.imported_modules(ast.parse("__import__('undeclared_demo')"), "fixture")
