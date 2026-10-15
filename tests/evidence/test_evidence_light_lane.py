"""S5 light batch lane (LB-1 label panel, VR-5 trades) on fixture payloads; no live endpoint.

Guards: docs/operations/EVIDENCE_HOST.md (DLv2 plan S5 rows: the light lane runs each task once per
local day in 00:30-01:00, serially, under a <=256 MiB Job cap and a <=600 s wall bound; the fetch
guard's ``capture`` mode refuses every ``full`` embargo day and records outcome/MG-1 scopes; LB-1
writes one panel row per location-day-kind and at most one strict-guarded WRH wanted row per US
station-day where METAR-all and METAR-hourly disagree (owner Q4); VR-5 keeps public wallet
addresses and drops profile fields (owner Q3 = A), requests only the two International Polymarket
public hosts and fetches prices-history once per closed-market token; S5b: WU daily and the IEM 6 h
composite sit behind the STRICT guard over the day and one day either side, so the boundary dates
2026-09-30 and 2026-10-15 never get a request URL, and WU goes only through the existing OD15
page-token client with the access value never journalled or stored; the US 1-minute ASOS and NWS
CLI/CF6 members sit behind the same strict guard, one public IEM request per station-day each).
"""
from __future__ import annotations

import gzip
import io
import json
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from weather.evidence import batch
from weather.evidence.batch import LightLaneConfigError, run_task, task_configs, utc_days
from weather.evidence.child import PollContext
from weather.evidence.config import MIB, declared_caps_bytes, load_config, load_locations
from weather.evidence.embargo import EmbargoRefused, embargo_guard
from weather.evidence.fetch import Fetcher, Response
from weather.evidence.host import LightLaneSupervisor
from weather.evidence.journal import EvidenceJournal, iter_segment_rows, segment_dirs
from weather.evidence.reader import read
from weather.evidence.tasks import lb1_labels, lb1_strict, lb1_us, vr5_trades
from weather.evidence.telemetry import FamilyTelemetry

LOCATIONS = load_locations()
CONFIG, CONFIG_SHA = load_config()
STATIONS = lb1_labels.panel_stations(LOCATIONS, {"HKO": "VHHH"})
CONDITION_A, CONDITION_B = "0x" + "a" * 64, "0x" + "b" * 64
CONFIG_IEM_ONLY = json.loads(json.dumps(CONFIG))
CONFIG_IEM_ONLY["light_lane"]["tasks"]["lb1_labels"].update(wu_daily=False, asos_1min=False, cli_cf6=False)
CONFIG_US_ONLY = json.loads(json.dumps(CONFIG))
CONFIG_US_ONLY["light_lane"]["tasks"]["lb1_labels"]["wu_daily"] = False


class Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def _events(root, family, day):
    out = []
    for segment in segment_dirs(root / family / day):
        out += [row for name, row in iter_segment_rows(segment) if name == "events.jsonl"]
    return out


def _rows(root, family, day):
    return read(family, "2030-01-01T00:00:00Z", "capture_check", days=[day], root=root).rows


def _run(task, tmp_path, transport, now, *, days=None, config=None, monotonic=None):
    return run_task(task, config=config or CONFIG, config_sha256=CONFIG_SHA, root=tmp_path, repo_root=tmp_path,
                    locations=LOCATIONS, days=days, transport=transport, clock=Clock(now), sleep=lambda _s: None,
                    monotonic=monotonic or (lambda: 0.0))


# ------------------------------------------------------------------------------------- capture guard
def test_capture_mode_refuses_full_and_records_outcome_and_mg1_scopes():
    today = date(2026, 12, 1)
    assert embargo_guard("t", "2026-01-02", mode="capture", today=today)["decision"] == "allowed"
    with pytest.raises(EmbargoRefused) as refused:
        embargo_guard("t", "2026-10-05", mode="capture", today=today)
    assert refused.value.reason == "fetch_event_date_full_window"
    outcome = embargo_guard("t", "2026-10-20", mode="capture", today=today)
    assert outcome["decision"] == "allowed_outcome_blind_capture"
    assert {"outcome", "mg1_reserved"} <= set(outcome["scopes"])
    for strict in ("backfill", "sweep"):
        for day in ("2026-10-05", "2026-10-20"):
            with pytest.raises(EmbargoRefused):
                embargo_guard("t", day, mode=strict, today=today)


# ------------------------------------------------------------------------------------- lane config
def test_task_configs_bound_caps_walls_modules_and_names():
    assert list(task_configs(CONFIG)) == ["lb1_labels", "vr5_trades"]
    without = json.loads(json.dumps(CONFIG))
    without.pop("light_lane")
    assert declared_caps_bytes(CONFIG) - declared_caps_bytes(without) == 256 * MIB
    assert batch.max_task_cap_bytes(CONFIG) == 256 * MIB
    for key, value in (("ram_cap_mib", 257), ("wall_seconds", 601), ("module", "weather.evidence.families.x"),
                       ("hour_byte_budget_mib", 0)):
        bad = json.loads(json.dumps(CONFIG))
        bad["light_lane"]["tasks"]["lb1_labels"][key] = value
        with pytest.raises(LightLaneConfigError):
            task_configs(bad)
    clash = json.loads(json.dumps(CONFIG))
    clash["light_lane"]["tasks"]["ob1_metar"] = clash["light_lane"]["tasks"]["lb1_labels"]
    with pytest.raises(LightLaneConfigError):
        task_configs(clash)
    missing = json.loads(json.dumps(CONFIG))
    del missing["light_lane"]["tasks"]["vr5_trades"]["wall_seconds"]
    with pytest.raises(LightLaneConfigError):
        task_configs(missing)


