"""Polite, serial collector for an immutable PIT forecast training-corpus plan.

``weather.sources.forecast_training_corpus`` deliberately has no HTTP client.
This module is the separately reviewed collector its contract names: it reads a
verified plan, fetches each planned request from the free Open-Meteo Previous
Runs endpoint (no API key, no credentials, no environment variables), and hands
the raw bytes to ``forecast_training_corpus.stage_response``.  It never writes
anything itself; every byte on disk goes through ``stage_response`` under the
caller-supplied staging root.  Resume is the existing ``resume-status``
contract: a hash-verified complete unit is skipped without a network call.

Politeness: requests are strictly serial, separated by a configurable minimum
interval, retried with exponential backoff on transport errors and 5xx, and a
429 honours ``Retry-After``.  The run stops at the first unit it cannot stage.

Issue evidence: the Previous Runs API does not expose a run id.  For a lead of
``N`` days every hourly value on a local target date comes from a run initialised
at least ``N * 24`` hours before that hour.  The collector therefore records an
upper bound: the latest 6-hourly cycle at or before (local 23:00 on the target
date minus ``N`` days), plus a conservative publication latency.  Staging and
materialization then enforce that bound against every feature cutoff.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time as time_module
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.sources.forecast_training_corpus import (
    ACTIVE_FORECAST_ARCHIVE_ROOT,
    ISSUE_EVIDENCE_KIND,
    PREVIOUS_RUNS_ENDPOINT,
    PROTECTED_REPOSITORY_ROOTS,
    StagingValidationError,
    _path_overlaps,
    inspect_staged_unit,
    load_plan,
    resume_ledger,
    stage_response,
)


DEFAULT_MIN_INTERVAL_SECONDS = 10.0
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BACKOFF_BASE_SECONDS = 30.0
DEFAULT_BACKOFF_CAP_SECONDS = 600.0
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_AVAILABILITY_LATENCY_HOURS = 6
MODEL_CYCLE_HOURS = 6
USER_AGENT = "weather-pit-forecast-corpus-collector/1 (serial; free tier)"
ISSUE_TIME_BASIS = "previous_runs_fixed_lead_latest_cycle_upper_bound"
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class CollectorRefused(RuntimeError):
    """The collector refused to start or to continue."""


def assert_collector_staging_root(staging_root, active_archive_roots=None):
    """Refuse any staging root that is, contains, or sits inside a forecast archive.

    The default protected roots are this checkout's ``data/forecast_history``.
    Any path with a ``forecast_history`` component is refused as well, so a
    different checkout's active archive is not reachable either.
    """
    path = Path(staging_root)
    if not str(staging_root).strip():
        raise CollectorRefused("a staging root is required")
    roots = list(active_archive_roots or [ACTIVE_FORECAST_ARCHIVE_ROOT])
    for root in roots:
        if _path_overlaps(path, root):
            raise CollectorRefused(f"staging root overlaps the active forecast archive: {root}")
    for root in PROTECTED_REPOSITORY_ROOTS:
        if _path_overlaps(path, root):
            raise CollectorRefused(f"staging root overlaps a tracked repository root: {root}")
    resolved = path.resolve()
    if any(part.lower() == "forecast_history" for part in resolved.parts):
        raise CollectorRefused(
            f"staging root must never be under a forecast_history directory: {resolved}"
        )
    return path


def issue_evidence_for(request, *, latency_hours=DEFAULT_AVAILABILITY_LATENCY_HOURS):
    """Conservative per-date issue evidence for a fixed-lead Previous Runs unit."""
    zone = ZoneInfo(request["source_timezone"])
    lead_days = int(request["lead_days"])
    rows = []
    for target_date_text in request["expected_local_dates"]:
        target_day = date.fromisoformat(target_date_text)
        last_valid_local = datetime.combine(target_day, time(23, 0), tzinfo=zone)
        bound = last_valid_local.astimezone(timezone.utc) - timedelta(days=lead_days)
        issue = bound.replace(
            hour=bound.hour - bound.hour % MODEL_CYCLE_HOURS,
            minute=0,
            second=0,
            microsecond=0,
        )
        available = issue + timedelta(hours=int(latency_hours))
        rows.append(
            {
                "target_date": target_date_text,
                "issue_evidence_kind": ISSUE_EVIDENCE_KIND,
                "issue_time_utc": issue.isoformat(),
                "available_at_utc": available.isoformat(),
                "run_id_exposed": False,
                "run_id": "",
                "issue_time_basis": ISSUE_TIME_BASIS,
                "availability_latency_hours": int(latency_hours),
            }
        )
    return rows


def request_url(request):
    if request.get("endpoint") != PREVIOUS_RUNS_ENDPOINT:
        raise CollectorRefused("request endpoint is not the free Previous Runs endpoint")
    params = request["params"]
    if any(key.lower() in {"apikey", "api_key", "key", "token"} for key in params):
        raise CollectorRefused("credential-bearing parameters are never sent")
    return f"{PREVIOUS_RUNS_ENDPOINT}?{urllib.parse.urlencode(sorted(params.items()))}"


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the 3xx is returned as a non-retryable status."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def urllib_get(url, timeout):
    """Default transport: one anonymous GET, no redirects. Returns (status, headers, body)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with _OPENER.open(req, timeout=timeout) as response:
            return int(response.status), dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), dict((exc.headers or {}).items()), exc.read() or b""


