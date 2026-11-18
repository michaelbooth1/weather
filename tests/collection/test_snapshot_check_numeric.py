import csv
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from weather.collection.snapshot_store import SnapshotStore
from weather.release_serving import STATUS_RESEARCH_UNBOUND, VerifiedServingBundle


def row(p, bucket=0):
    return {"range_label": "fixture", "bin_kind": "eq", "bin_value_c": bucket, "model_probability": p}


def compare(tmp_path, rows, recompute):
    store = SnapshotStore(root=tmp_path, event_slug="fixture")
    return store.check_snapshot_probabilities({0: 1.0}, rows, SimpleNamespace(bin_probability=recompute))


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), float("-inf"), "bad", True])
def test_uncheckable_values_cannot_pass(tmp_path, bad):
    result = compare(tmp_path, [row(bad)], lambda *_: pytest.fail("unusable stored value"))
    assert result["status"] == "skipped"
    assert result["unchecked_reasons"] == {"missing_or_invalid_stored": 1}
    assert result["rows_checked"] == 0 and result["max_abs_diff"] is None

    result = compare(tmp_path, [row(.25)], lambda *_: bad)
    assert result["status"] == "skipped"
    assert result["unchecked_reasons"] == {"missing_or_invalid_recomputed": 1}


def test_empty_and_partial_comparisons_preserve_coverage(tmp_path):
    assert compare(tmp_path, [], lambda *_: 0)["status"] == "skipped"
    result = compare(tmp_path, [row("0.25"), row(.25, None), row(.25, "bad")], lambda *_: .25)
    assert result["status"] == "skipped" and result["rows_checked"] == 1
    assert result["rows_unchecked"] == 2 and result["max_abs_diff"] == 0
    assert result["unchecked_reasons"] == {"missing_bin": 1, "invalid_bin": 1}


def test_finite_agreement_preserves_rounding_and_partial_event_ranges(tmp_path):
    results = iter([.0, 1 + 5e-13, .25 + 2e-10])
    result = compare(tmp_path, [row(0), row(1, 1), row(.25, 2)], lambda *_: next(results))
    assert result["status"] == "pass" and result["rows_checked"] == 3
    assert result["max_abs_diff"] == pytest.approx(2e-10, abs=1e-16)
    for invalid in (-.2, 1.2):
        result = compare(tmp_path, [row(invalid)], lambda *_: invalid)
        assert result["status"] == "skipped" and result["rows_checked"] == 0
        assert result["unchecked_reasons"] == {"probability_out_of_range": 1}


def test_finite_mismatch_still_raises_even_among_uncheckable_rows(tmp_path):
    with pytest.raises(ValueError, match="snapshot probability self-check failed for fixture"):
        compare(tmp_path, [row(float("nan")), row(.2)], lambda *_: .7)


def test_write_persists_uncheckable_evidence_and_return_status(tmp_path, monkeypatch):
    slug = "highest-temperature-in-nyc-on-may-28-2025"
    captured = datetime(2025, 5, 28, 16, tzinfo=timezone.utc)
    store = SnapshotStore(root=tmp_path, event_slug=slug)
    bundle = VerifiedServingBundle(status=STATUS_RESEARCH_UNBOUND, reason="synthetic", pointer_present=False)
    monkeypatch.setattr(store, "verified_serving_bundle", lambda: bundle)
    monkeypatch.setattr(store, "verified_shadow_capture_bundle", lambda: None)
    model = {"distribution": {90: .4, 91: .6}, "model_version": "fixture", "model_identity": {"fixture": True}}
    # A finite published value becomes uncheckable during the independent recomputation.
    values = iter([.4, float("nan")])
    client = SimpleNamespace(
        target_date=captured.date(),
        market_bins=lambda _: [{"label": "90 F", "value": 90, "kind": "eq"}],
        bin_probability=lambda *_: next(values),
        source_data=lambda *_: {},
        forecast_ensemble_metrics=lambda *_, **__: {},
        max_row_temp=lambda *_: None,
    )
    result = store.write({"slug": slug, "markets": []}, model, client, captured, runtime_guard={"ok": True})
    snapshot = json.loads(store.jsonl_path.read_text(encoding="utf-8"))
    with store.long_path.open(encoding="utf-8", newline="") as handle:
        [band] = csv.DictReader(handle)
    assert snapshot["snapshot_id"] == band["snapshot_id"] == result["snapshot_id"]
    assert float(band["model_probability"]) == .4
    assert result["snapshot_self_check"] == snapshot["snapshot_self_check"]
    check = result["snapshot_self_check"]
    assert check["status"] == "skipped" and check["rows_checked"] == 0
    assert check["unchecked_reasons"] == {"missing_or_invalid_recomputed": 1}
