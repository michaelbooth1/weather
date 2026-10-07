"""The maker replay v2 panel export gate (Swarm M unit U6); fictional inputs only, no data is ever read.

Guards: owner decision 3 (Swarm M 2026-10-06) and A-defender B1 -- every export or read entry point refuses UTC
days 2026-09-30..2026-10-15 before opening any input until the maker-replay-v2-v1 authorization verifies; U6
Defender M1-M4 -- carried bundles are gated by their own day, the dry run is gated, the inner export keeps the owner
decision and the verifier sees only the real clock; B-defender D12 -- the v0.2 CLI only verifies the four thread
pins and records the real pools and CPU count. The structural entry-point ratchet is in
test_maker_replay_panel_entry_points.py.
"""
from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
import inspect
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from maker_core.replay import export_gate
from maker_core.replay.bundle import BundleError
from maker_core.replay.v2 import threads
from weather.market import maker_replay_bundle as bundle_v01
from weather.market import maker_replay_bundle_v02 as bundle_v02
from weather.market import maker_replay_night as night_v01
from weather.market import maker_replay_night_v02 as night_v02
from weather.market import maker_plugin_runner as runner
from weather.market.maker_plugin import replay_export

ROOT = Path(__file__).resolve().parents[2]
LATE = datetime(2026, 10, 20, tzinfo=timezone.utc)  # every gated day is closed by then
GATED = [(date(2026, 9, 30) + timedelta(days=n)).isoformat() for n in range(16)]
BOUNDARY = ["2026-09-29", "2026-10-16"]
GATE_CODE = "panel_export_requires_signed_registration"
PINNED = {name: "1" for name in threads.PINNED_VARIABLES}
MODULES = (bundle_v01, bundle_v02, night_v01, night_v02)
FIXED_NOW = datetime(2026, 10, 7, 1, tzinfo=timezone.utc)


class InputOpened(Exception):
    """Raised by the spy reader: an input was about to be opened."""


def _args(tmp_path, day):
    return SimpleNamespace(day=day, date=day, data_root=tmp_path / "no-input", out=tmp_path / "out",
                           release_root=None, markets=["chicago"], max_seconds=60.0, max_input_bytes=1024**2,
                           max_output_bytes=1024**2, max_records=1000, carry_bundle=[], kinds=None)


def _cli(tmp_path, day, command, flag="--day"):
    return [command, flag, day, "--data-root", str(tmp_path / "no-input"), "--out", str(tmp_path / "out")]


def _dry(tmp_path, day):
    return SimpleNamespace(date=day, data_root=tmp_path / "no-input", output=tmp_path / "out", markets=["chicago"],
                           max_seconds=60.0, max_output_bytes=1024**2, max_input_bytes=1024**2,
                           hypothetical_hazard_per_minute=None)


ENTRY_POINTS = {
    "maker_replay_night.export_day[panel]": lambda t, d: night_v01.export_day(_args(t, d), "panel", now=LATE),
    "maker_replay_night.export_day[calibration]":
        lambda t, d: night_v01.export_day(_args(t, d), "calibration", now=LATE),
    "maker_replay_night.main[night]": lambda t, d: night_v01.main(_cli(t, d, "night")),
    "maker_plugin.replay_export.main[night]": lambda t, d: replay_export.main(_cli(t, d, "night")),
    "maker_replay_night_v02.export_day[panel]": lambda t, d: night_v02.export_day(_args(t, d), "panel", now=LATE),
    "maker_replay_night_v02.export_day[calibration]":
        lambda t, d: night_v02.export_day(_args(t, d), "calibration", now=LATE),
    "maker_replay_night_v02.main[night]": lambda t, d: night_v02.main(_cli(t, d, "night"), environ=PINNED),
    "maker_replay_night_v02.main[calibration]":
        lambda t, d: night_v02.main(_cli(t, d, "calibration"), environ=PINNED),
    "maker_replay_bundle.export": lambda t, d: bundle_v01.export(_args(t, d), now=LATE),
    "maker_replay_bundle.main": lambda t, d: bundle_v01.main([*_cli(t, d, "bundle", "--date"), "--markets", "chicago"]),
    "maker_replay_bundle_v02.export": lambda t, d: bundle_v02.export(_args(t, d), now=LATE),
    "maker_replay_bundle_v02.main":
        lambda t, d: bundle_v02.main([*_cli(t, d, "bundle", "--date"), "--markets", "chicago"]),
    "maker_plugin_runner.run": lambda t, d: runner.run(_dry(t, d)),
    "maker_plugin_runner.main (dry_run)": lambda t, d: runner.main(
        ["--date", d, "--data-root", str(t / "no-input"), "--output", str(t / "out"), "--markets", "chicago"]),
}
# The module whose own gate call guards each entry point (the mutant removes exactly that one).
OWNER = {name: ((runner, "read_permitted") if name.startswith("maker_plugin_runner") else
                (night_v01, "export_permitted") if name.startswith(("maker_replay_night.", "maker_plugin.")) else
                (night_v02, "export_permitted") if name.startswith("maker_replay_night_v02") else
                (bundle_v01, "export_permitted") if name.startswith("maker_replay_bundle.") else
                (bundle_v02, "export_permitted")) for name in ENTRY_POINTS}


