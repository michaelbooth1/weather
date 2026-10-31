"""The data layer v2 platform registry (config/capture_families.json ``platform``) stays true.

Guards: docs/operations/DATA_LAYER_V2_CONTRACT.md (data layer v2 S1, plan PL-3): the roll-closure
rows reproduce the pre-S1 hand list; every registered task, storage path and code reference
resolves; every evidence path is classified (an unclassified path fails); the pending storage
list only shrinks; and the embargo windows exist in exactly two code owners, which the contract's
copy must agree with (embargo-agreement ratchet).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
from datetime import date
from pathlib import Path

import pytest

from maker_core.shadow import admission
from weather import mg1_reserved_window
from weather.market.maker_evidence_family import load_family
from weather.operations.storage_classes import UNCLASSIFIED, classify_storage_path
from weather.reporting.market.capture_family_status import configured_families, task_name


REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "config" / "capture_families.json"
SCHEDULED_TASKS = REPO_ROOT / "config" / "scheduled_tasks.json"
CONTRACT = REPO_ROOT / "docs" / "operations" / "DATA_LAYER_V2_CONTRACT.md"
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
PLATFORM = REGISTRY["platform"]

# The hand-maintained list in roll_verdict.ps1 / staleness_sweep.ps1 before S1, frozen. Changing a
# row changes every roll verdict, so it is a reviewed change to this list and to the contract.
PRE_S1_ROLL_CLOSURES = [
    ("snapshot", "data/snapshots/loop_supervisor_status.json", "WeatherSnapshotLoopSupervisor", "always"),
    ("clob", "data/snapshots/clob_loop_supervisor_status.json", "WeatherClobBookLoopSupervisor", "always"),
    ("observation-trigger", "data/snapshots/observation_trigger_supervisor_status.json",
     "WeatherObservationTriggerSupervisor", "always"),
    ("clob-enrichment", "data/snapshots/clob_enrichment_status.json", "WeatherClobEnrichmentLoop", "always"),
    ("execution-tape", "data/snapshots/execution_tape_supervisor_status.json", "WeatherExecutionTapeSupervisor",
     "while_armed_or_active"),
]
EXECUTION_TAPE_OPTIONAL = {
    "worker_status": "data/snapshots/execution_tape_status.json",
    "writer_lock": "data/snapshots/.execution_tape_status.json.writer.lock",
}
EVIDENCE_FIELDS = {
    "id", "plan_family", "task", "entry_module", "status_path", "adoption", "roll_class", "ram_cap",
    "byte_budget", "request_budget", "embargo_scope", "licence", "storage",
}
PLACEHOLDERS = {
    "<event>": "highest-temperature-in-toronto-on-january-2-2026",
    "<prefix>": "ab",
    "<sha256>": "ab" + "0" * 62,
    "<part>": "000001",
    "<utc_day>": "2026-01-02",
    "<day>": "2026-01-02",
    "<hour>": "07",
    "<segment>": "segment-000001",
    "<run>": "r1",
}
ISO_DATE = re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b")


def _family_ids() -> list[str]:
    return sorted(REGISTRY["families"])


def _expand(path: str) -> list[str]:
    """Concrete example paths for a registry path; ``<family>`` expands to every configured family."""
    families = _family_ids() if "<family>" in path else [None]
    out = []
    for family in families:
        concrete = path if family is None else path.replace("<family>", family)
        for key, value in PLACEHOLDERS.items():
            concrete = concrete.replace(key, value)
        assert "<" not in concrete, f"unknown placeholder in {path}"
        out.append(concrete)
    return out


def _expand_task(task: str) -> list[str]:
    if "<PascalId>" in task:
        return [task_name(family) for family in _family_ids()]
    return [task]


def _scheduled_task_names() -> set[str]:
    return {row["name"] for row in json.loads(SCHEDULED_TASKS.read_text(encoding="utf-8"))["tasks"]}


def _resolve(reference: str):
    module, _, attribute = reference.partition(":")
    value = importlib.import_module(module)
    for part in attribute.split("."):
        value = getattr(value, part)
    return value


def test_roll_closures_reproduce_the_pre_registry_list_in_order() -> None:
    rows = PLATFORM["roll_closures"]
    assert [(r["id"], r["status_path"], r["task"], r["arming"]) for r in rows] == PRE_S1_ROLL_CLOSURES
    optional = [r for r in rows if r["arming"] != "always"]
    assert [{k: r[k] for k in EXECUTION_TAPE_OPTIONAL} for r in optional] == [EXECUTION_TAPE_OPTIONAL]
    for row in rows:
        assert re.fullmatch(r"data/[A-Za-z0-9_./-]+\.json", row["status_path"]) and ".." not in row["status_path"]


def test_every_registered_task_is_a_reviewed_scheduled_task() -> None:
    known = _scheduled_task_names()
    tasks = [row["task"] for row in PLATFORM["roll_closures"]]
    tasks += [row["task"] for row in PLATFORM["evidence_families"]]
    missing = sorted({name for task in tasks for name in _expand_task(task)} - known)
    assert missing == []


def test_evidence_family_rows_are_complete_and_their_entry_modules_exist() -> None:
    ids = [row["id"] for row in PLATFORM["evidence_families"]]
    assert len(ids) == len(set(ids))
    for row in PLATFORM["evidence_families"]:
        assert set(row) == EVIDENCE_FIELDS, row["id"]
        assert row["embargo_scope"] == "capture_outcome_blind", row["id"]
        assert row["storage"], row["id"]
        spec = importlib.util.find_spec(row["entry_module"])
        assert spec is not None, row["entry_module"]


@pytest.mark.parametrize("field", ["ram_cap", "byte_budget"])
def test_budget_references_resolve_to_positive_integers(field: str) -> None:
    for row in PLATFORM["evidence_families"]:
        value = row[field]
        if value == "not_declared":
            continue
        resolved = _resolve(value)
        assert isinstance(resolved, int) and resolved > 0, (row["id"], field, value)


def test_request_budget_references_name_a_configured_family_field() -> None:
    for row in PLATFORM["evidence_families"]:
        value = row["request_budget"]
        if value == "not_declared":
            continue
        prefix, _, field = value.partition("<family>.")
        assert prefix == "families."
        for family in _family_ids():
            assert int(REGISTRY["families"][family][field]) > 0


def test_every_registered_evidence_path_is_classified_as_declared() -> None:
    wrong = []
    for row in PLATFORM["evidence_families"]:
        for entry in row["storage"]:
            for concrete in _expand(entry["path"]):
                got = classify_storage_path(concrete).artifact_family
                if got == UNCLASSIFIED or got != entry["artifact_family"]:
                    wrong.append(f"{row['id']}: {concrete} -> {got}, registry says {entry['artifact_family']}")
    assert wrong == []


def test_every_status_path_is_classified_or_explicitly_pending() -> None:
    pending = {row["path"] for row in PLATFORM["storage_pending"]}
    unclassified = []
    paths = [row["status_path"] for row in PLATFORM["roll_closures"]]
    paths += [row["status_path"] for row in PLATFORM["evidence_families"]]
    for path in paths:
        if path in pending:
            continue
        for concrete in _expand(path):
            if classify_storage_path(concrete).artifact_family == UNCLASSIFIED:
                unclassified.append(concrete)
    assert unclassified == []


def test_pending_storage_rows_are_still_pending() -> None:
    """Shrink-only: once storage_classes classifies a pending path properly, delete its row."""
    for row in PLATFORM["storage_pending"]:
        for concrete in _expand(row["path"]):
            assert classify_storage_path(concrete).artifact_family == row["today"], (
                f"{concrete} is no longer classified as {row['today']}: remove it from storage_pending"
            )


def test_platform_block_holds_no_dates_and_its_embargo_references_resolve() -> None:
    assert ISO_DATE.search(json.dumps(PLATFORM)) is None
    assert _resolve(PLATFORM["embargo"]["windows"]) is admission.EMBARGO_WINDOWS
    assert _resolve(PLATFORM["embargo"]["mg1"]) is mg1_reserved_window.window
    assert (REPO_ROOT / PLATFORM["contract"]).is_file()


def _contract_embargo_rows() -> list[tuple[str, str, str]]:
    text = CONTRACT.read_text(encoding="utf-8")
    section = text.split("<!-- embargo-table:start -->", 1)[1].split("<!-- embargo-table:end -->", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 4 and ISO_DATE.fullmatch(cells[1] or "x"):
            rows.append(tuple(cells[:4]))
    return rows


def test_contract_embargo_table_agrees_with_the_code_owners() -> None:
    expected = [("maker_core", start, end, scope) for start, end, scope, _ in admission.EMBARGO_WINDOWS]
    floor, last = mg1_reserved_window.window()
    expected.append(("mg1", floor.isoformat(), "open" if last is None else last.isoformat(), "mg1_reserved"))
    assert _contract_embargo_rows() == expected


def test_mg1_window_copies_agree_when_the_maker_core_copy_exists() -> None:
    try:
        other = importlib.import_module("maker_core.mg1_window")
    except ModuleNotFoundError:
        pytest.skip("maker_core.mg1_window is not on this tree")
    for name in ("MG1_FLOOR", "MG1_D0", "MG1_LAST", "MG1_RESERVED_COUNT"):
        if hasattr(other, name):
            assert getattr(other, name) == getattr(mg1_reserved_window, name), name
    assert isinstance(mg1_reserved_window.MG1_FLOOR, date)


def test_existing_family_readers_still_accept_the_registry() -> None:
    families = configured_families(REGISTRY_PATH)
    assert [row["id"] for row in families] == _family_ids()
    assert len(REGISTRY_PATH.read_bytes()) <= 65536
    for family in _family_ids():
        assert load_family(family, REGISTRY_PATH)
