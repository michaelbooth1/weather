"""Lane L12: fetch a point-in-time NBM NBS/NBH station-block archive (offline research corpus).

Source: NOAA open data on AWS, ``noaa-nbm-grib2-pds`` (anonymous HTTPS, free, official), the
national hourly-issued text bulletins

* NBS (short range, 3-hourly columns, carries ``TXN``): ``blend.YYYYMMDD/HH/text/blend_nbstx.tHHz``
* NBH (hourly columns, ~25 h):                         ``blend.YYYYMMDD/HH/text/blend_nbhtx.tHHz``

Each bulletin is ~28-30 MB, but its station blocks are sorted by station id and are fixed-width
within one file, so this fetcher reads only each wanted station's block with HTTP Range requests:
one read at the previous object's offset (usually exact), then a wider window, then a binary search.
Range reads carry ``If-Match: <ETag>`` so a block can never mix two uploads.

Per (date, cycle, product) it records the S3 ``LastModified`` (the point-in-time availability
instant), size and ETag from the bucket listing, and writes the verbatim station-block bytes to one
``raw/<product>/<YYYYMMDD>/<product>.t<HH>z.blocks`` file plus one manifest JSONL row with each
block's offset in the bulletin, its offset/length in the blocks file and its sha256.

Serial and polite (one request at a time, a short pause, retry with exponential backoff), resumable
from the manifest after a crash, refuses any date after 2026-09-29, and pauses while free disk on
the output volume is below ``--min-free-gb``. Never executes downloaded content. Run it directly with
the venv python (``python -I``), never through the heavy wrapper. It writes only under ``--out-dir``.
This is a research corpus builder, not a production capture path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BUCKET = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
LAST_ALLOWED = date(2026, 9, 29)
PRODUCTS = ("nbs", "nbh")
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
HEADER_RE = re.compile(rb"(?m)^ ?([A-Z0-9]{3,8}) +NBM V\S+ +(NBS|NBH|NBP|NBE|NBX) +GUIDANCE")
PROBE = 6000
NEAR = 16384
WINDOW = 65536
DEFAULT_BLOCK = 3600
PAUSE = 0.05
MANIFEST = "manifest.jsonl"


# --------------------------------------------------------------------------- pure parsing
def header_matches(data):
    """[(station_id, product, offset)] for every block header that starts at a line start."""
    out = []
    for m in HEADER_RE.finditer(data):
        if m.start() == 0 or data[m.start() - 1:m.start()] == b"\n":
            out.append((m.group(1).decode("ascii"), m.group(2).decode("ascii"), m.start()))
    return out


def parse_header_line(block):
    """Parse the first line of a station block: station, product, model version, issue time (UTC)."""
    text = block.decode("ascii", "replace") if isinstance(block, bytes) else block
    first = text.splitlines()[0] if text else ""
    m = re.match(
        r"^ ?([A-Z0-9]{3,8}) +NBM (V\S+) +(NB[A-Z]) +GUIDANCE +(\d{1,2})/(\d{1,2})/(\d{4}) +(\d{2})(\d{2}) UTC",
        first,
    )
    if not m:
        raise ValueError(f"not a NBM block header: {first!r}")
    st, ver, prod, mo, dy, yr, hh, mi = m.groups()
    issued = datetime(int(yr), int(mo), int(dy), int(hh), int(mi), tzinfo=timezone.utc)
    return {"station": st, "version": ver, "product": prod, "issued_utc": issued}


def parse_block(block):
    """Parse one NBS or NBH station block into {header, columns, rows}.

    The bulletin is fixed-width: three characters per column after a five-character element
    label (`` TMP ``), right-aligned, blank where an element is not defined for that column
    (``TXN`` and 6/12-hour fields). Missing columns become ``None``. ``columns`` lists the UTC
    hour of each column; for NBS ``fhr`` gives the forecast hour, and ``valid_utc`` gives the
    column's valid instant resolved forward from the issue time (hours only increase).
    """
    text = block.decode("ascii", "replace") if isinstance(block, bytes) else block
    lines = [ln.rstrip("\r") for ln in text.splitlines()]
    header = parse_header_line(lines[0])
    rows = {}
    utc_hours = None
    fhr = None
    for ln in lines[1:]:
        if len(ln) < 5 or not ln[1:4].strip():
            continue
        label = ln[1:4]
        body = ln[5:]
        if label == "DT ":
            continue
        cells = [body[i:i + 3] for i in range(0, len(body), 3)]
        if label == "UTC":
            utc_hours = [int(c) for c in cells if c.strip()]
            continue
        if label == "FHR":
            fhr = [int(c) for c in cells if c.strip()]
            continue
        rows[label.strip()] = [int(c) if c.strip() else None for c in cells]
    if utc_hours is None:
        raise ValueError("block has no UTC row")
    n = len(utc_hours)
    for k, v in rows.items():
        rows[k] = (v + [None] * n)[:n]
    valid = []
    prev = header["issued_utc"] - timedelta(seconds=1)
    for h in utc_hours:
        cand = prev.replace(hour=h, minute=0, second=0)
        while cand <= prev:
            cand += timedelta(days=1)
        valid.append(cand)
        prev = cand
    return {"header": header, "utc_hours": utc_hours, "fhr": fhr, "valid_utc": valid, "rows": rows}


# --------------------------------------------------------------------------- network
class Fetcher:
    def __init__(self, session, pause=PAUSE):
        self.s = session
        self.pause = pause
        self.requests = 0
        self.bytes = 0

    def _get(self, url, **kw):
        last = None
        for attempt in range(7):
            try:
                self.requests += 1
                r = self.s.get(url, timeout=60, **kw)
                if r.status_code in (200, 206, 404, 416, 412):
                    self.bytes += len(r.content)
                    time.sleep(self.pause)
                    return r
                last = f"HTTP {r.status_code}"
            except Exception as exc:  # transient network error: back off and retry
                last = repr(exc)
            time.sleep(min(120, 2 ** attempt))
        raise RuntimeError(f"GET failed after retries ({last}): {url}")

    def list_text(self, day, cycle):
        """{product: {key, last_modified, size, etag}} for one cycle's text directory."""
        prefix = f"blend.{day:%Y%m%d}/{cycle}/text/"
        r = self._get(BUCKET + "/", params={"list-type": "2", "prefix": prefix})
        if r.status_code != 200:
            raise RuntimeError(f"listing {prefix}: HTTP {r.status_code}")
        root = ET.fromstring(r.content)
        out = {}
        for c in root.findall(f"{NS}Contents"):
            key = c.findtext(f"{NS}Key") or ""
            for p in PRODUCTS:
                if key == f"{prefix}blend_{p}tx.t{cycle}z":
                    out[p] = {"key": key, "last_modified": c.findtext(f"{NS}LastModified"),
                              "size": int(c.findtext(f"{NS}Size")),
                              "etag": (c.findtext(f"{NS}ETag") or "").strip('"')}
        return out

    def read(self, obj, start, length):
        size = obj["size"]
        start = max(0, int(start))
        end = min(size - 1, start + int(length) - 1)
        if start > end:
            return b""
        r = self._get(f"{BUCKET}/{obj['key']}",
                      headers={"Range": f"bytes={start}-{end}", "If-Match": f'"{obj["etag"]}"'})
        if r.status_code == 412:
            raise RuntimeError(f"object changed during read (ETag mismatch): {obj['key']}")
        if r.status_code not in (200, 206):
            raise RuntimeError(f"range read HTTP {r.status_code}: {obj['key']}")
        if r.status_code == 200:  # server ignored Range; keep only the requested slice
            return r.content[start:end + 1]
        return r.content

    # -- locating blocks
    def _block_from(self, obj, data, base, station):
        """If ``data`` (read at ``base``) holds station's header, return (offset, bytes) of its block."""
        hdrs = header_matches(data)
        for i, (sid, _p, off) in enumerate(hdrs):
            if sid != station:
                continue
            if i + 1 < len(hdrs):
                return base + off, data[off:hdrs[i + 1][2]]
            # Header seen but the block runs past the read: extend until the next header/EOF.
            buf = data[off:]
            pos = base + len(data)
            while pos < obj["size"]:
                chunk = self.read(obj, pos, 8192)
                if not chunk:
                    break
                buf += chunk
                pos += len(chunk)
                nxt = [h for h in header_matches(buf) if h[2] > 0]
                if nxt:
                    return base + off, buf[: nxt[0][2]]
            return base + off, buf
        return None

    def first_header_at_or_after(self, obj, offset):
        pos = max(0, offset)
        while pos < obj["size"]:
            chunk = self.read(obj, pos, PROBE)
            if not chunk:
                return None, None
            for sid, _p, off in header_matches(chunk):
                if pos == 0 or off > 0:
                    return sid, pos + off
            pos += PROBE - 200
        return None, None

    def locate(self, obj, station, guess, block_len):
        """(offset, block bytes, method) or (None, None, reason)."""
        if guess is not None:
            start = max(0, guess - 256)
            data = self.read(obj, start, block_len + 1024)
            got = self._block_from(obj, data, start, station)
            if got:
                return got[0], got[1], "guess"
            for win in (NEAR, WINDOW):
                start = max(0, guess - win)
                data = self.read(obj, start, 2 * win)
                got = self._block_from(obj, data, start, station)
                if got:
                    return got[0], got[1], "window"
        lo, hi = 0, obj["size"]
        for _ in range(48):
            mid = (lo + hi) // 2
            sid, off = self.first_header_at_or_after(obj, mid)
            if sid == station:
                data = self.read(obj, off, block_len + 1024)
                got = self._block_from(obj, data, off, station)
                return (got[0], got[1], "bisect") if got else (None, None, "block_unreadable")
            if sid is None or sid > station:
                hi = mid
            else:
                lo = off + 1
            if hi - lo < PROBE // 2:
                data = self.read(obj, lo, PROBE + block_len)
                got = self._block_from(obj, data, lo, station)
                return (got[0], got[1], "bisect") if got else (None, None, "station_absent")
        return None, None, "station_absent"


