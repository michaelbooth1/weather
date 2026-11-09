"""Guards: WP-01 T5-R guards, selection, capital and isolated pure policy API."""
import ast
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import json
import re

import pytest

from weather.market import f3_policy as p
from weather.market.f3_types import (
    BandCandidate, BandDayUsage, BookState, CapitalState, EnvelopeCell, F3Params,
    Level, ObsState, PortfolioState, QuotePair, Refusal, SimCashState, Terms,
    TokenBook, UniverseCity, Window, load_nwp_schedule, load_policy,
)
from weather.paths import REPO_ROOT

PARAMS = F3Params()
NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
TERMS = Terms(D(24), D(20), D("4.5"), D(".05"), D(0), D(".25"))
CITY = UniverseCity("london", "Europe/London", "EGLC", "metar_routine", ("highest", "lowest"))


def book(bid=".40", ask=".43", size="30"):
    bid, ask, size = D(bid), D(ask), D(size)
    yes = TokenBook((Level(bid, size),), (Level(ask, size),), D(".01"), D(20))
    no = TokenBook((Level(1-ask, size),), (Level(1-bid, size),), D(".01"), D(20))
    return BookState("known", yes, no, NOW)


def candidate(**changes):
    return replace(BandCandidate("london", "highest", date(2026,9,21), "X", ("Y", "N"), ("X",),
                   book(), TERMS, "cell", "cluster"), **changes)


def state(**changes):
    capital = CapitalState(D(300), D(0), D(0), D(0), D(0), D(0), D(0), D(0), D(0), "net_of_retained_gains")
    return replace(PortfolioState(capital, SimCashState(D(300), D(300)), {}, frozenset(), {}, {}, frozenset()), **changes)


def envelope(amount="50", *, validated=True, shape="additive"):
    return {"cell": EnvelopeCell("cell", shape, D(amount) if shape == "additive" else None,
                D(amount) if shape == "proportional" else None, D(10), validated)}


def select(candidates, portfolio=None, **changes):
    universe = {c.city: replace(CITY, slug=c.city, timezone="UTC") for c in candidates}
    return p.select(candidates, portfolio or state(), now_utc=NOW, windows=(), universe=universe,
                    envelope=envelope(), params=replace(PARAMS, **changes))


@pytest.mark.parametrize("distance,expected", [(".5","15.802"),("1","12.099"),("1.5","8.889"),
    ("2","6.173"),("2.5","3.951"),("3","2.222"),("4.5","0.000")])
def test_decimal_score_table(distance, expected):
    assert p.order_score(D(20), D(distance), D("4.5"), D(20)).quantize(D(".001")) == D(expected)
    assert p.order_score(D(19), D(distance), D("4.5"), D(20)) == 0


@pytest.mark.parametrize("mid,expected", [(".10",3),(".90",3),(".0999",0),(".9001",0)])
def test_q_min_inclusive_window(mid, expected):
    assert p.q_min(D(9),D(0),D(mid)) == expected


@pytest.mark.parametrize("bid,ask,mid,yes,no,reserve,distance", [
    (".40",".43",".415",".40",".57","19.40","1.5"),
    (".40",".42",".41",".39",".57","19.20","2.0"),
    (".79",".81",".80",".78",".18","19.20","2.0"),
    (".19",".21",".20",".18",".78","19.20","2.0")])
def test_outward_snap_and_leg_boundaries(bid,ask,mid,yes,no,reserve,distance):
    q = p.quote_pair(book(bid,ask), TERMS, PARAMS)
    assert isinstance(q, QuotePair)
    assert (q.adjusted_mid,q.yes_buy,q.no_buy,q.reserve_pusd) == tuple(map(D,(mid,yes,no,reserve)))
    assert q.distances_cents == (D(distance),D(distance))


def test_true_no_touch_binds_even_when_not_mirrored():
    current = book(".40",".42")
    no = replace(current.no,bids=(Level(D(".55"),D(30)),),asks=(Level(D(".57"),D(30)),))
    assert p.quote_pair(replace(current,no=no), TERMS, PARAMS).code == "would_cross_or_violate_touch_buffer"
    assert p.quote_pair(book(".80",".82"), TERMS, PARAMS).code == "midpoint_outside_treatment"


def test_adjusted_mid_is_level_filter_not_cumulative_or_plain():
    token = replace(book().yes, bids=(Level(D(".42"),D(10)),Level(D(".41"),D(10)),Level(D(".40"),D(20))))
    assert p.adjusted_mid(token,D(20)) == D(".415")
    assert p.adjusted_mid(replace(token,asks=()),D(20)) is None