def test_utc_days_spans_every_day_touched():
    start = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    assert utc_days(start, start + timedelta(hours=50)) == ["2026-01-01", "2026-01-02", "2026-01-03"]


# ------------------------------------------------------------------------------------- LB-1 parsers
def test_iem_ids_local_days_and_default_days():
    assert len(STATIONS) == 51 and lb1_labels.iem_station("KLGA", "US") == "LGA"
    assert lb1_labels.iem_station("CYYZ", "CA") == "CYYZ" and lb1_labels.iem_station("PHNL", "US") == "PHNL"
    nyc = next(s for s in STATIONS if s["location"] == "nyc")
    assert (nyc["iem"], nyc["unit"]) == ("LGA", "F")
    start, end = lb1_labels.local_day_bounds(date(2026, 1, 2), "America/New_York")
    assert (start.hour, end - start) == (5, timedelta(days=1))
    # Pacific/Auckland is first to finish, Los Angeles last: 2026-01-02 ends 08:00Z there.
    assert lb1_labels.default_days(datetime(2026, 1, 3, 9, 1, tzinfo=timezone.utc), STATIONS) == [
        date(2026, 1, 2), date(2026, 1, 1)]
    assert lb1_labels.default_days(datetime(2026, 1, 3, 8, 59, tzinfo=timezone.utc), STATIONS)[0] == date(2026, 1, 1)


def test_hourly_rule_is_routine_with_a_numeric_slp_group():
    text = ("station,valid,tmpc,metar\n"
            "LGA,2026-01-02 17:51,10.0,KLGA 021751Z 00000KT 10SM CLR 10/01 A3000 RMK AO2 SLP160 T01000010\n"
            "LGA,2026-01-02 18:51,12.0,KLGA 021851Z 00000KT 10SM CLR 12/01 A3000 RMK AO2 SLPNO\n"
            "LGA,2026-01-02 19:51,M,KLGA 021951Z 00000KT 10SM CLR A3000 RMK AO2 SLP160\n")
    routine = lb1_labels.parse_iem_csv(text, lb1_labels.ROUTINE)
    special = lb1_labels.parse_iem_csv("station,valid,tmpc,metar\nLGA,2026-01-02 18:20,15.0,KLGA 021820Z RMK AO2\n",
                                       lb1_labels.SPECIAL)
    assert len(routine) == 2 and routine[0]["slp_hpa"] is not None and routine[1]["slp_hpa"] is None
    nyc = next(s for s in STATIONS if s["location"] == "nyc")
    inst = lb1_labels.metar_instruments(routine + special, nyc, date(2026, 1, 2))
    assert (inst["metar_all"]["max"], inst["metar_all"]["reports"]) == (59, 3)  # 15.0 C = 59 F
    assert (inst["metar_hourly"]["max"], inst["metar_hourly"]["reports"]) == (50, 1)
    assert lb1_labels.wants_wrh(nyc, inst) == ["max"]  # min agrees at 50 F
    london = next(s for s in STATIONS if s["location"] == "london")
    assert lb1_labels.wants_wrh(london, inst) == []


def test_finality_proxy_uses_state_when_the_next_day_report_was_first_seen():
    nyc = next(s for s in STATIONS if s["location"] == "nyc")

    def row(obs, seen, temp):
        return {"first_seen_utc": seen, "body": {"station": "KLGA", "obs_time_utc": obs, "t_group_c": temp}}

    rows = [row("2026-01-02T18:51:00Z", "2026-01-02T18:55:00Z", 10.0),
            row("2026-01-03T04:51:00Z", "2026-01-03T06:10:00Z", 12.0),   # late arrival: after the cutoff
            row("2026-01-03T05:51:00Z", "2026-01-03T05:56:00Z", 1.0)]    # first report of the next local day
    proxy = lb1_labels.ob1_finality_proxy(rows, nyc, date(2026, 1, 2))
    assert proxy["status"] == "ok" and proxy["final_at_utc"] == "2026-01-03T05:56:00Z"
    assert (proxy["max"], proxy["reports"]) == (50, 1)
    assert lb1_labels.ob1_finality_proxy(rows[:2], nyc, date(2026, 1, 2))["status"] == "no_next_day_report"


# ------------------------------------------------------------------------------------- LB-1 runs
def _iem_transport(calls, *, special_temps=None):
    special_temps = special_temps or {}

    def transport(url, headers, timeout, max_bytes):
        calls.append(url)
        if not urlparse(url).path.endswith("/asos.py"):
            return Response(url, 404)
        query = parse_qs(urlparse(url).query)
        start = datetime.strptime(query["sts"][0], "%Y-%m-%dT%H:%M:%SZ")
        end = datetime.strptime(query["ets"][0], "%Y-%m-%dT%H:%M:%SZ")
        lines = ["station,valid,tmpc,metar"]
        for station in query["station"]:
            if query["report_type"][0] == "3":
                t = start.replace(minute=51)
                while t < end:
                    lines.append(f"{station},{t:%Y-%m-%d %H:%M},10.0,{station} {t:%d%H%M}Z RMK AO2 SLP160")
                    t += timedelta(hours=1)
            elif station in special_temps:
                when, temp = special_temps[station]
                lines.append(f"{station},{when},{temp},{station} SPECI RMK AO2")
        return Response(url, 200, ("\n".join(lines) + "\n").encode())
    return transport


