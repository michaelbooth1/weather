"""LB-1 strict-guard instruments: WU daily and the IEM 6-hour composite (shadow panel members only).

Both sit behind the STRICT fetch guard (``backfill`` mode: every embargo window, OUTCOME and MG-1
reserved days included, is refused) over the target local day and one day either side, so no
request or read touches a refused day through a lookback. A refused day gets
``status=embargo_refused`` and no URL is built.

- ``wu_daily``: the WU public history for the market's settlement station through the existing
  OD15 route, :class:`weather.sources.wu_history.PublicWundergroundHistoryClient` (the same client
  the settlement restore uses: it reads the page's runtime access value from the public history
  page and sends it with the history request). Its session is :class:`FetcherSession`, which routes
  every GET through the task's fetcher (budget, deadline, telemetry) and keeps the access value in
  memory only: it is never journalled, logged or stored; errors pass through
  :func:`weather.sources.wu_redaction.sanitize_exception` and are journalled as a failure class
  only; a payload that contains the value is not stored. Covers the markets in
  :func:`weather.market.market_registry.all_specs` (the WU settlement-restore set).
- ``iem_6h_composite``: daily max/min composed from the 6-hour ``1snTTT``/``2snTTT`` remark groups of
  the routine IEM reports LB-1 already fetched (no extra request). ``max``/``min`` use the periods
  fully inside the local day (``covered_hours``; ``status=partial`` below 24); ``max_overlap`` and
  ``min_overlap`` use every period overlapping it.
"""
from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from weather.evidence.batch import TaskDeadline
from weather.evidence.fetch import RequestBudgetExceeded
from weather.units import c_to_native, round_half_up

WU_PAGE_HOST = "www.wunderground.com"
SYNOPTIC_HOURS = (0, 6, 12, 18)
PERIOD = timedelta(hours=6)


def strict_allowed(ctx, day) -> bool:
    """The strict guard over ``day`` and one day either side (lookbacks included)."""
    return ctx.guard_days([day - timedelta(days=1), day, day + timedelta(days=1)], mode="backfill")


# --------------------------------------------------------------------------------------------- WU daily
class FetcherResponse:
    """The slice of ``requests.Response`` the public WU client reads."""

    def __init__(self, response):
        self.status_code = int(response.status)
        self.content = response.body
        self.text = response.body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FetcherSession:
    """``requests.Session`` stand-in: GETs go through ``ctx.fetch``; the access value stays in memory."""

    def __init__(self, ctx, access_param, page_reader):
        self.ctx, self.access_param, self.page_reader = ctx, access_param, page_reader
        self._secrets: set[str] = set()
        self.api_host = None  # learned only from the public page's own runtime data
        self.requests = 0

    def allowed_host(self, host) -> bool:
        return host == WU_PAGE_HOST or (self.api_host is not None and host == self.api_host)

    def get(self, url, params=None, headers=None, timeout=None):
        if params:
            for key, value in params.items():
                if key == self.access_param and value:
                    self._secrets.add(str(value))
            url = url + ("&" if "?" in url else "?") + urlencode(list(params.items()))
        parts = urlsplit(url)
        if parts.scheme != "https" or not self.allowed_host(parts.hostname):
            raise ValueError("not an allowlisted WU host")
        self.requests += 1
        response = FetcherResponse(self.ctx.fetch(url, headers=headers))
        if parts.hostname == WU_PAGE_HOST and response.status_code == 200:
            try:
                api_root, _value = self.page_reader(response.text)
            except RuntimeError:
                pass
            else:
                self.api_host = urlsplit(api_root).hostname
        return response

    def carries_secret(self, raw: bytes) -> bool:
        return any(secret.encode() in raw for secret in self._secrets)

    def forget(self):
        self._secrets.clear()


def wu_specs(location_ids):
    from weather.market.market_registry import all_specs
    return [spec for spec in all_specs() if spec.id in set(location_ids)]


