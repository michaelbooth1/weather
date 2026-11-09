"""Guards: WP-01 exact F2 ports within the reconciled simulation parity domain."""
from dataclasses import asdict, replace
from datetime import date, datetime
from decimal import Decimal as D
import hashlib
import json

import pytest

from weather.market import f3_policy as policy
from weather.market.f3_types import (
    BandDayUsage, BookState, CapitalState, F3NotReconciled, F3Params, Level,
    QuotePair, Refusal, SimCashState, Terms, TokenBook, UniverseCity,
)
from weather.paths import REPO_ROOT

FIXTURES = REPO_ROOT / "tests/fixtures/f3/f2_parity"
NAMES = ("quote", "check_book", "observe_held", "gate", "sleeve_charge", "daily_gate", "horizon")


def decoded_book(row):
    def token(prefix):
        levels = lambda side: tuple(Level(D(v["price"]), D(v["size"])) for v in row[prefix + "_" + side])
        return TokenBook(levels("bids"), levels("asks"), D(row["tick"]), D(20))
    return BookState("known", token("yes"), token("no"), None)


def decoded_terms(row):
    return Terms(D(row["reward_rate_per_day"]), D(row["reward_min_size"]), D(row["reward_max_spread_cents"]),
                 D(".05"), D(0), D(".25"), row["post_only_available"])


def decoded_params(raw):
    values = {}
    for key, value in raw.items():
        if key == "tokens": values[key] = tuple(value)
        elif isinstance(value, list): values[key] = tuple(map(D, value))
        else: values[key] = D(value)
    return replace(F3Params(), **values)


def gate_result(result):
    return dict(ok=result.ok, code=result.code, figures={k:str(v) for k,v in result.figures.items()})


def port(name, row):
    if name in ("quote", "check_book", "observe_held"):
        book, terms, params = decoded_book(row["inputs"]), decoded_terms(row["inputs"]), decoded_params(row["policy"])
        if name == "quote":
            result = policy.quote_pair(book, terms, params)
            if isinstance(result, Refusal):
                return dict(code=result.code)
            return {k: [str(v) for v in value] if isinstance(value, tuple) else str(value) if isinstance(value, D) else value
                    for k, value in asdict(result).items()}
        if name == "check_book":
            result = policy.check_book(book, terms, mid=D(row["mid"]), size=D(row["size"]), share=float(row["share"]), params=params)
            return dict(code=result.code if result else None)
        yes, no = map(D, row["prices"])
        pair = QuotePair(D(".41"), yes, no, D(20), D(20)*(yes+no), (D(1), D(1)), D(0), 0.0)
        return dict(decision=policy.observe_held(book, terms, pair, params))
    if name == "sleeve_charge":
        values = {k: D(v) if k != "basis" else v for k,v in row["inputs"].items()}
        charged, offset = policy.sleeve_charge(**values)
        return dict(charged=str(charged), offset=str(offset))
    if name == "gate":
        capital = CapitalState(**{k:D(v) if k != "basis" else v for k,v in row["capital"].items()})
        cash = SimCashState(**{k:D(v) for k,v in row["cash"].items()})
        return gate_result(policy.gate(capital, reserve=D(row["reserve"]), own_resting=D(row["own_resting"]), cash=cash))
    if name == "daily_gate":
        usage = BandDayUsage(**{k:D(v) for k,v in row["usage"].items()})
        return gate_result(policy.daily_gate(usage, reserve=D(row["reserve"]), own_resting=D(row["own_resting"]), cap=D(row["cap"])))
    city = UniverseCity(row["city"], row["zone"], "SYNTHETIC", "metar_routine", ("highest",))
    return dict(allowed=policy.horizon_allowed(city, date.fromisoformat(row["target"]), datetime.fromisoformat(row["now"]), F3Params()))


@pytest.mark.parametrize("name", NAMES)
def test_exact_f2_recorded_decisions(name):
    # Stop at the first differing case; the assertion always prints its id.
    count = 0
    with (FIXTURES / (name + ".jsonl")).open(encoding="utf-8") as source:
        for count, line in enumerate(source, 1):
            row = json.loads(line)
            assert port(name, row) == row["expected"], row["id"]
    assert count >= 1000


