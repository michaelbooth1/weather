"""U7: MG-1 refuses every view-vs-outcome metric on reserved target dates (fictional fixtures only)."""
import ast
import inspect
import io
import os
import subprocess
from datetime import date, datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import re
import sys
import types

import pytest

from maker_core.replay.engine import ReplayConfig, replay
from maker_core.replay.score import score as paper_score
from weather.market import maker_fair_value_score as scorer
from weather.market import maker_fair_value_statistics as statistics
from weather.market.maker_plugin import fair_value_score as plugin_cli
from weather.market import mg1_metric_guard as guard
from weather.market.mg1_metric_guard import MG1Reserved
from maker_core import mg1_window
from maker_core.replay.v2.pipeline import Pass
from tests.maker_core.fixtures.replay_scenario import Scenario


SRC = Path(__file__).resolve().parents[2] / "src"
RESERVED = [date(2026, 10, 15), date(2026, 11, 30), date(2027, 3, 1)]
ALLOWED = [date(2026, 10, 14), date(2026, 9, 1)]
AFTER_CLOSE = datetime(2026, 12, 31, tzinfo=timezone.utc)
TIP = "a" * 40

# (module file, function qualname, entry name in the refusal). Every view-vs-outcome scorer.
SCORERS = [
    ("weather/market/maker_fair_value_score.py", "score", "maker_fair_value_score.score"),
    ("weather/market/maker_fair_value_score.py", "main", "maker_fair_value_score.main"),
    ("weather/market/maker_fair_value_score.py", "Panel.settle", "maker_fair_value_score.settle"),
    ("weather/market/maker_fair_value_statistics.py", "summarize", "maker_fair_value_statistics.summarize"),
    ("weather/market/maker_fair_value_statistics.py", "tables", "maker_fair_value_statistics.tables"),
]


class Sentinel(Exception):
    """Raised by a stub when an entry point reached evidence before refusing."""


def stat_row(target):
    return dict(target_date=str(target), market_id="a", source="nbp", lead=1,
                bands=[dict(probability=.3, mid=.5, observed_yes=0, stdev=.2)])


def _stop(*args, **kwargs):
    raise Sentinel("evidence opened")


# Each probe runs one entry point of a (possibly mutated) module pair and returns the outcome.
def probe_score(mods, target, monkeypatch):
    sc = mods["score"]
    monkeypatch.setattr(sc, "PANEL_END", target, raising=True)
    monkeypatch.setattr(sc, "load_bundle", _stop)
    sc.score(["never-open"], code_tip=TIP, now=AFTER_CLOSE)


def probe_main(mods, target, monkeypatch):
    sc = mods["score"]
    monkeypatch.setattr(sc, "PANEL_END", target, raising=True)
    monkeypatch.setattr(sc, "regular_path", _stop)
    monkeypatch.setattr(sc, "load_bundle", _stop)
    monkeypatch.setattr(sc.argparse.ArgumentParser, "parse_args", _stop)
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    try:
        sc.main(["--bundle", "never-open", "--out", "never-written"])
    except SystemExit as exc:
        prefix = "fair-value score refused: MG1Reserved: "
        lines = err.getvalue().splitlines()
        if exc.code == 2 and len(lines) == 1 and lines[0].startswith(prefix + "mg1_"):
            raise MG1Reserved(lines[0][len(prefix):]) from None  # The CLI's one-line refusal.
        raise


def probe_settle(mods, target, monkeypatch):
    panel = object.__new__(mods["score"].Panel)
    panel.facts, panel.now = {"c": []}, AFTER_CLOSE
    panel.settle(dict(target_date=str(target), bands=[dict(condition_id="c")]))


def probe_summarize(mods, target, monkeypatch):
    return mods["stats"].summarize([stat_row(target)])


def probe_tables(mods, target, monkeypatch):
    return mods["stats"].tables([stat_row(target)])


PROBES = {"score": probe_score, "main": probe_main, "Panel.settle": probe_settle,
          "summarize": probe_summarize, "tables": probe_tables}
REAL = {"score": scorer, "stats": statistics}


def outcome(qualname, mods, target, monkeypatch):
    try:
        PROBES[qualname](mods, target, monkeypatch)
    except MG1Reserved as exc:
        return "refused", str(exc)
    except (Sentinel, ValueError, SystemExit) as exc:
        return "proceeded", repr(exc)
    return "proceeded", "returned"


