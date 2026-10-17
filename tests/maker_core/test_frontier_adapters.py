"""Item 330 build 4 (a, d): real-object adapters for the frontier runner and the B3 binding follow-ups.

Guards: the frontier adapters bind the real fill v3 kernel and build 2's real TableFillCostProvider and refuse any
  other version or digest; the cf-tape context builder reads only a receipted strictly_through cf_minutes Parquet
  through the embargo; the fill model binds by class and version, not by name; decay inputs enter the decay digest.
"""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path

import pytest

from maker_core.frontier import adapters, embargo, prereg, runner, seams, share_decay
from maker_core.frontier.adapters import (
    FILL_V3_BINDING, AdapterRefused, CfTapeContexts, CostQuery, RecordingFillCost, fill_v3_model,
)
from maker_core.frontier.embargo import EmbargoRefused
from maker_core.frontier.grid import GRID, GRID_HASH
from maker_core.frontier.seams import FillBindingRefused, PricePathFillModel, QueueFillModel, binding
from maker_core.frontier.share_decay import DecayModel
from maker_core.quoting.fill_cost import ConstantFillCost, FillContext, TableFillCostProvider
from maker_core.quoting.policy import Book, QuoteLeg
from maker_core.replay import fill_v3
from maker_core.replay import toxicity as tx
from maker_core.replay.payloads import Trade
from maker_core.replay.v2.lockstep import bundle_source
from .fixtures.frontier_cost_stub import SCORED_COST, TOXICITY_LINE
from .fixtures.replay_scenario import Scenario
from .fixtures.toxicity_synthetic import synthetic_records

UTC = timezone.utc
FIXTURES = Path(__file__).parent / "fixtures"
DECAY = DecayModel(5.0, 5.0, 20.0, ())
DAY = date(2026, 9, 10)
V2_BINDING = "maker_core.frontier.seams.PricePathFillModel@v2-price-path.1:v2-strictly_through"
PINNED_V3_BINDING = ("maker_core.frontier.seams.QueueFillModel@queue-adapter.1+maker_core.replay.fill_v3@fill-v3.0"
                     ":v3-queue")
PINNED_RE1_DECAY_DIGEST = "07a5507c72b052c90898b72751e786c6c2afcb7bbe187145f69c998f5adddaec"


def source(tmp_path, day=DAY, name="b", minutes=8, sweep=False):
    s = Scenario(day=day, minutes=minutes)
    for minute in range(minutes):
        for market in s.markets:
            s.book(market, minute * 60)
    s.trade("a", 125, price=".40", size="10")
    s.trade("a", 200, price=".55", size="30")
    if sweep:  # through the 75 displayed at the touch and our 20
        s.trade("a", 300, price=".40", size="120")
    s.settle("a", minutes * 60 - 30, p=0)
    return bundle_source(s.bundle(tmp_path / name)), s


# -- (d)(b) the fill-model binding -------------------------------------------------------------------------
def test_bindings_are_class_version_and_name():
    assert binding(PricePathFillModel()) == V2_BINDING
    assert FILL_V3_BINDING == binding(fill_v3_model()) == PINNED_V3_BINDING
    assert prereg._FILL.findall("Fill model: `%s`\n" % FILL_V3_BINDING) == [FILL_V3_BINDING]


def test_a_queue_model_named_like_v2_is_refused():
    spoof = QueueFillModel(fill_v3, name="v2-strictly_through")
    with pytest.raises(FillBindingRefused, match="fill_model_name_contradicts_class"):
        binding(spoof)
    with pytest.raises(FillBindingRefused):
        runner.run([], decay=DECAY, fill_model=spoof)
    renamed = PricePathFillModel()
    renamed.name = "v3-queue"
    with pytest.raises(FillBindingRefused, match="fill_model_name_contradicts_class"):
        binding(renamed)