@pytest.fixture
def spies(monkeypatch):
    """Readers that refuse to open anything, and a record of every gate decision."""
    calls = []

    def reader(*args, **kwargs):
        raise InputOpened("input_opened")

    def gate(day, owner_decision=None):
        calls.append(day)
        result = export_gate.export_permitted(day, owner_decision)
        calls.append(("permitted", result))
        return result

    for module in MODULES:
        monkeypatch.setattr(module, "ExportReader", reader)
        monkeypatch.setattr(module, "export_permitted", gate)
    monkeypatch.setattr(runner, "Reader", reader)
    monkeypatch.setattr(runner, "read_permitted", gate)
    return calls


def refusal(entry, tmp_path, day, capsys):
    """The refusal text of one entry point (a raised error or a CLI's exit message)."""
    try:
        entry(tmp_path, day)
    except SystemExit as exc:
        assert exc.code == 2
        return capsys.readouterr().err
    except (BundleError, ValueError, InputOpened) as exc:
        return f"{type(exc).__name__}: {exc}"
    pytest.fail("entry point did not refuse")


@pytest.mark.parametrize("day", GATED)
@pytest.mark.parametrize("name", sorted(ENTRY_POINTS))
def test_every_entry_point_refuses_every_gated_day_before_any_input(tmp_path, capsys, spies, name, day):
    text = refusal(ENTRY_POINTS[name], tmp_path, day, capsys)
    assert GATE_CODE in text and "input_opened" not in text
    assert ("permitted", date.fromisoformat(day)) not in spies
    assert list(tmp_path.iterdir()) == []  # no output folder, ledger, lock or receipt


@pytest.mark.parametrize("day", BOUNDARY)
@pytest.mark.parametrize("name", sorted(ENTRY_POINTS))
def test_boundary_days_pass_the_gate_and_meet_the_next_refusal(tmp_path, capsys, spies, name, day):
    text = refusal(ENTRY_POINTS[name], tmp_path, day, capsys)
    assert ("permitted", date.fromisoformat(day)) in spies
    assert not any(code in text for code in export_gate.REFUSAL_CODES)


@pytest.mark.parametrize("name", sorted(ENTRY_POINTS))
def test_mutant_without_the_gate_in_one_entry_point_is_caught(tmp_path, capsys, monkeypatch, spies, name):
    module, attribute = OWNER[name]
    monkeypatch.setattr(module, attribute, lambda day, *a, **k: export_gate.utc_day(day))
    text = refusal(ENTRY_POINTS[name], tmp_path, "2026-10-01", capsys)
    assert GATE_CODE not in text  # so the 16-day test above fails for this mutant


def test_gated_window_is_exactly_sixteen_utc_days():
    assert sorted(export_gate.GATED_DAYS) == [date.fromisoformat(d) for d in GATED]
    assert export_gate.GATE_FIRST_UTC.tzinfo is timezone.utc and export_gate.GATE_END_UTC.tzinfo is timezone.utc
    assert [export_gate.gated(d) for d in BOUNDARY] == [False, False]
    assert all(export_gate.gated(d) and export_gate.gated(date.fromisoformat(d)) for d in GATED)


@pytest.mark.parametrize("day, code", [
    (datetime(2026, 9, 29, 23, tzinfo=timezone(timedelta(hours=-5))), "export_gate_day_required"),  # 09-30 UTC
    (datetime(2026, 10, 16, tzinfo=timezone.utc), "export_gate_day_required"),
    ("20260930", "export_gate_noncanonical_day"),
    ("2026-9-30", "export_gate_noncanonical_day"),
    (None, "export_gate_day_required"),
])
def test_ambiguous_days_are_refused_not_truncated(day, code):
    with pytest.raises(BundleError, match=code):
        export_gate.export_permitted(day)


