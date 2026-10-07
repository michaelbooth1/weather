"""MG-1: the item-190 NBM settlement scorer refuses reserved target dates (fictional folders only)."""
import ast
from datetime import date, datetime, timezone
import hashlib
import inspect
from pathlib import Path
import re
import sys
import types

import pytest

from weather import mg1_reserved_window as mg1
from weather.mg1_reserved_window import MG1Reserved
from weather.reporting.source_gates import nbm_probabilistic_tmax_settlement_scoring as item190
from tests.reporting.test_nbm_probabilistic_tmax_settlement_scoring import _write_nbm_folder


SRC = Path(__file__).resolve().parents[2] / "src"
SCORER = SRC / "weather/reporting/source_gates/nbm_probabilistic_tmax_settlement_scoring.py"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
RESERVED = [date(2026, 10, 15), date(2026, 11, 30), date(2027, 3, 1)]
ALLOWED = [date(2026, 10, 14), date(2026, 6, 23)]


class Sentinel(Exception):
    """A settlement or folder was opened before the guard refused."""


def _stop(*args, **kwargs):
    raise Sentinel("settlement opened")


def slug_folder(root, day, city="nyc"):
    folder = Path(root) / f"highest-temperature-in-{city}-on-{MONTHS[day.month - 1]}-{day.day}-{day.year}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def probe_score_folder(module, root, day, monkeypatch):
    monkeypatch.setattr(module, "_read_json", _stop)
    return module.score_folder(slug_folder(root, day))


def probe_build_payload(module, root, day, monkeypatch):
    monkeypatch.setattr(module, "score_folder", _stop)
    return module.build_payload(root, folders=[slug_folder(root, date(2026, 6, 23)), slug_folder(root, day)])


PROBES = {"score_folder": (probe_score_folder, "item190.score_folder"),
          "build_payload": (probe_build_payload, "item190.build_payload")}


def outcome(qualname, module, root, day, monkeypatch):
    probe, _ = PROBES[qualname]
    try:
        probe(module, root, day, monkeypatch)
    except MG1Reserved as exc:
        return "refused", str(exc)
    except Sentinel as exc:
        return "proceeded", repr(exc)
    return "proceeded", "returned"


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
    assert mg1.window(date(2026, 10, 20), date(2026, 12, 31)) == (date(2026, 10, 20), date(2026, 12, 31))
    for d0, last in ((date(2026, 10, 1), date(2026, 12, 31)), (date(2026, 10, 20), date(2026, 10, 19)),
                     (date(2026, 10, 20), None), ("2026-10-20", "2026-12-31")):
        assert mg1.window(d0, last) == (date(2026, 10, 15), None)


@pytest.mark.parametrize("bad", [None, "", "june-23", 20261015, datetime(2026, 10, 1, tzinfo=timezone.utc)])
def test_unreadable_targets_are_refused(bad):
    with pytest.raises(MG1Reserved, match="unparseable"):
        mg1.refuse_nbm_band_scoring([date(2026, 6, 1), bad], entry="t")