# --- the guard itself -------------------------------------------------------------------------

def test_recorded_window_is_open_ended_from_the_floor_until_d0_is_dated():
    assert guard.MG1_FLOOR == date(2026, 10, 15)
    # Narrowing is only by a reviewed edit of these constants; this pin must change with them.
    assert guard.MG1_D0 is None and guard.MG1_LAST is None
    assert guard.MG1_RESERVED_COUNT == 45
    assert guard.window() == (date(2026, 10, 15), None)
    for day in RESERVED + [date(2099, 1, 1)]:
        assert guard.is_reserved(day) and guard.is_reserved(day.isoformat())
    for day in ALLOWED:
        assert not guard.is_reserved(day) and not guard.is_reserved(day.isoformat())


def test_window_can_only_narrow_and_inconsistent_recordings_fail_wide():
    assert guard.window(date(2026, 10, 20), date(2026, 12, 31)) == (date(2026, 10, 20), date(2026, 12, 31))
    # D0 before the floor, an end before D0, or half a recording never narrows below the floor.
    assert guard.window(date(2026, 10, 1), date(2026, 12, 31)) == (date(2026, 10, 15), None)
    assert guard.window(date(2026, 10, 20), date(2026, 10, 19)) == (date(2026, 10, 15), None)
    assert guard.window(date(2026, 10, 20), None) == (date(2026, 10, 15), None)
    assert guard.window("2026-10-20", "2026-12-31") == (date(2026, 10, 15), None)


@pytest.mark.parametrize("bad", [None, "", "d1", "2026-10-15T00:00", 20261015,
                                 datetime(2026, 10, 1, tzinfo=timezone.utc)])
def test_unreadable_target_dates_are_refused(bad):
    with pytest.raises(MG1Reserved, match="unparseable"):
        guard.refuse_reserved_targets([date(2026, 9, 1), bad], entry="t")


def test_no_override_parameter_or_environment_variable():
    params = inspect.signature(guard.refuse_reserved_targets).parameters
    assert list(params) == ["targets", "entry"]
    assert list(inspect.signature(guard.is_reserved).parameters) == ["target"]
    assert list(inspect.signature(mg1_window.refuse_paper_scoring).parameters) == ["days", "entry"]
    for module in (guard, mg1_window):
        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        imports = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        assert not ({"os", "environ", "getenv", "sys"} & (names | attrs | imports)), module.__name__
        assert not re.search(r"override|bypass|force", source.split('"' * 3, 2)[2], re.IGNORECASE)


# --- every entry point refuses a reserved target, and admits pre-window targets ----------------

@pytest.mark.parametrize("target", RESERVED)
@pytest.mark.parametrize("module,qualname,entry", SCORERS)
def test_every_metric_entry_point_refuses_reserved_targets(monkeypatch, module, qualname, entry, target):
    status, detail = outcome(qualname, REAL, target, monkeypatch)
    assert status == "refused", detail
    # A declared panel range is refused at its first reserved date, which is the floor.
    first = guard.MG1_FLOOR if qualname in ("score", "main") else target
    assert detail == f"mg1_reserved_target_date:{entry}:{first.isoformat()}"


@pytest.mark.parametrize("target", ALLOWED)
@pytest.mark.parametrize("module,qualname,entry", SCORERS)
def test_pre_window_targets_reach_the_metric(monkeypatch, module, qualname, entry, target):
    status, detail = outcome(qualname, REAL, target, monkeypatch)
    assert status == "proceeded", detail
    if qualname in ("summarize", "tables"):
        result = PROBES[qualname](REAL, target, monkeypatch)
        assert result  # A real Brier/reliability table, not a refusal.
    elif qualname == "Panel.settle":
        assert "missing_reconciled_settlement" in detail
    else:
        assert "Sentinel" in detail  # Passed the guard and reached the (stubbed) evidence read.


def test_plugin_cli_is_the_guarded_scorer_main(monkeypatch, capsys):
    assert plugin_cli.main is scorer.main
    monkeypatch.setattr(scorer, "PANEL_END", date(2026, 10, 15))
    with pytest.raises(SystemExit) as exc:
        plugin_cli.main(["--bundle", "x", "--out", "y"])
    assert exc.value.code == 2
    assert "maker_fair_value_score.main" in capsys.readouterr().err