def test_no_override_parameter_environment_variable_or_flag(monkeypatch):
    assert list(inspect.signature(export_gate.export_permitted).parameters) == ["day", "owner_decision"]
    assert export_gate.read_permitted is export_gate.export_permitted
    source = (ROOT / "src/maker_core/replay/export_gate.py").read_text(encoding="utf-8")
    assert "os.environ" not in source and "getenv" not in source and "argv" not in source
    assert export_gate.SIGNED_REGISTRATION_SHA256 is None
    for value in ("1", "true", "yes"):
        for name in ("WEATHER_PANEL_EXPORT", "PANEL_GATE_OVERRIDE", "FORCE"):
            monkeypatch.setenv(name, value)
    with pytest.raises(BundleError, match=GATE_CODE):
        export_gate.export_permitted("2026-10-03", ROOT / "decision.json")
    for module in (*MODULES, runner):
        assert not any(word in (inspect.getsource(module)) for word in ("--force", "--skip-gate", "--no-gate"))


def _signed(monkeypatch, verifier):
    """A test-only signature inside this process: the constant, a fake U4 module and a fixed real clock."""
    monkeypatch.setattr(export_gate, "SIGNED_REGISTRATION_SHA256", "a" * 64)
    module = ModuleType("maker_core.replay.v2.authorization")
    if verifier is not None:
        module.verify_export_decision = verifier
    monkeypatch.setattr(export_gate, "_authorization", module)
    monkeypatch.setattr(export_gate, "_utc_now", lambda: FIXED_NOW)


def test_signed_registration_still_needs_a_verified_owner_decision(monkeypatch):
    seen = []

    def verifier(path, **kwargs):
        seen.append((path, kwargs))
        return True

    _signed(monkeypatch, verifier)
    with pytest.raises(BundleError, match="panel_export_requires_owner_decision"):
        export_gate.export_permitted("2026-10-03")
    assert export_gate.export_permitted("2026-10-03", Path("decision.json")) == date(2026, 10, 3)
    assert seen == [(Path("decision.json"), dict(authorization_id="maker-replay-v2-v1", registration_sha256="a" * 64,
                                                 day=date(2026, 10, 3), now=FIXED_NOW))]


@pytest.mark.parametrize("result", [False, None, "yes", 1])
def test_a_verifier_that_does_not_return_true_refuses(monkeypatch, result):
    _signed(monkeypatch, lambda path, **kwargs: result)
    with pytest.raises(BundleError, match="panel_export_authorization_refused"):
        export_gate.export_permitted("2026-10-03", Path("decision.json"))


def test_a_verifier_error_propagates_as_a_refusal(monkeypatch):
    def verifier(path, **kwargs):
        raise BundleError("authorization_expired")

    _signed(monkeypatch, verifier)
    with pytest.raises(BundleError, match="authorization_expired"):
        export_gate.export_permitted("2026-10-03", Path("decision.json"))


def test_missing_v2_verifier_refuses(monkeypatch):
    _signed(monkeypatch, None)
    with pytest.raises(BundleError, match="panel_export_authorization_unavailable"):
        export_gate.export_permitted("2026-10-03", Path("decision.json"))
    monkeypatch.setattr(export_gate, "_authorization", None)  # U4 not landed
    with pytest.raises(BundleError, match="panel_export_authorization_unavailable"):
        export_gate.export_permitted("2026-10-03", Path("decision.json"))


# ------------------------------------------------------------------------------------------- thread pins
@pytest.mark.parametrize("missing", [None, *threads.PINNED_VARIABLES])
def test_thread_check_refuses_unless_all_four_pins_are_one(missing):
    environ = dict(PINNED)
    if missing is None:
        environ = {}
    else:
        environ[missing] = "2"
    with pytest.raises(BundleError, match="blas_threads_not_pinned"):
        threads.check_thread_pins(environ)


def test_thread_record_has_pins_cpu_count_and_actual_pools():
    record = threads.check_thread_pins(PINNED)
    assert record["environment"] == PINNED and record["pinned"] is True
    assert record["logical_cpus"] == os.cpu_count()
    pytest.importorskip("threadpoolctl")
    assert record["threadpoolctl"] != "absent" and isinstance(record["pools"], list)
    for pool in record["pools"]:
        assert set(pool) == {"user_api", "internal_api", "prefix", "num_threads"}
        assert isinstance(pool["num_threads"], int)


