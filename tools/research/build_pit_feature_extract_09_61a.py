"""Build the frozen -09-61a decision-10 feature matrix from the staged PIT corpus.

WHY THIS EXISTS. The staged corpus is 1.6 M rows / 163 MB across two roots on the PRODUCTION
host only; `data/` is gitignored and the workstation holds no copy. The frozen protocol uses a
single lead and a single daily window, so the entire feature set the executor needs is
58 dates x 12 markets x 12 fields = 8,352 numbers. This collapses the corpus to that, exactly as
`docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.json` specifies, so the mission can run
where the analysis code lives.

WHAT IT DELIBERATELY DOES NOT DO.

  * It does NOT standardize. The protocol requires B-only market scaling recomputed inside every
    chronological fit and bootstrap refit; precomputing it here would leak C into the scaling and
    silently break the design. Raw aggregates only.
  * It does NOT emit any outcome, settlement, market probability, or incumbent probability. This
    file is features and nothing else, so building it cannot spend campaign decision 10.
  * It does NOT include leads 2-7, hours outside 07:00-20:00, or any date after 2026-07-30.

WHAT THE EXECUTOR MUST STILL CHECK. The `lead_days=1` rows come from the previous-runs endpoint's
`fixed_lead_day_offset` contract; this script asserts the provenance columns but does NOT
independently verify the T-1 00:00 issue hour, because the staged rows carry no issue-time column.
Confirm that against the protocol's `issue_time_rule` before fitting.

    venv\\Scripts\\python.exe tools\\research\\build_pit_feature_extract_09_61a.py

Writes the extract plus a manifest carrying its SHA-256 and full support counts.
"""
from __future__ import annotations

import csv
import glob
import hashlib
import json
import math
import os
from collections import defaultdict

PROTOCOL_SHA256 = "336150be1a62e88c2fe40ccd7b77916576d08981617ebbff1e01195007cfc146"

# Both roots are required. Reading only the back root yields 37 of 58 sealed dates, and because
# B is June it leaves 7 usable fit dates instead of 23 -- with coverage still reading 100%.
ROOTS = [
    (r"C:\tmp\pit-refetch-2026-08-10-front", "*_previous_runs_long_front.csv"),
    (r"C:\tmp\pit-refetch-2026-08-10", "*_previous_runs_long.csv"),
]

# Frozen aggregations, verbatim from the protocol's `mechanism.features`.
AGGREGATIONS = {
    "temperature_2m": "max",
    "cloud_cover": "mean",
    "shortwave_radiation": "sum",
    "wind_speed_10m": "mean",
    "cape": "max",
    "direct_radiation": "sum",
    "diffuse_radiation": "sum",
    "wind_gusts_10m": "max",
    "precipitation_probability": "max",
    "precipitation": "sum",
    "vapour_pressure_deficit": "max",
    "et0_fao_evapotranspiration": "sum",
}
FIELDS = list(AGGREGATIONS)
HOURS = list(range(7, 21))                      # 07:00-20:00 inclusive
DMIN, DMAX = "2026-06-03", "2026-07-30"         # sealed window; 2026-07-31 is the regime boundary
LEAD = "1"

OUT_DIR = os.path.join("scratch", "runs", "pit-feature-extract-2026-09-61a")
OUT_CSV = os.path.join(OUT_DIR, "pit-lead1-daily-features.csv")
OUT_MANIFEST = os.path.join(OUT_DIR, "manifest.json")