# --------------------------------------------------------------------------- driver
def registry_stations():
    """Settlement stations of the built-in markets, from the market registry (weather.paths config)."""
    src = Path(__file__).resolve().parents[2] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from weather.market.market_registry import all_specs

    return sorted({s.icao for s in all_specs() if getattr(s, "icao", None)})


def plan_dates(years, months):
    for y in years:
        for m in months:
            d = date(y, m, 1)
            while d.month == m:
                if d > LAST_ALLOWED:
                    raise SystemExit(f"refusing date after {LAST_ALLOWED}: {d}")
                yield d
                d += timedelta(days=1)


def free_gb(path):
    return shutil.disk_usage(path).free / 1e9


def load_done(manifest):
    done = set()
    if manifest.exists():
        with manifest.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue  # torn last line after a crash: refetch that object
                done.add((rec["utc_date"], rec["cycle"], rec["product"]))
    return done


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def fetch_object(f, obj, stations, guesses, block_lens, product):
    blob = bytearray()
    st_rows = {}
    # NOAA alternates between a few station lists, and the object size identifies the list, so an
    # offset seen in an earlier object of the same size is usually exact. Otherwise fall back to the
    # latest offset of this product, shifted by the delta already seen in this object (the stations
    # are sorted, so a shift for one station usually applies to the next).
    size = obj["size"]
    delta = 0
    for st in stations:
        exact = guesses.get((product, size, st))
        prev = guesses.get((product, st))
        if exact is not None:
            guess = exact
        else:
            guess = None if prev is None else max(0, prev + delta)
        off, block, how = f.locate(obj, st, guess, block_lens.get(product, DEFAULT_BLOCK))
        if off is None:
            st_rows[st] = {"status": how}
            continue
        try:
            head = parse_header_line(block)
            valid = head["station"] == st and head["product"] == product.upper()
        except ValueError:
            valid = False
        if not valid:
            raise RuntimeError(f"located block does not start with {st} {product}: {obj['key']}")
        if exact is None and prev is not None:
            delta = off - prev
        guesses[(product, st)] = off
        guesses[(product, size, st)] = off
        block_lens[product] = max(len(block), 512)
        st_rows[st] = {"status": "ok", "method": how, "bulletin_offset": off, "file_offset": len(blob),
                       "length": len(block), "sha256": hashlib.sha256(block).hexdigest()}
        blob += block
    return bytes(blob), st_rows


