"""MG-1: the item-190 NBM settlement scorer never scores a reserved target date (fictional folders only).

Owner decision OD31 (2026-10-07): the whole-history run drops reserved target dates before any outcome
join and discloses only counts; non-reserved dates are scored as before. A direct single-folder call on
a reserved date is refused. OD32: the window constants are bound to the reservation doc's status line.
"""
import ast
from datetime import date, datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import re
import shutil
import sys
import types

import pytest

from weather import mg1_reserved_window as mg1
from weather.mg1_reserved_window import MG1Reserved
from weather.reporting.source_gates import nbm_probabilistic_tmax_settlement_scoring as item190
from tests.reporting.test_nbm_probabilistic_tmax_settlement_scoring import _write_nbm_folder


REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCORER = SRC / "weather/reporting/source_gates/nbm_probabilistic_tmax_settlement_scoring.py"
WINDOW = SRC / "weather/mg1_reserved_window.py"
RESERVATION_DOC = REPO / "docs/operations/reserved-confirmation-window.md"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
RESERVED = [date(2026, 10, 15), date(2026, 11, 30), date(2027, 3, 1)]
ALLOWED = [date(2026, 10, 14), date(2026, 6, 23)]


class Sentinel(Exception):
    """A settlement was opened for a date that must never reach it."""


def _stop(*args, **kwargs):
    raise Sentinel("settlement opened")


def slug_name(day, city="nyc"):
    return f"highest-temperature-in-{city}-on-{MONTHS[day.month - 1]}-{day.day}-{day.year}"


def slug_folder(root, day, city="nyc"):
    folder = Path(root) / slug_name(day, city)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def scored_folder(root, day):
    """A real scorable fictional folder whose slug and settlement both carry ``day``."""
    source = _write_nbm_folder(Path(root) / f"src-{day.isoformat()}", "2026-06-23")
    target = Path(root) / slug_name(day)
    shutil.copytree(source, target)
    settlement = json.loads((target / "settlement.json").read_text(encoding="utf-8"))
    settlement["target_date"] = day.isoformat()
    (target / "settlement.json").write_text(json.dumps(settlement), encoding="utf-8")
    return target


def payload_seen(module, root, days, monkeypatch):
    """Run build_payload over slug folders for ``days``; return the target dates score_folder received."""
    seen = []

    def record(folder, **kwargs):
        seen.append(item190.date_from_event_slug(Path(folder).name))
        return {"folder": str(folder), "status": "SKIPPED", "rows": []}

    monkeypatch.setattr(module, "score_folder", record)
    payload = module.build_payload(root, folders=[slug_folder(root, d) for d in days])
    return seen, payload


# --- the window -------------------------------------------------------------------------------

def test_window_is_open_ended_from_the_floor_and_allowlist_is_empty():
    assert mg1.MG1_FLOOR == date(2026, 10, 15)
    assert mg1.MG1_D0 is None and mg1.MG1_LAST is None and mg1.MG1_RESERVED_COUNT == 45
    # No MG-1 look entry point is registered as code yet; adding one is a reviewed edit of this pin.
    assert mg1.MG1_CONFIRMATION_ENTRY_POINTS == {}
    assert mg1.window() == (date(2026, 10, 15), None)
    for day in RESERVED + [date(2099, 1, 1)]:
        assert mg1.is_reserved(day) and mg1.is_reserved(day.isoformat())
    for day in ALLOWED:
        assert not mg1.is_reserved(day)


def test_window_only_narrows_and_inconsistent_recordings_fail_wide():
    d0 = date(2026, 10, 20)
    assert mg1.window(d0, date(2026, 12, 31)) == (d0, date(2026, 12, 31))
    assert mg1.window(d0, date(2026, 12, 3)) == (d0, date(2026, 12, 3))  # D0 + 44 days: 45 dates
    for start, last in ((date(2026, 10, 1), date(2026, 12, 31)), (d0, date(2026, 10, 19)), (d0, d0),
                        (d0, date(2026, 12, 2)),  # D0 + 43 days cannot hold 45 promotion-countable dates
                        (d0, None), ("2026-10-20", "2026-12-31"), (datetime(2026, 10, 20), datetime(2027, 1, 1))):
        assert mg1.window(start, last) == (date(2026, 10, 15), None)


