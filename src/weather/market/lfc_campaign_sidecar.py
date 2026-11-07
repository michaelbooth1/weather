"""Optional reviewed T017 public recorder adapter; failure is a research gap.

The adapter never supplies account credentials or controls the private heartbeat.
It records exact scope/cadence/coverage and verifies the final physical chunks.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import re
import subprocess
import time

from weather.market.lfc_recording_io import file_sha, read_bytes, strict_json, write_new
from weather.market.lfc_session_driver import ChildProcess
from weather.operations.live_path_security import validate_nonreparse_directory, validate_regular_nonreparse_file


SIDECAR_SCHEMA = 'lfc_campaign_sidecar_v0.1'


def cadences(bands):
    if type(bands) is not int or not 1 <= bands <= 1000:
        raise ValueError('sidecar_scope_size')
    batches = math.ceil(2 * bands / 100)
    books = max(5, math.ceil(batches / .5))
    slow = max(180, math.ceil((4 * bands + 1) / (1.5 - batches / books - 1 / 60)))
    nominal = batches / books + (4 * bands + 1) / slow + 1 / 60
    return {'book_seconds': books, 'slow_seconds': slow, 'nominal_rps': nominal, 'hard_rps': 2}


def public_environment(root):
    # An allowlist, not an inherited environment with a handful of secrets removed.
    result = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'PATH') if key in os.environ}
    result.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8',
                  TEMP=str(root), TMP=str(root))
    return result


def health_receipt(output, *, event_slug, health_schema, final=False, expected_conditions=None):
    row = strict_json(read_bytes(Path(output) / 'health.json', 600000))
    body = {k: v for k, v in row.items() if k != 'health_receipt_sha256'}
    sha = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if row.get('schema_version') != health_schema or row.get('health_receipt_sha256') != sha:
        raise ValueError('sidecar_health_identity')
    coverage = row.get('coverage')
    if not isinstance(coverage, dict) or set(coverage.get('events') or {}) != {event_slug}:
        raise ValueError('sidecar_health_scope')
    if expected_conditions is not None:
        tokens = coverage.get('tokens')
        if (not isinstance(tokens, dict) or type(coverage.get('expected_tokens')) is not int or
                len(tokens) != coverage['expected_tokens'] or not set(expected_conditions) <=
                {state.get('condition_id') for state in tokens.values() if isinstance(state, dict)}):
            raise ValueError('sidecar_token_scope_incomplete')
    # Remote source timestamps do not determine whether the local receiver lives.
    observed = datetime.fromisoformat(row['receipt_utc'])
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    source_gaps = bool(coverage.get('open_intervals'))
    counts = row.get('counts')
    if not isinstance(counts, dict) or not 0 <= age <= 90:
        raise ValueError('sidecar_writer_stale')
    chunks, chunk_hashes = list(Path(output).glob('chunk-*.jsonl.gz.sha256.json')), {}
    if final:
        if row.get('final') is not True or type(row.get('sealed_chunks')) is not int or len(chunks) != row['sealed_chunks']:
            raise ValueError('sidecar_chunks_incomplete')
        for path in chunks:
            receipt = strict_json(read_bytes(path, 16384))
            name = receipt.get('file')
            if not isinstance(name, str) or not re.fullmatch(r'chunk-[0-9]{6}\.jsonl\.gz', name):
                raise ValueError('sidecar_chunk_name')
            chunk = validate_regular_nonreparse_file(Path(output) / name)
            if chunk.stat().st_size != receipt.get('bytes') or file_sha(chunk) != receipt.get('sha256'):
                raise ValueError('sidecar_chunk_corrupt')
            chunk_hashes[name] = receipt['sha256']
        if list(Path(output).glob('*.partial')):
            raise ValueError('sidecar_partial_chunk')
    complete = (not row.get('storage_failed') and not source_gaps and coverage.get('coverage_ready') is True and
                coverage.get('expected_tokens', 0) > 0 and coverage.get('baselines_taken') == coverage['expected_tokens'])
    return {'research_evidence_complete': complete, 'source_gaps': source_gaps,
            'health_sha256': file_sha(Path(output) / 'health.json'), 'coverage': coverage,
            'writer_counts': counts, 'receipt_utc': row['receipt_utc'], 'chunk_sha256': chunk_hashes,
            'errors': row.get('secondary_errors'), 'native_sequence_completeness_proven': False}


class Sidecar:
    def __init__(self, *, manifest, output, scope, started, seconds, process_factory=ChildProcess, policy_metadata=None):
        self.output, self.scope, self.process = Path(output), scope, None
        self.report = {'schema_version': SIDECAR_SCHEMA, 'scope': scope, 'research_evidence_complete': False,
                       **({} if policy_metadata is None else policy_metadata),
                       'gap': 'sidecar_not_started'}
        self.stopped = False
        try:
            if Path(manifest).suffix.lower() != '.json':
                raise ValueError('sidecar_manifest_extension')
            release_path = validate_regular_nonreparse_file(manifest)
            release = strict_json(read_bytes(release_path, 65536))
            if release.get('schema_version') != 'lfc_campaign_sidecar_release_v0.1':
                raise ValueError('sidecar_release_schema')
            root = validate_nonreparse_directory(release['root'])
            interpreter = validate_regular_nonreparse_file(release['python'])
            if interpreter.name.lower() != 'python.exe' or file_sha(interpreter) != release['python_sha256']:
                raise ValueError('sidecar_interpreter_hash')
            result = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True,
                                    text=True, timeout=15, check=True)
            if result.stdout.strip() != release['head']:
                raise ValueError('sidecar_head')
            result = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], capture_output=True,
                                    text=True, timeout=15, check=True)
            if result.stdout.strip():
                raise ValueError('sidecar_dirty_pin')
            rate = cadences(len(scope['condition_ids']))
            text = lambda value: value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
            argv = [str(interpreter), '-m', 'weather.market.pilot_validation_evidence', 'public-capture',
                    '--market', scope['market_id'], '--event-date', scope['event_date'],
                    '--all-bands', '--both-tokens', '--raw-market-stream', '--start-utc', text(started),
                    '--end-utc', text(started + timedelta(seconds=seconds)), '--output', str(self.output),
                    '--max-rest-rps', '2', '--max-rss-mib', '256', '--max-output-mib', '512', '--min-free-gib', '40',
                    '--rest-book-seconds', str(rate['book_seconds'])]
            for flag in ('terms', 'fee', 'fee-rate', 'metadata'):
                argv += ['--' + flag + '-seconds', str(rate['slow_seconds'])]
            self.health_schema = release['health_schema']
            self.process = process_factory(argv, cwd=root, env=public_environment(self.output.parent),
                                           interactive=False, require_containment=True)
            self.report.update(gap='sidecar_readiness_pending', cadences=rate, release_sha256=file_sha(release_path))
        except Exception as exc:
            self.report['gap'] = 'sidecar_start_' + type(exc).__name__

    def observe(self, *, final=False):
        try:
            self.report.update(health_receipt(self.output, event_slug=self.scope['event_slug'],
                                              health_schema=self.health_schema, final=final,
                                              expected_conditions=self.scope['condition_ids']))
            self.report['gap'] = None if self.report['research_evidence_complete'] else 'sidecar_coverage_gap'
        except Exception as exc:
            self.report.update(gap='sidecar_health_' + type(exc).__name__, research_evidence_complete=False)
        return self.report

    def stop(self):
        if self.stopped:
            return True
        contained = True
        if self.process is not None:
            try:
                self.process.request_stop()
            except Exception:
                pass
            deadline = time.monotonic() + 5
            while self.process.popen.poll() is None and time.monotonic() < deadline:
                time.sleep(.1)
            if self.process.job is not None:
                self.process.job.terminate()  # exact owned job; never a reused PID/taskkill fallback
            contained = self.process.job is not None and self.process.job.wait_empty(timeout=15)
            self.process.close()
            self.observe(final=True)
        self.report['child_contained'] = contained
        try:
            write_new(self.output.parent / (self.output.name + '-adapter-final.json'), self.report)
        except OSError:
            self.report.update(gap='sidecar_final_publication_failed', research_evidence_complete=False)
        self.stopped = contained
        return contained
