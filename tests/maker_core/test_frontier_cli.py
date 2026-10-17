"""Item 330 build 4 (c): ``python -m maker_core.frontier.cli`` calibrate and score, on SYNTHETIC v0.2 bundles only.

Guards: the frontier CLI builds day sources only through ``intervals.sources`` (declared windows, a required
  inventory, v0.1 refused); calibrate reads only the calibration days, drops bands closing in a refused window
  from descriptor metadata alone (no other record or tape row of a dropped band is decoded or indexed),
  receipts per-day and per-horizon kept/dropped counts, refuses a fully embargoed horizon, is labelled
  PIPELINE REHEARSAL and writes a create-only report and receipt with input hashes, commit and digests; score
  refuses before 2026-11-14T00:00Z by the real clock, without a pinned signed registration matching decay,
  fill binding, grid and decision rule, outside the 10-16..11-13 panel, and while no intervals panel covers
  it; the runner honours declared windows minute by minute and reads condition envelopes as half-open;
  event-day clusters sum to one run over the kept bands.
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
from .fixtures.frontier_cost_stub import STUB_TABLE_DIGEST
from .fixtures.panel_v02 import ZONES, Panel, cid_of, close_of
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


def schedules(bundles_opened):
    return {b.day: cli.schedule(b, fit_check, drop_embargoed=True) for b in bundles_opened}


def fixture_dropped(days):
    """The bands the fixture closes on or after 09-30, from its own schedule (independent of the CLI)."""
    cut = datetime(2026, 9, 30, tzinfo=UTC)
    return {r["condition_id"] for r in fixture().inventory(days)
            if close_of(r["market_id"], date.fromisoformat(r["target_date"])) >= cut}


# -- calibrate -----------------------------------------------------------------------------------------------
def test_calibrate_writes_a_create_only_report_and_receipt(tmp_path, capsys):
    dirs, inventory = bundles(tmp_path, CALIBRATION_DATES)
    out = tmp_path / "out"
    assert cli.main(argv("calibrate", dirs, inventory, out, "--replicates", "199")) == 0
    printed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert printed["label"] == "PIPELINE REHEARSAL" and "not a power estimate" in printed["note"]
    report = json.loads((out / "report.json").read_bytes())
    receipt = json.loads((out / "receipt.json").read_bytes())
    assert report["label"] == receipt["label"] == "PIPELINE REHEARSAL" and report["authority"] == "none"
    assert "margin" in receipt["note"] and "not a power estimate" in receipt["note"]
    assert report["intervals"]["panel"] == "calibration" and report["intervals"]["windows"] > 0
    assert report["decision"]["verdict"] == "NO_GO"
    assert report["decision"]["reasons"] == ["underpowered_clusters", "margin_unsigned"]
    # bands closing on or after 09-30 are dropped, never handed to the runner
    embargo_block = receipt["embargo"]
    assert embargo_block == report["embargo"]
    assert {b["condition_id"] for b in embargo_block["embargoed_bands"]} == fixture_dropped(CALIBRATION_DATES)
    counts = embargo_block["counts_by_day_and_horizon"]
    assert sum(c["dropped"] for d in CALIBRATION_DATES for c in counts[d.isoformat()].values()) == len(
        embargo_block["embargoed_bands"])
    assert all(c["kept"] == 0 for h, c in counts["2026-09-29"].items() if h in ("1", "2"))
    assert all(c["kept"] > 0 for c in counts["all"].values())
    assert set(report["runs"]) and max(report["runs"]) <= "2026-09-29"
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


@pytest.mark.parametrize("days,horizons", [((date(2026, 9, 28),), "2"), ((date(2026, 9, 29),), "1,2")])
def test_a_horizon_with_every_band_dropped_refuses_calibrate(tmp_path, capsys, days, horizons):
    """An empty calibration is never a pass."""
    dirs, inventory = bundles(tmp_path, days)
    assert cli.main(argv("calibrate", dirs, inventory, tmp_path / "out")) == 2
    assert refusal(capsys) == "calibrate_horizon_fully_embargoed: horizon " + horizons
    assert not (tmp_path / "out").exists()


def test_a_dropped_band_is_decided_from_its_descriptors_and_nothing_else_is_read(tmp_path, capsys, monkeypatch):
    """The drop reads schedule metadata only. Spies fail on: any non-descriptor record of a dropped band being
    decoded (every replay decode goes through ``lockstep.decode_record``); any record of a dropped band, its
    descriptors included, reaching the runner; and any tape row of a dropped band being materialised."""
    from maker_core.quoting.fill_cost import TableFillCostProvider
    from maker_core.replay import toxicity as tx
    from maker_core.replay.v2 import lockstep, universe_v02
    days = CALIBRATION_DATES
    dropped = fixture_dropped(days)
    assert dropped
    dirs, inventory = bundles(tmp_path, days)
    group_of = {"g-" + cid: cid for cid in dropped}
    touched = []

    real_decode = lockstep.decode_record

    def decode_spy(record):
        cid = getattr(record, "condition_id", None) or group_of.get(getattr(record, "group_id", None))
        if cid in dropped and record.kind != "descriptor":  # descriptors are the schedule metadata
            touched.append((record.kind, cid))
            raise AssertionError("a dropped band's record was decoded: %s" % record.kind)
        return real_decode(record)

    real_items = runner.items

    def runner_items_spy(source):
        for at, batch in real_items(source):
            hit = [item.kind for item in batch if item.condition_id in dropped]
            if hit:
                touched.extend(hit)
                raise AssertionError("a dropped band reached the runner: %s" % hit)
            yield at, batch

    descriptor_reads = []
    real_descriptors = universe_v02.descriptors

    def descriptors_spy(bundle):
        records = real_descriptors(bundle)
        descriptor_reads.extend(r.kind for r in records)
        return records

    monkeypatch.setattr(lockstep, "decode_record", decode_spy)
    monkeypatch.setattr(runner, "items", runner_items_spy)
    monkeypatch.setattr(universe_v02, "descriptors", descriptors_spy)
    real_load = adapters.CfTapeContexts._load

    def load_spy(self, day):
        index = real_load(self, day)
        assert not {cid for cid, _ in index} & dropped, "a dropped band's tape row was materialised"
        return index

    monkeypatch.setattr(adapters.CfTapeContexts, "_load", load_spy)
    table = tx.fit(*synthetic_records(dates=12, markets=12, minutes_per_cell=12, seed=11), replicates=100)
    table_path = tmp_path / "table.json"
    table_path.write_text(json.dumps(table), encoding="utf-8")
    expected = TableFillCostProvider(json.loads(table_path.read_text(encoding="utf-8"))).digest
    for day in days:  # tape rows for every band, dropped ones included
        start = datetime.combine(day, time(), tzinfo=UTC)
        write_tape(tmp_path / "tape", day, [tape_row(r["condition_id"], side, start + timedelta(minutes=k))
                                           for r in fixture().inventory([day]) for side in ("YES", "NO")
                                           for k in range(0, 1440, 60)])
    args = argv("calibrate", dirs, inventory, tmp_path / "out", "--replicates", "199", "--toxicity-table",
                str(table_path), "--toxicity-table-digest", expected, "--cf-tape", str(tmp_path / "tape"))
    assert cli.main(args) == 0, capsys.readouterr().out
    assert touched == [] and set(descriptor_reads) == {"descriptor"}
    report = json.loads((tmp_path / "out" / "report.json").read_bytes())
    assert {b["condition_id"] for b in report["embargo"]["embargoed_bands"]} == dropped
    assert report["fill_cost"]["decisions"] > 0
    contexts = adapters.CfTapeContexts(tmp_path / "tape", purpose="descriptive", conditions=set())
    with pytest.raises(adapters.AdapterRefused, match="cf_tape_condition_not_kept"):
        contexts(condition_id=sorted(dropped)[0], at=datetime.combine(days[0], time(1), tzinfo=UTC))


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
    _, sources, evaluation = cli.open_sources(dirs, rows, "calibration")
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
    opened, (source,), _ = cli.open_sources(dirs, rows, "calibration")
    kept = cli.clusters([source], schedules(opened))
    sources = [s for group in kept.values() for s in group]
    quoting = runner.run(sources, decay=DECAY)["strategies"]
    assert any(quoting[p.label]["quoted_seconds"] > 0 for p in GRID)
    closed = [replace(s, plan=replace(s.plan, windows={})) for s in sources]
    silent = runner.run(closed, decay=DECAY)["strategies"]
    assert all(silent[p.label]["quoted_seconds"] == 0 and silent[p.label]["quotes"] == 0 for p in GRID)


def test_capture_day_clusters_sum_to_one_run_over_the_kept_bands(tmp_path):
    dirs, inventory = bundles(tmp_path, CALIBRATION_DATES[:2])
    rows, _ = cli.read_inventory(inventory, CALIBRATION_DATES[:2])
    opened, sources, _ = cli.open_sources(dirs, rows, "calibration")
    plans = schedules(opened)
    split = cli.clusters(sources, plans)
    assert len(split) >= 2 and any(p.dropped for p in plans.values())
    kept = [cli.restrict(s, plans[s.plan.day].event_days) for s in sources]
    whole = runner.run(kept, decay=DECAY)["strategies"]
    parts = [runner.run(group, decay=DECAY)["strategies"] for group in split.values()]
    for point in GRID:
        label = point.label
        assert sum(p[label]["quoted_seconds"] for p in parts) == pytest.approx(whole[label]["quoted_seconds"])
        assert sum(p[label]["reward"]["central"] for p in parts) == pytest.approx(whole[label]["reward"]["central"])
        assert sum(p[label]["filled_shares"] for p in parts) == whole[label]["filled_shares"]
    assert any(whole[p.label]["quoted_seconds"] for p in GRID)


def test_clusters_are_capture_days_and_each_is_its_bundle_run_alone(tmp_path, capsys):
    """Round 3: clusters are UTC capture days, not event days (h1 for T and h2 for T+1 are quoted on the same
    day and must share a cluster); the report discloses the horizon split."""
    dirs, inventory = bundles(tmp_path, CALIBRATION_DATES)
    rows, _ = cli.read_inventory(inventory, CALIBRATION_DATES)
    opened, sources, _ = cli.open_sources(dirs, rows, "calibration")
    plans = schedules(opened)
    split = cli.clusters(sources, plans)
    assert sorted(split) == [d.isoformat() for d in CALIBRATION_DATES]
    for source in sources:
        (group,) = split[source.plan.day.isoformat()]
        alone = runner.run([cli.restrict(source, plans[source.plan.day].event_days)], decay=DECAY)
        assert runner.run([group], decay=DECAY)["digest"] == alone["digest"]
    assert any({h for h, c in counts.items() if c["kept"]} >= {"1", "2"}
               for counts in cli.drop_counts(plans).values())
    assert cli.main(argv("calibrate", dirs, inventory, tmp_path / "out", "--replicates", "199")) == 0
    report = json.loads((tmp_path / "out" / "report.json").read_bytes())
    assert report["clusters"]["unit"] == "capture_day" == report["decision"]["rule"]["parameters"]["cluster_unit"]
    assert report["clusters"]["keys"] == sorted(split) == report["decision"]["clusters"]
    assert report["clusters"]["horizon_split"] == report["embargo"]["counts_by_day_and_horizon"]


# -- round 4: scored schedule, cost coverage ----------------------------------------------------------------
class LateBands(Panel):
    """The fixture plus a horizon -1 band per market (``payloads`` admits -1): captured 10-17T00:00-04:00Z it is
    local 10-16, so its target is 10-15 and it closes 10-16T04:00/05:00Z, before the bundle's UTC day."""

    def conditions_at(self, at):
        from zoneinfo import ZoneInfo
        out = super().conditions_at(at)
        for market in self.markets:
            target = at.astimezone(ZoneInfo(ZONES[market])).date() - timedelta(days=1)
            for event_id, suffix in self.events(market, target):
                cid = cid_of(market, target, 0, suffix)
                out = [c for c in out if c[3] != cid] + [(market, target, event_id, cid, -1)]
        return sorted(out, key=lambda c: c[3])


