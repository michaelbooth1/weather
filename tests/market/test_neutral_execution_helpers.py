"""Shared execution helpers retain values while live imports avoid paper owners."""
import ast
from datetime import datetime, timezone
import importlib
from pathlib import Path
import subprocess

import pytest

from weather import time
from weather.market import mm_policy, platform_contract, public_capture_inputs, value_helpers

ROOT = Path(__file__).resolve().parents[2]
BASE = '8180404a0e588f73dab3c83a171538f8a89c9705'


@pytest.mark.parametrize('value', [None, '', '0', 0, False, 'NaN', 'inf', '-2.3', 'bad'])
def test_scalar_helpers_match_frozen_policy(value):
    source = subprocess.check_output(['git','show',f'{BASE}:src/weather/market/mm_policy.py'], cwd=ROOT, text=True, encoding='utf-8')
    tree = ast.parse(source)
    names = {'maybe_float','bool_value','parse_time'}
    tree.body = [node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
    namespace = dict(vars(value_helpers))
    exec(compile(tree,'frozen-policy','exec'),namespace)
    for name in names:
        assert getattr(value_helpers,name)(value) == namespace[name](value)
        assert getattr(mm_policy,name) is getattr(value_helpers,name)


def test_clocks_keep_input_diagnostics_and_patchable_aliases(monkeypatch):
    from weather.market import info_event_calendar
    from weather.operations import event_metadata_validation, runtime_monitor
    expected = datetime(2026,9,26,12,tzinfo=timezone.utc)
    assert time.utc_now('2026-09-26T08:00:00-04:00') == expected
    assert mm_policy.utc_now(expected.replace(tzinfo=None)) == expected
    assert info_event_calendar.utc_now(' 2026-09-26T12:00:00Z ') == expected
    with pytest.raises(ValueError):
        event_metadata_validation.utc_now('bad')
    assert event_metadata_validation.utc_now(expected.replace(tzinfo=None)) == expected
    assert runtime_monitor.utc_now is time.utc_now
    monkeypatch.setattr(runtime_monitor,'utc_now',lambda: expected)
    assert runtime_monitor.utc_now() == expected


def test_live_entrypoints_and_neutral_owners_have_no_paper_helper_imports():
    names = ['exchange_economics','live_forward_gate','market_making_live_pilot',
             'mm_exchange','mm_exchange_reports','mm_live_bootstrap','mm_live_candidate_cli',
             'mm_live_lifecycle_probe','mm_live_pilot_cli','mm_credentials','mm_credential_import_cli',
             'mm_official_adapter','portable_live_candidate_preflight',
             'execution_contract','platform_contract','public_capture_inputs','observation_status',
             'quote_policy_defaults','value_helpers']
    for name in names:
        tree = ast.parse((ROOT/f'src/weather/market/{name}.py').read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                assert not (node.module or '').startswith(('weather.market.mm_policy','weather.market.market_making_')), (name,node.lineno,node.module)


def test_moved_public_and_platform_helpers_are_single_owners():
    from weather.market import market_making_preflight, market_making_run_support
    assert market_making_preflight.REMEDIATION_RULES is platform_contract.REMEDIATION_RULES
    assert market_making_preflight.valid_evm_address is platform_contract.valid_evm_address
    assert market_making_run_support.latest_book_rows is public_capture_inputs.latest_book_rows
    assert platform_contract.valid_evm_address('0x'+'a'*40)
    assert not platform_contract.valid_evm_address('0x'+'a'*39)
    assert public_capture_inputs.clob_token_discovery_health([])['status'] == 'BLOCK'


def test_all_datetime_clock_definitions_use_the_shared_owner():
    # Explicit string clocks are deliberately outside the datetime contract.
    for path in (ROOT/'src/weather').rglob('*.py'):
        source=path.read_text(encoding='utf-8-sig')
        for node in ast.parse(source).body:
            if isinstance(node,ast.FunctionDef) and node.name=='utc_now' and path.name!='time.py':
                body=ast.get_source_segment(source,node)
                assert '.isoformat()' in body or 'return utc_iso()' in body, path