@pytest.mark.parametrize("zone,event,before,at", [
    ("Europe/London","2026-10-25","2026-10-24T22:44:00+00:00","2026-10-24T22:45:00+00:00"),
    ("Europe/London","2026-10-26","2026-10-25T23:44:00+00:00","2026-10-25T23:45:00+00:00"),
    ("Pacific/Auckland","2026-11-20","2026-11-19T10:44:00+00:00","2026-11-19T10:45:00+00:00")])
def test_midnight_guard_uses_zoneinfo_across_dst(zone,event,before,at):
    city = replace(CITY,timezone=zone)
    cand = candidate(event_date_local=date.fromisoformat(event))
    before,at=map(datetime.fromisoformat,(before,at))
    assert not p.guards(cand,now_utc=before,windows=(),city=city,params=PARAMS)
    hits=p.guards(cand,now_utc=at,windows=(),city=city,params=PARAMS)
    assert [(h.guard,h.action) for h in hits] == [("G-MID","retire")]
    assert p.stratum(city,"highest",cand.event_date_local,before,PARAMS) == "H-PRE"
    assert p.stratum(city,"highest",cand.event_date_local,at,PARAMS) is None


def test_nwp_windows_include_previous_cycle_and_half_open_edges():
    schedule=load_nwp_schedule(REPO_ROOT/"config/f3/nwp_release_schedule.json")
    windows=p.nwp_windows(schedule,date(2026,11,20))
    assert len(windows) == 12
    first=windows[0]
    assert first.source == "IFS_HRES_open:18"
    assert first.start_utc == datetime(2026,11,20,1,29,tzinfo=timezone.utc)
    assert first.end_utc == datetime(2026,11,20,2,4,tzinfo=timezone.utc)
    assert sum((w.end_utc-w.start_utc).total_seconds() for w in windows) == 420*60
    cand=candidate(event_date_local=date(2026,11,21))
    hits=lambda t:p.guards(cand,now_utc=t,windows=windows,city=CITY,params=PARAMS)
    assert "G-NWP" not in {h.guard for h in hits(first.start_utc-timedelta(microseconds=1))}
    assert "G-NWP" in {h.guard for h in hits(first.start_utc)}
    assert "G-NWP" not in {h.guard for h in hits(first.end_utc)}
    assert "G-NWP" in {h.guard for h in hits(datetime(2026,11,20,15,30,tzinfo=timezone.utc))}


@pytest.mark.parametrize("condition,minute,expected", [("X",47,True),("Y",47,True),("Z",47,False),
    ("X",46,True),("X",56,True),("X",57,False)])
def test_obs_guard_in_day_and_neighbours(condition,minute,expected):
    obs=ObsState((NOW.replace(hour=13,minute=51),),"X",("Y",))
    cand=candidate(condition_id=condition,event_date_local=NOW.date(),obs=obs)
    hits=p.guards(cand,now_utc=NOW.replace(hour=13,minute=minute),windows=(),city=CITY,params=PARAMS)
    assert ([(h.guard,h.action) for h in hits] == [("G-OBS","cancel")]) is expected


def test_t_plus_one_has_no_observation_guard_and_impossible_is_cancelled():
    cand=candidate()
    assert not p.guards(cand,now_utc=NOW,windows=(),city=CITY,params=PARAMS)
    hits=p.guards(replace(cand,possible=False),now_utc=NOW,windows=(),city=CITY,params=PARAMS)
    assert [(h.guard,h.action) for h in hits] == [("G-POSS","cancel")]
    obs=ObsState((),"X",())
    hits=p.guards(replace(cand,possible=False,obs=obs,event_date_local=NOW.date()),now_utc=NOW,windows=(),city=CITY,params=PARAMS)
    assert [(h.guard,h.action) for h in hits] == [("G-POSS","cancel"),("G-OBS","retire")]


@pytest.mark.parametrize("cand,expected", [
    (candidate(terms=None),("G-TERMS","no_post")),
    (candidate(terms=replace(TERMS,min_size=D(50))),("G-TERMS","no_post")),
    (candidate(terms=replace(TERMS,max_spread_cents=D("2.5"))),("G-TERMS","no_post")),
    (candidate(terms=replace(TERMS,fee_maker=D(".001"))),("G-FEE","exclude_day")),
    (candidate(book=replace(book(),state="unknown")),("G-STALE","no_post"))])
def test_terms_fee_and_stale_guards(cand,expected):
    assert [(h.guard,h.action) for h in p.guards(cand,now_utc=NOW,windows=(),city=CITY,params=PARAMS)] == [expected]


