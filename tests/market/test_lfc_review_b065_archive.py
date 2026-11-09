"""Guards: bounded B065 fixture archives preserve every byte before reclaiming space.

Only an explicitly supplied test-owned synthetic benchmark directory is allowed.
No pilot, credentials, venue, reader or production evidence paths are accepted.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import zipfile
import pytest

from tests.market.test_lfc_f2_capital import MAKER
from weather.operations.live_path_security import validate_nonreparse_directory


def hashed(stream):
    result = hashlib.sha256()
    for part in iter(lambda: stream.read(1024*1024), b''): result.update(part)
    return result.hexdigest()


def test_archive_only_verified_synthetic_benchmark_bytes(pytestconfig, tmp_path):
    argument = pytestconfig.getoption('--lfc-existing-scale', default=None)
    if not argument: pytest.skip('Explicit task-owned synthetic fixture required')
    root = Path(argument).resolve(strict=True)
    allowed = Path(r'C:\t\codex\T004\pt').resolve(strict=True)
    assert root.is_relative_to(allowed) and root.name.startswith((
        'test_day_one_twenty_forty_fina', 'test_day_one_twenty_final_c'))
    validate_nonreparse_directory(root)
    with (root/'ledger.jsonl').open('rb') as stream:
        genesis = json.loads(stream.readline(1024*1024))
    assert genesis['event']=='genesis' and genesis['maker_address'].lower()==MAKER.lower()
    files = []; pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for item in entries:
                info = item.stat(follow_symlinks=False)
                assert not getattr(info, 'st_file_attributes', 0) & 0x400
                assert not item.is_symlink()
                path = Path(item.path)
                assert path.resolve(strict=True).is_relative_to(root)
                if item.is_dir(follow_symlinks=False): pending.append(path)
                else:
                    assert not path.name.startswith('.env') and path.suffix not in {'.key','.cred','.pem'}
                    files.append(path)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    target = Path(r'C:\t\codex\T004\out')/('b065-synthetic-'+stamp+'.zip')
    inventory = {}
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            sha = hashlib.sha256(); count = 0
            with path.open('rb') as source, archive.open(relative, 'w') as dest:
                for part in iter(lambda: source.read(1024*1024), b''):
                    sha.update(part); count += len(part); dest.write(part)
            inventory[relative] = {'sha256':sha.hexdigest(), 'bytes':count}
    # Verify the complete archive and unchanged sources before deleting a leaf.
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == set(inventory)
        for name, metadata in inventory.items():
            with archive.open(name) as stream: assert hashed(stream)==metadata['sha256']
            with (root/name).open('rb') as stream: assert hashed(stream)==metadata['sha256']
    manifest = {'synthetic_only':True, 'source_root':str(root), 'archive':str(target),
                'verified_members':inventory, 'reclaimed_bytes':sum(v['bytes'] for v in inventory.values())}
    with target.open('rb') as stream: manifest['archive_sha256']=hashed(stream)
    target.with_suffix('.json').write_text(json.dumps(manifest, indent=2))
    for name in inventory:
        path = (root/name).resolve(strict=True)
        assert path.is_relative_to(root) and path.is_relative_to(allowed)
        path.unlink()  # Exact task-owned leaves; byte-identical verified archive retained.
    assert not any(path.is_file() for path in root.rglob('*'))
    (tmp_path/'archive.json').write_text(json.dumps({k:v for k,v in manifest.items() if k!='verified_members'}, indent=2))


def test_restore_verified_synthetic_archive_without_overwriting(pytestconfig):
    argument=pytestconfig.getoption('--lfc-scale-archive',default=None)
    root_argument=pytestconfig.getoption('--lfc-existing-scale',default=None)
    if not argument or not root_argument:pytest.skip('Explicit synthetic archive required')
    from tests.market.test_lfc_review_b065_remeasure import bounded
    from weather.market.lfc_ledger import Ledger
    from weather.market.lfc_recording_io import read_bytes, strict_json
    root=Path(root_argument).absolute()
    allowed=Path(r'C:\t\codex\T004\pt').resolve(strict=True)
    assert root.is_relative_to(allowed) and root.name.startswith('test_day_one_twenty_forty_fina')
    validate_nonreparse_directory(root)
    archive_path=Path(argument).resolve(strict=True)
    assert archive_path.parent==Path(r'C:\t\codex\T004\out')
    assert archive_path.name.startswith('b065-synthetic-') and archive_path.suffix=='.zip'
    manifest=strict_json(read_bytes(archive_path.with_suffix('.json'),16*1024**2))
    assert manifest['synthetic_only'] is True and Path(manifest['source_root'])==root
    with bounded(),archive_path.open('rb') as stream:
        assert hashed(stream)==manifest['archive_sha256']
        with zipfile.ZipFile(archive_path) as archive:
            inventory=manifest['verified_members']
            assert len(archive.namelist())==len(inventory) and set(archive.namelist())==set(inventory)
            with archive.open('ledger.jsonl') as genesis:
                assert json.loads(genesis.readline(1024*1024))['maker_address'].lower()==MAKER.lower()
            for name,metadata in inventory.items():
                relative=Path(name)
                assert not relative.is_absolute() and '..' not in relative.parts
                assert not any(part.startswith('.env') for part in relative.parts)
                assert relative.suffix not in {'.key','.cred','.pem'}
                path=root/relative
                path.parent.mkdir(parents=True,exist_ok=True)
                validate_nonreparse_directory(path.parent)
                assert path.resolve(strict=False).is_relative_to(root)
                if path.exists():
                    assert not path.is_symlink() and not path.stat().st_file_attributes & 0x400
                    with path.open('rb') as original:assert hashed(original)==metadata['sha256']
                    continue
                sha=hashlib.sha256();size=0
                with archive.open(name) as source,path.open('xb') as dest:
                    for block in iter(lambda:source.read(1024*1024),b''):
                        sha.update(block);size+=len(block);dest.write(block)
                assert size==metadata['bytes'] and sha.hexdigest()==metadata['sha256']
        ledger=Ledger.open(root/'ledger.jsonl',clock=lambda:datetime.now(timezone.utc),maker_address=MAKER)
        assert len(ledger.autostart_claims)==40 and not ledger.open_sessions() and not ledger.unresolved_legs()


def test_archive_delta_against_a_verified_synthetic_base(pytestconfig):
    """Preserve new measurements without making a second 435 MB fixture copy."""
    argument=pytestconfig.getoption('--lfc-scale-archive',default=None)
    root_argument=pytestconfig.getoption('--lfc-existing-scale',default=None)
    if not argument or not root_argument:pytest.skip('Explicit synthetic archive required')
    from tests.market.test_lfc_review_b065_remeasure import bounded
    from weather.market.lfc_recording_io import read_bytes,strict_json
    root=Path(root_argument).resolve(strict=True)
    assert root.is_relative_to(Path(r'C:\t\codex\T004\pt'))
    assert root.name.startswith('test_day_one_twenty_forty_fina')
    validate_nonreparse_directory(root)
    base=Path(argument).resolve(strict=True)
    assert base.parent==Path(r'C:\t\codex\T004\out') and base.name.startswith('b065-synthetic-')
    original=strict_json(read_bytes(base.with_suffix('.json'),16*1024**2))
    assert original['synthetic_only'] is True and Path(original['source_root'])==root
    files=[];pending=[root]
    while pending:
        directory=pending.pop()
        validate_nonreparse_directory(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                assert not entry.is_symlink() and not entry.stat(follow_symlinks=False).st_file_attributes & 0x400
                path=Path(entry.path)
                if entry.is_dir(follow_symlinks=False):pending.append(path)
                else:
                    assert not path.name.startswith('.env') and path.suffix not in {'.key','.cred','.pem'}
                    assert path.resolve(strict=True).is_relative_to(root)
                    files.append(path)
    target=base.parent/('b065-synthetic-delta-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.zip')
    inventory={}
    with bounded(),base.open('rb') as stream:
        assert hashed(stream)==original['archive_sha256']
        with zipfile.ZipFile(base) as prior,zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1) as delta:
            assert set(prior.namelist())==set(original['verified_members'])
            with prior.open('ledger.jsonl') as genesis:
                assert json.loads(genesis.readline(1024*1024))['maker_address'].lower()==MAKER.lower()
            for path in files:
                name=path.relative_to(root).as_posix()
                with path.open('rb') as source:sha=hashed(source)
                old=original['verified_members'].get(name)
                origin='base' if old and old['sha256']==sha else 'delta'
                inventory[name]={'sha256':sha,'bytes':path.stat().st_size,'archive_source':origin}
                if origin=='delta':delta.write(path,name)
                assert target.stat().st_size<8*1024**2,'bounded delta output'
        with zipfile.ZipFile(base) as prior,zipfile.ZipFile(target) as delta:
            assert set(delta.namelist())=={name for name,row in inventory.items() if row['archive_source']=='delta'}
            for name,row in inventory.items():
                archive=prior if row['archive_source']=='base' else delta
                with archive.open(name) as source:assert hashed(source)==row['sha256']
                with (root/name).open('rb') as source:assert hashed(source)==row['sha256']
        with target.open('rb') as stream:delta_sha=hashed(stream)
        target.with_suffix('.json').write_text(json.dumps({'synthetic_only':True,'source_root':str(root),
            'base_archive':str(base),'base_archive_sha256':original['archive_sha256'],
            'archive':str(target),'archive_sha256':delta_sha,'verified_members':inventory},indent=2))
        for name in inventory:
            path=(root/name).resolve(strict=True)
            assert path.is_relative_to(root)
            path.unlink()  # Both archives and the current source were verified above.