def main() -> int:
    hourly: dict[tuple[str, str, str], dict[int, float]] = defaultdict(dict)
    # Units are tracked per MARKET-field, not per field. temperature_2m arrives fahrenheit for the
    # 11 F markets and celsius for Toronto, so a field-keyed map would silently record whichever
    # market was read first. Every other field is Open-Meteo `native` and uniform.
    units: dict[tuple[str, str], set[str]] = defaultdict(set)
    seen_markets: set[str] = set()
    skipped_boundary = 0

    for root, pattern in ROOTS:
        paths = sorted(glob.glob(os.path.join(root, pattern)))
        if not paths:
            print("FAIL: no files matched %s in %s" % (pattern, root))
            return 2
        for path in paths:
            with open(path, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if (row["issue_time_basis"] != "fixed_lead_day_offset"
                            or row["source"] != "open_meteo_previous_runs"):
                        print("FAIL: provenance violation in %s" % path)
                        return 2
                    if row["lead_days"] != LEAD:
                        continue
                    field = row["field"]
                    if field not in AGGREGATIONS:
                        continue
                    stamp = row["target_datetime_local"]
                    date, hour = stamp[:10], int(stamp[11:13])
                    if date > DMAX:
                        skipped_boundary += 1
                        continue
                    if date < DMIN or hour not in HOURS:
                        continue
                    market = row["market"]
                    seen_markets.add(market)
                    value = float(row["value"])
                    if not math.isfinite(value):
                        print("FAIL: non-finite %s %s %s %02d" % (market, field, date, hour))
                        return 2
                    bucket = hourly[(market, date, field)]
                    if hour in bucket:
                        print("FAIL: duplicate %s %s %s %02d" % (market, field, date, hour))
                        return 2
                    bucket[hour] = value
                    units[(market, field)].add(row["unit"])

    markets = sorted(seen_markets)
    dates = sorted({d for (_, d, _) in hourly})
    expected_cells = len(markets) * len(dates) * len(FIELDS)
    if len(hourly) != expected_cells:
        print("FAIL: %d market-date-field cells, expected %d" % (len(hourly), expected_cells))
        return 2

    # A market whose unit changed between the two staging segments would corrupt within-market
    # standardization silently, so fail closed rather than record an ambiguous manifest.
    mixed = sorted(k for k, v in units.items() if len(v) != 1)
    if mixed:
        print("FAIL: %d market-field pairs carry more than one unit: %s" % (len(mixed), mixed[:5]))
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    written = 0
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["market", "target_date"] + FIELDS)
        for market in markets:
            for date in dates:
                values = []
                for field in FIELDS:
                    series = hourly[(market, date, field)]
                    if len(series) != len(HOURS):
                        print("FAIL: %s %s %s has %d of %d hours"
                              % (market, date, field, len(series), len(HOURS)))
                        return 2
                    ordered = [series[h] for h in HOURS]
                    how = AGGREGATIONS[field]
                    agg = max(ordered) if how == "max" else (
                        sum(ordered) / len(ordered) if how == "mean" else sum(ordered))
                    values.append(repr(round(agg, 10)))
                writer.writerow([market, date] + values)
                written += 1

    with open(OUT_CSV, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()

    manifest = {
        "artifact": "pit_lead1_daily_features_v1",
        "built_for": "-09-61a decision 10, frozen protocol",
        "protocol_sha256": PROTOCOL_SHA256,
        "extract_sha256": digest,
        "extract_rows": written,
        "markets": markets,
        "date_min": dates[0],
        "date_max": dates[-1],
        "dates": len(dates),
        "fields": FIELDS,
        "aggregations": AGGREGATIONS,
        "units_by_market_field": {"%s/%s" % k: sorted(v)[0] for k, v in sorted(units.items())},
        "temperature_unit_by_market": {
            m: sorted(units[(m, "temperature_2m")])[0] for m in markets},
        "unit_warning": "temperature_2m is fahrenheit in the 11 F markets and celsius in Toronto. "
                        "Within-market standardization makes that harmless for the fit, but the "
                        "protocol requires Celsius-equivalent conversion and pooling raw "
                        "temperature across markets would be catastrophic. Every other field is "
                        "Open-Meteo `native` and uniform across markets.",
        "valid_local_hours_inclusive": [HOURS[0], HOURS[-1]],
        "lead_days": int(LEAD),
        "issue_time_basis": "fixed_lead_day_offset",
        "source": "open_meteo_previous_runs",
        "hourly_values_consumed": len(hourly) * len(HOURS),
        "rows_past_boundary_excluded": skipped_boundary,
        "standardized": False,
        "standardization_note": "Raw aggregates only. B-only market scaling must be recomputed "
                                "inside every chronological fit and bootstrap refit per the "
                                "protocol; precomputing it here would leak C into the scaling.",
        "contains_outcomes_or_market_prices": False,
    }
    with open(OUT_MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print("markets            : %d" % len(markets))
    print("sealed dates       : %d  (%s -> %s)" % (len(dates), dates[0], dates[-1]))
    print("hourly values used : %d" % (len(hourly) * len(HOURS)))
    print("rows excluded past %s: %d" % (DMAX, skipped_boundary))
    print("extract rows       : %d  (%d markets x %d dates)" % (written, len(markets), len(dates)))
    print("extract sha256     : %s" % digest)
    print("wrote              : %s" % OUT_CSV)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
