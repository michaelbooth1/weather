"""Strict evidence parsing, crash-atomic publication and explicit corruption recovery.

Recovery never replaces a final file. A separate immutable manifest binds the
original bytes to a validated replacement; readers refuse conflicting manifests.
"""
from __future__ import annotations

import hashlib
import base64
import json
import os
from pathlib import Path
import uuid
from datetime import datetime, timezone


RECOVERY_SCHEMA = 'lfc_recording_recovery_v0.1'
READ_SCHEMA = 'lfc_recording_read_v0.1'
# Cumulative campaign observations through Dec31 (12 bands/day) can exceed
# the original 16 MB state cap. All state writers/readers share this bound.
STATE_JSON_LIMIT = 96_000_000


def clock_text(clock):
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('recording_observation_clock')
    return value.astimezone(timezone.utc).isoformat()


class PublicReadFailure(ValueError):
    def __init__(self, code, *, status=None, raw=None, truncated=False):
        super().__init__(code)
        self.code, self.status, self.raw, self.truncated = code, status, raw, truncated


def retained(raw):
    result = {'sha256': hashlib.sha256(raw).hexdigest()}
    try:
        result['raw_response'] = raw.decode('utf-8')
    except UnicodeError:
        result['raw_base64'] = base64.b64encode(raw).decode('ascii')
    return result


def response_bytes(receipt):
    if ('raw_response' in receipt) == ('raw_base64' in receipt):
        raise ValueError('recording_response_shape')
    raw = (receipt['raw_response'].encode('utf-8') if 'raw_response' in receipt else
           base64.b64decode(receipt['raw_base64'], validate=True))
    if hashlib.sha256(raw).hexdigest() != receipt['sha256']:
        raise ValueError('recording_response_hash')
    return raw


def observed_get(directory, get, endpoint, params, *, clock):
    """Retain each requested public read, including bounded failed-response prefixes."""
    started = clock_text(clock)
    raw, status, failure, truncated = None, None, None, False
    try:
        raw = get(endpoint, dict(params))
        status = 200
        return raw
    except BaseException as exc:
        raw, status = getattr(exc, 'raw', None), getattr(exc, 'status', None)
        truncated = getattr(exc, 'truncated', False) is True
        failure = exc.code if isinstance(exc, PublicReadFailure) else type(exc).__name__
        raise
    finally:
        row = dict(schema_version=READ_SCHEMA, kind='lfc_recording_read', endpoint=endpoint,
                   query=dict(params), started_at_utc=started, ended_at_utc=clock_text(clock),
                   status=status, failure_code=failure,
                   response_truncated=truncated,
                   response=retained(raw) if isinstance(raw, bytes) else None)
        write_new(Path(directory) / (uuid.uuid4().hex + '.json'), row)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('recording_duplicate_json_key')
            result[key] = value
        return result

    def constant(value):
        raise ValueError('recording_nonfinite_json')

    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def read_bytes(path, limit):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('recording_file_budget')
    return raw


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def write_new(path, row, *, max_bytes=None):
    """Flush a same-directory attempt, then atomically publish without overwrite.

    The hard link is an exclusive create on NTFS and POSIX. Failed temporary
    attempts survive; only a successfully published duplicate link is removed.
    """
    raw = (json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False, default=str) + '\n').encode('utf-8')
    if max_bytes is not None and len(raw) > max_bytes:
        raise ValueError('recording_file_budget')
    # canonical_bytes uses json.dumps; reject nonstandard constants before I/O.
    strict_json(raw)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.attempt-' + uuid.uuid4().hex)
    with temporary.open('xb') as stream:
        if stream.write(raw) != len(raw):
            raise OSError('recording_short_write')
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, path)
    temporary.unlink()


def prepare_recovery(path, *, clock, reason):
    path = Path(path)
    identity = uuid.uuid4().hex
    replacement = path.with_name(path.stem + '-recovery-' + identity + path.suffix)
    manifest = dict(schema_version=RECOVERY_SCHEMA, kind='lfc_recording_recovery',
                    observed_at_utc=clock_text(clock), original=path.name,
                    original_sha256=file_sha(path), replacement=replacement.name,
                    reason=reason, recovery_id=identity, state='STARTED')
    write_new(path.parent / 'recovery' / (identity + '-started.json'), manifest)
    return replacement, manifest


def publish_recovery(path, manifest):
    path = Path(path)
    row = dict(manifest, state='PUBLISHED', replacement_sha256=file_sha(path))
    write_new(path.parent / 'recovery' / (manifest['recovery_id'] + '-published.json'), row)


def read_recovered(path, validate):
    """A corrupt original needs a hash-bound published recovery, never a silent skip."""
    path = Path(path)
    try:
        return validate(path), path
    except (ValueError, KeyError, TypeError, UnicodeError) as original_error:
        original_sha = file_sha(path)
        candidates = []
        for index, candidate in enumerate((path.parent / 'recovery').glob('*-published.json')):
            if index >= 1000:
                raise ValueError('recording_recovery_budget')
            manifest = strict_json(read_bytes(candidate, 65536))
            if manifest.get('original') != path.name or manifest.get('original_sha256') != original_sha:
                continue
            name = manifest.get('replacement')
            if (manifest.get('schema_version') != RECOVERY_SCHEMA or manifest.get('state') != 'PUBLISHED' or
                    not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name or
                    not name.startswith(path.stem + '-recovery-')):
                raise ValueError('recording_recovery_scope')
            replacement = path.parent / name
            if file_sha(replacement) != manifest.get('replacement_sha256'):
                raise ValueError('recording_recovery_hash')
            candidates.append((validate(replacement), replacement))
        if len(candidates) > 1:
            raise ValueError('recording_recovery_conflict')
        if candidates:
            return candidates[0]
        raise original_error
