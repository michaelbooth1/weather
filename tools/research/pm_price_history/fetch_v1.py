"""Step 2: fetch and raw-save International Polymarket closed-event price history (Yes tokens).

History-tier comparator data: selection evidence only, never an edge claim. Public endpoints
only (Gamma series/events, CLOB ``/prices-history``), unauthenticated GETs, wire rate capped at
4 MiB/s with request pacing and 429/5xx backoff. International Polymarket only.

Guards (``guards.py``) refuse in code before any price request for an event: event dates after
2026-09-29, the sealed panels 2026-05-27..07-30, the MG-1 window (open-ended from 2026-10-15) and
unreadable dates. A guard refusal aborts the run; it is never caught to continue.

Storage is immutable: every run writes a new ``<root>/<run_id>/`` directory; raw responses are
written exactly as received (decoded JSON bytes, gzip-compressed) with exclusive create, never
overwritten; the run ends with ``SHA256SUMS`` over every file and ``manifest.json``, and all files
are set read-only. Stops cleanly (manifest + sums still written) if free space on the output
volume falls below ``--min-free-gib`` (default 8) or process RSS exceeds ``--max-rss-mib``
(default 1024).

This file prints no price, outcome or resolution. Run from the repository root:
    python -m tools.research.pm_price_history.fetch_v1 --root C:\\t\\l52\\history --fidelity 1
"""

from __future__ import annotations

import argparse
import ctypes
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from tools.research.pm_price_history import guards
from tools.research.pm_price_history import inventory as inv

SCHEMA = "pm_price_history_step2_raw_v1"
DEFAULT_MIN_FREE_GIB = 8.0
DEFAULT_MAX_RSS_MIB = 1024.0
RESOURCE_CHECK_EVERY = 100  # requests
MAX_429 = 20  # total 429 responses before the run stops
MAX_TOKEN_ERRORS = 100  # total token fetch errors before the run stops

# Like inventory.SLUG_DATE_RE, plus an optional 3-digit re-creation suffix ("-on-may-22-799").
# A 3-digit group is never a year. Suffixed slugs are admitted only when endDate's date agrees exactly.
SLUG_DATE_V1_RE = re.compile(r"-on-([a-z]+)-(\d{1,2})(?:-(\d{4}|\d{2}))?(?:-(\d{3}))?$")


# --------------------------------------------------------------------------- dates

def _end_date(event) -> date | None:
    text = str(event.get("endDate") or "")
    try:
        return date.fromisoformat(text[:10]) if len(text) >= 10 else None
    except ValueError:
        return None


def event_target_date_v1(event) -> tuple[date | None, str]:
    """``inventory.event_target_date`` plus suffixed slugs whose endDate date agrees exactly."""
    target, how = inv.event_target_date(event)
    if target is not None or how != "slug_unparsed" or event.get("eventDate"):
        return target, how
    match = SLUG_DATE_V1_RE.search(str(event.get("slug") or "").lower())
    end_date = _end_date(event)
    if not match or not match.group(4) or end_date is None:
        return None, how
    month = inv.MONTHS.get(match.group(1))
    year_text = match.group(3)
    year = (int(year_text) + (2000 if len(year_text) == 2 else 0)) if year_text else end_date.year
    try:
        from_slug = date(year, month, int(match.group(2))) if month else None
    except ValueError:
        from_slug = None
    if from_slug is not None and from_slug == end_date:
        return from_slug, "suffixed_slug_eq_endDate"
    return None, "suffixed_slug_endDate_mismatch"


# --------------------------------------------------------------------------- HTTP

class RawClient(inv.PublicClient):
    """``PublicClient`` that also returns the decoded response bytes exactly as received."""

    def get_raw(self, url, params=None) -> bytes:
        full = url + ("?" + urlencode(params) if params else "")
        guards.require_public_endpoint(full, self.session.headers)
        for attempt in range(self.max_attempts):
            self.limiter.wait()
            self.stats.requests += 1
            try:
                resp = self.session.get(full, timeout=self.timeout, stream=True)
                wire = resp.raw.read(decode_content=False) if resp.raw is not None else resp.content
            except Exception:  # noqa: BLE001 - connection error: back off and retry
                self.stats.retries += 1
                self.sleep(min(60, 2 ** attempt))
                continue
            self.limiter.record(len(wire))
            self.stats.wire_bytes += len(wire)
            status = resp.status_code
            if status == 429 or status >= 500:
                self.stats.retries += 1
                self.stats.status_429 += int(status == 429)
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1)
                self.sleep(min(120.0, delay))
                continue
            if status != 200:
                raise RuntimeError(f"HTTP {status} for {url}")
            body = inv._decode(wire, resp.headers.get("Content-Encoding", ""))
            self.stats.decoded_bytes += len(body)
            return body
        raise RuntimeError(f"gave up after {self.max_attempts} attempts: {url}")

    def get_json(self, url, params=None):
        return json.loads(self.get_raw(url, params))


