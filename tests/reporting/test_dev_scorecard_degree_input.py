"""Native degree PMFs must be valid before the scorecard aggregates or applies a floor."""

from types import SimpleNamespace

import pandas as pd
import pytest

from weather.reporting.scorecards import dev_scorecard_data as data


def read_candidate(tmp_path, *rows):
    path = tmp_path / "candidate.jsonl"
    path.write_text("\n".join(rows), encoding="utf-8")
    key = "market|now"
    layout = SimpleNamespace(
        snaps=pd.DataFrame({"row_key": [key]}),
        bands=pd.DataFrame({
            "row_key": [key] * 3, "band_index": [0, 1, 2], "kind": ["lte", "eq", "gte"],
            "low": [-1, 0, 1], "high": [-1, 0, 1],
        }),
    )
    return data.distribution_predictions(data.CandidateSpec("distributions", str(path), no_training=True), layout, [])


def record(pmf, snapshot_id="now"):
    return f'{{"market":"market","snapshot_id":"{snapshot_id}","distribution":{pmf}}}'


def test_preserves_exact_large_degrees_signed_decimal_aliases_and_zero(tmp_path):
    row = record('{"-1.00":"0.25","0e-2":0,"9007199254740992":0.25,"9007199254740993":0.5}')
    frame, meta = read_candidate(tmp_path, row, record('{"0":true,"0":2}', "unknown"))
    assert frame.p.tolist() == [0.25, 0, 0.75]
    assert meta["unknown_snapshots"] == 1


@pytest.mark.parametrize("pmf", [
    '{"-0.9":0.4,"1":0.6}', '{"1.00000000000000000000000001":1}',
    '{"NaN":1}', '{"Infinity":1}', '{"0":true}', '{"0":null}', '{"0":"not a number"}',
    '{"0":NaN}', '{"0":Infinity}', '{"1":-0.25,"2":0.75,"0":0.5}',
    '{"0":1.1}', '{"0":0.5}', '{"0":0}', '{}', 'null', '[0.5,0.5]',
])
def test_rejects_invalid_native_inputs_before_band_mapping(tmp_path, pmf):
    with pytest.raises(data.Refused):
        read_candidate(tmp_path, record(pmf))


@pytest.mark.parametrize("pmf", ['{"1":0.1,"1":1}', '{"-0":0.2,"0.0":0.3,"1":0.5}'])
def test_rejects_repeated_or_aliasing_native_keys(tmp_path, pmf):
    with pytest.raises(data.Refused, match="duplicate native degree"):
        read_candidate(tmp_path, record(pmf))


def test_rejects_competing_forecasts_for_one_issued_key(tmp_path):
    with pytest.raises(data.Refused, match="duplicate candidate snapshot"):
        read_candidate(tmp_path, record('{"-1":1}'), record('{"1":1}'))


def test_date_guard_still_precedes_unknown_snapshot_filter(tmp_path):
    late = '{"market":"market","snapshot_id":"other","target_date":"2026-09-30","distribution":{}}'
    with pytest.raises(data.Refused, match="after"):
        read_candidate(tmp_path, late)
