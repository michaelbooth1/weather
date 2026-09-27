"""Recorded quote-price parity, not a claim of full runtime/venue replay."""
from dataclasses import replace
from decimal import Decimal as D
import json
from pathlib import Path
import pytest

from maker_core.contracts import Unavailable
from maker_core.quoting.policy import Book, RewardTerms, blind_re1, decide
from maker_core.evidence.journal import canonical_bytes, SecretGuard
from .fixtures.re1_session_replay import replay_session

FIXTURES = json.loads((Path(__file__).parent / "fixtures/re1_price_parity.json").read_text())


@pytest.mark.parametrize("record", FIXTURES, ids=lambda r: f"attempt-{r['attempt']}")
def test_recorded_quote_prices_through_blind_profile(inputs, record):
    raw = record["quote_inputs"]
    def levels(name):
        return tuple((D(str(v["price"])), D(str(v["size"]))) for v in raw[name])
    size = D(record["size"])
    i = replace(inputs, profile=blind_re1,
                book=Book(inputs.now, *(levels(k) for k in ("yes_bids", "yes_asks", "no_bids", "no_asks"))),
                terms=RewardTerms(inputs.now, D(str(raw["reward_min_size"])),
                                  D(str(raw["reward_max_spread_cents"])), D(str(raw["reward_rate_per_day"]))),
                market=replace(inputs.market, tick=D(str(raw["tick"]))),
                portfolio=replace(inputs.portfolio, order_cap=size * D('.8'), band_cap=size),
                fair_value=Unavailable("historical blind profile", inputs.now))
    d = decide(i)
    assert d.action == "QUOTE", d.reasons
    assert tuple(leg.price for leg in d.legs) == tuple(map(D, record["expected_prices"]))
    assert all(leg.size == size for leg in d.legs)
    if record["first_minute_prices"] is not None:
        assert tuple(leg.price for leg in d.legs) == tuple(map(D, record["first_minute_prices"]))


def test_parity_evidence_is_bounded_and_available():
    assert len(FIXTURES) == 12
    assert sum(r["first_minute_prices"] is not None for r in FIXTURES) == 8
    for r in FIXTURES:
        assert len(r["source_journal_sha256"]) == len(r["source_selection_sha256"]) == 64


SESSION_FIXTURES = json.loads((Path(__file__).parent / 'fixtures/re1_sessions.json').read_text())['sessions']
FINDINGS = json.loads((Path(__file__).parent / 'fixtures/re1_session_findings.json').read_text())


@pytest.mark.parametrize('session', SESSION_FIXTURES, ids=lambda s: f"attempt-{s['attempt']}")
def test_recorded_session_findings(session):
    """Reproduce measured FAIL/INCOMPLETE findings, not assert parity passed."""
    result = replay_session(session, FIXTURES[session['attempt'] - 1])
    assert result == FINDINGS[session['attempt'] - 1]
    assert result['initial_quote_equal']
    assert result['full_session_parity'] != 'PASS'


@pytest.mark.parametrize('session', [
    pytest.param(s, id=f"attempt-{s['attempt']}", marks=() if s['attempt'] in (8, 9) else
                 pytest.mark.xfail(strict=True, reason='Recorded parity finding; see 110l qualification and findings JSON'))
    for s in SESSION_FIXTURES
])
def test_recorded_decision_bytes_equal(session):
    """An unexpected pass requires review; these failures are not hidden skips."""
    result = replay_session(session, FIXTURES[session['attempt'] - 1])
    assert result['decision_bytes_equal'], result


def test_session_projection_is_minimal_bound_and_guard_clean():
    assert len(SESSION_FIXTURES) == 12
    assert sum(len(s['minutes']) for s in SESSION_FIXTURES) == 313
    assert SecretGuard().clean(SESSION_FIXTURES) == SESSION_FIXTURES
    for session, selection in zip(SESSION_FIXTURES, FIXTURES):
        assert session['source_journal_sha256'] == selection['source_journal_sha256']
        assert session['initial_prices_source_selection_sha256'] == selection['source_selection_sha256']
        encoded = canonical_bytes(session)
        for excluded in (b'order_id', b'maker_address', b'token_id', b'lifecycle_key', b'sdk_response', b'available_collateral'):
            assert excluded not in encoded


def test_measured_mismatches_are_behavioral_not_requote_vocabulary():
    both = replay_session(SESSION_FIXTURES[3], FIXTURES[3])
    one = replay_session(SESSION_FIXTURES[4], FIXTURES[4])
    assert both['mismatched_minutes'] == 0  # Both controllers cancel both legs.
    assert one['first_mismatch']['expected']['cancel_legs'] == [0]
    assert one['first_mismatch']['actual']['cancel_legs'] == [0, 1]
    assert one['first_mismatch']['expected']['action'] == one['first_mismatch']['actual']['action'] == 'CANCEL'