def test_a_v2_registration_does_not_score_a_v3_model(tmp_path, monkeypatch):
    doc = ("Grid hash: `%s`\nDecay digest: `%s`\nFill model: `%s`\n%sSigned: Owner, 2027-01-31\n"
           % (GRID_HASH, DECAY.digest(), V2_BINDING, TOXICITY_LINE)).encode()
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", prereg.registration_hash(doc))
    src, _ = source(tmp_path, day=date(2027, 2, 1))
    with pytest.raises(prereg.PreregRefused, match="fill_model_mismatch"):
        runner.run([src], decay=DECAY, mode="scored", registration=doc, fill_model=fill_v3_model(), **SCORED_COST)


def test_unregistered_or_unversioned_models_cannot_score(tmp_path, monkeypatch):
    class Subclass(PricePathFillModel):
        pass

    class Kernel:
        eligibility, q_ahead, QueueState = staticmethod(fill_v3.eligibility), staticmethod(fill_v3.q_ahead), fill_v3.QueueState

    assert binding(Subclass()).startswith(seams.UNREGISTERED) and not seams.is_bindable(binding(Subclass()))
    assert not seams.is_bindable(binding(QueueFillModel(Kernel())))
    doc = b"Signed: Owner\n"
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", prereg.registration_hash(doc))
    src, _ = source(tmp_path, day=date(2027, 2, 1))
    for model in (Subclass(), QueueFillModel(Kernel())):
        with pytest.raises(runner.FrontierRefused, match="scored_requires_registered_fill_model"):
            runner.run([src], decay=DECAY, mode="scored", registration=doc, fill_model=model, **SCORED_COST)


def test_a_kernel_claiming_the_fill_v3_name_does_not_bind():
    """Round 3: a kernel's ``__name__`` is a claim; it binds only when it is the loaded module of that name."""
    import types
    impostor = types.ModuleType("maker_core.replay.fill_v3")
    for name in ("eligibility", "q_ahead", "QueueState", "VERSION"):
        setattr(impostor, name, getattr(fill_v3, name))
    spoof = binding(QueueFillModel(impostor, name="v3-queue"))
    assert spoof != FILL_V3_BINDING and not seams.is_bindable(spoof)
    assert "unloaded:maker_core.replay.fill_v3" in spoof
    assert binding(QueueFillModel(fill_v3, name="v3-queue")) == FILL_V3_BINDING


def test_the_v3_adapter_refuses_another_kernel_or_version(monkeypatch):
    class Kernel:
        VERSION, LABEL = adapters.FILL_V3_VERSION, adapters.FILL_V3_LABEL
        eligibility, q_ahead, QueueState = fill_v3.eligibility, fill_v3.q_ahead, fill_v3.QueueState

    with pytest.raises(AdapterRefused, match="fill_kernel_is_not"):
        fill_v3_model(Kernel())
    monkeypatch.setattr(fill_v3, "VERSION", "fill-v3.1")
    with pytest.raises(AdapterRefused, match="fill_kernel_version_mismatch"):
        fill_v3_model()


def test_real_fill_v3_queue_ahead_is_consumed_before_our_leg():
    model = fill_v3_model()
    at = datetime(2026, 9, 10, 12, tzinfo=UTC)
    book = Book(at, ((D(".49"), D(25)),), ((D(".51"), D(75)),), ((D(".49"), D(75)),), ((D(".51"), D(75)),))
    leg = QuoteLeg("YES", D(".49"), D(20))
    state = model.place((leg,), book)

    def trade(size, price=".49"):
        return Trade("t" + size, "YES", D(price), D(size), at, "SELL")

    state, hits = model.on_trade(state, trade("20"))
    assert hits == ()  # 20 of the 25 displayed ahead of us
    state, hits = model.on_trade(state, trade("10"))
    assert hits == ((leg, D(5)),)  # 5 left ahead, then 5 to us
    state, hits = model.on_trade(state, trade("30", ".47"))
    assert hits == ((leg, D(15)),)  # strictly through, capped at what is left of the leg


