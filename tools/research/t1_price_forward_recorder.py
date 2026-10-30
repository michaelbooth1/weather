"""Lane L3: WS T+1 price forward recorder: Gamma Yes and CLOB best bid/ask for every band of the T+1 and T+2 events.

Public, read-only International Polymarket endpoints only, over plain HTTPS with no credentials, cookies or auth
headers. Design note: ``docs/research/t1-price-forward-recorder-2026-10-30.md``. Research / shadow only: nothing
imports this module, nothing is served, no order, signing or account endpoint exists here, and no outcome,
settlement or label is read.

* **What is fetched.** At every UTC quarter-hour slot (every local top of hour for these whole-hour time zones,
  plus the :15/:30/:45 points), for each market and horizon h in (1, 2):
  - ``GET https://gamma-api.polymarket.com/events/slug/<slug>`` for target date = market-local today + h;
  - ``POST https://clob.polymarket.com/books`` with the YES token ids of the event's bands (the public batch book
    read; no auth).
* **What is kept, per band.** The Gamma ``outcomePrices`` entry labelled "Yes" (the T+0 layout's ``market_yes``
  definition), the CLOB best bid and best ask of the YES token with their sizes and the book timestamp, the
  condition id, Gamma market id, band label and active/closed flags. Never ``last_trade_price``.
* **Per event row.** Receipt times for the Gamma and the book replies, event id and slug, target date, horizon,
  the full-ladder Yes sum and whether the ladder is complete (every band has a finite Yes price).
* **Per cycle.** All event rows of a slot and then one ``cycle`` record are written in one fsynced append to
  ``<out>/<YYYYMMDD>/prices.jsonl`` (UTC day). The cycle record carries ``rows_sha256`` over its event rows and
  ``complete`` (every expected event fetched with a complete ladder) or the reasons it is incomplete. Readers trust
  event rows only when a cycle record with the same ``slot_utc`` and a matching ``rows_sha256`` follows them.
  When a UTC day is over, ``<out>/<YYYYMMDD>/manifest.json`` records the counts and the file sha256.
* **No backfill.** Prices cannot be fetched after the fact: a slot is attempted only within ``SLOT_GRACE`` of its
  start; a missed slot is written to ``gaps.jsonl``.

Guards as the L13 recorders: below-normal priority, a request throttle and hourly request ceiling, a per-process
byte cap, a pause file, a STOP file, a single-instance lock, a free-disk floor and an output-size cap; the URL
allowlist refuses anything but the two reads above.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
import traceback
from pathlib import Path
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]

UTC = dt.timezone.utc
SCHEMA = "l3_t1_price_forward/1"
GAMMA_HOST = "gamma-api.polymarket.com"
CLOB_HOST = "clob.polymarket.com"
GAMMA_EVENT = f"https://{GAMMA_HOST}/events/slug/"
CLOB_BOOKS = f"https://{CLOB_HOST}/books"
SLUG = re.compile(r"[a-z0-9-]{8,120}\Z")
TOKEN = re.compile(r"[0-9]{10,90}\Z")
# The 10 US markets other than Denver, Toronto, and Denver (KDEN; recorded because it costs nothing).
MARKETS = ("toronto", "nyc", "atlanta", "miami", "austin", "chicago", "dallas", "houston", "denver", "los-angeles",
           "san-francisco", "seattle")
HORIZONS = (1, 2)
SLOT = dt.timedelta(minutes=15)
SLOT_GRACE = dt.timedelta(minutes=10)
BOOK_BATCH = 50
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
SUM_LO, SUM_HI = 0.90, 1.10


def _iso(t):
    return None if t is None else t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def slot_floor(t):
    t = t.astimezone(UTC)
    return t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0)


# --------------------------------------------------------------------------- parsing
def json_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            out = json.loads(value)
        except ValueError:
            return []
        return out if isinstance(out, list) else []
    return []


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def yes_entry(outcomes, values):
    """The entry of ``values`` labelled "Yes" in ``outcomes`` (case-insensitive), else None."""
    for o, v in zip(outcomes, values):
        if str(o).strip().lower() == "yes":
            return v
    return None


def parse_event(event):
    """Bands of a Gamma event: one dict per market with the Yes price and the YES token id."""
    bands = []
    for m in event.get("markets") or []:
        outcomes = json_list(m.get("outcomes"))
        bands.append({
            "condition_id": m.get("conditionId"),
            "gamma_market_id": m.get("id"),
            "label": m.get("groupItemTitle") or m.get("question"),
            "yes": _num(yes_entry(outcomes, json_list(m.get("outcomePrices")))),
            "yes_token": yes_entry(outcomes, json_list(m.get("clobTokenIds"))),
            "active": m.get("active"),
            "closed": m.get("closed"),
            "accepting_orders": m.get("acceptingOrders"),
        })
    return bands


def best_levels(book):
    """(best bid, bid size, best ask, ask size) from a CLOB book; None where a side is empty."""
    def levels(side):
        out = []
        for lv in book.get(side) or []:
            p, s = _num(lv.get("price")), _num(lv.get("size"))
            if p is not None and s is not None and s > 0:
                out.append((p, s))
        return out
    bids, asks = levels("bids"), levels("asks")
    bb = max(bids) if bids else (None, None)
    ba = min(asks) if asks else (None, None)
    return bb[0], bb[1], ba[0], ba[1]


def ladder_check(bands):
    yes = [b["yes"] for b in bands]
    complete = bool(bands) and all(v is not None for v in yes)
    total = round(sum(v for v in yes if v is not None), 6) if bands else None
    return {"n_bands": len(bands), "n_yes": sum(v is not None for v in yes), "yes_sum": total,
            "ladder_complete": complete,
            "sum_in_range": bool(complete and SUM_LO <= total <= SUM_HI),
            "n_book_two_sided": sum(b.get("best_bid") is not None and b.get("best_ask") is not None for b in bands)}


# --------------------------------------------------------------------------- storage and guards
def append_jsonl_many(path, recs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))
        fh.flush()
        os.fsync(fh.fileno())


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:  # a torn last line after a hard kill
                continue
    return out


def write_json_atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, indent=1, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def dir_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


def git_blob_id(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def code_identity():
    raw = Path(__file__).read_bytes()
    return {Path(__file__).name: {"git_blob_lf": git_blob_id(raw.replace(b"\r\n", b"\n")), "sha256": sha256(raw)}}


def markets_from_registry():
    """{market: (slug_prefix, tz)} for the built-in markets, from the default market registry only."""
    if os.environ.get("WEATHER_MARKET_REGISTRY"):
        raise SystemExit("WEATHER_MARKET_REGISTRY is set; this recorder reads the built-in registry only")
    src = _REPO / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from weather.market.market_registry import spec_for_id

    out = {}
    for m in MARKETS:
        spec = spec_for_id(m)
        if spec.id != m or not SLUG.fullmatch(spec.slug_prefix):
            raise SystemExit(f"{m}: unexpected spec {spec.id!r} {spec.slug_prefix!r}")
        tz = getattr(spec.tz, "key", spec.tz)
        ZoneInfo(tz)
        out[m] = (spec.slug_prefix, tz)
    return out


MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")


def event_slug(prefix, day):
    """The repository's event slug rule (weather.market.market_config.event_slug_for_date)."""
    return f"{prefix}-{MONTHS[day.month - 1]}-{day.day}-{day.year}"