def test_provenance_and_distinct_case_counts():
    provenance = json.loads((FIXTURES / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert provenance["f2_git_sha"] == "c4c3216b1c98f74fd7dc1716c6cf8e45b70beb4f"
    assert provenance["f2_worktree_clean"] is True
    for name in NAMES:
        filename = name + ".jsonl"
        data = (FIXTURES / filename).read_bytes()
        assert hashlib.sha256(data).hexdigest() == provenance["fixture_sha256"][filename]
        assert len(data.splitlines()) == provenance["case_counts"][filename] >= 1000
        rows = [json.loads(line) for line in data.splitlines()]
        distinct = {json.dumps({k:v for k,v in row.items() if k not in ("id", "expected")}, sort_keys=True) for row in rows}
        assert len(distinct) == provenance["unique_input_counts"][filename] >= 1000
    assert hashlib.sha256((FIXTURES / "extract_f2_parity.py.txt").read_bytes()).hexdigest() == provenance["generator_sha256"]
    universe=provenance["universe_fixture"]
    assert len(universe["t046_git_sha"]) == 40
    assert hashlib.sha256((FIXTURES/universe["fixture"]).read_bytes()).hexdigest() == universe["sha256"]
    quote_mix = provenance["case_mix"]["quote.jsonl"]
    assert len(quote_mix) >= 20 and all(n >= 20 for n in quote_mix.values())


def capital(**changes):
    return replace(CapitalState(D(300), D(100), D(150), D(40), D(0), D(10), D(10), D(0), D(0), "net_of_retained_gains"), **changes)


@pytest.mark.parametrize("name,expected,quarantine,field", [
    ("cash_reconciled", "200", "0", None),
    ("unexplained_debit", "201", "0", "cash.available"),
    ("unrecorded_incoming", "100", "0", "cash.available"),
    ("incoming_quarantined", "100", "100", "cash.available"),
])
def test_original_stop_witnesses(name, expected, quarantine, field):
    cash = SimCashState(D(200), D(expected), D(quarantine))
    if field:
        with pytest.raises(F3NotReconciled) as caught:
            policy.gate(capital(), reserve=D("19.60"), own_resting=D(0), cash=cash)
        assert caught.value.field == field, name
    else:
        assert policy.gate(capital(), reserve=D("19.60"), own_resting=D(0), cash=cash).ok, name


@pytest.mark.parametrize("field,value", [("quarantined_after_bridge", D(1)), ("bridge_exists", False),
    ("ledger_halted", True), ("ledger_mismatches", True), ("unknown_outgoing_activity", True),
    ("blocking_legacy_activity", True), ("unknown_activity", True)])
def test_each_reconciliation_assertion_runs_before_money_decision(field, value):
    cash = replace(SimCashState(D(200), D(200)), **{field:value})
    with pytest.raises(F3NotReconciled) as caught:
        policy.gate(capital(), reserve=D(999), own_resting=D(0), cash=cash)
    assert caught.value.field == field


@pytest.mark.parametrize("changes,field", [(dict(external=D(1)), "external"),
    (dict(profit=D(0), incentives=D(10), available_gains=D(10)), "available_gains")])
def test_external_activity_and_incentive_gain_relabelling_refused(changes, field):
    with pytest.raises(F3NotReconciled) as caught:
        policy.gate(capital(**changes), reserve=D(1), own_resting=D(0), cash=SimCashState(D(500), D(500)))
    assert caught.value.field == field


def test_reward_and_rebate_pool_never_refills_gate():
    state = capital(available_gains=D(0), profit=D(0), incentives=D(50))
    assert policy.gate(state, reserve=D("19.60"), own_resting=D(0), cash=SimCashState(D(500), D(500))).code == "capital_total_ceiling"


def test_none_cash_cannot_make_an_unasserted_decision():
    with pytest.raises(F3NotReconciled) as caught:
        policy.gate(capital(), reserve=D(0), own_resting=D(0), cash=None)
    assert caught.value.field == "cash"
