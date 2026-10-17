"""Item 330 build 4 (c): ``python -m maker_core.frontier.cli`` calibrate and score, on SYNTHETIC v0.2 bundles only.

Guards: the frontier CLI builds day sources only through ``intervals.sources`` (declared windows, a required
  inventory, v0.1 refused); calibrate reads only the calibration days, drops bands closing in a refused window
  and writes a create-only report and receipt with input hashes, commit and digests; score refuses before
  2026-11-14T00:00Z by the real clock, without a pinned signed registration matching decay, fill binding, grid
  and decision rule, outside the 10-16..11-13 panel, and while no intervals panel covers it; the runner
  honours declared windows; event-day clusters sum to one run over the kept bands.
"""
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from maker_core.frontier import adapters, cli, decision, embargo, prereg, runner
from maker_core.frontier.grid import GRID, GRID_HASH
from maker_core.frontier.share_decay import DecayModel
from maker_core.replay.v2.panel import CALIBRATION_DATES
from .fixtures.panel_v02 import Panel
from .fixtures.replay_scenario import Scenario
from .fixtures.toxicity_synthetic import synthetic_records
from .test_frontier_adapters import PINNED_RE1_DECAY_DIGEST, tape_row, write_tape

UTC = timezone.utc
FIXTURES = Path(__file__).parent / "fixtures"
COMMIT = "c" * 40
AFTER = datetime(2026, 11, 14, 0, 0, 1, tzinfo=UTC)
DECAY = DecayModel(5.0, 5.0, 20.0, ())
PANEL_DAYS = [date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)]


def fixture():
    return Panel(("austin", "toronto"), bands=1, step=60, full=True)


def bundles(tmp_path, days, *, provenance="synthetic", name="bundles"):
    """Synthetic v0.2 bundles plus the rehearsal inventory document for ``days``; returns (dirs, inventory)."""
    panel = fixture()
    dirs = [panel.write(tmp_path / name / d.isoformat(), d, provenance=provenance) for d in days]
    path = tmp_path / name / "inventory.json"
    path.write_text(json.dumps({"format": cli.INVENTORY_FORMAT, "dates": [d.isoformat() for d in sorted(days)],
                                "rows": panel.inventory(days)}), encoding="utf-8")
    return dirs, path


def manifest_only(tmp_path, days):
    """Bundle folders holding only a manifest: for refusals that must happen before any stream is opened."""
    dirs = []
    for d in days:
        folder = tmp_path / "manifests" / d.isoformat()
        folder.mkdir(parents=True)
        (folder / "bundle.json").write_text(json.dumps({"format": "maker-core.replay-bundle.v0.2",
                                                        "day": d.isoformat()}), encoding="utf-8")
        dirs.append(folder)
    inventory = tmp_path / "manifests" / "inventory.json"
    inventory.write_text("{}", encoding="utf-8")
    return dirs, inventory


def argv(command, dirs, inventory, out, *extra):
    args = [command, "--re1-projection", str(FIXTURES / "re1_sessions.json"),
            "--re1-selections", str(FIXTURES / "re1_price_parity.json"), "--inventory", str(inventory),
            "--out-dir", str(out), "--code-commit", COMMIT]
    for d in dirs:
        args += ["--bundle", str(d)]
    return args + list(extra)


def refusal(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])["refused"]


def fit_check(*values):
    embargo.check("fit", *values)


# -- calibrate -----------------------------------------------------------------------------------------------
def test_calibrate_writes_a_create_only_report_and_receipt(tmp_path, capsys):
    dirs, inventory = bundles(tmp_path, CALIBRATION_DATES)
    out = tmp_path / "out"
    assert cli.main(argv("calibrate", dirs, inventory, out, "--replicates", "199")) == 0
    report = json.loads((out / "report.json").read_bytes())
    receipt = json.loads((out / "receipt.json").read_bytes())
    assert report["label"] == "DESCRIPTIVE" and report["authority"] == "none"
    assert report["intervals"]["panel"] == "calibration" and report["intervals"]["windows"] > 0
    assert report["decision"]["verdict"] == "NO_GO" and report["decision"]["reasons"] == ["underpowered_clusters"]
    # every band of 09-29 closes on or after 09-30 and is dropped, never handed to the runner
    dropped_days = {b["day"] for b in report["embargoed_bands"]}
    assert "2026-09-29" in dropped_days and set(report["runs"]) and max(report["runs"]) <= "2026-09-29"
    assert receipt["code"]["commit"] == COMMIT
    assert set(receipt["code"]["modules"]) >= {"maker_core.frontier.decision", "maker_core.replay.fill_v3",
                                               "maker_core.quoting.fill_cost", "maker_core.frontier.cli"}
    assert receipt["digests"]["decay"] == PINNED_RE1_DECAY_DIGEST and receipt["digests"]["grid_hash"] == GRID_HASH
    assert receipt["digests"]["fill_model_binding"] == adapters.FILL_V3_BINDING
    assert receipt["digests"]["decision_rule"] == replace(decision.PROPOSED_RULE, replicates=199).digest()
    assert receipt["digests"]["report_sha256"] == hashlib.sha256((out / "report.json").read_bytes()).hexdigest()
    assert receipt["inputs"]["inventory_sha256"] == hashlib.sha256(inventory.read_bytes()).hexdigest()
    assert [b["manifest_sha256"] for b in receipt["inputs"]["bundles"]] == [
        hashlib.sha256((d / "bundle.json").read_bytes()).hexdigest() for d in dirs]
    assert receipt["inputs"]["re1"]["re1_sessions.json"] == hashlib.sha256(
        (FIXTURES / "re1_sessions.json").read_bytes()).hexdigest()
    before = (out / "report.json").read_bytes()
    assert cli.main(argv("calibrate", dirs, inventory, out, "--replicates", "199")) == 2
    assert refusal(capsys) == "out_dir_exists" and (out / "report.json").read_bytes() == before