# --------------------------------------------------------------------------- discovery

def strip_event_v1(event) -> dict:
    """Identity, dates and per-band Yes tokens with band labels. Prices and resolutions are dropped."""
    bands = []
    for market in event.get("markets") or []:
        token = inv._yes_token(market)
        if token:
            bands.append({"yes_token": token, "condition_id": market.get("conditionId"),
                          "band_label": market.get("groupItemTitle"), "question": market.get("question")})
    base = inv.strip_event(event)
    return {"slug": base["slug"], "end_date_utc": base["end_date_utc"], "start_utc": base["start_utc"],
            "bands": bands}


@dataclass
class DiscoveryV1:
    market: inv.Market
    series_id: str | None = None
    admitted: list = field(default_factory=list)
    refused: dict = field(default_factory=dict)
    inference: dict = field(default_factory=dict)
    non_highest: int = 0


def discover_v1(client, market: inv.Market) -> DiscoveryV1:
    out = DiscoveryV1(market)
    series = client.get_json(f"{inv.GAMMA}/series", {"slug": market.series_slug})
    if not series:
        return out
    out.series_id = str(series[0]["id"])
    seen = set()
    for end_min, end_max in inv.DISCOVERY_WINDOWS:
        offset = 0
        while True:
            params = {"series_id": out.series_id, "closed": "true", "limit": inv.PAGE_LIMIT, "offset": offset,
                      "order": "endDate", "ascending": "true"}
            if end_min:
                params["end_date_min"] = end_min
            if end_max:
                params["end_date_max"] = end_max
            page = client.get_json(f"{inv.GAMMA}/events", params)
            for raw in page:
                slug = raw.get("slug")
                if slug in seen:
                    continue
                seen.add(slug)
                if "highest-temperature" not in str(slug):
                    out.non_highest += 1
                    continue
                target, how = event_target_date_v1(raw)
                out.inference[how] = out.inference.get(how, 0) + 1
                reason = guards.refusal_reason(target)
                if reason is not None:
                    out.refused[reason] = out.refused.get(reason, 0) + 1
                    continue
                kept = strip_event_v1(raw)
                kept["event_date"] = target.isoformat()
                kept["date_inference"] = how
                out.admitted.append(kept)
            n = len(page)
            del page
            if n < inv.PAGE_LIMIT:
                break
            offset += inv.PAGE_LIMIT
    return out


# --------------------------------------------------------------------------- resources

def rss_bytes() -> int | None:
    """Current process working set (Windows); None where unavailable."""
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    try:
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
    except (AttributeError, OSError):
        return None
    return int(counters.WorkingSetSize)


class ResourceStop(RuntimeError):
    """Free space or RSS crossed its floor/ceiling; the run stops cleanly."""


@dataclass
class ResourceGuard:
    root: Path
    min_free_gib: float = DEFAULT_MIN_FREE_GIB
    max_rss_mib: float = DEFAULT_MAX_RSS_MIB
    free_bytes = staticmethod(lambda p: shutil.disk_usage(p).free)
    rss = staticmethod(rss_bytes)

    def check(self) -> dict:
        free = self.free_bytes(self.root)
        rss = self.rss()
        if free < self.min_free_gib * 1024 ** 3:
            raise ResourceStop(f"free space {free / 1024 ** 3:.2f} GiB below floor {self.min_free_gib} GiB")
        if rss is not None and rss > self.max_rss_mib * 1024 ** 2:
            raise ResourceStop(f"RSS {rss / 1024 ** 2:.0f} MiB above ceiling {self.max_rss_mib} MiB")
        return {"free_bytes": free, "rss_bytes": rss}


# --------------------------------------------------------------------------- immutable store

