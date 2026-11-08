"""Bounded F0/LFC recorder intake. Missing evidence produces gaps, never fabricated zeros.

This accepts the real writer's journal shapes at the reviewed F0 commit. It
does not call, import or modify the pilot, a reader or a venue client.
"""
from dataclasses import asdict
from datetime import timedelta

from weather.backtesting.t1_types import digest, number, utc

F0_GAPS = {
    'public_executions': 'Unique confirmed maker-side executions, route/mirror linkage and gap-free coverage for both tokens.',
    'continuous_books': 'Per-token request/receipt clocks and books within frozen freshness throughout orders and post-fill horizons.',
    'own_liquidity': 'Private remaining-size intervals bound to each raw book and exactly one checked subtraction.',
    'reward_census': 'Native maker/order identities or a separately frozen one-sided bound validation.',
    'reward_samples': 'Realized venue samples and complete condition-day denominator, or a validated uncertainty design.',
    'midpoint_rule': 'Dated authoritative size-cutoff rule or prospective fragmented-depth comparison.',
    'reward_payment': 'Distinct D+1 and D+2 reads, actual cash credit and independent shared-day allocations.',
    'rebate_economics': 'Dated condition-day eligibility/pool/fee-weight, rounding and independently attributed actual credit.',
    'settlement_redemption': 'Venue payout fractions, token holdings, redemption transactions and residual value through follow-up.',
    'cash_positions': 'Independent opening/terminal/follow-up token and collateral accounts, all cashflows and costs.',
    'persistent_capital': 'Verified flat nonoverlapping funded periods and cash continuity; unsettled opening lots are unsupported.',
    'provenance': 'Retained raw evidence, exporter/profile hashes, full ledger chain and clean source/preregistration certificate.',
    'competition_response': 'Public passive data cannot identify our posting response; validate an intervention/response envelope.',
    'clock_resolution': 'Independent clock-offset evidence and resolved submit/cancel/fill intervals.',
}


def recorder_report(payload, config, raw_journal, receipts, tolerance):
    from weather.backtesting.t1_accuracy import F0_PIN, pin_commands, pin_latency_evidence, read_pin_evidence
    from weather.backtesting.t1_capture import pin_snapshot

    evidence = read_pin_evidence(raw_journal, require_complete=False, observations=True)
    rows, opened = evidence.rows, evidence.rows[0]
    scope = opened['scope']
    if payload['recorder_pin'] != F0_PIN:
        raise ValueError('F0 intake requires the actual reviewed recorder pin, never relabel it as the legacy pin')
    if receipts.get('journal_sha256', evidence.sha256) != evidence.sha256:
        raise ValueError('receipt/journal scope mismatch')
    gaps = {k: {'status': 'NOT QUALIFIED', 'evidence_required': v} for k, v in F0_GAPS.items()}
    for gap in evidence.gaps:
        gaps[gap] = {'status': 'NOT QUALIFIED', 'evidence_required': 'Complete original journal and cleanup proof.'}
    try:
        commands, known = pin_commands(rows, scope['condition_id'])
    except (KeyError, ValueError) as exc:
        commands, known = [], {}
        gaps['lifecycle'] = {'status': 'NOT QUALIFIED', 'evidence_required': str(exc)}
    snapshots, times = [], []
    for row in rows:
        if row['event'] not in ('submit_market_snapshot', 'market_snapshot'):
            continue
        snapshot = row['snapshot']
        available = utc(row['recorded_at_utc'])
        times.append(available)
        try:
            # No own-size assumption: these are retained raw diagnostics, never
            # competitor-only replay inputs. The absent subtraction stays a gap.
            book, terms = pin_snapshot(snapshot, available_at=available.isoformat(),
                                        valid_until=(available + timedelta(seconds=float(number(config.max_book_age_seconds)))).isoformat())
            book.pop('own_exclusion', None)
            book['competitor_only'] = False
            book['own_liquidity_status'] = 'NOT QUALIFIED'
            snapshots.append({'book': book, 'terms': terms, 'use': 'RAW_DIAGNOSTIC_ONLY'})
        except (ValueError, KeyError) as exc:
            gaps['snapshot_projection'] = {'status': 'NOT QUALIFIED', 'evidence_required': str(exc)}
    try:
        latency = pin_latency_evidence(raw_journal, recorder_pin=payload['recorder_pin'])
    except (ValueError, KeyError):
        latency = None
    confirmed, pending = [], []
    for row in rows:
        if row['event'] == 'terminal_trades':
            for trade in row.get('rows', []):
                (confirmed if trade.get('status') == 'CONFIRMED' else pending).append(trade)
    max_gap = max(((b - a).total_seconds() for a, b in zip(times, times[1:])), default=None)
    # Supplemental normalized evidence can be evaluated independently, but F0
    # intake itself never promotes unobserved fields to complete=true.
    supplemental = None
    if payload.get('normalized_payload') is not None:
        from weather.backtesting.t1_accuracy import accuracy_gate

        supplemental = accuracy_gate(payload['normalized_payload'], config, raw_journal, receipts, tolerance)
    return {'status': 'NOT_QUALIFIED', 'qualification': 'F0_PARTIAL_CALIBRATION',
            'synthetic': opened['mode'] != 'live', 'trial_can_pass': False,
            'recorder_pin': payload['recorder_pin'], 'profile_sha256': opened['profile_sha256'],
            'journal_sha256': evidence.sha256, 'journal_records': evidence.record_count,
            'journal_bytes': evidence.byte_count, 'scope': scope,
            'commands': commands, 'known_order_ids': sorted(known), 'snapshots': snapshots,
            'submit_latency_evidence': latency, 'max_recorded_snapshot_gap_seconds': max_gap,
            'confirmed_terminal_trades': confirmed, 'pending_terminal_trades': pending,
            'gap_flags': gaps, 'supplemental_accuracy': supplemental,
            'net_pnl': None, 'cash': None, 'end_positions': None,
            'tolerance_sha256': digest(asdict(tolerance)), 'config_sha256': digest(config.projection())}