@pytest.mark.parametrize("day,reason", [(date(2026, 9, 30), "reserved_window"), (date(2026, 10, 15), "reserved_window"),
                                        (date(2026, 10, 20), "fit_after_cutoff"), (date(2026, 11, 20), "fit_after_cutoff")])
def test_calibrate_refuses_any_day_after_the_fit_cutoff_before_opening_it(tmp_path, capsys, monkeypatch, day, reason):
    dirs, inventory = manifest_only(tmp_path, [day])
    opened = []
    monkeypatch.setattr(cli, "open_bundle", lambda d: opened.append(d))
    assert cli.main(argv("calibrate", dirs, inventory, tmp_path / "out")) == 2
    assert refusal(capsys) == reason and opened == [] and not (tmp_path / "out").exists()


def test_calibrate_reads_only_the_calibration_panel_days(tmp_path, capsys):
    dirs, inventory = bundles(tmp_path, [date(2026, 9, 20)])
    assert cli.main(argv("calibrate", dirs, inventory, tmp_path / "out")) == 2
    assert refusal(capsys) == "day_outside_panel"


def test_a_v01_bundle_is_refused(tmp_path, capsys):
    s = Scenario(day=CALIBRATION_DATES[0], minutes=8)
    s.bundle(tmp_path / "v01")
    _, inventory = bundles(tmp_path, CALIBRATION_DATES[:1])
    assert cli.main(argv("calibrate", [tmp_path / "v01"], inventory, tmp_path / "out")) == 2
    assert refusal(capsys) == "v01_bundle_unsupported"


def test_the_inventory_must_name_the_bundle_days(tmp_path, capsys):
    dirs, _ = bundles(tmp_path, CALIBRATION_DATES[:1])
    _, other = bundles(tmp_path, CALIBRATION_DATES[1:2], name="other")
    assert cli.main(argv("calibrate", dirs, other, tmp_path / "out")) == 2
    assert refusal(capsys) == "inventory_dates_mismatch"


def test_a_commit_is_required(tmp_path, capsys):
    dirs, inventory = manifest_only(tmp_path, [CALIBRATION_DATES[0]])
    args = argv("calibrate", dirs, inventory, tmp_path / "out")
    args[args.index(COMMIT)] = "HEAD"
    assert cli.main(args) == 2 and refusal(capsys) == "code_commit_must_be_40_hex"


# -- the sanctioned source path ----------------------------------------------------------------------------
def test_a_captured_bundle_gets_declared_windows_through_intervals_sources(tmp_path, capsys):
    dirs, inventory = bundles(tmp_path, CALIBRATION_DATES, provenance="captured")
    rows, _ = cli.read_inventory(inventory, CALIBRATION_DATES)
    sources, evaluation = cli.open_sources(dirs, rows, "calibration")
    assert all(s.plan.declared and s.plan.provenance == "captured" for s in sources)
    declared = {(w["condition_id"], w["start"], w["end"]) for w in evaluation.windows}
    for s in sources:
        for cid, spans in s.plan.windows.items():
            for start, end in spans:
                assert (cid, start.isoformat(), end.isoformat()) in declared
                # maintenance minutes [05:00, 08:00) UTC are never active
                maintenance = datetime.combine(s.plan.day, time(5), tzinfo=UTC)
                assert end <= maintenance or start >= maintenance + timedelta(hours=3)
    assert any(e["reason"] == "MAINTENANCE_UTC" for e in evaluation.exclusions)
    assert cli.main(argv("calibrate", dirs, inventory, tmp_path / "out", "--replicates", "199")) == 0


