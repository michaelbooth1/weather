"""Item 330 build 4 (c): ``python -m maker_core.frontier.cli`` calibrate and score, on SYNTHETIC bundles only.

Guards: frontier calibrate reads only days on or before 2026-09-29 and writes a create-only report and receipt with
  input hashes, commit and digests; frontier score refuses before 2026-11-14T00:00Z by the real clock, without a
  pinned signed registration matching decay, fill binding, grid and decision rule, and outside the 10-16..11-13
  panel; event-day clusters sum to the unrestricted run for every grid point.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.frontier import adapters, cli, decision, embargo, prereg, runner
from maker_core.frontier.share_decay import DecayModel
from maker_core.frontier.grid import GRID, GRID_HASH
from maker_core.replay.bundle import sha256
from .fixtures.replay_scenario import Scenario
from .test_frontier_adapters import PINNED_RE1_DECAY_DIGEST, tape_row, write_tape
from .fixtures.toxicity_synthetic import synthetic_records

UTC = timezone.utc
FIXTURES = Path(__file__).parent / "fixtures"
COMMIT = "c" * 40
AFTER = datetime(2026, 11, 14, 0, 0, 1, tzinfo=UTC)


def scenario(day, *, split=False):
    s = Scenario(day=day, minutes=8)
    if split:  # band b closes a day later, so this capture day holds two event days
        record = next(r for r in s.records if r["kind"] == "descriptor" and r["condition_id"] == s.cid("b"))
        desc = replace(s.descriptors["b"], close_at_utc=s.at(3 * 86400), settle_at_utc=s.at(3 * 86400 + 60))
        payload = dict(market=plain(desc), horizon_days=2)
        record.update(payload=plain(payload), payload_sha256=sha256(canonical_bytes(payload)))
    for minute in range(8):
        for market in s.markets:
            s.book(market, minute * 60)
    s.trade("a", 125, price=".40", size="10")
    s.trade("b", 200, price=".55", size="30")
    s.settle("a", 8 * 60 - 30, p=0)
    return s


def bundles(tmp_path, days, **kwargs):
    out = []
    for day in days:
        s = scenario(day, **kwargs)
        s.bundle(tmp_path / ("bundle-" + day.isoformat()))
        out.append(tmp_path / ("bundle-" + day.isoformat()))
    return out


def argv(command, dirs, out, *extra):
    args = [command, "--re1-projection", str(FIXTURES / "re1_sessions.json"),
            "--re1-selections", str(FIXTURES / "re1_price_parity.json"), "--out-dir", str(out), "--code-commit", COMMIT]
    for d in dirs:
        args += ["--bundle", str(d)]
    return args + list(extra)


def refusal(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])["refused"]


# -- calibrate -----------------------------------------------------------------------------------------------
def test_calibrate_writes_a_create_only_report_and_receipt(tmp_path, capsys):
    dirs = bundles(tmp_path, [date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12)])
    out = tmp_path / "out"
    assert cli.main(argv("calibrate", dirs, out, "--replicates", "199")) == 0
    report = json.loads((out / "report.json").read_bytes())
    receipt = json.loads((out / "receipt.json").read_bytes())
    assert report["label"] == "DESCRIPTIVE" and report["authority"] == "none"
    assert report["decision"]["cluster_count"] == 3 and report["decision"]["verdict"] == "NO_GO"
    assert report["decision"]["reasons"] == ["underpowered_clusters"]
    assert receipt["code"]["commit"] == COMMIT
    assert set(receipt["code"]["modules"]) >= {"maker_core.frontier.decision", "maker_core.replay.fill_v3",
                                               "maker_core.quoting.fill_cost", "maker_core.frontier.cli"}
    assert receipt["digests"]["decay"] == PINNED_RE1_DECAY_DIGEST and receipt["digests"]["grid_hash"] == GRID_HASH
    assert receipt["digests"]["fill_model_binding"] == adapters.FILL_V3_BINDING
    rule = replace(decision.PROPOSED_RULE, replicates=199)
    assert receipt["digests"]["decision_rule"] == rule.digest()
    assert receipt["digests"]["report_sha256"] == hashlib.sha256((out / "report.json").read_bytes()).hexdigest()
    assert [b["manifest_sha256"] for b in receipt["inputs"]["bundles"]] == [
        hashlib.sha256((d / "bundle.json").read_bytes()).hexdigest() for d in dirs]
    assert receipt["inputs"]["re1"]["re1_sessions.json"] == hashlib.sha256(
        (FIXTURES / "re1_sessions.json").read_bytes()).hexdigest()
    before = (out / "report.json").read_bytes()
    assert cli.main(argv("calibrate", dirs, out, "--replicates", "199")) == 2
    assert refusal(capsys) == "out_dir_exists" and (out / "report.json").read_bytes() == before


@pytest.mark.parametrize("day", [date(2026, 9, 30), date(2026, 10, 15), date(2026, 10, 20), date(2026, 11, 20)])
def test_calibrate_refuses_any_day_after_the_fit_cutoff_before_opening_it(tmp_path, capsys, monkeypatch, day):
    dirs = bundles(tmp_path, [day])
    opened = []
    monkeypatch.setattr(cli, "open_source", lambda d: opened.append(d))
    assert cli.main(argv("calibrate", dirs, tmp_path / "out")) == 2
    assert refusal(capsys) in ("reserved_window", "fit_after_cutoff") and opened == []
    assert not (tmp_path / "out").exists()


def test_calibrate_refuses_a_market_closing_after_the_cutoff(tmp_path, capsys):
    dirs = bundles(tmp_path, [date(2026, 9, 28)])  # Scenario markets close two days later, 09-30
    assert cli.main(argv("calibrate", dirs, tmp_path / "out")) == 2
    assert refusal(capsys) in ("reserved_window", "fit_after_cutoff")


def test_a_commit_is_required(tmp_path, capsys):
    dirs = bundles(tmp_path, [date(2026, 9, 10)])
    args = argv("calibrate", dirs, tmp_path / "out")
    args[args.index(COMMIT)] = "HEAD"
    assert cli.main(args) == 2 and refusal(capsys) == "code_commit_must_be_40_hex"


def test_event_day_clusters_sum_to_the_unrestricted_run_for_grid_points(tmp_path):
    (path,) = bundles(tmp_path, [date(2026, 9, 10)], split=True)
    source = cli.open_source(path)
    split = cli.clusters([source], lambda *v: embargo.check("fit", *v))
    assert sorted(split) == ["2026-09-11", "2026-09-12"]
    decay = DecayModel(5.0, 5.0, 20.0, ())
    whole = runner.run([source], decay=decay)["strategies"]
    parts = [runner.run(sources, decay=decay)["strategies"] for sources in split.values()]
    for point in GRID:
        label = point.label
        assert sum(p[label]["quoted_seconds"] for p in parts) == pytest.approx(whole[label]["quoted_seconds"])
        assert sum(p[label]["reward"]["central"] for p in parts) == pytest.approx(whole[label]["reward"]["central"])
        assert sum(p[label]["filled_shares"] for p in parts) == whole[label]["filled_shares"]
    assert any(whole[p.label]["fills"] for p in GRID)


# -- score ---------------------------------------------------------------------------------------------------
PANEL_DAYS = [date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)]


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


@pytest.mark.parametrize("now", [datetime(2026, 11, 13, 23, 59, 59, tzinfo=UTC),
                                 datetime(2026, 11, 14, 0, 0, tzinfo=timezone(timedelta(hours=1)))])
def test_score_refuses_before_the_panel_closes(tmp_path, capsys, monkeypatch, now):
    path = pinned(tmp_path, monkeypatch)
    dirs = bundles(tmp_path, PANEL_DAYS[:1])
    assert cli.main(argv("score", dirs, tmp_path / "out", "--registration", str(path)), clock=lambda: now) == 2
    assert refusal(capsys).startswith("score_refused_before_2026-11-14T00:00:00")


def test_score_reads_the_real_utc_clock_by_default(tmp_path, capsys, monkeypatch):
    real = cli.utc_now()
    assert real.tzinfo is not None and abs((real - datetime.now(UTC)).total_seconds()) < 60
    monkeypatch.setattr(cli, "utc_now", lambda: datetime(2026, 10, 16, 12, tzinfo=UTC))
    path = pinned(tmp_path, monkeypatch)
    dirs = bundles(tmp_path, PANEL_DAYS[:1])
    assert cli.main(argv("score", dirs, tmp_path / "out", "--registration", str(path))) == 2
    assert refusal(capsys).startswith("score_refused_before")


def test_score_refuses_without_a_pinned_registration(tmp_path, capsys):
    assert prereg.SIGNED_PREREGISTRATION_SHA256 is None
    path = tmp_path / "registration.md"
    path.write_bytes(registration())
    dirs = bundles(tmp_path, PANEL_DAYS[:1])
    assert cli.main(argv("score", dirs, tmp_path / "out", "--registration", str(path)), clock=lambda: AFTER) == 2
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
    path = pinned(tmp_path, monkeypatch, document())
    dirs = bundles(tmp_path, PANEL_DAYS[:1])
    assert cli.main(argv("score", dirs, tmp_path / "out", "--registration", str(path)), clock=lambda: AFTER) == 2
    assert refusal(capsys) == reason


@pytest.mark.parametrize("day,reason", [(date(2026, 11, 20), "score_reads_only_the_scored_panel"),
                                        (date(2026, 10, 15), "score_reads_only_the_scored_panel"),
                                        (date(2026, 9, 20), "score_reads_only_the_scored_panel")])
def test_score_reads_only_the_panel_and_checks_before_opening(tmp_path, capsys, monkeypatch, day, reason):
    path = pinned(tmp_path, monkeypatch)
    dirs = bundles(tmp_path, [day])
    opened = []
    monkeypatch.setattr(cli, "open_source", lambda d: opened.append(d))
    assert cli.main(argv("score", dirs, tmp_path / "out", "--registration", str(path)), clock=lambda: AFTER) == 2
    assert refusal(capsys) == reason and opened == []


def test_score_on_a_synthetic_panel_with_a_pinned_signed_registration(tmp_path, capsys, monkeypatch):
    path = pinned(tmp_path, monkeypatch)
    dirs = bundles(tmp_path, PANEL_DAYS)
    out = tmp_path / "out"
    assert cli.main(argv("score", dirs, out, "--registration", str(path)), clock=lambda: AFTER) == 0
    report = json.loads((out / "report.json").read_bytes())
    receipt = json.loads((out / "receipt.json").read_bytes())
    assert report["label"] == receipt["label"] == "SCORED"
    assert report["decision"]["registration_sha256"] == prereg.registration_hash(path.read_bytes())
    assert receipt["inputs"]["registration_sha256"] == prereg.registration_hash(path.read_bytes())
    assert receipt["digests"]["decision_rule"] == cli.SCORED_RULE.digest() == decision.PROPOSED_RULE.digest()
    assert receipt["clock_utc"] == AFTER.isoformat()
    assert report["decision"]["cluster_count"] == 3 and report["decision"]["verdict"] == "NO_GO"


def test_score_wires_the_real_fill_cost_and_the_panel_tape(tmp_path, capsys, monkeypatch):
    from maker_core.replay import toxicity as tx
    table = tx.fit(*synthetic_records(dates=12, markets=12, minutes_per_cell=12, seed=11), replicates=100)
    table_path = tmp_path / "table.json"
    table_path.write_text(json.dumps(table), encoding="utf-8")
    from maker_core.quoting.fill_cost import TableFillCostProvider
    expected = TableFillCostProvider(json.loads(table_path.read_text(encoding="utf-8"))).digest
    day = PANEL_DAYS[0]
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    s = scenario(day)
    write_tape(tmp_path / "tape", day, [tape_row(s.cid(m), side, start + timedelta(minutes=k))
                                       for m in s.markets for side in ("YES", "NO") for k in range(8)])
    path = pinned(tmp_path, monkeypatch)
    dirs = bundles(tmp_path, [day])
    out = tmp_path / "out"
    args = argv("score", dirs, out, "--registration", str(path), "--toxicity-table", str(table_path),
                "--toxicity-table-digest", expected, "--cf-tape", str(tmp_path / "tape"))
    assert cli.main(args, clock=lambda: AFTER) == 0
    report = json.loads((out / "report.json").read_bytes())
    receipt = json.loads((out / "receipt.json").read_bytes())
    assert report["fill_cost"]["table_digest"] == expected and report["fill_cost"]["decisions"] > 0
    assert receipt["inputs"]["cf_tape_days"][day.isoformat()]["rows"] == 32
    assert receipt["digests"]["toxicity_table"] == expected
    bad = argv("score", dirs, tmp_path / "out2", "--registration", str(path), "--toxicity-table", str(table_path),
               "--toxicity-table-digest", "0" * 64, "--cf-tape", str(tmp_path / "tape"))
    assert cli.main(bad, clock=lambda: AFTER) == 2 and refusal(capsys) == "toxicity_table_digest_mismatch"


def test_the_cli_module_reads_no_environment_and_spawns_nothing():
    text = Path(cli.__file__).read_text(encoding="utf-8")
    for forbidden in ("environ", "getenv", "subprocess", "dotenv"):
        assert forbidden not in text
