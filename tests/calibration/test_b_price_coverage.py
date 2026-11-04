"""B-1 coverage counts (host side) and the end-to-end verdict against b_scorer's own recompute.

Guards: master ruling R19 (2026-11-01) and B-1 Clarification 4
(docs/research/b-coverage-2026-11-02/b1-clarification-4-coverage-counts-2026-11-02.md): the host tool
(tools/research/b_price_coverage.py, R19 option b; nothing under src names it but the schema family) writes
per-snapshot integers only (rows, rows with an admitted capture-time price) for in-cut rows, records whether its
re-projection reproduces the bundle's snapshots_long sha256, writes create-only; the predicate is the layout
builder's finite check plus [0, 1]; the workstation verdict built from the counts equals
``b_scorer.market_coverage`` over a NaN-elsewhere price frame (nan, inf, -0.1, 1.2, empty, after-cut rows, D-1
capture, bad bands, Denver, hours 6/7/16/17, 0.90 kept).
"""
import csv
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tools.research import b_price_coverage as bpc
from weather.calibration import mg2_input_allowlist as allow
from weather.calibration import mg2_input_export as mx

from tests.calibration.test_mg2_input_export import LONG_HOST, make_host
from tests.host_guard import import_or_skip_on_capture_host

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
D = date(2026, 10, 30)
NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
BANDS = [("lte", 79, 79)] + [("eq", lo, lo + 1) for lo in range(80, 90, 2)] + [("gte", 90, 90)]
PROBS = [0.0, 0.1, 0.2, 0.4, 0.2, 0.1, 0.0]
PRICE = "0.4375"  # a distinctive admitted price that must never reach a sidecar
SCORED = [m for m in allow.MARKETS if m != "denver"]
# (market, local hour) -> (band index, bad value): one unpriced band makes the snapshot unpriced.
BAD = {("atlanta", 9): (2, "nan"), ("austin", 12): (3, "inf"), ("chicago", 16): (0, "-0.1"),
       ("dallas", 7): (6, "1.2"), ("houston", 9): (1, "")}


def _local(market, day, hour, minute=7):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(mx.TZ[market]))


def _rows(market, local, prices, probs=PROBS):
    slug = allow.slug_for(market, D)
    sid, utc = local.strftime("%Y%m%dT%H%M%S%z"), local.astimezone(timezone.utc).isoformat()
    return [{"snapshot_id": sid, "captured_at_utc": utc, "captured_at_local": local.isoformat(), "event_slug": slug,
             "model_version": "v-test", "range_label": f"{kind}{lo}", "bin_kind": kind, "bin_value_c": lo,
             "bin_value_hi_c": hi if kind == "eq" else "", "model_probability": p, "market_yes": price,
             "best_bid": "0.3", "best_ask": "0.6"}
            for (kind, lo, hi), p, price in zip(BANDS, probs, prices)]


def _market_rows(market, bad):
    """D's snapshots_long: D-1 evening, 06, 07, 09, 10 (bad bands), 12, 16, 17 local, and one after the cut."""
    priced = [PRICE] * len(BANDS)
    rows = _rows(market, _local(market, D - timedelta(days=1), 20), priced)  # capture_not_on_target_date
    for hour in (6, 7, 9, 12, 16, 17):
        prices = list(priced)
        if hour in (6, 17) or market == "denver":
            prices[4] = "nan"  # outside 07-16 or Denver: never counted, so never lowers the share
        if (market, hour) in bad:
            index, value = bad[(market, hour)]
            prices[index] = value
        if (market, hour) == ("miami", 12):
            prices[0], prices[6] = "0", "1"  # the [0, 1] edges are admitted
        rows += _rows(market, _local(market, D, hour), prices)
    rows += _rows(market, _local(market, D, 10), priced, probs=[0.1] * len(BANDS))  # bad bands: excluded
    late = (allow.export_cut_utc(D) + timedelta(hours=1)).astimezone(ZoneInfo(mx.TZ[market]))
    rows += _rows(market, late, ["nan"] * len(BANDS))  # after the cut: neither exported nor counted
    return rows


