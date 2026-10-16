"""LFC owner-run session driver (weather.market.lfc_session_driver): orchestration over fake children, fake clock.

Guards: the session-1 driver contract (docs/research/live-fill-calibration-session1-runbook-2026-10-16.md, Driver):
it calls every pinned-CLI gate as a child and never bypasses one; it never writes to a child's stdin, so every `go` and
`attest` phrase is typed by the owner; the neg_risk screen of clarification D, D8 (session 0: false only; counted
sessions: true or false; missing/None/non-bool/mixed refuses); pin review e27909a76..6bc6f2bec SF-1 (per-spender
allowance of the band's exchange path) and SF-2 (neg_risk and fee class printed before go and after the run, a
rejected first neg-risk post flagged as a signing-contract suspect); the session-0 reader-cap finding (Wait-ReaderQuiet
and ONE retry, then FAIL); stop on the first FAIL/refusal with pack.json + summary.txt always written; owner Ctrl+C
kills the child tree (Windows job object, kill-on-close) with stopped_reason=owner_interrupt; the --to-go-prompt dry
run never releases the go line and kills live; the runbook section 8 "send to master" fields in every pack.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from weather.market import lfc_cli
from weather.market import lfc_session_driver as D

SHA = 'a' * 40
COND = '0xcond'
T24_AT = '2026-10-17T14:00:00+00:00'
NOW = datetime(2026, 10, 18, 15, 0, 0, tzinfo=timezone.utc)
ENOUGH = str(10 ** 9)


class FakeClock:
    def __init__(self, now):
        self.t = now

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += timedelta(seconds=seconds)


class FakeConsole:
    def __init__(self, tty=True):
        self.lines, self.tty = [], tty

    def say(self, text):
        self.lines.extend(str(text).splitlines())

    def isatty(self):
        return self.tty


class FakeProc:
    """A child: yields its lines (a callable line runs its side effect when the driver reads it), then EOF.
    `interrupts` lists, per Ctrl+C, how many lines must have been read before poll_line raises KeyboardInterrupt."""

    def __init__(self, key, argv, interactive, lines, code, interrupts=()):
        self.key, self.argv, self.interactive = key, argv, interactive
        self.pending, self.code, self.interrupts = list(lines), code, list(interrupts)
        self.killed, self.closed, self.yielded = None, False, []

    def poll_line(self, timeout):
        if self.interrupts and len(self.yielded) >= self.interrupts[0] and not self.killed:
            self.interrupts.pop(0)
            raise KeyboardInterrupt
        if self.killed or not self.pending:
            return D.EOF
        item = self.pending.pop(0)
        item = item() if callable(item) else item
        self.yielded.append(item)
        return item

    def wait(self):
        return 1 if self.killed else self.code

    def kill_tree(self):
        self.killed = 'job'
        return 'job'

    def close(self):
        self.closed = True


def append_ledger(root, **row):
    with open(root / 'ledger.jsonl', 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(row) + '\n')


def write_baseline(root, label, at, *, collateral='100', maker='0xmaker'):
    body = {'schema_version': D.BASELINE_SCHEMA, 'maker_address': maker, 'open_order_ids': [], 'positions': {},
            'available_collateral': collateral}
    raw = json.dumps(body).encode()
    name = f"baseline-{label}-{at.strftime('%Y%m%dT%H%M%S%f')}Z.json"
    (root / name).write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    append_ledger(root, event='baseline', label=label, file=name, sha256=sha, at_utc=at.isoformat())
    return name, sha


class World:
    """The fake pinned CLI, reader and host: one handler per child kind, scripted overrides consumed in order."""

    def __init__(self, tmp_path, clock, *, neg_risk=(False, False), t24_at=T24_AT):
        self.pin, self.root, self.snap = tmp_path / 'pin', tmp_path / 'root', tmp_path / 'snap'
        self.pin.mkdir()
        self.root.mkdir()
        self.clock, self.neg_risk = clock, neg_risk
        self.allowances = {a.lower(): ENOUGH for a in D.SPENDERS.values()}
        self.overrides, self.procs, self.counter = {}, [], 0
        self.live_mode, self.end_reason, self.cleanup_ok = 'ok', 'fixed_end', True
        self.final_collateral = '100'
        self.interrupts = {}
        (self.root / 'ledger.jsonl').write_text('')  # init-ledger ran before any session
        if t24_at:
            write_baseline(self.root, 't24', datetime.fromisoformat(t24_at))

    def keyed(self, argv):
        if argv[0] == 'git':
            return 'git_' + argv[3]
        if argv[0] == 'powershell.exe':
            return 'host_free' if 'MUTEX' in argv[-1] else 'assignment'
        if argv[1] == '-c':
            return 'interpreter' if 'econ_loaded' in argv[2] else 'open_orders'
        if argv[2] == 'weather.market.wallet_reader_client':
            return 'snapshot'
        return argv[3]

    def start(self, argv, *, interactive=False):
        key = self.keyed(argv)
        scripted = self.overrides.get(key)
        lines, code = scripted.pop(0) if scripted else getattr(self, 'h_' + key.replace('-', '_'))(argv)
        proc = FakeProc(key, argv, interactive, lines, code, self.interrupts.pop(key, ()))
        self.procs.append(proc)
        return proc

    def stamp(self):
        self.counter += 1
        return f"{self.clock.now().strftime('%Y%m%dT%H%M%S')}{self.counter:06d}Z"

    # --- handlers ---
    def h_git_rev_parse(self, argv):
        return [SHA], 0

    def h_git_status(self, argv):
        return [], 0

    def h_git_worktree(self, argv):
        return ['worktree C:/elsewhere', 'HEAD x', '', f'worktree {self.pin}', 'HEAD ' + SHA, 'detached', 'locked'], 0

    def h_interpreter(self, argv):
        return ['econ_loaded=False', 'version=3.11.9', f"weather={self.pin / 'weather' / '__init__.py'}",
                f"lfc_cli={self.pin / 'src' / 'weather' / 'market' / 'lfc_cli.py'}", f'repo_root={self.pin}',
                'sdk=0.6.0'], 0

    def h_assignment(self, argv):
        return [D.EXPECTED_ASSIGNMENT_LINE], 0

    def h_host_free(self, argv):
        return ['holder=null', 'poison=False', 'queued=0', 'MUTEX FREE'], 0

    def h_open_orders(self, argv):
        return ['0'], 0

    def h_snapshot(self, argv):
        return ['{"rows": []}'], 0

    def h_baseline(self, argv):
        label = argv[argv.index('--label') + 1]
        posted = any(r.get('event') == 'session_start' for r in D.ledger_rows(self.root))
        name, sha = write_baseline(self.root, label, self.clock.now(),
                                   collateral=self.final_collateral if posted else '100')
        return [str({'baseline': name, 'sha256': sha, 'positions': 0, 'open_orders': 0, 'status': 'PASS'})], 0

    def selection(self):
        rules = {'t1': {'neg_risk': self.neg_risk[0]}, 't2': {'neg_risk': self.neg_risk[1]}}
        return {'selected_condition_id': COND, 'rows': [
            {'condition_id': COND, 'token_ids': ['t1', 't2'], 'snapshot': {'rules': rules},
             'fee': {'fee_class': 'fee_free'}}]}

    def h_preflight(self, argv):
        folder = self.root / ('preflight-' + self.stamp())
        folder.mkdir()
        (folder / 'selection.json').write_text(json.dumps(self.selection()))
        (folder / 'preflight.json').write_text(json.dumps({'status': 'PASS'}))
        balances = {'available_collateral': '100', 'collateral_evidence': {'balance': '1', 'allowances': self.allowances}}
        (folder / 'journal.jsonl').write_text(
            json.dumps({'event': 'preflight_read', 'step': 'balances', 'response': balances}) + '\n')
        return ['PASS proxy_host_tip', str({'status': 'PASS', 'receipt': str(folder / 'preflight.json')})], 0

    def post(self):
        """What the pinned live does after the owner typed the right phrase: a session in the ledger, its files."""
        directory = 'session-' + self.stamp()
        (self.root / directory).mkdir()
        append_ledger(self.root, event='session_start', session_id='S1', directory=directory)
        (self.root / directory / 'session_end.json').write_text(json.dumps(
            {'reason': self.end_reason, 'cleanup_ok': self.cleanup_ok, 'panic': False,
             'notification': {'toast_delivered': True}}))
        (self.root / directory / 'journal.jsonl').write_text(''.join(
            json.dumps({'event': 'submit_request', 'request': {'expiration': 1760820000}}) + '\n' for _ in range(2)))
        (self.root / directory / 'selection.json').write_text(json.dumps(self.selection()))
        return (f'LFC-RESULT session_id=S1 reason={self.end_reason} cleanup_ok={self.cleanup_ok} panic=False L=0 '
                'L_filled=0 L_resting=0 open_orders=0 fills=0')

    def h_live(self, argv):
        confirm = str({'condition': COND, 'event_slug': 'nyc-high', 'quote': {'bid': '0.30'}, 'selection_sha256': 'b',
                       'size': '40', 'run': None, 'minutes': 360})
        if self.live_mode == 'refused_gate':
            return [str({'status': 'REFUSED', 'refusals': ['baseline_t24_age']})], 1
        if self.live_mode == 'wrong_phrase':
            return [confirm, 'Type: go abc123', str({'status': 'REFUSED', 'exception_type': 'RuntimeError',
                                                     'code': 'owner_confirmation_refused'})], 1
        return [confirm, 'Type: go abc123', self.post], 0

    def h_verify(self, argv):
        return [str({'status': 'PASS', 'our_open_orders': 0, 'foreign_open_orders': 0, 'open_sessions': 0,
                     'counted_sessions': 1, 'L': '0'})], 0

    def h_wallet_verify(self, argv):
        return [str({'status': 'PASS', 's0_1': 'PASS', 's0_6': 'PASS', 'open_orders': 0, 'ledger_L': '0',
                     'venue_L': '0', 'l_difference': '0', 'positions_reader_status': 'OBSERVED',
                     'positions_changed_outside_pilot': []})], 0

    def h_session0_attest(self, argv):
        return [str({'runs': 'ok'}), 'Type: attest session0 abcdef', str({'status': 'ATTESTED', 'file': 'pass.json',
                                                                         'sha256': 'c'})], 0

    def of(self, key):
        return [p for p in self.procs if p.key == key]


def drive(world, clock, console=None, **config):
    console = console or FakeConsole()
    cfg = D.DriverConfig(pin=world.pin, expect_commit=SHA, root=world.root, snap_dir=world.snap, python='py',
                         **config)
    pack, sha = D.SessionDriver(cfg, runner=world, clock=clock, console=console).run()
    folder = world.root / pack['pack_folder']
    assert json.loads((folder / 'pack.json').read_bytes())['stopped_reason'] == pack['stopped_reason']
    assert (folder / 'summary.txt').read_text(encoding='utf-8').startswith('LFC session driver pack')
    return pack, console


@pytest.fixture
def clock():
    return FakeClock(NOW)


@pytest.fixture
def world(tmp_path, clock):
    return World(tmp_path, clock)


def posted(world):
    return any(r.get('event') == 'session_start' for r in D.ledger_rows(world.root))


# ----- happy paths ---------------------------------------------------------------------------------------------------
def test_counted_session_runs_every_step_in_order_and_writes_the_pack(world, clock):
    pack, console = drive(world, clock)
    assert pack['stopped_reason'] == 'session_complete' and pack['stop_code'] is None
    order = [p.key for p in world.procs]
    assert order.index('git_rev-parse') < order.index('host_free') < order.index('open_orders') < \
        order.index('snapshot') < order.index('baseline') < order.index('preflight') < order.index('live') < \
        order.index('verify') < order.index('wallet-verify') < len(order) - 1 - order[::-1].index('baseline')
    assert [p.key for p in world.procs if p.interactive] == ['preflight', 'live']  # owner console stdin only there
    assert pack['runs'][0]['reason'] == 'fixed_end' and pack['runs'][0]['cleanup_ok'] is True
    assert pack['runs'][0]['submit_expirations'] == ['1760820000']
    assert pack['runs'][0]['session_selection_neg_risk'] == {'t1': False, 't2': False}
    assert pack['selection_screen']['status'] == 'PASS' and pack['selection_screen']['fee_class'] == 'fee_free'
    assert pack['latest_legal_live_start_utc'] == '2026-10-18T17:50:00Z'
    assert pack['compare_lines'][0].startswith('start: PASS') and pack['compare_lines'][-1].startswith('final: PASS')
    assert 'Type: go abc123' in console.lines  # released only after the screen
    assert console.lines.index('Type: go abc123') > next(i for i, l in enumerate(console.lines)
                                                         if l.startswith('SCREEN PASS'))
    snaps = sorted(p.name for p in world.snap.iterdir())
    assert len(snaps) == 6 and len(pack['snapshot_hash_lines']) == 6


def test_every_section8_field_is_in_the_pack_and_the_summary(world, clock):
    pack, _ = drive(world, clock)
    for key in D.MASTER_FIELDS:
        assert key in pack
    for key in set(D.MASTER_FIELDS) - {'action', 'attestation', 'stop_step', 'stop_code', 'refusal_codes'}:
        assert pack[key] not in (None, [], {}), key
    for key in D.RUN_FIELDS:
        assert key in pack['runs'][0]
    summary = (world.root / pack['pack_folder'] / 'summary.txt').read_text(encoding='utf-8')
    for key in D.MASTER_FIELDS:
        assert key in summary
    assert '0xmaker' not in summary and '0xmaker' not in json.dumps(pack)  # no address in the paste block


def test_t24_phase_takes_the_snapshot_and_baseline_only(world, clock):
    pack, _ = drive(world, clock, phase='t24')
    assert pack['stopped_reason'] == 't24_complete'
    assert 'preflight' not in [p.key for p in world.procs] and 'live' not in [p.key for p in world.procs]
    assert D.latest_baseline_row(world.root, 't24')['file'] == pack['t24']['file']


# ----- neg_risk screen (clarification D, D8) and pin review SF-1 / SF-2 ---------------------------------------------
def test_counted_session_may_sign_a_neg_risk_band_and_prints_it_before_go_and_after(tmp_path, clock):
    world = World(tmp_path, clock, neg_risk=(True, True))
    pack, console = drive(world, clock)
    assert pack['stopped_reason'] == 'session_complete'
    screen = next(l for l in console.lines if l.startswith('SCREEN PASS'))
    assert "neg_risk={'t1': True, 't2': True}" in screen and 'fee_class=fee_free' in screen
    assert any('signing-contract suspect' in l for l in console.lines)
    assert any(l.startswith("AFTER-RUN neg_risk={'t1': True, 't2': True} fee_class=fee_free") for l in console.lines)
    assert pack['runs'][0]['neg_risk_signing_suspect'] is False


def test_a_rejected_first_neg_risk_post_is_flagged_as_a_signing_suspect(tmp_path, clock):
    world = World(tmp_path, clock, neg_risk=(True, True))
    world.end_reason = 'submit_acknowledgment'
    pack, console = drive(world, clock)
    assert pack['runs'][0]['neg_risk_signing_suspect'] is True
    assert any('SIGNING-CONTRACT SUSPECT' in l for l in console.lines)


@pytest.mark.parametrize('values,code', [
    ((None, None), 'neg_risk_missing_or_not_bool'), (('true', 'true'), 'neg_risk_missing_or_not_bool'),
    ((True, False), 'neg_risk_differs_between_tokens')])
def test_counted_neg_risk_screen_refuses_missing_or_mixed_and_posts_nothing(tmp_path, clock, values, code):
    world = World(tmp_path, clock, neg_risk=values)
    pack, console = drive(world, clock)
    assert (pack['stopped_reason'], pack['stop_code']) == ('REFUSED', code)
    assert world.of('live')[0].killed == 'job' and not posted(world)
    assert not any(l.startswith('Type: go') for l in console.lines)


def test_session0_refuses_a_neg_risk_band_but_accepts_a_plain_one(tmp_path, clock):
    world = World(tmp_path, clock, neg_risk=(True, True), t24_at=None)
    pack, _ = drive(world, clock, session0_runs=('0a',))
    assert pack['stop_code'] == 'neg_risk_true_not_allowed' and not posted(world)
    (tmp_path / 'b').mkdir()
    other = World(tmp_path / 'b', clock, t24_at=None)
    pack, _ = drive(other, clock, session0_runs=('0a',))
    assert pack['stopped_reason'] == 'session_complete'
    assert '--session0' in other.of('live')[0].argv and '--run' in other.of('live')[0].argv


@pytest.mark.parametrize('spender', ['neg_risk_exchange', 'neg_risk_adapter'])
def test_a_neg_risk_band_needs_each_neg_risk_spender_allowance(tmp_path, clock, spender):
    world = World(tmp_path, clock, neg_risk=(True, True))
    world.allowances[D.SPENDERS[spender].lower()] = str(int(39.2 * 10 ** 6) - 1)  # one unit below 0.98 x 40
    pack, _ = drive(world, clock)
    assert pack['stop_code'] == f'allowance_{spender}_below_band_cap' and not posted(world)
    assert world.of('live')[0].killed == 'job'


def test_a_plain_band_needs_the_standard_exchange_allowance_not_the_neg_risk_ones(tmp_path, clock):
    world = World(tmp_path, clock)
    for name in ('neg_risk_exchange', 'neg_risk_adapter'):
        del world.allowances[D.SPENDERS[name].lower()]
    world.allowances[D.SPENDERS['standard_exchange'].lower()] = str(39_200_000)  # exactly the band cap
    assert drive(world, clock)[0]['stopped_reason'] == 'session_complete'
    (tmp_path / 'c').mkdir()
    world2 = World(tmp_path / 'c', clock)
    del world2.allowances[D.SPENDERS['standard_exchange'].lower()]
    assert drive(world2, clock)[0]['stop_code'] == 'allowance_standard_exchange_missing'


def test_the_spender_addresses_match_the_pinned_sdk():
    environments = pytest.importorskip('polymarket.environments')
    config = environments.PRODUCTION._config
    for name, address in D.SPENDERS.items():
        assert getattr(config, name) == address


def test_neg_risk_screen_pure():
    sel = {'rows': [{'condition_id': 'c', 'token_ids': ['a', 'b'],
                     'snapshot': {'rules': {'a': {'neg_risk': False}, 'b': {'neg_risk': False}}}}]}
    assert D.neg_risk_screen(sel, 'c', session0=True)[:2] == (True, None)
    assert D.neg_risk_screen(sel, 'c', session0=False)[:2] == (True, None)
    assert D.neg_risk_screen(sel, 'other', session0=False)[1] == 'neg_risk_row_missing'
    del sel['rows'][0]['snapshot']['rules']['b']['neg_risk']
    assert D.neg_risk_screen(sel, 'c', session0=False)[1] == 'neg_risk_missing_or_not_bool'
    assert D.neg_risk_screen(None, 'c', session0=False)[1] == 'neg_risk_row_missing'


# ----- reader discipline -----------------------------------------------------------------------------------------------
def test_a_reader_timeout_waits_for_quiet_and_retries_once(world, clock):
    world.overrides['open_orders'] = [(['ERR timeout'], 0)]
    pack, _ = drive(world, clock)
    assert pack['stopped_reason'] == 'session_complete'
    statuses = [s['status'] for s in pack['steps'] if s['step'] == 'open_order_count_start']
    assert statuses == ['RETRY', 'PASS']
    assert sum(1 for l in pack['reader_quiet_lines'] if l.startswith('open_order_count_start:')) == 2


def test_a_second_reader_timeout_fails_the_step(world, clock):
    world.overrides['open_orders'] = [(['ERR timeout'], 0), (['ERR refused'], 0)]
    pack, _ = drive(world, clock)
    assert (pack['stopped_reason'], pack['stop_step'], pack['stop_code']) == \
        ('FAIL', 'open_order_count_start', 'reader_refused')
    assert 'preflight' not in [p.key for p in world.procs]


def test_a_baseline_timeout_refusal_retries_once_but_a_real_failure_does_not(world, clock):
    timeout = [str({'status': 'REFUSED', 'exception_type': 'TimeoutError', 'code': None})]
    world.overrides['baseline'] = [(timeout, 1)]
    assert drive(world, clock)[0]['stopped_reason'] == 'session_complete'


def test_wallet_verify_err_fields_retry_once(world, clock):
    err = str({'status': 'ATTENTION', 's0_1': 'PASS', 's0_6': 'PASS', 'venue_L': 'ERR', 'open_orders': 0})
    world.overrides['wallet-verify'] = [([err], 1), ([err], 1)]
    pack, _ = drive(world, clock)
    assert (pack['stop_step'], pack['stop_code']) == ('wallet_verify', 'wallet_verify_reader_err')


def test_every_reader_step_starts_inside_the_quiet_window(world, clock):
    pack, _ = drive(world, clock)
    for line in pack['reader_quiet_lines']:
        fields = dict(part.split('=') for part in line.split(': ', 1)[1].split()[1:])
        assert 60 <= int(fields['phase_s']) <= 270 and int(fields['since_last_read_s']) >= 60


def test_reader_quiet_boundaries():
    at = datetime(2026, 10, 18, 15, 1, 0, tzinfo=timezone.utc)
    assert D.reader_quiet_at(at, None)['ok'] and not D.reader_quiet_at(at - timedelta(seconds=1), None)['ok']
    assert D.reader_quiet_at(at + timedelta(seconds=210), None)['ok']
    assert not D.reader_quiet_at(at + timedelta(seconds=211), None)['ok']
    assert not D.reader_quiet_at(at, at - timedelta(seconds=59))['ok']
    assert D.reader_quiet_at(at, at - timedelta(seconds=60))['ok']


# ----- refusals and stops -----------------------------------------------------------------------------------------------
def test_host_not_free_stops_before_any_reader_or_venue_step(world, clock):
    world.overrides['host_free'] = [(['holder={"pid":1}', 'poison=False', 'queued=0', 'MUTEX BUSY'], 0)]
    pack, _ = drive(world, clock)
    assert (pack['stop_step'], pack['stop_code']) == ('test_host_free_start', 'host_not_free')
    assert not world.of('open_orders') and not world.of('live')


def test_compare_stop_is_a_fail_and_the_pack_still_written(world, clock):
    world.final_collateral = '90'  # changed with zero fills in the ledger
    pack, _ = drive(world, clock)
    assert pack['stop_step'] == 'compare_t40_to_start_final'
    assert pack['stop_code'].startswith('STOP collateral_changed_without_pilot_fill')


def test_compare_pure_reports_start_not_in_ledger(tmp_path):
    root = tmp_path
    name, sha = write_baseline(root, 't40', NOW)
    assert D.compare_t40_to_start(root, name, sha)[0]
    ok, line = D.compare_t40_to_start(root, name, 'f' * 64)
    assert not ok and 'start_not_a_ledger_t40' in line and 'start_sha_mismatch' in line


def test_preflight_failure_stops_before_live(world, clock):
    world.overrides['preflight'] = [([str({'status': 'FAIL', 'message': 'preflight_failed'})], 1)]
    pack, _ = drive(world, clock)
    assert pack['stop_step'] == 'preflight' and not world.of('live')
    assert pack['preflight']['status'] == 'FAIL'


def test_a_wrong_go_phrase_is_the_pinned_cli_refusal_and_stops(world, clock):
    world.live_mode = 'wrong_phrase'
    pack, _ = drive(world, clock)
    assert (pack['stopped_reason'], pack['stop_code']) == ('REFUSED', 'owner_confirmation_refused')
    assert not posted(world) and not world.of('verify')


def test_a_pinned_start_gate_refusal_stops(world, clock):
    world.live_mode = 'refused_gate'
    pack, _ = drive(world, clock)
    assert pack['stop_code'] == 'baseline_t24_age' and pack['refusal_codes'][-1] == 'baseline_t24_age'


def test_a_wrong_attest_phrase_is_refused(tmp_path, clock):
    world = World(tmp_path, clock, t24_at=None)
    world.overrides['session0-attest'] = [([str({'runs': 'ok'}), 'Type: attest session0 abcdef',
                                            str({'status': 'REFUSED', 'exception_type': 'RuntimeError',
                                                 'code': 'owner_confirmation_refused'})], 1)]
    pack, _ = drive(world, clock, session0_runs=('0a',), attest=('12', '2026-10-18T15:30:00Z'))
    assert (pack['stop_step'], pack['stop_code']) == ('session0_attest', 'owner_confirmation_refused')
    assert world.of('session0-attest')[0].interactive


def test_a_mid_run_cleanup_failure_stops_and_still_writes_the_pack(world, clock):
    world.cleanup_ok = False
    pack, _ = drive(world, clock)
    assert (pack['stop_step'], pack['stop_code']) == ('after_run', 'cleanup_not_ok_or_panic')
    assert pack['runs'][0]['cleanup_ok'] is False and 'cancel-ours' in pack['action']
    assert not world.of('wallet-verify') and not any('cancel' in ' '.join(p.argv) for p in world.procs)


def test_a_late_start_is_stopped_with_the_latest_legal_go_shown(tmp_path):
    clock = FakeClock(datetime(2026, 10, 18, 17, 51, tzinfo=timezone.utc))
    world = World(tmp_path, clock)
    pack, _ = drive(world, clock)
    assert pack['stop_code'] == 'driver_past_latest_legal_live_start'
    assert pack['latest_legal_live_start_utc'] == '2026-10-18T17:50:00Z' and not world.of('preflight')


def test_a_t24_younger_than_20h_is_stopped(tmp_path, clock):
    world = World(tmp_path, clock, t24_at='2026-10-18T00:00:00+00:00')
    pack, _ = drive(world, clock)
    assert pack['stop_code'].startswith('driver_t24_younger_than_20h')


def test_the_pin_must_be_the_expected_clean_locked_commit(world, clock):
    world.overrides['git_status'] = [([' M src/x.py'], 0)]
    assert drive(world, clock)[0]['stop_code'] == 'pin_worktree_not_clean'


def test_no_terminal_refuses(world, clock):
    pack, _ = drive(world, clock, console=FakeConsole(tty=False))
    assert pack['stop_code'] == 'owner_terminal_required' and not world.procs


def test_counted_sessions_take_no_session0_flags(capsys):
    assert lfc_cli.main(['session-run', '--expect-commit', SHA, '--extra-conditions', 'x.json']) == 1
    assert 'session0_flags_without_session0' in capsys.readouterr().out
    assert lfc_cli.main(['session-run', '--expect-commit', 'abc']) == 1
    assert 'expect_commit_must_be_full_sha' in capsys.readouterr().out


# ----- owner Ctrl+C and the dry run --------------------------------------------------------------------------------------
def test_owner_ctrl_c_kills_the_child_tree_and_writes_the_pack(world, clock):
    world.interrupts['baseline'] = [0]
    pack, _ = drive(world, clock)
    assert pack['stopped_reason'] == 'owner_interrupt' and world.of('baseline')[0].killed == 'job'
    assert pack['action'] == D.SECTION9_ACTION and not world.of('live')


def test_ctrl_c_in_live_gives_its_cleanup_grace_then_a_second_kills_the_tree(world, clock):
    world.interrupts['live'] = [3, 3]  # after the go phrase; the live child would be running its own cleanup
    world.h_live = lambda argv: ([str({'condition': COND, 'event_slug': 'e', 'selection_sha256': 'b', 'size': '40'}),
                                  'Type: go abc123', 'posting'] + ['still running'] * 50, 0)
    pack, console = drive(world, clock)
    assert pack['stopped_reason'] == 'owner_interrupt' and world.of('live')[0].killed == 'job'
    assert any('running its own cleanup' in l for l in console.lines)


def test_ctrl_c_outside_a_child_still_writes_the_pack(world, clock):
    calls = {'n': 0}
    real = clock.sleep

    def sleep(seconds):
        calls['n'] += 1
        if calls['n'] == 5:
            raise KeyboardInterrupt
        real(seconds)
    clock.sleep = sleep
    pack, _ = drive(world, clock)
    assert pack['stopped_reason'] == 'owner_interrupt'


def test_dry_run_never_releases_the_go_line_and_kills_live(world, clock):
    pack, console = drive(world, clock, to_go_prompt=True)
    assert pack['stopped_reason'] == 'dry_run_complete' and pack['action'] is None
    live = world.of('live')[0]
    assert live.killed == 'job' and live.interactive
    assert not any(str(y).startswith('Type: go') for y in live.yielded)  # never read, so never shown
    assert not any(l.startswith('Type: go') for l in console.lines) and not posted(world)
    assert world.procs[-1].key == 'host_free'  # clears the mutex the killed live left abandoned
    assert pack['selection_screen']['status'] == 'PASS'


def test_dry_run_and_session_flags_are_validated(capsys):
    assert lfc_cli.main(['session-run', '--expect-commit', SHA, '--phase', 't24', '--to-go-prompt']) == 1
    assert 'to_go_prompt_is_a_session_phase_option' in capsys.readouterr().out


# ----- the real child tree kill -----------------------------------------------------------------------------------------
@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='Windows job object')
def test_the_job_object_kills_a_grandchild(tmp_path):
    import ctypes
    script = ("import subprocess, sys, time\n"
              "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
              "print(p.pid, flush=True)\ntime.sleep(120)\n")
    child = D.ChildProcess([sys.executable, '-c', script], cwd=tmp_path, env=dict(os.environ), interactive=False)
    try:
        line = child.poll_line(30)
        grandchild = int(line)
        k32 = ctypes.WinDLL('kernel32')
        k32.OpenProcess.restype = ctypes.c_void_p
        handle = k32.OpenProcess(0x00100000, False, grandchild)  # SYNCHRONIZE
        assert handle
        assert child.kill_method == 'job' and child.kill_tree() == 'job'
        assert k32.WaitForSingleObject(ctypes.c_void_p(handle), 20000) == 0  # the grandchild ended
        k32.CloseHandle(ctypes.c_void_p(handle))
        assert child.wait() != 0
    finally:
        child.kill_tree()
        child.close()