def test_lb1_writes_51_station_panel_and_one_pending_wrh_row_for_a_us_disagreement(tmp_path):
    calls = []
    transport = _iem_transport(calls, special_temps={"LGA": ("2026-01-02 18:20", 30.0),
                                                     "EGLC": ("2026-01-02 12:20", 30.0)})
    result = _run("lb1_labels", tmp_path, transport, datetime(2026, 1, 3, 15, tzinfo=timezone.utc),
                  days=["2026-01-02"], config=CONFIG_IEM_ONLY)
    assert result["outcome"] == "ok" and result["refused_days"] == [] and result["wrh_wanted"] == 1
    assert len(calls) == 12 and all(urlparse(u).hostname == "mesonet.agron.iastate.edu" for u in calls)
    assert {parse_qs(urlparse(u).query)["report_type"][0] for u in calls} == {"3", "4"}
    rows = _rows(tmp_path, "lb1_labels", "2026-01-03")
    panel = [r for r in rows if r["channel"] == "label_panel"]
    assert len(panel) == 102 and {r["body"]["label_kind"] for r in panel} == {"max", "min"}
    assert all(r["event_date"] == "2026-01-02" and r["body"]["read"] == "backfill" for r in panel)
    nyc = next(r["body"] for r in panel if r["key"] == "nyc|2026-01-02|max")
    assert nyc["instruments"]["metar_all"]["max"] == 86 and nyc["instruments"]["metar_hourly"]["max"] == 50
    assert nyc["venue_view"] == "metar_hourly" and nyc["wrh_wanted"] is True
    london = next(r["body"] for r in panel if r["key"] == "london|2026-01-02|max")
    assert london["venue_view"] == "metar_all" and london["wrh_wanted"] is False
    wrh = [r for r in rows if r["channel"] == "wrh_read"]
    assert [r["key"] for r in wrh] == ["KLGA|2026-01-02"]
    assert wrh[0]["body"]["status"] == "pending_route" and wrh[0]["body"]["kinds"] == ["max"]
    # The re-run neither duplicates the WRH row nor rewrites unchanged panel rows.
    again = _run("lb1_labels", tmp_path, transport, datetime(2026, 1, 3, 16, tzinfo=timezone.utc),
                 days=["2026-01-02"], config=CONFIG_IEM_ONLY)
    assert again["wrh_wanted"] == 0 and again["panel_rows"] == 0


def test_lb1_outcome_day_writes_the_panel_but_no_wrh_row(tmp_path):
    calls = []
    transport = _iem_transport(calls, special_temps={"LGA": ("2026-10-20 18:20", 30.0)})
    result = _run("lb1_labels", tmp_path, transport, datetime(2026, 10, 21, 15, tzinfo=timezone.utc),
                  days=["2026-10-20"])
    assert result["panel_rows"] == 102 and result["wrh_wanted"] == 0 and calls
    rows = _rows(tmp_path, "lb1_labels", "2026-10-21")
    assert not [r for r in rows if r["channel"] == "wrh_read"]
    guards = [e for e in _events(tmp_path, "lb1_labels", "2026-10-21") if e["kind"] == "guard"]
    assert guards and guards[-1]["mode"] == "backfill" and guards[-1]["reason"] == "fetch_event_date_embargoed"


def test_lb1_full_window_day_sends_no_request(tmp_path):
    calls = []
    result = _run("lb1_labels", tmp_path, _iem_transport(calls), datetime(2026, 10, 6, 15, tzinfo=timezone.utc),
                  days=["2026-10-05"])
    assert calls == [] and result["refused_days"] == ["2026-10-05"] and result["panel_rows"] == 0
    guards = [e for e in _events(tmp_path, "lb1_labels", "2026-10-06") if e["kind"] == "guard"]
    assert guards and guards[0]["reason"] == "fetch_event_date_full_window"


def test_lb1_reread_journals_a_cor_event_when_the_proxy_differs(tmp_path):
    clock = Clock(datetime(2026, 1, 4, 15, tzinfo=timezone.utc))
    journal = EvidenceJournal(tmp_path, "lb1_labels", clock=clock).open()
    telemetry = FamilyTelemetry(tmp_path, "lb1_labels", clock=clock)
    fetcher = Fetcher(user_agent="t", request_budget_per_hour=100, telemetry=telemetry,
                      transport=_iem_transport([]), clock=lambda: 0.0)
    ctx = PollContext("lb1_labels", CONFIG["light_lane"]["tasks"]["lb1_labels"], CONFIG["host"], journal, fetcher,
                      telemetry, LOCATIONS, clock, lambda _s: None, channel="lb1_labels")
    nyc = next(s for s in STATIONS if s["location"] == "nyc")
    reports = lb1_labels.parse_iem_csv("station,valid,tmpc,metar\nLGA,2026-01-02 18:51,10.0,LGA RMK AO2 SLP160\n",
                                       lb1_labels.ROUTINE)
    ob1 = [{"first_seen_utc": "2026-01-02T18:55:00Z",
            "body": {"station": "KLGA", "obs_time_utc": "2026-01-02T18:51:00Z", "t_group_c": 11.0}},
           {"first_seen_utc": "2026-01-03T05:56:00Z",
            "body": {"station": "KLGA", "obs_time_utc": "2026-01-03T05:51:00Z", "t_group_c": 1.0}}]
    items, _ = lb1_labels.panel_items([nyc], reports, ob1, date(2026, 1, 2), read_kind="reread", raw_refs=[])
    lb1_labels.record_cor(ctx, items, date(2026, 1, 2))
    journal.close()
    cor = [e for e in _events(tmp_path, "lb1_labels", "2026-01-04") if e["kind"] == "cor"]
    assert {(e["label_kind"], e["proxy"], e["metar_all"]) for e in cor} == {("max", 52, 50), ("min", 52, 50)}