def test_the_runner_quotes_only_inside_declared_windows(tmp_path):
    dirs, inventory = bundles(tmp_path, CALIBRATION_DATES[:1])
    rows, _ = cli.read_inventory(inventory, CALIBRATION_DATES[:1])
    (source,), _ = cli.open_sources(dirs, rows, "calibration")
    kept = cli.clusters([source], fit_check, drop_embargoed=True)
    sources = [s for group in kept.values() for s in group]
    quoting = runner.run(sources, decay=DECAY)["strategies"]
    assert any(quoting[p.label]["quoted_seconds"] > 0 for p in GRID)
    closed = [replace(s, plan=replace(s.plan, windows={})) for s in sources]
    silent = runner.run(closed, decay=DECAY)["strategies"]
    assert all(silent[p.label]["quoted_seconds"] == 0 and silent[p.label]["quotes"] == 0 for p in GRID)


def test_event_day_clusters_sum_to_one_run_over_the_kept_bands(tmp_path):
    dirs, inventory = bundles(tmp_path, CALIBRATION_DATES[:2])
    rows, _ = cli.read_inventory(inventory, CALIBRATION_DATES[:2])
    sources, _ = cli.open_sources(dirs, rows, "calibration")
    dropped = set()
    split = cli.clusters(sources, fit_check, drop_embargoed=True, dropped=dropped)
    assert len(split) >= 2 and dropped
    kept = [cli.restrict(s, cli.event_days(s, fit_check, drop_embargoed=True)[0]) for s in sources]
    whole = runner.run(kept, decay=DECAY)["strategies"]
    parts = [runner.run(group, decay=DECAY)["strategies"] for group in split.values()]
    for point in GRID:
        label = point.label
        assert sum(p[label]["quoted_seconds"] for p in parts) == pytest.approx(whole[label]["quoted_seconds"])
        assert sum(p[label]["reward"]["central"] for p in parts) == pytest.approx(whole[label]["reward"]["central"])
        assert sum(p[label]["filled_shares"] for p in parts) == whole[label]["filled_shares"]
    assert any(whole[p.label]["quoted_seconds"] for p in GRID)


def test_calibrate_wires_the_real_fill_cost_and_the_tape(tmp_path, capsys):
    from maker_core.quoting.fill_cost import TableFillCostProvider
    from maker_core.replay import toxicity as tx
    table = tx.fit(*synthetic_records(dates=12, markets=12, minutes_per_cell=12, seed=11), replicates=100)
    table_path = tmp_path / "table.json"
    table_path.write_text(json.dumps(table), encoding="utf-8")
    expected = TableFillCostProvider(json.loads(table_path.read_text(encoding="utf-8"))).digest
    day = CALIBRATION_DATES[0]
    dirs, inventory = bundles(tmp_path, [day])
    start = datetime.combine(day, time(), tzinfo=UTC)
    cids = [r["condition_id"] for r in fixture().inventory([day])]
    write_tape(tmp_path / "tape", day, [tape_row(cid, side, start + timedelta(minutes=k))
                                       for cid in cids for side in ("YES", "NO") for k in range(0, 1440, 60)])
    out = tmp_path / "out"
    args = argv("calibrate", dirs, inventory, out, "--replicates", "199", "--toxicity-table", str(table_path),
                "--toxicity-table-digest", expected, "--cf-tape", str(tmp_path / "tape"))
    assert cli.main(args) == 0
    report = json.loads((out / "report.json").read_bytes())
    receipt = json.loads((out / "receipt.json").read_bytes())
    assert report["fill_cost"]["table_digest"] == expected and report["fill_cost"]["decisions"] > 0
    assert receipt["inputs"]["cf_tape_days"][day.isoformat()]["rows"] == len(cids) * 2 * 24
    assert receipt["digests"]["toxicity_table"] == expected
    bad = argv("calibrate", dirs, inventory, tmp_path / "out2", "--toxicity-table", str(table_path),
               "--toxicity-table-digest", "0" * 64, "--cf-tape", str(tmp_path / "tape"))
    assert cli.main(bad) == 2 and refusal(capsys) == "toxicity_table_digest_mismatch"


# -- score ---------------------------------------------------------------------------------------------------
def registration(rule=None, fill=None, decay=None):
    return ("# synthetic registration\n\nGrid hash: `%s`\n\nDecay digest: `%s`\n\nFill model: `%s`\n\n"
            "Decision rule digest: `%s`\n\nSigned: Test Owner, 2026-11-01\n"
            % (GRID_HASH, decay or PINNED_RE1_DECAY_DIGEST, fill or adapters.FILL_V3_BINDING,
               (rule or cli.SCORED_RULE).digest())).encode()