def test_runner_with_the_real_fill_v3_records_its_binding(tmp_path):
    src, _ = source(tmp_path)
    v3 = runner.run([src], decay=DECAY, fill_model=fill_v3_model(), points=GRID[:4], baselines=("no-quote",))
    v2 = runner.run([src], decay=DECAY, points=GRID[:4], baselines=("no-quote",))
    assert v3["fill_model_binding"] == FILL_V3_BINDING and v2["fill_model_binding"] == V2_BINDING
    assert v3["fill_model"] == "v3-queue"
    point = GRID[0].label
    # a 10-share through-print fills the v2 price path but only eats 10 of the 75 queued ahead in v3
    assert v2["strategies"][point]["fills"] >= 1 and v3["strategies"][point]["fills"] == 0
    swept, _ = source(tmp_path, name="swept", sweep=True)
    v3 = runner.run([swept], decay=DECAY, fill_model=fill_v3_model(), points=GRID[:4], baselines=("no-quote",))
    assert v3["strategies"][point]["fills"] >= 1
    assert 0 < v3["strategies"][point]["filled_shares"] <= D(GRID[0].size)


# -- (d)(a) decay inputs in the digest ---------------------------------------------------------------------
def test_re1_input_bytes_enter_the_decay_digest():
    projection, selections = (FIXTURES / "re1_sessions.json").read_bytes(), (FIXTURES / "re1_price_parity.json").read_bytes()
    sessions, sources = share_decay.load_re1(projection, selections)
    model = share_decay.fit(sessions, sources=sources)
    assert model.digest() == PINNED_RE1_DECAY_DIGEST
    assert model.summary()["source_sha256"] == {"re1_sessions.json": hashlib.sha256(projection).hexdigest(),
                                                "re1_price_parity.json": hashlib.sha256(selections).hexdigest()}
    # One changed byte (whitespace: the fitted numbers cannot move) changes the digest.
    edited = projection.rstrip() + b"\n\n"
    assert edited != projection
    again, edited_sources = share_decay.load_re1(edited, selections)
    changed = share_decay.fit(again, sources=edited_sources)
    assert (changed.k, changed.tau_minutes, changed.x_full) == (model.k, model.tau_minutes, model.x_full)
    assert changed.digest() != model.digest()
    # A source-free model keeps its earlier digest (the B3 test stand-ins and the old draft value).
    assert share_decay.fit(sessions).digest() == "38c47129ae4a215f4b1abe77248ef09457f0563fc55394319cb4db0287cc9cd3"
    with pytest.raises(ValueError, match="decay_source_sha256_invalid"):
        DecayModel(1.0, 1.0, 1.0, (), (("x", "not-a-sha"),))


def test_the_draft_pins_the_re1_decay_digest_and_the_v3_binding():
    draft = (Path(__file__).parents[2] / "docs" / "research"
             / "informed-v1-frontier-preregistration-DRAFT-2026-10-16.md").read_text(encoding="utf-8")
    assert prereg._DECAY.findall(draft) == [PINNED_RE1_DECAY_DIGEST]
    assert prereg._FILL.findall(draft) == [FILL_V3_BINDING]
    # round 3: the rule line is the current (margin-unset) rule; the toxicity table is unset, so nothing matches
    from maker_core.frontier.decision import PROPOSED_RULE
    assert prereg._RULE.findall(draft) == [PROPOSED_RULE.digest()]
    assert prereg._TOXICITY.findall(draft) == [] and draft.count("\nToxicity table:") == 1
    assert "Signed: UNSIGNED" in draft

# -- build 2: the real fill cost ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def table():
    return tx.fit(*synthetic_records(dates=12, markets=12, minutes_per_cell=12, seed=11), replicates=100)


def ctx(at, side="YES", **overrides):
    values = dict(at_utc=at, maker_side=side, horizon_days=1, minutes_to_close=600.0,
                  minutes_from_scheduled_print=20.0, minutes_since_model_cycle=120.0, decided_probability=.4,
                  book_imbalance=0.0, depth_shares=100.0, last_print_size=10.0, burst_prints=0, sweep_bands=1,
                  feature_times={"prints": at - timedelta(seconds=1)})
    values.update(overrides)
    return FillContext(**values)