def test_task_deadline_stops_the_task_with_a_wall_cap_row(tmp_path):
    mono, calls = [0.0], []

    def transport(url, headers, timeout, max_bytes):
        mono[0] = 10_000.0  # the next fetch is past the wall bound
        return _iem_transport(calls)(url, headers, timeout, max_bytes)

    result = _run("lb1_labels", tmp_path, transport, datetime(2026, 1, 3, 15, tzinfo=timezone.utc),
                  days=["2026-01-02"], monotonic=lambda: mono[0])
    assert result["outcome"] == "wall_bound" and len(calls) == 1
    caps = [e for e in _events(tmp_path, "lb1_labels", "2026-01-03") if e["kind"] == "cap"]
    assert caps and caps[0]["reason"] == "wall_seconds"


# ------------------------------------------------------------------------------------- VR-5
def _vr3_rows(root, now):
    journal = EvidenceJournal(root, "vr3_gamma", clock=Clock(now)).open()
    markets = [{"conditionId": CONDITION_A, "clobTokenIds": json.dumps(["111", "222"]), "closed": True},
               {"conditionId": CONDITION_B, "clobTokenIds": ["333", "444"], "closed": False},
               {"conditionId": "0xnot", "clobTokenIds": ["555"]}]
    journal.record_poll("events", [
        {"key": "ev-nyc", "body": {"location": "nyc", "markets": markets},
         "envelope": {"event_date": "2026-01-02", "availability_basis": "live_receipt"}},
        {"key": "ev-pilot", "body": {"location": "not-a-builtin", "markets": markets},
         "envelope": {"event_date": "2026-01-02", "availability_basis": "live_receipt"}}])
    journal.close()


def _venue_transport(calls):
    def transport(url, headers, timeout, max_bytes):
        calls.append(url)
        parts = urlparse(url)
        query = parse_qs(parts.query)
        if parts.hostname == vr5_trades.DATA_HOST:
            cid = query["market"][0]
            trades = [{"proxyWallet": "0x" + "1" * 40, "side": "BUY", "asset": "111", "conditionId": cid, "size": 5,
                       "price": 0.4, "timestamp": 1767355800, "transactionHash": "0x" + "c" * 64,
                       "name": "someone", "pseudonym": "Some-One", "bio": "x", "profileImage": "https://img"},
                      {"proxyWallet": "0x" + "2" * 40, "side": "SELL", "asset": "222", "conditionId": cid, "size": 1,
                       "price": 0.6, "timestamp": 1767355860, "transactionHash": "0x" + "d" * 64}]
            return Response(url, 200, json.dumps(trades).encode())
        return Response(url, 200, json.dumps({"history": [{"t": 1767312000, "p": 0.4},
                                                          {"t": 1767312060, "p": 0.41}]}).encode())
    return transport


def test_vr5_keeps_wallets_drops_profiles_and_fetches_history_once_for_closed_markets(tmp_path):
    _vr3_rows(tmp_path, datetime(2026, 1, 3, 1, tzinfo=timezone.utc))
    calls = []
    now = datetime(2026, 1, 5, 2, tzinfo=timezone.utc)
    result = _run("vr5_trades", tmp_path, _venue_transport(calls), now)
    assert result["outcome"] == "ok" and result["conditions"] == 2 and sorted(result["event_days"]) == [
        "2026-01-02", "2026-01-03", "2026-01-04"]
    assert all(vr5_trades.allowed(u) for u in calls)
    hosts = [urlparse(u).hostname for u in calls]
    assert hosts.count(vr5_trades.DATA_HOST) == 2 and hosts.count(vr5_trades.CLOB_HOST) == 2
    history_tokens = {parse_qs(urlparse(u).query)["market"][0] for u in calls if "prices-history" in u}
    assert history_tokens == {"111", "222"}
    rows = _rows(tmp_path, "vr5_trades", "2026-01-05")
    trades = [r for r in rows if r["channel"] == "trades"]
    assert len(trades) == 4 and {r["body"]["proxyWallet"] for r in trades} == {"0x" + "1" * 40, "0x" + "2" * 40}
    assert not any(field in r["body"] for r in trades for field in vr5_trades.DROPPED_PROFILE_FIELDS)
    assert {r["body"]["location"] for r in trades} == {"nyc"}
    history = [r for r in rows if r["channel"] == "prices_history"]
    assert {r["key"] for r in history} == {"111", "222"} and all(r["raw_ref"] for r in history)
    assert history[0]["body"]["points"] == 2 and history[0]["body"]["fidelity_minutes"] == 1
    calls.clear()
    again = _run("vr5_trades", tmp_path, _venue_transport(calls), now + timedelta(hours=1))
    assert again["history_rows"] == 0 and all("prices-history" not in u for u in calls)


def test_vr5_urls_are_validated_and_allowlisted():
    assert vr5_trades.allowed(vr5_trades.trades_url(CONDITION_A, 0))
    assert vr5_trades.allowed(vr5_trades.history_url("111", 0, 60))
    assert not vr5_trades.allowed(f"https://{vr5_trades.DATA_HOST}/trades?user=0x{'1' * 40}")
    assert not vr5_trades.allowed("https://gamma-api.polymarket.com/events")
    assert not vr5_trades.allowed(f"http://{vr5_trades.CLOB_HOST}/prices-history")
    with pytest.raises(ValueError):
        vr5_trades.trades_url("0xnot", 0)
    with pytest.raises(ValueError):
        vr5_trades.history_url("abc", 0, 60)


def test_vr5_full_window_event_day_is_refused_before_any_request(tmp_path):
    calls = []
    result = _run("vr5_trades", tmp_path, _venue_transport(calls), datetime(2026, 10, 7, 2, tzinfo=timezone.utc),
                  days=["2026-10-05"])
    assert calls == [] and result["refused_event_days"] == ["2026-10-05"] and result["conditions"] == 0
    assert "2026-10-05" in result["refused_capture_days"]
    guards = [e for e in _events(tmp_path, "vr5_trades", "2026-10-07") if e["kind"] == "guard"]
    assert guards and guards[0]["reason"] == "fetch_event_date_full_window"


