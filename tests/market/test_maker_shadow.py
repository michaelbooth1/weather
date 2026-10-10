"""Weather shadow CLI: no-network fixture run, 88a fixture panel scoring, embargo and import closure.

Guards: weather maker shadow CLI no-network run, 88a scoring embargo, import closure and the mid-minute refresh
  deadline and backoff (owner decision N7) (docs/operations/maker-shadow-runner.md, Commands, Tape v0.2 record
  stream and Nightly scoring against 88a).
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import types

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.runtime import guard_latch
from maker_core.venue import public_feed
from weather.market import maker_shadow
from weather.market.maker_evidence_store import EvidenceStore
from weather.market.maker_shadow_panel import EMBARGOED_UTC_DAYS, MakerEvidencePanel, embargo_reason
from weather.market.market_config import event_slug_for_date

from tests.maker_core.fixtures.shadow_rig import (CAPS, CONDITION, NO, NOW, PAPER_POLICY, POLICY, YES, data_print,
                                                  public_book, reward_record)


REAL_CODE_IDENTITY = maker_shadow.code_identity
FIXTURE_CODE = {"git_commit": "f" * 40, "git_dirty": False, "git_error": None}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("shadow test attempted network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    # run() must not spawn git in these fixture tests; the real code_identity is exercised below.
    monkeypatch.setattr(maker_shadow, "code_identity", lambda: dict(FIXTURE_CODE))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))
    return str(path)


def setup(tmp_path, *, bleed_limit="5", prints=()):
    guard_latch.initialize(tmp_path / "latch", NOW)
    guard = {"policy": PAPER_POLICY, "latch_dir": str(tmp_path / "latch"), "pause_file": str(tmp_path / "PAUSE")}
    paper = {"starting_cash_pusd": "100", "bleed_limit_pusd": bleed_limit, "fill_rule": "at_price"}
    config = {"schema_version": maker_shadow.CONFIG_SCHEMA, "profile": "informed-v0", "hazard_per_minute": 0.001,
              "caps": CAPS, "markets": ["nyc"], "horizons": [1, 2], "max_conditions": 4, "guard": guard,
              "paper": paper}
    nyc = next(s for s in maker_shadow.all_specs() if s.id == "nyc")
    local = NOW.astimezone(nyc.tz).date()
    slugs = [event_slug_for_date(local + timedelta(days=h), "nyc") for h in (1, 2)]
    event = {"id": "77", "slug": slugs[0], "negRisk": True, "markets": [
        {"conditionId": CONDITION, "active": True, "closed": False, "enableOrderBook": True,
         "clobTokenIds": json.dumps([YES, NO]), "outcomes": json.dumps(["Yes", "No"]),
         "orderPriceMinTickSize": 0.01, "orderMinSize": 5, "endDate": "2026-09-30T16:00:00Z",
         "bestBid": 0.49, "bestAsk": 0.51, "clobRewards": [{"rewardsDailyRate": 100}]},
        {"conditionId": "0x" + "b" * 64, "active": True, "closed": True, "clobTokenIds": "[]", "outcomes": "[]"}]}
    replies = {public_feed.events_url(slugs): [event], public_feed.book_url(YES): public_book(YES),
               public_feed.book_url(NO): public_book(NO, bids=(("0.49", "100"),), asks=(("0.51", "100"),)),
               public_feed.rewards_url(CONDITION): {"data": [reward_record()], "next_cursor": "LTE="},
               public_feed.trades_url(CONDITION): list(prints)}
    fixture = {"schema_version": maker_shadow.FIXTURE_SCHEMA, "clock_start_utc": NOW.isoformat(), "replies": replies}
    return write(tmp_path / "config.json", config), write(tmp_path / "fixture.json", fixture)


def run_offline(tmp_path, minutes=3, **kw):
    config, fixture = setup(tmp_path, **kw)
    code = maker_shadow.main(["run", "--config", config, "--offline-fixture", fixture, "--minutes", str(minutes),
                              "--output-root", str(tmp_path / "tapes")])
    assert code == 0
    return sorted((tmp_path / "tapes").glob("*.tape.jsonl"))


def test_offline_fixture_run_writes_sealed_per_minute_tape(tmp_path, capsys):
    tapes = run_offline(tmp_path)
    summary = json.loads(capsys.readouterr().out)
    assert summary["mode"] == "offline_fixture" and summary["minutes"] == 3 and len(summary["sealed"]) == 1
    rows = [json.loads(line) for line in tapes[0].read_text().splitlines()]
    events = [r["event"] for r in rows]
    assert events == ["opened", "universe", "minute", "minute", "minute", "terminal"]
    universe = rows[1]
    assert universe["selected"] == [CONDITION] and universe["refused"] == {"not_open": 1}
    assert len(universe["events_missing"]) == 1
    first = rows[2]["conditions"][0]
    assert first["decision"]["action"] == "QUOTE" and [g["action"] for g in first["gate"]] == ["ALLOW", "ALLOW"]
    assert first["inputs"]["market"]["native_unit"] == "F" and first["horizon_days"] == 1
    assert rows[0]["scope"]["fair_value"].startswith("unavailable:")


def test_offline_run_paper_book_fills_and_allows(tmp_path):
    # A print at the bid fills 30 YES at 0.48 under the at-price rule; the mark stays at the 0.50 mid,
    # so paper P&L is +0.6 and the guard keeps allowing. The bleed HALT path is in test_shadow.py.
    prints = [data_print(YES, NOW + timedelta(seconds=20), "0.48", 30)]
    tapes = run_offline(tmp_path, minutes=3, prints=prints)
    rows = [json.loads(line) for line in tapes[0].read_text().splitlines()]
    minutes = [r for r in rows if r["event"] == "minute"]
    assert all(m["guard"]["action"] == "ALLOW" for m in minutes)
    assert minutes[1]["paper"]["fills"][0]["size"] == "30.0" and minutes[2]["paper"]["pnl_pusd"] == "0.600"
    assert rows[0]["scope"]["guard_book"] == "paper_campaign_book"


def test_stop_file_and_config_refusals(tmp_path, capsys):
    config, fixture = setup(tmp_path)
    (tmp_path / "STOP").write_text("x")
    assert maker_shadow.main(["run", "--config", config, "--offline-fixture", fixture, "--minutes", "1",
                              "--stop-file", str(tmp_path / "STOP")]) == 2
    assert "stop_file_present_at_start" in capsys.readouterr().err
    base = json.loads(Path(config).read_text())
    for change in ({"guard": {**base["guard"], "wallet_book": str(tmp_path / "book.json")}},
                   {"guard": {**base["guard"], "campaigns": str(tmp_path / "campaigns.json")}}):
        with pytest.raises(ValueError, match="shadow_mode_refuses_real_wallet_book"):
            maker_shadow.load_config(write(tmp_path / "wallet.json", {**base, **change}))
    with pytest.raises(ValueError, match="guard_policy_must_name_paper_campaign"):
        maker_shadow.load_config(write(tmp_path / "pol.json", {**base, "guard": {**base["guard"], "policy": POLICY}}))
    for change in ({"hazard_per_minute": None}, {"paper": {**base["paper"], "fill_rule": "midpoint"}},
                   {"paper": {**base["paper"], "bleed_limit_pusd": "500"}}, {"paper": None}, {"markets": ["atlantis"]}, {"profile": "aggressive"},
                   {"caps": {"cash": "1"}}, {"extra": 1}, {"adverse_markout": 0.001}, {"horizons": [3]}):
        bad = write(tmp_path / "bad.json", {**base, **change})
        with pytest.raises(ValueError):
            maker_shadow.load_config(bad)
    assert maker_shadow.main(["run", "--config", config, "--offline-fixture", fixture]) == 2


def write_panel(root, *, day_start=NOW, minutes=40):
    clock = {"now": day_start}
    store = EvidenceStore(root, clock=lambda: clock["now"])
    for n in range(minutes):
        clock["now"] = day_start + timedelta(minutes=n, seconds=5)
        store.record("books", json.dumps([public_book(YES), public_book(NO)]).encode())
        if n == 0:
            clock["now"] = day_start + timedelta(seconds=40)
            ms = int((day_start + timedelta(seconds=30)).timestamp() * 1000)
            trade = {"event_type": "last_trade_price", "asset_id": YES, "price": "0.47", "size": "10",
                     "side": "SELL", "timestamp": str(ms), "market": CONDITION}
            store.record("trades", json.dumps([trade, trade]).encode())  # duplicate print counts once
    store.seal()


def test_nightly_score_against_88a_fixture_panel(tmp_path, capsys):
    run_offline(tmp_path, minutes=3)
    capsys.readouterr()
    write_panel(tmp_path / "maker_evidence")
    out = tmp_path / "report.json"
    code = maker_shadow.main(["score", "--day", "2026-09-28", "--tape-root", str(tmp_path / "tapes"),
                              "--maker-evidence-root", str(tmp_path / "maker_evidence"), "--out", str(out)])
    assert code == 0, capsys.readouterr()
    report = json.loads(out.read_text())
    assert report["label"] == "DIAGNOSTIC_NOT_A_VERDICT" and report["agreement"]["status"] == "PASS"
    assert report["panel"]["segments_read"] == 1 and report["panel"]["assets_covered"] == 2
    strict = report["strata"]["gated"]["rules"]["strictly_through"]
    assert strict["fills"] == 1 and strict["shares"] == "10" and strict["spread_pusd"] == "0.20"
    assert strict["horizons"]["30"]["missing"] == 0
    with pytest.raises(FileExistsError):
        maker_shadow.main(["score", "--day", "2026-09-28", "--tape-root", str(tmp_path / "tapes"),
                           "--maker-evidence-root", str(tmp_path / "maker_evidence"), "--out", str(out)])


def test_panel_rejects_changed_evidence_and_skips_unsealed(tmp_path):
    write_panel(tmp_path / "me", minutes=2)
    segment = next((tmp_path / "me" / "2026-09-28").iterdir())
    (tmp_path / "me" / "2026-09-28" / "15-0123456789ab").mkdir()
    panel = MakerEvidencePanel(tmp_path / "me", "2026-09-28", {YES})
    assert panel.summary["unsealed_segments_skipped"] == ["15-0123456789ab"]
    assert panel.mid(YES, NOW + timedelta(minutes=1, seconds=10)) == panel.mid(YES, NOW + timedelta(seconds=6))
    assert panel.mid(YES, NOW + timedelta(minutes=10)) is None  # older than 120 s
    book_file = next(segment.glob("book-111.jsonl"))
    book_file.write_bytes(book_file.read_bytes().replace(b"0.49", b"0.39"))
    with pytest.raises(ValueError, match="differs_from_manifest"):
        MakerEvidencePanel(tmp_path / "me", "2026-09-28", {YES})


@pytest.mark.parametrize("day", ["2026-09-30", "2026-10-14", "2026-10-15", "2026-10-30", "2026-11-13"])
def test_embargoed_days_refused_before_any_read(tmp_path, capsys, day):
    assert embargo_reason(day)
    code = maker_shadow.main(["score", "--day", day, "--tape-root", str(tmp_path / "missing"),
                              "--maker-evidence-root", str(tmp_path / "missing")])
    assert code == 2 and json.loads(capsys.readouterr().out)["refused"] == "embargoed_utc_day"


def test_embargo_windows_and_open_day(tmp_path, capsys):
    assert embargo_reason("2026-09-29") is None and embargo_reason("2026-11-14") is None
    assert all(start <= end for start, end, _ in EMBARGOED_UTC_DAYS)
    today = max(datetime.now(timezone.utc).date().isoformat(), "2026-11-14")
    assert maker_shadow.main(["score", "--day", today, "--tape-root", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["refused"] == "utc_day_not_closed"


def test_cli_import_closure_has_no_order_client_or_credentials():
    code = ("import sys, json, weather.market.maker_shadow, weather.market.maker_shadow_panel; "
            "print(json.dumps(sorted(sys.modules)))")
    env = dict(os.environ, PYTHONPATH=str(Path("src").resolve()))
    loaded = set(json.loads(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                                           env=env, cwd=Path.cwd()).stdout))
    forbidden = {"py_clob_client", "eth_account", "web3", "dotenv", "websocket", "requests",
                 "maker_core.runtime.credentials", "maker_core.venue.portfolio_client",
                 "weather.market.mm_exchange", "weather.market.mm_official_adapter",
                 "weather.market.mm_official_transport", "weather.market.polymarket_client",
                 "weather.market.mm_credentials", "weather.market.live_sdk_overlay",
                 "weather.market.maker_evidence_capture", "weather.market.wallet_reader"}
    assert not {m for m in loaded if m in forbidden or m.split(".")[0] in forbidden}


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd,
                          check=True, capture_output=True, text=True, timeout=60).stdout.strip()


@pytest.mark.spawns
@pytest.mark.skipif(maker_shadow.shutil.which("git") is None, reason="git not on PATH")
def test_code_identity_records_commit_and_dirty_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "c1")
    head = _git(repo, "rev-parse", "HEAD")
    assert REAL_CODE_IDENTITY(repo) == {"git_commit": head, "git_dirty": False, "git_error": None}
    (repo / "untracked.txt").write_text("runtime state\n")  # untracked files never make the tree dirty
    assert REAL_CODE_IDENTITY(repo)["git_dirty"] is False
    (repo / "a.txt").write_text("two\n")
    assert REAL_CODE_IDENTITY(repo) == {"git_commit": head, "git_dirty": True, "git_error": None}
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    assert REAL_CODE_IDENTITY(plain) == {"git_commit": None, "git_dirty": None, "git_error": "git_failed"}


def test_code_identity_never_raises(monkeypatch):
    monkeypatch.setattr(maker_shadow.shutil, "which", lambda name: None)
    assert REAL_CODE_IDENTITY()["git_error"] == "git_unavailable"
    monkeypatch.setattr(maker_shadow.shutil, "which", lambda name: "git")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 60)
    monkeypatch.setattr(maker_shadow.subprocess, "run", timeout)
    assert REAL_CODE_IDENTITY() == {"git_commit": None, "git_dirty": None, "git_error": "git_timeout"}
    monkeypatch.setattr(maker_shadow.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout="not-a-sha\n", stderr=""))
    assert REAL_CODE_IDENTITY()["git_error"] == "git_output_invalid"


def test_tape_opening_scope_carries_code_identity_and_score_surfaces_it(tmp_path, capsys, monkeypatch):
    calls = []
    identity = {"git_commit": "c" * 40, "git_dirty": False, "git_error": None}
    monkeypatch.setattr(maker_shadow, "code_identity", lambda: calls.append(1) or dict(identity))
    tapes = run_offline(tmp_path, minutes=3)
    assert calls == [1]  # computed once at start, not per minute
    opened = json.loads(tapes[0].read_text().splitlines()[0])
    assert opened["event"] == "opened" and {k: opened["scope"][k] for k in identity} == identity
    capsys.readouterr()
    write_panel(tmp_path / "maker_evidence")
    out = tmp_path / "report.json"
    assert maker_shadow.main(["score", "--day", "2026-09-28", "--tape-root", str(tmp_path / "tapes"),
                              "--maker-evidence-root", str(tmp_path / "maker_evidence"), "--out", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    report = json.loads(out.read_text())
    assert report["tapes"][0]["git_commit"] == "c" * 40 and report["tapes"][0]["git_dirty"] is False
    assert report["code"] == {"git_commits": ["c" * 40], "tapes": 1, "dirty_tapes": 0, "unbound_tapes": 0}
    assert printed["code"] == report["code"]


def test_offline_run_writes_record_stream_and_bundle_day_cli(tmp_path, capsys):
    from maker_core.shadow.records import day_directory
    from tests.maker_core.fixtures import replay_v2_reader_contract as reader
    prints = [data_print(YES, NOW + timedelta(seconds=20), "0.48", 30)]
    tapes = run_offline(tmp_path, minutes=3, prints=prints)
    capsys.readouterr()
    rows = [json.loads(line) for line in tapes[0].read_text().splitlines()]
    run_id = rows[0]["scope"]["run_id"]
    assert rows[0]["scope"]["records_stream"] == f"records/{NOW.date()}/{NOW.date()}-{run_id}-records.jsonl"
    assert [r["raw"]["records"] > 0 for r in rows if r["event"] == "minute"] == [True, True, True]
    root = tmp_path / "tapes"
    assert maker_shadow.main(["bundle-day", "--day", NOW.date().isoformat(), "--tape-root", str(root)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["streams"] == 1 and printed["conditions"] == 1 and printed["records"]["unsealed_streams"] == []
    bundle = reader.StreamBundle(day_directory(root, NOW.date().isoformat()))
    assert bundle.conditions and set(bundle.groups) == {"cov-" + CONDITION[2:26]}
    kinds = {r.kind for r in bundle.records()}
    # The static fixture serves its one print from the first poll, so it is the trade baseline, never a trade.
    assert kinds == {"plugin_input", "descriptor", "book", "terms", "outcome_view", "info_event", "coverage"}
    manifest = json.loads((bundle.root / "bundle.json").read_text())
    assert manifest["conditions"][0]["market_id"] == "nyc"
    assert printed["gaps"] == [] and printed["excluded"] == []
    assert maker_shadow.main(["bundle-day", "--day", NOW.date().isoformat(), "--tape-root", str(root)]) == 2
    capsys.readouterr()
    (bundle.root / "bundle.json").unlink()
    seal = next(bundle.root.glob("*-records.seal.json"))
    seal.write_bytes(b"{not json")  # a coded refusal on stdout, never a traceback
    assert maker_shadow.main(["bundle-day", "--day", NOW.date().isoformat(), "--tape-root", str(root)]) == 2
    assert json.loads(capsys.readouterr().out) == {"refused": "record_stream_seal_unreadable",
                                                   "utc_day": NOW.date().isoformat()}


def test_rediscovery_is_due_at_each_market_local_midnight():
    specs = [s for s in maker_shadow.all_specs() if s.id in ("nyc", "seattle")]
    found = NOW.replace(hour=3, minute=50)  # 23:50 in New York, 20:50 in Seattle
    previous = (found, maker_shadow.local_dates(specs, found))
    due = lambda minute: maker_shadow.discovery_due(previous, minute, specs, 15)  # noqa: E731
    assert maker_shadow.discovery_due(None, found, specs, 15)
    assert not due(found + timedelta(minutes=9))  # 23:59 New York: same local dates, inside the interval
    assert due(found + timedelta(minutes=10))  # 00:00 New York: leads change, horizons are recomputed
    assert due(found + timedelta(minutes=15))  # the schedule
    later = NOW.replace(hour=6, minute=50)
    previous = (later, maker_shadow.local_dates(specs, later))
    assert not due(later + timedelta(minutes=9)) and due(later + timedelta(minutes=10))  # Seattle's midnight


class BandWriter:
    """A fake writer whose refresh reads its bands one at a time; each band read takes ``took`` seconds on the
    monotonic clock and ``took + wall_step`` on the wall clock (a wall-clock step lands inside the read)."""

    def __init__(self, start, bands, took, wall_step=0.0):
        self.now, self.mono, self.bands, self.took, self.wall_step = start, 1000.0, bands, took, wall_step
        self.reads, self.incomplete = [], []

    def clock(self):
        return self.now

    def monotonic(self):
        return self.mono

    def poll(self, condition_ids, proceed=None):
        for index in range(self.bands):
            if proceed is not None and not proceed(self.bands - index):
                break
            self.reads.append(self.now)
            self.now += timedelta(seconds=self.took + self.wall_step)
            self.mono += self.took

    def incomplete_refresh(self, code, minute, refreshed, left):
        self.incomplete.append((code, minute, refreshed, left))


def refresh_at(writer, minute, plan, second=30):
    writer.now = minute + timedelta(seconds=second)
    return maker_shadow.mid_minute_refresh(writer, ["c%d" % n for n in range(writer.bands)], writer.clock, minute,
                                           plan, monotonic=writer.monotonic)


def test_mid_minute_refresh_stops_at_its_hard_deadline_and_records_the_partial_refresh():
    """N7 / Defender F11: bands are read one at a time and a band starts only when the clock plus the per-band
    estimate is within the deadline (the next minute less REFRESH_MARGIN). A cut-short refresh is recorded with
    what it read and what it left; the next refresh uses the measured band time. It stopped within the deadline,
    so (owner decision N1) it does not back off: the very next minute is attempted again."""
    plan, writer = maker_shadow.RefreshPlan(), BandWriter(NOW, bands=5, took=7)
    deadline = NOW + timedelta(minutes=1) - maker_shadow.REFRESH_MARGIN
    refresh_at(writer, NOW, plan)  # estimate REFRESH_BAND_BOUND (15 s): starts at +30 and +37, not at +44
    assert writer.reads == [NOW + timedelta(seconds=s) for s in (30, 37)] and writer.now <= deadline
    assert writer.incomplete == [(maker_shadow.REFRESH_PARTIAL, NOW, 2, 3)]
    assert plan.band_estimate == timedelta(seconds=7) and plan.resume_at is None and plan.late == 0
    later, writer.reads = NOW + timedelta(minutes=1), []
    refresh_at(writer, later, plan)  # the measured 7 s: starts at +30, +37 and +44 (ends +51 <= +57), not +51
    assert writer.reads == [later + timedelta(seconds=s) for s in (30, 37, 44)]
    assert writer.incomplete[-1] == (maker_shadow.REFRESH_PARTIAL, later, 3, 2)
    assert writer.now <= later + timedelta(minutes=1) - maker_shadow.REFRESH_MARGIN


def test_a_refresh_that_fits_reads_every_band_and_records_nothing():
    plan, writer = maker_shadow.RefreshPlan(), BandWriter(NOW, bands=3, took=4)
    refresh_at(writer, NOW, plan)
    assert len(writer.reads) == 3 and writer.incomplete == [] and plan.band_estimate == timedelta(seconds=4)
    assert plan.late == 0 and plan.resume_at is None


def test_a_clean_skip_or_partial_never_backs_off():
    """Owner decision N1 (2026-10-09): back off only after a LATE refresh. A refresh that read nothing because the
    estimate did not fit, or stopped part-way, ended within its deadline and delayed nothing, so every minute is
    attempted again: no ``backed_off`` minute, and the backoff level is neither raised nor reset. Kills mutant
    N1-partial-backs-off (any incomplete refresh backs off again)."""
    plan, writer = maker_shadow.RefreshPlan(), BandWriter(NOW, bands=1, took=7)
    minute = lambda n: NOW + timedelta(minutes=n)  # noqa: E731
    for n in range(24):
        refresh_at(writer, minute(n), plan, second=50)  # 50 + 15 > 57: nothing is read
    assert writer.incomplete == [(maker_shadow.REFRESH_SKIPPED, minute(n), 0, 1) for n in range(24)]
    assert plan.late == 0 and plan.resume_at is None and plan.band_estimate is None and writer.reads == []
    writer.bands = 5
    for n in range(24, 30):
        refresh_at(writer, minute(n), plan)  # 7 s bands from +30: a clean partial every minute
    assert [code for code, *_ in writer.incomplete[24:]] == [maker_shadow.REFRESH_PARTIAL] * 6
    assert plan.late == 0 and plan.resume_at is None and len(writer.reads) == 2 + 5 * 3
    plan.late = 2  # an earlier late streak: a clean partial keeps its level, it does not reset it
    refresh_at(writer, minute(30), plan)
    assert plan.late == 2 and plan.resume_at is None and writer.incomplete[-1][0] == maker_shadow.REFRESH_PARTIAL


def test_band_reads_are_timed_on_the_monotonic_clock_not_the_wall_clock():
    """N7 / Defender F4, F12: a 40 s wall-clock step inside a 2 s band read must not become the band estimate
    (that would skip every later refresh); the estimate is the monotonic 2 s, so the next refresh is full."""
    plan, writer = maker_shadow.RefreshPlan(), BandWriter(NOW, bands=1, took=2, wall_step=40)
    refresh_at(writer, NOW, plan, second=5)
    assert plan.band_estimate == timedelta(seconds=2) and writer.incomplete == []
    writer.wall_step, writer.bands = 0, 3
    refresh_at(writer, NOW + timedelta(minutes=1), plan, second=45)  # 45 + 2 + 2 + 2 <= 57 with the 2 s estimate
    assert len(writer.reads) == 4 and writer.incomplete == []


def test_a_backward_band_duration_is_clamped_to_zero():
    """M6: a monotonic reading that goes backwards measures zero, never a negative band estimate."""
    plan, writer = maker_shadow.RefreshPlan(), BandWriter(NOW, bands=1, took=-5)
    refresh_at(writer, NOW, plan)
    assert plan.band_estimate == timedelta(0) and writer.incomplete == []


def test_a_band_slower_than_the_carried_estimate_raises_the_estimate_within_the_refresh():
    """N7: the band estimate is the longer of the carried one and this refresh's longest read, so one slow band
    stops the refresh before a second slow band could pass the deadline."""
    plan, writer = maker_shadow.RefreshPlan(), BandWriter(NOW, bands=4, took=10)
    plan.band_estimate = timedelta(seconds=2)
    refresh_at(writer, NOW, plan)  # +30 (estimate 2 s), +40 (estimate 10 s); +50 + 10 s would pass +57
    assert writer.reads == [NOW + timedelta(seconds=s) for s in (30, 40)] and writer.now == NOW + timedelta(seconds=50)
    assert writer.incomplete == [(maker_shadow.REFRESH_PARTIAL, NOW, 2, 2)]


def test_a_refresh_that_ends_late_is_recorded_and_backs_off_and_a_skip_returns_to_the_bound():
    """N7 / Defender F1, F11, owner decision N1: a band read longer than its estimate (here 30 s against the 15 s
    bound) ends past the deadline; that refresh is recorded ``late_overrun`` and is the only kind that backs off,
    1, 2, 4 then 8 minutes (capped) by late refreshes since the last full on-time one, so the late decisions it
    causes thin out (minutes 0, 2, 5, 10, 19, 28), never every other minute. Each backed-off minute is recorded
    with all its bands left. A skip measures nothing, so the next attempt uses REFRESH_BAND_BOUND again, never
    the 30 s that would lock refreshes out; that clean skip neither raises nor resets the backoff. A full on-time
    refresh resets it."""
    plan, writer = maker_shadow.RefreshPlan(), BandWriter(NOW, bands=1, took=30)
    minute = lambda n: NOW + timedelta(minutes=n)  # noqa: E731
    for n in range(30):
        refresh_at(writer, minute(n), plan)
    by_code = lambda code: [m for c, m, _, _ in writer.incomplete if c == code]  # noqa: E731
    assert by_code(maker_shadow.REFRESH_LATE) == [minute(n) for n in (0, 2, 5, 10, 19, 28)]  # gaps 2, 3, 5, 9, 9
    assert by_code(maker_shadow.REFRESH_SKIPPED) == [minute(n) for n in (1, 4, 9, 18, 27)]
    assert by_code(maker_shadow.REFRESH_BACKOFF) == [minute(n) for n in (3, 6, 7, 8, *range(11, 18),
                                                                         *range(20, 27), 29)]
    assert writer.incomplete[0] == (maker_shadow.REFRESH_LATE, minute(0), 1, 0) and len(writer.incomplete) == 30
    assert all((r, left) == (0, 1) for c, _, r, left in writer.incomplete if c != maker_shadow.REFRESH_LATE)
    assert writer.reads == [minute(n) + timedelta(seconds=30) for n in (0, 2, 5, 10, 19, 28)]
    assert plan.late == 6 and plan.resume_at == minute(36)
    writer.took = 4
    refresh_at(writer, minute(36), plan)  # the carried 30 s does not fit: a clean skip, the backoff kept
    assert plan.late == 6 and plan.resume_at is None
    refresh_at(writer, minute(37), plan)  # the bound fits and the band takes 4 s: full and on time, reset
    assert plan.late == 0 and plan.resume_at is None and writer.incomplete[-1][1] == minute(36)
    writer.took = 30
    refresh_at(writer, minute(38), plan)  # late again: the backoff restarts at 1 minute
    assert plan.late == 1 and plan.resume_at == minute(39)


class SleepDrivenClock:
    """The offline run jumps ``clock.now`` to the next minute after each step; this clock ignores that jump and
    advances only through the patched ``time.sleep``, a slow step or a slow refresh read, so the loop reaches its
    +30 s refresh and its next minute at the scripted times."""

    def __init__(self, start):
        self._now = start

    def __call__(self):
        return self._now

    now = property(lambda self: self._now, lambda self, value: None)

    def advance(self, seconds):
        self._now += timedelta(seconds=seconds)


def add_bands(config_path, fixture_path, bands):
    """Grow the one-band fixture to ``bands`` rewarded bands (distinct conditions and tokens)."""
    config, fixture = json.loads(Path(config_path).read_bytes()), json.loads(Path(fixture_path).read_bytes())
    config["max_conditions"] = bands
    event = next(v[0] for v in fixture["replies"].values() if isinstance(v, list) and v and "markets" in v[0])
    conditions = [CONDITION]
    for n in range(1, bands):
        cid, yes, no = "0x" + ("%02d" % n) * 32, "5%02d1" % n, "5%02d2" % n
        event["markets"].append({**event["markets"][0], "conditionId": cid, "clobTokenIds": json.dumps([yes, no])})
        fixture["replies"].update({
            public_feed.book_url(yes): public_book(yes, condition=cid),
            public_feed.book_url(no): public_book(no, condition=cid, bids=(("0.49", "100"),), asks=(("0.51", "100"),)),
            public_feed.rewards_url(cid): {"data": [reward_record(cid)], "next_cursor": "LTE="},
            public_feed.trades_url(cid): []})
        conditions.append(cid)
    write(Path(config_path), config)
    write(Path(fixture_path), fixture)
    return conditions


def scripted_run(tmp_path, monkeypatch, *, minutes, step_seconds, band_seconds, bands=5):
    """Drive the real ``run`` loop on a sleep-driven clock: each decision step takes ``step_seconds`` and, during
    the mid-minute refresh only, each band read takes ``band_seconds`` (charged on its trade poll). Returns the
    decision starts, the refresh calls (start, minute, end) and the record-stream seal."""
    clocks, starts, refreshes, phase = [], [], [], {"refresh": False}
    real_refresh, real_build = maker_shadow.mid_minute_refresh, maker_shadow.build_runner
    trade_urls = set()

    def make_clock(start):
        clocks.append(SleepDrivenClock(start))
        return clocks[-1]

    class ScriptedTransport(maker_shadow.FixtureTransport):
        def get(self, url):
            if phase["refresh"] and url in trade_urls:
                clocks[-1].advance(band_seconds)
            return super().get(url)

    def spy(writer, condition_ids, clock, minute, plan, monotonic=None):
        begin, phase["refresh"] = clock(), True
        try:
            return real_refresh(writer, condition_ids, clock, minute, plan, monotonic=monotonic)
        finally:
            phase["refresh"] = False
            refreshes.append((begin, minute, clock()))

    def slow_runner(config, feed, clock):
        runner = real_build(config, feed, clock)
        step = runner.step

        def timed(minute, markets):
            starts.append((clock(), minute))
            result = step(minute, markets)
            clock.advance(step_seconds)
            return result
        runner.step = timed
        return runner

    config, fixture = setup(tmp_path)
    trade_urls.update(public_feed.trades_url(c) for c in add_bands(config, fixture, bands))
    monkeypatch.setattr(maker_shadow, "SimulatedClock", make_clock)
    monkeypatch.setattr(maker_shadow, "FixtureTransport", ScriptedTransport)
    monkeypatch.setattr(maker_shadow, "mid_minute_refresh", spy)
    monkeypatch.setattr(maker_shadow, "build_runner", slow_runner)
    monkeypatch.setattr(maker_shadow, "time", types.SimpleNamespace(
        sleep=lambda seconds: clocks[-1].advance(seconds), monotonic=lambda: clocks[-1]().timestamp()))
    assert maker_shadow.main(["run", "--config", config, "--offline-fixture", fixture, "--minutes", str(minutes),
                              "--output-root", str(tmp_path / "tapes")]) == 0
    from maker_core.shadow.records import day_directory
    folder = day_directory(tmp_path / "tapes", NOW.date().isoformat())
    seal = json.loads(next(folder.glob("*-records.seal.json")).read_bytes())
    tape = next((tmp_path / "tapes").glob("*.tape.jsonl"))
    rows = [json.loads(line) for line in tape.read_bytes().decode().splitlines()]
    assert sum(r["event"] == "minute" for r in rows) == minutes
    return starts, refreshes, seal, folder


def incomplete_rows(*rows, code="deadline_partial"):
    return [{"minute": (NOW + timedelta(minutes=n)).isoformat(), "code": code, "refreshed": r, "left": left}
            for n, r, left in rows]


ONE_BAND_EACH_MINUTE = tuple((n, 1, 4) for n in range(5))


@pytest.mark.parametrize("step_seconds, band_seconds, expected", [
    (35, 7, ((0, 2, 3), *((n, 3, 2) for n in range(1, 5)))),  # step 35 s, full refresh 35 s
    (0, 14, ONE_BAND_EACH_MINUTE),  # full refresh 70 s
    (0, 19, ONE_BAND_EACH_MINUTE),  # full refresh 95 s
], ids=["step35-refresh35", "refresh70", "refresh95"])
def test_a_slow_refresh_never_delays_a_decision_and_its_lost_work_is_recorded(tmp_path, monkeypatch, step_seconds,
                                                                               band_seconds, expected):
    """N7 / Defender F11: the real run loop with the Defender's scripted timings. Every decision starts on its
    minute (0 late, 0 uncaptured), every refresh ends by its deadline, and the lost refresh work is named per
    minute, coded ``deadline_partial``, on the stream seal and in gaps.json. Owner decision N1: those clean
    partial refreshes never back off, so every minute refreshes what fits (as built before N1, every other
    minute was ``backed_off``). The exact rows need the run loop to carry its RefreshPlan (estimate and backoff)
    from one refresh to the next."""
    starts, refreshes, seal, folder = scripted_run(tmp_path, monkeypatch, minutes=6, step_seconds=step_seconds,
                                                   band_seconds=band_seconds)
    minutes = [NOW + timedelta(minutes=n) for n in range(6)]
    assert starts == [(m, m) for m in minutes]  # each decision at its minute's first instant
    assert [m for _, m, _ in refreshes] == minutes[:5]
    assert all(m + timedelta(seconds=max(30, step_seconds)) == begin for begin, m, _ in refreshes)
    assert all(end <= m + timedelta(minutes=1) - maker_shadow.REFRESH_MARGIN for _, m, end in refreshes)
    assert seal["incomplete_refreshes"] == incomplete_rows(*expected)
    assert seal["faults"] == [{"fault_code": maker_shadow.REFRESH_PARTIAL, "count": 5}]
    assert maker_shadow.main(["bundle-day", "--day", NOW.date().isoformat(),
                              "--tape-root", str(tmp_path / "tapes")]) == 0
    gaps = json.loads((folder / "gaps.json").read_bytes())
    assert gaps["incomplete_refreshes"] == [{"run_id": seal["run_id"], "stream": seal["stream"],
                                             "refreshes": incomplete_rows(*expected)}]


def test_every_refresh_fault_code_has_its_own_incomplete_refresh_row_code():
    """Owner decision N2: each ``incomplete_refreshes`` row names its reason, one distinct code per runner fault
    code, so a backed-off row is never confused with a skipped one, nor a late row (``left`` may be 0) with a
    complete refresh. Kills mutant N2-mislabel (two fault codes share a row code, or a code is swapped)."""
    from maker_core.shadow.records import INCOMPLETE_REFRESH_CODES
    assert INCOMPLETE_REFRESH_CODES == {
        maker_shadow.REFRESH_LATE: "late", maker_shadow.REFRESH_PARTIAL: "deadline_partial",
        maker_shadow.REFRESH_SKIPPED: "skipped", maker_shadow.REFRESH_BACKOFF: "backed_off"}


def test_an_on_time_loop_refreshes_every_band_every_minute(tmp_path, monkeypatch):
    """N7 / Defender F2: the run loop's +30 s refresh goes through ``mid_minute_refresh`` and, when it fits,
    reads every band each minute it waits through, recording nothing."""
    starts, refreshes, seal, _ = scripted_run(tmp_path, monkeypatch, minutes=3, step_seconds=0, band_seconds=1)
    assert [(b, m) for b, m, _ in refreshes] == [(NOW + timedelta(minutes=n, seconds=30), NOW + timedelta(minutes=n))
                                                 for n in range(2)]  # the run stops after its third step
    assert all(end == m + timedelta(seconds=35) for _, m, end in refreshes)  # five 1 s bands each
    assert seal["faults"] == [] and seal["incomplete_refreshes"] == []


def test_bundle_day_cli_excludes_a_broken_run_from_its_summary(tmp_path, capsys):
    """Q-D5 / Defender F5: a broken run whose stream no longer matches its seal is excluded and listed in the CLI's
    ``excluded``; the printed summary covers only the bundled streams, so it never refuses after the bundle is
    written. Kills mutant M5 (the CLI prints ``excluded: []``)."""
    from maker_core.shadow.records import STREAM_SEAL_SCHEMA, day_directory
    run_offline(tmp_path, minutes=2)
    capsys.readouterr()
    day, root = NOW.date().isoformat(), tmp_path / "tapes"
    folder = day_directory(root, day)
    good = json.loads(next(folder.glob("*-records.seal.json")).read_bytes())
    name = f"{day}-ghost-records.jsonl"
    (folder / name).write_bytes(b"partial")  # differs from its seal: re-verifying it would refuse the day
    write(folder / name.replace(".jsonl", ".seal.json"), {
        "schema_version": STREAM_SEAL_SCHEMA, "stream": name, "utc_day": day, "run_id": "ghost",
        "status": "broken", "broken_reason": "write:OSError", "sha256": "0" * 64, "bytes": 99, "records": 5,
        "kinds": {"book": 5}, "dropped": {}, "faults": [], "conditions": {}})
    assert maker_shadow.main(["bundle-day", "--day", day, "--tape-root", str(root)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["excluded"] == [{"run_id": "ghost", "stream": name, "reason": "broken_record_stream:write:OSError"}]
    assert printed["streams"] == 1 and printed["records"]["records"] == good["records"]
    assert printed["records"]["kinds"] == good["kinds"] and printed["records"]["broken_streams"] == []
