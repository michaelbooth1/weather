"""Bounded two-capability place-and-hold controller. No client is created here.

The sealed entrypoint supplies independently validated token gates and exact
public inputs. Rehearsals use an in-memory exchange. Neither a profile nor a
rehearsal result is live authority.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
import re
from pathlib import Path
import time

from weather.market.mm_geographic_eligibility import validate_geographic_eligibility_receipt
from weather.market.mm_live_envelope import STAGE2_HOLD_V1 as PROFILE
from weather.market.mm_live_lifecycle_probe import _validate_bootstrap_binding, _verified_exact_positions
from weather.market.mm_pilot_capital import collateral_backs_pilot_budget
from weather.market.reward_quote import QuoteRefused, price_reward_quote, _decimal, _levels
from weather.market.reward_share_estimate import order_score, q_min, share_of, side_score
from weather.market.mm_stage2_public import (
    SCHEMA_VERSION, HoldEnd, canonical_bytes, digest, utc, public_quote,
)
CONFIRMATION = "INTERNATIONAL_POLYMARKET_STAGE2_PLACE_AND_HOLD"


def write_new(path, value):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(destination.read_bytes()).hexdigest()


class HoldJournal:
    def __init__(self, path, *, clock, scope, mode):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("xb")
        self.clock, self.sequence, self.previous = clock, 0, None
        self.record("opened", scope=scope, mode=mode, profile_sha256=PROFILE.sha256)

    def record(self, event, **fields):
        row = {
            "schema_version": SCHEMA_VERSION, "kind": "journal",
            "sequence": self.sequence, "previous_sha256": self.previous,
            "recorded_at_utc": utc(self.clock()).isoformat(), "event": event, **fields,
        }
        raw = canonical_bytes(row)
        self.handle.write(raw)
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.previous = hashlib.sha256(raw).hexdigest()
        self.sequence += 1

    def close(self):
        self.handle.close()


def verify_prediction_journal(prediction, journal_path):
    """Recompute the frozen sums from the retained, chained session journal."""
    import math
    raw = Path(journal_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != prediction['journal_sha256']:
        raise ValueError('prediction journal hash differs')
    previous, rows, last_time = None, [], None
    for index, line in enumerate(raw.splitlines(keepends=True)):
        row = json.loads(line)
        when = utc(row['recorded_at_utc'])
        if (canonical_bytes(row) != line or row['schema_version'] != SCHEMA_VERSION
                or row['kind'] != 'journal' or row['sequence'] != index
                or row['previous_sha256'] != previous or last_time is not None and when < last_time):
            raise ValueError('session journal chain or clock differs')
        previous, last_time = hashlib.sha256(line).hexdigest(), when
        rows.append(row)
    if (len(rows) < 2 or rows[0]['event'] != 'opened' or rows[-1]['event'] != 'terminal'
            or rows[0]['scope'] != prediction['scope'] or rows[0]['mode'] != prediction['mode']
            or rows[0]['profile_sha256'] != PROFILE.sha256 or prediction['profile_sha256'] != PROFILE.sha256
            or prediction['reward_day'] != utc(rows[0]['recorded_at_utc']).date().isoformat()
            or prediction['condition_id'] != prediction['scope']['condition_id']
            or utc(prediction['frozen_at_utc']) < last_time or prediction['earnings_read'] is not False):
        raise ValueError('frozen prediction scope or terminal record differs')
    for key in ('cleanup_ok', 'cancel_acknowledged', 'fill_seen', 'failure_type'):
        if rows[-1][key] != prediction[key]:
            raise ValueError('frozen terminal outcome differs')
    sums = {'P_many': 0.0, 'P_single': 0.0, 'visible_two_sided_minutes': 0.0}
    prior_sample, prior_visible, scoring, samples = None, False, True, 0
    boundaries = [r for r in rows if r['event'] == 'submit_boundary']
    acknowledgments = [r for r in rows if r['event'] == 'order_acknowledged']
    proposals = [r for r in rows if r['event'] == 'proposal']
    ends = [r for r in rows if r['event'] == 'end_condition']
    if len(proposals) != 1 or len(ends) != 1 or ends[0]['reason'] != prediction['end_condition']:
        raise ValueError('journal proposal or end condition differs')
    initial_terms = proposals[0]['snapshot']['quote_inputs']
    changed = False
    if len(boundaries) > 2 or len(acknowledgments) > len(boundaries):
        raise ValueError('session exceeds the submit ceiling')
    for i, row in enumerate(boundaries):
        if (row['leg'] != i + 1 or row['token_id'] != prediction['scope']['token_ids'][i]
                or _decimal(row['size']) != 20 or _decimal(row['price']) * 20 > PROFILE.per_order_pusd
                or _decimal(row['fresh_fee_rate_bps']) < 0
                or _decimal(row['fresh_fee_rate_bps']) != _decimal(row['candidate_fee_rate_bps'])):
            raise ValueError('journal submit binding differs')
    cancellation = [r for r in rows if r['event'] == 'cancel_all_acknowledged']
    zeroes = [r for r in rows if r['event'] == 'zero_open_orders']
    if (prediction['cancel_acknowledged'] is not bool(cancellation) or len(cancellation) > 1
            or prediction['cleanup_ok'] and (len(zeroes) != 1 or not zeroes[0]['cleanup_in_budget']
                or zeroes[0]['cleanup_elapsed_seconds'] > PROFILE.cleanup_seconds)):
        raise ValueError('terminal cleanup lacks acknowledged evidence')
    for cancel in cancellation:
        canceled = _cancel_ack_ids(cancel['response'])
        for proof in cancel.get('prior_acknowledgments', []):
            if (proof['profile_sha256'] != PROFILE.sha256
                    or proof['maker_address'] != prediction['scope']['maker_address']
                    or proof['condition_id'] != prediction['condition_id']
                    or not utc(rows[0]['recorded_at_utc']) <= utc(proof['checked_at_utc']) <= utc(cancel['recorded_at_utc'])):
                raise ValueError('emergency cancel acknowledgment scope differs')
            canceled.update(_cancel_ack_ids(proof['response']))
        terminal = cancel['terminal_orders']
        if (len(terminal) != len(acknowledgments)
                or {_order_id(r) for r in terminal} != {r['order_id'] for r in acknowledgments}
                or any(_decimal(r['size_matched']) == 0 and _order_id(r) not in canceled for r in terminal)):
            raise ValueError('terminal orders lack explicit cancellation acknowledgments')
    for row in rows:
        if row['event'] == 'public_observation':
            changed = changed or any(row['snapshot']['quote_inputs'][k] != initial_terms[k] for k in (
                'reward_min_size', 'reward_rate_per_day', 'reward_max_spread_cents'))
        if row['event'] != 'minute':
            continue
        if len(boundaries) != 2 or len(acknowledgments) != 2:
            raise ValueError('minutes precede two acknowledged orders')
        samples += 1
        snapshot, observed = row['snapshot'], row['observation']
        changed = changed or any(snapshot['quote_inputs'][k] != initial_terms[k] for k in (
            'reward_min_size', 'reward_rate_per_day', 'reward_max_spread_cents'))
        current = utc(row['recorded_at_utc'])
        quote = public_quote(snapshot, now=current, condition_id=prediction['condition_id'],
                             token_ids=prediction['scope']['token_ids'])
        from dataclasses import replace
        held = replace(quote, yes_buy=_decimal(boundaries[0]['price']), no_buy=_decimal(boundaries[1]['price']))
        if observe_held_quote(snapshot, held) != observed:
            raise ValueError('journal reward observation does not reproduce')
        elapsed = 0 if prior_sample is None else (current - prior_sample).total_seconds()
        counted = elapsed / 60 if 0 < elapsed <= 60.5 and prior_visible and observed['visible_two_sided'] else 0
        if not math.isclose(counted, row['counted_minutes'], abs_tol=1e-6):
            raise ValueError('journal visible minutes do not reproduce')
        if set(row['scoring']) != {r['order_id'] for r in acknowledgments} or any(type(v) is not bool for v in row['scoring'].values()):
            raise ValueError('journal scoring identities differ')
        scoring = scoring and all(row['scoring'].values())
        sums['visible_two_sided_minutes'] += counted
        sums['P_many'] += counted * observed['per_minute_many']
        sums['P_single'] += counted * observed['per_minute_single']
        prior_sample, prior_visible = current, observed['visible_two_sided']
    if any(not math.isclose(float(prediction[k]), v, rel_tol=1e-9, abs_tol=1e-6) for k, v in sums.items()):
        raise ValueError('frozen reward sums differ from journal')
    if prediction['all_observed_legs_scoring'] != (scoring and samples > 0 and len(acknowledgments) == 2):
        raise ValueError('frozen scoring outcome differs')
    if prediction['reward_terms_changed'] != changed:
        raise ValueError('frozen reward terms outcome differs')
    if prediction['visible_two_sided_minutes'] > PROFILE.session_seconds / 60:
        raise ValueError('visible minutes exceed the session ceiling')
    return rows


def observe_held_quote(snapshot, quote):
    """Value the original prices; subtract own size before competing-depth scores."""
    values = snapshot["quote_inputs"]
    fresh = price_reward_quote(**values)
    mid = fresh.adjusted_mid
    maximum = _decimal(values["reward_max_spread_cents"])
    distances = ((mid - quote.yes_buy) * 100, (1 - mid - quote.no_buy) * 100)
    if any(not Decimal("1") <= d <= Decimal("3") or d >= maximum for d in distances):
        raise HoldEnd("midpoint_drift")
    yb, ya, nb = (_levels(values[k]) for k in ("yes_bids", "yes_asks", "no_bids"))
    visible = all(sum(s for p, s in levels if p == price) >= quote.size
                  for levels, price in ((yb, quote.yes_buy), (nb, quote.no_buy)))
    scores = []
    for levels, own_price in ((yb, quote.yes_buy), (ya, 1 - quote.no_buy)):
        # Aggregate duplicate price rows before removing our resting quantity.
        aggregate = {}
        for price, size in levels:
            aggregate[price] = aggregate.get(price, Decimal(0)) + size
        aggregate[own_price] = max(Decimal(0), aggregate.get(own_price, Decimal(0)) - quote.size)
        scores.append(side_score(
            [(float(p), float(s)) for p, s in aggregate.items() if s > 0], float(mid),
            float(maximum), float(_decimal(values["reward_min_size"])),
        )[0])
    own = q_min(*(order_score(float(quote.size), float(d), float(maximum),
                              float(_decimal(values["reward_min_size"]))) for d in distances), float(mid))
    rate = float(_decimal(values["reward_rate_per_day"])) / 1440
    return {
        "visible_two_sided": visible, "adjusted_mid": str(mid),
        "per_minute_many": rate * share_of(own, sum(scores) / 2),
        "per_minute_single": rate * share_of(own, q_min(*scores, float(mid))),
    }


def _order_id(row):
    return str(row.get("id") or row.get("order_id") or row.get("orderID") or row.get("lifecycle_key") or "")


def _cancel_ack_ids(response):
    canceled = response.get('canceled') if isinstance(response, dict) else None
    if (not isinstance(canceled, list) or response.get('not_canceled')
            or any(not isinstance(oid, str) or not oid for oid in canceled)
            or len(set(canceled)) != len(canceled)):
        raise RuntimeError('explicit cancellation has no complete acknowledgment list')
    return set(canceled)


def _exact_open_orders(rows, expected, *, maker, condition):
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise HoldEnd("unexpected_open_orders")
    seen = set()
    for row in rows:
        order_id = _order_id(row)
        if order_id not in expected or order_id in seen:
            raise HoldEnd("unexpected_open_orders")
        token, price, size = expected[order_id]
        if (str(row.get("asset_id") or row.get("token_id")) != token
                or str(row.get('maker_address', '')).lower() != maker.lower()
                or row.get('market') != condition or str(row.get('status', '')).lower() != 'live'
                or row.get("side") != "BUY" or _decimal(row.get("price")) != price
                or _decimal(row.get("original_size")) != size):
            raise HoldEnd("open_order_binding")
        if _decimal(row.get("size_matched")) != 0:
            raise HoldEnd("fill")
        seen.add(order_id)


def _check_fills(adapters, expected, *, check_rest=True, checkpoint=lambda: None):
    for adapter in adapters:
        for row in adapter.user_events():
            oid = _order_id(row)
            if oid not in expected:
                raise HoldEnd("unknown_user_event")
            if (row.get("official_event_type") == "trade"
                    or row.get("event_type") in {"trade", "trade_pending", "rejected"}
                    or _decimal(row.get("size_matched", 0)) > 0):
                raise HoldEnd("fill")
        if not check_rest:
            continue
        checkpoint()
        # REST evidence catches fills even before the user stream delivers them.
        if adapter.account_trades():
            raise HoldEnd("fill")
        for oid, (token, _, _) in expected.items():
            if token != adapter.token_id:
                continue
            checkpoint()
            order = adapter.get_order(oid)
            if _order_id(order) != oid or str(order.get("asset_id")) != token:
                raise HoldEnd("rest_order_binding")
            if _decimal(order.get("size_matched")) > 0 or order.get("associate_trades"):
                raise HoldEnd("fill")


def _collateral(adapter, gate, required):
    payload = adapter.refresh_balance_allowance()
    cash = _decimal(payload.get("balance")) / 1_000_000
    raw = payload.get("allowances")
    if not isinstance(raw, dict) or not raw:
        raise HoldEnd("collateral")
    allowance = min(_decimal(x) for x in raw.values()) / 1_000_000
    if (gate.get("isolated_pilot_wallet") is not True or "pilot_capital_mode" in gate
            or not collateral_backs_pilot_budget(gate, balance=cash, allowance=allowance,
                                                requested_budget=required)):
        raise HoldEnd("collateral")
    return {"cash_pusd": str(cash), "allowance_pusd": str(allowance), "snapshot_sha256": digest(payload)}


def run_hold_session(
    adapters, bootstrap_gates, *, scope, initial_public, public_reader, geography_reader,
    journal_path, prediction_path, confirmation, operator_stop, scoring_reader,
    utc_clock=None, monotonic_clock=None, sleeper=None, mode="live",
):
    """Own at most two submits, one heartbeat and unconditional cancel/reconcile.

    Callers may inject clocks and exchange transports, never control predicates.
    The live entrypoint must first validate host/seal/Stage-1 evidence and grants.
    """
    wall = utc_clock or (lambda: datetime.now(timezone.utc))
    mono, sleep = monotonic_clock or time.monotonic, sleeper or time.sleep
    adapters, gates = tuple(adapters), tuple(bootstrap_gates)
    if (len(adapters) != 2 or len(gates) != 2 or confirmation != CONFIRMATION
            or scope.get("profile_sha256") != PROFILE.sha256
            or re.fullmatch(r"[a-f0-9]{64}", str(scope.get("selection_sha256", ""))) is None):
        raise ValueError("invalid sealed two-leg session")
    start, end = utc(wall()), utc(scope["end_at_utc"])
    seconds = (end - start).total_seconds()
    if (not 0 < seconds <= PROFILE.session_seconds
            or start.date() != (end + timedelta(seconds=PROFILE.cleanup_seconds)).date()):
        raise ValueError("hold session must fit 120 minutes in one UTC reward day")
    tokens = tuple(scope["token_ids"])
    if (len(set(tokens)) != 2 or tuple(a.token_id for a in adapters) != tokens
            or adapters[0].client is not adapters[1].client
            or adapters[0].heartbeat_sender is not adapters[1].heartbeat_sender
            or adapters[0].maker_address != adapters[1].maker_address
            or any(a.condition_id != scope["condition_id"] or a.envelope is not PROFILE for a in adapters)):
        raise ValueError("two capabilities must bind one account and two exact tokens")
    for adapter, gate in zip(adapters, gates):
        _validate_bootstrap_binding(adapter, gate)
        if gate.get("isolated_pilot_wallet") is not True or "pilot_capital_mode" in gate:
            raise ValueError("hold session requires a dedicated isolated wallet")
    if mode not in {"live", "rehearsal"}:
        raise ValueError("unknown session mode")
    if mode == 'live':
        from weather.market.mm_official_adapter import OfficialPolymarketGlobalAdapter
        if any(type(a) is not OfficialPolymarketGlobalAdapter for a in adapters):
            raise ValueError('live mode requires the official grant-checked adapters')
    quote = public_quote(initial_public, now=wall(), condition_id=scope["condition_id"], token_ids=tokens)
    if quote.reserve_pusd > PROFILE.per_band_pusd:
        raise ValueError("band cap exceeded")
    if Path(prediction_path).exists():
        raise FileExistsError("frozen prediction must be new")
    journal = HoldJournal(journal_path, clock=wall, scope=scope, mode=mode)
    expected, capabilities = {}, []
    reason, cleanup_ok, cancel_ack = "timeout", False, False
    p_many = p_single = visible_minutes = 0.0
    all_scoring, terms_changed, fill_seen = True, False, False
    next_beat = next_geo = next_public = mono()
    next_account = mono()
    geo = None
    last_sample, previous_visible = None, False
    deadline_mono = mono() + seconds
    last_heartbeat = None
    initial_terms = {k: initial_public["quote_inputs"][k] for k in (
        "reward_min_size", "reward_rate_per_day", "reward_max_spread_cents")}
    failure = None
    starting_collateral = None

    def record(event, **fields):
        journal.record(event, **fields)

    def geography():
        nonlocal geo, next_geo
        requested_at = mono()
        receipt = geography_reader()
        geo = validate_geographic_eligibility_receipt(receipt, now=wall(), require_fresh=True)
        # The existing public endpoint has a 10 s timeout. Leave that budget
        # inside the 45 s maximum refresh cadence, rather than after it.
        next_geo = requested_at + PROFILE.geoblock_refresh_seconds - 10
        record("geography", receipt=geo)

    def heartbeat():
        nonlocal next_beat, last_heartbeat
        if last_heartbeat is not None and mono() - last_heartbeat > 7.5:
            raise HoldEnd("heartbeat_loss")
        adapters[0].heartbeat()
        adapters[1].accept_shared_stage2_heartbeat(adapters[0])
        last_heartbeat = mono()
        next_beat = last_heartbeat + PROFILE.heartbeat_seconds
        record("heartbeat_acknowledged", account_count=1)

    def control_tick():
        if operator_stop():
            raise HoldEnd("operator_stop")
        if utc(wall()) >= end or mono() >= deadline_mono:
            raise HoldEnd("timeout")
        if mono() >= next_geo:
            try:
                geography()
            except Exception as exc:
                raise HoldEnd("geoblock") from exc
        validate_geographic_eligibility_receipt(geo, now=wall(), require_fresh=True)
        if mono() >= next_beat:
            try:
                heartbeat()
            except Exception as exc:
                raise HoldEnd("heartbeat_loss") from exc

    try:
        record('proposal', snapshot=initial_public)
        control_tick()
        _exact_open_orders(adapters[0].open_orders(), {}, maker=adapters[0].maker_address, condition=scope['condition_id'])
        positions, evidence = _verified_exact_positions(adapters[0])
        if positions:
            raise HoldEnd("initial_positions")
        starting_collateral = _collateral(adapters[0], gates[0], quote.reserve_pusd)
        record("initial_zero_state", positions_evidence=evidence, collateral=starting_collateral)
        for adapter, gate in zip(adapters, gates):
            capabilities.append(adapter.authorize_stage1_lifecycle(gate, submit_deadline_utc=end.isoformat()))
        for index, (adapter, capability, price) in enumerate(zip(adapters, capabilities, (quote.yes_buy, quote.no_buy))):
            control_tick()
            if index:
                _check_fills(adapters, expected, checkpoint=control_tick)
                _exact_open_orders(adapters[0].open_orders(), expected, maker=adapters[0].maker_address, condition=scope['condition_id'])
            rules = adapter.refresh_market_rules()
            candidate_rules = initial_public["rules"][adapter.token_id]
            if (rules["neg_risk"] is not candidate_rules["neg_risk"]
                    or _decimal(rules["tick_size"]) != _decimal(candidate_rules["tick_size"])
                    or _decimal(rules["min_order_size"]) != _decimal(candidate_rules["min_order_size"])
                    or _decimal(rules["fee_rate_bps"]) != _decimal(candidate_rules["fee_rate_bps"])):
                raise HoldEnd("market_rules_changed")
            control_tick()
            record("collateral_before_submit", leg=index + 1,
                   collateral=_collateral(adapter, gates[index], price * quote.size))
            record("submit_boundary", leg=index + 1, token_id=adapter.token_id,
                   candidate_fee_rate_bps=candidate_rules["fee_rate_bps"],
                   fresh_fee_rate_bps=rules["fee_rate_bps"], price=str(price), size=str(quote.size))
            response = adapter.place_order(
                {"token_id": adapter.token_id, "side": "BUY", "price": str(price),
                 "size": str(quote.size), "post_only": True}, stage1_capability=capability,
                geographic_eligibility_fresh_until_utc=geo["fresh_until_utc"],
            )
            oid = _order_id(response)
            if not oid or oid in expected:
                raise HoldEnd("submit_response")
            expected[oid] = (adapter.token_id, price, quote.size)
            record("order_acknowledged", order_id=oid, leg=index + 1)
        while True:
            control_tick()
            account_due = mono() >= next_account
            _check_fills(adapters, expected, check_rest=account_due, checkpoint=control_tick)
            if account_due:
                _exact_open_orders(adapters[0].open_orders(), expected, maker=adapters[0].maker_address, condition=scope['condition_id'])
                next_account = mono() + 1
            if mono() >= next_public:
                requested_at = mono()
                snapshot = public_reader(checkpoint=control_tick)
                terms_changed = terms_changed or any(snapshot["quote_inputs"][k] != v for k, v in initial_terms.items())
                record('public_observation', snapshot=snapshot)
                control_tick()
                public_quote(snapshot, now=wall(), condition_id=scope["condition_id"], token_ids=tokens)
                observation = observe_held_quote(snapshot, quote)
                scoring = scoring_reader(tuple(expected))
                control_tick()
                if set(scoring) != set(expected) or any(type(v) is not bool for v in scoring.values()):
                    raise HoldEnd("scoring_evidence")
                all_scoring = all_scoring and all(scoring.values())
                sample_time = mono()
                elapsed = 0 if last_sample is None else sample_time - last_sample
                counted = (elapsed / 60 if 0 < elapsed <= 60.5 and previous_visible
                           and observation["visible_two_sided"] else 0)
                visible_minutes += counted
                p_many += counted * observation["per_minute_many"]
                p_single += counted * observation["per_minute_single"]
                record("minute", snapshot=snapshot, observation=observation,
                       scoring=scoring, counted_minutes=counted)
                last_sample, previous_visible = sample_time, observation["visible_two_sided"]
                next_public = requested_at + PROFILE.public_refresh_seconds
            sleep(min(0.25, max(0, deadline_mono - mono())))
    except QuoteRefused as exc:
        reason = str(exc)
    except HoldEnd as exc:
        reason = exc.reason
        fill_seen = reason == "fill"
    except BaseException as exc:
        reason = "operator_stop" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "control_or_transport_failure"
        failure = type(exc).__name__
    finally:
        cleanup_start = mono()
        try:
            record("end_condition", reason=reason, exception_type=failure)
            record("cancel_all_requested", order_ids=list(expected))
        except Exception:
            failure = "JournalWriteError"
        # Cancellation is attempted even when recording the trigger failed.
        try:
            prior_acks = []
            try:
                for adapter in adapters:
                    proof = getattr(adapter, 'probe_evidence', lambda: {})().get('stage2_cancel_acknowledgment')
                    if proof is not None:
                        prior_acks.append(proof)
            except Exception:
                # An audit-reader failure cannot prevent the primary cancel.
                prior_acks = []
            response = adapters[0].cancel_all()
            remaining = adapters[0].open_orders()
            if remaining or not isinstance(response, dict) or response.get("not_canceled"):
                raise RuntimeError("explicit cancellation did not reconcile")
            canceled = _cancel_ack_ids(response)
            for proof in prior_acks:
                if (proof['profile_sha256'] != PROFILE.sha256 or proof['maker_address'] != scope['maker_address']
                        or proof['condition_id'] != scope['condition_id']
                        or not start <= utc(proof['checked_at_utc']) <= utc(wall())):
                    raise RuntimeError('emergency cancellation belongs to another session')
                canceled.update(_cancel_ack_ids(proof['response']))
            terminal = []
            for oid, (token, _, _) in expected.items():
                adapter = adapters[tokens.index(token)]
                order = adapter.get_order(oid)
                matched = _decimal(order.get("size_matched"))
                if _order_id(order) != oid or str(order.get("asset_id")) != token:
                    raise RuntimeError("terminal order identity differs")
                if matched > 0:
                    fill_seen = True
                elif (oid not in canceled
                        or str(order.get("status", "")).lower() not in {"canceled", "cancelled", "expired"}):
                    raise RuntimeError("terminal zero-fill order lacks explicit cancellation acknowledgment")
                terminal.append(order)
            cancel_ack = True
            record("cancel_all_acknowledged", response=response, terminal_orders=terminal,
                   **({'prior_acknowledgments': prior_acks} if prior_acks else {}))
            sleep(2)
            if adapters[0].open_orders():
                raise RuntimeError("order remains after cancellation quiescence")
            positions, evidence = _verified_exact_positions(adapters[0])
            if positions:
                fill_seen = True
            for adapter in adapters:
                if adapter.account_trades():
                    fill_seen = True
            ending_collateral = _collateral(adapters[0], gates[0], quote.reserve_pusd)
            if (not fill_seen and starting_collateral is not None
                    and ending_collateral['cash_pusd'] != starting_collateral['cash_pusd']):
                raise RuntimeError('no-fill collateral did not reconcile')
            cleanup_ok = mono() - cleanup_start <= PROFILE.cleanup_seconds
            record("zero_open_orders", positions_evidence=evidence, fill_seen=fill_seen,
                   collateral=ending_collateral,
                   cleanup_elapsed_seconds=mono() - cleanup_start, cleanup_in_budget=cleanup_ok)
        except BaseException as exc:
            failure = type(exc).__name__
            cleanup_ok = False
            # No heartbeat is sent after the primary cancellation attempt.
            # Observe the existing 10-15 s lapse window; never call it an ACK.
            try:
                until = cleanup_start + PROFILE.cleanup_seconds
                while mono() < until:
                    age = None if last_heartbeat is None else mono() - last_heartbeat
                    remaining = adapters[0].open_orders()
                    if not remaining:
                        record("dead_man_backstop_observed", heartbeat_age_seconds=age,
                               accepted_window=age is not None and 10 <= age <= 15)
                        break
                    sleep(0.25)
            except BaseException:
                pass
        try:
            record("terminal", cleanup_ok=cleanup_ok, cancel_acknowledged=cancel_ack,
                   fill_seen=fill_seen, failure_type=failure)
        finally:
            journal.close()
    journal_hash = hashlib.sha256(Path(journal_path).read_bytes()).hexdigest()
    prediction = {
        "schema_version": SCHEMA_VERSION, "kind": "prediction", "mode": mode,
        "scope": scope, "profile_sha256": PROFILE.sha256,
        "reward_day": start.date().isoformat(), "condition_id": scope["condition_id"],
        "P_many": p_many, "P_single": p_single, "visible_two_sided_minutes": visible_minutes,
        "all_observed_legs_scoring": all_scoring and len(expected) == 2 and last_sample is not None,
        "reward_terms_changed": terms_changed, "journal_sha256": journal_hash,
        "frozen_at_utc": utc(wall()).isoformat(), "earnings_read": False,
        "cleanup_ok": cleanup_ok, "cancel_acknowledged": cancel_ack,
        "fill_seen": fill_seen, "end_condition": reason, "failure_type": failure,
    }
    write_new(prediction_path, prediction)
    return prediction
