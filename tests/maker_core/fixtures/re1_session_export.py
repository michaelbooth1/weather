"""Explicit-path, guard-first fixture derivation for the owner-authorized 110l read.

No discovery, default campaign path, output writes, account imports or network.
SecretGuard below is copied unchanged from re1_attended.py at GUARD_REF.
The caller must supply only authorized session-N/journal.jsonl paths.
"""
import hashlib
import json
from pathlib import Path
import re
import stat

from maker_core.evidence.journal import canonical_bytes

GUARD_REF = '2b9a0ca9e586d510b4aa879fad8f0e7331cfe2c8'


class SecretGuard:
    """Drop auth/signature fields, then refuse any residual loaded secret."""
    def __init__(self, secrets=()):
        self.secrets = tuple(s for s in secrets if s)

    def clean(self, value):
        if hasattr(value, 'model_dump'):
            value = value.model_dump(mode='json')
        if isinstance(value, dict):
            value = {k: self.clean(v) for k, v in value.items()
                     if str(k).lower().replace('_', '') not in {
                         'headers', 'auth', 'authorization', 'signature', 'secret',
                         'apikey', 'apisecret', 'passphrase', 'privatekey'} and
                     not (str(k).lower() == 'owner' and isinstance(v, str) and v in self.secrets)}
        elif isinstance(value, (tuple, list)):
            value = [self.clean(v) for v in value]
        encoded = canonical_bytes(value).decode('utf-8')
        if any(s in encoded or json.dumps(s)[1:-1] in encoded for s in self.secrets):
            raise RuntimeError('secret_output_refused')
        return value

    def print(self, value):
        print(self.clean(value), flush=True)


def check_secrets(row):
    # A guard that silently scrubs is insufficient for this owner's STOP rule.
    if SecretGuard().clean(row) != row:
        raise ValueError('STOP: existing secret guard changed journal content')

    def inspect(value, location=()):
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = re.sub('[^a-z]', '', key.lower())
                label = key if re.fullmatch('[A-Za-z_]{1,64}', key) else '<field>'
                path = (*location, label)
                # Owner-approved field-name-only classification traced this to
                # mm_official_adapter.py at GUARD_REF: normalized order/trade
                # events copy order_id into lifecycle_key. It is not a secret.
                order_identity = (key == 'lifecycle_key' and isinstance(child, str) and bool(child)
                                  and child == value.get('order_id')
                                  and value.get('source') == 'polymarket_global_user_ws'
                                  and value.get('official_event_type') in ('order', 'trade'))
                if any(s in normalized for s in ('key', 'secret', 'passphrase', 'password',
                                                  'signature', 'credential', 'mnemonic',
                                                  'authorization', 'bearer', 'cookie')) and not order_identity:
                    raise ValueError('STOP: credential-like field at ' + '.'.join(path))
                inspect(child, path)
        elif isinstance(value, list):
            for child in value:
                inspect(child, (*location, '[]'))
        elif isinstance(value, str):
            if re.search(r'-----BEGIN .*PRIVATE KEY|\bBearer\s+\S+|\b0x[0-9a-fA-F]{130}\b|'
                         r'\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.', value):
                raise ValueError('STOP: credential-like value')
    inspect(row)


def read_guarded(path):
    path = Path(path)
    if path.name != 'journal.jsonl' or not re.fullmatch(r'session-[1-9][0-9]*', path.parent.name):
        raise ValueError('only explicit session journal paths are allowed')
    for part in (path, *path.parents):
        info = part.lstat()
        if getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT or part.is_symlink():
            raise ValueError('redirected journal path')
    with path.open('rb') as handle:
        raw = handle.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError('journal byte bound')
    rows = []
    previous = None
    for sequence, line in enumerate(raw.splitlines(keepends=True)):
        row = json.loads(line)
        check_secrets(row)  # Before semantic inspection, projection or printing.
        if row['sequence'] != sequence or row['previous_sha256'] != previous or canonical_bytes(row) != line:
            raise ValueError('journal hash chain differs')
        previous = hashlib.sha256(line).hexdigest()
        rows.append(row)
    if not rows or rows[0]['event'] != 'opened' or rows[-1]['event'] != 'terminal':
        raise ValueError('incomplete journal')
    if sum(r['event'] == 'terminal' for r in rows) != 1:
        raise ValueError('multiple terminal records')
    return hashlib.sha256(raw).hexdigest(), len(raw), rows


def snapshot_frame(row):
    snapshot = row['snapshot']
    raw = snapshot['quote_inputs']
    values = {k: str(raw[k]) for k in ('tick', 'reward_min_size', 'reward_max_spread_cents', 'reward_rate_per_day')}
    values['post_only_available'] = raw['post_only_available']
    for name in ('yes_bids', 'yes_asks', 'no_bids', 'no_asks'):
        values[name] = [[str(v['price']), str(v['size'])] for v in raw[name]]
    return dict(at=row['recorded_at_utc'], observed_at=snapshot['observed_at_utc'], quote_inputs=values)


def project_journals(paths, selections):
    paths = tuple(Path(p) for p in paths)
    if not paths or len(paths) > 30 or len(set(paths)) != len(paths):
        raise ValueError('bounded unique journal list required')
    files = [(p, *read_guarded(p)) for p in paths]  # Guard ALL inputs before any projection.
    sessions = []
    for path, sha, size_bytes, rows in files:
        attempt = int(path.parent.name.split('-')[1])
        frozen = next(r for r in selections if r['attempt'] == attempt)
        if frozen['source_journal_sha256'] != sha:
            raise ValueError('journal differs from frozen selection fixture binding')
        terminal = rows[-1]
        session = dict(attempt=attempt, session=None if terminal['submits'] == 0 else rows[1]['attempt']['session_number'],
                       source_journal_sha256=sha, source_bytes=size_bytes, source_rows=len(rows),
                       size=frozen['size'], initial_prices=frozen['expected_prices'],
                       initial_prices_source_selection_sha256=frozen['source_selection_sha256'],
                       fixed_end_at=rows[1]['fixed_end_at_utc'],
                       opening=snapshot_frame(next(r for r in rows if 'snapshot' in r)), minutes=[],
                       terminal=dict(at=terminal['recorded_at_utc'], reason=terminal['reason'],
                                     fill_seen=terminal['fill_seen'], requotes=terminal['requotes'],
                                     submits=terminal['submits']),
                       missing_minutes=sum(r['event'] == 'minute_missed' for r in rows))
        last_snapshot = None
        for row in rows:
            if row['event'] == 'market_snapshot':
                last_snapshot = row
            elif row['event'] == 'minute':
                if last_snapshot is None or last_snapshot['snapshot'] != row['snapshot']:
                    raise ValueError('minute snapshot binding differs')
                frame = snapshot_frame(last_snapshot)
                frame.update(sequence=row['sequence'], recorded_at=row['recorded_at_utc'], prices=row['prices'],
                             requote_legs=row['observation']['requote_legs'])
                session['minutes'].append(frame)
        sessions.append(session)
    for path, sha, _, _ in files:
        # Guard again before using bytes for the after-read stability binding.
        if read_guarded(path)[0] != sha:
            raise ValueError('source changed during projection')
    return dict(format='re1-session-decision-projection-1',
                guard_source=GUARD_REF + ':src/weather/market/re1_attended.py:SecretGuard',
                sessions=sorted(sessions, key=lambda s: s['attempt']))