def retry_after_seconds(headers, now=None):
    value = None
    for key, raw in (headers or {}).items():
        if str(key).lower() == "retry-after":
            value = str(raw).strip()
            break
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0.0, (when - now).total_seconds())


def fetch_with_retries(
    url,
    *,
    http_get=urllib_get,
    sleep=time_module.sleep,
    max_attempts=DEFAULT_MAX_ATTEMPTS,
    backoff_base_seconds=DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_cap_seconds=DEFAULT_BACKOFF_CAP_SECONDS,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    log=None,
):
    """GET with exponential backoff; 429 waits at least its Retry-After.

    A Retry-After longer than ``backoff_cap_seconds`` is not slept: the unit is
    refused instead, so a far-future hint can never park the run for hours.
    """
    if int(max_attempts) < 1:
        raise CollectorRefused("max attempts must be at least 1")
    last_error = None
    status = None
    for attempt in range(1, int(max_attempts) + 1):
        try:
            status, headers, body = http_get(url, timeout_seconds)
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            TimeoutError,
        ) as exc:
            status, headers, body = None, {}, b""
            last_error = f"{type(exc).__name__}: {exc}"
        if status is not None and status not in RETRYABLE_STATUSES:
            return status, headers, body, attempt
        if status is not None:
            last_error = f"http_status_{status}"
        if attempt >= int(max_attempts):
            break
        delay = min(
            float(backoff_cap_seconds),
            float(backoff_base_seconds) * (2 ** (attempt - 1)),
        )
        if status == 429:
            hinted = retry_after_seconds(headers)
            if hinted is not None and hinted > float(backoff_cap_seconds):
                raise CollectorRefused(
                    f"Retry-After of {hinted:.0f}s exceeds the {float(backoff_cap_seconds):.0f}s "
                    "backoff cap; stopping instead of waiting"
                )
            if hinted is not None:
                delay = max(delay, hinted)
        if log:
            log(f"retry {attempt}/{max_attempts} after {last_error}; sleeping {delay:.0f}s")
        sleep(delay)
    if status is not None:
        return status, headers, body, int(max_attempts)
    raise CollectorRefused(f"transport failed after {max_attempts} attempts: {last_error}")


