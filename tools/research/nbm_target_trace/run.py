"""Serial, cached public-bulletin trace; run through workstation_heavy.ps1.

T0 records NOAA's token convention, T1 calls the unchanged parser, T2 diagnoses
the frozen export. Nothing here imports a scorer or constructs probabilities.
"""
from __future__ import annotations

from weather.projection_io import open_projection, projection_source

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from weather.paths import repo_path
from weather.sources.nbm_probabilistic_tmax import (
    _parse_issue_time, _slot_index_for_target, _parse_pair_row,
    parse_nbp_station_tmax,
)

DATES = ("2026-09-17", "2026-09-18", "2026-09-19")
HOURS = (1, 7, 13, 19)
STATES = dict(atlanta="GA", austin="TX", chicago="IL", dallas="TX",
              denver="CO", houston="TX", miami="FL", nyc="NY", seattle="WA",
              **{"los-angeles": "CA", "san-francisco": "CA"})
DOC = "https://vlab.noaa.gov/web/mdl/nbm-textcard-v5.0"
SNAPSHOT_HASH = "249a9de0da7b41cb8a2ce1f07944e4007c585f601028b73acaae0dd4bd141c2e"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def stations():
    registry = json.loads(repo_path("config/locations.json").read_text())
    result = {r["id"]: dict(station=r["settlement"]["station_id"],
                           timezone=r["timezone"], network=STATES[r["id"]] + "_ASOS")
              for r in registry["locations"] if r["id"] in STATES}
    assert len(result) == 11
    return result


def fetch(cache, name, url):
    """One serial bounded fetch per URL; completed cached objects never refetch."""
    path = cache / name
    meta = cache / (name + ".json")
    if path.exists():
        record = json.loads(meta.read_text())
        if record["url"] != url or sha(path) != record["sha256"]:
            raise ValueError("cache identity/hash mismatch")
        return path, record
    cache.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    with requests.get(url, timeout=(20, 60), stream=True) as r:
        r.raise_for_status()
        partial = path.with_suffix(path.suffix + ".partial")
        size = 0
        with partial.open("xb") as f:
            for chunk in r.iter_content(1024 * 1024):
                size += len(chunk)
                if size > 128 * 1024 * 1024:
                    raise ValueError("public file exceeds 128 MiB bound")
                f.write(chunk)
        partial.rename(path)
    record = dict(url=url, sha256=sha(path), bytes=size, started_at_utc=started,
                  retrieved_at_utc=datetime.now(timezone.utc).isoformat())
    write_json(meta, record)
    print(json.dumps(dict(fetched=name, bytes=size)), flush=True)
    time.sleep(1)
    return path, record


def station_blocks(path, wanted):
    header = re.compile(r"^\s*([A-Z0-9]{3,5})\s+NBM\s+V\S+\s+NBP\s+GUIDANCE")
    result = {}
    current = None
    with path.open(encoding="ascii") as f:
        for line in f:
            match = header.search(line)
            if match:
                current = match[1] if match[1] in wanted else None
                if current:
                    if current in result:
                        raise ValueError("duplicate station block")
                    result[current] = []
            if current:
                result[current].append(line.rstrip("\r\n"))
    if set(result) != set(wanted):
        raise ValueError(f"stations missing: {set(wanted) - set(result)}")
    return {k: "\n".join(v).rstrip() + "\n" for k, v in result.items()}


def token_grid(block):
    """Preserve literal group/token positions, including a lone leading 12Z."""
    lines = block.splitlines()
    issued = _parse_issue_time(lines[0])
    if issued is None:
        raise ValueError("missing issue")
    rows = {line[:6].strip(): line[6:].split("|") for line in lines[1:]}
    result = []
    for group, segment in enumerate(rows["FHR"]):
        hours = [int(x) for x in re.findall(r"\d+", segment)]
        utc = [int(x) for x in re.findall(r"\d+", rows["UTC"][group])]
        if len(hours) != len(utc):
            raise ValueError("FHR/UTC shape mismatch")
        for token, (fhr, hour) in enumerate(zip(hours, utc)):
            valid = issued + timedelta(hours=fhr)
            if valid.hour != hour or hour not in (0, 12):
                raise ValueError("unsupported TXN valid hour")
            kind = "maximum" if hour == 0 else "minimum"
            period_date = (valid - timedelta(days=1)).date() if hour == 0 else valid.date()
            values = {}
            for code in ("TXNP1", "TXNP2", "TXNP5", "TXNP7", "TXNP9", "TXNMN", "TXNSD"):
                nums = re.findall(r"-?\d+", rows[code][group]) if code in rows else []
                values[code] = int(nums[token]) if token < len(nums) else None
            result.append(dict(group=group, token=token, forecast_hour=fhr,
                               valid_time_utc=valid.isoformat(), period_kind=kind,
                               period_date=period_date.isoformat(), **values))
    return issued, rows, result


