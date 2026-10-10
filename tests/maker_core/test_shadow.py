"""Shadow runner: tape schema, OrderGate refusal path, no order path, nightly diagnostics. Fixtures only.

Guards: maker shadow runner public-reads-only contract (docs/operations/maker-shadow-runner.md, What it is and Tape;
  docs/operations/maker-core-contracts.md, Journal and deferred execution).
"""
import ast
from datetime import timedelta
from decimal import Decimal as D
import json
from pathlib import Path
import socket

import pytest

from maker_core.contracts import Unavailable
from maker_core.evidence.journal import digest
from maker_core.runtime import guard_latch
from maker_core.runtime.guard import ALLOW, HALT, PAUSE
from maker_core.runtime.guard_conformance import check_guard_conformance
from maker_core.shadow.runner import ShadowCancelPort, ShadowRunner, ShadowSink
from maker_core.shadow.score import SCORE_SCHEMA, score_day
from maker_core.shadow.tape import PROFILES, SEAL_SCHEMA, TAPE_SCHEMA, TapeWriter, inputs_from, sealed_tapes
from maker_core.venue import public_feed
from maker_core.venue.public_feed import FixtureTransport, PublicFeed, UrllibTransport, public_url

from .fixtures.shadow_rig import CAPS, CONDITION, MARKETS, NO, NOW, YES, Reads, rig, wallet_book

