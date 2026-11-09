"""Bounded read-only D+1/D+2 and settlement follow-up for the owner task.

No order client, redemption or task activation exists here. Ancillary failures
are retained as gaps; private evidence faults still take the ordinary N1 path.
"""
from datetime import timedelta
from types import SimpleNamespace
import uuid

def collect(runtime, *, get=None, reward_client=None):
    from weather.market.lfc_settlement_record import public_get, record_settlement
    from weather.market.lfc_rewards_record import record_rewards, record_rebates, latest_record, record_complete
    from weather.market.re1_payout_evidence import ReadJournal
    from weather.market.wallet_reader_security import SecretGuard
    get = get or public_get
    state, ledger = runtime.state, runtime.state.ledger
    observed = runtime.clock.now()
    stop = runtime.clock.monotonic() + 120
    observations, gaps = [], []
    last_get = [None]
    def bounded_get(endpoint, params):
        if last_get[0] is not None:
            runtime.clock.sleep(max(0, .5 - (runtime.clock.monotonic() - last_get[0])))
        if runtime.clock.monotonic() >= stop:
            raise TimeoutError('followup_budget')
        last_get[0] = runtime.clock.monotonic()
        return get(endpoint, params)
    conditions = {}
    for session in ledger.sessions.values():
        if session['legs']:
            for key in session['legs']:
                leg = ledger.legs[key]
                cid = session['start'].get('condition_id') or leg.get('condition_id')
                if not cid:
                    gaps.append('followup_condition_scope_missing')
                    continue
                conditions.setdefault(cid, set()).add(leg['token_id'])
    for condition, tokens in sorted(conditions.items()):
        if runtime.clock.monotonic() >= stop:
            gaps.append('followup_time_budget')
            break
        try:
            row = record_settlement(runtime.pilot_root, condition, clock=runtime.clock.now,
                                     get=bounded_get, traded_tokens=tokens)
            observations.append({'condition_id': condition, 'settlement_terminal': row['terminal']})
        except FileExistsError:
            continue
        except Exception as exc:
            gaps.append('settlement_' + type(exc).__name__)
    # D+2 runs independently even if the previous D+1 pass never completed.
    for lag in (1, 2):
        day = (observed.date() - timedelta(days=lag)).isoformat()
        selected = sorted(filter(None, {s['start'].get('condition_id') or ledger.legs[key].get('condition_id')
            for s in ledger.sessions.values() for key in s['legs']
            if s['start']['recorded_at_utc'][:10] == day}))
        if not selected or runtime.clock.monotonic() >= stop:
            continue
        try:
            previous, _, _ = latest_record(runtime.pilot_root / 'rewards' / f'{day}-d{lag}.json',
                kind='lfc_rewards_record', day=day, maker=state.maker.lower(), conditions=selected, lag=lag)
            if previous is not None and record_complete(previous):
                raise FileExistsError('already_complete')
            # Credentials are loaded only by the authorized owner task. No
            # dotenv or reader token is added to the R3 recording contract.
            if reward_client is None:
                from weather.market.lfc_rewards_record import AccrualTransport, AccrualClient
                context = getattr(runtime, 'reward_read_context', None)
                if context is None:
                    from weather.market.lfc_rewards_record import load_reward_credentials
                    import os
                    fields, guard = load_reward_credentials()
                    kind = os.environ.get('POLYMM_SIGNATURE_TYPE')
                    if kind not in ('2', '3'):
                        raise ValueError('reward_signature_type_missing')
                    context = fields, guard, int(kind)
                fields, guard, signature_type = context
                if fields['FUNDER_ADDRESS'].lower() != state.maker.lower():
                    raise ValueError('rewards_account_changed')
                journal = ReadJournal(guard, runtime.clock.now)
                class BoundedTransport(AccrualTransport):
                    def request(self, *args, **kwargs):
                        if runtime.clock.monotonic() >= stop:
                            raise TimeoutError('followup_budget')
                        return super().request(*args, **kwargs)
                client = AccrualClient(BoundedTransport(fields, guard, journal), signature_type)
            else:
                journal = ReadJournal(SecretGuard(()), runtime.clock.now)
                client = reward_client
            record_rewards(runtime.pilot_root, day, maker=state.maker.lower(), conditions=selected,
                venue=SimpleNamespace(client=client), journal=journal, clock=runtime.clock.now,
                get=bounded_get, as_of=observed)
            observations.append({'date': day, 'pass': lag, 'reward_read': 'recorded'})
        except FileExistsError:
            observations.append({'date': day, 'pass': lag, 'reward_read': 'already_recorded'})
        except Exception as exc:
            gaps.append(f'd{lag}_reward_' + type(exc).__name__)
        try:
            record_rebates(runtime.pilot_root, day, maker=state.maker.lower(), conditions=selected,
                           clock=runtime.clock.now, get=bounded_get, as_of=observed)
        except FileExistsError:
            pass
        except Exception as exc:
            gaps.append(f'd{lag}_rebate_' + type(exc).__name__)
    return {'observed_at_utc': observed.isoformat(), 'observations': observations, 'gaps': gaps,
            'monetary_action': False}


