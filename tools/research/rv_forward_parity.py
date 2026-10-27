"""Lane L13: parity check of the R-V forward MOS/NBE recorder against a later IEM archive refetch.

Design: docs/research/rv-capture-proposal-2026-10-27.md section 5. Inputs only: the refetch uses the
recorder's allowlisted client (mos.py, the 11 R0 ICAOs, GFS/NAM/NBE, never 2026-09-30..10-15) and the
comparison reads only the forward run files and the archive CSVs. No outcome, price or label is read.

``refetch`` takes one declared window of runtime days [start, end] (at most 10 days, ended at least
one day before now) and writes ``<ICAO>_<MODEL>.csv`` plus ``manifest.json`` (sha256 per file).

``compare`` reports, for every forward run of a used runtime inside the window:
* selected-value parity: the day-max field at ftime D+1 00Z must be exactly equal (NaN == NaN);
* row parity (reported): the run's rows are byte-identical in the archive;
* coverage: forward runs missing from the archive (gating) and archive runs the recorder never saw
  (reported gaps);
* ``mos_x`` parity at every (station, local day, hour 13-16): the forward rule (lag AND first_seen)
  against the training rule on the archive; where both select the same runs, |d| <= 1e-9 (gating);
  where a late first_seen made the forward rule pick an older run, the row is counted, not failed;
* the share of forward runs first seen more than 15 min after runtime + lag, i.e. missed by the
  recorder's request at the due time (reported; above 5 % is escalated).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
from pathlib import Path

try:
    from tools.research import rv_forward_recorder as r
except ImportError:  # run as a script from tools/research
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import rv_forward_recorder as r

UTC = dt.timezone.utc
MOS_X_TOL = 1e-9
LATE_ESCALATE = 0.05
LATE_SLACK = dt.timedelta(minutes=15)  # the recorder asks at the due time; one retry later is late


def _days(start, end):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def refetch(out_dir, start, end, client, now):
    """Archive refetch of runtimes [start 00:00Z, end 23:59Z] for every station and model."""
    if end < start or (end - start).days >= 10:
        raise r.AllowlistError("parity window must be 1..10 days")
    if dt.datetime(end.year, end.month, end.day, tzinfo=UTC) + dt.timedelta(days=2) > now:
        raise r.AllowlistError("parity window must have ended at least one day before the refetch")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sts = dt.datetime(start.year, start.month, start.day, tzinfo=UTC)
    ets = dt.datetime(end.year, end.month, end.day, 23, 59, tzinfo=UTC)
    files = {}
    for st in r.STATIONS:
        for model in r.MODELS:
            _, _, text = client.fetch(r.request_params(st, model, sts, ets))
            data = text.encode("utf-8")
            path = out / f"{st}_{model}.csv"
            path.write_bytes(data)
            files[path.name] = hashlib.sha256(data).hexdigest()
    manifest = {"url": r.URL, "window_runtime_days": [start.isoformat(), end.isoformat()],
                "fetched_utc": r._iso(now), "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def load_archive(archive_dir):
    """{(station, model): {runtime: run bytes}} from a refetch directory, sha-checked."""
    root = Path(archive_dir)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    out = {}
    for name, sha in sorted(manifest["files"].items()):
        data = (root / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != sha:
            raise RuntimeError(f"{name} does not match the manifest")
        st, model = name[:-4].split("_")
        out[(st, model)] = r.split_runs(data.decode("utf-8"), st, model)
    return out, manifest


def _same(a, b):
    return (math.isnan(a) and math.isnan(b)) or a == b


def compare(forward_dir, archive_dir, start, end, stations=tuple(r.STATIONS)):
    store = r.Store(forward_dir)
    archive, manifest = load_archive(archive_dir)
    days = list(_days(start, end))
    rep = {"window_runtime_days": [start.isoformat(), end.isoformat()], "archive_manifest_sha256":
           hashlib.sha256((Path(archive_dir) / "manifest.json").read_bytes()).hexdigest(),
           "selected_compared": 0, "selected_mismatches": [], "rows_identical": 0, "rows_differ": [],
           "missing_in_archive": [], "missing_in_forward": [], "late_first_seen": [], "forward_runs": 0,
           "mos_x_compared": 0, "mos_x_mismatches": [], "mos_x_late_fallback": 0, "mos_x_both_nan": 0}
    for st in stations:
        fwd_tables, fwd_seen = store.tables(st)
        arc_tables = {}
        for model, (field, hours, lag) in r.MODELS.items():
            runs = archive.get((st, model), {})
            for runtime, data in runs.items():
                for ftime, v in r.run_values(data, model).items():
                    arc_tables.setdefault(model, {})[(runtime, ftime)] = v
            for day in days:
                ftime = dt.datetime(day.year, day.month, day.day, tzinfo=UTC) + dt.timedelta(days=1)
                for hour in hours:
                    runtime = dt.datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
                    key = (st, model, runtime)
                    tag = f"{st}/{model}/{r._iso(runtime)}"
                    rec = store.runs.get(key)
                    if rec is None:
                        if runtime in runs:
                            rep["missing_in_forward"].append(tag)
                        continue
                    rep["forward_runs"] += 1
                    seen = r._parse_iso(rec["first_seen_utc"])
                    if seen > runtime + dt.timedelta(seconds=lag) + LATE_SLACK:
                        rep["late_first_seen"].append(tag)
                    if runtime not in runs:
                        rep["missing_in_archive"].append(tag)
                        continue
                    if (store.out / rec["path"]).read_bytes() == runs[runtime]:
                        rep["rows_identical"] += 1
                    else:
                        rep["rows_differ"].append(tag)
                    a = fwd_tables.get(model, {}).get((runtime, ftime), float("nan"))
                    b = arc_tables.get(model, {}).get((runtime, ftime), float("nan"))
                    rep["selected_compared"] += 1
                    if not _same(a, b):
                        rep["selected_mismatches"].append({"run": tag, "forward": a, "archive": b})
        for day in days:
            for hour in r.HOURS:
                f = r.entry(fwd_tables, st, day, hour, first_seen=fwd_seen)
                h = r.entry(arc_tables, st, day, hour)
                if f["runs"] != h["runs"]:
                    rep["mos_x_late_fallback"] += 1
                    continue
                if math.isnan(f["mos_x"]) and math.isnan(h["mos_x"]):
                    rep["mos_x_both_nan"] += 1
                    continue
                rep["mos_x_compared"] += 1
                if not (math.isfinite(f["mos_x"]) and math.isfinite(h["mos_x"])
                        and abs(f["mos_x"] - h["mos_x"]) <= MOS_X_TOL):
                    rep["mos_x_mismatches"].append({"station": st, "day": day.isoformat(), "hour": hour,
                                                    "forward": f["mos_x"], "archive": h["mos_x"]})
    rep["late_share"] = len(rep["late_first_seen"]) / max(rep["forward_runs"], 1)
    rep["late_escalate"] = rep["late_share"] > LATE_ESCALATE
    rep["pass"] = bool(rep["selected_compared"] > 0 and not rep["selected_mismatches"]
                       and not rep["missing_in_archive"] and not rep["mos_x_mismatches"])
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("refetch", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--start", required=True, type=dt.date.fromisoformat)
        p.add_argument("--end", required=True, type=dt.date.fromisoformat)
        p.add_argument("--archive", default=r"C:\t\l13\rv_parity\archive")
    sub.choices["compare"].add_argument("--forward", default=r"C:\t\l13\rv_forward")
    sub.choices["compare"].add_argument("--report", default=r"C:\t\l13\rv_parity\parity_report.json")
    args = ap.parse_args(argv)
    if args.cmd == "refetch":
        clock = lambda: dt.datetime.now(UTC)  # noqa: E731
        client = r.Client(r.LiteSession().get, clock)
        print(json.dumps(refetch(args.archive, args.start, args.end, client, clock()), indent=1))
        return 0
    rep = compare(args.forward, args.archive, args.start, args.end)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(rep, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("pass", "selected_compared", "mos_x_compared", "late_share",
                                          "late_escalate")}, indent=1))
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