def make_coverage_host(tmp_path, bad=BAD):
    data = make_host(tmp_path, target=D)
    for market in allow.MARKETS:
        path = data / "snapshots" / allow.slug_for(market, D) / bpc.SNAPSHOTS_LONG
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(LONG_HOST), lineterminator="\n")
        writer.writeheader()
        writer.writerows(_market_rows(market, bad))
        path.write_bytes(out.getvalue().encode("utf-8"))
    quiet = time.time() - 2 * 3600
    for path in data.rglob("*"):
        if path.is_file():
            os.utime(path, (quiet, quiet))
    return data


def export_and_count(tmp_path, bad=BAD):
    data = make_coverage_host(tmp_path, bad)
    out = tmp_path / "out"
    mx.export(day=D, data_root=data, out=out, now=NOW)
    sidecar = bpc.count_date(day=D, data_root=data, out=out, now=NOW)
    return data, out, sidecar


# ----------------------------------------------------------------------------- predicate and shape

VALUES = ["0", "1", "0.5", " 0.25 ", "1e-3", "", " ", "nan", "NaN", "inf", "-inf", "-0.1", "1.2", "1.0000001",
          "-0", "abc", None, "0x1", "True"]


def test_predicate_is_the_builders_finite_check_within_unit_interval():
    mi = import_or_skip_on_capture_host("weather.calibration.mg2_inputs")
    for value in VALUES:
        finite = mi.finite(value)
        expected = finite if finite is not None and 0 <= finite <= 1 else None
        assert bpc.capture_price(value) == expected, value
    assert bpc.capture_price(True) is None and bpc.capture_price(float("nan")) is None
    assert bpc.capture_price(0.0) == 0.0 and bpc.capture_price(1) == 1.0


def test_sidecar_is_integers_only_and_reproduces_the_bundle(tmp_path):
    data, out, sidecar = export_and_count(tmp_path)
    target, sums = bpc.coverage_paths(out, D)
    text = target.read_text(encoding="utf-8")
    assert PRICE not in text and "market_yes" not in text
    assert json.loads(text) == sidecar
    assert sidecar["schema"] == bpc.SCHEMA and sidecar["counts_only"] is True and sidecar["match"] is True
    assert sums.read_text(encoding="ascii") == f"{hashlib.sha256(target.read_bytes()).hexdigest()}  {target.name}\n"
    assert set(sidecar["counts"]) == set(allow.MARKETS)
    for market, snaps in sidecar["counts"].items():
        assert len(snaps) == 8  # D-1 evening, 06, 07, 09, 10, 12, 16, 17; the after-cut capture is not counted
        for pair in snaps.values():
            assert isinstance(pair, list) and len(pair) == 2 and all(type(v) is int for v in pair)
            assert pair[0] == len(BANDS)
        source = sidecar["sources"][market]
        assert source["match"] and source["projected_sha256"] == source["bundle_sha256"]
        assert source["rows_after_cut_or_untimed"] == len(BANDS)
        assert source["rows_in_cut"] == 8 * len(BANDS)
    atlanta = sidecar["counts"]["atlanta"][_local("atlanta", D, 9).strftime("%Y%m%dT%H%M%S%z")]
    assert atlanta == [len(BANDS), len(BANDS) - 1]
    miami = sidecar["counts"]["miami"][_local("miami", D, 12).strftime("%Y%m%dT%H%M%S%z")]
    assert miami == [len(BANDS), len(BANDS)]

    def leaves(value, path=""):
        if isinstance(value, dict):
            for k, v in value.items():
                yield from leaves(v, f"{path}/{k}")
        elif isinstance(value, list):
            for v in value:
                yield from leaves(v, path)
        else:
            yield path, value

    for path, value in leaves(sidecar):
        assert not isinstance(value, float), path  # no price, no share: integers, strings and flags only


def test_sidecar_is_create_only_and_catch_up_skips_counted_dates(tmp_path):
    data, out, _ = export_and_count(tmp_path)
    assert bpc.pending_dates(out) == []
    with pytest.raises(bpc.CoverageRefused):
        bpc.count_date(day=D, data_root=data, out=out, now=NOW)
    with pytest.raises(bpc.CoverageRefused):
        bpc.count_date(day=date(2026, 10, 28), data_root=data, out=out, now=NOW)  # before B's D0