def wu_member(spec, day, payload, raw_ref) -> dict:
    from weather.sources.wu_history import normalize_observation, summarize_daily
    rows = [r for r in (normalize_observation(o, tz=spec.tz, unit=spec.display_unit)
                        for o in payload.get("observations") or [] if isinstance(o, dict)) if r]
    daily = next((d for d in summarize_daily(rows) if d["local_date"] == day.isoformat()), None)
    base = {"instrument": "wu_daily", "history_id": spec.wu_history_id, "unit": spec.display_unit,
            "raw_ref": raw_ref}
    if not daily or daily.get("max_temp") is None:
        return {**base, "status": "no_rows", "max": None, "min": None, "reports": 0}
    return {**base, "status": "ok", "max": round_half_up(daily["max_temp"]), "min": round_half_up(daily["min_temp"]),
            "max_native": daily["max_temp"], "min_native": daily["min_temp"], "reports": daily["row_count"],
            "has_non_hourly_rows": daily["has_non_hourly_rows"]}


def wu_daily(ctx, cfg, day, location_ids) -> dict | None:
    """``{location: wu_daily member}``, or None when the strict guard refuses the day (no URL built)."""
    if not strict_allowed(ctx, day):
        return None
    from weather.sources.wu_history import (
        PUBLIC_WU_ACCESS_PARAM, PublicWundergroundHistoryClient, failure_class_for_exception,
    )
    from weather.sources.wu_redaction import safe_attr, sanitize_exception
    out = {}
    for spec in wu_specs(location_ids):
        ctx.check_deadline()
        client = PublicWundergroundHistoryClient(history_id=spec.wu_history_id, station_icao=spec.icao,
                                                 units=spec.wu_units, sleep_seconds=0)
        session = client.session = FetcherSession(ctx, PUBLIC_WU_ACCESS_PARAM, client.public_access_from_page)
        try:
            payload = client.fetch_range(day, day, units=spec.wu_units)
        except (TaskDeadline, RequestBudgetExceeded):
            session.forget()
            raise
        except Exception as exc:  # noqa: BLE001 - recorded as a failure class only
            sanitize_exception(exc)
            status = safe_attr(safe_attr(exc, "response"), "status_code")
            failure = failure_class_for_exception(exc)
            session.forget()
            ctx.gap("wu_daily_fetch", location=spec.id, day=day.isoformat(), failure_class=failure,
                    status=status, error_type=type(exc).__name__)
            out[spec.id] = {"instrument": "wu_daily", "status": "fetch_failed", "failure_class": failure,
                            "max": None, "min": None}
            continue
        payload.pop("_wu_collector_provenance", None)  # carries a retrieval time; the row has first_seen
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ref = None
        if session.carries_secret(raw):
            ctx.warn("wu_payload_not_stored", location=spec.id, day=day.isoformat())
        else:
            ref = ctx.journal.put_raw(raw, channel=ctx.channel)
        session.forget()
        out[spec.id] = wu_member(spec, day, payload, ref)
        ctx.sleep(float(cfg.get("wu_spacing_seconds", 1.0)))
    return out


# --------------------------------------------------------------------------------------------- IEM 6 h
def six_hour_periods(reports) -> dict:
    """``{period_end_utc: (max6h_c, min6h_c)}`` from routine reports at the synoptic hours."""
    out = {}
    for r in sorted(reports, key=lambda r: r["valid_utc"]):
        if r.get("report_type") != 3 or (r.get("max6h_c") is None and r.get("min6h_c") is None):
            continue
        end = (r["valid_utc"] + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
        if end.hour in SYNOPTIC_HOURS:
            out[end] = (r.get("max6h_c"), r.get("min6h_c"))  # a later report (COR) replaces an earlier one
    return out


def _native(values, unit, pick):
    values = [c_to_native(v, unit) for v in values if v is not None]
    return round_half_up(pick(values)) if values else None


def iem_6h_member(periods, start, end, unit) -> dict:
    inside = {e: v for e, v in periods.items() if e - PERIOD >= start and e <= end}
    overlap = {e: v for e, v in periods.items() if e > start and e - PERIOD < end}
    covered = 6 * len(inside)
    return {"instrument": "iem_6h_composite",
            "status": "no_groups" if not overlap else ("ok" if covered >= 24 else "partial"),
            "max": _native([v[0] for v in inside.values()], unit, max),
            "min": _native([v[1] for v in inside.values()], unit, min),
            "max_overlap": _native([v[0] for v in overlap.values()], unit, max),
            "min_overlap": _native([v[1] for v in overlap.values()], unit, min),
            "covered_hours": covered, "periods": len(inside), "overlap_periods": len(overlap)}


REFUSED = {"status": "embargo_refused", "max": None, "min": None}