def test_thread_record_says_when_threadpoolctl_is_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "threadpoolctl", None)
    record = threads.check_thread_pins(PINNED)
    assert record["threadpoolctl"] == "absent" and record["pools"] is None


def test_thread_check_never_sets_the_environment(monkeypatch):
    for name in threads.PINNED_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(BundleError):
        threads.check_thread_pins(os.environ)
    assert not any(name in os.environ for name in threads.PINNED_VARIABLES)
    assert "environ[" not in inspect.getsource(threads) and "putenv" not in inspect.getsource(threads)


@pytest.mark.parametrize("command", ["night", "calibration"])
def test_v02_cli_refuses_unpinned_threads_before_any_output(tmp_path, capsys, spies, command):
    day = "2026-09-28"
    with pytest.raises(SystemExit) as exc:
        night_v02.main(_cli(tmp_path, day, command), environ={})
    assert exc.value.code == 2 and "blas_threads_not_pinned" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
    # The panel gate still comes first.
    with pytest.raises(SystemExit):
        night_v02.main(_cli(tmp_path, "2026-10-01", command), environ={})
    assert GATE_CODE in capsys.readouterr().err


def test_v02_cli_defaults_to_the_process_environment(tmp_path, capsys, spies, monkeypatch):
    for name in threads.PINNED_VARIABLES:
        monkeypatch.setenv(name, "4")
    with pytest.raises(SystemExit):
        night_v02.main(_cli(tmp_path, "2026-09-28", "night"))
    assert "blas_threads_not_pinned" in capsys.readouterr().err
    assert night_v02.main(["module-hash"]) == 0  # module-hash reads no data and needs no pins


def test_v02_receipt_records_threads(tmp_path):
    from tests.market.test_maker_replay_night import LATER, receipt, setup

    args, _ = setup(tmp_path)
    report = night_v02.export_day(args, "panel", now=LATER, environ=PINNED)
    assert report["status"] == "SEALED"
    recorded = receipt(args)["threads"]
    assert recorded["environment"] == PINNED and recorded["pinned"] is True
    assert recorded["logical_cpus"] == os.cpu_count() and "pools" in recorded and "threadpoolctl" in recorded
    # In-process callers without an environ are recorded, not refused.
    other = SimpleNamespace(**{**vars(args), "out": tmp_path / "other"})
    assert set(night_v02.export_day(other, "panel", now=LATER)["threads"]) == set(recorded)


def test_exporter_closure_has_no_blas_reductions():
    """B-defender D13: thread pins are for memory and CPU; nothing on the export hash path may route through BLAS."""
    files = [ROOT / "src/weather/market" / name for name in ("maker_replay_bundle.py", "maker_replay_bundle_v02.py",
                                                             "maker_replay_night.py", "maker_replay_night_v02.py")]
    files += sorted((ROOT / "src/weather/market/maker_plugin").glob("*.py"))
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [f"{node.module}.{a.name}" for a in node.names] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n.split(".")[0] in ("numpy", "scipy") and "linalg" in n for n in names), path
            assert not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.MatMult)), path
            assert not (isinstance(node, ast.Attribute) and node.attr in ("dot", "matmul", "einsum")
                        and isinstance(node.value, ast.Name) and node.value.id in ("np", "numpy")), path


def test_the_verifier_sees_the_real_clock_never_a_callers_now(monkeypatch):
    """U6 Defender M4: exporters still accept ``now`` for closed-day checks, but it never reaches authorization."""
    seen = []
    _signed(monkeypatch, lambda path, **kwargs: seen.append(kwargs["now"]) or True)
    assert "now" not in inspect.signature(export_gate.export_permitted).parameters
    with pytest.raises(TypeError):
        export_gate.export_permitted("2026-10-03", Path("decision.json"), now=LATE)
    export_gate.export_permitted("2026-10-03", Path("decision.json"))
    assert seen == [FIXED_NOW]
    source = (ROOT / "src/maker_core/replay/export_gate.py").read_text(encoding="utf-8")
    assert "now=_utc_now()" in source