def test_score_drops_a_band_closed_before_its_bundle_day_from_metadata_only(tmp_path, monkeypatch):
    """Round 4 (B): a 10-17 bundle's horizon -1 band closing on 10-16 used to refuse the whole scored run
    (shadow_embargo). It is now dropped (closed_before_day) before its close is checked; every other close
    is still checked and refuses."""
    from maker_core.replay.bundle_v02 import open_stream_bundle
    from maker_core.replay.v2 import universe_v02
    day = date(2026, 10, 17)
    panel = LateBands(("austin", "toronto"), bands=1, step=60, full=True)
    bundle = open_stream_bundle(panel.write(tmp_path / "late" / day.isoformat(), day))
    late = {r["condition_id"] for r in panel.inventory([day])
            if close_of(r["market_id"], date.fromisoformat(r["target_date"]))
            <= datetime(2026, 10, 17, tzinfo=UTC)}
    assert late

    def scored(*values):
        embargo.check("scored", *values, now=AFTER)

    with pytest.raises(embargo.EmbargoRefused, match="shadow_embargo"):
        cli.schedule(bundle, scored)  # the round 3 behaviour
    reads = []
    real = universe_v02.descriptors
    monkeypatch.setattr(universe_v02, "descriptors", lambda b: reads.append(b.day) or real(b))
    plan = cli.schedule(bundle, scored, drop_closed_before_day=True)
    assert reads == [day]
    assert plan.dropped == {cid: cli.CLOSED_BEFORE_DAY for cid in sorted(late)}
    assert plan.event_days and not set(plan.event_days) & late
    assert all(plan.horizons[cid] == -1 for cid in late)
    # the hard refusal stays for any other embargoed close: shift the clock back so 10-17 is not yet open
    with pytest.raises(embargo.EmbargoRefused, match="shadow_embargo"):
        cli.schedule(bundle, lambda *v: embargo.check("scored", *v, now=datetime(2026, 11, 13, tzinfo=UTC)),
                     drop_closed_before_day=True)


