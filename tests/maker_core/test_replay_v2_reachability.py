"""Registration draft §11 reachability fields and the R1 hazard hook, on hand-built inputs (U3).

No bundle, panel or calibration data is read: scorers, plans and books are small fakes, and the calibration
documents are invented.

Guards: maker replay v2 reachability fields and R1 hazard hook (docs/research/maker-replay-v2-registration-DRAFT.md, section 11).
"""
from __future__ import annotations

from array import array
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from maker_core.replay.bundle import BundleError
from maker_core.replay.v2 import reachability, rehearsal
from maker_core.replay.v2.pull import LARGE_MOVE_MID2
from maker_core.replay.v2.score import MINUTE_US, us

T0 = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
POLICY_SOURCE = Path(__file__).resolve().parents[2] / "src" / "maker_core" / "quoting" / "policy.py"


def test_every_screen_reason_is_a_reason_decide_returns_with_that_action():
    text = POLICY_SOURCE.read_text(encoding="utf-8")
    reasons = set(re.findall(r'(?:result|rejection = )\(?\s*["\']([A-Z_0-9]+)["\']', text))
    for action, reason in reachability.SCREEN_PASSED | reachability.SCREEN_FAILED:
        assert reason in reasons, reason
    # the HOLD outcomes are the ones decide() returns with legs kept; the kernel's own cooldown pull is NO_QUOTE
    assert 'result("REQUOTE_COOLDOWN", legs=i.existing, action="HOLD"' in text
    assert ("NO_QUOTE", "REQUOTE_COOLDOWN") not in reachability.SCREEN_PASSED


def test_the_screen_rate_counts_reached_and_passed_by_action_and_reason():
    counts = Counter({"QUOTE:INFORMED_QUOTE": 3, "NO_QUOTE:NONPOSITIVE_NET": 4, "CANCEL:NONPOSITIVE_NET": 1,
                      "NO_QUOTE:COMPETITION_OUTSIDE_RANGE": 2, "HOLD:REQUOTE_COOLDOWN": 2,
                      "NO_QUOTE:REQUOTE_COOLDOWN": 7, "NO_QUOTE:BOOK_STALE_OR_FUTURE": 9})
    result = reachability.screen(counts)
    assert (result["reached"], result["passed"]) == (12, 7)
    assert result["rate"] == str(reachability.D(7) / reachability.D(12))
    assert reachability.screen(Counter({"NO_QUOTE:MID_OUTSIDE_RANGE": 5}))["rate"] is None


def _scorer(*rows):
    return SimpleNamespace(rows={i: SimpleNamespace(covered=c, pulled=p) for i, (c, p) in enumerate(rows)})


def test_quoted_fraction_is_clarification_3_quote_presence_from_exact_sums():
    result = reachability.quoted_fraction(_scorer((60_000_000, 15_000_000), (40_000_000, 40_000_000)))
    assert result == dict(eligible_seconds="100.000000", quoted_seconds="45.000000", quoted_fraction="0.45")
    assert reachability.quoted_fraction(_scorer())["quoted_fraction"] is None


def _calibration(**overrides):
    doc = dict(format="maker_core.replay.calibration.v1", hazard_per_minute="0.004000000000",
               markets=["austin", "toronto"], global_fallback=None,
               cities={"austin": {"upper": "0.004000000000"}, "toronto": {"upper": "0.001000000000"}})
    doc.update(overrides)
    return doc