def test_authorization_module_is_imported_eagerly_for_the_module_hash():
    """U6 Defender M3: the gate imports v2.authorization at import time, so module-hash covers it once U4 lands."""
    tree = ast.parse((ROOT / "src/maker_core/replay/export_gate.py").read_text(encoding="utf-8"))
    eager = [node for node in tree.body if isinstance(node, ast.Try)
             and any(isinstance(s, ast.ImportFrom) and s.module == "maker_core.replay.v2"
                     and [a.name for a in s.names] == ["authorization"] for s in node.body)]
    assert eager
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for fn in ast.walk(tree)
                   if isinstance(fn, ast.FunctionDef) for node in ast.walk(fn))


def _bundle_manifest(folder, day):
    folder.mkdir(parents=True)
    (folder / "bundle.json").write_text('{"day": "%s", "conditions": []}' % day, encoding="ascii")
    return folder


@pytest.mark.parametrize("exporter", [bundle_v01, bundle_v02])
def test_a_carried_gated_bundle_is_refused_before_any_input(tmp_path, capsys, spies, exporter):
    """U6 Defender M1: --carry-bundle of a 10-15 bundle into a 10-16 export is refused by the carried day."""
    carried = _bundle_manifest(tmp_path / "carry" / "2026-10-15" / "bundle", "2026-10-15")
    args = _args(tmp_path, "2026-10-16")
    args.carry_bundle = [carried]
    with pytest.raises(BundleError, match=GATE_CODE):
        exporter.export(args, now=LATE)
    assert not args.out.exists() and not args.out.with_name("out.partial").exists()
    assert "2026-10-15" in spies and ("permitted", date(2026, 10, 15)) not in spies
    args.carry_bundle = [_bundle_manifest(tmp_path / "carry" / "2026-09-29" / "bundle", "2026-09-29")]
    with pytest.raises(InputOpened):  # the ungated carried day passes; the next step opens input
        exporter.export(args, now=LATE)


def test_a_carried_bundle_needs_a_bounded_manifest(tmp_path, spies):
    args = _args(tmp_path, "2026-10-16")
    (tmp_path / "carry").mkdir()
    args.carry_bundle = [tmp_path / "carry"]
    with pytest.raises(BundleError, match="carry_bundle_manifest_required"):
        bundle_v01.export(args, now=LATE)


@pytest.mark.parametrize("module", [night_v01, night_v02])
def test_signed_night_export_end_to_end_keeps_the_decision_and_a_refusal_never_poisons_the_ledger(
        tmp_path, monkeypatch, module):
    """U6 Defender M3, through a whole night export of the fictional fixture day, made 'gated' for this test only."""
    from tests.market.test_maker_replay_night import LATER, setup

    args, _ = setup(tmp_path)
    fixture_day = date.fromisoformat(args.day)
    monkeypatch.setattr(export_gate, "GATE_FIRST_UTC", datetime.combine(fixture_day, datetime.min.time(), timezone.utc))
    monkeypatch.setattr(export_gate, "GATE_END_UTC",
                        datetime.combine(fixture_day + timedelta(days=1), datetime.min.time(), timezone.utc))
    ledger = args.out / module.KINDS["panel"]["ledger"]
    # Unsigned: refused before anything is created, so the day stays exportable.
    with pytest.raises(BundleError, match=GATE_CODE):
        module.export_day(args, "panel", now=LATER)
    assert not args.out.exists()
    # Signed in this process only, with a decision: verified by the outer and the inner gate, then sealed.
    calls = []
    _signed(monkeypatch, lambda path, **kwargs: calls.append((path, kwargs)) or True)
    with pytest.raises(BundleError, match="panel_export_requires_owner_decision"):
        module.export_day(args, "panel", now=LATER)
    assert not args.out.exists()
    args.owner_decision = tmp_path / "decision.json"
    closure = module.module_sha256(module.module_closure()) if hasattr(module, "module_sha256") else None
    receipt = module.export_day(args, "panel", now=LATER)
    assert receipt["status"] == "SEALED" and receipt["day"] == args.day
    expected = (args.owner_decision, dict(authorization_id="maker-replay-v2-v1", registration_sha256="a" * 64,
                                          day=fixture_day, now=FIXED_NOW))
    assert calls == [expected, expected]
    assert [json.loads(line)["status"] for line in ledger.read_bytes().splitlines()] == ["SEALED"]
    if closure is not None:
        assert receipt["module_sha256"] == closure  # nothing new loads on the gated path