def test_envelope_value_uses_conservative_four_side_bound():
    cand=candidate(book=book(size="45"))
    pair=p.quote_pair(cand.book,TERMS,PARAMS)
    assert p.competitor_q(cand.book,pair.adjusted_mid,TERMS) == D(40)
    reward,score=p.value(cand,pair,envelope("480"),PARAMS)
    assert (reward/TERMS.rate_daily_pusd).quantize(D(".000001")) == D(".016807")
    assert reward.quantize(D(".0001")) == D(".4034")
    assert score == reward/pair.reserve_pusd
    assert p.value(cand,pair,envelope(validated=False),PARAMS) == (D(0),D(0))
    assert p.value(cand,pair,{},PARAMS) == (D(0),D(0))


def test_empty_competition_still_pays_envelope_denominator():
    pair=p.quote_pair(book(),TERMS,PARAMS)
    empty=replace(book(),yes=replace(book().yes,bids=(),asks=()),no=replace(book().no,bids=(),asks=()))
    cand=candidate(book=empty)
    reward,_=p.value(cand,pair,envelope("50"),PARAMS)
    assert (reward/TERMS.rate_daily_pusd).quantize(D(".000001")) == D(".150943")
    assert 0 < reward < TERMS.rate_daily_pusd
    reward,_=p.value(cand,pair,envelope("9",shape="proportional"),PARAMS)
    assert reward/TERMS.rate_daily_pusd == D(".1")


def test_own_orders_subtracted_after_duplicate_aggregation_and_on_mirror():
    current=book(size="20")
    yes=replace(current.yes,bids=(Level(D(".40"),D(10)),Level(D(".40"),D(10))))
    no=replace(current.no,asks=(Level(D(".60"),D(10)),Level(D(".60"),D(10))))
    current=replace(current,yes=yes,no=no)
    before=p.competitor_q(current,D(".415"),TERMS)
    after=p.competitor_q(current,D(".415"),TERMS,(("YES",D(".40"),D(20)),))
    assert after == before/2
    assert p.competitor_q(current,D(".415"),TERMS,(("YES",D(".40"),D(20)),("NO",D(".57"),D(20)))) == 0


def test_one_bin_per_cfd_then_no_replacement():
    candidates=[candidate(condition_id=cid,terms=replace(TERMS,rate_daily_pusd=D(rate))) for cid,rate in (("C","3"),("B","5"),("A","9"))]
    result=select(candidates)
    assert [c.condition_id for c,_,_ in result.picks] == ["A"]
    again=select(candidates,state(quoted_cfds=frozenset({candidates[0].cfd_key})))
    assert not again.picks and again.refusals == {"f3_cfd_already_quoted":3}
    assert result == select(list(reversed(candidates)))


def test_cluster_cap_and_active_cluster_count():
    candidates=[candidate(city=f"city-{i}",condition_id=str(i)) for i in range(5)]
    result=select(candidates)
    assert len(result.picks) == 3 and result.refusals == {"f3_cluster_cap":2}
    result=select(candidates,state(active_bands={"existing":"cluster"}))
    assert len(result.picks) == 2 and result.refusals == {"f3_cluster_cap":3}


def test_concurrency_cap_and_tie_order():
    candidates=[candidate(city=f"city-{i}",condition_id=f"{i:02d}",cluster=f"cluster-{i}") for i in range(20)]
    result=select(list(reversed(candidates)))
    assert [c.condition_id for c,_,_ in result.picks] == [f"{i:02d}" for i in range(15)]
    assert result.refusals == {"f3_concurrency_cap":1}
    assert sum(pair.reserve_pusd for _,pair,_ in result.picks) <= D(300)


def test_reward_floor_and_unvalidated_cell():
    cand=candidate(book=book(size="45"),terms=replace(TERMS,rate_daily_pusd=D(".4")))
    universe={"london":CITY}
    result=p.select([cand],state(),now_utc=NOW,windows=(),universe=universe,envelope=envelope("40"),params=PARAMS)
    assert not result.picks and result.refusals == {"f3_reward_below_floor":1}
    result=p.select([candidate()],state(),now_utc=NOW,windows=(),universe=universe,envelope=envelope(validated=False),params=PARAMS)
    assert result.refusals == {"f3_reward_below_floor":1}


def test_gate_refusals_and_prospective_reserves_counted():
    candidates=[candidate(city=f"city-{i}",condition_id=str(i),cluster=str(i)) for i in range(3)]
    capital=replace(state().capital,inventory=D(270))
    result=select(candidates,state(capital=capital))
    assert len(result.picks) == 1
    assert result.refusals == {"capital_total_ceiling":2,"gate_refusals":2}
    usage={(candidates[0].band_key,NOW.date().isoformat()):BandDayUsage(D(30),D(0))}
    result=select([candidates[0]],state(band_day_usage=usage))
    assert not result.picks and result.refusals == {"per_band_daily_filled_cap":1,"gate_refusals":1}


