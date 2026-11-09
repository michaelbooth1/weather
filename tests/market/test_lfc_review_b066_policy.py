"""Guards: B066 explicit live basis, historical identity and local-only status."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import pytest

from tests.market.test_lfc_campaign import Clock, MAKER, Mutexes, state_at
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_breadth import example_policy
from weather.market.lfc_f2_freeze import economic_digest


@pytest.fixture
def sealing(tmp_path,monkeypatch):
    from weather.market import lfc_campaign_release as release, lfc_campaign_guard as guard
    from weather.market import lfc_campaign_state as states, lfc_pilot
    with account_lease(MAKER,backend=Mutexes()):state=state_at(tmp_path/'account',Clock())
    # Enrollment is already synthetic and guarded by the fixture's memory mutex.
    root=tmp_path/'code'; (root/'scripts/ops').mkdir(parents=True)
    (root/'scripts/ops/lfc_campaign_windowless.py').write_text('fixture')
    (root/'config').mkdir();(root/'config/international_live_execution_host.json').write_text('{}')
    (tmp_path/'python.exe').write_bytes(b'fixture');(tmp_path/'pythonw.exe').write_bytes(b'fixture')
    (tmp_path/'pregate.json').write_text('{}')
    path=tmp_path/'campaign.json';path.write_text(json.dumps(example_policy()))
    monkeypatch.setattr(release,'REPO_ROOT',root)
    monkeypatch.setattr(release,'validate_policy_path',lambda p:Path(p))
    monkeypatch.setattr(release,'require_current_portable_execution_assignment',lambda:{})
    monkeypatch.setattr(release,'git_identity',lambda p:'1'*40)
    monkeypatch.setattr(release,'datetime',SimpleNamespace(now=lambda tz:datetime(2026,11,11,tzinfo=timezone.utc)))
    monkeypatch.setattr(release,'current_execution_host_id',lambda:'fixture')
    monkeypatch.setattr(release,'current_execution_principal_id',lambda:'fixture')
    monkeypatch.setattr(release,'resolve_production_python_runtime_binding',lambda *a,**kw:{})
    monkeypatch.setattr(release,'package_binding',lambda name:{})
    monkeypatch.setattr(lfc_pilot,'pilot_root',lambda:state.ledger.path.parent)
    monkeypatch.setattr(states,'DEFAULT_STATE_ROOT',state.root.parent)
    monkeypatch.setattr(guard,'account_lease',lambda maker:account_lease(maker,backend=Mutexes()))
    def seal(row):
        path.write_text(json.dumps(row))
        return release.seal_release(campaign_path=path,pregate_path=tmp_path/'pregate.json',
            qualified_head='1'*40,python_path=tmp_path/'python.exe',output=tmp_path/'release.json')
    return seal,state,path


def test_seal_refuses_missing_live_basis_before_any_pilot_access(sealing,monkeypatch):
    seal,state,path=sealing
    row=example_policy();row.pop('sleeve_loss_basis')
    from weather.market import lfc_pilot
    monkeypatch.setattr(lfc_pilot,'pilot_root',lambda:pytest.fail('missing basis reached pilot state'))
    with pytest.raises(ValueError,match='explicit_sleeve_loss_basis_required'):seal(row)


@pytest.mark.parametrize('basis',['gross','net_of_retained_gains'])
def test_explicit_basis_seals_and_local_status_prints_it(sealing,monkeypatch,capsys,basis,tmp_path):
    from weather.market import lfc_campaign_cli as cli
    from weather.market.lfc_campaign_control import control_record
    seal,state,path=sealing
    row=example_policy();row['sleeve_loss_basis']=basis
    sealed=seal(row)
    assert sealed['sleeve_loss_basis']==basis
    monkeypatch.setattr(cli,'load_release',lambda *a:sealed)
    monkeypatch.setattr(cli,'validate_release',lambda *a:None)
    monkeypatch.setattr(cli,'bound_state',lambda *a,**kw:(state.ledger.path.parent,state))
    monkeypatch.setattr(cli,'account_lease',lambda maker:account_lease(maker,backend=Mutexes()))
    monkeypatch.setattr(cli,'CONTROL_ROOT',tmp_path/'control')
    control_record(tmp_path/'control','a'*32,phase='COMPLETE',now=Clock().now())
    assert cli.main(['status','--release','fixture','--release-sha256','a'*64])==0
    printed=json.loads(capsys.readouterr().out.splitlines()[-1])
    assert printed['sleeve_loss_basis']==basis and printed['clean'] is True


def test_legacy_missing_basis_keeps_exact_gross_economic_identity():
    row=example_policy();row.pop('sleeve_loss_basis')
    legacy=parse_policy(row)
    explicit=parse_policy({**row,'sleeve_loss_basis':'gross'})
    assert economic_digest(legacy)==economic_digest(explicit)


@pytest.mark.parametrize('basis',['gross','net_of_retained_gains'])
def test_new_claim_and_control_row_show_effective_basis(tmp_path,basis):
    from weather.market.lfc_campaign_control import control_record
    row=example_policy();row['sleeve_loss_basis']=basis
    policy=parse_policy(row);entry=next(e for e in policy.entries if e.local_date=='2026-11-12')
    with account_lease(MAKER,backend=Mutexes()):
        state=state_at(tmp_path,Clock());state.ledger.clock=lambda:entry.start
        claim=state.claim(entry,policy,entry.start)
        assert claim['sleeve_loss_basis']==state.ledger.autostart_claims[-1]['sleeve_loss_basis']==basis
        control=control_record(tmp_path/'control',claim['attempt_id'],phase='RUNNING',now=entry.start,
            policy_metadata=state.policy_labels(policy,entry.local_date))
        assert control['sleeve_loss_basis']==basis


def test_require_enabled_check_refuses_missing_basis_before_funding_read(tmp_path,monkeypatch,capsys):
    from weather.market import lfc_campaign_cli as cli
    from weather.market.lfc_campaign_runtime import Runtime
    with account_lease(MAKER,backend=Mutexes()):state=state_at(tmp_path,Clock())
    path=tmp_path/'campaign.json'
    row=example_policy();row.update(enabled=True);row.pop('sleeve_loss_basis');path.write_text(json.dumps(row))
    monkeypatch.setattr(cli,'load_release',lambda *a:{'campaign_path':str(path),'maker_address':MAKER})
    monkeypatch.setattr(cli,'validate_release',lambda *a:None)
    monkeypatch.setattr(cli,'bound_state',lambda *a,**kw:(state.ledger.path.parent,state))
    monkeypatch.setattr(cli,'account_lease',lambda maker:account_lease(maker,backend=Mutexes()))
    monkeypatch.setattr(cli,'CONTROL_ROOT',tmp_path/'control')
    monkeypatch.setattr(Runtime,'confirm_funding',lambda *a:pytest.fail('missing basis reached account read'))
    assert cli.main(['check','--release','fixture','--release-sha256','a'*64,'--require-enabled'])==1
    assert 'explicit_sleeve_loss_basis_required' in capsys.readouterr().out


def test_all_shipped_f2_examples_carry_explicit_owner_refill_basis():
    from weather.paths import REPO_ROOT
    found=[]
    for path in (REPO_ROOT/'docs/examples').glob('*.json'):
        row=json.loads(path.read_text())
        if isinstance(row,dict) and row.get('schema_version') in {'lfc_campaign_policy_v0.2','lfc_campaign_policy_v0.3'}:
            assert row['sleeve_loss_basis']=='net_of_retained_gains'
            found.append(path)
    assert found