def test_cost_adapter_refuses_other_providers_versions_digests_and_widen(table):
    provider = TableFillCostProvider(table)
    with pytest.raises(AdapterRefused, match="is_not_TableFillCostProvider"):
        RecordingFillCost(ConstantFillCost(), expected_table_digest=provider.digest)
    with pytest.raises(AdapterRefused, match="toxicity_table_digest_mismatch"):
        RecordingFillCost(provider, expected_table_digest="0" * 64)
    with pytest.raises(AdapterRefused, match="toxicity_table_version_mismatch"):
        RecordingFillCost(provider, expected_table_digest=provider.digest, expected_table_version="v0.2")
    with pytest.raises(AdapterRefused, match="widen_not_modelled"):
        RecordingFillCost(provider, expected_table_digest=provider.digest, veto_action="widen")


def test_cost_adapter_keeps_the_stricter_leg_and_records_each_decision(table):
    provider = TableFillCostProvider(table)
    cost = RecordingFillCost(provider, expected_table_digest=provider.digest)
    at = datetime(2026, 9, 10, 15, tzinfo=UTC)
    calm = cost.estimate(CostQuery("c1", at, "p", (ctx(at), ctx(at, "NO"))))
    single = [provider.estimate(ctx(at)).adverse_markout_upper, provider.estimate(ctx(at, "NO")).adverse_markout_upper]
    assert calm.adverse_markout_upper == max(single) and calm.veto is None
    swept = cost.estimate(CostQuery("c1", at, "p", (ctx(at), ctx(at, "NO", sweep_bands=3))))
    assert swept.veto == "SWEEP"
    assert seams.fill_cost_terms(swept)[1] == "SWEEP"
    assert cost.estimate(None) is None
    actions = [d[5] for d in cost.decisions]
    assert actions == ["quote", "cancel", "quote"]
    summary = cost.summary()
    assert summary["decisions"] == 3 and summary["table_digest"] == provider.digest
    assert any(key.endswith("|SWEEP|cancel") for key in summary["by_status_veto_action"])


# -- the cf tape context builder ---------------------------------------------------------------------------
def write_tape(root: Path, day: date, rows, *, fill_rule="strictly_through", drop=None, sha=None):
    import pyarrow as pa
    import pyarrow.parquet as pq

    types = {"string": pa.string(), "date32[day]": pa.date32(), "double": pa.float64(), "int32": pa.int32(),
             adapters._TS: pa.timestamp("us", tz="UTC")}
    fields = [(n, types[t]) for n, t in adapters.CF_MINUTES_SCHEMA if n != drop]
    schema = pa.schema(fields, metadata=adapters.CF_MINUTES_METADATA)
    folder = root / "tape" / ("utc_day=" + day.isoformat())
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "cf_minutes.parquet"
    columns = {n: [r.get(n) for r in rows] for n, _ in fields}
    pq.write_table(pa.Table.from_pydict(columns, schema=schema), path)
    (root / "receipts").mkdir(exist_ok=True)
    receipt = {"receipt": "cf_tape_day_receipt", "receipt_revision": 1, "tape": "maker_counterfactual_tape",
               "tape_revision": 1, "basis": "counterfactual", "utc_day": day.isoformat(), "fill_rule": fill_rule,
               "match": True, "outputs": {"cf_minutes": {"path": str(path), "rows": len(rows),
                                                         "bytes": path.stat().st_size,
                                                         "sha256": sha or hashlib.sha256(path.read_bytes()).hexdigest()}}}
    (root / "receipts" / (day.isoformat() + ".json")).write_text(json.dumps(receipt), encoding="utf-8")


