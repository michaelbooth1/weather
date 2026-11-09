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
    assert root.is_relative_to(allowed) and root.name.startswith('test_day_one_twenty_forty_fina')
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