def _status_paragraph():
    text = RESERVATION_DOC.read_text(encoding="utf-8")
    start = text.index("**Status:")
    return text[start:text.index("\n\n", start)]


def test_recorded_window_is_bound_to_the_reservation_doc_status_line():
    """OD32: whoever dates the doc's status line records MG1_D0/MG1_LAST in the same commit, and back."""
    status = _status_paragraph()
    assert "MG-1" in status

    def recorded(label):
        found = re.findall(r"MG-1 " + label + r" = (\d{4}-\d{2}-\d{2})", status)
        assert len(found) <= 1, f"ambiguous MG-1 {label} in the status line"
        return date.fromisoformat(found[0]) if found else None

    assert (mg1.MG1_D0, mg1.MG1_LAST) == (recorded("D0"), recorded("last"))
    if mg1.MG1_D0 is not None:
        assert mg1.window() == (mg1.MG1_D0, mg1.MG1_LAST), "a recording must narrow, not fail wide"


@pytest.mark.parametrize("bad", [None, "", "june-23", 20261015, datetime(2026, 10, 1, tzinfo=timezone.utc)])
def test_unreadable_targets_are_refused_or_dropped(bad):
    with pytest.raises(MG1Reserved, match="unparseable"):
        mg1.refuse_nbm_band_scoring([date(2026, 6, 1), bad], entry="t")
    kept, counts = mg1.drop_reserved_targets([date(2026, 6, 1), bad], target_of=lambda x: x)
    assert kept == [date(2026, 6, 1)] and counts == {"reserved_dropped": 0, "unreadable_dropped": 1}