def test_hazards_read_the_unchanged_calibration_document():
    assert reachability.hazards(_calibration(), "max_m") == (0.004, None)
    assert reachability.hazards(_calibration(), "r1_per_city") == (0.004, {"austin": 0.004, "toronto": 0.001})
    fallback = _calibration(global_fallback="uncomputable_numerical_bound", hazard_per_minute="1.000000000000")
    assert reachability.hazards(fallback, "r1_per_city") == (1.0, {"austin": 1.0, "toronto": 1.0})
    with pytest.raises(BundleError, match="invalid_calibration_document"):
        reachability.hazards(dict(_calibration(), format="other"), "max_m")
    with pytest.raises(BundleError, match="invalid_calibration_document"):
        reachability.hazards(_calibration(cities={"austin": {}}), "r1_per_city")
    with pytest.raises(BundleError, match="invalid_hazard_value"):
        reachability.hazards(_calibration(hazard_per_minute="1.5"), "max_m")
    with pytest.raises(BundleError, match="rehearsal_hazard_variant_invalid"):
        reachability.hazards(_calibration(), "per_band")


def test_the_hazard_map_is_required_for_r1_only_and_must_cover_every_market():
    assert reachability.check_hazard_map("max_m", None, {"austin"}) is None
    with pytest.raises(BundleError, match="max_m_takes_no_hazard_map"):
        reachability.check_hazard_map("max_m", {"austin": .1}, {"austin"})
    with pytest.raises(BundleError, match="r1_hazard_map_required"):
        reachability.check_hazard_map("r1_per_city", None, {"austin"})
    with pytest.raises(BundleError, match="r1_hazard_market_missing"):
        reachability.check_hazard_map("r1_per_city", {"austin": .1}, {"austin", "toronto"})
    with pytest.raises(BundleError, match="invalid_hazard_value"):
        reachability.check_hazard_map("r1_per_city", {"austin": float("nan")}, {"austin"})


class _Base:
    def __init__(self, config, plan, *, sink=None):
        self.config, self.plan, self.sink = config, plan, sink

    def hazard_for(self, state):
        return self.config.hazard_per_minute


def test_r1_reads_each_market_s_own_hazard_and_refuses_an_unmapped_market():
    engine = reachability.per_city_engine(_Base, {"austin": .25})(SimpleNamespace(hazard_per_minute=.5), None)
    assert engine.hazard_for(SimpleNamespace(market_id="austin")) == .25
    with pytest.raises(BundleError, match="r1_hazard_market_missing"):
        engine.hazard_for(SimpleNamespace(market_id="toronto"))
    assert _Base(SimpleNamespace(hazard_per_minute=.5), None).hazard_for(None) == .5


def test_only_the_informed_strictly_through_base_pass_is_counted():
    counts = Counter()
    make = reachability.counting_engine(counts, _Base)
    sink = SimpleNamespace(decision=lambda e: seen.append(e), interval=lambda iv: seen.append(iv),
                           fill=lambda f: seen.append(f))
    seen = []
    counted = make(SimpleNamespace(policy="informed-v0", fill_bound="strictly_through", clock_pulls=()), None, sink=sink)
    event = SimpleNamespace(decision=SimpleNamespace(action="QUOTE", reasons=("INFORMED_QUOTE",)))
    counted.sink.decision(event)
    counted.sink.interval("iv")
    counted.sink.fill("fill")
    assert counts == Counter({"QUOTE:INFORMED_QUOTE": 1}) and seen == [event, "iv", "fill"]
    for cfg in (dict(policy="informed-v0", fill_bound="at_price", clock_pulls=()),
                dict(policy="clock_only", fill_bound="strictly_through", clock_pulls=()),
                dict(policy="informed-v0", fill_bound="strictly_through", clock_pulls=(("c", T0, T0),))):
        assert make(SimpleNamespace(**cfg), None, sink=sink).sink is sink


def _plan(windows):
    return SimpleNamespace(days=(SimpleNamespace(windows=windows),))


def _books(series):
    return SimpleNamespace(pull={cid: tuple(array("q", v) for v in zip(*rows)) for cid, rows in series.items()})