REFUSAL_LINE = ("fair-value score refused: MG1Reserved: "
                "mg1_reserved_target_date:maker_fair_value_score.main:2026-10-15")


@pytest.mark.parametrize("argv", [["--bundle", "x", "--out", "y"], [], ["--help"]])
def test_refused_main_exits_2_with_one_line_and_no_traceback(monkeypatch, capsys, argv):
    monkeypatch.setattr(scorer, "PANEL_END", date(2026, 11, 1))
    monkeypatch.setattr(scorer, "regular_path", _stop)
    with pytest.raises(SystemExit) as exc:
        scorer.main(argv)
    assert exc.value.code == 2
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
    out, err = capsys.readouterr()
    assert out == ""
    assert err.splitlines() == [REFUSAL_LINE] and err.endswith("\n")


def test_refused_main_in_a_real_process_prints_one_line(tmp_path):
    code = ("import datetime; from weather.market import maker_fair_value_score as s; "
            "s.PANEL_END = datetime.date(2026, 10, 20); s.main(['--bundle', 'x', '--out', 'y'])")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(SRC.parent), str(SRC)])}
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                          cwd=tmp_path, env=env)
    assert done.returncode == 2, done.stderr
    assert done.stdout == ""
    assert done.stderr.splitlines() == [REFUSAL_LINE]


def test_bundle_captured_on_a_reserved_day_is_refused_before_indexing(monkeypatch):
    for day, refused in ((date(2026, 10, 15), True), (date(2026, 10, 14), False)):
        fake = types.SimpleNamespace(day=day, sealed_at=datetime(2026, 10, 16, tzinfo=timezone.utc))
        monkeypatch.setattr(scorer, "load_bundle", lambda *a, _f=fake, **k: _f)
        monkeypatch.setattr(scorer, "Panel", _stop)
        if refused:
            with pytest.raises(MG1Reserved, match="bundle_day:2026-10-15"):
                scorer.score(["fixture"], code_tip=TIP, now=datetime(2026, 10, 20, tzinfo=timezone.utc))
        else:
            with pytest.raises((AttributeError, Sentinel)):  # Past the guard: the fake has no hashes.
                scorer.score(["fixture"], code_tip=TIP, now=datetime(2026, 10, 20, tzinfo=timezone.utc))


def test_frozen_panel_itself_is_outside_the_window():
    assert scorer.PANEL_END < guard.MG1_FLOOR
    guard.refuse_reserved_targets(guard.date_range(scorer.PANEL_START, scorer.PANEL_END), entry="t")


# --- AST: each scorer calls the guard as its first statement ----------------------------------

def _function(tree, qualname):
    node = tree
    for part in qualname.split("."):
        node = next(n for n in node.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == part)
    return node


def _is_guard_stmt(stmt):
    """The guard call itself, or a try whose only statement is the guard and whose single handler
    reports the refusal and exits 2: the CLI form."""
    if isinstance(stmt, ast.Try):
        handler = stmt.handlers[0] if len(stmt.handlers) == 1 else None
        handler_ok = (handler is not None and isinstance(handler.type, ast.Name)
                      and handler.type.id == "MG1Reserved" and isinstance(handler.body[-1], ast.Raise)
                      and ast.unparse(handler.body[-1].exc) == "SystemExit(2)")
        return (handler_ok and not stmt.orelse and not stmt.finalbody and len(stmt.body) == 1
                and _is_guard_stmt(stmt.body[0]))
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "refuse_reserved_targets")


def _first_is_guard(func):
    body = list(func.body)
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return bool(body) and _is_guard_stmt(body[0])


def _guard_entry(func):
    call = next(n for n in ast.walk(func) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "refuse_reserved_targets")
    return next(k.value.value for k in call.keywords if k.arg == "entry")


@pytest.mark.parametrize("module,qualname,entry", SCORERS)
def test_ast_every_scorer_calls_the_guard_first(module, qualname, entry):
    func = _function(ast.parse((SRC / module).read_text(encoding="utf-8")), qualname)
    assert _first_is_guard(func), f"{module}:{qualname} must call refuse_reserved_targets first"
    assert _guard_entry(func) == entry