def _coverage_run(tmp_path, *, upper=False, skip=None):
    """Calibrate on 09-27 with a minute-by-minute tape for every band (``skip`` has none; ``upper`` writes the
    condition IDs upper-cased)."""
    from maker_core.quoting.fill_cost import TableFillCostProvider
    from maker_core.replay import toxicity as tx
    table = tx.fit(*synthetic_records(dates=12, markets=12, minutes_per_cell=12, seed=11), replicates=100)
    table_path = tmp_path / "table.json"
    table_path.write_text(json.dumps(table), encoding="utf-8")
    expected = TableFillCostProvider(json.loads(table_path.read_text(encoding="utf-8"))).digest
    day = CALIBRATION_DATES[0]
    dirs, inventory = bundles(tmp_path, [day])
    start = datetime.combine(day, time(), tzinfo=UTC)
    cids = [r["condition_id"] for r in fixture().inventory([day]) if r["condition_id"] != skip]
    write_tape(tmp_path / "tape", day, [tape_row(cid.upper() if upper else cid, side, start + timedelta(minutes=k))
                                       for cid in cids for side in ("YES", "NO") for k in range(1440)])
    out = tmp_path / "out"
    args = argv("calibrate", dirs, inventory, out, "--replicates", "199", "--toxicity-table", str(table_path),
                "--toxicity-table-digest", expected, "--cf-tape", str(tmp_path / "tape"))
    assert cli.main(args) == 0
    return json.loads((out / "receipt.json").read_bytes())["cost_coverage"]