def test_no_override_parameter_or_environment_variable():
    assert list(inspect.signature(mg1.refuse_nbm_band_scoring).parameters) == ["targets", "entry"]
    tree = ast.parse(Path(mg1.__file__).read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not ({"environ", "getenv", "argv"} & (names | attrs))
    assert "os" not in {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}


# --- the scorer's entry points -----------------------------------------------------------------

@pytest.mark.parametrize("day", RESERVED)
@pytest.mark.parametrize("qualname", sorted(PROBES))
def test_entry_points_refuse_reserved_targets_before_any_settlement(tmp_path, monkeypatch, qualname, day):
    status, detail = outcome(qualname, item190, tmp_path, day, monkeypatch)
    assert (status, detail) == ("refused", f"mg1_reserved_target_date:{PROBES[qualname][1]}:{day.isoformat()}")


@pytest.mark.parametrize("day", ALLOWED)
@pytest.mark.parametrize("qualname", sorted(PROBES))
def test_pre_window_targets_reach_the_scorer(tmp_path, monkeypatch, qualname, day):
    status, detail = outcome(qualname, item190, tmp_path, day, monkeypatch)
    assert status == "proceeded" and "Sentinel" in detail, detail


def test_unparseable_folder_name_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(item190, "_read_json", _stop)
    folder = tmp_path / "not-a-market-slug"
    folder.mkdir()
    with pytest.raises(MG1Reserved, match="unparseable"):
        item190.score_folder(folder)


def test_pre_window_scoring_is_unchanged(tmp_path):
    result = item190.score_folder(_write_nbm_folder(tmp_path, "2026-06-23"))
    assert result["status"] == "SCORED" and result["scored_rows"] == 3


def test_refused_cli_exits_2_with_one_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(item190, "score_folder", _stop)
    out = tmp_path / "out.json"
    code = item190.main([str(slug_folder(tmp_path, date(2026, 10, 16))), "--out", str(out),
                         "--report", str(tmp_path / "r.md")])
    stdout, stderr = capsys.readouterr()
    assert code == 2 and stdout == "" and not out.exists()
    assert stderr.splitlines() == ["NBM settlement scoring refused: MG1Reserved: "
                                   "mg1_reserved_target_date:item190.build_payload:2026-10-16"]


# --- AST: the guard precedes every settlement read ----------------------------------------------

def _function(tree, name):
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _is_guard(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "refuse_nbm_band_scoring")


def test_ast_guard_is_first_in_score_folder_and_before_scoring_in_build_payload():
    tree = ast.parse(SCORER.read_text(encoding="utf-8"))
    assert _is_guard(_function(tree, "score_folder").body[0])
    body = _function(tree, "build_payload").body
    # The only statement before the guard lists folder names (outcome-blind).
    assert ast.unparse(body[0]).startswith("folder_paths = _folder_inputs(") and _is_guard(body[1])


# --- mutants: removing either guard is detected -------------------------------------------------

def _mutant(qualname):
    tree = ast.parse(SCORER.read_text(encoding="utf-8"))
    func = _function(tree, qualname)
    func.body = [s for s in func.body if not _is_guard(s)]
    module = types.ModuleType("mg1_mutant_item190")
    module.__file__ = str(SCORER)
    exec(compile(ast.fix_missing_locations(tree), str(SCORER), "exec"), module.__dict__)
    return module


@pytest.mark.parametrize("qualname", sorted(PROBES))
def test_mutant_without_guard_is_detected(tmp_path, monkeypatch, qualname):
    mutant = _mutant(qualname)
    status, _ = outcome(qualname, mutant, tmp_path / "m", date(2026, 10, 15), monkeypatch)
    assert status == "proceeded"  # The refusal test above fails against this mutant.
    status, _ = outcome(qualname, item190, tmp_path / "r", date(2026, 10, 15), monkeypatch)
    assert status == "refused"


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
    status, _ = outcome("score_folder", item190, tmp_path / "s", date(2026, 10, 15), monkeypatch)
    assert status == "proceeded"
    with pytest.raises(MG1Reserved, match="unparseable"):  # Still fail-closed on unreadable dates.
        mg1.refuse_nbm_band_scoring([None], entry="t")


@pytest.mark.parametrize("name", ["tools.research.mg1.look2", "tools.research.mg1.Look", "tools.research.mg1",
                                  "tools.research.mg1.look.extra", "mg1.look", "look", "", None])
def test_lookalike_entry_names_are_refused(tmp_path, monkeypatch, registered, name):
    _run_as_main(monkeypatch, name, registered)
    assert mg1.registered_confirmation_entry() is None
    with pytest.raises(MG1Reserved, match="mg1_reserved_target_date:t:2026-10-15"):
        mg1.refuse_nbm_band_scoring([date(2026, 10, 15)], entry="t")


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
    assert not re.search(r"override|bypass", Path(mg1.__file__).read_text(encoding="utf-8").split('"' * 3, 2)[2],
                         re.IGNORECASE)
