"""R28b item 4: presence-only T+2 check over the WS T+1 price recorder (master ruling R28b, 2026-11-01).

It measures, for horizon +2 only, whether the recorder held complete T+2 event ladders, using completeness flags and
reason codes and nothing else. It is outcome-blind and price-blind:

* Day manifests (``<root>/<YYYYMMDD>/manifest.json``) are parsed for counts, horizons and ``file_sha256`` only.
* ``prices.jsonl`` is read as bytes. Only lines that start with the cycle record's sorted-key prefix
  (``{"complete": ``) are parsed, and only the fields in ``CYCLE_FIELDS`` are used. Event rows, which hold prices and
  books, are never parsed: they are hashed as raw bytes to verify each cycle's ``rows_sha256`` and the manifest's
  ``file_sha256``.
* ``gaps.jsonl`` holds no prices; only its ``at_utc`` field is used, to count gap records per day.

Recorder contract: ``tools/research/t1_price_forward_recorder.py`` on ``claude/t1-price-recorder-20261030`` @
``32998ac68d8f57e59eab4e7b841eb8993bb6e7f0`` (``run_slot``, ``close_day``; schema ``l3_t1_price_forward/1``). Cycle
reasons are ``<market>+<horizon>:gamma_<status>`` or ``<market>+<horizon>:ladder_incomplete``, plus the unattributed
``stop_file`` and ``events_missing``.

The check runs once, by hand, on an explicit ``--root`` and ``--out``. It registers nothing, schedules nothing and
writes only the one result file under ``--out``. It never prints a price, size, label or settlement.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

SCHEMA_IN = "l3_t1_price_forward/1"
SCHEMA_OUT = "r28b_t2_presence/1"
HORIZON = 2
CYCLE_PREFIX = b'{"complete": '
CYCLE_FIELDS = ("complete", "events_expected", "events_rows", "kind", "late", "reasons", "rows_sha256", "schema",
                "slot_utc", "top_of_hour")
MANIFEST_FIELDS = ("cycles", "cycles_complete", "file_sha256", "horizons", "markets", "recorder_sha256", "schema",
                   "top_of_hour_cycles", "top_of_hour_complete", "top_of_hour_missing", "utc_day")
GLOBAL_REASONS = ("stop_file", "events_missing")


class Refused(Exception):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def closed_days(root: Path, today_utc: dt.date, n: int):
    """The n latest UTC day folders strictly before today that have a closed manifest (names only)."""
    days = []
    for p in root.iterdir():
        if p.is_dir() and len(p.name) == 8 and p.name.isdigit():
            day = dt.datetime.strptime(p.name, "%Y%m%d").date()
            if day < today_utc and (p / "manifest.json").is_file():
                days.append(day)
    return sorted(days)[-n:]


def project(obj, fields):
    return {k: obj.get(k) for k in fields}


def check_day(root: Path, day: dt.date):
    d = root / f"{day:%Y%m%d}"
    man = project(json.loads((d / "manifest.json").read_text(encoding="utf-8")), MANIFEST_FIELDS)
    if man["schema"] != SCHEMA_IN:
        raise Refused(f"{d.name}: manifest schema {man['schema']!r}")
    raw = (d / "prices.jsonl").read_bytes()
    out = {"utc_day": day.isoformat(), "manifest": {k: man[k] for k in MANIFEST_FIELDS if k != "markets"},
           "file_sha256_ok": sha(raw) == man["file_sha256"], "horizon2_recorded": HORIZON in (man["horizons"] or [])}
    markets = sorted(man["markets"] or [])
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    pending = []  # raw event-row lines since the last cycle record (never parsed)
    cycles = 0
    tops = 0
    rows_sha_ok = 0
    torn = 0
    global_reasons = Counter()
    h2_codes = {m: Counter() for m in markets}
    h2_complete = Counter()
    h2_complete_top = Counter()
    unattributed_cycles = 0
    for line in lines:
        if not line.startswith(CYCLE_PREFIX):
            pending.append(line)
            continue
        try:
            cyc = project(json.loads(line), CYCLE_FIELDS)
        except json.JSONDecodeError:
            torn += 1
            pending = []
            continue
        if cyc["kind"] != "cycle" or cyc["schema"] != SCHEMA_IN:
            raise Refused(f"{d.name}: a cycle-prefixed line is not a {SCHEMA_IN} cycle record")
        body = b"".join(x + b"\n" for x in pending[-int(cyc["events_rows"] or 0):]) if cyc["events_rows"] else b""
        rows_sha_ok += sha(body) == cyc["rows_sha256"]
        pending = []
        cycles += 1
        tops += bool(cyc["top_of_hour"])
        reasons = list(cyc["reasons"] or [])
        glob = [r for r in reasons if r in GLOBAL_REASONS]
        global_reasons.update(glob)
        if glob:
            unattributed_cycles += 1
        for m in markets:
            mine = [r.split(":", 1)[1] for r in reasons if r.startswith(f"{m}+{HORIZON}:")]
            h2_codes[m].update(mine)
            if not mine and not glob:
                h2_complete[m] += 1
                h2_complete_top[m] += bool(cyc["top_of_hour"])
    out.update({
        "cycles": cycles, "top_of_hour_cycles": tops, "rows_sha256_ok": rows_sha_ok, "torn_lines": torn,
        "trailing_unclosed_event_lines": len(pending), "cycles_with_unattributed_reason": unattributed_cycles,
        "unattributed_reasons": dict(global_reasons),
        "h2_by_market": {m: {"complete_cycles": h2_complete[m], "complete_top_of_hour": h2_complete_top[m],
                             "reason_codes": dict(h2_codes[m])} for m in markets},
    })
    return out


def gap_counts(root: Path, days):
    path = root / "gaps.jsonl"
    want = {d.isoformat(): 0 for d in days}
    if not path.is_file():
        return {"present": False, "per_day": want}
    for line in path.read_bytes().split(b"\n"):
        if not line.strip():
            continue
        try:
            at = str(json.loads(line).get("at_utc", ""))[:10]
        except json.JSONDecodeError:
            continue
        if at in want:
            want[at] += 1
    return {"present": True, "per_day": want}


def run(root: Path, out: Path, today_utc: dt.date, n_days: int, not_before: dt.date | None):
    root, out = root.resolve(), out.resolve()
    if out == root or root in out.parents:
        raise Refused("--out must be outside --root")
    if not root.is_dir():
        raise Refused(f"--root {root} is not a directory")
    days = closed_days(root, today_utc, n_days)
    if not_before is not None and any(d < not_before for d in days):
        raise Refused("a selected day is before --not-before")
    if len(days) < n_days:
        raise Refused(f"only {len(days)} closed day(s) before {today_utc}; {n_days} required")
    per_day = [check_day(root, d) for d in days]
    result = {"schema": SCHEMA_OUT, "root": str(root), "today_utc": today_utc.isoformat(),
              "days": [d.isoformat() for d in days], "horizon": HORIZON, "per_day": per_day,
              "gaps": gap_counts(root, days),
              "integrity_ok": all(x["file_sha256_ok"] and x["rows_sha256_ok"] == x["cycles"] for x in per_day),
              "note": "presence and counts only; no price, size, label or settlement was parsed"}
    out.mkdir(parents=True, exist_ok=True)
    target = out / "t2_presence_result.json"
    if target.exists():
        raise Refused(f"{target} exists; results are never overwritten")
    data = (json.dumps(result, indent=1, sort_keys=True) + "\n").encode("utf-8")
    target.write_bytes(data)
    return target, sha(data), result


def _selftest():
    """Synthetic only: two markets, horizons 1 and 2, three closed days plus an open one. Reads no real file."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "forward"
        markets = ["aaa", "bbb"]
        for i, day in enumerate([dt.date(2001, 1, 1), dt.date(2001, 1, 2), dt.date(2001, 1, 3), dt.date(2001, 1, 4)]):
            d = root / f"{day:%Y%m%d}"
            d.mkdir(parents=True)
            buf = b""
            cycles = []
            for hour in range(2):
                rows = [{"kind": "event", "market": m, "horizon": h, "secret_price_field": 0.5}
                        for m in markets for h in (1, 2)]
                body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
                reasons = ["bbb+2:ladder_incomplete"] if hour == 1 else []
                if i == 2 and hour == 0:
                    reasons = ["events_missing"]
                cyc = {"kind": "cycle", "schema": SCHEMA_IN, "slot_utc": f"{day}T{hour:02d}:00:00Z",
                       "top_of_hour": True, "late": False, "events_expected": 4, "events_rows": 4,
                       "complete": not reasons, "reasons": reasons, "rows_sha256": sha(body)}
                buf += body + (json.dumps(cyc, sort_keys=True) + "\n").encode()
                cycles.append(cyc)
            (d / "prices.jsonl").write_bytes(buf)
            if i < 3:
                (d / "manifest.json").write_text(json.dumps(
                    {"schema": SCHEMA_IN, "utc_day": day.isoformat(), "cycles": 2, "file_sha256": sha(buf),
                     "horizons": [1, 2], "markets": markets}), encoding="utf-8")
        (root / "gaps.jsonl").write_text(json.dumps({"at_utc": "2001-01-02T05:00:00Z"}) + "\n", encoding="utf-8")
        target, digest, res = run(root, Path(tmp) / "out", dt.date(2001, 1, 5), 3, None)
        assert res["days"] == ["2001-01-01", "2001-01-02", "2001-01-03"], res["days"]
        assert res["integrity_ok"], res
        d1 = res["per_day"][0]
        assert d1["h2_by_market"]["aaa"]["complete_cycles"] == 2
        assert d1["h2_by_market"]["bbb"]["complete_cycles"] == 1
        assert d1["h2_by_market"]["bbb"]["reason_codes"] == {"ladder_incomplete": 1}
        d3 = res["per_day"][2]
        assert d3["cycles_with_unattributed_reason"] == 1 and d3["unattributed_reasons"] == {"events_missing": 1}
        assert d3["h2_by_market"]["aaa"]["complete_cycles"] == 1
        assert res["gaps"]["per_day"] == {"2001-01-01": 0, "2001-01-02": 1, "2001-01-03": 0}
        assert b"secret_price_field" not in target.read_bytes()
        try:
            run(root, Path(tmp) / "out", dt.date(2001, 1, 5), 3, None)
            raise AssertionError("overwrite not refused")
        except Refused:
            pass
        try:
            run(root, root / "x", dt.date(2001, 1, 5), 3, None)
            raise AssertionError("--out inside --root not refused")
        except Refused:
            pass
    return "selftest PASS"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="the recorder's forward root, for example C:/t/t1_prices/forward")
    ap.add_argument("--out", help="a new folder outside --root for the one result file")
    ap.add_argument("--today-utc", help="YYYY-MM-DD; only closed days strictly before it are used")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--not-before", help="YYYY-MM-DD; refuse if a selected day is earlier")
    ap.add_argument("--selftest", action="store_true", help="run the synthetic self-test only (reads no real file)")
    a = ap.parse_args(argv)
    if a.selftest:
        print(_selftest())
        return 0
    if not (a.root and a.out and a.today_utc):
        ap.error("--root, --out and --today-utc are required")
    nb = dt.date.fromisoformat(a.not_before) if a.not_before else None
    try:
        target, digest, res = run(Path(a.root), Path(a.out), dt.date.fromisoformat(a.today_utc), a.days, nb)
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"result": str(target), "sha256": digest, "days": res["days"],
                      "integrity_ok": res["integrity_ok"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