def set_below_normal_priority():
    try:
        if os.name == "nt":
            import ctypes

            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = ctypes.c_void_p
            k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
            return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000))
        os.nice(5)
        return True
    except Exception:  # pragma: no cover - best effort, recorded in events
        return False


def acquire_lock(path, wait_s=0.0, sleep=time.sleep):
    deadline = time.monotonic() + wait_s
    while True:
        fh = open(path, "a+")
        try:
            if os.name == "nt":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            fh.close()
            if time.monotonic() >= deadline:
                raise SystemExit(f"another recorder holds {path}")
            sleep(1.0)


class CapReached(RuntimeError):
    pass


class Refused(ValueError):
    pass


def check_url(method, url, body):
    """Only the two public reads: GET a Gamma event by slug, POST a CLOB book batch of token ids."""
    from urllib.parse import urlsplit

    u = urlsplit(url)
    if u.scheme != "https" or u.username or u.password or u.query or u.fragment or u.port:
        raise Refused(f"not an allowlisted public read: {url}")
    if method == "GET" and u.hostname == GAMMA_HOST and u.path.startswith("/events/slug/") and body is None:
        if SLUG.fullmatch(u.path[len("/events/slug/"):]):
            return
    if method == "POST" and u.hostname == CLOB_HOST and u.path == "/books" and isinstance(body, list):
        if body and len(body) <= BOOK_BATCH and all(
                isinstance(x, dict) and set(x) == {"token_id"} and TOKEN.fullmatch(str(x["token_id"])) for x in body):
            return
    raise Refused(f"not an allowlisted public read: {method} {url}")