def test_full_tape_coverage_has_no_holes_and_a_reported_share(tmp_path, capsys):
    coverage = _coverage_run(tmp_path)
    assert coverage["bands_without_tape_rows"] == [] and coverage["decisions"] > 0
    assert coverage["cost_unavailable_share"] <= coverage["max_cost_unavailable_share"] == .02


def test_a_kept_band_without_tape_rows_is_a_hole_that_score_refuses(tmp_path, capsys):
    """Round 4 (C, F): a missing tape row silently became the 0.0043 floor. A kept band queried on a day with no
    tape row is now listed, and score refuses it, as it refuses an unavailable share above the bound."""
    day = CALIBRATION_DATES[0]
    dirs, inventory = bundles(tmp_path / "probe", [day])
    rows, _ = cli.read_inventory(inventory, [day])
    (bundle,), _, evaluation = cli.open_sources(dirs, rows, "calibration")
    quoted = sorted(set(cli.schedule(bundle, fit_check, drop_embargoed=True).event_days)
                    & {w["condition_id"] for w in evaluation.windows})  # kept and with a declared window
    victim = quoted[0]
    coverage = _coverage_run(tmp_path, skip=victim)
    assert {b["condition_id"] for b in coverage["bands_without_tape_rows"]} == {victim}
    contexts = adapters.CfTapeContexts(tmp_path / "tape", purpose="descriptive", conditions=quoted)
    contexts(condition_id=victim, at=datetime.combine(day, time(9), tzinfo=UTC))
    cost = adapters.RecordingFillCost.__new__(adapters.RecordingFillCost)
    cost.decisions = [("t", victim, "s", "NO_CONTEXT", None, "quote", None)]
    with pytest.raises(cli.CliRefused, match="cf_tape_band_without_rows"):
        cli.cost_coverage(cost, contexts, SIGNED_RULE, refuse=True)
    assert cli.cost_coverage(cost, contexts, SIGNED_RULE, refuse=False)["bands_without_tape_rows"]