def test_event_inventory_horizon_guard_and_cash_refusals():
    cand=candidate(event_condition_ids=("X","SIBLING"))
    assert select([cand],state(held_conditions=frozenset({"sibling"}))).refusals == {"f3_event_held":1}
    assert select([replace(cand,family="lowest")]).refusals == {"f3_not_h_pre":1}
    assert select([replace(cand,possible=False)]).refusals == {"G-POSS":1}
    assert select([cand],state(per_market_open={"X":D(290)})).refusals == {"f3_per_market_cash":1}
    assert p.per_market_cash_ok(D(280),D(20),D(300))
    assert not p.per_market_cash_ok(D(280),D("20.000001"),D(300))


def test_handwritten_money_boundaries():
    c=CapitalState(D(300),D(100),D(150),D(40),D(0),D(10),D(10),D(0),D(0),"net_of_retained_gains")
    cash=SimCashState(D(500),D(500))
    assert p.gate(c,reserve=D("19.60"),own_resting=D(0),cash=cash).ok
    replacement=p.gate(c,reserve=D("19.60"),own_resting=D("19.60"),cash=cash)
    assert replacement.ok and replacement.figures["charged_native"] == D(280_000_000)
    assert p.gate(c,reserve=D("20.01"),own_resting=D(0),cash=cash).code == "capital_total_ceiling"
    assert p.gate(replace(c,basis="gross"),reserve=D("19.60"),own_resting=D(0),cash=cash).code == "capital_total_ceiling"
    assert p.gate(c,reserve=D("19.60"),own_resting=D(0),cash=SimCashState(D(120),D(120))).code == "capital_spendable_cash"
    usage=BandDayUsage(D(25),D("9.60"),D(25))
    assert p.daily_gate(usage,reserve=D("5.40"),own_resting=D(0),cap=D(40)).ok
    assert p.daily_gate(usage,reserve=D("9.80"),own_resting=D(0),cap=D(40)).code == "per_band_daily_filled_cap"


def test_f2_policy_adapter_requires_frozen_basis_and_source():
    row=json.loads((REPO_ROOT/"config/f3/f3_policy.example.json").read_text(encoding="utf-8"))
    row["owner_funding_ceiling_pusd"]=row["sleeve_ceiling_pusd"]
    row.update(quote_offset_pusd=".025",sleeve_loss_basis="gross")
    result=p.params_from_f2_policy(row,f2_git_sha="a"*40,f2_policy_sha256="b"*64)
    assert result.quote_offset_pusd == D(".025") and result.sleeve_loss_basis == "gross"
    assert result.f2_source["git_sha"] == "a"*40
    del row["sleeve_loss_basis"]
    with pytest.raises(ValueError):
        p.params_from_f2_policy(row,f2_git_sha="a"*40,f2_policy_sha256="b"*64)


def test_pure_modules_have_no_forbidden_edges_io_or_clocks():
    for name in ("f3_types","f3_policy"):
        source=(REPO_ROOT/"src/weather/market"/(name+".py")).read_text(encoding="utf-8")
        tree=ast.parse(source)
        docstrings={id(node.value) for node in ast.walk(tree) if isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant)
                    and isinstance(node.value.value,str)}
        for node in ast.walk(tree):
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                imports=[alias.name for alias in node.names] if isinstance(node,ast.Import) else [node.module or ""]
                for value in imports:
                    assert not re.search(r"(^|\.)(lfc_|reward_quote|mm_stage2_|backtesting|urllib|socket|requests|random)",value)
            if isinstance(node,ast.Call):
                call=ast.unparse(node.func)
                assert not call.endswith((".now",".utcnow")) and call != "time.time"
                if name == "f3_policy":
                    assert call not in ("open","print","input") and not call.endswith((".read_text",".read_bytes",".write_text",".write_bytes"))
            if isinstance(node,ast.Constant) and isinstance(node.value,str) and id(node) not in docstrings:
                assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b",node.value)


def test_naive_or_non_utc_times_are_programming_errors():
    with pytest.raises(ValueError):
        p.stratum(CITY,"highest",date(2026,9,21),datetime(2026,9,20),PARAMS)
    with pytest.raises(ValueError):
        p.guards(candidate(),now_utc=NOW.astimezone(timezone(timedelta(hours=1))),windows=(),city=CITY,params=PARAMS)