def test_vr5_run_request_cap_journals_a_cap_row(tmp_path):
    _vr3_rows(tmp_path, datetime(2026, 1, 3, 1, tzinfo=timezone.utc))
    config = json.loads(json.dumps(CONFIG))
    config["light_lane"]["tasks"]["vr5_trades"]["max_requests_per_run"] = 1
    calls = []
    result = _run("vr5_trades", tmp_path, _venue_transport(calls), datetime(2026, 1, 5, 2, tzinfo=timezone.utc),
                  config=config)
    assert len(calls) == 1 and result["requests"] == 1
    caps = [e for e in _events(tmp_path, "vr5_trades", "2026-01-05") if e["kind"] == "cap"]
    assert caps and caps[0]["reason"] == "max_requests_per_run"


# ------------------------------------------------------------------------------------- supervisor
class LaneRunner:
    def __init__(self, results=None):
        self.calls, self.results = [], list(results or [])

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return self.results.pop(0) if self.results else {"returncode": 0, "duration_seconds": 1.0}


def _lane(tmp_path, runner, local):
    return LightLaneSupervisor(config=CONFIG, config_path="cfg.json", root=tmp_path, runner=runner, python="py",
                               clock=lambda: datetime(2026, 1, 2, 5, tzinfo=timezone.utc),
                               local_clock=lambda: local[0])


def test_lane_runs_each_task_serially_once_per_local_day_in_its_window(tmp_path):
    runner, local = LaneRunner(), [datetime(2026, 1, 2, 0, 29)]
    lane = _lane(tmp_path, runner, local)
    assert not lane.due()
    local[0] = datetime(2026, 1, 2, 0, 40)
    assert lane.due()

    class Stop:
        def __init__(self):
            self.n = 0

        def is_set(self):
            self.n += 1
            return self.n > 2

        def wait(self, _seconds):
            return None

    lane.loop(Stop())
    assert [c[0][-1] for c in runner.calls] == ["lb1_labels", "vr5_trades"]
    command, kwargs = runner.calls[0]
    assert command[:3] == ["py", "-m", "weather.evidence.batch"] and command[-3:] == ["task", "--task", "lb1_labels"]
    assert kwargs["private_memory_max_bytes"] == 256 * MIB and kwargs["timeout_seconds"] == 600.0
    assert lane.state["ran_on"] == "2026-01-02" and not lane.due()
    local[0] = datetime(2026, 1, 3, 0, 31)
    assert lane.due()


def test_lane_cap_kill_receipt_wall_bound_kill_and_host_stop(tmp_path):
    runner = LaneRunner([{"returncode": 1, "resource_limit_exceeded": True, "duration_seconds": 3.0},
                         {"returncode": None, "timed_out": True, "duration_seconds": 600.0}])
    lane = _lane(tmp_path, runner, [datetime(2026, 1, 2, 0, 40)])
    first, second = lane.run_once()
    assert first["outcome"] == "cap_kill" and (tmp_path / first["receipt"]).exists()
    assert second["outcome"] == "wall_bound_kill"
    (tmp_path / "control").mkdir()
    (tmp_path / "control" / "host.stop").write_text("stop\n")
    assert lane.run_once() == [{"task": "lb1_labels", "outcome": "stopped"}]
    assert len(runner.calls) == 2


# ------------------------------------------------------------------------------------- S5b strict instruments
def _task_ctx(root, now, transport):
    clock = Clock(now)
    journal = EvidenceJournal(root, "lb1_labels", clock=clock).open()
    telemetry = FamilyTelemetry(root, "lb1_labels", clock=clock)
    fetcher = Fetcher(user_agent="t", request_budget_per_hour=500, telemetry=telemetry, transport=transport,
                      clock=lambda: 0.0)
    return batch.TaskContext("lb1_labels", CONFIG["light_lane"]["tasks"]["lb1_labels"], CONFIG["host"], journal,
                             fetcher, telemetry, LOCATIONS, clock, lambda _s: None, channel="lb1_labels")


@pytest.mark.parametrize("boundary", ["2026-09-30", "2026-10-15"])
def test_strict_guard_refuses_each_boundary_date(boundary):
    for mode in ("backfill", "sweep"):
        with pytest.raises(EmbargoRefused):
            embargo_guard("lb1_labels", boundary, mode=mode, today=date(2026, 12, 1))


def test_no_wu_or_strict_request_url_is_built_for_boundary_days_or_their_neighbours(tmp_path, monkeypatch):
    from weather.sources import wu_history
    built, calls = [], []
    monkeypatch.setattr(wu_history.PublicWundergroundHistoryClient, "history_page_url",
                        lambda self, d: built.append(d) or "https://www.wunderground.com/x")
    ctx = _task_ctx(tmp_path, datetime(2026, 12, 1, 1, tzinfo=timezone.utc),
                    lambda u, h, t, m: calls.append(u) or Response(u, 500))
    ids = [loc["id"] for loc in LOCATIONS]
    for day in ("2026-09-29", "2026-09-30", "2026-10-15", "2026-10-16"):
        assert lb1_strict.wu_daily(ctx, ctx.cfg, date.fromisoformat(day), ids) is None
        assert not lb1_strict.strict_allowed(ctx, date.fromisoformat(day))
    ctx.journal.close()
    assert built == [] and calls == []
    guards = [e for e in _events(tmp_path, "lb1_labels", "2026-12-01") if e["kind"] == "guard"]
    assert guards and {e["mode"] for e in guards} == {"backfill"}
    assert {"2026-09-30", "2026-10-15"} <= {e["event_date"] for e in guards}


WU_API_HOST = "wu-history-api.invalid"  # the page's runtime data names the API host; tests use a fake one


