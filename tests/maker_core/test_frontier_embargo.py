"""Item 330 build 3 (e): every dated frontier entry point refuses embargoed days.

Guards: every dated frontier entry point (decay fit, RE-1 loader, runner) refuses the reserved window 09-30..10-15,
  descriptive and scored reads through 11-13 and fits after 09-29, on UTC days, signed preregistration or not.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import json
from pathlib import Path

import pytest

from maker_core.frontier import embargo, runner as frontier_runner
from maker_core.frontier.embargo import EmbargoRefused, check
from maker_core.frontier.share_decay import DecayModel, Sample, Session, fit, re1_sessions
from maker_core.replay.v2.lockstep import bundle_source
from .fixtures.replay_scenario import Scenario

FIXTURES = Path(__file__).parent / "fixtures"
DECAY = DecayModel(5.0, 5.0, 20.0, ())
UTC = timezone.utc


def at(day, hour=12):
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=hour)


@pytest.mark.parametrize("purpose", embargo.PURPOSES)
@pytest.mark.parametrize("day", [date(2026, 9, 30), date(2026, 10, 7), date(2026, 10, 15)])
def test_reserved_window_is_refused_for_every_purpose(purpose, day):
    for value in (day, at(day), day.isoformat(), at(day).isoformat()):
        with pytest.raises(EmbargoRefused, match="reserved_window"):
            check(purpose, value)


@pytest.mark.parametrize("purpose", ("descriptive", "scored"))
@pytest.mark.parametrize("day", [date(2026, 10, 16), date(2026, 11, 1), date(2026, 11, 13)])
def test_shadow_embargo_refuses_reads_through_11_13(purpose, day):
    with pytest.raises(EmbargoRefused, match="shadow_embargo"):
        check(purpose, at(day))


@pytest.mark.parametrize("day", [date(2026, 10, 16), date(2026, 11, 14), date(2027, 1, 1)])
def test_fit_refuses_any_day_after_09_29(day):
    with pytest.raises(EmbargoRefused, match="fit_after_cutoff"):
        check("fit", day)


def test_allowed_days_pass():
    check("fit", date(2026, 9, 29), at(date(2026, 9, 29), 23))
    for purpose in ("descriptive", "scored"):
        check(purpose, date(2026, 9, 29), date(2026, 11, 14), at(date(2030, 1, 1)))


def test_utc_day_is_used_for_offset_instants():
    late = datetime(2026, 9, 29, 21, tzinfo=timezone(timedelta(hours=-5)))  # 2026-09-30 02:00 UTC
    with pytest.raises(EmbargoRefused, match="reserved_window"):
        check("fit", late)


@pytest.mark.parametrize("value,reason", [(datetime(2026, 9, 1), "naive_datetime"), ("2026-9-1", "unparseable_date"),
                                          (20260901, "undated_value"), ("2026-09-01T00:00:00", "naive_datetime")])
def test_undated_or_naive_values_are_refused(value, reason):
    with pytest.raises(EmbargoRefused, match=reason):
        check("fit", value)


def test_unknown_purpose_and_empty_read_are_refused():
    with pytest.raises(EmbargoRefused, match="unknown_purpose"):
        check("peek", date(2026, 9, 1))
    with pytest.raises(EmbargoRefused, match="undated_read"):
        check("fit")


# -- entry point: share_decay.fit -----------------------------------------------------------------------
def _session(opened):
    return Session("s", opened, 1.0, 1.0, tuple(Sample(opened + timedelta(minutes=m), 1.0 + m, 1.0) for m in range(1, 5)))


@pytest.mark.parametrize("opened,reason", [(at(date(2026, 10, 1)), "reserved_window"),
                                           (at(date(2026, 10, 20)), "fit_after_cutoff"),
                                           (at(date(2026, 9, 29), 23) + timedelta(minutes=58), "reserved_window")])
def test_decay_fit_refuses_embargoed_sessions(opened, reason):
    with pytest.raises(EmbargoRefused, match=reason):
        fit([_session(at(date(2026, 9, 20))), _session(opened)])


def test_decay_fit_accepts_only_the_fit_purpose():
    with pytest.raises(ValueError, match="purpose"):
        fit([_session(at(date(2026, 9, 20)))], purpose="descriptive")


# -- entry point: share_decay.re1_sessions --------------------------------------------------------------
def test_re1_projection_loader_refuses_a_session_opened_in_the_window():
    projection = json.loads((FIXTURES / "re1_sessions.json").read_text(encoding="utf-8"))
    selections = json.loads((FIXTURES / "re1_price_parity.json").read_text(encoding="utf-8"))
    assert re1_sessions(projection, selections)
    shifted = dict(projection, sessions=[dict(projection["sessions"][0],
                                              opening=dict(projection["sessions"][0]["opening"],
                                                           at="2026-10-02T01:48:14+00:00"))])
    with pytest.raises(EmbargoRefused, match="reserved_window"):
        re1_sessions(shifted, selections)


# -- entry point: runner.run ----------------------------------------------------------------------------
def _source(tmp_path, day, minutes=6):
    s = Scenario(day=day, minutes=minutes)
    for minute in range(minutes):
        for market in s.markets:
            s.book(market, minute * 60)
    s.trade("a", 125, price=".40", size="10")
    s.settle("a", minutes * 60 - 30, p=0)
    return bundle_source(s.bundle(tmp_path / ("b" + day.isoformat())))


@pytest.mark.parametrize("mode", ("descriptive",))
@pytest.mark.parametrize("day,reason", [(date(2026, 10, 1), "reserved_window"), (date(2026, 11, 13), "shadow_embargo"),
                                        (date(2026, 10, 20), "shadow_embargo")])
def test_runner_refuses_embargoed_days(tmp_path, mode, day, reason):
    with pytest.raises(EmbargoRefused, match=reason):
        frontier_runner.run([_source(tmp_path, day)], decay=DECAY, mode=mode)


@pytest.mark.parametrize("day,reason", [(date(2026, 10, 1), "reserved_window"), (date(2026, 11, 13), "shadow_embargo"),
                                        (date(2026, 10, 20), "shadow_embargo")])
def test_a_signed_scored_read_is_still_refused_on_embargoed_days(tmp_path, monkeypatch, day, reason):
    """The registration gate passes here (pinned, signed, matching), so the refusal is the embargo's."""
    from maker_core.frontier import prereg
    from maker_core.frontier.grid import GRID_HASH
    V2_BINDING = "maker_core.frontier.seams.PricePathFillModel@v2-price-path.1:v2-strictly_through"
    doc = ("Grid hash: `%s`\nDecay digest: `%s`\nFill model: `%s`\nSigned: Owner, 2026-11-01\n"
           % (GRID_HASH, DECAY.digest(), V2_BINDING)).encode()
    monkeypatch.setattr(prereg, "SIGNED_PREREGISTRATION_SHA256", prereg.registration_hash(doc))
    assert prereg.verify(doc, decay_digest=DECAY.digest(), fill_model_binding=V2_BINDING)
    with pytest.raises(EmbargoRefused, match=reason):
        frontier_runner.run([_source(tmp_path, day)], decay=DECAY, mode="scored", registration=doc)