class Resp:
    def __init__(self, status, content, headers):
        self.status_code, self.content, self.headers = status, content, headers


class Http:
    """HTTPS client for the two allowlisted public reads, with a per-process byte cap. No cookies, no auth."""

    def __init__(self, cap_bytes, user_agent="weather-research-l3-t1-price-forward/1 (public read-only)"):
        import ssl

        self.ctx = ssl.create_default_context()
        self.base_headers = {"User-Agent": user_agent, "Accept": "application/json", "Accept-Encoding": "identity"}
        self.conns, self.cap = {}, cap_bytes
        self.used, self.requests = 0, 0

    def _close(self, host):
        c = self.conns.pop(host, None)
        if c is not None:
            c.close()

    def request(self, method, url, body=None, timeout=20):
        import http.client
        from urllib.parse import urlsplit

        check_url(method, url, body)
        if self.used >= self.cap:
            raise CapReached(self.used)
        u = urlsplit(url)
        payload = None if body is None else json.dumps(body).encode()
        headers = dict(self.base_headers)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        for attempt in (0, 1):
            conn = self.conns.get(u.hostname)
            if conn is None:
                conn = self.conns[u.hostname] = http.client.HTTPSConnection(u.hostname, context=self.ctx,
                                                                            timeout=timeout)
            try:
                conn.request(method, u.path, body=payload, headers=headers)
                resp = conn.getresponse()
                data = resp.read(MAX_RESPONSE_BYTES + 1)
            except (http.client.HTTPException, OSError):
                self._close(u.hostname)
                if attempt:
                    raise
                continue
            self.requests += 1
            self.used += len(data) + (len(payload) if payload else 0)
            if len(data) > MAX_RESPONSE_BYTES:
                self._close(u.hostname)
                raise ValueError("public reply exceeds byte bound")
            if (resp.getheader("Connection") or "").lower() == "close":
                self._close(u.hostname)
            return Resp(resp.status, data, {"Date": resp.getheader("Date")})