def _wu_transport(calls, token, *, page_status=200):
    iem = _iem_transport([])

    def transport(url, headers, timeout, max_bytes):
        calls.append(url)
        parts = urlparse(url)
        if parts.hostname == "www.wunderground.com":
            page = ('<html><script>const data = {"API_URL":"https://%s","API_KEY":"%s"};</script>'
                    "</html>" % (WU_API_HOST, token))
            return Response(url, page_status, page.encode() if page_status == 200 else b"")
        if parts.hostname == WU_API_HOST:
            query = parse_qs(parts.query)
            metric = query["units"][0] == "m"
            obs = [{"valid_time_gmt": 1767355200 + 3600 * h, "temp": t, "key": "X", "obs_id": "X"}
                   for h, t in ((0, 5 if metric else 41), (7, 13 if metric else 55), (11, 9 if metric else 48))]
            return Response(url, 200, json.dumps({"metadata": {"status_code": 200}, "observations": obs}).encode())
        return iem(url, headers, timeout, max_bytes)
    return transport


def _all_bytes(root):
    for path in root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            yield gzip.decompress(data) if path.suffix == ".gz" else data


def test_wu_daily_uses_the_page_token_route_and_never_stores_the_token(tmp_path):
    token = uuid.uuid4().hex  # generated in memory; no fixture holds an access value
    calls = []
    result = _run("lb1_labels", tmp_path, _wu_transport(calls, token), datetime(2026, 1, 3, 15, tzinfo=timezone.utc),
                  days=["2026-01-02"])
    assert result["outcome"] == "ok"
    api = [u for u in calls if urlparse(u).hostname == WU_API_HOST]
    assert len(api) == 12 and all(parse_qs(urlparse(u).query)["apiKey"] == [token] for u in api)
    assert all(parse_qs(urlparse(u).query)["startDate"] == ["20260102"] for u in api)
    rows = _rows(tmp_path, "lb1_labels", "2026-01-03")
    nyc = next(r["body"] for r in rows if r["key"] == "nyc|2026-01-02|max")
    wu = nyc["instruments"]["wu_daily"]
    assert (wu["status"], wu["max"], wu["history_id"]) == ("ok", 55, "KLGA:9:US") and wu["raw_ref"]
    assert "wu_daily_vs_metar_all" in nyc["agreement"]
    london = next(r["body"] for r in rows if r["key"] == "london|2026-01-02|max")
    assert "wu_daily" not in london["instruments"]
    stored = list(_all_bytes(tmp_path))
    assert stored and not any(token.encode() in blob for blob in stored)
    assert not any(b"const data" in blob for blob in stored)


def test_wu_fetch_failure_journals_a_failure_class_only(tmp_path):
    token = uuid.uuid4().hex
    calls = []
    result = _run("lb1_labels", tmp_path, _wu_transport(calls, token, page_status=403),
                  datetime(2026, 1, 3, 15, tzinfo=timezone.utc), days=["2026-01-02"])
    assert result["outcome"] == "ok" and not any(urlparse(u).hostname == WU_API_HOST for u in calls)
    gaps = [e for e in _events(tmp_path, "lb1_labels", "2026-01-03") if e.get("reason") == "wu_daily_fetch"]
    assert len(gaps) == 12 and {g["failure_class"] for g in gaps} == {"auth_failure"}
    assert all("url" not in g and "error" not in g for g in gaps)
    rows = _rows(tmp_path, "lb1_labels", "2026-01-03")
    nyc = next(r["body"] for r in rows if r["key"] == "nyc|2026-01-02|max")
    assert nyc["instruments"]["wu_daily"]["status"] == "fetch_failed"


def test_strict_refused_day_marks_wu_and_iem_6h_refused(tmp_path):
    calls = []
    result = _run("lb1_labels", tmp_path, _wu_transport(calls, uuid.uuid4().hex),
                  datetime(2026, 10, 21, 15, tzinfo=timezone.utc), days=["2026-10-20"])
    assert result["panel_rows"] == 102
    assert not any(urlparse(u).hostname in (lb1_strict.WU_PAGE_HOST, WU_API_HOST) for u in calls)
    rows = _rows(tmp_path, "lb1_labels", "2026-10-21")
    nyc = next(r["body"] for r in rows if r["key"] == "nyc|2026-10-20|max")
    assert nyc["instruments"]["wu_daily"]["status"] == "embargo_refused"
    assert nyc["instruments"]["iem_6h_composite"]["status"] == "embargo_refused"


def test_iem_6h_composite_uses_periods_inside_the_local_day():
    def line(when, max6, min6):
        return f"LGA,{when},5.0,KLGA RMK AO2 SLP160 1{max6} 2{min6}"
    text = "\n".join(["station,valid,tmpc,metar",
                      line("2026-01-02 05:51", "0050", "0011"),   # 00-06Z: starts before 05Z local midnight
                      line("2026-01-02 11:51", "0100", "0022"),   # 06-12Z
                      line("2026-01-02 17:51", "0156", "0078"),   # 12-18Z
                      line("2026-01-02 23:51", "0122", "0044"),   # 18-00Z
                      line("2026-01-03 05:51", "0300", "1011")])  # 00-06Z: ends after 05Z
    reports = lb1_labels.parse_iem_csv(text + "\n", lb1_labels.ROUTINE)
    nyc = next(s for s in STATIONS if s["location"] == "nyc")
    start, end = lb1_labels.local_day_bounds(date(2026, 1, 2), nyc["timezone"])
    member = lb1_strict.iem_6h_member(lb1_strict.six_hour_periods(reports), start, end, "F")
    assert (member["status"], member["covered_hours"], member["periods"], member["overlap_periods"]) == (
        "partial", 18, 3, 5)
    assert (member["max"], member["min"]) == (60, 36)            # 15.6 C, 2.2 C
    assert (member["max_overlap"], member["min_overlap"]) == (86, 30)  # 30.0 C, -1.1 C


