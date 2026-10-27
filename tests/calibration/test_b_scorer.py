"""Rule B-1 scorer: MG-1 receipt precondition, rule parse, estimand, keep/kill table and VOID conditions.

Guards: Rule B-1 (B_forward_test_design.md, b_rule_v1 block): sections 3 (10 markets, 45 dates, coverage
drop), 5 (Delta 07-16 on covered snapshots, date-clustered w_date 2,000 draws seed 20260921), 6 (PASS / FAIL /
INCONCLUSIVE, NOT-WORSE below +0.0027), 8 (VOID 1-7), 9 (MG-1 look receipt first, embargo, one look) and (a)
(positive-control receipt); MG-2 rule section 8 C7 (as-of-capture vectors only); the Fable review of 2026-10-26
("bind with fixes": consumed-look markers, ABORTED receipts, verified bound fields, VOIDs 1/4/5 from recorded
evidence, a VOID on a degenerate interval, the market-local embargo) and the MG-2 season-L6 clarification
(``l6_state_sha256``); master's review of de422aa59 (R1 the fixed per-rule consumed marker, R2 an unevaluated
section 7 condition is VOID 1, R4 the release binding is bind-release output, R6 the embargo covers every market).
"""
import json
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather.reporting.scorecards import dev_scorecard as sc
from weather.reporting.scorecards import dev_scorecard_data as data

from tests.host_guard import import_or_skip_on_capture_host

ROOT = Path(__file__).resolve().parents[2]

b = import_or_skip_on_capture_host("weather.calibration.b_scorer")
mg2 = import_or_skip_on_capture_host("weather.calibration.mg2_composite")
l3 = import_or_skip_on_capture_host("weather.calibration.r0_ols_floor_challenger")
REAL_CONSUMED_ROOT = b.CONSUMED_ROOT  # before the autouse fixture moves it into tmp

D0 = date(2026, 10, 28)
DATES = [(D0 + timedelta(days=i)).isoformat() for i in range(45)]
TODAY = date(2026, 12, 20)
FILLED = {"mg2_rule_sha256": "1" * 64, "mg2_binding_commit": "2" * 40, "mg2_release_binding_sha256": "3" * 64,
          "mg2_owner_decision_id": "OD-2026-10-27-mg2", "l6_coefficients_sha256": "4" * 64,
          "p3d_n_state_sha256": "5" * 64, "function_sha256": "6" * 64, "l6_state_sha256": "7" * 64}


@pytest.fixture(autouse=True)
def _fixed_marker_root(tmp_path, monkeypatch):
    """The fixed consumed-look marker lives under the repo's data/; tests keep it in tmp."""
    monkeypatch.setattr(b, "CONSUMED_ROOT", tmp_path / "_b_look")


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


MG1_LOOKED = "2026-12-14T00:00:00Z"


def _receipt(tmp_path, looked=MG1_LOOKED):
    path = tmp_path / "mg1_look_receipt.json"
    path.write_text(json.dumps({"mg1": "look", **({b.MG1_RECEIPT_TIME: looked} if looked else {})}), encoding="utf-8")
    return path


# ----------------------------------------------------------------------------- precondition and rule

def test_l6_state_sha_is_a_bound_field_that_must_be_filled_with_hex(tmp_path):
    """MG-2 clarification season-L6 2026-10-26 sections 3 and 7: the frozen L6 state sha is bound in B-1."""
    assert "l6_state_sha256" in b.BOUND_FIELDS and "l6_state_sha256" in b.RULE_FIELDS
    _, fields = b.read_rule(_rule(tmp_path, fill=False))
    assert "l6_state_sha256" in b.unfilled(fields)
    _, fields = b.read_rule(_rule(tmp_path))
    assert b.unfilled(fields) == []
    assert b.unfilled(dict(fields, l6_state_sha256="")) == ["l6_state_sha256"]
    assert b.unfilled({k: v for k, v in fields.items() if k != "l6_state_sha256"}) == ["l6_state_sha256"]
    with pytest.raises(b.BRefused, match="FILL@BINDING.*l6_state_sha256"):
        b.look_guard(rule=_rule(tmp_path, l6_state_sha256=b.FILL), mg1_look_receipt=_receipt(tmp_path), out=tmp_path,
                     today=TODAY)