def test_an_unavailable_share_above_the_bound_refuses_score(tmp_path):
    cost = adapters.RecordingFillCost.__new__(adapters.RecordingFillCost)
    cost.decisions = [("t", "c", "s", "OK", None, "quote", .01)] * 97 + [("t", "c", "s", "UNAVAILABLE", None, "quote", None)] * 3
    coverage = cli.cost_coverage(cost, None, SIGNED_RULE, refuse=False)
    assert coverage["cost_unavailable_share"] == pytest.approx(.03)
    with pytest.raises(cli.CliRefused, match="cost_unavailable_share_above_bound"):
        cli.cost_coverage(cost, None, SIGNED_RULE, refuse=True)
    cost.decisions = [("t", "c", "s", "OK", None, "quote", .01)] * 98 + [("t", "c", "s", "NO_CONTEXT", None, "quote", None)] * 2
    assert cli.cost_coverage(cost, None, SIGNED_RULE, refuse=True)["cost_unavailable_share"] == pytest.approx(.02)


def test_an_upper_case_tape_condition_id_is_a_hole_not_a_silent_floor(tmp_path, capsys):
    """Round 4 (F): the Parquet filter is case-exact on the kept IDs; a tape written with other-case IDs shows
    every quoted band as a hole, so score refuses instead of pricing every decision at the floor."""
    coverage = _coverage_run(tmp_path, upper=True)
    assert coverage["bands_without_tape_rows"]
    assert coverage["cost_unavailable_share"] == 1.0