def test_wu_session_allows_only_the_page_host_and_the_api_host_the_page_names():
    session = lb1_strict.FetcherSession(None, "apiKey", lambda text: ("https://" + WU_API_HOST, "v"))
    assert session.allowed_host(lb1_strict.WU_PAGE_HOST) and not session.allowed_host(WU_API_HOST)
    with pytest.raises(ValueError):
        session.get("https://elsewhere.invalid/x", params={"apiKey": "v"})
    session.api_host = WU_API_HOST
    assert session.allowed_host(WU_API_HOST) and not session.allowed_host("elsewhere.invalid")


# ------------------------------------------------------------------------------------- 1-minute ASOS, CLI/CF6
def _cli(day_text, final, hi, lo):
    valid = "" if final else "VALID TODAY AS OF 0400 PM LOCAL TIME.\n"
    when = "YESTERDAY" if final else "TODAY"
    return ("CLIMATE REPORT\nNATIONAL WEATHER SERVICE TEST\n\n"
            f"...THE TEST CLIMATE SUMMARY FOR {day_text}...\n{valid}\n"
            "WEATHER ITEM   OBSERVED TIME   RECORD YEAR NORMAL\n"
            f"TEMPERATURE (F)\n {when}\n  MAXIMUM         {hi}    433 PM  96    2010  82\n"
            f"  MINIMUM         {lo}   1159 PM  55    1967  69\n  AVERAGE         50\n\n"
            "PRECIPITATION (IN)\n  MAXIMUM         99\n")


def _cf6(month, year, rows):
    body = "\n".join(f"{d:2d}  {hi:>2}  {lo:>2}  50   1   0   9 0.00  0.0" for d, hi, lo in rows)
    return (f"PRELIMINARY LOCAL CLIMATOLOGICAL DATA (WS FORM: F-6)\n  STATION: TEST\n  MONTH:     {month}\n"
            f"  YEAR:      {year}\n====\n1   2   3   4   5  6A  6B    7    8\nDY MAX MIN AVG DEP HDD CDD  WTR  SNW\n"
            f"====\n\n{body}\n====\nSM   80   68\n")


def _zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in entries:
            archive.writestr(name, text)
    return buffer.getvalue()


def test_cli_and_cf6_parsers_pick_the_final_product_for_the_day():
    cli = [("CLIX_1.txt", _cli("JANUARY 1 2026", True, 40, 30)),       # the day before, final
           ("CLIX_2.txt", _cli("JANUARY 2 2026", False, 55, 31)),      # preliminary
           ("CLIX_3.txt", _cli("JANUARY 2 2026", True, "56R", 30)),    # final, record flag
           ("CLIX_4.txt", _cli("JANUARY 3 2026", False, 70, 60))]
    member = lb1_us.climate_member(lb1_us.CLI, cli, date(2026, 1, 2), "F", "ref")
    assert (member["status"], member["product"], member["final"], member["max"], member["min"]) == (
        "ok", "CLIX_3.txt", True, 56, 30)
    assert member["day_basis"] == "lst"
    only_preliminary = lb1_us.climate_member(lb1_us.CLI, cli[:2], date(2026, 1, 2), "F", "ref")
    assert (only_preliminary["final"], only_preliminary["max"]) == (False, 55)
    assert lb1_us.parse_cli(_cli("JANUARY 2 2026", True, "MM", 30))["max_f"] is None
    cf6 = [("CF6X_1.txt", _cf6("DECEMBER", 2025, [(1, 33, 20)])),
           ("CF6X_2.txt", _cf6("JANUARY", 2026, [(1, 41, 29), (2, 57, 31)]))]
    member = lb1_us.climate_member(lb1_us.CF6, cf6, date(2026, 1, 2), "F", "ref")
    assert (member["status"], member["product"], member["max"], member["min"]) == ("ok", "CF6X_2.txt", 57, 31)
    # The column-number line above the header is not a day row.
    assert lb1_us.parse_cf6(_cf6("JANUARY", 2026, [(2, 57, 31)]), date(2026, 1, 1)) is None
    assert lb1_us.climate_member(lb1_us.CF6, [], date(2026, 1, 2), "F", None)["status"] == "no_product"
    assert lb1_us.climate_member(lb1_us.CF6, cf6[:1], date(2026, 1, 2), "F", "r")["status"] == "no_day"


def test_one_minute_member_uses_the_local_day_and_reports_coverage():
    nyc = next(s for s in STATIONS if s["location"] == "nyc")
    start, end = lb1_labels.local_day_bounds(date(2026, 1, 2), nyc["timezone"])
    text = "station,station_name,valid(Etc/UTC),tmpf,dwpf\n" + "\n".join(
        [f"LGA,X,{(start - timedelta(minutes=1)):%Y-%m-%d %H:%M},90,1",          # before the local day
         f"LGA,X,{start:%Y-%m-%d %H:%M},40,1", f"LGA,X,{(start + timedelta(minutes=1)):%Y-%m-%d %H:%M},M,1",
         f"LGA,X,{(start + timedelta(hours=9)):%Y-%m-%d %H:%M},52,1",
         f"LGA,X,{(end - timedelta(minutes=1)):%Y-%m-%d %H:%M},31,1",
         f"LGA,X,{end:%Y-%m-%d %H:%M},10,1"]) + "\n"                             # the next local day
    member = lb1_us.one_minute_member(lb1_us.parse_one_minute(text), start, end, "F", "ref")
    assert (member["status"], member["max"], member["min"], member["minutes"], member["expected_minutes"]) == (
        "ok", 52, 31, 3, 1440)
    assert member["first_max_utc"] == "2026-01-02T14:00:00Z"
    query = parse_qs(urlparse(lb1_us.one_minute_url(lb1_us.IEM_1MIN_URL, "LGA", start, end)).query)
    assert query["vars"] == ["tmpf", "dwpf"]
    assert (query["hour1"], query["hour2"], query["minute2"]) == (["5"], ["4"], ["59"])


