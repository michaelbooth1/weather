from decimal import Decimal as D
from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.inference import cluster_intervals, paired_cells


def test_three_dates_two_markets_are_underpowered_and_deterministic():
    cells = {(str(d), str(m)): float(d+m) for d in range(3) for m in range(2)}
    a = cluster_intervals(cells, replicates=200)
    b = cluster_intervals(dict(reversed(list(cells.items()))), replicates=200)
    assert canonical_bytes(a) == canonical_bytes(b)
    assert all(x["status"] == "UNDERPOWERED" for x in a.values())
    assert all(x["interval_level"] == .9 and len(x["interval"]) == 2 for x in a.values())


def test_market_shock_survives_date_replication():
    cells = {(str(d), str(m)): 100.0 * (m >= 5) for d in range(12) for m in range(10)}
    r = cluster_intervals(cells, replicates=500)
    assert r["date"]["interval"] == [50, 50]
    assert r["date_x_market"]["interval"][0] < 50 < r["date_x_market"]["interval"][1]
    assert r["date_x_market"]["status"] == "OK"
    thin = cluster_intervals({k: v for k, v in cells.items() if k[1] == "0"}, replicates=100)
    assert thin["date"]["status"] == "OK"
    assert thin["date_x_market"]["status"] == "UNDERPOWERED"


def test_excluded_or_unmatched_band_drops_entire_market_date():
    def r(cid, value, status="COVERED"):
        return dict(date="2020-01-01", market_id="a", condition_id=cid, active_seconds=60,
                    covered_seconds=60, status=status, modeled_net_k1=value)
    cells, dropped = paired_cells([r("a", D(2)), r("b", None, "PARTIAL")], [r("a", D(1)), r("b", D(0))])
    assert cells == {} and dropped == [("2020-01-01", "a")]
    cells, dropped = paired_cells([r("a", D(2)), r("b", D(3))], [r("a", D(1)), r("b", D(1))])
    assert cells == {("2020-01-01", "a"): 3} and not dropped


def test_empty_and_sparse_panels_do_not_impute_zero():
    empty = cluster_intervals({}, replicates=100)
    assert empty["date_x_market"]["estimate"] is None
    sparse = cluster_intervals({("d1", "m1"): 2., ("d2", "m2"): 2.}, replicates=500)
    assert sparse["date_x_market"]["empty_replicates"] > 0
    assert sparse["date_x_market"]["interval"] == [2, 2]