# -- runner regressions ------------------------------------------------------------------------------------
def test_a_declared_window_gap_stops_quote_cost_query_reward_and_fill_in_that_minute(tmp_path):
    """Fails on the build 3 runner, which ignored ``plan.windows``: minute 3 of band a is outside its declared
    windows and holds a 120-share print through the bid that would fill."""
    from maker_core.replay.v2.lockstep import bundle_source
    s = Scenario(day=date(2026, 9, 10), minutes=8)
    for minute in range(8):
        for market in s.markets:
            s.book(market, minute * 60)
    s.trade("a", 200, price=".40", size="120")
    source = bundle_source(s.bundle(tmp_path / "b"))
    a = s.cid("a")
    windows = {a: ((s.at(0), s.at(180)), (s.at(240), s.at(480)))}  # b: no window at all
    declared = replace(source, plan=replace(source.plan, windows=windows, declared=True))
    queries = []

    def builder(*, condition_id, at, band=None, strategy=None):
        queries.append((condition_id, at))
        return None

    point = GRID[0]
    gap = runner.run([declared], decay=DECAY, points=[point], baselines=("no-quote",), context_builder=builder)
    envelope = runner.run([replace(declared, plan=replace(declared.plan, declared=False))], decay=DECAY,
                          points=[point], baselines=("no-quote",))
    assert envelope["strategies"][point.label]["fills"] >= 1  # the print fills when minute 3 is open
    totals = gap["strategies"][point.label]
    assert totals["fills"] == 0 and totals["filled_shares"] == 0
    assert all(cid == a and not s.at(180) <= at < s.at(240) for cid, at in queries)
    assert {at for _, at in queries} >= {s.at(0), s.at(120), s.at(240), s.at(420)}
    # reward accrues over [0, 180) and [240, 480) only: 420 quoted seconds, nothing in the gap
    assert totals["quoted_seconds"] == pytest.approx(420.0)
    assert envelope["strategies"][point.label]["quoted_seconds"] > 0


def _late_close(tmp_path, *, until=None):
    """The synthetic 09-29 v0.2 calibration source cut to its kept bands (those closing on 09-29), whose
    envelopes end at 09-30T00:00Z; ``until`` replaces every kept condition's ``active_until`` in the plan."""
    day = date(2026, 9, 29)
    dirs, inventory = bundles(tmp_path, [day])
    rows, _ = cli.read_inventory(inventory, [day])
    (bundle,), (source,), _ = cli.open_sources(dirs, rows, "calibration")
    kept = cli.schedule(bundle, fit_check, drop_embargoed=True).event_days
    assert kept
    source = cli.restrict(source, kept)
    assert {c.active_until for c in source.plan.conditions} == {datetime(2026, 9, 30, tzinfo=UTC)}
    if until is not None:
        source = replace(source, plan=replace(source.plan, conditions=tuple(
            replace(c, active_until=until) for c in source.plan.conditions)))
    return source


def test_a_0929_envelope_ending_at_0930_midnight_is_accepted(tmp_path):
    result = runner.run([_late_close(tmp_path)], decay=DECAY, points=GRID[:2], baselines=("no-quote",))
    assert result["days"] == ["2026-09-29"]


def test_an_envelope_reaching_into_0930_is_refused(tmp_path):
    source = _late_close(tmp_path, until=datetime(2026, 9, 30, 0, 0, 1, tzinfo=UTC))
    with pytest.raises(embargo.EmbargoRefused, match="reserved_window"):
        runner.run([source], decay=DECAY, points=GRID[:2], baselines=("no-quote",))


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
SIGNED_RULE = replace(decision.PROPOSED_RULE, min_effect_pusd_per_cluster=0.0)  # a fictional owner signature


def registration(rule=None, fill=None, decay=None, toxicity=STUB_TABLE_DIGEST):
    return ("# synthetic registration\n\nGrid hash: `%s`\n\nDecay digest: `%s`\n\nFill model: `%s`\n\n"
            "Decision rule digest: `%s`\n\nToxicity table: `%s`\n\nSigned: Test Owner, 2026-11-01\n"
            % (GRID_HASH, decay or PINNED_RE1_DECAY_DIGEST, fill or adapters.FILL_V3_BINDING,
               (rule or SIGNED_RULE).digest(), toxicity)).encode()


def pinned(tmp_path, monkeypatch, document=None, *, sign_margin=True):
    if sign_margin:
        monkeypatch.setattr(cli, "SCORED_RULE", SIGNED_RULE)
    document = document or registration()
    path = tmp_path / "registration.md"
    path.write_bytes(document)
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", prereg.registration_hash(document))
    return path


COST_ARGS = ("--toxicity-table", "table.json", "--toxicity-table-digest", STUB_TABLE_DIGEST, "--cf-tape", "tape")


def score(tmp_path, days, *extra, cost=COST_ARGS):
    dirs, inventory = manifest_only(tmp_path, days)
    return argv("score", dirs, inventory, tmp_path / "out", "--registration", str(tmp_path / "registration.md"),
                *cost, *extra)


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