def tape_row(cid, side, at, **overrides):
    row = {"utc_day": at.date().isoformat(), "condition_id": cid, "market_id": "m", "station": "s", "event_slug": "e",
           "event_date": at.date(), "token_id": cid + side, "maker_side": side, "minute_utc": at, "quote_price": .49,
           "quote_ask": .51, "quote_snapshot_at_utc": at - timedelta(seconds=3), "ctx_at_utc": at,
           "ctx_horizon_days": 1, "ctx_minutes_to_close": 600.0, "ctx_minutes_from_scheduled_print": 20.0,
           "ctx_minutes_since_model_cycle": 120.0, "ctx_decided_probability": .4, "ctx_book_imbalance": 0.0,
           "ctx_depth_shares": 100.0, "ctx_last_print_size": 10.0, "ctx_burst_prints": 0, "ctx_sweep_bands": 1,
           "ctx_ft_info_clock": None, "ctx_ft_book": at - timedelta(seconds=1), "ctx_ft_prints": at - timedelta(seconds=2),
           "basis": "counterfactual"}
    row.update(overrides)
    return row


T = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)


def test_cf_contexts_use_the_latest_fresh_row_per_side(tmp_path):
    rows = [tape_row("a-x", "YES", T), tape_row("a-x", "YES", T + timedelta(minutes=1), ctx_sweep_bands=3),
            tape_row("a-x", "NO", T)]
    write_tape(tmp_path, T.date(), rows)
    contexts = CfTapeContexts(tmp_path, purpose="descriptive")
    query = contexts(condition_id="A-X", at=T + timedelta(seconds=90), strategy="p")
    assert [c.maker_side for c in query.contexts] == ["YES", "NO"]
    assert query.contexts[0].sweep_bands == 3 and query.contexts[0].at_utc == T + timedelta(minutes=1)
    later = contexts(condition_id="a-x", at=T + timedelta(seconds=150), strategy="p")
    assert [c.maker_side for c in later.contexts] == ["YES"]  # the NO row is older than 120 s
    assert contexts(condition_id="a-x", at=T + timedelta(minutes=10), strategy="p").contexts == ()  # an empty query: the miss is logged
    assert contexts(condition_id="other", at=T + timedelta(seconds=90), strategy="p").contexts == ()  # an empty query: the miss is logged
    assert set(contexts.receipts) == {T.date().isoformat()}


@pytest.mark.parametrize("kwargs,reason", [
    (dict(fill_rule="at_price"), "cf_tape_receipt_fill_rule"),
    (dict(sha="0" * 64), "cf_tape_minutes_sha256_mismatch"),
    (dict(drop="ctx_sweep_bands"), "cf_tape_schema_mismatch"),
])
def test_cf_tape_refuses_other_rules_hashes_and_schemas(tmp_path, kwargs, reason):
    write_tape(tmp_path, T.date(), [tape_row("a-x", "YES", T)], **kwargs)
    with pytest.raises(AdapterRefused, match=reason):
        CfTapeContexts(tmp_path, purpose="descriptive")(condition_id="a-x", at=T + timedelta(seconds=5))


def test_cf_tape_reads_only_the_kept_conditions_from_parquet(tmp_path, monkeypatch):
    """Round 3: with ``conditions`` the Parquet read itself is filtered, so a foreign row is never materialised."""
    import pyarrow.parquet as pq
    rows = [tape_row(cid, side, T + timedelta(minutes=m)) for cid in ("a-x", "b-x") for side in ("YES", "NO")
            for m in range(3)]
    write_tape(tmp_path, T.date(), rows)
    calls, real = [], pq.read_table

    def spy(path, *args, **kwargs):
        table = real(path, *args, **kwargs)
        calls.append((kwargs.get("filters"), set(table.column("condition_id").to_pylist())))
        return table

    monkeypatch.setattr(pq, "read_table", spy)
    contexts = CfTapeContexts(tmp_path, purpose="descriptive", conditions={"a-x"})
    assert contexts(condition_id="a-x", at=T + timedelta(minutes=1)) is not None
    assert calls == [([("condition_id", "in", ["a-x"])], {"a-x"})]
    assert contexts.receipts[T.date().isoformat()]["rows"] == len(rows)  # the file's count, from its footer
    with pytest.raises(AdapterRefused, match="cf_tape_condition_not_kept"):
        contexts(condition_id="b-x", at=T + timedelta(minutes=1))