def test_no_override_parameter_or_environment_variable():
    assert list(inspect.signature(mg1.refuse_nbm_band_scoring).parameters) == ["targets", "entry"]
    assert list(inspect.signature(mg1.drop_reserved_targets).parameters) == ["items", "target_of"]
    tree = ast.parse(WINDOW.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not ({"environ", "getenv", "argv"} & (names | attrs))
    assert "os" not in {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}


# --- whole-history run: reserved dates are filtered before the outcome join --------------------

@pytest.mark.parametrize("day", RESERVED)
def test_build_payload_never_hands_a_reserved_folder_to_the_scorer(tmp_path, monkeypatch, day):
    seen, payload = payload_seen(item190, tmp_path, [date(2026, 6, 23), day, date(2026, 10, 14)], monkeypatch)
    assert seen == [date(2026, 6, 23), date(2026, 10, 14)]
    disclosed = payload["mg1_reserved_window"]
    assert disclosed["reserved_folders_dropped"] == 1 and disclosed["listed_folder_count"] == 3
    assert payload["coverage"]["discovered_folder_count"] == 2


def test_unparseable_folder_names_are_dropped_and_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(item190, "score_folder", _stop)
    (tmp_path / "not-a-market-slug").mkdir()
    payload = item190.build_payload(tmp_path, folders=[tmp_path / "not-a-market-slug"])
    assert payload["mg1_reserved_window"]["unreadable_folders_dropped"] == 1


def test_real_run_scores_pre_window_dates_and_discloses_counts_only(tmp_path):
    pre = _write_nbm_folder(tmp_path / "pre", "2026-06-23")
    reserved = scored_folder(tmp_path / "res", date(2026, 10, 16))
    # A pre-window slug whose settlement names a reserved target date: refused before the join, dropped.
    mismatch = _write_nbm_folder(tmp_path / "mis", "2026-10-23")
    # A pre-window slug with no settlement date whose source rows carry a reserved date: the row line.
    undated = _undated_settlement_folder(tmp_path / "und", "2026-10-24")
    payload = item190.build_payload(tmp_path, folders=[pre, reserved, mismatch, undated])
    assert payload["coverage"]["target_dates"] == ["2026-06-23"]
    assert payload["coverage"]["row_count"] == 3
    disclosed = payload["mg1_reserved_window"]
    assert disclosed == {"window_start": "2026-10-15", "window_end": None, "listed_folder_count": 4,
                         "reserved_folders_dropped": 1, "unreadable_folders_dropped": 0,
                         "settlement_target_refused": 1, "reserved_rows_dropped": 3, "unreadable_rows_dropped": 0}
    text = json.dumps(payload)
    for leaked in ("2026-10-16", "2026-10-23", "2026-10-24", "october-16"):
        assert leaked not in text, leaked  # Counts only: no reserved date is disclosed.


def _undated_settlement_folder(root, day):
    folder = _write_nbm_folder(root, day)
    settlement = json.loads((folder / "settlement.json").read_text(encoding="utf-8"))
    del settlement["target_date"]
    (folder / "settlement.json").write_text(json.dumps(settlement), encoding="utf-8")
    return folder


def test_settlement_naming_a_reserved_date_is_refused_before_the_join(tmp_path, monkeypatch):
    monkeypatch.setattr(item190, "resolve_outcome", _stop)
    with pytest.raises(MG1Reserved, match="item190.settlement_target_date:2026-10-23"):
        item190.score_folder(_write_nbm_folder(tmp_path, "2026-10-23"))


def test_pre_window_scoring_is_unchanged(tmp_path):
    result = item190.score_folder(_write_nbm_folder(tmp_path, "2026-06-23"))
    assert result["status"] == "SCORED" and result["scored_rows"] == 3
    payload = item190.build_payload(tmp_path, folders=[tmp_path / slug_name(date(2026, 6, 23))])
    assert payload["mg1_reserved_window"]["reserved_folders_dropped"] == 0
    assert payload["coverage"]["row_count"] == 3


def test_cli_scores_and_reports_the_dropped_count(tmp_path, capsys):
    pre = _write_nbm_folder(tmp_path / "pre", "2026-06-23")
    reserved = slug_folder(tmp_path, date(2026, 10, 16))
    out, report = tmp_path / "out.json", tmp_path / "r.md"
    assert item190.main([str(pre), str(reserved), "--out", str(out), "--report", str(report)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["mg1_reserved_window"]["reserved_folders_dropped"] == 1
    assert "| MG-1 reserved folders dropped | 1 |" in report.read_text(encoding="utf-8")


# --- single-folder entry point: refused -----------------------------------------------------------

@pytest.mark.parametrize("day", RESERVED)
def test_score_folder_refuses_reserved_targets_before_any_settlement(tmp_path, monkeypatch, day):
    monkeypatch.setattr(item190, "_read_json", _stop)
    with pytest.raises(MG1Reserved, match=f"mg1_reserved_target_date:item190.score_folder:{day.isoformat()}"):
        item190.score_folder(slug_folder(tmp_path, day))


@pytest.mark.parametrize("day", ALLOWED)
def test_score_folder_admits_pre_window_targets(tmp_path, monkeypatch, day):
    monkeypatch.setattr(item190, "_read_json", _stop)
    with pytest.raises(Sentinel):
        item190.score_folder(slug_folder(tmp_path, day))


def test_unparseable_single_folder_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(item190, "_read_json", _stop)
    folder = tmp_path / "not-a-market-slug"
    folder.mkdir()
    with pytest.raises(MG1Reserved, match="unparseable"):
        item190.score_folder(folder)


def test_cli_exits_2_with_one_line_if_a_reserved_folder_ever_reaches_the_scorer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(item190, "drop_reserved_targets",
                        lambda items, target_of: (list(items), {"reserved_dropped": 0, "unreadable_dropped": 0}))
    monkeypatch.setattr(item190, "_read_json", _stop)
    out = tmp_path / "out.json"
    code = item190.main([str(slug_folder(tmp_path, date(2026, 10, 16))), "--out", str(out),
                         "--report", str(tmp_path / "r.md")])
    stdout, stderr = capsys.readouterr()
    assert code == 2 and stdout == "" and not out.exists()
    assert stderr.splitlines() == ["NBM settlement scoring refused: MG1Reserved: "
                                   "mg1_reserved_target_date:item190.score_folder:2026-10-16"]


# --- AST: the filter precedes every settlement read ---------------------------------------------

def _function(tree, name):
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _is_guard(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "refuse_nbm_band_scoring")


def _is_filter(stmt, source):
    return (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "drop_reserved_targets"
            and ast.unparse(stmt.value.args[0]) == source)


def test_ast_guard_first_in_score_folder_and_filter_before_scoring_in_build_payload():
    tree = ast.parse(SCORER.read_text(encoding="utf-8"))
    assert _is_guard(_function(tree, "score_folder").body[0])
    body = _function(tree, "build_payload").body
    # The only statement before the filter lists folder names (outcome-blind).
    assert ast.unparse(body[0]).startswith("listed_paths = _folder_inputs(")
    assert _is_filter(body[1], "listed_paths") and ast.unparse(body[1].targets[0]) == "(folder_paths, mg1_folders)"
    assert any(_is_filter(stmt, "scored_rows") for stmt in body), "the row line must stay"


# --- mutants: removing the filter, or letting one reserved date through, is detected --------------

def _load(path, name, transform):
    tree = transform(ast.parse(path.read_text(encoding="utf-8")))
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(ast.fix_missing_locations(tree), str(path), "exec"), module.__dict__)
    return module


def _without_folder_filter(tree):
    func = _function(tree, "build_payload")
    func.body[1] = ast.parse("folder_paths, mg1_folders = list(listed_paths), "
                             "{'reserved_dropped': 0, 'unreadable_dropped': 0}").body[0]
    return tree


def test_mutant_without_the_folder_filter_is_detected(tmp_path, monkeypatch):
    mutant = _load(SCORER, "mg1_mutant_item190", _without_folder_filter)
    seen, _ = payload_seen(mutant, tmp_path / "m", [date(2026, 6, 23), date(2026, 10, 15)], monkeypatch)
    assert date(2026, 10, 15) in seen  # The filter test above fails against this mutant.
    seen, _ = payload_seen(item190, tmp_path / "r", [date(2026, 6, 23), date(2026, 10, 15)], monkeypatch)
    assert seen == [date(2026, 6, 23)]


class _OffByOne(ast.NodeTransformer):
    """``start <= day`` -> ``start < day``: the window would admit exactly its first reserved date."""

    def visit_Compare(self, node):
        if isinstance(node.ops[0], ast.LtE) and ast.unparse(node.left) == "start":
            node.ops[0] = ast.Lt()
        return node


def test_mutant_admitting_one_reserved_date_is_detected():
    mutant = _load(WINDOW, "mg1_mutant_window", _OffByOne().visit)
    days = [date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)]
    kept, counts = mutant.drop_reserved_targets(days, target_of=lambda d: d)
    assert date(2026, 10, 15) in kept  # One reserved date leaks through the mutant ...
    kept, counts = mg1.drop_reserved_targets(days, target_of=lambda d: d)
    assert kept == [date(2026, 10, 14)] and counts["reserved_dropped"] == 2  # ... and never through the real one.


def test_mutant_without_the_row_line_is_detected(tmp_path):
    def drop_row_line(tree):
        func = _function(tree, "build_payload")
        for i, stmt in enumerate(func.body):
            if _is_filter(stmt, "scored_rows"):
                func.body[i] = ast.parse("rows, mg1_rows = list(scored_rows), "
                                         "{'reserved_dropped': 0, 'unreadable_dropped': 0}").body[0]
        return tree

    undated = _undated_settlement_folder(tmp_path, "2026-10-24")
    mutant = _load(SCORER, "mg1_mutant_item190_rows", drop_row_line)
    assert mutant.build_payload(tmp_path, folders=[undated])["coverage"]["target_dates"] == ["2026-10-24"]
    assert item190.build_payload(tmp_path, folders=[undated])["coverage"]["target_dates"] == []


def test_mutant_without_the_settlement_date_check_is_detected(tmp_path, monkeypatch):
    def drop_settlement_check(tree):
        func = _function(tree, "score_folder")
        func.body = [s for s in func.body
                     if not (isinstance(s, ast.If) and "item190.settlement_target_date" in ast.unparse(s))]
        return tree

    mismatch = _write_nbm_folder(tmp_path, "2026-10-23")
    mutant = _load(SCORER, "mg1_mutant_item190_settlement", drop_settlement_check)
    mutant.resolve_outcome = _stop
    with pytest.raises(Sentinel):  # The mutant joins the reserved settlement to an outcome.
        mutant.build_payload(tmp_path, folders=[mismatch])
    monkeypatch.setattr(item190, "resolve_outcome", _stop)
    real = item190.build_payload(tmp_path, folders=[mismatch])
    assert real["coverage"]["target_dates"] == [] and real["mg1_reserved_window"]["settlement_target_refused"] == 1


# --- allowlist: only the registered MG-1 look, by exact name and bytes ----------------------------

def _run_as_main(monkeypatch, name, origin):
    main = types.ModuleType("__main__")
    main.__spec__ = types.SimpleNamespace(name=name, origin=str(origin))
    monkeypatch.setitem(sys.modules, "__main__", main)


@pytest.fixture
def registered(tmp_path, monkeypatch):
    look = tmp_path / "mg1_look.py"
    look.write_bytes(b"# fictional registered MG-1 look\n")
    monkeypatch.setattr(mg1, "MG1_CONFIRMATION_ENTRY_POINTS",
                        {"tools.research.mg1.look": hashlib.sha256(look.read_bytes()).hexdigest()})
    return look


def test_registered_look_is_admitted_on_reserved_dates(tmp_path, monkeypatch, registered):
    _run_as_main(monkeypatch, "tools.research.mg1.look", registered)
    assert mg1.registered_confirmation_entry() == "tools.research.mg1.look"
    mg1.refuse_nbm_band_scoring(RESERVED, entry="t")
    assert mg1.drop_reserved_targets(RESERVED, target_of=lambda d: d)[0] == RESERVED
    monkeypatch.setattr(item190, "_read_json", _stop)
    with pytest.raises(Sentinel):
        item190.score_folder(slug_folder(tmp_path / "s", date(2026, 10, 15)))
    with pytest.raises(MG1Reserved, match="unparseable"):  # Still fail-closed on unreadable dates.
        mg1.refuse_nbm_band_scoring([None], entry="t")


@pytest.mark.parametrize("name", ["tools.research.mg1.look2", "tools.research.mg1.Look", "tools.research.mg1",
                                  "tools.research.mg1.look.extra", "mg1.look", "look", "", None])
def test_lookalike_entry_names_are_refused(tmp_path, monkeypatch, registered, name):
    _run_as_main(monkeypatch, name, registered)
    assert mg1.registered_confirmation_entry() is None
    with pytest.raises(MG1Reserved, match="mg1_reserved_target_date:t:2026-10-15"):
        mg1.refuse_nbm_band_scoring([date(2026, 10, 15)], entry="t")
    assert mg1.drop_reserved_targets([date(2026, 10, 15)], target_of=lambda d: d)[0] == []


def test_registered_name_with_edited_bytes_or_missing_file_is_refused(tmp_path, monkeypatch, registered):
    _run_as_main(monkeypatch, "tools.research.mg1.look", registered)
    registered.write_bytes(b"# edited\n")
    with pytest.raises(MG1Reserved):
        mg1.refuse_nbm_band_scoring([date(2026, 10, 15)], entry="t")
    _run_as_main(monkeypatch, "tools.research.mg1.look", tmp_path / "missing.py")
    with pytest.raises(MG1Reserved):
        mg1.refuse_nbm_band_scoring([date(2026, 10, 15)], entry="t")


def test_this_test_process_is_not_a_registered_entry():
    assert mg1.registered_confirmation_entry() is None
    assert not re.search(r"override|bypass", WINDOW.read_text(encoding="utf-8").split('"' * 3, 2)[2],
                         re.IGNORECASE)