def collect(
    plan_path,
    staging_root,
    *,
    http_get=None,
    sleep=time_module.sleep,
    clock=time_module.monotonic,
    min_interval_seconds=DEFAULT_MIN_INTERVAL_SECONDS,
    max_attempts=DEFAULT_MAX_ATTEMPTS,
    backoff_base_seconds=DEFAULT_BACKOFF_BASE_SECONDS,
    backoff_cap_seconds=DEFAULT_BACKOFF_CAP_SECONDS,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    latency_hours=DEFAULT_AVAILABILITY_LATENCY_HOURS,
    max_requests=None,
    active_archive_roots=None,
    log=None,
):
    """Fetch every incomplete planned unit serially and stage it."""
    assert_collector_staging_root(staging_root, active_archive_roots=active_archive_roots)
    if float(min_interval_seconds) < 1.0:
        raise CollectorRefused("min interval below 1 second is not polite")
    if int(max_attempts) < 1:
        raise CollectorRefused("max attempts must be at least 1")
    http_get = http_get or urllib_get
    plan = load_plan(plan_path)
    fetched = []
    skipped = []
    last_request_at = None
    for request in plan["requests"]:
        state = inspect_staged_unit(plan, staging_root, request["request_hash"])
        if state["complete"]:
            skipped.append(request["request_hash"])
            continue
        if max_requests is not None and len(fetched) >= int(max_requests):
            break
        if last_request_at is not None:
            wait = float(min_interval_seconds) - (clock() - last_request_at)
            if wait > 0:
                sleep(wait)
        url = request_url(request)
        if log:
            log(f"fetch {request['market_id']} {request['year']} {request['request_hash'][:12]}")
        last_request_at = clock()
        status, headers, body, attempts = fetch_with_retries(
            url,
            http_get=http_get,
            sleep=sleep,
            max_attempts=max_attempts,
            backoff_base_seconds=backoff_base_seconds,
            backoff_cap_seconds=backoff_cap_seconds,
            timeout_seconds=timeout_seconds,
            log=log,
        )
        last_request_at = clock()
        receipt = stage_response(
            plan_path,
            staging_root,
            request["request_hash"],
            body,
            http_status=status,
            http_headers=headers,
            retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
            issue_evidence=issue_evidence_for(request, latency_hours=latency_hours),
        )
        fetched.append(
            {
                "request_hash": request["request_hash"],
                "market_id": request["market_id"],
                "year": request["year"],
                "attempts": attempts,
                "row_count": receipt["row_count"],
                "byte_count": receipt["byte_count"],
            }
        )
    ledger = resume_ledger(plan_path, staging_root)
    return {
        "plan_sha256": plan["plan_sha256"],
        "fetched": fetched,
        "skipped_complete": len(skipped),
        "complete_units": ledger["complete_units"],
        "required_units": ledger["required_units"],
        "all_complete": ledger["all_complete"],
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Serially fetch a PIT forecast corpus plan from the free Open-Meteo "
            "Previous Runs API and stage it (no API key; resumable)."
        )
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument(
        "--staging-root",
        required=True,
        help="Scratch staging root. Any forecast_history path is refused.",
    )
    parser.add_argument("--min-interval-seconds", type=float, default=DEFAULT_MIN_INTERVAL_SECONDS)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--backoff-base-seconds", type=float, default=DEFAULT_BACKOFF_BASE_SECONDS)
    parser.add_argument("--backoff-cap-seconds", type=float, default=DEFAULT_BACKOFF_CAP_SECONDS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--availability-latency-hours",
        type=int,
        default=DEFAULT_AVAILABILITY_LATENCY_HOURS,
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="Stop after this many network fetches (for a bounded trial).",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    def _log(message):
        print(message, file=sys.stderr, flush=True)

    try:
        result = collect(
            args.plan,
            args.staging_root,
            min_interval_seconds=args.min_interval_seconds,
            max_attempts=args.max_attempts,
            backoff_base_seconds=args.backoff_base_seconds,
            backoff_cap_seconds=args.backoff_cap_seconds,
            timeout_seconds=args.timeout_seconds,
            latency_hours=args.availability_latency_hours,
            max_requests=args.max_requests,
            log=_log,
        )
    except (CollectorRefused, StagingValidationError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
