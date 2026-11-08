"""Embargo-safe unattended notices, bounded progress and rotating diagnostics."""
from pathlib import Path
import json
import os
import re
import shutil
import uuid

from weather.market.lfc_campaign_control import SAFE_STATES, control_record
from weather.market.lfc_recording_io import strict_json

DISK_FLOOR_BYTES = 5 * 1024 ** 3
STALL_SECONDS = 120
LOG_BYTES = 1024 ** 2


def disk_headroom(path):
    from weather.market.lfc_campaign_state import StateRefused
    free = shutil.disk_usage(path).free
    if free < DISK_FLOOR_BYTES:
        raise StateRefused('disk_free_below_floor')
    return {'available_disk_bytes': free, 'disk_floor_bytes': DISK_FLOOR_BYTES}


def safe_traceback(tb):
    frames = []
    while tb is not None and len(frames) < 64:
        frame = tb.tb_frame
        module = str(frame.f_globals.get('__name__', 'other'))
        if not module.startswith(('weather.', 'urllib.', 'httpx.', 'httpcore.')):
            module = 'other'
        name = frame.f_code.co_name
        frames.append({'module': module, 'function': name if re.fullmatch('[A-Za-z0-9_<>]{1,96}', name) else 'other',
                       'line': tb.tb_lineno})
        tb = tb.tb_next
    return frames


def tick_log(root, *, now, attempt_id, exit_code, frames=()):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'campaign-ticks.jsonl'
    if path.exists() and path.stat().st_size >= LOG_BYTES:
        path.rename(root / ('campaign-ticks-' + now.strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex + '.jsonl'))
    row = {'at_utc': now.isoformat(), 'attempt_id': attempt_id, 'exit_code': exit_code, 'traceback': list(frames)}
    with path.open('ab') as handle:
        handle.write((json.dumps(row, sort_keys=True) + '\n').encode())
        handle.flush()
        os.fsync(handle.fileno())


def notify_control(runtime, row):
    """No detailed outcome, exception text or private path enters the toast."""
    from weather.market.lfc_pilot import notify_owner
    signature = {key: row[key] for key in ('attempt_id', 'phase', 'orders_open_unproven')}
    previous = getattr(runtime, '_last_control_notice', None)
    if previous is None:
        path = runtime.control_root.parent / 'notifications.jsonl'
        if path.exists():
            try:
                with path.open('rb') as handle:
                    handle.seek(max(0, path.stat().st_size - 65536))
                    for line in handle:
                        try:
                            previous = strict_json(line).get('public_status', previous)
                        except ValueError:
                            continue
            except OSError:
                pass
    runtime._last_control_notice = signature
    if row['phase'] in {'INCIDENT', 'POSTCHECK_PENDING', 'COMPLETE', 'MISSED', 'REFUSED', 'DEFERRED'} and signature != previous:
        return notify_owner(runtime.control_root.parent, {}, public_status=signature)


def stalled(runtime, claim, *, last_progress, now_mono, exit_process=os._exit):
    if now_mono - last_progress <= STALL_SECONDS:
        return False
    # The claim and workload markers remain. A watchdog cannot claim cleanup,
    # write concurrently to the money ledger, or authorize another attempt.
    try:
        row = control_record(runtime.control_root, claim['attempt_id'], phase='INCIDENT', now=runtime.clock.now(),
            incident=True, postchecks_pending=True, reason='session_stalled', orders_open_unproven=True,
            policy_metadata=runtime.state.policy_binding)
        notify_control(runtime, row)
        tick_log(runtime.control_root.parent, now=runtime.clock.now(), attempt_id=claim['attempt_id'],
                 exit_code=1, frames=[{'module': 'weather.market.lfc_campaign_visibility', 'function': 'session_stalled', 'line': 0}])
    finally:
        exit_process(1)
    return True