def pinned(tmp_path, monkeypatch, document=None):
    document = document or registration()
    path = tmp_path / "registration.md"
    path.write_bytes(document)
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", prereg.registration_hash(document))
    return path


def score(tmp_path, days, *extra):
    dirs, inventory = manifest_only(tmp_path, days)
    return argv("score", dirs, inventory, tmp_path / "out", "--registration", str(tmp_path / "registration.md"),
                *extra)


@pytest.mark.parametrize("now", [datetime(2026, 11, 13, 23, 59, 59, tzinfo=UTC),
                                 datetime(2026, 11, 14, 0, 0, tzinfo=timezone(timedelta(hours=1)))])
def test_score_refuses_before_the_panel_closes(tmp_path, capsys, monkeypatch, now):
    pinned(tmp_path, monkeypatch)
    assert cli.main(score(tmp_path, PANEL_DAYS[:1]), clock=lambda: now) == 2
    assert refusal(capsys).startswith("score_refused_before_2026-11-14T00:00:00")


def test_score_reads_the_real_utc_clock_by_default(tmp_path, capsys, monkeypatch):
    real = cli.utc_now()
    assert real.tzinfo is not None and abs((real - datetime.now(UTC)).total_seconds()) < 60
    monkeypatch.setattr(cli, "utc_now", lambda: datetime(2026, 10, 16, 12, tzinfo=UTC))
    pinned(tmp_path, monkeypatch)
    assert cli.main(score(tmp_path, PANEL_DAYS[:1])) == 2
    assert refusal(capsys).startswith("score_refused_before")


def test_score_refuses_without_a_pinned_registration(tmp_path, capsys):
    assert prereg.SIGNED_PREREGISTRATION_SHA256 is None
    (tmp_path / "registration.md").write_bytes(registration())
    assert cli.main(score(tmp_path, PANEL_DAYS[:1]), clock=lambda: AFTER) == 2
    assert refusal(capsys) == "no_signed_preregistration"


@pytest.mark.parametrize("document,reason", [
    (lambda: registration(rule=replace(decision.PROPOSED_RULE, min_effect_cents=.05)), "decision_rule_digest_mismatch"),
    (lambda: registration().replace(b"Decision rule digest", b"Decision digest"), "decision_rule_digest_mismatch"),
    (lambda: registration(fill="maker_core.frontier.seams.PricePathFillModel@v2-price-path.1:v2-strictly_through"),
     "fill_model_mismatch"),
    (lambda: registration(decay="0" * 64), "decay_digest_mismatch"),
    (lambda: registration().replace(b"Test Owner, 2026-11-01", b"UNSIGNED"), "preregistration_unsigned"),
])
def test_score_refuses_a_registration_that_does_not_bind_this_run(tmp_path, capsys, monkeypatch, document, reason):
    pinned(tmp_path, monkeypatch, document())
    assert cli.main(score(tmp_path, PANEL_DAYS[:1]), clock=lambda: AFTER) == 2
    assert refusal(capsys) == reason


@pytest.mark.parametrize("day", [date(2026, 11, 20), date(2026, 10, 15), date(2026, 9, 28)])
def test_score_reads_only_the_panel_and_checks_before_opening(tmp_path, capsys, monkeypatch, day):
    pinned(tmp_path, monkeypatch)
    opened = []
    monkeypatch.setattr(cli, "open_bundle", lambda d: opened.append(d))
    assert cli.main(score(tmp_path, [day]), clock=lambda: AFTER) == 2
    assert refusal(capsys) == "score_reads_only_the_scored_panel" and opened == []


def test_score_refuses_while_no_intervals_panel_covers_the_scored_panel(tmp_path, capsys, monkeypatch):
    """A matching pinned signed registration on panel days still stops here: no ``panel.PANELS`` name declares
    windows for 10-16..11-13, and the CLI builds sources only through ``intervals.sources``."""
    from maker_core.replay.v2 import panel
    assert cli.SCORED_INTERVALS_PANEL is None
    assert all(not set(PANEL_DAYS) & set(days) for days in (panel.QUOTE_DATES, panel.CALIBRATION_DATES))
    pinned(tmp_path, monkeypatch)
    opened = []
    monkeypatch.setattr(cli, "open_bundle", lambda d: opened.append(d))
    assert cli.main(score(tmp_path, PANEL_DAYS), clock=lambda: AFTER) == 2
    assert refusal(capsys) == "score_has_no_intervals_panel" and opened == []
    assert not (tmp_path / "out").exists()


def test_the_cli_module_reads_no_environment_and_spawns_nothing():
    text = Path(cli.__file__).read_text(encoding="utf-8")
    for forbidden in ("environ", "getenv", "subprocess", "dotenv"):
        assert forbidden not in text