def _us_transport(calls):
    iem = _iem_transport(calls)

    def transport(url, headers, timeout, max_bytes):
        parts = urlparse(url)
        query = parse_qs(parts.query)
        if parts.path.endswith("/asos1min.py"):
            calls.append(url)
            start = datetime(int(query["year1"][0]), int(query["month1"][0]), int(query["day1"][0]),
                             int(query["hour1"][0]), int(query["minute1"][0]))
            lines = ["station,station_name,valid(Etc/UTC),tmpf,dwpf"]
            for minute in range(0, 1440, 10):
                temp = 52 if minute == 600 else 40
                lines.append(f"{query['station'][0]},X,{start + timedelta(minutes=minute):%Y-%m-%d %H:%M},{temp},30")
            return Response(url, 200, ("\n".join(lines) + "\n").encode())
        if parts.path.endswith("/afos/retrieve.py"):
            calls.append(url)
            pil = query["pil"][0]
            if pil.endswith("BKF"):
                return Response(url, 200, _zip([]))
            if pil.startswith("CLI"):
                return Response(url, 200, _zip([(pil + "_1.txt", _cli("JANUARY 2 2026", True, 52, 39))]))
            return Response(url, 200, _zip([(pil + "_1.txt", _cf6("JANUARY", 2026, [(2, 52, 39)]))]))
        return iem(url, headers, timeout, max_bytes)
    return transport


def test_lb1_us_members_use_one_public_request_per_station_day_each(tmp_path):
    calls = []
    result = _run("lb1_labels", tmp_path, _us_transport(calls), datetime(2026, 1, 3, 15, tzinfo=timezone.utc),
                  days=["2026-01-02"], config=CONFIG_US_ONLY)
    assert result["outcome"] == "ok"
    us = [s for s in STATIONS if s["country_code"] == "US"]
    one_min = [u for u in calls if urlparse(u).path.endswith("/asos1min.py")]
    afos = [u for u in calls if urlparse(u).path.endswith("/afos/retrieve.py")]
    assert len(one_min) == len(us) and len(afos) == 2 * len(us)
    assert {urlparse(u).hostname for u in calls} == {"mesonet.agron.iastate.edu"}
    assert {parse_qs(urlparse(u).query)["pil"][0] for u in afos} == (
        {"CLI" + s["station"][1:] for s in us} | {"CF6" + s["station"][1:] for s in us})
    assert all(parse_qs(urlparse(u).query)["sdate"] == ["2026-01-02T00:00Z"] for u in afos)
    assert all(parse_qs(urlparse(u).query)["edate"] == ["2026-01-03T23:59Z"] for u in afos)
    rows = _rows(tmp_path, "lb1_labels", "2026-01-03")
    nyc = next(r["body"] for r in rows if r["key"] == "nyc|2026-01-02|max")
    assert nyc["instruments"]["asos_1min"]["max"] == 52 and nyc["instruments"]["asos_1min"]["raw_ref"]
    assert nyc["instruments"]["nws_cli"]["max"] == 52 and nyc["instruments"]["nws_cf6"]["max"] == 52
    assert {"asos_1min_vs_metar_all", "nws_cli_vs_metar_all", "nws_cf6_vs_metar_all"} <= set(nyc["agreement"])
    nyc_min = next(r["body"] for r in rows if r["key"] == "nyc|2026-01-02|min")
    assert nyc_min["instruments"]["nws_cli"]["min"] == 39 and "max" not in nyc_min["instruments"]["nws_cli"]
    denver = next(r["body"] for r in rows
                  if r["channel"] == "label_panel" and r["body"]["station"] == "KBKF" and r["body"]["label_kind"] == "max")
    assert denver["instruments"]["nws_cli"]["status"] == "no_product"
    london = next(r["body"] for r in rows if r["key"] == "london|2026-01-02|max")
    assert not {"asos_1min", "nws_cli", "nws_cf6"} & set(london["instruments"])


def test_lb1_us_members_build_no_url_for_boundary_days_and_mark_refused_days(tmp_path):
    calls = []
    ctx = _task_ctx(tmp_path / "unit", datetime(2026, 12, 1, 1, tzinfo=timezone.utc),
                    lambda u, h, t, m: calls.append(u) or Response(u, 500))
    for day in ("2026-09-29", "2026-09-30", "2026-10-15", "2026-10-16"):
        assert lb1_us.one_minute(ctx, ctx.cfg, date.fromisoformat(day), STATIONS, lb1_labels.local_day_bounds) is None
        assert lb1_us.climate(ctx, ctx.cfg, date.fromisoformat(day), STATIONS) is None
    ctx.journal.close()
    assert calls == []
    result = _run("lb1_labels", tmp_path / "run", _us_transport(calls),
                  datetime(2026, 10, 21, 15, tzinfo=timezone.utc), days=["2026-10-20"], config=CONFIG_US_ONLY)
    assert result["panel_rows"] == 102
    assert not any(urlparse(u).path.endswith(("/asos1min.py", "/afos/retrieve.py")) for u in calls)
    rows = _rows(tmp_path / "run", "lb1_labels", "2026-10-21")
    nyc = next(r["body"] for r in rows if r["key"] == "nyc|2026-10-20|max")
    assert {nyc["instruments"][n]["status"] for n in ("asos_1min", "nws_cli", "nws_cf6")} == {"embargo_refused"}