def test_runner_refuses_a_market_whose_close_falls_in_the_window(tmp_path):
    # Day 09-28 is allowed, but Scenario markets close two days later, on 09-30.
    with pytest.raises(EmbargoRefused, match="reserved_window"):
        frontier_runner.run([_source(tmp_path, date(2026, 9, 28))], decay=DECAY)


def test_runner_checks_every_instant_trade_and_settlement(tmp_path, monkeypatch):
    seen = []

    def spy(purpose, *values):
        seen.append((purpose, values))

    monkeypatch.setattr(embargo, "check", spy)
    frontier_runner.run([_source(tmp_path, date(2026, 11, 20))], decay=DECAY, points=(), baselines=("no-quote",))
    checked = {v for _, values in seen for v in values}
    assert {p for p, _ in seen} == {"descriptive"}
    assert date(2026, 11, 20) in checked
    start = at(date(2026, 11, 20), 0)
    assert start + timedelta(seconds=125) in checked  # the trade instant and its traded_at
    assert start + timedelta(seconds=330) in checked  # the settlement instant and its as_of
    assert start + timedelta(days=2) in checked       # the market close
    assert start + timedelta(days=2, minutes=1) in checked  # the market settle time
    assert all(start + timedelta(minutes=m) in checked for m in range(6))


def test_runner_allows_days_outside_both_windows(tmp_path):
    result = frontier_runner.run([_source(tmp_path, date(2026, 11, 20))], decay=DECAY, points=(),
                                 baselines=("blind_re1",))
    assert result["days"] == ["2026-11-20"] and result["label"] == "DESCRIPTIVE"
    assert result["strategies"]["blind_re1"]["filled_shares"] == D(10)