def test_a_changed_source_records_match_false(tmp_path):
    data = make_coverage_host(tmp_path)
    out = tmp_path / "out"
    mx.export(day=D, data_root=data, out=out, now=NOW)
    path = data / "snapshots" / allow.slug_for("nyc", D) / bpc.SNAPSHOTS_LONG
    extra = _rows("nyc", _local("nyc", D, 13), [PRICE] * len(BANDS))
    with open(path, "a", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=list(LONG_HOST), lineterminator="\n").writerows(extra)
    quiet = time.time() - 2 * 3600
    os.utime(path, (quiet, quiet))
    sidecar = bpc.count_date(day=D, data_root=data, out=out, now=NOW)
    assert sidecar["match"] is False and sidecar["sources"]["nyc"]["match"] is False
    assert all(s["match"] for m, s in sidecar["sources"].items() if m != "nyc")


def test_module_imports_only_stdlib_paths_allowlist_and_exporter():
    import ast
    import sys

    tree = ast.parse((ROOT / "tools/research/b_price_coverage.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(f"{node.module}.{a.name}" for a in node.names)
    third = {m for m in imported if m.split(".")[0] not in sys.stdlib_module_names and m != "__future__.annotations"}
    assert third == {"weather.paths", "weather.calibration.mg2_input_allowlist",
                     "weather.calibration.mg2_input_export"}


# Master ruling R19 option b: the counts tool lives in tools/research (R11 Head 1 pattern), never under src.
# The one carve-out is the schema family, whose registered version literal "b_price_coverage/1" and owner
# string name the host tool; it imports nothing.
SCHEMA_FAMILY = "src/weather/schema_families/b_coverage.py"


def test_nothing_under_src_imports_or_names_the_counts_tool():
    hits = [p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")
            if "b_price_coverage" in p.read_text(encoding="utf-8", errors="replace")]
    assert hits == [SCHEMA_FAMILY]
    family = (ROOT / SCHEMA_FAMILY).read_text(encoding="utf-8")
    assert "import" not in "".join(line for line in family.splitlines() if "b_price_coverage" in line)
    assert not (ROOT / "src/weather/calibration/b_price_coverage.py").exists()


def test_drop_list_stays_free_of_the_exporter_and_the_tool():
    text = (ROOT / "src/weather/calibration/b_drop_list.py").read_text(encoding="utf-8")
    for name in ("mg2_input_export", "mg2_inputs", "b_price_coverage", "tools.research"):
        assert name not in text, name


def test_wrapper_pins_root_and_src_and_proves_both_modules():
    code = (OPS / "b_price_coverage.ps1").read_text(encoding="utf-8")
    assert "$pinnedPath = '{0};{1}' -f $pinnedRoot.TrimEnd('\\'), $pinnedSrc.TrimEnd('\\')" in code
    assert ("'import tools.research.b_price_coverage as b, weather.calibration.mg2_input_export as m; '"
            in code)
    assert "$toolFull.StartsWith($pinnedTool," in code
    assert "$exporterFull.StartsWith($pinnedSrc," in code
    assert "[IO.DriveInfo]::new([IO.Path]::GetPathRoot($outRoot))" in code
    assert "$null -eq $memory -or $null -eq $memory.commit_percent" in code
    assert code.count("$env:PYTHONPATH = $pinnedPath") == 2


# ----------------------------------------------------------------------------- end to end

class FakeParser:
    parser_version = 2
    identity = {"head": "fake", "module_sha256": "a" * 64}

    def parse(self, blob, sha256, targets):
        return None, [{"available": False, "reason": "fixture", "parser_version": "v2"} for _ in targets]

    def close(self):
        pass


def _scorer_recompute(b_scorer, data, snaps, bands):
    """``b_scorer.market_coverage`` over a price frame written the R19 way: capture_price, NaN elsewhere."""
    import numpy as np
    import pandas as pd

    cut = allow.export_cut_utc(D)
    keyed = {(r, k, float(lo)): i for r, k, lo, i in zip(bands.row_key, bands.kind, bands.low, bands.band_index)}
    rows = []
    for market in allow.MARKETS:
        path = data / "snapshots" / allow.slug_for(market, D) / bpc.SNAPSHOTS_LONG
        for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
            if mx.parse_time(row["captured_at_utc"]) > cut:
                continue
            key = (f"{market}|{row['snapshot_id']}", row["bin_kind"], float(row["bin_value_c"]))
            if key in keyed:
                price = bpc.capture_price(row["market_yes"])
                rows.append({"row_key": key[0], "band_index": keyed[key],
                             "p_market_yes": np.nan if price is None else price})
    market = pd.DataFrame(rows)
    assert len(market) == len(bands)
    return b_scorer.market_coverage(snaps, b_scorer.priced_snapshots(bands, market))[D.isoformat()]


@pytest.mark.parametrize("bad, expected_priced, dropped", [
    (BAD, 35, True),  # 35 / 40 = 0.875
    ({k: v for k, v in BAD.items() if k[0] != "houston"}, 36, False),  # 36 / 40 = 0.90 is kept
])
def test_verdict_from_counts_equals_b_scorers_recompute(tmp_path, bad, expected_priced, dropped):
    b_scorer = import_or_skip_on_capture_host("weather.calibration.b_scorer")
    mi = import_or_skip_on_capture_host("weather.calibration.mg2_inputs")
    from weather.calibration import b_drop_list as bdl
    import pandas as pd

    data, out, sidecar = export_and_count(tmp_path, bad)
    layout, verified = tmp_path / "layout", tmp_path / "inbox" / D.isoformat() / "verified"
    shutil.copytree(out / D.isoformat(), verified)  # the receiver's verified copy of the published bundle
    mi.build(bundle=verified, out=layout, day=D, parser=FakeParser())
    snaps = pd.read_parquet(layout / "inputs_snapshots.parquet")
    bands = pd.read_parquet(layout / "inputs_bands.parquet")
    hours = sorted(set(snaps.local_hour))
    assert hours == [6, 7, 9, 12, 16, 17]  # the D-1 capture and the bad-band snapshot are excluded
    assert len(snaps) == 11 * 6

    ledger, store = tmp_path / "ws" / "receipts.jsonl", tmp_path / "ws" / "store"
    logged = bdl.log(share_root=out, day=D, store=store, ledger=ledger)
    assert logged["kind"] == "log" and logged["match"] is True
    row = bdl.verdict(day=D, layout=layout, store=store, ledger=ledger)
    expected = _scorer_recompute(b_scorer, data, snaps, bands)
    assert {k: row[k] for k in ("snapshots", "priced", "share")} == expected
    assert expected["snapshots"] == 40 and expected["priced"] == expected_priced
    assert row["dropped"] is dropped
    assert not math.isnan(row["share"])


# ----------------------------------------------------------------------------- host wrapper

POWERSHELL = shutil.which("powershell.exe")


@pytest.mark.spawns
@pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell")
def test_wrapper_plan_touches_nothing_and_catches_up_by_default(tmp_path):
    root = tmp_path / "prod repo"
    for extra, tail in (([], ["--catch-up"]), (["-Date", "2026-10-30"], ["--date", "2026-10-30"])):
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                 str(OPS / "b_price_coverage.ps1"), "-ProductionRepoRoot", str(root), *extra,
                                 "-PlanOnly"], cwd=tmp_path, capture_output=True, text=True, timeout=120,
                                check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        plan = json.loads(result.stdout.strip().splitlines()[-1])
        assert plan["child_arguments"] == ["-P", "-B", "-m", "tools.research.b_price_coverage", "--data-root",
                                           str(root / "data"), "--out", str(root / "data" / "exports" / "mg2-inputs"),
                                           *tail]
        assert plan["coverage_root"] == str(root / "data" / "exports" / "mg2-inputs" / "_b_coverage")
    assert not root.exists()


def test_wrapper_uses_utc_memory_freshness_and_refuses_a_null_lease():
    code = "\n".join(line for line in (OPS / "b_price_coverage.ps1").read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("#"))
    assert "Get-WeatherMemoryGuardStatusAgeMinutes -Read $memoryRead" in code
    assert "last_write_time" not in code
    assert "-Workload 'b_price_coverage'" in code
    assert "if ($null -eq $lease) { throw 'REFUSED: shared workload lease is busy' }" in code
    assert "--coverage-counts" not in code
