"""No new HTTP bypasses, implicit dependencies or policy-dependent spawns."""
import ast
import json
from pathlib import Path

from tests.operations.live_path_ast import import_misses, powershell_commands, raw_http_sites, trees

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).with_name('live_path_allowlist.json')


def test_raw_http_allowlist_only_shrinks():
    actual = {f'{path}:{line}' for path, tree in trees(ROOT)
              if path != 'src/weather/http.py' for line in raw_http_sites(tree)}
    expected = set(json.loads(ALLOWLIST.read_text())['raw_http'])
    assert actual == expected, f'New={actual - expected}; remove stale exceptions={expected - actual}'


def test_all_third_party_imports_are_declared_or_named_debt():
    actual = set(import_misses(ROOT))
    expected = set(json.loads(ALLOWLIST.read_text())['undeclared_imports'])
    assert actual == expected, f'New={actual - expected}; remove stale exceptions={expected - actual}'


def test_every_powershell_spawn_bypasses_execution_policy():
    commands = [(path, line, valid) for path, tree in trees(ROOT) for line, valid in powershell_commands(tree)]
    assert commands, 'PowerShell inventory must not silently become empty'
    assert not [(path, line) for path, line, valid in commands if not valid]


def test_http_ratchet_catches_aliases_and_injected_openers():
    source = 'import urllib.request as u\nfrom urllib.request import urlopen as op\nu.Request("x")\nop("x")\n(opener or op)("x")'
    assert raw_http_sites(ast.parse(source)) == [3, 4, 5]


def test_powershell_ratchet_checks_position_alias_and_absolute_path():
    for executable in ['"powershell.exe"', '"C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"',
                       'str(canonical_windows_powershell())']:
        good = ast.parse(f'args = [{executable}, "-ExecutionPolicy", "Bypass", "-Command", script]')
        bad = ast.parse(f'args = [{executable}, "-Command", script, "-ExecutionPolicy", "Bypass"]')
        assert list(powershell_commands(good)) == [(1, True)]
        assert list(powershell_commands(bad)) == [(1, False)]
