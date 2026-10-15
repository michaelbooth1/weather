"""LB-1 multi-instrument label panel (shadow only): METAR-all, METAR-hourly and the OB-1 finality proxy.

One panel row per ``(location, local day, label_kind)`` for ``label_kind`` in ``max`` and ``min``,
written change-only to the ``label_panel`` partition of the ``lb1_labels`` journal. Nothing here
writes a settlement label, a ledger row or ``config/``.

Instruments built here (the plan's other LB-1 members are not built yet; see EVIDENCE_HOST.md).
``wu_daily`` and ``iem_6h_composite`` are added by :mod:`weather.evidence.tasks.lb1_strict`, and the US
``asos_1min``, ``nws_cli`` and ``nws_cf6`` members by :mod:`weather.evidence.tasks.lb1_us`, all behind the
strict guard:

- ``metar_all``: every routine and special report (IEM ``asos.py``, ``report_type`` 3 and 4 fetched
  separately so the classification never depends on a SPECI prefix) whose UTC time falls in the
  station's local day; whole native degrees by half-up rounding of the IEM ``tmpc`` value;
- ``metar_hourly``: routine reports carrying a numeric SLP group (the WRH "Hourly Data" rule, EF §10c,
  derived from the raw text; no minute window). Foreign WRH cities resolve on all times, so their
  row says ``venue_view=metar_all``;
- ``ob1_finality_proxy`` (``instrument=awc_proxy_of_wrh``, a panel member, not a label): the OB-1
  journal state when the first report of the next local day was first seen. On the re-read, every
  difference from ``metar_all`` is journalled as a ``cor`` event.

Embargo: every UTC day an IEM request touches passes the fetch guard in ``capture`` mode first (a
``full`` day is refused; outcome and MG-1 days are outcome-blind writes). The OB-1 journal is read
with ``capture_check``.

WRH disagreement read (owner Q4, DECISION_LOG 2026-10-15): for a US station-day where
``metar_all`` and ``metar_hourly`` differ at the degree, at most one ``wrh_read`` row per station-day,
after the strict fetch guard (``backfill`` mode: every window, including outcome and MG-1 reserved
days, is refused). The page renders its table from a third-party API through a page-embedded token,
which no decision covers yet (OD15 covers WU only), so the row records the wanted read with
``status=pending_route`` and nothing is fetched.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time as dtime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from weather.evidence.embargo import EmbargoRefused
from weather.evidence.envelope import ARCHIVE_PROXY, parse_utc, utc_text
from weather.evidence.families.common import chunks, item, settlement_stations
from weather.evidence.families.ob1_metar import parse_remarks
from weather.units import c_to_native, round_half_up

PARSER_VERSION = "lb1-labels-3"
LABEL_INSTRUMENT_VERSION = "lb1-panel-3"
DEFAULT_BASE_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
WRH_PAGE = "https://www.weather.gov/wrh/timeseries?site={station}"
PANEL, WRH = "label_panel", "wrh_read"
KINDS = ("max", "min")
ROUTINE, SPECIAL = 3, 4
OB1_FAMILY = "ob1_metar"
# Request span around a target local day: covers UTC+14 .. UTC-12 local days.
SPAN_BEFORE, SPAN_AFTER = timedelta(hours=14), timedelta(hours=12)


def iem_station(station: str, country_code) -> str:
    """IEM ids drop the leading K of contiguous-US ICAOs (the verified 2026-09-21 request form)."""
    station = str(station).upper()
    if country_code == "US" and len(station) == 4 and station.startswith("K"):
        return station[1:]
    return station


def panel_stations(locations, overrides=None) -> list[dict]:
    by_id = {row["id"]: row for row in locations}
    out = []
    for row in settlement_stations(locations, overrides=overrides):
        loc = by_id[row["location"]]
        settlement = loc.get("settlement") or {}
        out.append({**row, "country_code": loc.get("country_code"),
                    "unit": settlement.get("unit") or loc.get("market_unit") or "C",
                    "iem": iem_station(row["station"], loc.get("country_code")),
                    "source_type": settlement.get("source_type"),
                    "resolution_view": settlement.get("resolution_view")})
    return out


def local_day_bounds(day: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start = datetime.combine(day, dtime.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), dtime.min, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def default_days(now_utc: datetime, stations, *, settle_hours=1.0, reread_days=1) -> list[date]:
    """The latest local day complete (plus ``settle_hours``) at every station, then the re-read days."""
    day = now_utc.date()
    for _ in range(5):
        if all(local_day_bounds(day, s["timezone"])[1] + timedelta(hours=settle_hours) <= now_utc for s in stations):
            break
        day -= timedelta(days=1)
    return [day - timedelta(days=back) for back in range(int(reread_days) + 1)]


def parse_iem_csv(text: str, report_type: int) -> list[dict]:
    """Rows ``{iem, valid_utc, tmpc, raw, report_type, slp_hpa}``; missing temperatures are dropped."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        raw = str(row.get("metar") or "").strip()
        valid = str(row.get("valid") or "").strip()
        try:
            tmpc = float(row.get("tmpc"))
            when = datetime.strptime(valid, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        remarks = parse_remarks(raw)
        out.append({"iem": str(row.get("station") or "").upper(), "valid_utc": when, "tmpc": tmpc, "raw": raw,
                    "report_type": report_type, "slp_hpa": remarks["slp_hpa"], "max6h_c": remarks["max6h_c"],
                    "min6h_c": remarks["min6h_c"]})
    return out


def _extremes(values_c, unit) -> dict:
    native = [c_to_native(v, unit) for v in values_c]
    if not native:
        return {"max": None, "min": None, "max_native": None, "min_native": None, "reports": 0}
    hi, lo = max(native), min(native)
    return {"max": round_half_up(hi), "min": round_half_up(lo), "max_native": round(hi, 2),
            "min_native": round(lo, 2), "reports": len(native)}


def metar_instruments(reports, station, day) -> dict:
    start, end = local_day_bounds(day, station["timezone"])
    inside = [r for r in reports if start <= r["valid_utc"] < end]
    hourly = [r for r in inside if r["report_type"] == ROUTINE and r["slp_hpa"] is not None]
    return {"metar_all": _extremes([r["tmpc"] for r in inside], station["unit"]),
            "metar_hourly": _extremes([r["tmpc"] for r in hourly], station["unit"])}


def ob1_finality_proxy(ob1_rows, station, day) -> dict:
    """OB-1 state when the first report of the next local day was first seen (``awc_proxy_of_wrh``)."""
    start, end = local_day_bounds(day, station["timezone"])
    mine, next_seen = [], []
    for row in ob1_rows:
        body = row.get("body") or {}
        if str(body.get("station") or "").upper() != station["station"] or not body.get("obs_time_utc"):
            continue
        try:
            obs, seen = parse_utc(body["obs_time_utc"]), parse_utc(row["first_seen_utc"])
        except (KeyError, TypeError, ValueError):
            continue
        temp = body.get("t_group_c") if body.get("t_group_c") is not None else body.get("awc_temp_c")
        if start <= obs < end and temp is not None:
            mine.append((seen, float(temp)))
        elif obs >= end:
            next_seen.append(seen)
    if not next_seen:
        return {"instrument": "awc_proxy_of_wrh", "status": "no_next_day_report", **_extremes([], station["unit"])}
    cutoff = min(next_seen)
    values = [t for seen, t in mine if seen <= cutoff]
    return {"instrument": "awc_proxy_of_wrh", "status": "ok", "final_at_utc": utc_text(cutoff),
            **_extremes(values, station["unit"])}


def agreement(instruments, kind) -> dict:
    a, h = instruments["metar_all"][kind], instruments["metar_hourly"][kind]
    out = {"metar_all_vs_hourly": None if a is None or h is None else a == h}
    for name, key in (("ob1_finality_proxy", "finality_proxy_vs_metar_all"), ("wu_daily", "wu_daily_vs_metar_all"),
                      ("iem_6h_composite", "iem_6h_vs_metar_all"), ("asos_1min", "asos_1min_vs_metar_all"),
                      ("nws_cli", "nws_cli_vs_metar_all"), ("nws_cf6", "nws_cf6_vs_metar_all")):
        if name in instruments or name == "ob1_finality_proxy":
            other = (instruments.get(name) or {}).get(kind)
            out[key] = None if a is None or other is None else a == other
    return out


def wants_wrh(station, instruments) -> list[str]:
    if station["country_code"] != "US":
        return []
    return [k for k in KINDS if agreement(instruments, k)["metar_all_vs_hourly"] is False]


def _iem_url(base, iem_ids, report_type, start, end) -> str:
    params = [("station", s) for s in iem_ids] + [
        ("data", "tmpc"), ("data", "metar"), ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"),
        ("elev", "no"), ("missing", "M"), ("trace", "T"), ("report_type", str(report_type)),
        ("sts", utc_text(start)), ("ets", utc_text(end))]
    return base + "?" + urlencode(params)


def fetch_day(ctx, cfg, stations, day) -> tuple[list[dict], list[str]] | None:
    """All routine and special reports for ``day``'s request span, or None when the guard refuses it."""
    start = datetime.combine(day, dtime.min, tzinfo=timezone.utc) - SPAN_BEFORE
    end = datetime.combine(day + timedelta(days=1), dtime.min, tzinfo=timezone.utc) + SPAN_AFTER
    from weather.evidence.batch import utc_days
    if not ctx.guard_days(utc_days(start, end) + [day.isoformat()], mode="capture"):
        return None
    base = cfg.get("base_url", DEFAULT_BASE_URL)
    reports, refs = [], []
    for group in chunks(sorted({s["iem"] for s in stations}), cfg.get("chunk", 10)):
        for report_type in (ROUTINE, SPECIAL):
            response = ctx.fetch(_iem_url(base, group, report_type, start, end))
            if response.status != 200 or not response.body.startswith(b"station,valid"):
                ctx.gap("iem_reply", status=response.status, day=day.isoformat(), report_type=report_type,
                        stations=len(group))
                continue
            ref = ctx.journal.put_raw(response.body, channel=ctx.channel)
            if ref:
                refs.append(ref)
            reports += parse_iem_csv(response.body.decode("utf-8", "replace"), report_type)
            ctx.sleep(float(cfg.get("spacing_seconds", 1.1)))
    return reports, refs


def read_ob1(ctx, day) -> list[dict] | None:
    from weather.evidence.reader import read
    days = [(day + timedelta(days=d)).isoformat() for d in (-1, 0, 1, 2)]
    try:
        return read(OB1_FAMILY, utc_text(ctx.now()), "capture_check", days=days, root=ctx.journal.root).rows
    except EmbargoRefused:
        return None


def panel_items(stations, reports, ob1_rows, day, *, read_kind, raw_refs, wu=None, strict=False,
                us=None) -> tuple[list[dict], list[tuple]]:
    """``wu`` is ``{location: member}`` (None: strict guard refused); ``strict`` adds the IEM 6 h composite.

    ``us`` is ``(one_minute, climate)`` from :mod:`weather.evidence.tasks.lb1_us`, each None when the strict
    guard refused the day and ``{}`` when disabled; ``us=None`` marks both refused for US stations.
    """
    from weather.evidence.tasks import lb1_strict, lb1_us
    one_min, climate = us if us is not None else (None, None)
    wu_ids = {spec.id for spec in lb1_strict.wu_specs([s["location"] for s in stations])}
    by_iem: dict[str, list] = {}
    for r in reports:
        by_iem.setdefault(r["iem"], []).append(r)
    items, wanted = [], []
    for station in stations:
        instruments = metar_instruments(by_iem.get(station["iem"], []), station, day)
        instruments["ob1_finality_proxy"] = (ob1_finality_proxy(ob1_rows, station, day) if ob1_rows is not None
                                             else {"instrument": "awc_proxy_of_wrh", "status": "embargo_refused"})
        start, end = local_day_bounds(day, station["timezone"])
        if strict:
            instruments["iem_6h_composite"] = lb1_strict.iem_6h_member(
                lb1_strict.six_hour_periods(by_iem.get(station["iem"], [])), start, end, station["unit"])
        else:
            instruments["iem_6h_composite"] = {"instrument": "iem_6h_composite", **lb1_strict.REFUSED}
        if wu is None and station["location"] in wu_ids:
            instruments["wu_daily"] = {"instrument": "wu_daily", **lb1_strict.REFUSED}
        elif wu and station["location"] in wu:
            instruments["wu_daily"] = wu[station["location"]]
        if station["country_code"] == "US":
            if one_min is None:
                instruments[lb1_us.ONE_MIN] = lb1_us.refused(lb1_us.ONE_MIN)
            elif station["location"] in one_min:
                instruments[lb1_us.ONE_MIN] = one_min[station["location"]]
            for name, _prefix in lb1_us.PRODUCTS:
                if climate is None:
                    instruments[name] = lb1_us.refused(name)
                elif name in climate.get(station["location"], {}):
                    instruments[name] = climate[station["location"]][name]
        disagree = wants_wrh(station, instruments)
        if disagree:
            wanted.append((station, disagree, instruments))
        for kind in KINDS:
            body = {"location": station["location"], "station": station["station"], "iem_station": station["iem"],
                    "day": day.isoformat(), "label_kind": kind, "timezone": station["timezone"],
                    "unit": station["unit"], "local_day_start_utc": utc_text(start), "local_day_end_utc": utc_text(end),
                    "declared_source_type": station["source_type"], "resolution_view": station["resolution_view"],
                    "venue_view": "metar_hourly" if station["country_code"] == "US" else "metar_all",
                    "instruments": {name: {k: v for k, v in member.items() if k not in KINDS or k == kind}
                                    for name, member in instruments.items()},
                    "agreement": agreement(instruments, kind), "wrh_wanted": kind in disagree,
                    "label_instrument_version": LABEL_INSTRUMENT_VERSION, "read": read_kind, "raw_refs": raw_refs}
            items.append(item(f"{station['location']}|{day.isoformat()}|{kind}", body, parser_version=PARSER_VERSION,
                              basis=ARCHIVE_PROXY, event_date=day.isoformat(), raw_ref=raw_refs[0] if raw_refs else None,
                              partition=PANEL))
    return items, wanted


def record_wrh_wanted(ctx, wanted, day) -> int:
    rows = []
    for station, kinds, instruments in wanted:
        key = f"{station['station']}|{day.isoformat()}"
        if ctx.journal.seen(WRH, key):
            continue  # at most one read per station-day
        try:
            ctx.guard(day.isoformat(), mode="backfill")  # strict: reserved and embargo days excluded
        except EmbargoRefused:
            continue
        rows.append(item(key, {"station": station["station"], "location": station["location"], "day": day.isoformat(),
                               "kinds": kinds, "metar_all": {k: instruments["metar_all"][k] for k in KINDS},
                               "metar_hourly": {k: instruments["metar_hourly"][k] for k in KINDS},
                               "page": WRH_PAGE.format(station=station["station"].lower()),
                               "status": "pending_route"},
                         parser_version=PARSER_VERSION, basis=ARCHIVE_PROXY, event_date=day.isoformat()))
    if rows:
        ctx.record(rows, channel=WRH, meta={"day": day.isoformat(), "wanted": len(rows)})
    return len(rows)


def record_cor(ctx, items, day):
    for row in items:
        body = row["body"]
        kind, proxy = body["label_kind"], body["instruments"]["ob1_finality_proxy"]
        if proxy.get("status") == "ok" and body["agreement"]["finality_proxy_vs_metar_all"] is False:
            ctx.journal.event("cor", {"reason": "finality_proxy_differs_from_iem", "location": body["location"],
                                      "day": day.isoformat(), "label_kind": kind, "proxy": proxy.get(kind),
                                      "metar_all": body["instruments"]["metar_all"].get(kind)}, channel=PANEL)


def run(ctx, days=None) -> dict:
    from weather.evidence.tasks import lb1_strict, lb1_us
    cfg = ctx.cfg
    stations = panel_stations(ctx.locations, cfg.get("station_overrides"))
    targets = days or default_days(ctx.now(), stations, settle_hours=float(cfg.get("settle_hours", 1)),
                                   reread_days=int(cfg.get("reread_days", 1)))
    first = max(targets)
    summary = {"days": [], "refused_days": [], "panel_rows": 0, "wrh_wanted": 0}
    for day in sorted(targets, reverse=True):
        ctx.check_deadline()
        fetched = fetch_day(ctx, cfg, stations, day)
        if fetched is None:
            summary["refused_days"].append(day.isoformat())
            continue
        reports, refs = fetched
        read_kind = "first" if day == first and not days else ("reread" if not days else "backfill")
        strict = lb1_strict.strict_allowed(ctx, day)
        if not strict:
            wu = None
        elif cfg.get("wu_daily", True):
            wu = lb1_strict.wu_daily(ctx, cfg, day, [s["location"] for s in stations])
        else:
            wu = {}
        one_min = (lb1_us.one_minute(ctx, cfg, day, stations, local_day_bounds) if strict and cfg.get("asos_1min", True)
                   else ({} if strict else None))
        climate = (lb1_us.climate(ctx, cfg, day, stations) if strict and cfg.get("cli_cf6", True)
                   else ({} if strict else None))
        items, wanted = panel_items(stations, reports, read_ob1(ctx, day), day, read_kind=read_kind, raw_refs=refs,
                                    wu=wu, strict=strict and bool(cfg.get("iem_6h", True)), us=(one_min, climate))
        result = ctx.record(items, channel=PANEL, meta={"day": day.isoformat(), "read": read_kind,
                                                        "reports": len(reports), "stations": len(stations)})
        if read_kind == "reread":
            record_cor(ctx, items, day)
        summary["days"].append(day.isoformat())
        summary["panel_rows"] += result["changed"]
        summary["wrh_wanted"] += record_wrh_wanted(ctx, wanted, day)
    return summary
