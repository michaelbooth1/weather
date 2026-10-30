"""Lane L13: NBM text-bulletin forward recorder: NBH, NBS, NBE and NBP station blocks for the 12 market stations.

Free NOAA open data: the National Blend of Models bucket ``https://noaa-nbm-grib2-pds.s3.amazonaws.com`` (anonymous
HTTPS, no key, no credentials), objects ``blend.<YYYYMMDD>/<HH>/text/blend_<product>tx.t<HH>z``. Design note:
``docs/research/nbm-text-forward-recorder-2026-10-30.md``. Research / shadow only: nothing imports this module, nothing
is served, and no outcome, price or label is read.

* **What is fetched.** NBM is issued every hour. Per cycle one small S3 listing of ``blend.<date>/<HH>/text/`` and then
  each wanted product present in it (NBH about 29 MB, NBS 30 MB, NBE 21 MB, NBP 28 MB; NBP is not issued every hour).
  Each bulletin holds about 9,600 station blocks; only the 12 market stations are kept.
* **What is kept.** For each product and station the block verbatim (``raw`` lines) plus a column parse aligned on the
  header row (``FHR`` where present, else ``UTC``): forecast hour, valid time and every row's integer values in the
  published units (temperatures in deg F, also at CYYZ). Raw bulletins are never written to disk.
* **Point in time.** Every product row carries the key, the S3 listing ``LastModified`` (true publication time; the
  archive keeps it, so a catch-up fetch still knows when the bulletin became available), the response
  ``Last-Modified`` and ETag, our fetch time, the fetch lag and the sha256 of the bytes; ``backfill`` is true when the
  fetch happened more than ``LIVE_WINDOW`` after the cycle. Every block row repeats those and the issuance time parsed
  from its own header, which must equal the cycle.

Per cycle ``<out>/<YYYYMMDD>/<HH>/nbm_text.jsonl`` is append-only. A product's block rows and its ``product`` row are
written in one fsynced append, ``product`` row last; readers trust a block only when a ``product`` row with
``status: ok`` and the same ``file_sha256`` follows it (a torn write after a hard kill leaves blocks without one, and
the product is fetched again). A cycle closes with ``manifest.json`` when every wanted product is ok, or once the
listing has been stable for ``SETTLE`` after the cycle (unlisted products are recorded ``not_issued``; NBP is skipped
most hours), or at ``CLOSE_AFTER`` (products that kept failing are recorded ``missing`` and appended to ``gaps.jsonl``).
Restarts are idempotent: closed cycles and ok products are never fetched again. Guards as the ENS and ECCC recorders:
below-normal priority, throttle and hourly ceiling, a per-process byte cap, a pause file, a STOP file, a
single-instance lock, a free-disk floor and an output-size cap.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import time
import traceback
from collections import defaultdict
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]

UTC = dt.timezone.utc
SCHEMA = "l13_nbm_text_forward/1"
BUCKET = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
FORWARD_FIRST = dt.datetime(2026, 10, 30, 0, tzinfo=UTC)  # first cycle the recorder may ask for
PRODUCTS = ("nbh", "nbs", "nbe", "nbp")
FIRST_TRY = dt.timedelta(minutes=50)    # NBM text appears about 60-80 min after the cycle
LIVE_WINDOW = dt.timedelta(hours=4)     # a fetch later than cycle + LIVE_WINDOW is flagged backfill
SETTLE = dt.timedelta(hours=4)          # after this an unlisted product counts as not issued for the cycle
CLOSE_AFTER = dt.timedelta(hours=48)
LOOKBACK = dt.timedelta(hours=72)       # cycles older than this before the recorder starts are not caught up
MAX_TRIES = 6
SIZE_HINT = 32_000_000
MARKETS = ("toronto", "nyc", "atlanta", "miami", "austin", "chicago", "dallas", "houston", "denver", "los-angeles",
           "san-francisco", "seattle")
HEADER = re.compile(r"^\s*(\S+)\s+NBM V(\S+)\s+(NB[A-Z])\s+GUIDANCE\s+(\d\d)/(\d\d)/(\d{4})\s+(\d\d)(\d\d) UTC")
_LABEL = re.compile(r"\s*([A-Z][A-Z0-9]*)")
_NUM = re.compile(r"-?\d+")
_CELL = re.compile(r"-?\d+")
COL_W = 3  # every NBM text product prints values in 3-character cells right-aligned under the time row


def _iso(t):
    return None if t is None else t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def object_key(cycle, product):
    return f"blend.{cycle:%Y%m%d}/{cycle:%H}/text/blend_{product}tx.t{cycle:%H}z"


def listing_url(cycle):
    return f"{BUCKET}/?list-type=2&prefix=blend.{cycle:%Y%m%d}/{cycle:%H}/text/&max-keys=100"


def parse_listing(xml_bytes):
    """{key: {"last_modified_utc", "etag", "size"}} from an S3 ListObjectsV2 page."""
    root = ElementTree.fromstring(xml_bytes)
    ns = root.tag[: root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    if (root.findtext(f"{ns}IsTruncated") or "false").lower() == "true":
        raise ValueError("listing truncated")
    out = {}
    for c in root.findall(f"{ns}Contents"):
        lm = _parse_iso(c.findtext(f"{ns}LastModified"))
        out[c.findtext(f"{ns}Key")] = {"last_modified_utc": _iso(lm), "etag": (c.findtext(f"{ns}ETag") or "").strip('"'),
                                       "size": int(c.findtext(f"{ns}Size"))}
    return out


# --------------------------------------------------------------------------- bulletin parsing
def split_blocks(text, wanted):
    """{station: (header match groups, lines)} for the wanted station ids; each block runs to the next header."""
    out, cur, lines = {}, None, None
    for line in text.splitlines():
        m = HEADER.match(line)
        if m:
            if cur is not None:
                out[cur[0]] = (cur, lines)
            cur, lines = (m.groups() if m.group(1) in wanted else None), [line.rstrip()]
            continue
        if cur is not None:
            lines.append(line.rstrip())
    if cur is not None:
        out[cur[0]] = (cur, lines)
    return out


def header_fields(groups):
    station, version, product, mm, dd, yyyy, hh, mi = groups
    return {"station": station, "version": version, "product": product.lower(),
            "issued": dt.datetime(int(yyyy), int(mm), int(dd), int(hh), int(mi), tzinfo=UTC)}


def _row(line):
    m = _LABEL.match(line)
    if not m:
        return None, []
    return m.group(1), [(n.end(), int(n.group())) for n in _NUM.finditer(line, m.end())]


def parse_columns(lines, issued):
    """Column parse of one block (lines[0] is the header). Values are right-aligned under the FHR row where there is
    one (NBS, NBE, NBP) and under the UTC row otherwise (NBH, hourly from issue + 1 h). Returns (columns, values,
    unaligned); raises ValueError when the time rows disagree."""
    rows = [_row(l) for l in lines[1:]]
    labels = [r[0] for r in rows]
    if "UTC" not in labels:
        raise ValueError("no UTC row")
    i_utc = labels.index("UTC")
    utc = rows[i_utc][1]
    fhr = rows[labels.index("FHR")][1] if "FHR" in labels else None
    ends = [e for e, _ in (fhr if fhr is not None else utc)]
    if not ends:
        raise ValueError("empty time row")
    utc_at = dict(utc)
    if fhr is not None:
        hours = [v for _, v in fhr]
        if set(utc_at) != set(ends):
            raise ValueError("UTC and FHR columns are not aligned")
    else:
        hours, prev = [], 0
        for _, h in utc:
            k = (h - issued.hour) % 24 or 24
            while k <= prev:
                k += 24
            hours.append(k)
            prev = k
    columns = []
    for e, h in zip(ends, hours):
        valid = issued + dt.timedelta(hours=h)
        if valid.hour != utc_at.get(e):
            raise ValueError(f"FHR {h} valid {valid:%H}Z != UTC row {utc_at.get(e)}")
        columns.append({"fhr": h, "valid_utc": _iso(valid)})
    values, unaligned = {}, {}
    for j, (label, _) in enumerate(rows):
        if label is None or j <= i_utc or label == "FHR":
            continue
        # Fixed-width cells (COL_W characters ending at each header column): adjacent values such as " 99100" have no
        # separator, so tokenising the row would merge them.
        line = lines[1 + j]
        body_start = _LABEL.match(line).end()
        rest, vals = list(line), []
        for e in ends:
            cell = line[e - COL_W:e].strip() if e <= len(line) else line[e - COL_W:].strip()
            vals.append(int(cell) if _CELL.fullmatch(cell) else None)
            if cell and not _CELL.fullmatch(cell):
                unaligned.setdefault(label, []).append(cell)
            for k in range(max(e - COL_W, body_start), min(e, len(rest))):
                rest[k] = " "
        extra = "".join(rest)[body_start:]
        unaligned_vals = [int(n.group()) for n in _NUM.finditer(extra)]
        if unaligned_vals:
            unaligned.setdefault(label, []).extend(unaligned_vals)
        values[label] = vals
    return columns, values, unaligned


# --------------------------------------------------------------------------- storage and guards
def append_jsonl_many(path, recs):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in recs))
        fh.flush()
        os.fsync(fh.fileno())


def append_jsonl(path, rec):
    append_jsonl_many(path, [rec])


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


def stations_from_registry():
    """{icao: market} for the 12 markets, from the market registry."""
    src = _REPO / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from weather.market.market_registry import spec_for_id

    out = {}
    for m in MARKETS:
        icao = spec_for_id(m).icao
        if not re.fullmatch(r"[A-Z0-9]{4}", icao or ""):
            raise SystemExit(f"{m}: bad icao {icao!r}")
        out[icao] = m
    return out


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


class Resp:
    def __init__(self, status, content, headers):
        self.status_code, self.content, self.headers = status, content, headers


class Http:
    """Persistent HTTPS GET client with a per-process byte cap."""

    def __init__(self, cap_bytes, user_agent="weather-research-l13-nbm-text-forward/1 (serial; NOAA open data)"):
        import ssl

        self.ctx = ssl.create_default_context()
        self.base_headers = {"User-Agent": user_agent, "Accept-Encoding": "identity"}
        self.conn, self.host, self.cap = None, None, cap_bytes
        self.used, self.requests = 0, 0

    def _close(self):
        if self.conn is not None:
            self.conn.close()
        self.conn = None

    def get(self, url, timeout=180):
        import http.client
        from urllib.parse import urlsplit

        if self.used >= self.cap:
            raise CapReached(self.used)
        u = urlsplit(url)
        target = u.path + (f"?{u.query}" if u.query else "")
        for attempt in (0, 1):
            if self.conn is None or self.host != u.hostname:
                self._close()
                self.conn = http.client.HTTPSConnection(u.hostname, context=self.ctx, timeout=timeout)
                self.host = u.hostname
            try:
                self.conn.request("GET", target, headers=self.base_headers)
                resp = self.conn.getresponse()
                body = resp.read()
            except (http.client.HTTPException, OSError):
                self._close()
                if attempt:
                    raise
                continue
            self.requests += 1
            self.used += len(body)
            if (resp.getheader("Connection") or "").lower() == "close":
                self._close()
            keep = {k: resp.getheader(k) for k in ("Last-Modified", "ETag", "Content-Length")}
            return Resp(resp.status, body, keep)


class Throttle:
    """Average bytes/s plus a per-clock-hour byte ceiling."""

    def __init__(self, bytes_per_s, hourly_bytes, sleep=time.sleep):
        self.rate, self.hourly, self.sleep = bytes_per_s, hourly_bytes, sleep
        self.hour, self.hour_bytes = None, 0

    def allow(self, now, size_hint):
        hour = now.replace(minute=0, second=0, microsecond=0)
        if hour != self.hour:
            self.hour, self.hour_bytes = hour, 0
        return self.hour_bytes + size_hint <= self.hourly

    def spent(self, nbytes, elapsed_s):
        self.hour_bytes += nbytes
        floor = nbytes / self.rate if self.rate > 0 else 0.0
        if floor > elapsed_s:
            self.sleep(floor - elapsed_s)


def _lm(headers):
    lm = headers.get("Last-Modified")
    return _iso(parsedate_to_datetime(lm)) if lm else None


# --------------------------------------------------------------------------- recorder
class Recorder:
    def __init__(self, out, http, stations=None, clock=None, sleep=time.sleep, products=PRODUCTS, pause_file=None,
                 stop_file=None, bytes_per_s=3_000_000, hourly_mb=1500.0, min_free_gb=20.0, cap_gb=5.0,
                 first_cycle=FORWARD_FIRST):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.http = http
        self.stations = dict(stations) if stations is not None else stations_from_registry()
        self.clock = clock or (lambda: dt.datetime.now(UTC))
        self.sleep = sleep
        self.products = tuple(products)
        if not self.products or set(self.products) - set(PRODUCTS):
            raise SystemExit(f"products must be within {PRODUCTS}")
        self.pause_file = Path(pause_file) if pause_file else self.out / "RECORDER_PAUSE"
        self.stop_file = Path(stop_file) if stop_file else self.out / "STOP"
        self.throttle = Throttle(bytes_per_s, int(hourly_mb * 1e6), sleep)
        self.min_free, self.cap = min_free_gb * 1e9, cap_gb * 1e9
        self.first_cycle = max(first_cycle, FORWARD_FIRST)
        self.started = self.clock()
        self.paused_since = None
        self.cycles = {}
        self.code_sha256 = sha256(Path(__file__).read_bytes())

    def _p(self, *parts):
        return self.out.joinpath(*parts)

    def _dir(self, cycle):
        return self._p(f"{cycle:%Y%m%d}", f"{cycle:%H}")

    def log_event(self, event, **kw):
        append_jsonl(self._p("events.jsonl"), {"event": event, "at_utc": _iso(self.clock()), **kw})

    def cycle_state(self, cycle):
        st = self.cycles.get(cycle)
        if st is None:
            d = self._dir(cycle)
            st = {"ok": {}, "closed": {}, "tries": defaultdict(int), "done": (d / "manifest.json").exists()}
            for r in read_jsonl(d / "nbm_text.jsonl"):
                if r.get("kind") != "product":
                    continue
                p = r["product"]
                if r.get("status") == "ok":
                    st["ok"][p] = r
                elif r.get("status") in ("not_issued", "missing"):
                    st["closed"][p] = r["status"]
                else:
                    st["tries"][p] += 1
            self.cycles[cycle] = st
        return st

    def open_cycles(self, now):
        """Live cycles newest first, then catch-up cycles oldest first."""
        start = max(self.first_cycle, (self.started - LOOKBACK).replace(minute=0, second=0, microsecond=0))
        live, back = [], []
        t = start
        while t + FIRST_TRY <= now:
            if not self.cycle_state(t)["done"]:
                (live if now - t <= LIVE_WINDOW else back).append(t)
            t += dt.timedelta(hours=1)
        return sorted(live, reverse=True) + back

    def _guard(self):
        if not self.throttle.allow(self.clock(), SIZE_HINT):
            self.log_event("hourly_byte_ceiling")
            return False
        if shutil.disk_usage(self.out).free < self.min_free or dir_bytes(self.out) > self.cap:
            self.log_event("disk_guard")
            return False
        return True

    def list_cycle(self, cycle):
        r = self.http.get(listing_url(cycle))
        if r.status_code != 200:
            raise ValueError(f"listing http {r.status_code}")
        return parse_listing(r.content)

    def fetch_product(self, cycle, product, listed):
        """One bulletin; returns the rows to append (block rows, then the product row)."""
        key = object_key(cycle, product)
        url = f"{BUCKET}/{key}"
        base = {"kind": "product", "product": product, "cycle_utc": _iso(cycle), "key": key, "url": url,
                "available_utc": listed["last_modified_utc"], "listed_etag": listed["etag"],
                "listed_size": listed["size"]}
        u0, w0 = self.http.used, time.time()
        try:
            r = self.http.get(url)
        except CapReached:
            raise
        except Exception as e:
            return [{**base, "status": "fetch_error", "error": repr(e)[:300], "fetched_utc": _iso(self.clock())}]
        fetched = self.clock()
        self.throttle.spent(self.http.used - u0, time.time() - w0)
        avail = _parse_iso(listed["last_modified_utc"])
        rec = {**base, "fetched_utc": _iso(fetched), "fetch_lag_s": round((fetched - avail).total_seconds(), 1),
               "backfill": fetched - cycle > LIVE_WINDOW}
        if r.status_code != 200:
            return [{**rec, "status": f"http_{r.status_code}"}]
        rec.update(sha256=sha256(r.content), bytes=len(r.content), last_modified_utc=_lm(r.headers),
                   etag=(r.headers.get("ETag") or "").strip('"'))
        blocks = []
        try:
            if rec["bytes"] != listed["size"]:
                raise ValueError(f"{rec['bytes']} bytes != listed {listed['size']}")
            if rec["etag"] and listed["etag"] and rec["etag"] != listed["etag"]:
                raise ValueError("ETag changed since the listing")
            found = split_blocks(r.content.decode("ascii", errors="replace"), set(self.stations))
            parse_errors = {}
            for icao in sorted(found):
                groups, lines = found[icao]
                h = header_fields(groups)
                if h["product"] != product:
                    raise ValueError(f"{icao}: header product {h['product']} != {product}")
                if h["issued"] != cycle:
                    raise ValueError(f"{icao}: issued {_iso(h['issued'])} != cycle {_iso(cycle)}")
                row = {"kind": "block", "product": product, "cycle_utc": _iso(cycle), "issued_utc": _iso(h["issued"]),
                       "version": h["version"], "icao": icao, "market": self.stations[icao], "raw": lines,
                       "file_sha256": rec["sha256"], "available_utc": rec["available_utc"],
                       "fetched_utc": rec["fetched_utc"], "backfill": rec["backfill"]}
                try:
                    cols, vals, unal = parse_columns(lines, h["issued"])
                    row.update(parse_ok=True, columns=cols, values=vals, unaligned=unal)
                except ValueError as e:
                    row.update(parse_ok=False, parse_error=str(e)[:200])
                    parse_errors[icao] = str(e)[:200]
                blocks.append(row)
            rec.update(status="ok", stations_found=sorted(found),
                       stations_missing=sorted(set(self.stations) - set(found)), parse_errors=parse_errors)
        except CapReached:
            raise
        except Exception as e:
            rec.update(status="invalid", error=repr(e)[:300])
            blocks = []
        return blocks + [rec]

    def _close(self, cycle, product, status, tries):
        rec = {"kind": "product", "product": product, "cycle_utc": _iso(cycle), "key": object_key(cycle, product),
               "status": status, "tries": tries, "closed_utc": _iso(self.clock())}
        append_jsonl(self._dir(cycle) / "nbm_text.jsonl", rec)
        self.cycle_state(cycle)["closed"][product] = status
        if status == "missing" or product != "nbp":
            append_jsonl(self._p("gaps.jsonl"), {"gap": status, **rec})

    def work_cycle(self, cycle, now):
        """Returns (products fetched ok, stopped by a guard)."""
        st = self.cycle_state(cycle)
        todo = [p for p in self.products if p not in st["ok"] and p not in st["closed"]]
        fetched = 0
        if todo:
            try:
                listing = self.list_cycle(cycle)
            except CapReached:
                raise
            except Exception as e:
                self.log_event("listing_failed", cycle=_iso(cycle), error=repr(e)[:300])
                return 0, False
            for p in todo:
                listed = listing.get(object_key(cycle, p))
                if listed is None:
                    if now >= cycle + SETTLE:
                        self._close(cycle, p, "not_issued", st["tries"][p])
                    continue
                if st["tries"][p] >= MAX_TRIES or now >= cycle + CLOSE_AFTER:
                    self._close(cycle, p, "missing", st["tries"][p])
                    continue
                if not self._guard():
                    return fetched, True
                rows = self.fetch_product(cycle, p, listed)
                append_jsonl_many(self._dir(cycle) / "nbm_text.jsonl", rows)
                rec = rows[-1]
                if rec["status"] == "ok":
                    st["ok"][p] = rec
                    fetched += 1
                else:
                    st["tries"][p] += 1
                    self.log_event("fetch_failed", cycle=_iso(cycle), product=p, status=rec["status"])
        if all(p in st["ok"] or p in st["closed"] for p in self.products):
            self.finalize(cycle)
        return fetched, False

    def finalize(self, cycle):
        st = self.cycle_state(cycle)
        d = self._dir(cycle)
        ok = st["ok"]
        append_jsonl(d / "nbm_text.jsonl", {"kind": "cycle_done", "cycle_utc": _iso(cycle), "ok": sorted(ok),
                                            "closed": dict(sorted(st["closed"].items())),
                                            "closed_utc": _iso(self.clock())})
        write_json_atomic(d / "manifest.json", {
            "schema": SCHEMA, "cycle_utc": _iso(cycle), "source": f"NOAA NBM open data ({BUCKET})",
            "products_wanted": list(self.products), "products_ok": sorted(ok),
            "products_closed": dict(sorted(st["closed"].items())),
            "file_sha256": {p: r["sha256"] for p, r in sorted(ok.items())},
            "available_utc": {p: r["available_utc"] for p, r in sorted(ok.items())},
            "fetched_utc": {p: r["fetched_utc"] for p, r in sorted(ok.items())},
            "backfill": {p: r["backfill"] for p, r in sorted(ok.items())},
            "stations_missing": {p: r["stations_missing"] for p, r in sorted(ok.items()) if r["stations_missing"]},
            "parse_errors": {p: r["parse_errors"] for p, r in sorted(ok.items()) if r["parse_errors"]},
            "rows_sha256": sha256((d / "nbm_text.jsonl").read_bytes()),
            "stations": dict(sorted(self.stations.items())), "recorder_sha256": self.code_sha256,
            "written_utc": _iso(self.clock())})
        st["done"] = True
        self.log_event("cycle_done", cycle=_iso(cycle), ok=sorted(ok), closed=st["closed"])

    def step(self, cycles=None):
        now = self.clock()
        paused = self.pause_file.exists()
        if paused and self.paused_since is None:
            self.paused_since = now
            self.log_event("pause_start")
            append_jsonl(self._p("gaps.jsonl"), {"gap": "pause_start", "at_utc": _iso(now)})
        elif not paused and self.paused_since is not None:
            append_jsonl(self._p("gaps.jsonl"), {"gap": "pause_end", "at_utc": _iso(now),
                                                 "started_utc": _iso(self.paused_since)})
            self.log_event("pause_end")
            self.paused_since = None
        fetched, worked = 0, []
        if not paused:
            for c in (cycles if cycles is not None else self.open_cycles(now)):
                if self.stop_file.exists():
                    break
                worked.append(_iso(c))
                n, stopped = self.work_cycle(c, now)
                fetched += n
                if stopped:
                    break
        return {"fetched_products": fetched, "cycles": worked, "paused": paused}

    def status(self, state, extra=None):
        write_json_atomic(self._p("status.json"), {
            "state": state, "pid": os.getpid(), "updated_utc": _iso(self.clock()), "bytes_this_process": self.http.used,
            "requests_this_process": self.http.requests, "cpu_s": round(time.process_time(), 2),
            "paused": self.paused_since is not None, "recorder_sha256": self.code_sha256, **(extra or {})})

    def run(self, poll_s=300, max_steps=None):
        self.log_event("start", pid=os.getpid(), code=code_identity(), products=list(self.products),
                       stations=self.stations)
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
    ap.add_argument("--out", default=r"C:\t\nbm_text\forward")
    ap.add_argument("--products", default=",".join(PRODUCTS))
    ap.add_argument("--pause-file", default=None, help="default <out>/RECORDER_PAUSE")
    ap.add_argument("--stop-file", default=None, help="default <out>/STOP")
    ap.add_argument("--wait-lock-seconds", type=float, default=0.0)
    ap.add_argument("--poll-seconds", type=int, default=300)
    ap.add_argument("--bytes-per-second", type=int, default=3_000_000)
    ap.add_argument("--hourly-mb", type=float, default=1500.0)
    ap.add_argument("--net-cap-gb", type=float, default=200.0, help="network byte cap for this process")
    ap.add_argument("--cap-gb", type=float, default=5.0, help="output directory size cap")
    ap.add_argument("--min-free-gb", type=float, default=20.0)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--first-cycle", default=None, help="UTC ISO; not before the built-in forward start")
    ap.add_argument("--once-cycle", default=None, help="YYYYMMDDHH: one foreground pass over that cycle, then exit")
    args = ap.parse_args(argv)
    products = tuple(p.strip() for p in args.products.split(",") if p.strip())
    out = Path(args.out)
    if _REPO in out.resolve().parents or out.resolve() == _REPO:
        raise SystemExit("output must be outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(out / "recorder.lock", args.wait_lock_seconds)  # noqa: F841 - held until exit
    prio = set_below_normal_priority()
    first = _parse_iso(args.first_cycle) if args.first_cycle else FORWARD_FIRST
    rec = Recorder(out, Http(int(args.net_cap_gb * 1e9)), products=products, pause_file=args.pause_file,
                   stop_file=args.stop_file, bytes_per_s=args.bytes_per_second, hourly_mb=args.hourly_mb,
                   min_free_gb=args.min_free_gb, cap_gb=args.cap_gb, first_cycle=first)
    rec.log_event("priority", below_normal=prio)
    if args.once_cycle:
        cycle = dt.datetime.strptime(args.once_cycle, "%Y%m%d%H").replace(tzinfo=UTC)
        if cycle < FORWARD_FIRST:
            raise SystemExit(f"--once-cycle before the forward start {_iso(FORWARD_FIRST)}")
        rec.log_event("once", cycle=_iso(cycle), code=code_identity())
        result = rec.step([cycle])
        rec.status("once_done", result)
        print(json.dumps(result))
        return 0
    (out / "recorder.pid").write_text(str(os.getpid()), encoding="ascii")
    rec.run(args.poll_seconds, args.max_steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
