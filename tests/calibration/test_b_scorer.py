"""Rule B-1 scorer: MG-1 receipt precondition, rule parse, estimand, keep/kill table and VOID conditions.

Guards: Rule B-1 (B_forward_test_design.md, b_rule_v1 block): sections 3 (10 markets, 45 dates, coverage
drop), 5 (Delta 07-16 on covered snapshots, date-clustered w_date 2,000 draws seed 20260921), 6 (PASS / FAIL /
INCONCLUSIVE, NOT-WORSE below +0.0027), 8 (VOID 1-7), 9 (MG-1 look receipt first, embargo, one look) and (a)
(positive-control receipt); MG-2 rule section 8 C7 (as-of-capture vectors only).
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather.reporting.scorecards import dev_scorecard as sc
from weather.reporting.scorecards import dev_scorecard_data as data

from tests.host_guard import import_or_skip_on_capture_host

b = import_or_skip_on_capture_host("weather.calibration.b_scorer")
mg2 = import_or_skip_on_capture_host("weather.calibration.mg2_composite")
l3 = import_or_skip_on_capture_host("weather.calibration.r0_ols_floor_challenger")

D0 = date(2026, 10, 28)
DATES = [(D0 + timedelta(days=i)).isoformat() for i in range(45)]
TODAY = date(2026, 12, 20)
FILLED = {"mg2_rule_sha256": "1" * 64, "mg2_binding_commit": "2" * 40, "mg2_release_binding_sha256": "3" * 64,
          "mg2_owner_decision_id": "OD-2026-10-27-mg2", "l6_coefficients_sha256": "4" * 64,
          "p3d_n_state_sha256": "5" * 64, "function_sha256": "6" * 64}


def _rule(tmp_path, fill=True, **over):
    fields = dict(b.RULE_CONSTANTS, d0=D0.isoformat(), d0_latest="2026-11-02")
    for key in b.BOUND_FIELDS:
        fields[key] = b.FILL
    if fill:
        fields.update(FILLED, b_scorer_sha256=b.module_sha256(), scorecard_code_sha256=sc.code_sha256())
    fields.update(over)
    body = "\n".join(f"{k}: {v}" for k, v in fields.items())
    path = tmp_path / "b1.md"
    path.write_text(f"# Rule B-1\n\n```{b.RULE_BLOCK}\n{body}\n```\n", encoding="utf-8")
    return path


def _receipt(tmp_path):
    path = tmp_path / "mg1_look_receipt.json"
    path.write_text('{"mg1": "look"}', encoding="utf-8")
    return path


# ----------------------------------------------------------------------------- precondition and rule

def test_the_look_refuses_first_without_mg1_look_receipt(tmp_path):
    for receipt in (None, tmp_path / "absent.json"):
        with pytest.raises(b.BRefused, match="MG-1's look receipt does not exist"):
            b.look_guard(rule=tmp_path / "no-rule.md", mg1_look_receipt=receipt, out=tmp_path, today=TODAY)
    empty = tmp_path / "empty.json"
    empty.write_bytes(b"")
    with pytest.raises(b.BRefused, match="MG-1's look receipt"):
        b.look(rule="x", mg2_rule="x", release_binding="x", layout_root="x", vectors="x", mg2_look="x",
               transfer="x", drop_list="x", control_receipt="x", mg1_look_receipt=empty, void_record="x",
               out=tmp_path, today=TODAY)


def test_unfilled_rule_open_window_and_second_look_refuse(tmp_path, monkeypatch):
    receipt = _receipt(tmp_path)
    with pytest.raises(b.BRefused, match="FILL@BINDING"):
        b.look_guard(rule=_rule(tmp_path, fill=False), mg1_look_receipt=receipt, out=tmp_path, today=TODAY)
    rule = _rule(tmp_path)
    monkeypatch.setattr(mg2, "reserved_end", lambda: (date(2026, 10, 15), date(2026, 11, 28)))
    with pytest.raises(b.BRefused, match="has not closed"):
        b.look_guard(rule=rule, mg1_look_receipt=receipt, out=tmp_path, today=date(2026, 11, 28))
    monkeypatch.setattr(mg2, "reserved_end", lambda: (date(2026, 10, 15), None))
    with pytest.raises(b.BRefused, match="has not closed"):
        b.look_guard(rule=rule, mg1_look_receipt=receipt, out=tmp_path, today=TODAY)
    monkeypatch.setattr(mg2, "reserved_end", lambda: (date(2026, 10, 15), date(2026, 11, 28)))
    assert b.look_guard(rule=rule, mg1_look_receipt=receipt, out=tmp_path, today=TODAY)[2] == TODAY
    (tmp_path / b.LOOK).write_text("{}", encoding="utf-8")
    with pytest.raises(b.BRefused, match="exactly one look"):
        b.look_guard(rule=rule, mg1_look_receipt=receipt, out=tmp_path, today=TODAY)


@pytest.mark.parametrize("key,value", [("n_dates", "60"), ("noninferiority_margin", "0.005"),
                                       ("markets", "atlanta,denver"), ("hours_primary", "00-16"),
                                       ("interval", "crossed"), ("min_surviving_dates", "30")])
def test_rule_values_must_equal_the_scorer_constants(tmp_path, key, value):
    with pytest.raises(b.BRefused, match="differ"):
        b.read_rule(_rule(tmp_path, **{key: value}))


def test_rule_block_must_be_single_and_complete(tmp_path):
    path = _rule(tmp_path)
    text = path.read_text(encoding="utf-8")
    path.write_text(text + text, encoding="utf-8")
    with pytest.raises(b.BRefused, match="exactly one"):
        b.read_rule(path)
    path.write_text(text.replace("d0_latest: 2026-11-02\n", ""), encoding="utf-8")
    with pytest.raises(b.BRefused, match="lacks"):
        b.read_rule(path)
    with pytest.raises(b.BRefused, match="after d0_latest"):
        b.read_rule(_rule(tmp_path, d0="2026-11-03"))


def test_population_constants_are_b1s():
    assert "denver" not in b.MARKETS and len(b.MARKETS) == 10
    assert (b.N_DATES, b.MARGIN, b.COVERAGE_MIN, b.MIN_SURVIVING, b.DRAWS, b.SEED) == (45, 0.0027, 0.90, 40, 2000,
                                                                                      20260921)
    assert (b.DRAWS, b.SEED) == (sc.DRAWS, sc.SEED)
    assert b.PRIMARY == ("07-16", 7, 16) and [g[0] for g in b.HOURS] == [f"h{h:02d}" for h in range(7, 17)]


# ----------------------------------------------------------------------------- fixture forward data

def _forward(seed=0, markets=b.MARKETS + ("denver",), dates=DATES, hours=(8, 14), better=0.25):
    rng = np.random.default_rng(seed)
    snaps, bands, labels, market, vec = [], [], [], [], []
    for d in dates:
        for m in markets:
            for h in hours:
                rk = f"{m}|{d}|{h}"
                snaps.append({"row_key": rk, "market": m, "date": d, "local_hour": h, "n_bands": 3,
                              "guidance_physical_floor": 60.0, "high_so_far": np.nan, "trusted_current_max": np.nan,
                              "captured_at_utc": f"{d}T{h:02d}:05:00Z"})
                for i, (kind, lo, hi) in enumerate((("lte", np.nan, 69.0), ("between", 70.0, 71.0),
                                                    ("gte", 72.0, np.nan))):
                    bands.append({"row_key": rk, "band_index": i, "kind": kind, "low": lo, "high": hi,
                                  "p_served": 1 / 3})
                win = int(rng.integers(0, 3))
                labels.append({"row_key": rk, "date": d, "market": m, "winner": win})
                q = rng.dirichlet([2, 2, 2])
                market += [{"row_key": rk, "band_index": i, "p_market_yes": float(q[i])} for i in range(3)]
                p = (1 - better) * q + better * np.eye(3)[win]
                vec += [{"row_key": rk, "band_index": i, "p": float(p[i])} for i in range(3)]
    return (pd.DataFrame(snaps), pd.DataFrame(bands), pd.DataFrame(labels), pd.DataFrame(market),
            pd.DataFrame(vec))


def _table(snaps, bands, labels, market):
    lay = data.Layout(snaps=snaps, bands=bands, labels=labels, market=market, manifest_sha256="0" * 64,
                      file_sha256={}, label_source="test")
    return sc.Table(lay, sorted(snaps.date.astype(str).unique()))


def test_excess_rows_is_score_rows_against_the_market_date_clustered():
    snaps, bands, labels, market, vec = _forward(dates=DATES[:12], markets=b.MARKETS[:4])
    table = _table(snaps, bands, labels, market)
    assert np.array_equal(table.w_date, l3._date_weights([k[0] for k in table.keys], sc.DRAWS, sc.SEED))
    p, cov, _ = b.arm(table, vec)
    assert cov.all()
    mine = b._row(b.excess_rows(table, p, cov), "07-16")
    ref = next(r for r in sc.score_rows(table, p, False, table.p_market, (b.PRIMARY,)) if r["market"] == "ALL")
    assert mine["delta"] == ref["model_minus_control_date_clustered"]
    assert mine["crossed"]["estimate"] == ref["model_minus_market"]["estimate"]
    assert mine["crossed"]["ci95"] == ref["model_minus_market"]["ci95"]


def test_excess_rows_score_only_snapshots_both_arms_cover():
    snaps, bands, labels, market, vec = _forward(dates=DATES[:10], markets=b.MARKETS[:3])
    table = _table(snaps, bands, labels, market)
    drop = set(snaps.row_key[::3])
    p, cov, reasons = b.arm(table, vec[~vec.row_key.isin(drop)])
    assert int((~cov).sum()) == len(drop) and reasons["absent"] == len(drop)
    row = b._row(b.excess_rows(table, p, cov), "07-16")
    assert row["n_snapshots"] == len(snaps) - len(drop)


# ----------------------------------------------------------------------------- keep/kill (section 6)

def _rows(primary, early=(-0.01, 0.0), late=(-0.01, 0.0)):
    def r(group, ci):
        return {"market": "ALL", "group": group, "delta": {"estimate": sum(ci) / 2, "ci95": list(ci)}}
    return [r("07-16", primary), r("07-12", early), r("13-16", late)]


@pytest.mark.parametrize("primary,early,late,verdict,label", [
    ((-0.004, -0.001), (-0.01, 0.0), (-0.01, 0.0), "PASS", "edge"),
    ((-0.004, -0.001), (0.001, 0.01), (-0.01, 0.0), "INCONCLUSIVE", "NOT-WORSE"),
    ((-0.004, -0.001), (-0.01, 0.0), (0.0005, 0.01), "INCONCLUSIVE", "NOT-WORSE"),
    ((0.0001, 0.004), (-0.01, 0.0), (-0.01, 0.0), "FAIL", "kill_edge_claim"),
    ((-0.002, 0.0026), (-0.01, 0.0), (-0.01, 0.0), "INCONCLUSIVE", "NOT-WORSE"),
    ((-0.002, 0.0027), (-0.01, 0.0), (-0.01, 0.0), "INCONCLUSIVE", None),
    ((-0.001, 0.0), (-0.01, 0.0), (-0.01, 0.0), "INCONCLUSIVE", "NOT-WORSE"),
    ((0.0, 0.004), (-0.01, 0.0), (-0.01, 0.0), "INCONCLUSIVE", None),
])
def test_keep_kill_table(primary, early, late, verdict, label):
    out = b.decide(_rows(primary, early, late))
    assert (out["verdict"], out["label"]) == (verdict, label)


# ----------------------------------------------------------------------------- VOID conditions (section 8)

def test_manifest_conditions_cover_missing_order_count_and_other_dates():
    rows = [(date.fromisoformat(d), True) for d in DATES]
    assert b.manifest_problems({"x": 1}, rows, DATES, D0) == []
    assert b.manifest_problems(None, "manifest missing", DATES, D0) == ["manifest missing"]
    extra = rows + [(D0 + timedelta(days=45), False)]
    assert "dates after the 45th countable date" in b.manifest_problems({}, extra, DATES, D0)
    gap = rows[:10] + [(D0 + timedelta(days=10), False)] + [(d + timedelta(days=1), c) for d, c in rows[10:]]
    assert "countable dates differ from MG-2's look date set" in b.manifest_problems({}, gap, DATES, D0)
    assert any("not 45" in p for p in b.manifest_problems({}, rows[:44], DATES, D0))
    early = [(D0 - timedelta(days=1), False)] + rows
    assert any("before D0" in p for p in b.manifest_problems({}, early, DATES, D0))


def test_control_receipt_must_pass_at_this_scorer(tmp_path):
    fields = {"b_scorer_sha256": b.module_sha256(), "scorecard_code_sha256": sc.code_sha256()}
    assert b.control_problems(None, fields) == ["no control receipt"]
    path = tmp_path / b.CONTROL
    good = {"schema": b.CONTROL_SCHEMA, "verdict": "PASS", **fields}
    path.write_text(json.dumps(good), encoding="utf-8")
    assert b.control_problems(path, fields) == []
    path.write_text(json.dumps(dict(good, verdict="FAIL", b_scorer_sha256="0" * 64)), encoding="utf-8")
    assert len(b.control_problems(path, fields)) == 2


def _look_inputs(tmp_path, monkeypatch, *, transferred="2026-12-15T00:00:00Z", dropped=(), void=None, **kw):
    snaps, bands, labels, market, vec = _forward(**kw)
    layout = tmp_path / "layout"
    layout.mkdir(parents=True)
    snaps.to_parquet(layout / data.SNAPSHOTS_FILE, index=False)
    bands.to_parquet(layout / data.BANDS_FILE, index=False)
    emit = tmp_path / "emit"
    emit.mkdir()
    vectors = emit / mg2.ASOF_VECTORS
    vec.to_parquet(vectors, index=False)
    (emit / mg2.EMIT_AUDIT).write_text(json.dumps({"mode": "forward", "asof_capture": {
        "vectors_sha256": mg2.sha256_file(vectors)}}), encoding="utf-8")
    transfer = tmp_path / "transfer"
    transfer.mkdir()
    labels.to_parquet(transfer / "labels.parquet", index=False)
    market.to_parquet(transfer / "market.parquet", index=False)
    manifest = {"schema": b.TRANSFER_SCHEMA, "transferred_at_utc": transferred,
                "dates": [{"date": d, "promotion_countable": True} for d in DATES],
                "files": {n: b.sha256_file(transfer / n) for n in b.TRANSFER_FILES}}
    (transfer / b.TRANSFER_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    other = {}
    for name, payload in (("drop.json", {"schema": b.DROP_LIST_SCHEMA, "dropped": list(dropped)}),
                          ("void.json", {"schema": b.VOID_RECORD_SCHEMA, "mg2_void_conditions": [],
                                         "pre_look_reads": [], **(void or {})}),
                          (b.CONTROL, {"schema": b.CONTROL_SCHEMA, "verdict": "PASS",
                                       "b_scorer_sha256": b.module_sha256(),
                                       "scorecard_code_sha256": sc.code_sha256()}),
                          ("mg2_look.json", {"gate": {"verdict": "PASS"}, "rule_sha256": "1" * 64})):
        other[name] = tmp_path / name
        other[name].write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(mg2, "reserved_end", lambda: (date(2026, 10, 15), date(2026, 11, 28)))
    monkeypatch.setattr(b, "bound_hash_problems", lambda fields, **k: [])
    return dict(rule=_rule(tmp_path), mg2_rule=tmp_path / "mg2.md", release_binding=tmp_path / "void.json",
                layout_root=layout, vectors=vectors, mg2_look=other["mg2_look.json"], transfer=transfer,
                drop_list=other["drop.json"], control_receipt=other[b.CONTROL],
                mg1_look_receipt=_receipt(tmp_path), void_record=other["void.json"], out=tmp_path / "out",
                today=TODAY)


def test_full_look_scores_ten_markets_and_writes_one_receipt(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)
    out = b.look(**args)
    assert out["decision"]["verdict"] == "PASS" and out["surviving_dates"] == 45
    primary = b._row(out["rows"], "07-16")
    assert primary["n_market_days"] == 450 and primary["n_dates"] == 45
    assert {r["market"] for r in out["rows"]} == {"ALL", *b.MARKETS}
    assert out["drop_list_check"]["agrees"] and out["secondary"]["log_pool"]["w0_identity"]["verdict"] == "PASS"
    receipt = json.loads((args["out"] / b.RECEIPT).read_text(encoding="utf-8"))
    assert receipt["mg2_gate"] == {"verdict": "PASS"} and receipt["b_decision"]["verdict"] == "PASS"
    with pytest.raises(b.BRefused, match="exactly one look"):
        b.look(**args)


def test_the_look_refuses_last_in_hour_vectors_and_an_unsettled_45th_date(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)
    lih = Path(args["vectors"]).with_name(mg2.VECTORS)
    Path(args["vectors"]).replace(lih)
    with pytest.raises(mg2.Mg2Refused, match="C7"):
        b.look(**dict(args, vectors=lih))
    lih.replace(args["vectors"])
    with pytest.raises(b.BRefused, match="embargo"):
        b.look(**dict(args, today=date.fromisoformat(DATES[-1])))


@pytest.mark.parametrize("void,cond", [({"mg2_void_conditions": ["replay"]}, 1),
                                       ({"pre_look_reads": ["price 2026-11-01"]}, 4)])
def test_pre_outcome_voids_never_open_the_transfer(tmp_path, monkeypatch, void, cond):
    args = _look_inputs(tmp_path, monkeypatch, void=void)
    monkeypatch.setattr(b, "transfer_files", lambda *a: pytest.fail("transfer opened"))
    out = b.look(**args)
    assert out["decision"]["verdict"] == "VOID" and out["decision"]["conditions"] == [cond]
    assert out["outcomes_opened"] is False


def test_hash_control_receipt_time_and_manifest_voids(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch, transferred="2020-01-01T00:00:00Z")
    monkeypatch.setattr(b, "bound_hash_problems", lambda fields, **k: ["b_scorer_sha256"])
    Path(args["control_receipt"]).unlink()
    (Path(args["transfer"]) / "labels.parquet").write_bytes(b"x")  # altered after the manifest
    out = b.look(**args)
    assert out["decision"]["conditions"] == [2, 3, 5]
    monkeypatch.setattr(b, "bound_hash_problems", lambda fields, **k: [])
    args2 = _look_inputs(tmp_path / "t2", monkeypatch)
    (Path(args2["transfer"]) / "labels.parquet").write_bytes(b"x")
    Path(args2["control_receipt"]).write_text(json.dumps({"schema": b.CONTROL_SCHEMA, "verdict": "PASS",
                                                          "b_scorer_sha256": b.module_sha256(),
                                                          "scorecard_code_sha256": sc.code_sha256()}))
    out2 = b.look(**args2)
    assert out2["decision"]["conditions"] == [6] and "labels.parquet altered" in out2["decision"]["reasons"]["6"]


def test_missing_manifest_voids_and_fewer_than_40_survivors_void(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)
    (Path(args["transfer"]) / b.TRANSFER_MANIFEST).unlink()
    assert b.look(**args)["decision"]["conditions"] == [6]
    args2 = _look_inputs(tmp_path / "t2", monkeypatch, dropped=DATES[:6])
    out = b.look(**args2)
    assert out["decision"]["conditions"] == [7] and out["surviving_dates"] == 39
    assert out["drop_list_check"]["agrees"] is False


def test_coverage_drop_uses_ten_market_07_16_snapshots():
    snaps, bands, labels, market, _ = _forward(dates=DATES[:2], markets=("atlanta", "denver"), hours=(6, 8, 14))
    day0 = set(snaps.row_key[(snaps.date == DATES[0]) & (snaps.market == "atlanta") & (snaps.local_hour == 8)])
    denver = set(snaps.row_key[snaps.market == "denver"])
    early = set(snaps.row_key[snaps.local_hour == 6])
    market = market[~market.row_key.isin(day0 | denver | early) | (market.band_index != 1)]
    cov = b.market_coverage(snaps, b.priced_snapshots(bands, market))
    assert cov[DATES[0]] == {"snapshots": 2, "priced": 1, "share": 0.5}
    assert cov[DATES[1]]["share"] == 1.0


def test_import_refuses_from_a_production_package():
    saved = sys.modules.pop("weather.calibration.b_scorer")
    try:
        with pytest.raises(ImportError, match="research-only"):
            exec("import weather.calibration.b_scorer", {"__name__": "weather.serving.anything"})
    finally:
        sys.modules["weather.calibration.b_scorer"] = saved
