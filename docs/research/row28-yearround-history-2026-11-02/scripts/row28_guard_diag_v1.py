"""Row 28 guard localisation diagnostic v1 (lane L59). COUNTS ONLY; no date value, no hash of a dated string.

Started by launcher v6 like a stage (the launcher passes --roots --out-json --out-csv --expect-sha --stage; --stage is
only a launcher label here). It imports runner v6 as a module (sha256-checked; main() is not run) and uses the
runner's own context and guard: load_context, set_guard_centres, output_guard_scan, guard_file, _scan, _walk and the
runner's mask objects. Nothing is copied. To localise, the runner's _scan is wrapped: the original is called and its
result returned unchanged. For each call, the caller frame of the runner's _walk gives the key path, the field and
the weight.

Scope:
  (1) the a3 stage-end guard scope, reproduced with the runner's own output_guard_scan (every file under the run root
      except those that predate a3, and minus a3's own walk.json / walk.csv / logs / receipt). This is the 276.
  (2) the context counts of a3's walk.json (158) and walk.csv (66).

Every dated token (an ISO date >= 2026-01-01, as the guard counts it) is reported only as a class tag:
  PRE2026, Y26_PRE0527, SEALED (05-27..07-30), GAP (07-31..09-28), EMBARGO (>= 09-29).
File names and key-path segments that hold a date carry the class tag in place of the date.

Rows count tokens per (scope, file template, key-path template, field template, runner category, status, field
context, token format, literal class, market-local class, local differs, is an arm centre label). The fields mean:
  - status: hit, or allowed by context or mask.
  - token format: date-only, ISO-with-Z, ISO-with-offset or other.
  - local class: for an ISO instant in a records file, the class of its market-local date (otherwise n/a).
The output is checked with the runner's guard_text and _n_dated before it is written.
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

RUNNER = Path(r"C:\wt\L59row28\docs\research\row28-yearround-history-2026-11-02\scripts\row28_run_v6.py")
RUNNER_V6_SHA256 = "fd4464744e729cb8ed27eb68aa998d528ac4d2bfe5075d9837b9b02b7e2cae1b"
A3_DIR = Path(r"C:\t\L59\row28\run\s1_controls_a3")
RECORDS_DIR = Path(r"C:\t\L59\row28\run\records")
EXPECT_STAGE_END = 276
EXPECT_WALK_JSON = 158
EXPECT_WALK_CSV = 66
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


def main():
    a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    out_json, out_csv = Path(a["--out-json"]), Path(a["--out-csv"])
    if hashlib.sha256(RUNNER.read_bytes()).hexdigest() != RUNNER_V6_SHA256:
        out_json.write_text(json.dumps({"status": "REFUSED", "reason": "runner sha256 differs"}) + "\n")
        return 3
    spec = importlib.util.spec_from_file_location("row28_run_v6", RUNNER)
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)
    import pandas as pd

    cfg = json.loads(Path(a["--roots"]).read_text(encoding="utf-8"))
    ctx = rv.load_context(cfg)
    rv.set_guard_centres(ctx.centres, cfg["records_root"])
    rv.check_calibrated_weights(ctx.repo)
    markets = sorted(set(rv.US10) | set(rv.DESCRIPTIVE_MARKETS), key=len, reverse=True)
    centres = set(rv._GUARD_CENTRES)

    def templ(s):
        return rv._GUARD_RS.sub(lambda m: cls(m.group(1)), str(s))

    def market_of(name):
        if name.startswith("records_"):
            for m in markets:
                if name.startswith(f"records_{m}_"):
                    return m
        return None

    state = {"scope": None, "file": None, "market": None}
    rows = Counter()
    orig_scan = rv._scan

    def record_tokens(text, field, path, wt, status, ctxname, is_key, only_hits_n=None):
        raw = str(text)
        for m in rv._GUARD_RS.finditer(raw):
            d = m.group(1)
            if d < rv.GUARD_FROM:
                continue
            tail = _TAIL.match(raw, m.end())
            if is_key:
                fmt = "key"
            elif tail is None:
                fmt = "date-only"
            elif tail.group(1) == "Z":
                fmt = "ISO-with-Z"
            elif tail.group(1):
                fmt = "ISO-with-offset"
            else:
                fmt = "other"
            lit = cls(d)
            local, differs = "n/a", "n/a"
            if fmt in ("ISO-with-Z", "ISO-with-offset") and state["market"] in ctx.tz:
                try:
                    ts = pd.Timestamp(raw[m.start():tail.end()])
                    local = cls(ts.tz_convert(ctx.tz[state["market"]]).date().isoformat())
                    differs = str(local != lit)
                except Exception:
                    local, differs = "unparsed", "n/a"
            rows[(state["scope"], state["file"], "/".join(templ(x) for x in path) or "<root>",
                  templ(field) if field is not None else "", status, ctxname, fmt, lit, local, differs,
                  str(d in centres))] += wt

    def traced_scan(text, field=None, in_s7=False, parent=None, is_key=False):
        c, allowed = orig_scan(text, field, in_s7, parent, is_key)
        if rv._n_dated(str(text)):
            fr = sys._getframe(1)
            loc = fr.f_locals if fr.f_code is rv._walk.__code__ else {}
            path = tuple(loc.get("path", ("<text>",)))
            wt = loc.get("wt", 1)
            if is_key:
                ctxname = ("centre-keyed parent" if parent in rv.CENTRE_KEYED_PARENTS else
                           "record-keyed parent" if parent in rv.RECORD_KEYED_PARENTS else "unscoped key")
            elif rv.centre_set_for(field) is not None:
                ctxname = "centre field"
            elif in_s7 and field in rv.S7_CONSTANT_FIELDS:
                ctxname = "s7 constant field"
            elif field in rv.RECORD_FILE_FIELDS:
                ctxname = "record file field"
            elif path == tuple(rv.RULING_V4_RECORDS_GENERATED_AT):
                ctxname = "records generated_at"
            else:
                ctxname = "unscoped"
            if not c:
                record_tokens(text, field, path, wt, "allowed", ctxname, is_key)
            else:
                t = str(text).replace(rv.GUARD_MASK_TOKEN, "")
                if rv._RECORD_PATH_RE is not None:
                    t = rv._RECORD_PATH_RE.sub("[records_root]/records_[centre].pkl.gz", t)
                if sum(1 for m in rv._GUARD_RS.finditer(t) if m.group(1) >= rv.GUARD_FROM) != sum(c.values()):
                    rows[(state["scope"], state["file"], "/".join(templ(x) for x in path), "", "TRACE-MISMATCH",
                          ctxname, "", "", "", "", "")] += wt
                record_tokens(t, field, path, wt, "hit", ctxname, is_key)
                masked = sum(1 for m in rv._GUARD_RS.finditer(str(text)) if m.group(1) >= rv.GUARD_FROM) - \
                    sum(c.values())
                if masked:
                    rows[(state["scope"], state["file"], "/".join(templ(x) for x in path) or "<root>",
                          templ(field) if field is not None else "", "allowed", "mask", "masked token", "", "", "",
                          "")] += masked * wt
        return c, allowed

    # (1) the stage-end scope, exactly as the runner computed it at a3's end.
    a3_excl = [A3_DIR / n for n in ("walk.json", "walk.csv", "walker.stdout", "walker.stderr", "receipt.json")]
    a3_files = {os.path.normcase(str(p)) for p in A3_DIR.iterdir()} | \
        {os.path.normcase(str(p)) for p in RECORDS_DIR.iterdir()}
    snapshot = {}
    for dirpath, _, filenames in os.walk(rv.OUT_ROOT_PIN):
        for n in filenames:
            p = os.path.normcase(os.path.join(dirpath, n))
            if p not in a3_files:
                st = os.stat(p)
                snapshot[p] = (st.st_size, st.st_mtime_ns)
    og = rv.output_guard_scan(snapshot, a3_excl)   # unwrapped: the runner's own number
    per_file = Counter()
    extra = Counter()
    rv._scan = traced_scan
    try:
        state["scope"] = "stage_end"
        for dirpath, _, filenames in os.walk(rv.OUT_ROOT_PIN):
            for n in sorted(filenames):
                p = os.path.join(dirpath, n)
                key = os.path.normcase(p)
                if key in snapshot or key in {os.path.normcase(str(x)) for x in a3_excl}:
                    continue
                state["file"] = templ(os.path.relpath(p, rv.OUT_ROOT_PIN))
                state["market"] = market_of(n)
                c = rv.guard_file(p)
                if rv.guard_text(p):
                    c["file_name"] += 1
                for k in ("byte_crosscheck", "unscannable", "file_name"):
                    if c.get(k):
                        extra[(state["file"], k)] += c[k]
                per_file[state["file"]] += sum(c.values())
        for scope, name in (("walk_json", "walk.json"), ("walk_csv", "walk.csv")):
            state["scope"], state["file"], state["market"] = scope, "s1_controls_a3/" + name, None
            rv.guard_file(A3_DIR / name)
    finally:
        rv._scan = orig_scan

    def total(scope, statuses):
        return sum(n for k, n in rows.items() if k[0] == scope and k[4] in statuses)

    hit_rows = total("stage_end", ("hit",)) + sum(extra.values())
    mismatches = sum(n for k, n in rows.items() if k[4] == "TRACE-MISMATCH")
    stop_c = sum(n for k, n in rows.items() if k[4] == "hit" and
                 (k[8] if k[8] in ("PRE2026", "Y26_PRE0527", "SEALED", "GAP", "EMBARGO") else k[7])
                 in ("SEALED", "GAP", "EMBARGO"))
    reconcile = {
        "stage_end_runner_hits_total": og["hits_total"],
        "stage_end_rows_hits": hit_rows,
        "stage_end_expected": EXPECT_STAGE_END,
        "walk_json_tokens": total("walk_json", ("hit", "allowed")),
        "walk_json_expected": EXPECT_WALK_JSON,
        "walk_csv_tokens": total("walk_csv", ("hit", "allowed")),
        "walk_csv_expected": EXPECT_WALK_CSV,
        "trace_mismatches": mismatches,
    }
    ok = (og["hits_total"] == hit_rows == EXPECT_STAGE_END and reconcile["walk_json_tokens"] == EXPECT_WALK_JSON
          and reconcile["walk_csv_tokens"] == EXPECT_WALK_CSV and not mismatches)
    cols = ("scope", "file", "key_path", "field", "status", "field_context", "token_format", "literal_class",
            "local_class", "local_differs", "is_arm_centre_label")
    out_rows = [dict(zip(cols, k), count=n) for k, n in sorted(rows.items())]
    out_rows += [{"scope": "stage_end", "file": f, "key_path": "<file>", "status": "hit", "field_context": k,
                  "count": n} for (f, k), n in sorted(extra.items())]
    report = {
        "diag": "row28_guard_diag_v1", "runner_sha256": RUNNER_V6_SHA256,
        "status": "RECONCILED" if ok else "FLAG: does not reconcile",
        "stop_rule_c_hits_local_sealed_gap_embargo": stop_c,
        "reconcile": reconcile,
        "stage_end_files_scanned": og["files_scanned"],
        "stage_end_files_with_hits": sum(1 for v in per_file.values() if v),
        "stage_end_hits_by_file_template": dict(sorted(Counter(
            {f: n for f, n in per_file.items() if n}).items())),
        "rows": out_rows,
    }
    text = json.dumps(report, indent=1, sort_keys=True) + "\n"
    if rv.guard_text(text) or rv._n_dated(text):
        text = json.dumps({"diag": "row28_guard_diag_v1", "status": "WITHHELD (output held a dated string)",
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
