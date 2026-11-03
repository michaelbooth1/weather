"""Row 28 guard diagnostic d3 (lane L59): the build-1 HALT. COUNTS ONLY; no date value, no hash of a dated string.

Started by launcher v6 like a stage (the launcher passes --roots --out-json --out-csv --expect-sha --stage; --stage is
only a launcher label here), d1 method. It imports runner v10 as a module (sha256-checked; main() is not run) and
uses the runner's own context and guard objects: load_context, set_guard_centres, guard_file, _walk, _GUARD_RS,
GUARD_FROM, guard_text, _n_dated. Nothing is copied.

Scope: exactly one file, the build-1 stage-end hit file s2_build/nbm_market_new/nbm_pit_corpus_rows.jsonl, read in
place. (The refused 300-token write, pool_nbm_rows.jsonl, is NOT reproduced here: its producer reads about 2 GB of
block files and parses NBP text for 300 stations, which is not light.)

For every row the runner's own _walk gives that row's hits (so the attribution reconciles to the runner exactly); in
parallel every string value at every key path is scanned for dated tokens >= GUARD_FROM and each token is reported
only as (key path, class, token format, market-local class, row-date field or not). Month buckets are reported as
Y26-Mmm tags, the min and max only. The output is checked with the runner's guard_text and _n_dated before it is
written.
"""
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

RUNNER = Path(r"C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v10.py")
RUNNER_V10_SHA256 = "dc58715ca4f8834746051e3aa8c5408f115e384a63cbf512ef1940cfea82abaa"
HIT_FILE = Path(r"C:\t\L59\row28\run\s2_build\nbm_market_new\nbm_pit_corpus_rows.jsonl")
EXPECT_HITS = 11
# Row-date fields by name: a date or instant that describes the row itself (its day, its issue, its validity) or
# its source object's publication instant. last_modified is listed separately so a hit there is visible by name.
ROW_DATE_FIELDS = ("target_date", "date", "utc_date", "valid_time_utc", "issued_at")
OBJECT_INSTANT_FIELDS = ("last_modified",)
_TAIL = re.compile(r"[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?")


def cls(d):
    if d < "2026-01-01":
        return "PRE2026"
    if d < "2026-05-27":
        return "Y26_PRE0527"
    if d <= "2026-07-30":
        return "SEALED"
    if d <= "2026-09-28":
        return "GAP"
    return "EMBARGO"


def month_tag(d):
    return f"Y{d[2:4]}-M{d[5:7]}"