@pytest.mark.parametrize("key,bad", [
    ("l6_state_sha256", ""), ("l6_state_sha256", "TBD"), ("l6_state_sha256", "A" * 64),
    ("l6_state_sha256", "7" * 63), ("l6_state_sha256", "7" * 65), ("l6_state_sha256", "g" * 64),
    ("mg2_rule_sha256", "TBD"), ("p3d_n_state_sha256", "5" * 40), ("mg2_binding_commit", "2" * 64),
    ("mg2_binding_commit", ""), ("mg2_owner_decision_id", "TBD"), ("mg2_owner_decision_id", ""),
    ("b_scorer_sha256", "FILL")])
def test_any_bound_field_not_in_its_format_is_unfilled_and_refuses_the_look(tmp_path, key, bad):
    rule = _rule(tmp_path, **{key: bad})
    _, fields = b.read_rule(rule)
    assert b.unfilled(fields) == [key]
    with pytest.raises(b.BRefused, match="FILL@BINDING> or malformed"):
        b.look_guard(rule=rule, mg1_look_receipt=_receipt(tmp_path), out=tmp_path, today=TODAY)


def test_bound_field_formats_accept_the_filled_shapes(tmp_path):
    _, fields = b.read_rule(_rule(tmp_path, mg2_owner_decision_id="NONE"))
    assert b.unfilled(fields) == []
    assert b.BOUND_FORMATS["mg2_binding_commit"] is b.COMMIT_HEX
    assert set(b.BOUND_FORMATS) == set(b.BOUND_FIELDS)


def test_rule_with_an_unknown_key_refuses(tmp_path):
    with pytest.raises(b.BRefused, match="unknown keys"):
        b.read_rule(_rule(tmp_path, l6_state_sha256_note="x"))


def test_rule_without_the_l6_state_field_refuses(tmp_path):
    path = _rule(tmp_path)
    text = path.read_text(encoding="utf-8")
    kept = [x for x in text.splitlines() if not x.startswith("l6_state_sha256:")]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    with pytest.raises(b.BRefused, match="lacks.*l6_state_sha256"):
        b.read_rule(path)


def test_l6_state_sha_must_equal_the_mg2_release_binding(tmp_path):
    binding = tmp_path / "release-binding.json"
    fields = {"l6_state_sha256": "7" * 64}
    schema = {"schema": mg2.RELEASE_BINDING_SCHEMA}
    binding.write_text(json.dumps(dict(schema, l6_state_sha256="7" * 64)), encoding="utf-8")
    assert b.l6_state_problems(fields, binding) == []
    binding.write_text(json.dumps(dict(schema, l6_state_sha256="8" * 64)), encoding="utf-8")
    assert b.l6_state_problems(fields, binding) == ["l6_state_sha256 (MG-2 release binding)"]
    binding.write_text(json.dumps(schema), encoding="utf-8")
    assert b.l6_state_problems(fields, binding) == ["l6_state_sha256 (MG-2 release binding)"]
    binding.write_text(json.dumps({"l6_state_sha256": "7" * 64}), encoding="utf-8")  # a hand-written binding
    assert b.l6_state_problems(fields, binding) == [
        "l6_state_sha256 (the MG-2 release binding is not bind-release output)"]
    for bad in ("", b.FILL, "7" * 63):
        assert b.l6_state_problems({"l6_state_sha256": bad}, binding) == ["l6_state_sha256"]