def main(argv=None):
    import requests

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--years", default="2021,2022,2023,2024,2025")
    ap.add_argument("--months", default="8,9,10,11,12")
    ap.add_argument("--cycles", default=",".join(f"{h:02d}" for h in range(4, 20)))
    ap.add_argument("--products", default="nbs,nbh")
    ap.add_argument("--stations", help="comma list; default: the market registry's settlement stations")
    ap.add_argument("--dates-file", help="optional: one ISO date per line (overrides years/months)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N objects (probe runs)")
    ap.add_argument("--min-free-gb", type=float, default=60.0)
    ap.add_argument("--max-gb", type=float, default=40.0, help="hard cap on bytes downloaded this run")
    ap.add_argument("--pause", type=float, default=PAUSE)
    args = ap.parse_args(argv)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stations = args.stations.split(",") if args.stations else registry_stations()
    products = [p for p in args.products.split(",") if p in PRODUCTS]
    cycles = args.cycles.split(",")
    if args.dates_file:
        dates = [date.fromisoformat(x) for x in Path(args.dates_file).read_text().split() if x.strip()]
        if any(d > LAST_ALLOWED for d in dates):
            raise SystemExit(f"refusing a date after {LAST_ALLOWED}")
    else:
        dates = list(plan_dates([int(y) for y in args.years.split(",")],
                                [int(m) for m in args.months.split(",")]))
    manifest = out / MANIFEST
    done = load_done(manifest)
    total = len(dates) * len(cycles) * len(products)
    print(f"stations={','.join(stations)} objects={total} already_done={len(done)}", flush=True)

    f = Fetcher(requests.Session(), pause=args.pause)
    guesses, block_lens = {}, {}
    n = 0
    t0 = time.time()
    with manifest.open("a", encoding="utf-8") as sink:
        for day in dates:
            for cycle in cycles:
                todo = [p for p in products if (day.isoformat(), cycle, p) not in done]
                if not todo:
                    continue
                while free_gb(out) < args.min_free_gb:
                    print(f"PAUSED: free disk {free_gb(out):.1f} GB < {args.min_free_gb}", flush=True)
                    time.sleep(300)
                if f.bytes > args.max_gb * 1e9:
                    print(f"STOP: download cap {args.max_gb} GB reached", flush=True)
                    return 2
                listing = f.list_text(day, cycle)
                for p in todo:
                    obj = listing.get(p)
                    rec = {"utc_date": day.isoformat(), "cycle": cycle, "product": p,
                           "key": f"blend.{day:%Y%m%d}/{cycle}/text/blend_{p}tx.t{cycle}z",
                           "listed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                    if not obj:
                        rec.update(status="object_missing")
                    else:
                        blob, st_rows = fetch_object(f, obj, stations, guesses, block_lens, p)
                        rel = f"raw/{p}/{day:%Y%m%d}/{p}.t{cycle}z.blocks"
                        write_atomic(out / rel, blob)
                        rec.update(status="ok", last_modified=obj["last_modified"], etag=obj["etag"],
                                   size=obj["size"], blocks_file=rel,
                                   blocks_sha256=hashlib.sha256(blob).hexdigest(), stations=st_rows)
                    sink.write(json.dumps(rec, sort_keys=True) + "\n")
                    sink.flush()
                    os.fsync(sink.fileno())
                    n += 1
                if n and n % 50 < len(todo):
                    rate = n / max(1e-9, time.time() - t0)
                    left = total - len(done) - n
                    print(f"{day} {cycle}Z n={n} left={left} req={f.requests} MB={f.bytes / 1e6:.1f} "
                          f"eta_h={left / max(rate, 1e-9) / 3600:.1f} free_gb={free_gb(out):.0f}", flush=True)
                if args.limit and n >= args.limit:
                    print(f"limit reached n={n} requests={f.requests} MB={f.bytes / 1e6:.2f} "
                          f"secs={time.time() - t0:.0f}", flush=True)
                    return 0
    print(f"done n={n} requests={f.requests} MB={f.bytes / 1e6:.1f} secs={time.time() - t0:.0f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
