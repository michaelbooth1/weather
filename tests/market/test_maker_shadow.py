"""Weather shadow CLI: no-network fixture run, 88a fixture panel scoring, embargo and import closure.

Guards: weather maker shadow CLI no-network run, 88a scoring embargo, import closure and the mid-minute refresh
  skip (owner decision N7) (docs/operations/maker-shadow-runner.md, Commands, Tape v0.2 record stream and
  Nightly scoring against 88a).
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


class RefreshWriter:
    def __init__(self, clock, duration):
        self.clock, self.duration, self.polls, self.skips, self.skipped_minutes = clock, duration, [], [], []

    def poll(self, condition_ids):
        self.polls.append((self.clock.now, list(condition_ids)))
        self.clock.now += self.duration

    def skip_refresh(self, code, minute):
        self.skips.append((self.clock.now, code))
        self.skipped_minutes.append(minute)

    def monotonic(self):  # the refresh duration is measured on a monotonic clock; here it follows the fixture
        return self.clock.now.timestamp()


def refresh(writer, clock, minute, estimate):
    return maker_shadow.mid_minute_refresh(writer, [CONDITION], clock, minute, estimate, monotonic=writer.monotonic)


def test_mid_minute_refresh_is_skipped_when_it_would_overrun_the_next_minute():
    """N7. Kills mutants N7-always-refresh (no skip), N7-strict-boundary (a refresh ending exactly at the next
    minute is skipped), N7-stale-estimate (the measured duration is ignored) and N7-uncapped-estimate (one slow
    refresh locks every later on-time refresh out)."""
    minute, second = NOW.replace(second=0, microsecond=0), timedelta(seconds=1)
    clock = maker_shadow.SimulatedClock(minute + 30 * second)
    writer = RefreshWriter(clock, 9 * second)
    estimate = refresh(writer, clock, minute, maker_shadow.REFRESH_ESTIMATE)
    assert estimate == 9 * second and writer.polls == [(minute + 30 * second, [CONDITION])]
    clock.now = minute + 51 * second  # the step overran: 51 s + 10 s ends after the next minute starts
    assert refresh(writer, clock, minute, 10 * second) == 10 * second
    assert writer.skips == [(minute + 51 * second, maker_shadow.REFRESH_SKIPPED)] and len(writer.polls) == 1
    clock.now = minute + 50 * second  # ends exactly at the next minute: it fits
    refresh(writer, clock, minute, 10 * second)
    assert len(writer.polls) == 2 and len(writer.skips) == 1
    nxt = minute + timedelta(minutes=1)
    clock.now, writer.duration = nxt + 30 * second, 25 * second  # a slow refresh: the estimate becomes 25 s
    estimate = refresh(writer, clock, nxt, maker_shadow.REFRESH_ESTIMATE)
    assert estimate == 25 * second
    later = nxt + timedelta(minutes=1)
    clock.now = later + 40 * second  # 40 s + 25 s overruns, although the 10 s default would have fit
    assert refresh(writer, clock, later, estimate) == maker_shadow.REFRESH_ESTIMATE  # a skip re-measures
    assert len(writer.polls) == 3 and writer.skips[-1] == (later + 40 * second, maker_shadow.REFRESH_SKIPPED)
    clock.now, writer.duration = later + timedelta(minutes=1, seconds=30), 45 * second
    estimate = refresh(writer, clock, later + timedelta(minutes=1), estimate)
    assert estimate == maker_shadow.MID_MINUTE_POLL  # capped: a refresh started on time always fits
    last = later + timedelta(minutes=2)
    clock.now = last + 30 * second
    refresh(writer, clock, last, estimate)
    assert len(writer.polls) == 5 and len(writer.skips) == 2


def test_one_slow_refresh_never_locks_out_later_refreshes_after_a_late_wake():
    """N7 / Defender F1. After one 45 s refresh the capped estimate is 30 s, and the run loop always wakes a little
    after +30 s: the skip resets the estimate, so the very next minute refreshes and measures again. Kills the
    lock-out (a skip keeping the stale estimate gives 60 skips and 0 polls)."""
    minute, second, late = NOW.replace(second=0, microsecond=0), timedelta(seconds=1), timedelta(milliseconds=1)
    clock = maker_shadow.SimulatedClock(minute + 30 * second)
    writer = RefreshWriter(clock, 45 * second)
    estimate = refresh(writer, clock, minute, maker_shadow.REFRESH_ESTIMATE)
    assert estimate == maker_shadow.MID_MINUTE_POLL and len(writer.polls) == 1
    writer.duration = 9 * second
    for n in range(1, 61):
        at = minute + timedelta(minutes=n)
        clock.now = at + maker_shadow.MID_MINUTE_POLL + late  # the minute boundary + 30 s + 1 ms
        estimate = refresh(writer, clock, at, estimate)
    assert writer.skipped_minutes == [minute + timedelta(minutes=1)]  # one skip, then refreshes resume
    assert [at for at, _ in writer.polls[1:]] == [minute + timedelta(minutes=n, seconds=30) + late
                                                  for n in range(2, 61)]
    assert estimate == 9 * second



def test_a_backward_refresh_duration_is_clamped_to_zero():
    """N7 / Defender F4, M6: a duration below zero (a clock that steps back) is clamped, never a negative
    estimate that would let any later refresh "fit"."""
    minute = NOW.replace(second=0, microsecond=0)
    clock = maker_shadow.SimulatedClock(minute + maker_shadow.MID_MINUTE_POLL)
    writer = RefreshWriter(clock, timedelta(seconds=-5))
    assert refresh(writer, clock, minute, maker_shadow.REFRESH_ESTIMATE) == timedelta(0)

class SleepDrivenClock:
    """The offline run jumps ``clock.now`` to the next minute after each step; this clock ignores that jump and
    advances only through the patched ``time.sleep`` (or a slow step), so the loop reaches its +30 s refresh."""

    def __init__(self, start):
        self._now = start

    def __call__(self):
        return self._now

    now = property(lambda self: self._now, lambda self, value: None)

    def advance(self, seconds):
        self._now += timedelta(seconds=seconds)


@pytest.mark.parametrize("step_seconds", [0, 51])
def test_run_loop_takes_the_mid_minute_refresh_through_the_overrun_check(tmp_path, monkeypatch, step_seconds):
    """N7 / Defender F2: the run loop's +30 s refresh goes through ``mid_minute_refresh``. An on-time loop refreshes
    every minute it waits through; a 51 s decision step makes each refresh skip, named per minute on the stream
    seal and in gaps.json. Kills mutant W (the loop calls ``writer.poll`` directly, never skipping)."""
    clocks, calls = [], []
    real_refresh, real_build = maker_shadow.mid_minute_refresh, maker_shadow.build_runner

    def make_clock(start):
        clocks.append(SleepDrivenClock(start))
        return clocks[-1]

    def spy(writer, condition_ids, clock, minute, estimate, monotonic=None):
        calls.append((clock(), minute))
        return real_refresh(writer, condition_ids, clock, minute, estimate,
                            monotonic=lambda: clock().timestamp())

    def slow_runner(config, feed, clock):
        runner = real_build(config, feed, clock)
        step = runner.step

        def timed(minute, markets):
            result = step(minute, markets)
            clock.advance(step_seconds)  # a slow decision step
            return result
        runner.step = timed
        return runner

    monkeypatch.setattr(maker_shadow, "SimulatedClock", make_clock)
    monkeypatch.setattr(maker_shadow, "mid_minute_refresh", spy)
    monkeypatch.setattr(maker_shadow, "build_runner", slow_runner)
    monkeypatch.setattr(maker_shadow, "time", types.SimpleNamespace(
        sleep=lambda seconds: clocks[-1].advance(seconds), monotonic=maker_shadow.time.monotonic))
    run_offline(tmp_path, minutes=3)
    minutes = [NOW + timedelta(minutes=n) for n in range(2)]  # the run stops after its third step
    assert [m for _, m in calls] == minutes
    from maker_core.shadow.records import day_directory
    folder = day_directory(tmp_path / "tapes", NOW.date().isoformat())
    seal = json.loads(next(folder.glob("*-records.seal.json")).read_bytes())
    if step_seconds:
        assert [at for at, _ in calls] == [m + timedelta(seconds=step_seconds) for m in minutes]
        assert seal["faults"] == [{"fault_code": maker_shadow.REFRESH_SKIPPED, "count": 2}]
        assert seal["skipped_refresh_minutes"] == [m.isoformat() for m in minutes]
        assert maker_shadow.main(["bundle-day", "--day", NOW.date().isoformat(),
                                  "--tape-root", str(tmp_path / "tapes")]) == 0
        gaps = json.loads((folder / "gaps.json").read_bytes())
        assert gaps["skipped_refreshes"] == [{"run_id": seal["run_id"], "stream": seal["stream"],
                                              "minutes": [m.isoformat() for m in minutes]}]
    else:
        assert [at for at, _ in calls] == [m + maker_shadow.MID_MINUTE_POLL for m in minutes]
        assert seal["faults"] == [] and seal["skipped_refresh_minutes"] == []


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