def test_cf_tape_missing_day_is_refused(tmp_path):
    with pytest.raises(AdapterRefused, match="cf_tape_day_missing"):
        CfTapeContexts(tmp_path, purpose="descriptive")(condition_id="a-x", at=T)


def test_cf_tape_checks_the_embargo_before_opening_a_day(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(adapters, "_sha256_file", lambda path: opened.append(path))
    for at in (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 20, tzinfo=UTC)):
        with pytest.raises(EmbargoRefused):
            CfTapeContexts(tmp_path, purpose="descriptive")(condition_id="a", at=at)
        with pytest.raises(EmbargoRefused):
            CfTapeContexts(tmp_path, purpose="scored")(condition_id="a", at=at)
    with pytest.raises(EmbargoRefused, match="reserved_window"):
        CfTapeContexts(tmp_path, purpose="scored", now=datetime(2026, 11, 20, tzinfo=UTC))(
            condition_id="a", at=datetime(2026, 10, 1, tzinfo=UTC))
    assert opened == []
    with pytest.raises(AdapterRefused, match="cf_tape_purpose"):
        CfTapeContexts(tmp_path, purpose="fit")


def test_cf_tape_scored_panel_day_opens_only_after_the_panel_closes(tmp_path):
    at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    write_tape(tmp_path, at.date(), [tape_row("a-x", "YES", at)])
    with pytest.raises(EmbargoRefused, match="shadow_embargo"):
        CfTapeContexts(tmp_path, purpose="scored", now=datetime(2026, 11, 13, 23, 59, tzinfo=UTC))(
            condition_id="a-x", at=at)
    query = CfTapeContexts(tmp_path, purpose="scored", now=embargo.SCORED_OPENS_AT)(condition_id="a-x", at=at)
    assert query.contexts[0].at_utc == at


def test_runner_end_to_end_with_real_fill_v3_fill_cost_and_tape(tmp_path, table):
    src, scenario = source(tmp_path)
    cid = scenario.cid("a")
    rows = [tape_row(cid, side, T + timedelta(minutes=m), ctx_sweep_bands=3 if m == 2 else 1)
            for m in range(8) for side in ("YES", "NO")]
    write_tape(tmp_path / "tape", T.date(), rows)
    provider = TableFillCostProvider(table)
    cost = RecordingFillCost(provider, expected_table_digest=provider.digest)
    contexts = CfTapeContexts(tmp_path / "tape", purpose="descriptive")
    result = runner.run([src], decay=DECAY, fill_model=fill_v3_model(), cost_provider=cost, context_builder=contexts,
                        points=GRID[:2], baselines=("no-quote", "blind_re1"))
    totals = result["strategies"][GRID[0].label]
    assert result["cost_provider"] == "maker_core.frontier.adapters.RecordingFillCost"
    assert totals["vetoes"] >= 1  # the minute-2 sweep rows veto band a's decisions
    assert totals["cost_unavailable"] >= 1  # band b has no tape rows
    summary = cost.summary()
    assert summary["decisions"] == len(cost.decisions) > 0
    assert any(d[5] == "cancel" and d[1] == cid for d in cost.decisions)
    again = RecordingFillCost(provider, expected_table_digest=provider.digest)
    rerun = runner.run([src], decay=DECAY, fill_model=fill_v3_model(), cost_provider=again,
                       context_builder=CfTapeContexts(tmp_path / "tape", purpose="descriptive"),
                       points=GRID[:2], baselines=("no-quote", "blind_re1"))
    assert rerun["digest"] == result["digest"] and again.summary() == summary