# --------------------------------------------------------------------------- recorder
class Recorder:
    def __init__(self, out, http, markets=None, clock=None, sleep=time.sleep, horizons=HORIZONS, pause_file=None,
                 stop_file=None, min_interval_s=0.2, hourly_requests=4000, min_free_gb=20.0, cap_gb=2.0,
                 quarter_hours=True):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.http = http
        self.markets = dict(markets) if markets is not None else markets_from_registry()
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.sleep = sleep
        self.horizons = tuple(horizons)
        if not self.horizons or set(self.horizons) - set(HORIZONS):
            raise SystemExit(f"horizons must be within {HORIZONS}")
        self.pause_file = Path(pause_file) if pause_file else self.out / "RECORDER_PAUSE"
        self.stop_file = Path(stop_file) if stop_file else self.out / "STOP"
        self.min_interval, self.hourly_requests = min_interval_s, hourly_requests
        self.min_free, self.cap = min_free_gb * 1e9, cap_gb * 1e9
        self.quarter_hours = quarter_hours
        self.hour, self.hour_requests, self.last_request = None, 0, None
        self.paused_since = None
        self.last_slot = None
        self.done = {}
        self.code_sha256 = sha256(Path(__file__).read_bytes())

    def _p(self, *parts):
        return self.out.joinpath(*parts)

    def log_event(self, event, **kw):
        append_jsonl_many(self._p("events.jsonl"), [{"event": event, "at_utc": _iso(self.clock()), **kw}])

    def gap(self, **kw):
        append_jsonl_many(self._p("gaps.jsonl"), [{"at_utc": _iso(self.clock()), **kw}])

    def wanted(self, slot):
        return self.quarter_hours or slot.minute == 0

    def slot_done(self, slot):
        day = f"{slot:%Y%m%d}"
        if day not in self.done:  # read a day's cycle records once per process, then track in memory
            self.done[day] = {r.get("slot_utc") for r in read_jsonl(self._p(day, "prices.jsonl"))
                              if r.get("kind") == "cycle"}
        return _iso(slot) in self.done[day]

    def _guard(self):
        """True when another request may go out now (disk floor, output cap, hourly ceiling, throttle)."""
        if shutil.disk_usage(self.out).free < self.min_free:
            self.log_event("disk_floor")
            return False
        if dir_bytes(self.out) > self.cap:
            self.log_event("output_cap")
            return False
        now = self.clock()
        hour = now.replace(minute=0, second=0, microsecond=0)
        if hour != self.hour:
            self.hour, self.hour_requests = hour, 0
        if self.hour_requests >= self.hourly_requests:
            self.log_event("hourly_ceiling", requests=self.hour_requests)
            return False
        if self.last_request is not None:
            wait = self.min_interval - (time.monotonic() - self.last_request)
            if wait > 0:
                self.sleep(wait)
        self.hour_requests += 1
        self.last_request = time.monotonic()
        return True

    def _json(self, method, url, body=None):
        if not self._guard():
            return None, "guard", None
        try:
            r = self.http.request(method, url, body)
        except CapReached:
            raise
        except Exception as e:  # recorded per event; the cycle is marked incomplete
            return None, f"error:{type(e).__name__}", _iso(self.clock())
        received = _iso(self.clock())
        if r.status_code != 200:
            return None, f"http_{r.status_code}", received
        try:
            return json.loads(r.content), "ok", received
        except ValueError:
            return None, "bad_json", received

    def fetch_event(self, slot, market, h):
        prefix, tz = self.markets[market]
        target = (slot.astimezone(ZoneInfo(tz)).date() + dt.timedelta(days=h))
        slug = event_slug(prefix, target)
        row = {"kind": "event", "schema": SCHEMA, "slot_utc": _iso(slot), "top_of_hour": slot.minute == 0,
               "market": market, "horizon": h, "target_date": target.isoformat(), "event_slug": slug}
        event, status, received = self._json("GET", GAMMA_EVENT + slug)
        row.update(gamma_status=status, gamma_received_utc=received)
        if status != "ok" or not isinstance(event, dict):
            row.update(event_id=None, bands=[], book_status="skipped", books_received_utc=None, **ladder_check([]))
            return row
        bands = parse_event(event)
        row["event_id"] = event.get("id")
        tokens = [b["yes_token"] for b in bands if b["yes_token"] and TOKEN.fullmatch(str(b["yes_token"]))]
        books, book_status, books_received = {}, "ok" if tokens else "no_tokens", None
        for i in range(0, len(tokens), BOOK_BATCH):
            chunk = tokens[i:i + BOOK_BATCH]
            reply, st, books_received = self._json("POST", CLOB_BOOKS, [{"token_id": str(t)} for t in chunk])
            if st != "ok" or not isinstance(reply, list):
                book_status = st if st != "ok" else "bad_shape"
                continue
            for b in reply:
                if isinstance(b, dict) and b.get("asset_id"):
                    books[str(b["asset_id"])] = b
        for b in bands:
            book = books.get(str(b["yes_token"])) if b["yes_token"] else None
            bb, bs, ba, as_ = best_levels(book) if book else (None, None, None, None)
            b.update(best_bid=bb, best_bid_size=bs, best_ask=ba, best_ask_size=as_,
                     book_timestamp=book.get("timestamp") if book else None)
        row.update(bands=bands, book_status=book_status, books_received_utc=books_received, **ladder_check(bands))
        return row

    def run_slot(self, slot):
        """Fetch every (market, horizon) event for the slot; one fsynced append of the rows plus the cycle record."""
        started = self.clock()
        rows, stopped = [], False
        for market in self.markets:
            for h in self.horizons:
                if self.stop_file.exists():
                    stopped = True
                    break
                rows.append(self.fetch_event(slot, market, h))
            if stopped:
                break
        expected = len(self.markets) * len(self.horizons)
        reasons = []
        if stopped:
            reasons.append("stop_file")
        for r in rows:
            if r["gamma_status"] != "ok":
                reasons.append(f"{r['market']}+{r['horizon']}:gamma_{r['gamma_status']}")
            elif not r["ladder_complete"]:
                reasons.append(f"{r['market']}+{r['horizon']}:ladder_incomplete")
        if len(rows) < expected and not stopped:
            reasons.append("events_missing")
        body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
        cycle = {"kind": "cycle", "schema": SCHEMA, "slot_utc": _iso(slot), "top_of_hour": slot.minute == 0,
                 "started_utc": _iso(started), "finished_utc": _iso(self.clock()),
                 "late": started - slot > SLOT_GRACE, "events_expected": expected, "events_rows": len(rows),
                 "events_complete": sum(r["ladder_complete"] for r in rows),
                 "events_sum_in_range": sum(r["sum_in_range"] for r in rows),
                 "complete": not reasons, "reasons": reasons, "rows_sha256": sha256(body),
                 "recorder_sha256": self.code_sha256}
        append_jsonl_many(self._p(f"{slot:%Y%m%d}", "prices.jsonl"), rows + [cycle])
        self.slot_done(slot)
        self.done[f"{slot:%Y%m%d}"].add(_iso(slot))
        self.log_event("cycle", slot=_iso(slot), complete=cycle["complete"], reasons=reasons[:20])
        return cycle

    def close_day(self, day):
        d = self._p(f"{day:%Y%m%d}")
        f = d / "prices.jsonl"
        if (d / "manifest.json").exists() or not f.exists():
            return
        cycles = [r for r in read_jsonl(f) if r.get("kind") == "cycle"]
        tops = [c for c in cycles if c["top_of_hour"]]
        write_json_atomic(d / "manifest.json", {
            "schema": SCHEMA, "utc_day": f"{day:%Y-%m-%d}", "cycles": len(cycles),
            "cycles_complete": sum(c["complete"] for c in cycles), "top_of_hour_cycles": len(tops),
            "top_of_hour_complete": sum(c["complete"] for c in tops),
            "top_of_hour_missing": 24 - len({c["slot_utc"] for c in tops}),
            "file_sha256": sha256(f.read_bytes()), "markets": sorted(self.markets), "horizons": list(self.horizons),
            "recorder_sha256": self.code_sha256, "written_utc": _iso(self.clock())})
        self.log_event("day_closed", day=f"{day:%Y-%m-%d}")

    def step(self):
        """Run the current slot if it is due, not done and within its grace; record missed slots."""
        now = self.clock()
        paused = self.pause_file.exists()
        if paused and self.paused_since is None:
            self.paused_since = now
            self.log_event("pause_start")
            self.gap(gap="pause_start")
        elif not paused and self.paused_since is not None:
            self.gap(gap="pause_end", started_utc=_iso(self.paused_since))
            self.log_event("pause_end")
            self.paused_since = None
        slot = slot_floor(now)
        if self.last_slot is None:  # first step of this process: close any earlier UTC day left open by a restart
            for d in sorted(self.out.glob("[0-9]" * 8)):
                day = dt.datetime.strptime(d.name, "%Y%m%d").replace(tzinfo=UTC)
                if day.date() < slot.date():
                    self.close_day(day)
        else:
            t = self.last_slot + SLOT
            while t < slot:
                if self.wanted(t) and not self.slot_done(t):
                    self.gap(gap="slot_missed", slot_utc=_iso(t))
                t += SLOT
            if self.last_slot.date() != slot.date():
                self.close_day(self.last_slot)
        self.last_slot = slot
        if paused or not self.wanted(slot) or now - slot > SLOT_GRACE or self.slot_done(slot):
            return {"slot": _iso(slot), "ran": False, "paused": paused}
        cycle = self.run_slot(slot)
        return {"slot": _iso(slot), "ran": True, "complete": cycle["complete"], "paused": False}

    def status(self, state, extra=None):
        write_json_atomic(self._p("status.json"), {
            "state": state, "pid": os.getpid(), "updated_utc": _iso(self.clock()), "bytes_this_process": self.http.used,
            "requests_this_process": self.http.requests, "cpu_s": round(time.process_time(), 2),
            "paused": self.paused_since is not None, "recorder_sha256": self.code_sha256, **(extra or {})})

    def run(self, poll_s=20, max_steps=None):
        self.log_event("start", pid=os.getpid(), code=code_identity(), markets=self.markets,
                       horizons=list(self.horizons), quarter_hours=self.quarter_hours)
        n = 0
        while True:
            if self.stop_file.exists():
                self.log_event("stop_file")
                self.status("stopped_by_file")
                return
            try:
                self.status("running", self.step())
            except CapReached:
                self.log_event("cap_reached")
                self.status("cap_reached")
                return
            except Exception as e:  # keep recording; the failure is logged
                self.log_event("step_error", error=repr(e)[:500], tb=traceback.format_exc()[-1500:])
                self.status("running_after_error")
            n += 1
            if max_steps is not None and n >= max_steps:
                return
            self.sleep(poll_s)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=r"C:\t\t1_prices\forward")
    ap.add_argument("--horizons", default="1,2")
    ap.add_argument("--top-of-hour-only", action="store_true", help="skip the :15/:30/:45 points")
    ap.add_argument("--pause-file", default=None, help="default <out>/RECORDER_PAUSE")
    ap.add_argument("--stop-file", default=None, help="default <out>/STOP")
    ap.add_argument("--wait-lock-seconds", type=float, default=0.0)
    ap.add_argument("--poll-seconds", type=int, default=20)
    ap.add_argument("--min-interval-seconds", type=float, default=0.2)
    ap.add_argument("--hourly-requests", type=int, default=4000)
    ap.add_argument("--net-cap-gb", type=float, default=20.0, help="network byte cap for this process")
    ap.add_argument("--cap-gb", type=float, default=2.0, help="output directory size cap")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--once", action="store_true", help="one foreground cycle for the current slot, then exit")
    args = ap.parse_args(argv)
    horizons = tuple(int(h) for h in args.horizons.split(",") if h.strip())
    out = Path(args.out)
    if _REPO in out.resolve().parents or out.resolve() == _REPO:
        raise SystemExit("output must be outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(out / "recorder.lock", args.wait_lock_seconds)  # noqa: F841 - held until exit
    prio = set_below_normal_priority()
    rec = Recorder(out, Http(int(args.net_cap_gb * 1e9)), horizons=horizons, pause_file=args.pause_file,
                   stop_file=args.stop_file, min_interval_s=args.min_interval_seconds,
                   hourly_requests=args.hourly_requests, min_free_gb=args.min_free_gb, cap_gb=args.cap_gb,
                   quarter_hours=not args.top_of_hour_only)
    rec.log_event("priority", below_normal=prio)
    if args.once:
        slot = slot_floor(rec.clock())
        rec.log_event("once", slot=_iso(slot), code=code_identity())
        cycle = rec.run_slot(slot)
        result = {k: cycle[k] for k in ("slot_utc", "complete", "events_expected", "events_rows", "events_complete",
                                        "events_sum_in_range", "reasons")}
        result.update(bytes=rec.http.used, requests=rec.http.requests)
        rec.status("once_done", result)
        print(json.dumps(result))
        return 0
    (out / "recorder.pid").write_text(str(os.getpid()), encoding="ascii")
    rec.run(args.poll_seconds, args.max_steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
