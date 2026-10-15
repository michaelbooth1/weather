"""LB-1 strict-guard US instruments: IEM 1-minute ASOS and the NWS CLI/CF6 climate products (shadow panel members).

Both sit behind the same STRICT fetch guard as :mod:`weather.evidence.tasks.lb1_strict` (``backfill``
mode over the target local day and one day either side), so a refused day builds no URL and its
members say ``status=embargo_refused``. Both are public IEM archives; no credential, token or paid
route is involved. US panel stations only (``country_code == "US"``).

- ``asos_1min``: one IEM ``asos1min.py`` request per station-day over the station's local day in UTC
  (``vars`` ``tmpf`` and ``dwpf``; the header form ``valid(Etc/UTC)`` was read 2026-10-15). ``max``/``min``
  are whole native degrees (half-up) of the 1-minute ``tmpf`` values; ``coverage_ratio`` is minutes with a
  temperature over the local day's minutes (1380/1440/1500 on DST days).
- ``nws_cli`` and ``nws_cf6``: the IEM AFOS archive (``afos/retrieve.py``, ``fmt=zip``, one product per
  entry, the request form verified 2026-09-21) for PIL ``CLI``/``CF6`` + the ICAO without its first
  letter, issued from D 00:00Z to D+1 23:59Z. CLI: the last product whose "CLIMATE SUMMARY FOR" date is
  D, preferring a final (``YESTERDAY``) over a preliminary (``VALID TODAY AS OF``) one; its TEMPERATURE
  MAXIMUM/MINIMUM. CF6: the last product whose MONTH/YEAR match D that has a row for D. Both report
  degrees F over the **local standard time** day (``day_basis=lst``), so on a DST day they cover
  01:00-01:00 local clock time, not the market's local day; the member says so rather than adjusting.
  No product in the window is ``status=no_product``.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from weather.evidence.tasks.lb1_strict import REFUSED, strict_allowed
from weather.units import f_to_native, round_half_up, to_float

IEM_1MIN_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py"
IEM_AFOS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py"
ONE_MIN, CLI, CF6 = "asos_1min", "nws_cli", "nws_cf6"
PRODUCTS = ((CLI, "CLI"), (CF6, "CF6"))
MONTHS = ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
          "NOVEMBER", "DECEMBER")
SUMMARY_RE = re.compile(r"CLIMATE SUMMARY FOR\s+([A-Z]+)\s+(\d{1,2})\s+(\d{4})")
VALUE_RE = re.compile(r"^\s*(MAXIMUM|MINIMUM)\s+(-?\d+|MM)R?\b")
CF6_ROW_RE = re.compile(r"^\s*(\d{1,2})\s+(-?\d+|M)\s+(-?\d+|M)\s")


def us_stations(stations) -> list[dict]:
    return [s for s in stations if s.get("country_code") == "US"]


def refused(name) -> dict:
    return {"instrument": name, **REFUSED}


# ------------------------------------------------------------------------------------- 1-minute ASOS
def one_minute_url(base, station, start_utc, end_utc) -> str:
    last = end_utc - timedelta(minutes=1)
    params = [("station", station)]
    for suffix, when in (("1", start_utc), ("2", last)):
        params += [(f"year{suffix}", when.year), (f"month{suffix}", when.month), (f"day{suffix}", when.day),
                   (f"hour{suffix}", when.hour), (f"minute{suffix}", when.minute)]
    params += [("tz", "Etc/UTC"), ("format", "onlycomma"), ("vars", "tmpf"), ("vars", "dwpf")]
    return base + "?" + urlencode(params)


def parse_one_minute(text) -> list[tuple[datetime, float]]:
    """``(valid_utc, tmpf)`` pairs; the ``valid(...)`` column is matched by prefix, missing values dropped."""
    reader = csv.reader(io.StringIO(text))
    header = next(reader, [])
    try:
        valid_at = next(i for i, name in enumerate(header) if name.startswith("valid"))
        temp_at = header.index("tmpf")
    except (StopIteration, ValueError):
        return []
    out = []
    for row in reader:
        if len(row) <= max(valid_at, temp_at):
            continue
        temp = to_float(row[temp_at])
        try:
            when = datetime.strptime(row[valid_at].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if temp is not None:
            out.append((when, temp))
    return out


def one_minute_member(pairs, start_utc, end_utc, unit, raw_ref) -> dict:
    expected = int((end_utc - start_utc).total_seconds() // 60)
    inside = {when: temp for when, temp in pairs if start_utc <= when < end_utc}
    member = {"instrument": ONE_MIN, "raw_ref": raw_ref, "minutes": len(inside), "expected_minutes": expected,
              "coverage_ratio": round(len(inside) / expected, 4) if expected else 0.0}
    if not inside:
        return {**member, "status": "no_rows", "max": None, "min": None}
    native = [f_to_native(t, unit) for t in inside.values()]
    hi = max(native)
    first = min(when for when, temp in inside.items() if f_to_native(temp, unit) == hi)
    return {**member, "status": "ok", "max": round_half_up(hi), "min": round_half_up(min(native)),
            "max_native": round(hi, 2), "min_native": round(min(native), 2), "first_max_utc": first.strftime(
                "%Y-%m-%dT%H:%M:%SZ")}


def one_minute(ctx, cfg, day, stations, bounds) -> dict | None:
    """``{location: member}`` for the US stations, or None when the strict guard refuses ``day``."""
    if not strict_allowed(ctx, day):
        return None
    base = cfg.get("asos_1min_url", IEM_1MIN_URL)
    out = {}
    for station in us_stations(stations):
        ctx.check_deadline()
        start, end = bounds(day, station["timezone"])
        response = ctx.fetch(one_minute_url(base, station["iem"], start, end))
        if response.status != 200 or not response.body.startswith(b"station,"):
            ctx.gap("asos_1min_reply", status=response.status, location=station["location"], day=day.isoformat())
            out[station["location"]] = {"instrument": ONE_MIN, "status": "fetch_failed", "max": None, "min": None}
        else:
            ref = ctx.journal.put_raw(response.body, channel=ctx.channel)
            out[station["location"]] = one_minute_member(parse_one_minute(response.body.decode("utf-8", "replace")),
                                                         start, end, station["unit"], ref)
        ctx.sleep(float(cfg.get("spacing_seconds", 1.1)))
    return out


# ------------------------------------------------------------------------------------- CLI / CF6
def afos_url(base, pil, day) -> str:
    params = {"pil": pil, "fmt": "zip", "limit": 20, "order": "asc", "sdate": f"{day.isoformat()}T00:00Z",
              "edate": f"{(day + timedelta(days=1)).isoformat()}T23:59Z"}
    return base + "?" + urlencode(params)


def afos_products(body) -> list[tuple[str, str]]:
    """``(entry name, text)`` per product, in archive order; an empty archive is ``[]``."""
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        return [(name, archive.read(name).decode("latin-1")) for name in archive.namelist()]


def _value(token):
    return None if token in ("M", "MM") else int(token)


def parse_cli(text) -> dict | None:
    """``{day, final, max_f, min_f}`` from one CLI product, or None when it has no summary date."""
    found = SUMMARY_RE.search(text)
    if not found or found.group(1) not in MONTHS:
        return None
    day = date(int(found.group(3)), MONTHS.index(found.group(1)) + 1, int(found.group(2)))
    values, in_temperature = {}, False
    for line in text.splitlines():
        if line.startswith("TEMPERATURE"):
            in_temperature = True
            continue
        if in_temperature and line.strip() and not line.startswith(" "):
            break
        matched = VALUE_RE.match(line) if in_temperature else None
        if matched and matched.group(1) not in values:
            values[matched.group(1)] = _value(matched.group(2))
    return {"day": day, "final": "VALID TODAY AS OF" not in text, "max_f": values.get("MAXIMUM"),
            "min_f": values.get("MINIMUM")}


def parse_cf6(text, day) -> dict | None:
    """``{max_f, min_f}`` for ``day`` from one CF6 product whose MONTH/YEAR match, else None."""
    month = re.search(r"MONTH:\s+([A-Z]+)", text)
    year = re.search(r"YEAR:\s+(\d{4})", text)
    if not month or not year or month.group(1) != MONTHS[day.month - 1] or int(year.group(1)) != day.year:
        return None
    stage = 0  # 0: before the "DY MAX MIN" header, 1: before its rule line, 2: in the day rows
    for line in text.splitlines():
        if stage == 0:
            stage = 1 if line.startswith("DY MAX MIN") else 0
        elif line.startswith("="):
            if stage == 2:
                break
            stage = 2
        elif stage == 2:
            matched = CF6_ROW_RE.match(line)
            if matched and int(matched.group(1)) == day.day:
                return {"max_f": _value(matched.group(2)), "min_f": _value(matched.group(3))}
    return None


def climate_member(name, products, day, unit, raw_ref) -> dict:
    base = {"instrument": name, "raw_ref": raw_ref, "day_basis": "lst", "products": len(products)}
    chosen = None
    for entry, text in products:
        if name == CLI:
            parsed = parse_cli(text)
            if parsed and parsed["day"] == day and (chosen is None or parsed["final"] or not chosen["final"]):
                chosen = {**parsed, "product": entry}
        else:
            parsed = parse_cf6(text, day)
            if parsed:
                chosen = {**parsed, "final": False, "product": entry}
    if chosen is None:
        return {**base, "status": "no_product" if not products else "no_day", "max": None, "min": None}
    out = {**base, "status": "ok", "product": chosen["product"], "final": chosen["final"],
           "max": None if chosen["max_f"] is None else round_half_up(f_to_native(chosen["max_f"], unit)),
           "min": None if chosen["min_f"] is None else round_half_up(f_to_native(chosen["min_f"], unit))}
    if name == CF6:
        out.pop("final")  # the CF6 is preliminary by form; its row is not a final flag
    return out


def climate(ctx, cfg, day, stations) -> dict | None:
    """``{location: {nws_cli: member, nws_cf6: member}}``, or None when the strict guard refuses ``day``."""
    if not strict_allowed(ctx, day):
        return None
    base = cfg.get("afos_url", IEM_AFOS_URL)
    out = {}
    for station in us_stations(stations):
        members = out.setdefault(station["location"], {})
        for name, prefix in PRODUCTS:
            ctx.check_deadline()
            response = ctx.fetch(afos_url(base, prefix + station["station"][1:], day))
            try:
                if response.status != 200:
                    raise zipfile.BadZipFile(f"HTTP {response.status}")
                products = afos_products(response.body)
            except zipfile.BadZipFile:
                ctx.gap("afos_reply", status=response.status, product=prefix, location=station["location"],
                        day=day.isoformat())
                members[name] = {"instrument": name, "status": "fetch_failed", "max": None, "min": None}
            else:
                ref = ctx.journal.put_raw(response.body, channel=ctx.channel) if products else None
                members[name] = climate_member(name, products, day, station["unit"], ref)
            ctx.sleep(float(cfg.get("spacing_seconds", 1.1)))
    return out