def test_policy_free_opportunities_use_the_frozen_endpoint_rule_on_midpoints_only():
    start = us(T0)
    # a midpoint every minute for 12 minutes; a 0.05 move (100_000 in mid2 units) lands at minute 7
    rows = [(start + m * MINUTE_US, 1_000_000 + (LARGE_MOVE_MID2 if m >= 7 else 0), start + m * MINUTE_US)
            for m in range(12)]
    plan = _plan({"c1": [(T0, T0 + timedelta(minutes=10))], "c2": [(T0, T0 + timedelta(minutes=3))]})
    result = reachability.policy_free_opportunities(plan, _books({"c1": rows}))
    # c1: ten candidate minutes; minutes 0..6 have an end midpoint 5 minutes on (minute 7 ends at 12: missing)
    assert result["candidates"] == 13
    assert result["n_cal"] == 7
    assert result["l_cal"] == 5  # minutes 2..6 end at or after the move at minute 7
    assert result["exclusions"] == {"MISSING_END_MIDPOINT": 3, "MISSING_START_MIDPOINT": 3}


# -- §11 decision logic (Defender D6.1: mutants u01-u04) ---------------------------------------------------------------

@pytest.mark.parametrize("f_cal, status", [
    ("0.5", "PASS"),  # the boundary passes (>=, not >)
    ("0.50", "PASS"),
    ("0.5000001", "PASS"),
    ("1", "PASS"),
    ("0.4999999", "FAIL"),
    ("0.45", "FAIL"),  # between 0.4 and 0.5: a 0.4 threshold would pass it
    ("0.4", "FAIL"),
    ("0", "FAIL"),
    (None, "UNIDENTIFIED"),  # no eligible second: never a pass
])
def test_the_f_cal_status_table(f_cal, status):
    assert reachability.THRESHOLD == reachability.D("0.5")
    assert reachability.status_of(f_cal) == status


@pytest.mark.parametrize("max_m, r1, outcome", [
    ("PASS", None, "PASS"),
    ("PASS", "FAIL", "PASS"),
    ("PASS", "UNIDENTIFIED", "PASS"),
    ("FAIL", None, "FAIL_R1_NOT_RUN"),
    ("FAIL", "PASS", "PASS_UNDER_R1"),
    ("FAIL", "FAIL", "FAIL"),
    ("FAIL", "UNIDENTIFIED", "FAIL"),  # an unidentified R1 does not rescue max_m
    ("UNIDENTIFIED", None, "UNIDENTIFIED"),  # not a pass, and not a reason to run R1 (D6.7)
    ("UNIDENTIFIED", "PASS", "UNIDENTIFIED"),
    ("UNIDENTIFIED", "FAIL", "UNIDENTIFIED"),
])
def test_the_section_11_verdict_table(max_m, r1, outcome):
    assert reachability.verdict(max_m, r1) == outcome


@pytest.mark.parametrize("covered, pulled, status", [
    (2_000_000, 1_000_000, "PASS"),  # f_cal exactly 0.5
    (100_000_000, 55_000_000, "FAIL"),  # f_cal 0.45
    (0, 0, "UNIDENTIFIED"),
])
def test_the_block_status_reads_f_cal_through_the_table(covered, pulled, status, monkeypatch):
    monkeypatch.setattr(reachability, "policy_free_opportunities",
                        lambda *a, **k: dict(candidates=4, n_cal=3, l_cal=1, exclusions={}))
    scorers = {p: SimpleNamespace(scorer=_scorer((covered, pulled))) for p in reachability.QUOTED_FRACTION_POLICIES}
    run = SimpleNamespace(passes={reachability.BOUND: scorers}, plan=None, books=None)
    reach = reachability.block(run, Counter())
    assert reach["status"] == status
    assert set(reach) == set(rehearsal.REACHABILITY_KEYS)  # §11 fields only: no candidates or exclusion histogram
    assert not {"pull_candidates", "opportunity_exclusions"} & set(reach)
    assert (reach["expected_clock_removed"] is None) == (status == "UNIDENTIFIED")


def test_the_screen_reading_says_the_rate_is_biased_toward_pass():
    reading = reachability.screen(Counter())["reading"]
    assert "biased toward pass" in reading and "lower bound on decisions" not in reading
