"""Guards: T114 create-only disabled daily successors, monotonic economic revisions."""
from copy import deepcopy
import json

import pytest

from tests.market.lfc_wide_fixtures import policy_row
from weather.market.lfc_campaign_policy import PolicyRefused, parse_policy
from weather.market.lfc_f2_freeze import economic_digest
from weather.market.lfc_wide_policy import main, successor_row


def crossover(cities):
    first = ['dallas', 'houston', 'los-angeles', 'miami', 'nyc', 'toronto']
    return [dict(date=day, wide_cities=wide, standard_cities=sorted(set(cities)-set(wide))) for day, wide in
        [('2026-11-20', first), ('2026-11-21', sorted(set(cities)-set(first)))]]


def test_cli_chains_each_day_from_prior_output_and_carries_every_other_term(tmp_path):
    original = policy_row('complete_pairs')
    original['revision'] = 3
    source = tmp_path/'revision-6.json'
    source.write_text(json.dumps(original))
    assignments = tmp_path/'crossover.json'
    assignments.write_text(json.dumps(crossover(original['market_ids'])))
    previous = deepcopy(original)
    for revision, fill_mode, offset_mode in [(7, 'continue', 'wide'), (8, 'complete_pairs', 'wide'),
                                             (9, 'complete_pairs', 'standard'), (10, 'complete_pairs', 'standard')]:
        output = tmp_path/f'revision-{revision}.json'
        before = source.read_bytes()
        args = ['--upgrade-from', str(source), '--output', str(output), '--post-fill-mode', fill_mode,
                '--quote-offset-mode', offset_mode]
        if revision == 9:
            args += ['--city-assignments', str(assignments)]
        assert main(args) == 0
        row = json.loads(output.read_bytes())
        assert parse_policy(row).raw == row and row['enabled'] is False
        assert source.read_bytes() == before
        assert row['policy_revision'] == revision and row['revision'] == previous['revision']+1
        allowed = {'revision', 'policy_revision', 'post_fill_mode', 'quote_offset_mode', 'wide_offset_cents',
                   'city_quote_offset_assignments'}
        assert {key for key in row.keys() | previous.keys() if row.get(key) != previous.get(key)} <= allowed
        assert row['post_fill_mode'] == fill_mode and row['quote_offset_mode'] == offset_mode
        if revision >= 9:
            assert row['city_quote_offset_assignments'] == crossover(original['market_ids'])
        with pytest.raises(FileExistsError):
            main(args)
        assert json.loads(output.read_bytes()) == row
        previous, source = row, output
    friday = parse_policy(json.loads((tmp_path/'revision-9.json').read_bytes()))
    saturday = parse_policy(previous)
    assert economic_digest(friday) == economic_digest(saturday)


@pytest.mark.parametrize('change', [{'enabled': True}, {'policy_revision': 5}, {'policy_revision': True}])
def test_enabled_or_predecessor_source_refuses_without_changing_it(tmp_path, change):
    row = policy_row() | change
    path = tmp_path/'source.json'; path.write_text(json.dumps(row))
    original = path.read_bytes()
    with pytest.raises(PolicyRefused):
        successor_row(row, post_fill_mode='continue', quote_offset_mode='wide')
    assert path.read_bytes() == original


def test_cli_refuses_relative_paths_and_invalid_offset(tmp_path):
    with pytest.raises(SystemExit):
        main(['--upgrade-from', 'relative.json', '--output', str(tmp_path/'out.json'),
              '--post-fill-mode', 'continue', '--quote-offset-mode', 'wide'])
    with pytest.raises(PolicyRefused, match='unsupported_wide_offset_cents'):
        successor_row(policy_row(), post_fill_mode='continue', quote_offset_mode='wide', wide_offset_cents='3.5')
