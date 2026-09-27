from dataclasses import replace
from decimal import Decimal

import pytest
from scipy.stats import beta

from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import calibrate, cp_upper
from .fixtures.execution_pack import calibration_days


@pytest.mark.parametrize("n,x,m", [(1, 0, 1), (1440, 30, 12), (100000, 49999, 12), (10, 10, 2), (1000000, 0, 100)])
def test_exact_bisection_bracket_and_upward_rounding(n, x, m):
    bound = cp_upper(n, x, m)
    oracle = beta.ppf(1-.01/m, x+1, n-x) if x < n else 1
    assert bound["lower"]-2e-15 <= oracle <= bound["upper"]+2e-15
    assert bound["upper"]-bound["lower"] <= 1e-12
    assert Decimal(bound["rounded_upper"]) >= Decimal.from_float(bound["upper"])


def test_absent_city_uses_nonsparse_pool_with_same_bonferroni_quantile(tmp_path):
    bundles = calibration_days(tmp_path)
    result = calibrate(bundles, ["a", "absent"])
    assert result["cities"]["a"]["n"] == 1440
    assert result["cities"]["a"]["x"] == 30
    assert len(result["cities"]["a"]["dates"]) == 3
    assert result["cities"]["absent"]["bound_source"] == "pooled"
    assert result["cities"]["absent"]["bound"] == cp_upper(1440, 30, 2)
    assert result["hazard_per_minute"] == result["pooled"]["bound"]["rounded_upper"]
    assert float(result["hazard_per_minute"]) < .05


def test_sparse_pool_is_one_and_no_coverage_is_not_zero(tmp_path):
    bundles = calibration_days(tmp_path, minutes=2, occupied=1)
    result = calibrate(bundles, ["a", "absent"])
    assert result["pooled"]["n"] == 6 and result["pooled"]["x"] == 3
    assert result["hazard_per_minute"] == "1.000000000000"
    no_coverage = tuple(replace(b, records=tuple(r for r in b.records if r.kind != "coverage")) for b in bundles)
    assert calibrate(no_coverage, ["a"])["pooled"]["n"] == 0


def test_duplicates_conflicts_and_capture_minute_not_venue_minute(tmp_path):
    bundles = list(calibration_days(tmp_path, minutes=3, occupied=1))
    first = bundles[0]
    trade = next(r for r in first.records if r.kind == "trade")
    # Identical print captured again next minute cannot occupy a second minute.
    later = replace(trade, captured_at=trade.captured_at.replace(minute=1))
    bundles[0] = replace(first, records=tuple(sorted((*first.records, later), key=lambda r: r.captured_at)))
    assert calibrate(bundles, ["a"])["pooled"]["x"] == 3
    conflict = replace(later, payload={**dict(later.payload), "size": "999"})
    bundles[0] = replace(first, records=tuple(sorted((*first.records, conflict), key=lambda r: r.captured_at)))
    result = calibrate(bundles, ["a"])
    assert result["pooled"]["n"] == 7 and result["pooled"]["x"] == 2
    assert result["cities"]["a"]["exclusions"]["invalid_or_conflicting_trade"] == 2


def test_coverage_cannot_bridge_expiry_or_missing_descriptor(tmp_path):
    bundles = list(calibration_days(tmp_path, minutes=2, occupied=1))
    b = bundles[0]
    bundles[0] = replace(b, records=tuple(r for r in b.records if not (r.kind == "coverage" and r.captured_at.second == 30)))
    assert calibrate(bundles, ["a"])["pooled"]["n"] == 4
    bundles[0] = replace(b, records=tuple(r for r in b.records if r.kind != "descriptor"))
    assert calibrate(bundles, ["a"])["pooled"]["n"] == 4


def test_mixed_or_wrong_dates_refuse(tmp_path):
    bundles = calibration_days(tmp_path, minutes=1, occupied=0)
    with pytest.raises(BundleError, match="exact_three"):
        calibrate(bundles[:2], ["a"])
    b = bundles[0]
    with pytest.raises(BundleError, match="trade_only"):
        calibrate((replace(b, records=(*b.records, replace(b.records[0], kind="settlement"))), *bundles[1:]), ["a"])


def test_calibration_cli_hashes_create_only_and_unavailable_fallback(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    import json
    from maker_core.replay import pack_cli
    from maker_core.replay.__main__ import main
    from maker_core.replay.pack_io import write_json
    monkeypatch.setattr(pack_cli, "_now", lambda: datetime(2026, 9, 30, 12, tzinfo=timezone.utc))
    bundles = calibration_days(tmp_path, minutes=2, occupied=1)
    markets, output = tmp_path/"markets.json", tmp_path/"result.json"
    key = write_json(markets, ["a"])
    args = ["calibrate_hazard", "--quote-markets", str(markets), "--out", str(output)]
    for b in bundles:
        args += ["--bundle", str(tmp_path/b.day.isoformat())]
    assert main(args) == 0
    assert json.loads(output.read_bytes())["quote_inventory_sha256"] == key
    with pytest.raises(SystemExit):
        main(args)
    assert main(["calibrate_hazard", "--quote-markets", str(markets), "--out", str(tmp_path/"unavailable.json"),
                 "--bundle", str(tmp_path/"missing")]) == 0
    absent = json.loads((tmp_path/"unavailable.json").read_bytes())
    assert absent["hazard_per_minute"] == "1.000000000000"
    assert absent["binding_status"] == "INCOMPLETE_REFUSE_MANIFEST"
    stream = tmp_path/bundles[0].day.isoformat()/"records.jsonl"
    stream.write_bytes(stream.read_bytes()+b"\n")
    args[args.index(str(output))] = str(tmp_path/"tampered.json")
    with pytest.raises(SystemExit):
        main(args)
    assert not (tmp_path/"tampered.json").exists()
