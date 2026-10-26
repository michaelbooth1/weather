"""Lane L11 rung R-O: GEFS member-mean centre shift s = a + b (G - N) at 07-12 (rule_rn.md, NAMING.md).

Guards: the (a, b) grid keeps b in [0, 1] and contains (0, 0), ties go to the smallest |a| + b, the feature G uses
only perturbed members whose every needed step is available by the h:00 local cutoff and whose valid local date is
the target date, G is None below 25 members, a missing G gives a zero shift for every pair, and the parity scan
never opens an event folder dated outside 2026-07-30..2026-09-29 nor compares a snapshot outside h07-h12.
"""
import importlib
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

UTC = timezone.utc


def test_grid_and_tie_rule():
    assert prm.RO_B[0] == 0.0 and prm.RO_B[-1] == 1.0 and len(prm.RO_A) == 61 and len(prm.RO_PAIRS) == 61 * 21
    assert prm.RO_PAIRS[prm.RO_ZERO] == (0.0, 0.0)
    loss = np.ones(len(prm.RO_PAIRS))
    assert prm.ro_pick(loss) == (0.0, 0.0)
    for pair in ((0.2, 0.1), (0.1, 0.2), (-0.3, 0.0), (0.3, 0.0)):
        loss[prm.RO_PAIRS.index(pair)] = 0.5
    assert prm.ro_pick(loss) == (-0.3, 0.0)  # |a|+b ties at 0.3: smaller b, then smaller |a|, then smaller a


def test_missing_diff_gives_zero_shifts():
    assert not prm.ro_row_shifts(None).any()
    s = prm.ro_row_shifts(2.0)
    assert s[prm.RO_PAIRS.index((0.5, 0.25))] == pytest.approx(1.0)


def _table(n_members, late_member=None, avail=datetime(2024, 8, 10, 10, 0, tzinfo=UTC)):
    cycle = datetime(2024, 8, 10, 6, tzinfo=UTC)
    rows = []
    for k in range(1, n_members + 1):
        member = f"gep{k:02d}"
        for fh in (6, 9, 12, 15, 18, 21, 24):
            a = avail + timedelta(hours=3) if member == late_member and fh == 24 else avail
            rows.append((member, cycle + timedelta(hours=fh), a, 80.0 + k + fh / 100.0))
    rows += [("gec00", cycle + timedelta(hours=fh), avail, 200.0) for fh in (6, 9, 12, 15, 18, 21, 24)]
    return {("KNYC", "2024-08-10"): rows}


def test_feature_member_mean_with_local_date_and_pit():
    # New York, 2024-08-10, 07:00 EDT = 11:00Z. Steps valid on the local date: f006..f018 (12Z..00Z is 20:00 EDT);
    # f021 (03Z next day = 23:00 EDT) is also the local date; f024 (06Z = 02:00 EDT next day) is not.
    g = prm.ro_gefs_value(_table(30), "KNYC", "2024-08-10", 7, "America/New_York")
    want = np.mean([80.0 + k + 0.21 for k in range(1, 31)])  # control ignored, max over the local-date steps
    assert g == pytest.approx(want)
    # a member whose f024 is late is unaffected (f024 is not on the local date)
    assert prm.ro_gefs_value(_table(30, "gep01"), "KNYC", "2024-08-10", 7, "America/New_York") == pytest.approx(want)


def test_feature_needs_25_members_and_availability():
    assert prm.ro_gefs_value(_table(25), "KNYC", "2024-08-10", 7, "America/New_York") is not None
    assert prm.ro_gefs_value(_table(24), "KNYC", "2024-08-10", 7, "America/New_York") is None
    late = datetime(2024, 8, 10, 11, 1, tzinfo=UTC)  # one minute after 07:00 EDT
    assert prm.ro_gefs_value(_table(30, avail=late), "KNYC", "2024-08-10", 7, "America/New_York") is None
    assert prm.ro_gefs_value(_table(30, avail=late), "KNYC", "2024-08-10", 8, "America/New_York") is not None
    assert prm.ro_gefs_value(_table(30), "KMIA", "2024-08-10", 7, "America/New_York") is None


def test_kelvin_conversion():
    assert prm.ro_kelvin_to_f(273.15) == pytest.approx(32.0)
    assert prm.ro_kelvin_to_f(373.15) == pytest.approx(212.0)


def test_slug_date_and_parity_stats():
    import datetime as dt

    assert prm.ro_slug_date("highest-temperature-in-los-angeles-on-september-29-2026") == \
        ("los-angeles", dt.date(2026, 9, 29))
    assert prm.ro_slug_date("highest-temperature-in-nyc-on-smarch-1-2026") is None
    pairs = [("nyc", f"2026-08-{d:02d}", 80.0 + d + 0.5, 80.0 + d) for d in range(1, 11)]
    res = prm.ro_parity_stats(pairs)
    assert res["mean_diff"] == pytest.approx(0.5) and res["pearson_r_cell_means"] == pytest.approx(1.0)
    assert res["pass"] and not prm.ro_parity_stats([(m, d, o + 1.5, t) for m, d, o, t in pairs])["pass"]


def test_parity_reads_only_window_and_hours(tmp_path):
    import json

    cycle = datetime(2026, 8, 10, 6, tzinfo=UTC)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    with open(corpus / "gefs_member_rows.jsonl", "w", encoding="utf-8") as fh:
        for k in range(0, 31):
            member = "gec00" if k == 0 else f"gep{k:02d}"
            for step in (6, 9, 12, 15, 18, 21, 24):
                fh.write(json.dumps({"kind": "message", "status": "ok", "date": "2026-08-10", "member": member,
                                     "valid_utc": (cycle + timedelta(hours=step)).isoformat(),
                                     "available_utc": "2026-08-10T10:00:00+00:00",
                                     "points": {"nyc": {"bilinear_k": 300.0 + k / 10.0}}}) + "\n")
    inputs = tmp_path / "inputs"
    for slug, local, utc in (("highest-temperature-in-nyc-on-august-10-2026", "2026-08-10T08:05:00-04:00",
                              "2026-08-10T12:05:00+00:00"),
                             ("highest-temperature-in-nyc-on-september-30-2026", None, None)):
        (inputs / slug).mkdir(parents=True)
        lines = []
        if local:
            for loc, u in ((local, utc), ("2026-08-10T13:05:00-04:00", "2026-08-10T17:05:00+00:00")):
                lines.append(json.dumps({"captured_at_local": loc, "captured_at_utc": u, "target_date": "2026-08-10",
                                         "model_identity": {"market_id": "nyc"},
                                         "sources": {"global_ensemble": {"data": {
                                             "day_member_high_p10": 80.0, "day_member_high_p90": 81.0,
                                             "day_max_native": 80.33}}}}))
        else:
            lines.append("not json: must never be opened")
        (inputs / slug / "replay_inputs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = prm.rung_o_parity(inputs_root=inputs, gefs_corpus=corpus, out_dir=tmp_path / "out")
    assert res["counts"]["snapshots_compared"] == 1 and res["counts"]["skipped_date_outside"] == 1
    assert res["parity"]["control"]["n"] == 1