def observations(cache, start, end):
    result, manifests = {}, []
    for market, spec in stations().items():
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        params = dict(network=spec["network"], stations=spec["station"][1:],
                      year1=a.year, month1=a.month, day1=a.day,
                      year2=b.year, month2=b.month, day2=b.day, na="blank", format="csv")
        url = "https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py?" + urlencode(params)
        path, record = fetch(cache, f"iem-{market}-{start}-{end}.csv", url)
        manifests.append(record)
        for row in csv.DictReader(io.StringIO(path.read_text())):
            if row.get("station") != spec["station"][1:]:
                raise ValueError("IEM station mismatch")
            result[(market, row["day"])] = dict(max_f=number(row.get("max_temp_f")),
                                                min_f=number(row.get("min_temp_f")))
    return result, manifests


def number(x):
    try:
        import math
        n = float(x)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def t0(root, cache=None):
    out = root / "t0"
    if out.exists():
        raise ValueError("T0 already retained")
    specs = stations()
    tokens, manifests = [], []
    for day in DATES:
        for hour in HOURS:
            cycle = f"{day.replace('-', '')}T{hour:02d}Z"
            url = (f"https://noaa-nbm-grib2-pds.s3.amazonaws.com/blend.{day.replace('-', '')}"
                   f"/{hour:02d}/text/blend_nbptx.t{hour:02d}z")
            path, record = fetch(cache or root / "cache", f"nbp-{cycle}.txt", url)
            blocks = station_blocks(path, {s["station"] for s in specs.values()})
            manifests.append(record)
            for market, spec in specs.items():
                block = blocks[spec["station"]]
                issued, rows, grid = token_grid(block)
                assert issued == datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00")
                block_path = out / "blocks" / f"{cycle}-{spec['station']}.txt"
                block_path.parent.mkdir(parents=True, exist_ok=True)
                block_path.write_text(block, encoding="ascii", newline="\n")
                for cell in grid:
                    tokens.append(dict(cycle=cycle, market=market, station=spec["station"],
                                       issued_at=issued.isoformat(), fhr_row="|".join(rows["FHR"]),
                                       **cell))
    obs, obs_manifest = observations(cache or root / "cache", "2026-09-15", "2026-09-20")
    for cell in tokens:
        observation = obs.get((cell["market"], cell["period_date"]), {})
        cell.update(observed_max_f=observation.get("max_f"), observed_min_f=observation.get("min_f"))
    write_csv(out / "tokens.csv", tokens)
    write_json(out / "receipt.json", dict(stage="T0", noaa_description=DOC, manifests=manifests,
              observations=obs_manifest, tokens=len(tokens), blocks=132,
              completed_at_utc=datetime.now(timezone.utc).isoformat()))
    print(json.dumps(dict(stage="T0", tokens=len(tokens), blocks=132)), flush=True)