def main():
    a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    out_json, out_csv = Path(a["--out-json"]), Path(a["--out-csv"])
    if hashlib.sha256(RUNNER.read_bytes()).hexdigest() != RUNNER_V10_SHA256:
        out_json.write_text(json.dumps({"status": "REFUSED", "reason": "runner sha256 differs"}) + "\n")
        return 3
    spec = importlib.util.spec_from_file_location("row28_run_v10", RUNNER)
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)
    import pandas as pd

    cfg = json.loads(Path(a["--roots"]).read_text(encoding="utf-8"))
    ctx = rv.load_context(cfg)
    rv.set_guard_centres(ctx.centres, cfg["records_root"])

    runner_file_hits = rv.guard_file(HIT_FILE)
    rows = Counter()
    row_hits = Counter()
    months = []
    at_or_after_0527 = {"literal": 0, "market_local": 0}
    n_rows = rows_with_hits = 0
    unknown_market = 0
    with open(rv.guard_read(HIT_FILE), encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            r = json.loads(line)
            n_rows += 1
            h, _ = rv._walk(r)
            row_hits.update(h)
            if sum(h.values()):
                rows_with_hits += 1
            market = r.get("market_id")
            tz = ctx.tz.get(market)
            if tz is None:
                unknown_market += 1
            stack = [((), r)]
            while stack:
                path, o = stack.pop()
                if isinstance(o, dict):
                    for k, v in o.items():
                        if rv._n_dated(str(k)):
                            rows[("/".join(path) or "<root>", "<key>", "key", "n/a", "n/a", "n/a")] += 1
                        stack.append((path + (str(k),), v))
                    continue
                if isinstance(o, list):
                    stack.extend((path + ("[i]",), x) for x in o)
                    continue
                if not isinstance(o, str):
                    continue
                for m in rv._GUARD_RS.finditer(o):
                    d = m.group(1)
                    if d < rv.GUARD_FROM:
                        continue
                    tail = _TAIL.match(o, m.end())
                    if tail is None:
                        fmt = "date-only"
                    elif tail.group(1) == "Z":
                        fmt = "ISO-with-Z"
                    elif tail.group(1):
                        fmt = "ISO-with-offset"
                    else:
                        fmt = "ISO-naive"
                    local = cls(d)
                    local_day = d
                    if fmt in ("ISO-with-Z", "ISO-with-offset") and tz is not None:
                        try:
                            local_day = pd.Timestamp(o[m.start():tail.end()]).tz_convert(tz).date().isoformat()
                            local = cls(local_day)
                        except Exception:
                            local = "unparsed"
                    if d >= "2026-05-27":
                        at_or_after_0527["literal"] += 1
                    if local_day >= "2026-05-27" or local == "unparsed":
                        at_or_after_0527["market_local"] += 1
                    field = path[-1] if path else "<root>"
                    kind = ("row-date field" if field in ROW_DATE_FIELDS else
                            "object instant field" if field in OBJECT_INSTANT_FIELDS else "other field")
                    months.append(d)
                    rows[("/".join(path), kind, fmt, cls(d), local, str(local != cls(d)))] += 1
    hits_rows = sum(n for k, n in rows.items())
    reconcile = {"runner_guard_file_hits": int(sum(runner_file_hits.values())),
                 "runner_walk_row_hits": int(sum(row_hits.values())),
                 "attributed_tokens": int(hits_rows), "expected": EXPECT_HITS}
    ok = reconcile["runner_guard_file_hits"] == reconcile["runner_walk_row_hits"] == hits_rows == EXPECT_HITS
    cols = ("key_path", "field_kind", "token_format", "literal_class", "market_local_class", "local_differs")
    out_rows = [dict(zip(cols, k), count=n) for k, n in sorted(rows.items())]
    report = {
        "diag": "row28_guard_diag_v3", "runner_sha256": RUNNER_V10_SHA256,
        "status": "RECONCILED" if ok else "FLAG: does not reconcile",
        "file": "s2_build/nbm_market_new/nbm_pit_corpus_rows.jsonl",
        "rows_scanned": n_rows, "rows_with_hits": rows_with_hits, "rows_market_without_tz": unknown_market,
        "runner_hit_classes": dict(runner_file_hits),
        "reconcile": reconcile,
        "at_or_after_2026_05_27": at_or_after_0527,
        "month_bucket_min": month_tag(min(months)) if months else None,
        "month_bucket_max": month_tag(max(months)) if months else None,
        "row_date_fields_by_name": list(ROW_DATE_FIELDS),
        "object_instant_fields_by_name": list(OBJECT_INSTANT_FIELDS),
        "rows": out_rows,
    }
    text = json.dumps(report, indent=1, sort_keys=True) + "\n"
    if rv.guard_text(text) or rv._n_dated(text):
        text = json.dumps({"diag": "row28_guard_diag_v3", "status": "WITHHELD (output held a dated string)",
                           "reconcile": reconcile}) + "\n"
    lines = [",".join(cols + ("count",))] + [
        ",".join(str(r.get(k, "")).replace(",", ";") for k in cols + ("count",)) for r in out_rows]
    csv_text = "\n".join(lines) + "\n"
    if rv.guard_text(csv_text) or rv._n_dated(csv_text):
        csv_text = ",".join(cols + ("count",)) + "\n"
    out_json.write_text(text, encoding="utf-8", newline="\n")
    out_csv.write_text(csv_text, encoding="utf-8", newline="\n")
    return 0 if ok else 9


if __name__ == "__main__":
    sys.exit(main())