SHADOW_SOURCES = sorted(Path("src/maker_core/shadow").glob("*.py")) + [Path("src/maker_core/venue/public_feed.py")]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("shadow test attempted network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def run_minutes(tmp_path, runner, clock, minutes=2, start=NOW):
    writer = TapeWriter(tmp_path / "tapes", clock=clock, scope={"mode": "fixture"}, run_id="r1")
    for n in range(minutes):
        clock.now = start + timedelta(minutes=n)
        writer.record("minute", clock.now, **runner.step(clock.now, MARKETS))
    seal = writer.close("completed")
    return writer, seal


def test_minute_tape_schema_seal_and_exact_input_round_trip(tmp_path):
    runner, gate, port, clock, _ = rig(tmp_path)
    _, seal = run_minutes(tmp_path, runner, clock)
    assert seal["schema_version"] == SEAL_SCHEMA and seal["records"] == 4
    tapes, unsealed = sealed_tapes(tmp_path / "tapes", NOW.date().isoformat())
    assert unsealed == [] and len(tapes) == 1
    rows = tapes[0]["rows"]
    assert [r["event"] for r in rows] == ["opened", "minute", "minute", "terminal"]
    assert rows[0]["scope"]["tape_schema"] == TAPE_SCHEMA and rows[0]["mode"] == "public_shadow"
    first, second = rows[1], rows[2]
    assert set(first) >= {"minute_utc", "guard", "wallet_book_sha256", "conditions", "cancel_all", "resting_after"}
    row = first["conditions"][0]
    assert set(row) >= {"condition_id", "event_id", "horizon_days", "outcomes", "inputs", "decision", "gate", "venue"}
    assert row["outcomes"] == {"YES": YES, "NO": NO} and row["decision"]["action"] == "QUOTE"
    assert [g["action"] for g in row["gate"]] == [ALLOW, ALLOW] and all(g["placed"] for g in row["gate"])
    assert second["conditions"][0]["decision"]["action"] == "HOLD"
    for minute in (first, second):
        recorded = minute["conditions"][0]
        assert digest(inputs_from(recorded["inputs"])) == recorded["decision"]["input_hash"]
    assert len(runner.sink.accepted) == 2  # one would-quote per leg, only through the gate


def test_unsealed_tape_is_listed_never_read(tmp_path):
    runner, _, _, clock, _ = rig(tmp_path)
    writer = TapeWriter(tmp_path / "tapes", clock=clock, scope={}, run_id="crashed")
    writer.record("minute", NOW, **runner.step(NOW, MARKETS))
    tapes, unsealed = sealed_tapes(tmp_path / "tapes", NOW.date().isoformat())
    assert tapes == [] and unsealed == [f"{NOW.date()}-crashed.tape.jsonl"]


def test_day_roll_seals_previous_day(tmp_path):
    runner, _, _, clock, _ = rig(tmp_path)
    late = NOW.replace(hour=23, minute=59)
    writer = TapeWriter(tmp_path / "tapes", clock=clock, scope={}, run_id="r")
    clock.now = late
    writer.record("minute", late, **runner.step(late, ()))
    clock.now = late + timedelta(minutes=1)
    writer.record("minute", clock.now, **runner.step(clock.now, ()))
    writer.close("completed")
    assert [s["utc_day"] for s in writer.sealed] == ["2026-09-28", "2026-09-29"]


def test_incomplete_wallet_halts_every_would_quote(tmp_path):
    runner, gate, port, clock, _ = rig(tmp_path, wallet=wallet_book(complete=False))
    record = runner.step(NOW, MARKETS)
    row = record["conditions"][0]
    assert record["guard"]["action"] == HALT and "ledger_incomplete" in record["guard"]["reasons"]
    assert row["decision"]["action"] == "QUOTE"  # the policy is still recorded
    assert row["gate"][0]["action"] == HALT and not row["gate"][0]["placed"]
    assert runner.sink.accepted == [] and record["resting_after"] == {}
    assert record["cancel_all"] and record["cancel_all"][0]["trigger"] == HALT
    assert guard_latch.read_state(tmp_path / "latch") == guard_latch.HALTED


def test_halt_latches_and_withdraws_resting_legs(tmp_path):
    runner, gate, port, clock, book = rig(tmp_path)
    runner.step(NOW, MARKETS)
    assert runner.resting
    book["value"] = wallet_book(complete=False)
    clock.now = NOW + timedelta(minutes=1)
    record = runner.step(clock.now, MARKETS)
    assert record["resting_after"] == {} and len(runner.sink.accepted) == 2
    book["value"] = wallet_book(as_of=clock.now)
    clock.now += timedelta(minutes=1)
    record = runner.step(clock.now, MARKETS)  # a good book does not resume a latched HALT
    assert record["guard"]["action"] == HALT and "latched_halt" in record["guard"]["reasons"]
    assert len(runner.sink.accepted) == 2


@pytest.mark.parametrize("case", ["pause", "unreadable", "no_latch"])
def test_pause_unreadable_book_and_missing_latch_refuse(tmp_path, case):
    if case == "pause":
        (tmp_path / "PAUSE").write_text("owner")
    runner, _, _, _, book = rig(tmp_path, init_latch=case != "no_latch")
    if case == "unreadable":
        runner.wallet_book = lambda: (_ for _ in ()).throw(OSError("gone"))
    record = runner.step(NOW, MARKETS)
    expected = PAUSE if case == "pause" else HALT
    assert record["guard"]["action"] == expected
    assert record["conditions"][0]["gate"][0]["action"] == expected and runner.sink.accepted == []


def test_shadow_runtime_passes_guard_conformance_kit(tmp_path):
    port, intents = ShadowCancelPort(), []
    port.listeners.append(intents.append)
    _, gate, _, clock, _ = rig(tmp_path, port=port)

    class Adapter:
        def __init__(self, gate, placement):
            self.book = {"value": None}
            self.runner = ShadowRunner(reads=Reads(), gate=gate, cancel_port=port,
                                       wallet_book=lambda: self.book["value"],
                                       fair_value=lambda d, now: Unavailable("fixture", now), clock=clock, caps=CAPS,
                                       hazard_per_minute=0.001, adverse_markout=0.0043,
                                       profile=PROFILES["informed-v0"], placement=placement)

        def step(self, book):
            self.book["value"] = book
            self.runner.resting.clear()  # every kit cycle asks to place afresh
            self.runner.step(clock(), MARKETS)

    check_guard_conformance(Adapter, gate=gate, allow_book=wallet_book(), halt_book=wallet_book(complete=False),
                            cancel_intents=intents)


def test_runner_requires_order_gate_and_gated_placement(tmp_path):
    runner, gate, port, clock, _ = rig(tmp_path)
    with pytest.raises(TypeError):
        ShadowRunner(reads=Reads(), gate=object(), cancel_port=port, wallet_book=dict, fair_value=None, clock=clock,
                     caps={}, hazard_per_minute=0.001, adverse_markout=0.0043, profile=None)
    with pytest.raises(TypeError):
        rig(tmp_path, gate=gate, port=port, placement=ShadowSink())
    with pytest.raises(TypeError, match="shadow_order_required"):
        runner.sink({"side": "BUY"})


def test_public_input_failure_is_recorded_not_quoted(tmp_path):
    reads = Reads(rewards={})
    reads.books = {}
    runner, _, _, _, _ = rig(tmp_path, reads=reads)
    row = runner.step(NOW, MARKETS)["conditions"][0]
    assert row["unevaluated"].startswith("public_input_unavailable") and "decision" not in row
    reads = Reads(rewards={})
    runner, _, _, _, _ = rig(tmp_path / "b", reads=reads)
    row = runner.step(NOW, MARKETS)["conditions"][0]
    assert row["decision"]["reasons"] == ["TERMS_MISSING_STALE_OR_FUTURE"] and "gate" not in row


def test_shadow_sources_have_no_order_path():
    forbidden_calls = {"post_order", "create_order", "create_and_post_order", "cancel_order", "cancel_orders",
                       "sign", "sign_order", "derive_api_key", "create_api_key", "post_heartbeat"}
    forbidden_imports = ("py_clob_client", "eth_account", "web3", "dotenv", "polymarket", "weather",
                         "maker_core.runtime.credentials", "maker_core.venue.portfolio_client")
    for path in SHADOW_SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert not any(n == f or n.startswith(f + ".") for n in names for f in forbidden_imports), (path, names)
            if isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_calls, (path, node.attr)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "polymarket.us" not in node.value and "/order" not in node.value, (path, node.value)
    shadow_imports = Path("src/maker_core/shadow/runner.py").read_text(encoding="utf-8")
    assert "maker_core.venue" not in shadow_imports  # reads are injected; the runner builds no client
    assert not [name for name in dir(PublicFeed) if "order" in name or "cancel" in name or "sign" in name]


@pytest.mark.parametrize("url", [
    "https://clob.polymarket.com/order", "https://clob.polymarket.com/orders",
    "https://clob.polymarket.com/book?token_id=1&x=2", "http://clob.polymarket.com/book?token_id=1",
    "https://clob.polymarket.com:443/book?token_id=1", "https://user@clob.polymarket.com/book?token_id=1",
    "https://api.polymarket.us/v1/markets", "https://gateway.polymarket.us/book?token_id=1",
    "https://clob.polymarket.com/auth/api-key", "https://clob.polymarket.com/rewards/markets/0xabc",
    "https://gamma-api.polymarket.com/markets?slug=a", "https://data-api.polymarket.com/positions?user=0x1",
    "https://gamma-api.polymarket.com/events?slug=A", "https://evil.example/book?token_id=1",
    "https://data-api.polymarket.com/trades?user=0x1&limit=500",
    "https://data-api.polymarket.com/trades?market=0x" + "a" * 64 + "&limit=500&user=0x1",
    "https://data-api.polymarket.com/trades?market=0x" + "a" * 64 + "&limit=10",
])
def test_public_url_allowlist_refuses_everything_else(url):
    with pytest.raises(ValueError):
        public_url(url)


def test_public_url_accepts_exactly_the_four_reads():
    for url in (public_feed.book_url(YES), public_feed.rewards_url(CONDITION), public_feed.events_url(["a-b"]),
                public_feed.trades_url(CONDITION)):
        assert public_url(url) == url


def test_transport_is_get_only_without_redirect_or_proxy():
    seen = []

    class Response:
        status = 200

        def __init__(self, url):
            self.url = url

        def read(self, n):
            return b'{"data": []}'

        def geturl(self):
            return self.url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Opener:
        def open(self, request, timeout):
            seen.append((request.get_method(), request.full_url, dict(request.header_items())))
            return Response(request.full_url)

    feed = PublicFeed(UrllibTransport(opener=Opener()))
    assert feed.reward_terms(CONDITION) is None
    method, url, headers = seen[0]
    assert method == "GET" and url == public_feed.rewards_url(CONDITION)
    assert not {k.lower() for k in headers} & {"authorization", "cookie", "poly_api_key", "poly_signature"}
    handlers = {type(h).__name__ for h in UrllibTransport().opener.handlers}
    assert "_NoRedirect" in handlers and "HTTPRedirectHandler" not in handlers


def test_fixture_transport_serves_only_recorded_allowlisted_urls():
    transport = FixtureTransport({public_feed.book_url(YES): {"asset_id": YES}})
    assert PublicFeed(transport).book(YES)["asset_id"] == YES
    with pytest.raises(LookupError):
        PublicFeed(transport).book(NO)
    with pytest.raises(ValueError):
        FixtureTransport({"https://clob.polymarket.com/order": {}})


class Panel:
    def __init__(self, prints, mid=D(".50"), covered=(YES, NO)):
        self.p, self.m, self.covered = prints, mid, covered

    def covers(self, asset):
        return asset in self.covered

    def mid(self, asset, at):
        return self.m

    def prints(self, asset, start, end):
        return [(t, p, s) for a, t, p, s in self.p if a == asset and start < t <= end]


def test_nightly_score_fills_markouts_and_agreement(tmp_path):
    runner, _, _, clock, _ = rig(tmp_path)
    run_minutes(tmp_path, runner, clock)
    tapes, _ = sealed_tapes(tmp_path / "tapes", "2026-09-28")
    prints = [(YES, NOW + timedelta(seconds=30), D(".47"), D(10)),   # strictly through 0.48
              (YES, NOW + timedelta(seconds=90), D(".48"), D(10)),   # at price only
              (NO, NOW + timedelta(seconds=40), D(".49"), D(50))]    # above the NO bid: no fill
    report = score_day(tapes, Panel(prints), utc_day="2026-09-28")
    assert report["schema_version"] == SCORE_SCHEMA and report["label"] == "DIAGNOSTIC_NOT_A_VERDICT"
    assert report["agreement"]["status"] == "PASS" and report["agreement"]["matched"] == 2
    assert report["decisions"] == {"HOLD": 1, "QUOTE": 1}
    for stratum in ("policy", "gated"):
        rules = report["strata"][stratum]["rules"]
        assert rules["strictly_through"]["fills"] == 1 and rules["strictly_through"]["shares"] == "10"
        assert rules["at_price"]["fills"] == 2 and rules["at_price"]["spread_pusd"] == "0.40"
        assert rules["at_price"]["horizons"]["5"]["adverse_pusd"] == "0.00"
    assert report["strata"]["policy"]["condition_minutes"] == 2
    assert report["strata"]["policy"]["modelled_reward_pusd"]["1.0"] > 0


def test_nightly_score_flags_tampered_decision_and_uncovered_assets(tmp_path):
    runner, _, _, clock, _ = rig(tmp_path)
    run_minutes(tmp_path, runner, clock)
    tapes, _ = sealed_tapes(tmp_path / "tapes", "2026-09-28")
    tapes[0]["rows"][1]["conditions"][0]["decision"]["reasons"] = ["EDITED"]
    report = score_day(tapes, Panel([], covered=()), utc_day="2026-09-28")
    assert report["agreement"]["status"] == "FAIL" and report["agreement"]["mismatched"] == 1
    assert report["strata"]["policy"]["legs_not_in_panel"] == 4 and report["strata"]["policy"]["leg_minutes"] == 0


def test_halted_tape_scores_policy_but_no_gated_exposure(tmp_path):
    runner, _, _, clock, _ = rig(tmp_path, wallet=wallet_book(complete=False))
    run_minutes(tmp_path, runner, clock)
    tapes, _ = sealed_tapes(tmp_path / "tapes", "2026-09-28")
    report = score_day(tapes, Panel([(YES, NOW + timedelta(seconds=30), D(".47"), D(10))]), utc_day="2026-09-28")
    assert report["minute_guard_actions"] == {"HALT": 2}
    assert report["strata"]["policy"]["rules"]["strictly_through"]["fills"] == 1
    assert report["strata"]["gated"]["condition_minutes"] == 0
    assert json.dumps(report)  # plain JSON


def test_paper_campaign_book_makes_guard_allow(tmp_path):
    from .fixtures.shadow_rig import paper_ledger
    paper = paper_ledger()
    runner, gate, port, clock, _ = rig(tmp_path, paper=paper)
    record = runner.step(NOW, MARKETS)
    assert record["guard"]["action"] == ALLOW and record["paper"]["status"] == "OBSERVED"
    assert record["paper"]["pnl_pusd"] == "0" and record["paper"]["trade_count"] == 0
    assert [g["action"] for g in record["conditions"][0]["gate"]] == [ALLOW, ALLOW]
    assert runner.wallet_book()["account_id"] == "shadow-paper"


def test_paper_bleed_past_limit_halts_and_latches(tmp_path):
    from .fixtures.shadow_rig import data_print, paper_ledger, public_book
    paper = paper_ledger(cash="100", limit="5", rule="strictly_through")
    reads = Reads()
    runner, gate, port, clock, _ = rig(tmp_path, paper=paper, reads=reads)
    runner.step(NOW, MARKETS)  # YES 30 @ 0.48 and NO 30 @ 0.48 rest
    # Someone sells YES through our bid, then the YES book collapses.
    reads.prints = {CONDITION: [data_print(YES, NOW + timedelta(seconds=20), "0.47", 30),
                                data_print(YES, NOW + timedelta(seconds=20), "0.47", 30)]}  # duplicate print
    reads.books[YES] = public_book(YES, bids=(("0.10", "500"),), asks=(("0.12", "500"),))
    clock.now = NOW + timedelta(minutes=1)
    second = runner.step(clock.now, MARKETS)
    assert [D(f["size"]) for f in second["paper"]["fills"]] == [D(30)]
    assert second["conditions"][0]["inputs"]["fill_seen"] is True
    assert second["conditions"][0]["decision"]["action"] in ("CANCEL", "NO_QUOTE")
    clock.now = NOW + timedelta(minutes=2)
    third = runner.step(clock.now, MARKETS)  # paper P&L = 30 x (0.11 - 0.48) = -11.1 < -5
    assert third["paper"]["bleed_limit_reached"] is True and D(third["paper"]["pnl_pusd"]) == D("-11.1")
    assert third["guard"]["action"] == HALT and "bleed_limit_reached" in third["guard"]["reasons"]
    assert third["cancel_all"] and third["resting_after"] == {}
    assert guard_latch.read_state(tmp_path / "latch") == guard_latch.HALTED
    reads.books[YES] = public_book(YES)
    clock.now = NOW + timedelta(minutes=3)
    assert runner.step(clock.now, MARKETS)["guard"]["action"] == HALT  # latched; no automatic resume


def test_paper_fill_rules_and_print_gaps(tmp_path):
    from maker_core.shadow.paper import fill_legs
    prints = [(NOW, YES, D(".48"), D(10), "a"), (NOW + timedelta(seconds=1), YES, D(".47"), D(50), "b")]
    legs = [("YES", YES, D(".48"), D(30))]
    assert [f[4] for f in fill_legs(legs, prints, "at_price")] == [D(10), D(20)]
    assert [f[4] for f in fill_legs(legs, prints, "strictly_through")] == [D(30)]
    with pytest.raises(ValueError):
        fill_legs(legs, prints, "optimistic")
    from .fixtures.shadow_rig import paper_ledger

    class Broken(Reads):
        def trades(self, condition_id):
            raise OSError("down")

    runner, _, _, clock, _ = rig(tmp_path, paper=paper_ledger(), reads=Broken())
    runner.step(NOW, MARKETS)
    clock.now = NOW + timedelta(minutes=1)
    record = runner.step(clock.now, MARKETS)
    assert record["paper"]["print_gaps"][0]["error"] == "OSError" and record["paper"]["fills"] == []


def test_runner_takes_exactly_one_guard_book_source(tmp_path):
    from .fixtures.shadow_rig import paper_ledger
    runner, gate, port, clock, _ = rig(tmp_path)
    with pytest.raises(TypeError, match="exactly_one_guard_book_source"):
        ShadowRunner(reads=Reads(), gate=gate, cancel_port=port, fair_value=None, clock=clock, caps=CAPS,
                     hazard_per_minute=0.001, adverse_markout=0.0043, profile=PROFILES["informed-v0"],
                     paper=paper_ledger(), wallet_book=dict)
    with pytest.raises(TypeError, match="exactly_one_guard_book_source"):
        ShadowRunner(reads=Reads(), gate=gate, cancel_port=port, fair_value=None, clock=clock, caps=CAPS,
                     hazard_per_minute=0.001, adverse_markout=0.0043, profile=PROFILES["informed-v0"])


def test_score_surfaces_tape_code_identity_and_legacy_tapes_read_unrecorded(tmp_path):
    from maker_core.shadow.score import code_summary, tape_code
    runner, _, _, clock, _ = rig(tmp_path)
    writer = TapeWriter(tmp_path / "tapes", clock=clock,
                        scope={"mode": "fixture", "git_commit": "a" * 40, "git_dirty": True, "git_error": None},
                        run_id="r1")
    writer.record("minute", NOW, **runner.step(NOW, MARKETS))
    writer.close("completed")
    legacy = TapeWriter(tmp_path / "tapes", clock=clock, scope={"mode": "fixture"}, run_id="r2")
    clock.now = NOW + timedelta(minutes=1)
    legacy.record("minute", clock.now, **runner.step(clock.now, MARKETS))
    legacy.close("completed")
    tapes, _ = sealed_tapes(tmp_path / "tapes", "2026-09-28")
    assert [tape_code(t) for t in tapes] == [
        {"git_commit": "a" * 40, "git_dirty": True, "git_error": None},
        {"git_commit": None, "git_dirty": None, "git_error": "not_recorded"}]
    report = score_day(tapes, Panel([]), utc_day="2026-09-28")
    assert report["code"] == {"git_commits": ["a" * 40], "tapes": 2, "dirty_tapes": 1, "unbound_tapes": 2}
    assert [t["git_error"] for t in report["tapes"]] == [None, "not_recorded"]
    assert code_summary([]) == {"git_commits": [], "tapes": 0, "dirty_tapes": 0, "unbound_tapes": 0}