def t1(root, cache=None):
    json.loads((root / "t0/receipt.json").read_text())
    out = root / "t1"
    if out.exists():
        raise ValueError("T1 already retained")
    obs, manifests = observations(cache or root / "cache", "2026-09-15", "2026-09-20")
    picks = []
    for path in sorted((root / "t0/blocks").glob("*.txt")):
        block = path.read_text()
        issued, rows, grid = token_grid(block)
        station = path.stem.split("-")[-1]
        market, spec = next((m, s) for m, s in stations().items() if s["station"] == station)
        local_day = issued.astimezone(ZoneInfo(spec["timezone"])).date()
        fhr_line = next(line for line in block.splitlines() if line[:6].strip() == "FHR")
        for offset in (-1, 0, 1):
            target = local_day + timedelta(days=offset)
            payload = parse_nbp_station_tmax(block, station, target)
            group = _slot_index_for_target(_parse_pair_row(fhr_line), issued, target)
            cell = next((c for c in grid if c["group"] == group and c["token"] == 0), {})
            right = cell.get("period_kind") == "maximum" and cell.get("period_date") == target.isoformat()
            observation = obs.get((market, target.isoformat()), {})
            picks.append(dict(cycle=path.stem.split("-")[0], hour=issued.hour, market=market,
                              station=station, local_issue_date=local_day.isoformat(),
                              target_offset=offset, target_date=target.isoformat(),
                              chosen_group=group, chosen_token=0 if group is not None else None,
                              valid_time_utc=cell.get("valid_time_utc"),
                              period_kind=cell.get("period_kind"), period_date=cell.get("period_date"),
                              classification="unavailable" if not payload["available"] else "right" if right else "wrong",
                              p50=payload.get("percentiles", {}).get("50"),
                              observed_max_f=observation.get("max_f"), observed_min_f=observation.get("min_f"),
                              reason=payload.get("reason")))
    from collections import Counter
    counts = Counter((r["hour"], r["target_offset"], r["classification"]) for r in picks)
    summary = [dict(hour=k[0], offset=k[1], classification=k[2], n=v) for k, v in sorted(counts.items())]
    write_csv(out / "picks.csv", picks)
    write_json(out / "receipt.json", dict(stage="T1", counts=summary, observations=manifests,
               parser_sha256=sha(repo_path("src/weather/sources/nbm_probabilistic_tmax.py")),
               completed_at_utc=datetime.now(timezone.utc).isoformat()))
    print(json.dumps(summary), flush=True)


def recover_quantiles(features):
    """Only exact algebra on retained fields; never interpolate a missing p50."""
    q = {p: number(features.get(f"nbm_prob_tmax_p{p}")) for p in (10, 25, 50, 75, 90)}
    recovered = []
    for low, high, width in ((10, 90, "p10_p90_spread"), (25, 75, "iqr")):
        spread = number(features.get("nbm_prob_tmax_" + width))
        if q[low] is None and q[high] is not None and spread is not None:
            q[low] = q[high] - spread
            recovered.append(low)
    lower = max((q[p] for p in (10, 25) if q[p] is not None), default=None)
    upper = min((q[p] for p in (75, 90) if q[p] is not None), default=None)
    return q, recovered, lower, upper