def test_ast_inventory_of_view_vs_outcome_code_is_closed():
    """New code that joins plugin views to labels must be added to SCORERS (and guarded) or exempted here."""
    joins, consumers = set(), set()
    for root in ("maker_core", "weather/market"):
        for path in (SRC / root).rglob("*.py"):
            rel = path.relative_to(SRC).as_posix()
            text = path.read_text(encoding="utf-8")
            if "observed_yes" in text or re.search(r"maker_fair_value_(statistics|score)\b", text):
                joins.add(rel)
            if re.search(r"maker_plugin\.fair_value\b|maker_plugin import fair_value\b", text):
                consumers.add(rel)
    assert joins == {"weather/market/maker_fair_value_score.py", "weather/market/maker_fair_value_statistics.py",
                     "weather/market/maker_plugin/fair_value_score.py"}
    # maker_plugin_runner serves views to the policy and records a pending settlement join; it computes
    # no view-vs-outcome metric (outcome-blind dry-run coverage), so it is exempt.
    assert consumers == {"weather/market/maker_fair_value_score.py", "weather/market/maker_plugin_runner.py"}


# --- mutants: removing the guard from any one entry point is detected --------------------------

class _DropGuard(ast.NodeTransformer):
    def __init__(self, qualname):
        self.path, self.stack = qualname.split("."), []

    def _visit(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        if self.stack == self.path:
            node.body = [s for s in node.body if not _is_guard_stmt(s)]
        self.stack.pop()
        return node

    visit_FunctionDef = visit_ClassDef = _visit


def _mutant_modules(module, qualname):
    mods = {}
    for key, rel, real in (("stats", "weather/market/maker_fair_value_statistics.py", statistics),
                           ("score", "weather/market/maker_fair_value_score.py", scorer)):
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        if rel == module:
            tree = _DropGuard(qualname).visit(tree)
            assert not _first_is_guard(_function(tree, qualname))
        mod = types.ModuleType(f"mg1_mutant_{key}")
        mod.__file__ = real.__file__
        sys.modules[mod.__name__] = mod
        if key == "score":
            # The mutated scorer must call the (possibly mutated) statistics module.
            after_future = 1 + max(i for i, n in enumerate(tree.body)
                                   if isinstance(n, ast.ImportFrom) and n.module == "__future__")
            tree.body.insert(after_future, ast.parse(f"import {mods['stats'].__name__} as _mutant_stats").body[0])
            tree.body.append(ast.parse("tables = _mutant_stats.tables").body[0])
        exec(compile(ast.fix_missing_locations(tree), real.__file__, "exec"), mod.__dict__)
        mods[key] = mod
    return mods


@pytest.mark.parametrize("module,qualname,entry", SCORERS)
def test_mutant_without_guard_fails_the_refusal_and_ast_tests(monkeypatch, module, qualname, entry):
    mods = _mutant_modules(module, qualname)
    try:
        target = date(2026, 10, 15)
        status, detail = outcome(qualname, mods, target, monkeypatch)
        # The refusal test demands exactly this entry's refusal; the mutant either proceeds or is
        # refused only later by a different entry, so it fails that test either way.
        assert (status, detail) != ("refused", f"mg1_reserved_target_date:{entry}:{target.isoformat()}")
        unmutated = _mutant_modules("none", qualname)
        assert outcome(qualname, unmutated, target, monkeypatch) == (
            "refused", f"mg1_reserved_target_date:{entry}:{target.isoformat()}")
    finally:
        for key in ("stats", "score"):
            sys.modules.pop(f"mg1_mutant_{key}", None)


# --- MM paper scoring of fills stays exempt on reserved dates ----------------------------------

@pytest.mark.parametrize("day", [date(2026, 10, 15), date(2026, 11, 2)])
def test_mm_paper_fill_settlement_still_scores_on_reserved_dates(tmp_path, day):
    assert guard.is_reserved(day)
    s = Scenario(day=day, markets=("a",), minutes=40)
    for minute in range(40):
        s.book("a", minute * 60)
    s.trade("a", 30)
    s.settle("a", 2400)
    result = replay([s.bundle(tmp_path / "b")], ReplayConfig(hazard_per_minute=0))
    r, = paper_score(result)
    f, = result.fills
    assert r["date"] == day.isoformat()
    assert r["unresolved_fills"] == 0
    assert r["settled_inventory_pnl"] == f.size * (1 - f.price)
    assert r["markouts"]["settlement"]["pnl"] == r["settled_inventory_pnl"]
    assert result.final_cash == result.config.initial_cash + r["settled_inventory_pnl"]
    assert r["modeled_net_k1"] == r["reward_k1"] + r["nominal_rebate"] + r["settled_inventory_pnl"]
    assert D(0) < r["filled_shares"]


# --- OD3: one named switch decides whether MM paper scoring is exempt --------------------------

def _paper_result(tmp_path, day):
    tmp_path.mkdir(parents=True)
    s = Scenario(day=day, markets=("a",), minutes=40)
    for minute in range(40):
        s.book("a", minute * 60)
    s.trade("a", 30)
    s.settle("a", 2400)
    return replay([s.bundle(tmp_path / "b")], ReplayConfig(hazard_per_minute=0))


def _v2_pass(day, settled_on=None):
    settlements = {} if settled_on is None else {"c": types.SimpleNamespace(
        as_of_utc=datetime.combine(settled_on, datetime.min.time(), timezone.utc))}
    scorer_ = types.SimpleNamespace(rows={(day.isoformat(), "c"): None}, band_days=lambda *a: ["scored"])
    return Pass(engine=types.SimpleNamespace(settlements=settlements), scorer=scorer_)


def test_od3_switch_is_pinned_until_the_owner_decides():
    # OD3 is pending. Changing this value is the one-line owner decision; update this pin with it.
    assert mg1_window.MG1_OD3_QUOTING_AND_PAPER_SCORING_EXEMPT is True


@pytest.mark.parametrize("exempt", [True, False])
def test_od3_switch_controls_paper_fill_settlement_on_reserved_dates(tmp_path, monkeypatch, exempt):
    monkeypatch.setattr(mg1_window, "MG1_OD3_QUOTING_AND_PAPER_SCORING_EXEMPT", exempt)
    reserved = _paper_result(tmp_path / "r", date(2026, 10, 15))
    if exempt:
        r, = paper_score(reserved)
        assert r["settled_inventory_pnl"] == reserved.fills[0].size * (1 - reserved.fills[0].price)
        assert _v2_pass(date(2026, 10, 15)).band_days(None, None) == ["scored"]
    else:
        with pytest.raises(MG1Reserved, match="mg1_reserved_paper_scoring:replay.score:2026-10-15"):
            paper_score(reserved)
        with pytest.raises(MG1Reserved, match="mg1_reserved_paper_scoring:v2.band_days:2026-10-15"):
            _v2_pass(date(2026, 10, 15)).band_days(None, None)
        # A pre-window fill whose settlement fact is dated inside the window is refused too.
        with pytest.raises(MG1Reserved, match="v2.band_days:2026-10-15"):
            _v2_pass(date(2026, 10, 14), settled_on=date(2026, 10, 15)).band_days(None, None)
    # Pre-window paper scoring works under either answer.
    r, = paper_score(_paper_result(tmp_path / "a", date(2026, 10, 14)))
    assert r["unresolved_fills"] == 0
    assert _v2_pass(date(2026, 10, 14)).band_days(None, None) == ["scored"]


@pytest.mark.parametrize("exempt", [True, False])
def test_od3_never_exempts_view_vs_outcome_metrics(monkeypatch, exempt):
    monkeypatch.setattr(mg1_window, "MG1_OD3_QUOTING_AND_PAPER_SCORING_EXEMPT", exempt)
    with pytest.raises(MG1Reserved, match="summarize"):
        statistics.summarize([stat_row(date(2026, 10, 15))])


@pytest.mark.parametrize("module,qualname", [("maker_core/replay/score.py", "score"),
                                             ("maker_core/replay/v2/pipeline.py", "Pass.band_days")])
def test_ast_paper_scorers_call_the_od3_guard_first(module, qualname):
    func = _function(ast.parse((SRC / module).read_text(encoding="utf-8")), qualname)
    body = func.body[1:] if isinstance(func.body[0].value if isinstance(func.body[0], ast.Expr) else None,
                                       ast.Constant) else func.body
    first = body[0]
    assert (isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
            and isinstance(first.value.func, ast.Name) and first.value.func.id == "refuse_paper_scoring")