class ImmutableStore:
    """Exclusive-create writes under one run directory; nothing is ever overwritten."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.files: list[Path] = []

    def write(self, rel: str, data: bytes) -> Path:
        path = self.run_dir / rel
        if self.run_dir.resolve() not in path.resolve().parents:
            raise guards.GuardRefusal(f"path escapes run dir: {rel}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as handle:  # FileExistsError on any overwrite attempt
            handle.write(data)
        self.files.append(path)
        return path

    def append_jsonl(self, rel: str, row: dict) -> None:
        path = self.run_dir / rel
        if path not in self.files:
            path.parent.mkdir(parents=True, exist_ok=True)
            open(path, "xb").close()
            self.files.append(path)
        with open(path, "ab") as handle:
            handle.write((json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))

    def seal(self) -> Path:
        """Write SHA256SUMS over every file (sorted relative paths) and set all files read-only."""
        lines = []
        for path in sorted(self.files, key=lambda p: p.relative_to(self.run_dir).as_posix()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(self.run_dir).as_posix()}")
        sums = self.write("SHA256SUMS", ("\n".join(lines) + "\n").encode("ascii"))
        for path in self.files:
            os.chmod(path, stat.S_IREAD)
        return sums


def raw_rel_path(market_id: str, event_date: str, slug: str, token: str, fidelity: int) -> str:
    safe_slug = re.sub(r"[^a-z0-9-]", "_", str(slug).lower())[:120]
    if not re.fullmatch(r"\d{1,100}", str(token)):
        raise guards.GuardRefusal(f"unexpected token id format: {token!r}")
    return f"raw/{market_id}/{event_date}/{safe_slug}/{token}.f{int(fidelity)}.json.gz"


# --------------------------------------------------------------------------- fetch

def fetch_token(client: RawClient, store: ImmutableStore, market_id: str, event: dict, band: dict,
                fidelity: int) -> dict:
    guards.require_admitted(event["event_date"])  # before any price request for this event
    token = band["yes_token"]
    rel = raw_rel_path(market_id, event["event_date"], event["slug"], token, fidelity)
    start_ts, end_ts = inv.price_history_window(event)
    params = {"market": token, "startTs": start_ts, "endTs": end_ts, "fidelity": int(fidelity)}
    body = client.get_raw(f"{inv.CLOB}/prices-history", params)
    payload = gzip.compress(body, mtime=0)
    store.write(rel, payload)
    try:
        points = len(json.loads(body).get("history") or [])
    except (ValueError, AttributeError):
        points = None
    return {
        "market": market_id, "event_slug": event["slug"], "event_date": event["event_date"],
        "yes_token": token, "condition_id": band.get("condition_id"), "band_label": band.get("band_label"),
        "question": band.get("question"), "fidelity_min": int(fidelity), "start_ts": start_ts, "end_ts": end_ts,
        "url_params": params, "path": rel, "decoded_bytes": len(body),
        "decoded_sha256": hashlib.sha256(body).hexdigest(), "points": points,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def run(markets, client: RawClient, store: ImmutableStore, resources: ResourceGuard, fidelity: int,
        log=print) -> dict:
    counts = {"markets": {}, "tokens_saved": 0, "token_errors": 0, "stopped": None}
    since_check = 0
    try:
        resources.check()
        for market in markets:
            disc = discover_v1(client, market)
            mcount = {"series_id": disc.series_id, "admitted_events": len(disc.admitted),
                      "admitted_dates": len({e["event_date"] for e in disc.admitted}),
                      "refused_events_by_reason": disc.refused, "date_inference": disc.inference,
                      "non_highest_events_skipped": disc.non_highest, "tokens_saved": 0, "token_errors": 0}
            counts["markets"][market.id] = mcount
            for event in sorted(disc.admitted, key=lambda e: (e["event_date"], e["slug"])):
                store.append_jsonl("events.jsonl", {"market": market.id, **{k: event[k] for k in
                                   ("slug", "event_date", "date_inference", "end_date_utc", "start_utc")},
                                   "bands": event["bands"]})
                for band in event["bands"]:
                    if since_check >= RESOURCE_CHECK_EVERY:
                        resources.check()
                        since_check = 0
                    since_check += 1
                    if client.stats.status_429 > MAX_429:
                        raise ResourceStop(f"429 responses {client.stats.status_429} above {MAX_429}")
                    if counts["token_errors"] > MAX_TOKEN_ERRORS:
                        raise ResourceStop(f"token errors {counts['token_errors']} above {MAX_TOKEN_ERRORS}")
                    try:
                        row = fetch_token(client, store, market.id, event, band, fidelity)
                    except guards.GuardRefusal:
                        raise
                    except FileExistsError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - record and continue with other tokens
                        store.append_jsonl("errors.jsonl", {"market": market.id, "event_slug": event["slug"],
                                                            "yes_token": band["yes_token"], "error": repr(exc)[:300]})
                        mcount["token_errors"] += 1
                        counts["token_errors"] += 1
                        continue
                    store.append_jsonl("tokens.jsonl", row)
                    mcount["tokens_saved"] += 1
                    counts["tokens_saved"] += 1
            log(f"{market.id}: events={mcount['admitted_events']} saved={mcount['tokens_saved']} "
                f"errors={mcount['token_errors']} wire_MB={client.stats.wire_bytes / 1e6:.1f}")
    except ResourceStop as exc:
        counts["stopped"] = str(exc)
        log(f"STOPPED: {exc}")
    return counts


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="archive root; each run makes a new <run_id>/ under it")
    parser.add_argument("--markets", default="", help="comma-separated market ids (default: all 22)")
    parser.add_argument("--fidelity", type=int, default=1, choices=(1, 60))
    parser.add_argument("--min-interval", type=float, default=inv.DEFAULT_MIN_INTERVAL_S)
    parser.add_argument("--min-free-gib", type=float, default=DEFAULT_MIN_FREE_GIB)
    parser.add_argument("--max-rss-mib", type=float, default=DEFAULT_MAX_RSS_MIB)
    args = parser.parse_args(argv)
    if args.min_interval < 0.2:
        raise guards.GuardRefusal("request pacing below 0.2 s is refused")
    if args.min_free_gib < DEFAULT_MIN_FREE_GIB or args.max_rss_mib > DEFAULT_MAX_RSS_MIB:
        raise guards.GuardRefusal("free-space floor below 8 GiB or RSS ceiling above 1 GiB is refused")
    wanted = {m for m in args.markets.split(",") if m}
    markets = [m for m in inv.market_universe() if not wanted or m.id in wanted]
    if wanted - {m.id for m in markets}:
        raise SystemExit(f"unknown markets: {sorted(wanted - {m.id for m in markets})}")
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    store = ImmutableStore(root / run_id)
    resources = ResourceGuard(root, args.min_free_gib, args.max_rss_mib)
    client = RawClient(limiter=inv.RateLimiter(min_interval=args.min_interval))
    script_shas = {name: file_sha256(Path(__file__).with_name(name))
                   for name in ("fetch_v1.py", "inventory.py", "guards.py")}
    started = datetime.now(timezone.utc)
    print(f"pid={os.getpid()} run_dir={store.run_dir} script_sha256={script_shas['fetch_v1.py']}", flush=True)
    counts = run(markets, client, store, resources, args.fidelity, log=lambda m: print(m, flush=True))
    manifest = {
        "schema": SCHEMA,
        "purpose": "history-tier comparator, selection evidence only, never an edge claim",
        "run_id": run_id, "pid": os.getpid(),
        "started_utc": started.isoformat(timespec="seconds"),
        "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script_sha256": script_shas, "argv": sys.argv[1:] if argv is None else list(argv),
        "fidelity_min": args.fidelity, "token_side": "Yes only",
        "endpoints": {"gamma": inv.GAMMA, "clob": inv.CLOB},
        "guards": {"last_admitted": guards.LAST_ADMITTED.isoformat(),
                   "sealed_panel": [guards.SEALED_PANEL_FIRST.isoformat(), guards.SEALED_PANEL_LAST.isoformat()],
                   "mg1_refused_from": guards.mg1.MG1_FLOOR.isoformat()},
        "discovery_windows": inv.DISCOVERY_WINDOWS,
        "rate_cap_bytes_per_s": inv.MAX_RATE_BYTES_PER_S, "min_interval_s": args.min_interval,
        "http": vars(client.stats), "peak_rss_bytes_last_check": rss_bytes(),
        "raw_format": "gzip(mtime=0) of the decoded /prices-history response body, byte-exact",
        **counts,
    }
    store.write("manifest.json", json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
    sums = store.seal()
    print(f"sealed {sums} sha256={file_sha256(sums)} tokens_saved={counts['tokens_saved']} "
          f"errors={counts['token_errors']} stopped={counts['stopped']} http={vars(client.stats)}", flush=True)
    return 0 if counts["stopped"] is None else 3


if __name__ == "__main__":
    raise SystemExit(main())
