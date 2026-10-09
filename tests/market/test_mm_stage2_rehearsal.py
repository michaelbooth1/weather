import pytest

from tests.market.test_mm_stage2_selection import universe
from tests.market.stage2_fakes import Clock
from weather.market.mm_stage2_selection import select_table
from weather.market.mm_stage2_rehearsal import rehearse_table
from weather.market.mm_stage2_hold import verify_prediction_journal


def test_three_public_fixture_bands_rehearse_with_no_grant_files(tmp_path):
    table = select_table(universe(), now=Clock().now())
    for index, condition in enumerate(table['ranked_conditions'][:3]):
        root = tmp_path / str(index)
        result = rehearse_table(table, condition, root)
        assert result['mode'] == 'rehearsal'
        assert result['scope']['selected_for_live'] is (index == 0)
        assert result['cleanup_ok'] and result['cancel_acknowledged'] and not result['fill_seen']
        assert result['visible_two_sided_minutes'] == 2
        verify_prediction_journal(result, root / 'journal.jsonl')
    assert not list(tmp_path.rglob('international_live_execution_host.json'))
    assert not list(tmp_path.rglob('STATE_OF_PLAY.md'))


@pytest.mark.parametrize(('scenario', 'reason', 'fill'), [
    ('fill_first', 'fill', True), ('reject_second', 'control_or_transport_failure', False)])
def test_rehearsal_exchange_can_fill_or_reject_without_patching_controls(tmp_path, scenario, reason, fill):
    table = select_table(universe(), now=Clock().now())
    result = rehearse_table(table, table['selected_condition_id'], tmp_path, scenario=scenario)
    assert result['end_condition'] == reason and result['fill_seen'] is fill
    assert result['cleanup_ok'] and result['cancel_acknowledged']
    verify_prediction_journal(result, tmp_path / 'journal.jsonl')


def test_retained_three_real_public_band_rehearsals_reproduce(tmp_path):
    import json
    from pathlib import Path
    from weather.market.mm_stage2_hold import digest
    fixture = Path(__file__).parents[1] / 'fixtures/stage2_hold/20260921'
    table = json.loads((fixture / 'selection.json').read_bytes())
    for band in ('miami', 'dallas', 'los-angeles'):
        retained = json.loads((fixture / band / 'prediction.json').read_bytes())
        verify_prediction_journal(retained, fixture / band / 'journal.jsonl')
        replay = rehearse_table(table, retained['condition_id'], tmp_path / band)
        assert replay == retained
        bundle = json.loads((fixture / band / 'bundle.json').read_bytes())
        assert bundle['prediction_sha256'] == digest(replay)
        assert bundle['selection_sha256'] == digest(table)
