"""Replay recorded Toronto labels against pre-repair serialized band output."""
import json
from pathlib import Path

from weather.model.toronto_model import TorontoHighTempModel


def test_recorded_toronto_band_output_is_byte_identical():
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/toronto_signed_band_replay.json').read_text(encoding='utf-8'))
    model = TorontoHighTempModel()
    assert [case['event_date'] for case in fixture['cases']] == ['2026-09-23', '2026-09-24']
    for case in fixture['cases']:
        actual = json.dumps(model.market_bins(case['event']), ensure_ascii=False, sort_keys=True).encode('utf-8')
        assert actual == case['expected_bins_json'].encode('utf-8')