def due(runtime, policy, *, evidence_only=False):
    """One cadence contract for actual maintenance and non-admitting idle ticks."""
    from datetime import datetime
    now = runtime.clock.now()
    if not evidence_only and any(entry.start - timedelta(minutes=20) <= now < entry.end for entry in policy.entries):
        return False
    prior = sorted((runtime.state.root / 'followups').glob('*.json'))
    if prior:
        last = runtime.state.read(prior[-1])
        cadence = 300 if last.get('gaps') else 3600
        if (now - datetime.fromisoformat(last['observed_at_utc'])).total_seconds() < cadence:
            return False
    return True


def maintenance(runtime, policy, *, evidence_only=False):
    """Bounded GET recording survives incidents; it never closes money state."""
    from weather.market.lfc_campaign_guard import AdmissionBusy
    from weather.market.lfc_campaign_state import StateRefused
    from weather.market.lfc_f2_economics import publish_supplements
    now = runtime.clock.now()
    if not due(runtime, policy, evidence_only=evidence_only):
        return
    try:
        with runtime.readonly_admission():
            money_gap, money_complete = None, False
            if not evidence_only:
                try:
                    runtime.reload_ledger()
                    runtime.state.require_retained_evidence()
                    proof = runtime.core_proof(runtime.state.ledger, runtime.read_account())
                    money_complete = (proof.get('money_accounting_complete') is True and
                                      proof.get('cleanup_proven') is True and proof.get('unknown_submit') is False)
                    if proof.get('money_contradiction') is True or proof.get('unknown_submit') is not False:
                        runtime.state.latch('followup-money', 'followup_money_contradiction', runtime.clock.now())
                    if not money_complete:
                        money_gap = 'cash_followup_incomplete'
                except Exception as exc:
                    from weather.market.lfc_capital import CapitalRefused
                    if isinstance(exc, CapitalRefused) and str(exc) in {
                            'capital_cash_unreconciled', 'capital_inventory_unreconciled'}:
                        from weather.market.lfc_capital_consistency import observe
                        from weather.market.lfc_campaign import TransientPrecheck
                        try:
                            observe(runtime.state, runtime.clock.now(), reason=str(exc))
                        except (TransientPrecheck, StateRefused):
                            pass  # Keep the candidate/incident; continue only GET recording.
                    money_gap = 'cash_followup_' + type(exc).__name__
            facts = collect(runtime)
            facts['money_proof_complete'] = money_complete
            if evidence_only:
                facts['gaps'].append('money_or_evidence_incident_retained')
            if money_gap:
                facts['gaps'].append(money_gap)
            try:
                from weather.market.lfc_capital_settlement import record_zero_payouts
                facts['zero_payout_lots_realized'] = (record_zero_payouts(runtime.state.ledger, runtime.pilot_root)
                    if getattr(runtime.state.ledger, 'capital_rows', ()) else 0)
            except Exception as exc:
                facts['gaps'].append('zero_payout_' + type(exc).__name__)
            try:
                publish_supplements(runtime)
            except Exception as exc:
                facts['gaps'].append('supplement_' + type(exc).__name__)
            runtime.state.save('followups/' + now.strftime('%Y%m%dT%H%M%S%fZ') + '.json', facts)
    except AdmissionBusy:
        return  # Retry next tick, without consuming an hourly recording slot.
    except Exception as exc:
        runtime.state.save('followups/' + now.strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex + '.json',
            {'observed_at_utc': now.isoformat(), 'gaps': [type(exc).__name__], 'monetary_action': False,
             'money_proof_complete': False})