@pytest.mark.parametrize("drop", [0, 2, 4])
def test_score_requires_the_toxicity_table_its_digest_and_the_tape(tmp_path, capsys, monkeypatch, drop):
    """Round 3: whether a table or tape is supplied is not a free parameter of score."""
    pinned(tmp_path, monkeypatch)
    cost = COST_ARGS[:drop] + COST_ARGS[drop + 2:]
    assert cli.main(score(tmp_path, PANEL_DAYS[:1], cost=cost), clock=lambda: AFTER) == 2
    assert refusal(capsys) == "score_requires_toxicity_table_digest_and_cf_tape"


def test_score_refuses_while_the_margin_is_unsigned(tmp_path, capsys, monkeypatch):
    assert cli.SCORED_RULE is decision.PROPOSED_RULE and not decision.PROPOSED_RULE.margin_signed
    pinned(tmp_path, monkeypatch, registration(rule=decision.PROPOSED_RULE), sign_margin=False)
    assert cli.main(score(tmp_path, PANEL_DAYS[:1]), clock=lambda: AFTER) == 2
    assert refusal(capsys) == "decision_rule_margin_unsigned"


def test_score_refuses_without_a_pinned_registration(tmp_path, capsys, monkeypatch):
    assert prereg.SIGNED_PREREGISTRATION_SHA256 is None
    monkeypatch.setattr(cli, "SCORED_RULE", SIGNED_RULE)
    (tmp_path / "registration.md").write_bytes(registration())
    assert cli.main(score(tmp_path, PANEL_DAYS[:1]), clock=lambda: AFTER) == 2
    assert refusal(capsys) == "no_signed_preregistration"


@pytest.mark.parametrize("document,reason", [
    (lambda: registration(rule=replace(SIGNED_RULE, min_effect_pusd_per_cluster=.05)), "decision_rule_digest_mismatch"),
    (lambda: registration().replace(b"Decision rule digest", b"Decision digest"), "decision_rule_digest_mismatch"),
    (lambda: registration(fill="maker_core.frontier.seams.PricePathFillModel@v2-price-path.1:v2-strictly_through"),
     "fill_model_mismatch"),
    (lambda: registration(decay="0" * 64), "decay_digest_mismatch"),
    (lambda: registration(toxicity="9" * 64), "toxicity_table_mismatch"),
    (lambda: registration().replace(b"Toxicity table", b"Toxicity"), "toxicity_table_mismatch"),
    (lambda: registration().replace(b"Test Owner, 2026-11-01", b"UNSIGNED"), "preregistration_unsigned"),
])
def test_score_refuses_a_registration_that_does_not_bind_this_run(tmp_path, capsys, monkeypatch, document, reason):
    monkeypatch.setattr(cli, "SCORED_RULE", SIGNED_RULE)
    pinned(tmp_path, monkeypatch, document())
    assert cli.main(score(tmp_path, PANEL_DAYS[:1]), clock=lambda: AFTER) == 2
    assert refusal(capsys) == reason


@pytest.mark.parametrize("day", [date(2026, 11, 20), date(2026, 10, 16), date(2026, 10, 15), date(2026, 9, 28)])
def test_score_reads_only_the_panel_and_checks_before_opening(tmp_path, capsys, monkeypatch, day):
    """10-16 is outside the panel since round 3 (it starts on 10-17)."""
    pinned(tmp_path, monkeypatch)
    opened = []
    monkeypatch.setattr(cli, "open_bundle", lambda d: opened.append(d))
    assert cli.main(score(tmp_path, [day]), clock=lambda: AFTER) == 2
    assert refusal(capsys) == "score_reads_only_the_scored_panel" and opened == []


def test_score_refuses_while_no_intervals_panel_covers_the_scored_panel(tmp_path, capsys, monkeypatch):
    """A matching pinned signed registration on panel days still stops here: no ``panel.PANELS`` name declares
    windows for 10-17..11-13, and the CLI builds sources only through ``intervals.sources``."""
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