def test_the_look_refuses_first_without_mg1_look_receipt(tmp_path):
    for receipt in (None, tmp_path / "absent.json"):
        with pytest.raises(b.BRefused, match="MG-1's look receipt does not exist"):
            b.look_guard(rule=tmp_path / "no-rule.md", mg1_look_receipt=receipt, out=tmp_path, today=TODAY)
    empty = tmp_path / "empty.json"
    empty.write_bytes(b"")
    with pytest.raises(b.BRefused, match="MG-1's look receipt"):
        b.look(rule="x", mg2_rule="x", release_binding="x", layout_root="x", vectors="x", mg2_look="x",
               transfer="x", drop_list="x", control_receipt="x", mg1_look_receipt=empty,
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
    with pytest.raises(b.BRefused, match="needs the transfer"):
        b.look_guard(rule=rule, mg1_look_receipt=receipt, out=tmp_path, today=TODAY)
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


MG2_CONDITIONS = {name: {"pass": True, "detail": "ok"} for name in mg2.SECTION7_CONDITIONS}


def test_every_b_market_has_an_embargo_time_zone():
    assert set(b.MARKET_TZ) == set(b.MARKETS)


def _look_inputs(tmp_path, monkeypatch, *, transferred="2026-12-15T00:00:00Z", dropped=(), mg2_look=None,
                 manifest_extra=None, **kw):
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
    receipt = _receipt(tmp_path)
    manifest = {"schema": b.TRANSFER_SCHEMA, "transferred_at_utc": transferred,
                "mg1_look_receipt_sha256": b.sha256_file(receipt),
                "dates": [{"date": d, "promotion_countable": True} for d in DATES],
                "files": {n: b.sha256_file(transfer / n) for n in b.TRANSFER_FILES}, **(manifest_extra or {})}
    (transfer / b.TRANSFER_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    other = {}
    (tmp_path / "mg2").mkdir()
    look_payload = {"gate": {"verdict": "PASS"}, "rule_sha256": "1" * 64, "void_conditions": MG2_CONDITIONS,
                    "pre_look_reads": [], **(mg2_look or {})}
    for name, payload in (("drop.json", {"schema": b.DROP_LIST_SCHEMA, "dropped": list(dropped)}),
                          ("binding.json", {}),
                          (b.CONTROL, {"schema": b.CONTROL_SCHEMA, "verdict": "PASS",
                                       "b_scorer_sha256": b.module_sha256(),
                                       "scorecard_code_sha256": sc.code_sha256()}),
                          ("mg2/mg2_look.json", look_payload)):
        other[name] = tmp_path / name
        other[name].write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(mg2, "reserved_end", lambda: (date(2026, 10, 15), date(2026, 11, 28)))
    monkeypatch.setattr(b, "bound_hash_problems", lambda fields, **k: [])
    return dict(rule=_rule(tmp_path), mg2_rule=tmp_path / "mg2.md", release_binding=other["binding.json"],
                layout_root=layout, vectors=vectors, mg2_look=other["mg2/mg2_look.json"], transfer=transfer,
                drop_list=other["drop.json"], control_receipt=other[b.CONTROL],
                mg1_look_receipt=receipt, out=tmp_path / "out", today=TODAY)


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


def test_the_look_is_consumed_so_a_new_out_or_drop_list_cannot_rescore(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)
    b.look(**args)
    for marker in b.consumed_markers(args["transfer"], args["mg2_look"]):
        assert json.loads(marker.read_text(encoding="utf-8"))["schema"] == b.CONSUMED_SCHEMA
    drop = tmp_path / "drop5.json"
    drop.write_text(json.dumps({"schema": b.DROP_LIST_SCHEMA, "dropped": DATES[:5]}), encoding="utf-8")
    with pytest.raises(b.BRefused, match="already consumed"):
        b.look(**dict(args, out=tmp_path / "out2", drop_list=drop))
    assert not (tmp_path / "out2").exists()
    # either input-side marker, or the fixed marker alone, refuses
    (Path(args["transfer"]) / b.CONSUMED).unlink()
    with pytest.raises(b.BRefused, match="already consumed"):
        b.look(**dict(args, out=tmp_path / "out3"))
    (Path(args["mg2_look"]).parent / b.CONSUMED).unlink()
    with pytest.raises(b.BRefused, match="already consumed"):
        b.look(**dict(args, out=tmp_path / "out4"))


def test_copied_inputs_and_a_new_out_are_refused_by_the_fixed_per_rule_marker(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)
    b.look(**args)
    rule_sha, _ = b.read_rule(args["rule"])
    fixed = b.rule_marker(rule_sha)
    assert fixed == tmp_path / "_b_look" / f"consumed-{rule_sha}.json"
    assert json.loads(fixed.read_text(encoding="utf-8"))["rule_sha256"] == rule_sha
    transfer = shutil.copytree(args["transfer"], tmp_path / "copy" / "transfer")
    mg2_dir = shutil.copytree(Path(args["mg2_look"]).parent, tmp_path / "copy" / "mg2")
    for marker in (Path(transfer) / b.CONSUMED, Path(mg2_dir) / b.CONSUMED):
        marker.unlink()
    with pytest.raises(b.BRefused, match=f"rule {rule_sha} was already consumed"):
        b.look(**dict(args, transfer=transfer, mg2_look=Path(mg2_dir) / "mg2_look.json",
                      out=tmp_path / "copy" / "out"))
    assert not (tmp_path / "copy" / "out").exists()
    assert not (Path(transfer) / b.CONSUMED).exists()


def test_the_fixed_marker_root_is_repository_owned():
    from weather import paths

    assert REAL_CONSUMED_ROOT == paths.DATA_ROOT / "b_look"


def test_a_refusal_before_anything_is_read_does_not_consume_the_look(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)
    with pytest.raises(b.BRefused, match="embargo"):
        b.look(**dict(args, today=date.fromisoformat(DATES[-1])))
    assert not any(m.exists() for m in b.consumed_markers(args["transfer"], args["mg2_look"]))
    assert not any((tmp_path / "_b_look").glob("consumed-*.json"))
    assert b.look(**args)["decision"]["verdict"] == "PASS"


def test_a_crash_after_outcomes_open_writes_an_aborted_receipt_and_consumes(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("layout broke")

    monkeypatch.setattr(b, "build_table", boom)
    with pytest.raises(RuntimeError, match="layout broke"):
        b.look(**args)
    receipt = json.loads((args["out"] / b.RECEIPT).read_text(encoding="utf-8"))
    payload = json.loads((args["out"] / b.LOOK).read_text(encoding="utf-8"))
    assert receipt["b_decision"]["verdict"] == "ABORTED" and "layout broke" in receipt["b_decision"]["error"]
    assert payload["outcomes_opened"] is True and receipt["inputs"]["vectors_sha256"]
    monkeypatch.undo()
    monkeypatch.setattr(b, "CONSUMED_ROOT", tmp_path / "_b_look")
    _look_inputs(tmp_path / "unused", monkeypatch)  # restore the patched window and hash check
    with pytest.raises(b.BRefused, match="exactly one look|already consumed"):
        b.look(**dict(args, out=tmp_path / "again"))


def test_a_crash_before_outcomes_open_is_aborted_with_outcomes_closed(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(b, "control_problems", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        b.look(**args)
    payload = json.loads((args["out"] / b.LOOK).read_text(encoding="utf-8"))
    assert payload["decision"]["verdict"] == "ABORTED" and payload["outcomes_opened"] is False


def test_embargo_ends_at_the_latest_market_local_midnight(tmp_path, monkeypatch):
    end = b.embargo_end(DATES[-1])
    assert end == datetime(2026, 12, 12, 8, 0, tzinfo=timezone.utc)  # Pacific midnight, PST
    args = _look_inputs(tmp_path, monkeypatch)
    with pytest.raises(b.BRefused, match="embargo"):
        b.look(**dict(args, today=None, now=end - timedelta(seconds=1)))
    assert b.look(**dict(args, today=None, now=end))["decision"]["verdict"] == "PASS"


def test_the_look_refuses_last_in_hour_vectors_and_an_unsettled_45th_date(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)
    lih = Path(args["vectors"]).with_name(mg2.VECTORS)
    Path(args["vectors"]).replace(lih)
    with pytest.raises(mg2.Mg2Refused, match="C7"):
        b.look(**dict(args, vectors=lih))
    lih.replace(args["vectors"])
    with pytest.raises(b.BRefused, match="embargo"):
        b.look(**dict(args, today=date.fromisoformat(DATES[-1])))


@pytest.mark.parametrize("recorded,cond", [
    ({"void_conditions": dict(MG2_CONDITIONS, replay={"pass": False, "detail": "replay 1e-9"})}, 1),
    ({"void_conditions": {}}, 1),
    ({"void_conditions": dict(MG2_CONDITIONS, nowcast_replay={"pass": None, "detail": "not evaluated"})}, 1),
    ({"void_conditions": {k: v for k, v in MG2_CONDITIONS.items() if k != "window_leakage"}}, 1),
    ({"void_conditions": None}, 1),
    ({"pre_look_reads": ["price 2026-11-01"]}, 4),
    ({"pre_look_reads": None}, 4)])
def test_pre_outcome_voids_never_open_the_transfer(tmp_path, monkeypatch, recorded, cond):
    args = _look_inputs(tmp_path, monkeypatch, mg2_look=recorded)
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


@pytest.mark.parametrize("extra,looked", [({"mg1_look_receipt_sha256": "0" * 64}, MG1_LOOKED),
                                          ({}, None),
                                          ({"transferred_at_utc": MG1_LOOKED}, MG1_LOOKED),
                                          ({"transferred_at_utc": "2026-12-15T00:00:00"}, MG1_LOOKED)])
def test_void_5_uses_the_bound_receipt_and_the_instant_inside_it(tmp_path, monkeypatch, extra, looked):
    args = _look_inputs(tmp_path, monkeypatch, manifest_extra=extra)
    receipt = _receipt(tmp_path, looked=looked)
    manifest_path = Path(args["transfer"]) / b.TRANSFER_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "mg1_look_receipt_sha256" not in extra:
        manifest["mg1_look_receipt_sha256"] = b.sha256_file(receipt)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    out = b.look(**dict(args, mg1_look_receipt=receipt))
    assert out["decision"]["conditions"] == [5] and out["outcomes_opened"] is False


def test_void_5_ignores_the_receipt_file_time(tmp_path, monkeypatch):
    import os

    args = _look_inputs(tmp_path, monkeypatch)
    later = datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(args["mg1_look_receipt"], (later, later))  # a file time after the transfer no longer voids
    assert b.look(**args)["decision"]["verdict"] == "PASS"


def test_missing_manifest_voids_and_fewer_than_40_survivors_void(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch)
    (Path(args["transfer"]) / b.TRANSFER_MANIFEST).unlink()
    assert b.look(**args)["decision"]["conditions"] == [6]
    args2 = _look_inputs(tmp_path / "t2", monkeypatch, dropped=DATES[:6])
    out = b.look(**args2)
    assert out["decision"]["conditions"] == [6, 7] and out["surviving_dates"] == 39
    assert out["drop_list_check"]["agrees"] is False


def test_a_drop_list_that_disagrees_with_the_transfer_voids_6(tmp_path, monkeypatch):
    args = _look_inputs(tmp_path, monkeypatch, dropped=DATES[:5])  # full coverage: nothing should drop
    out = b.look(**args)
    assert out["decision"]["conditions"] == [6] and out["surviving_dates"] == 40
    assert out["drop_list_check"]["agrees"] is False and out["outcomes_opened"] is True


@pytest.mark.parametrize("ci", [[None, None], [float("nan"), 0.001], [0.002, -0.001], [], None])
def test_a_degenerate_primary_interval_is_void(ci):
    rows = [{"market": "ALL", "group": "07-16", "delta": {"estimate": 0.0, "ci95": ci}}]
    assert b.decide(rows)["verdict"] == "VOID"
    assert b.decide([])["verdict"] == "VOID"


# ----------------------------------------------------------------------------- bound hashes (VOID 2), unpatched

FIXTURE_GIT_CONFIG = ("user.name=Fixture", "user.email=fixture@example.invalid", "commit.gpgSign=false")


def _bound_world(tmp_path):
    """A binding commit holding the release files, the MG-2 rule, its release binding, a forward emit audit."""
    from tests.git_template import commit_fixture_tree
    from weather.model import observed_running_max

    repo = tmp_path / "repo"
    for rel in mg2.RELEASE_FILES:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, repo / rel)
    commit = commit_fixture_tree(repo, cache_root=tmp_path / "git-templates", config=FIXTURE_GIT_CONFIG,
                                 message="binding fixture", quiet=True)
    mg2_fields = {"switch_hour": "13", "d0": D0.isoformat(), "n_forward_dates": "45", "owner_decision_id": "NONE",
                  "l6_coefficients_sha256": "4" * 64, "p3d_n_state_sha256": "5" * 64,
                  "forecast_high_source": "captured_nbm_v2_mean_07z", "own_obs_source": "captured_metar_l6_own",
                  "function_sha256": mg2.sha256_file(observed_running_max.__file__),
                  "noninferiority_margin_00_16": "0.0010"}
    rule = tmp_path / "mg2_rule.md"
    rule.write_text("```mg2_rule_v1\n" + "\n".join(f"{k}: {v}" for k, v in mg2_fields.items()) + "\n```\n",
                    encoding="utf-8")
    rule_sha, _ = mg2.read_rule(rule)
    binding = tmp_path / "release-binding.json"
    binding.write_text(json.dumps({"schema": mg2.RELEASE_BINDING_SCHEMA, "rule_sha256": rule_sha,
                                   "files": mg2.release_hashes(repo), "l6_state_sha256": "7" * 64,
                                   **{k: mg2_fields[k] for k in ("l6_coefficients_sha256", "p3d_n_state_sha256",
                                                                 "forecast_high_source", "own_obs_source",
                                                                 "function_sha256")}}), encoding="utf-8")
    emit = tmp_path / "emit"
    emit.mkdir()
    vectors = emit / mg2.ASOF_VECTORS
    pd.DataFrame({"row_key": ["a|1"], "band_index": [0], "p": [1.0]}).to_parquet(vectors, index=False)
    audit = {"mode": "forward", "asof_capture": {"vectors_sha256": mg2.sha256_file(vectors)},
             "l6_coefficients_sha256": "4" * 64, "p3d_n_state_sha256": "5" * 64, "nowcasts_sha256": "9" * 64,
             "l6_state_sha256": "7" * 64,
             "nowcasts_manifest": {"nowcasts_sha256": "9" * 64, "l6_state_sha256": "7" * 64,
                                   "prev_day_source": mg2.FORWARD_PREV_DAY_SOURCE}}
    (emit / mg2.EMIT_AUDIT).write_text(json.dumps(audit), encoding="utf-8")
    look = tmp_path / "mg2_look.json"
    look.write_text(json.dumps({"rule_sha256": rule_sha, "vectors_sha256": mg2.sha256_file(vectors)}),
                    encoding="utf-8")
    fields = dict(FILLED, mg2_rule_sha256=rule_sha, mg2_binding_commit=commit,
                  mg2_release_binding_sha256=mg2.sha256_file(binding), mg2_owner_decision_id="NONE",
                  function_sha256=mg2_fields["function_sha256"], d0=D0.isoformat(),
                  b_scorer_sha256=b.module_sha256(), scorecard_code_sha256=sc.code_sha256())
    kw = dict(mg2_rule=rule, release_binding=binding, mg2_look=look, vectors=vectors, root=repo)
    return fields, kw, repo, emit


@pytest.mark.spawns
def test_bound_hash_problems_pass_on_a_consistent_binding_and_name_each_break(tmp_path):
    fields, kw, repo, emit = _bound_world(tmp_path)
    assert b.bound_hash_problems(fields, **kw) == []
    # each field mismatch is named, alone
    for key in ("mg2_rule_sha256", "mg2_release_binding_sha256", "l6_coefficients_sha256", "p3d_n_state_sha256",
                "b_scorer_sha256", "scorecard_code_sha256"):
        got = b.bound_hash_problems(dict(fields, **{key: "e" * 64}), **kw)
        assert key in got or any(key in g for g in got), (key, got)
    assert "mg2_owner_decision_id" in b.bound_hash_problems(dict(fields, mg2_owner_decision_id="OD-2026-10-27-x"),
                                                           **kw)
    assert "d0 (MG-2 rule)" in b.bound_hash_problems(dict(fields, d0="2026-10-29"), **kw)
    got = b.bound_hash_problems(dict(fields, l6_state_sha256="8" * 64), **kw)
    assert "l6_state_sha256 (MG-2 release binding)" in got and "emit audit l6_state_sha256" in got


@pytest.mark.spawns
def test_the_binding_commit_must_hold_the_bound_files(tmp_path):
    fields, kw, repo, emit = _bound_world(tmp_path)
    got = b.bound_hash_problems(dict(fields, mg2_binding_commit="0" * 40), **kw)
    assert any(g.startswith("mg2_binding_commit:") and "absent" in g for g in got)
    binding = json.loads(kw["release_binding"].read_text(encoding="utf-8"))
    rel = mg2.RELEASE_FILES[0]
    binding["files"][rel] = "0" * 64
    kw["release_binding"].write_text(json.dumps(binding), encoding="utf-8")
    got = b.binding_commit_problems(fields["mg2_binding_commit"], kw["release_binding"], root=repo)
    assert got == [f"mg2_binding_commit: {rel} at {fields['mg2_binding_commit']} is not the bound file"]


@pytest.mark.spawns
def test_running_code_that_differs_from_the_binding_is_a_hash_problem(tmp_path):
    fields, kw, repo, emit = _bound_world(tmp_path)
    (repo / mg2.RELEASE_FILES[0]).write_text("# edited after binding\n", encoding="utf-8")
    assert any(g.startswith("release:") for g in b.bound_hash_problems(fields, **kw))


@pytest.mark.parametrize("change,problem", [
    ({"l6_coefficients_sha256": "e" * 64}, "emit audit l6_coefficients_sha256"),
    ({"p3d_n_state_sha256": "e" * 64}, "emit audit p3d_n_state_sha256"),
    ({"nowcasts_sha256": "e" * 64}, "emit audit nowcasts_sha256"),
    ({"nowcasts_sha256": None}, "emit audit nowcasts_sha256"),
    ({"nowcasts_manifest": {"nowcasts_sha256": "9" * 64, "l6_state_sha256": "7" * 64,
                            "prev_day_source": "D-1 replay folder, last line"}}, "emit audit nowcasts prev_day_source"),
    ({"nowcasts_manifest": None}, "emit audit nowcasts_sha256"),
    ({"l6_state_sha256": "e" * 64}, "emit audit l6_state_sha256")])
def test_emit_audit_must_carry_the_bound_coefficients_nowcasts_and_l6_state(tmp_path, change, problem):
    emit = tmp_path / "emit"
    emit.mkdir()
    vectors = emit / mg2.ASOF_VECTORS
    vectors.write_bytes(b"v")
    audit = {"l6_coefficients_sha256": "4" * 64, "p3d_n_state_sha256": "5" * 64, "nowcasts_sha256": "9" * 64,
             "l6_state_sha256": "7" * 64,
             "nowcasts_manifest": {"nowcasts_sha256": "9" * 64, "l6_state_sha256": "7" * 64,
                                   "prev_day_source": mg2.FORWARD_PREV_DAY_SOURCE}}
    (emit / mg2.EMIT_AUDIT).write_text(json.dumps(audit), encoding="utf-8")
    assert b.emit_audit_problems(FILLED, vectors) == []
    (emit / mg2.EMIT_AUDIT).write_text(json.dumps(dict(audit, **change)), encoding="utf-8")
    assert problem in b.emit_audit_problems(FILLED, vectors)
    (emit / mg2.EMIT_AUDIT).unlink()
    assert b.emit_audit_problems(FILLED, vectors) == ["emit audit missing"]


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


def test_b_schemas_are_registered_and_the_void_record_is_retired():
    from weather.schema_families import schema_version
    from weather.schema_registry_families import installed_families

    specs = {s.version: s for s in installed_families().family_schemas}
    assert schema_version("b_look_consumed") == b.CONSUMED_SCHEMA
    assert specs["b_void_record/1"].status == "legacy" and specs["b_void_record/1"].migration_notes
    assert not hasattr(b, "VOID_RECORD_SCHEMA")


def test_the_control_needs_every_section7_replay_evaluated(tmp_path):
    path = tmp_path / "mg2_checks.json"
    good = {"nowcast_replay_pass": True, "p3d_n_replay_pass": True, "window_leakage_pass": False,
            "emit_audit_vectors_sha256": ["a" * 64, "a" * 64]}
    path.write_text(json.dumps(good), encoding="utf-8")
    got = b.section7_rehearsal(path)
    assert (got["nowcast_replay_pass"], got["window_leakage_pass"]) == (True, False)
    assert got["sha256"] == b.sha256_file(path)
    for key in b.SECTION7_REPLAYS:
        for bad in (None, "true"):
            path.write_text(json.dumps(dict(good, **{key: bad})), encoding="utf-8")
            with pytest.raises(b.BRefused, match="unevaluated"):
                b.section7_rehearsal(path)
    for missing in (None, tmp_path / "absent.json"):
        with pytest.raises(b.BRefused, match="needs the rehearsal"):
            b.section7_rehearsal(missing)
    with pytest.raises(b.BRefused, match="unevaluated"):  # refused before any control input is read
        b.control(layout="x", coefficients="x", nowcasts="x", p3d_files=["x", "y"], out=tmp_path / "ctl",
                  mg2_checks=path)
    with pytest.raises(SystemExit):
        b.build_parser().parse_args(["control", "--layout", "l", "--coefficients", "c", "--nowcasts", "n",
                                     "--p3d", "a", "b", "--out", "o"])
