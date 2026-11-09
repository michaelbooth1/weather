"""Guards: B072 owner policy preparation and same-root release migration."""
from copy import deepcopy
import json
import pytest

from tests.market.test_lfc_review_b066_policy import sealing
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_f2_pinb import SCHEMA, upgrade_policy, main


@pytest.mark.parametrize('basis', ['gross', 'net_of_retained_gains'])
def test_policy_upgrade_carries_account_money_and_eligibility_fields(basis):
    old = example_policy()
    old.update(enabled=True, sleeve_loss_basis=basis, campaign_id='same-account',
               min_reward_rate='0', min_book_depth='25')
    previous = parse_policy(old)
    successor = upgrade_policy(previous)
    changed = {'schema_version', 'enabled', 'policy_name', 'policy_revision', 'revision', 'tokens',
        'learning_dates', 'confirmation_dates', 'transition_no_entry_date', 'nominal_confirmation_dates',
        'freeze_deadline_toronto', 'trading_end_toronto', 'max_session_seconds',
        'per_band_daily_filled_cap_pusd', 'learning_quote_offsets_pusd'}
    assert {k: v for k, v in old.items() if k not in changed} == {
        k: successor.raw[k] for k in old if k not in changed}
    assert successor.raw['enabled'] is False and successor.raw['schema_version'] == SCHEMA
    assert successor.raw['revision'] == old['revision']+1
    assert successor.raw['policy_revision'] == old['policy_revision']+1
    assert previous.raw == old


def test_policy_preparation_is_create_only_and_leaves_source_bytes_unchanged(tmp_path, capsys):
    source, output = tmp_path/'campaign.json', tmp_path/'candidate.json'
    original = json.dumps(example_policy()).encode()
    source.write_bytes(original)
    assert main(['--upgrade-from', str(source), '--output', str(output)]) == 0
    row = parse_policy(json.loads(output.read_bytes()))
    assert row.raw['enabled'] is False and source.read_bytes() == original
    created = output.read_bytes()
    with pytest.raises(FileExistsError):
        main(['--upgrade-from', str(source), '--output', str(output)])
    assert output.read_bytes() == created and source.read_bytes() == original
    assert 'disabled Pin B' in capsys.readouterr().out


def test_policy_preparation_refuses_relative_paths_and_second_migration(tmp_path):
    with pytest.raises(ValueError, match='migration_absolute_paths_required'):
        main(['--upgrade-from', 'relative.json', '--output', str(tmp_path/'out.json')])
    with pytest.raises(ValueError, match='migration_requires_pina_policy'):
        upgrade_policy(upgrade_policy(parse_policy(example_policy())))


def test_release_upgrade_keeps_enrollment_genesis_and_old_release(sealing, tmp_path):
    from weather.market import lfc_campaign_release as release
    from weather.market.lfc_recording_io import file_sha
    seal, state, campaign = sealing
    old = seal(example_policy())
    previous = tmp_path/'release.json'
    original, rows = previous.read_bytes(), deepcopy(state.ledger.rows)
    campaign.write_text(json.dumps(upgrade_policy(parse_policy(example_policy())).raw))
    result = release.seal_release(campaign_path=campaign, pregate_path=tmp_path/'pregate.json',
        qualified_head='1'*40, python_path=tmp_path/'python.exe', output=tmp_path/'successor.json',
        previous_release=previous)
    assert result['state_id'] == old['state_id']
    assert result['ledger_genesis_sha256'] == old['ledger_genesis_sha256']
    assert result['parameter_support']['f2_pinb']['schema_version'] == SCHEMA
    assert previous.read_bytes() == original and state.ledger.rows == rows
    assert file_sha(tmp_path/'successor.json')


@pytest.mark.parametrize('key', ['maker_address', 'state_id', 'ledger_genesis_sha256',
                               'campaign_path', 'host_id', 'principal_id'])
def test_release_upgrade_refuses_a_changed_account_identity(sealing, tmp_path, key):
    from weather.market import lfc_campaign_release as release
    seal, state, campaign = sealing
    old = seal(example_policy()); old[key] = 'different'
    previous = tmp_path/'release.json'; previous.write_text(json.dumps(old))
    campaign.write_text(json.dumps(upgrade_policy(parse_policy(example_policy())).raw))
    with pytest.raises(RuntimeError, match='migration_account_identity_changed'):
        release.seal_release(campaign_path=campaign, pregate_path=tmp_path/'pregate.json',
            qualified_head='1'*40, python_path=tmp_path/'python.exe', output=tmp_path/'successor.json',
            previous_release=previous)
    assert not (tmp_path/'successor.json').exists()