def t2(root, input_path, raw, cache=None):
    json.loads((root / "t1/receipt.json").read_text())
    out = root / "t2"
    if projection_source(out).exists():
        raise ValueError("T2 already retained")
    if sha(input_path / "snapshots.jsonl") != SNAPSHOT_HASH:
        raise ValueError("79a snapshot hash mismatch")
    audit = json.loads((input_path / "extraction_audit.json").read_text())
    folders = {(r["market"], r["date"]): r["folder"] for r in audit if r.get("promotion_countable")}
    reasons, raw_hashes = {}, {}
    for folder in sorted(set(folders.values())):
        path = projection_source(raw / folder / "features_long.csv")
        raw_hashes[folder] = sha(path)
        with open_projection(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                reasons[(folder, row["snapshot_id"])] = row.get("guidance_impossible_features", "")
    print(json.dumps(dict(stage="T2", reason_files=len(raw_hashes))), flush=True)
    obs, manifest = observations(cache or root / "cache", "2026-08-01", "2026-09-20")
    # Retained T0 cycle signatures can corroborate a period, never prove a
    # snapshot's missing issue time or uniquely recover its deleted median.
    signatures = {}
    for path in sorted((root / "t0/blocks").glob("*.txt")):
        block = path.read_text()
        issued, _, grid = token_grid(block)
        station = path.stem.split("-")[-1]
        for cell in grid:
            if cell["token"] != 0:
                continue
            target = (datetime.fromisoformat(cell["valid_time_utc"]) - timedelta(days=1)).date().isoformat()
            signatures.setdefault((station, target), []).append((issued, cell))
    result = []
    with open_projection(input_path / "snapshots.jsonl") as f:
        for line in f:
            s = json.loads(line)
            if s["market"] == "toronto":
                continue
            features = s["features"]
            reason_key = (folders[(s["market"], s["date"])], s["snapshot_id"])
            dropped = reasons.get(reason_key, "")
            q, recovered, lower, upper = recover_quantiles(features)
            daily = obs.get((s["market"], s["date"]), {})
            next_date = (date.fromisoformat(s["date"]) + timedelta(days=1)).isoformat()
            next_min = obs.get((s["market"], next_date), {}).get("min_f")
            p50 = q[50]
            settled = s["settlement_high"]
            # Secondary diagnostic: representative-high is p90 for ordinary
            # positive complete TXN sets; do not label this a recovered p50.
            floor = number(features.get("guidance_physical_floor"))
            gap = number(features.get("nbm_prob_tmax_floor_gap"))
            representative = floor + gap if floor is not None and gap is not None else None
            cap = datetime.fromisoformat(s["captured_at_utc"])
            matches = []
            for issued, cell in signatures.get((s["station"], s["date"]), []):
                if not timedelta(0) <= cap - issued <= timedelta(hours=26):
                    continue
                constraints = [features.get("nbm_prob_tmax_stddev") == cell["TXNSD"],
                               features.get("nbm_prob_tmax_iqr") == cell["TXNP7"] - cell["TXNP2"],
                               features.get("nbm_prob_tmax_p10_p90_spread") == cell["TXNP9"] - cell["TXNP1"]]
                constraints.extend(q[p] == cell[code] for p, code in
                                   ((10, "TXNP1"), (25, "TXNP2"), (50, "TXNP5"), (75, "TXNP7"), (90, "TXNP9"))
                                   if q[p] is not None)
                if representative is not None:
                    constraints.append(abs(representative - cell["TXNP9"]) < 1e-8)
                if all(constraints):
                    matches.append(cell["period_kind"])
            result.append(dict(market=s["market"], date=s["date"], stratum=s["stratum"], hour=s["hour"],
                 snapshot_id=s["snapshot_id"], station=s["station"],
                 reason_present=reason_key in reasons, dropped_nbm="nbm_prob_tmax_" in dropped,
                 dropped_p50="nbm_prob_tmax_p50" in dropped,
                 p50=p50, p10=q[10], p25=q[25], p75=q[75], p90=q[90],
                 recovered_p10=10 in recovered, recovered_p25=25 in recovered,
                 p50_lower_bound=lower, p50_upper_bound=upper,
                 settled_max_f=settled, observed_min_f=daily.get("min_f"), next_min_f=next_min,
                 p50_minus_max=p50 - settled if p50 is not None else None,
                 p50_minus_min=p50 - daily["min_f"] if p50 is not None and daily.get("min_f") is not None else None,
                 p50_minus_next_min=p50 - next_min if p50 is not None and next_min is not None else None,
                 upper_minus_max=upper - settled if upper is not None else None,
                 representative_f=representative,
                 representative_minus_max=representative - settled if representative is not None else None,
                 representative_minus_next_min=representative - next_min if representative is not None and next_min is not None else None,
                 signature_match="none" if not matches else "|".join(sorted(set(matches))),
                 signature_match_count=len(matches)))
    import pandas as pd
    frame = pd.DataFrame(result)

    def summarize(g):
        def quantiles(key):
            values = g[key].dropna()
            return dict(n=len(values), **{f"q{int(p * 100)}": float(values.quantile(p)) if len(values) else None
                                         for p in (.1, .25, .5, .75, .9)})
        return dict(n=len(g), date_clusters=g.date.nunique(), market_clusters=g.market.nunique(),
                    market_days=len(g[["market", "date"]].drop_duplicates()),
                    dropped_p50=int(g.dropped_p50.sum()), retained_p50=int(g.p50.notna().sum()),
                    missing_reason_rows=int((~g.reason_present).sum()),
                    recovered_p10=int(g.recovered_p10.sum()), recovered_p25=int(g.recovered_p25.sum()),
                    signatures=g.signature_match.value_counts().to_dict(),
                    **{k: quantiles(k) for k in ("p50_minus_max", "p50_minus_min", "p50_minus_next_min",
                                                 "upper_minus_max", "representative_minus_max",
                                                 "representative_minus_next_min")})
    tables = {}
    for name, selected in (("all_us", frame), ("dropped", frame[frame.dropped_nbm]),
                           ("complete_or_other", frame[~frame.dropped_nbm])):
        tables[name] = dict(overall=summarize(selected))
        for keys in (["hour"], ["market"], ["stratum", "hour"], ["stratum", "market"]):
            rows = []
            for key, group in selected.groupby(keys, observed=True):
                key = key if isinstance(key, tuple) else (key,)
                rows.append({**dict(zip(keys, key)), **summarize(group)})
            tables[name]["by_" + "_".join(keys)] = rows
    write_csv(out / "diagnostic_rows.csv", result)
    write_json(out / "summary.json", tables)
    write_json(out / "receipt.json", dict(stage="T2", snapshot_sha256=SNAPSHOT_HASH,
              source_feature_hashes=raw_hashes, observation_manifests=manifest,
              diagnostic_rows_sha256=sha(out / "diagnostic_rows.csv"),
              completed_at_utc=datetime.now(timezone.utc).isoformat(),
              inference="finite-export census; no interval, score, candidate, or population-effect estimate",
              p50_limit="Deleted p50 is not algebraically recoverable from p75-IQR and p90-spread."))
    print(json.dumps(tables["dropped"]["overall"]), flush=True)


def artifact_audit(root):
    """Read tracked bundles and their existing LFS objects; never write artifacts."""
    import pickle
    import subprocess
    json.loads((root / "t2/receipt.json").read_text())
    git_common = Path(subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], text=True).strip())
    paths = subprocess.check_output(["git", "ls-files", "artifacts"], text=True).splitlines()
    records = []
    def selectors(obj, prefix=""):
        found = {}
        if isinstance(obj, dict):
            for key, value in obj.items():
                path = f"{prefix}/{key}"
                if key in ("feature_names", "numeric_feature_names", "feature_columns", "features"):
                    if isinstance(value, (list, tuple)) and all(isinstance(x, str) for x in value):
                        found[path] = list(value)
                if isinstance(value, (dict, list, tuple)):
                    found.update(selectors(value, path))
        elif isinstance(obj, (list, tuple)):
            for i, value in enumerate(obj):
                if isinstance(value, dict):
                    found.update(selectors(value, f"{prefix}/{i}"))
        return found
    for name in paths:
        path = repo_path(name)
        if path.suffix not in (".pkl", ".json"):
            continue
        actual = path
        if path.suffix == ".pkl":
            with path.open("rb") as f:
                header = f.read(200)
            if header.startswith(b"version https://git-lfs.github.com/spec/v1"):
                oid = re.search(rb"oid sha256:([0-9a-f]{64})", header)[1].decode()
                actual = git_common / "lfs/objects" / oid[:2] / oid[2:4] / oid
                if not actual.exists() or sha(actual) != oid:
                    raise ValueError(f"missing or invalid LFS object: {name}")
            with actual.open("rb") as f:
                obj = pickle.load(f)
        else:
            obj = json.loads(path.read_text(encoding="utf-8-sig"))
        sets = selectors(obj)
        names = sorted({x for values in sets.values() for x in values})
        matches = [x for x in names if x.startswith("nbm_prob_tmax_")]
        records.append(dict(path=name, sha256=sha(actual), selector_sets=sets,
                            nbm_selected=matches))
        del obj
    write_json(root / "artifact_audit.json", dict(records=records,
        tracked_current_release_pointer=any(p.endswith("current_release.json") for p in paths),
        selecting_nbm=[r["path"] for r in records if r["nbm_selected"]],
        scope="tracked artifact selectors only; no access to production's ignored release state"))
    print(json.dumps(dict(artifacts=len(records), selecting_nbm=[r["path"] for r in records if r["nbm_selected"]])), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("t0", "t1", "t2", "artifact_audit", "publish"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cache", type=Path, help="reuse the hash-verified public download cache")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--raw", type=Path)
    args = parser.parse_args()
    if os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") != "1":
        parser.error("use workstation_heavy.ps1")
    root = args.root.resolve()
    if "scratch" not in root.parts:
        parser.error("outputs must use ignored scratch")
    if args.cache is not None and "scratch" not in args.cache.resolve().parts:
        parser.error("cache must use ignored scratch")
    if args.stage == "publish":
        from .publish import publish
        publish(root)
    elif args.stage == "t2":
        if args.input is None or args.raw is None:
            parser.error("T2 requires --input and --raw")
        t2(root, args.input, args.raw, args.cache)
    elif args.stage in ("t0", "t1"):
        globals()[args.stage](root, args.cache)
    else:
        globals()[args.stage](root)


if __name__ == "__main__":
    main()
