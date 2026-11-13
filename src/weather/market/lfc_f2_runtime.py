"""Owner-task wiring for F2. Importing this module creates no account client."""
from pathlib import Path
from decimal import Decimal

from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_f2_controller import F2Band, F2Coordinator, ScopedVenue
from weather.market.lfc_f2_selection import band_table, validate_table
from weather.market.lfc_recording_io import write_new, file_sha
from weather.market.mm_stage2_hold import digest


def stream_factory(registry, *, retain_trade_identity=False):
    from weather.market.re1_transport import PairStream
    class CampaignPairStream(PairStream):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.retain_trade_identity = retain_trade_identity
            registry[self.condition_id] = self

        def _normalize_event(self, item):
            market = str(item.get('market', '')).lower() if isinstance(item, dict) else ''
            peer = registry.get(market)
            if peer is not None and peer is not self:
                # Validate another selected band's exact pair before ignoring
                # it here. That band's own account stream supplies its events.
                # Unknown/foreign/malformed events still fail the whole stream.
                peer._normalize_event(item)
                return []
            rows = super()._normalize_event(item)
            if (self.retain_trade_identity and isinstance(item, dict) and
                    str(item.get('event_type') or '').lower() == 'trade'):
                # PairStream historically retained the order and raw hash only.
                # Breadth continuation must bind the wire trade ID to fresh REST
                # evidence. Keep the old protocol's journal shape unchanged.
                trade_id = item.get('id')
                if not isinstance(trade_id, str) or not trade_id.strip() or len(trade_id) > 256:
                    raise RuntimeError('repost_trade_identity_unproven')
                rows = [dict(row, trade_id=trade_id) for row in rows]
            return rows
    return CampaignPairStream


def run_live(runtime, authority, status):
    """Called only after durable account/date claim and the owner setup gates."""
    from weather.market.lfc_campaign_runtime import selection_account_screen
    from weather.market.lfc_fees import guard_signed_orders
    from weather.market.lfc_pilot import LfcPublicBooks
    from weather.market.re1_owner_checks import code_identity
    from weather.market.re1_transport import OwnerVenue, build_client, load_owner_credentials
    policy, entry, claim = authority.policy, authority.entry, authority.claim
    from weather.market.lfc_f2_breadth import enabled, arm_field_keys, PROTOCOL as BREADTH_PROTOCOL
    breadth = enabled(policy)
    protocol = BREADTH_PROTOCOL if breadth else 'lfc_autostart_v2'
    authority.preflight(now=runtime.clock.now(), commit=code_identity())
    ledger = runtime.state.ledger
    ledger.policy_metadata = status.policy_metadata
    table = authority.selection()
    selected = validate_table(table, now=runtime.clock.now(), policy=policy)
    fields, guard = load_owner_credentials('live')
    if fields['FUNDER_ADDRESS'].lower() != runtime.state.maker.lower():
        raise RuntimeError('preflight_account_changed')
    timeouts = authority.prepared['preflight']['timeouts_seconds']
    reader = OwnerVenue(build_client(fields, readonly=True, timeout=max(timeouts.values())), fields, guard,
                        readonly=True, timeouts=timeouts)
    raws, coordinator = [], None
    try:
        if not breadth:
            balances = reader.balances()
            from weather.market.lfc_ledger import fetch_account_positions
            refusals = authority.start_gates(ledger=ledger, now=runtime.clock.now(), maker_address=runtime.state.maker,
                                              open_orders=reader.open_orders(), positions=fetch_account_positions(runtime.state.maker))
            if refusals:
                raise RuntimeError('f2_start_gates')
            reserve = sum(Decimal(row['quote']['reserve_pusd']) for row in selected)
            CapitalBook(ledger).gate(reserve=reserve, available_cash=balances['available_collateral'])
            for row in selected:
                selection_account_screen(band_table(table, row['condition_id']), balances)
        root_id = 'F2-' + claim['attempt_id']
        directory = runtime.pilot_root / ('session-' + root_id)
        directory.mkdir(parents=True, exist_ok=False)
        write_new(directory / 'selection.json', table)
        write_new(directory / 'attempt.json', {'session_id': root_id, 'attempt_id': claim['attempt_id'],
                    'policy_sha256': policy.sha256, 'selection_sha256': digest(table), **status.policy_metadata,
                    **({'quote_arms': [{key: row[key] for key in ('market_id', *arm_field_keys(policy))}
                         for row in selected]} if breadth else {})})
        def verify():
            # Keep the same in-process ledger object until every band closes.
            # The later ordinary postcheck reopens/validates it independently.
            read = runtime.read_account()
            return runtime.core_proof(ledger, read)
        def repost_proof(band):
            from weather.market.lfc_f2_reconcile import prove
            return prove(runtime, band, runtime.read_account())
        coordinator = F2Coordinator(ledger=ledger, clock=runtime.clock, directory=directory, session_id=root_id,
                      attempt_id=claim['attempt_id'], policy=policy, entry=entry, table=table,
                      status=status, verify=verify, guard=guard, repost_proof=repost_proof)
        status.bind(root_id, directory=directory, selection={}, ledger=ledger)
        status.session = coordinator
        public = LfcPublicBooks(clock=runtime.clock.now)
        registry = {}
        factory = stream_factory(registry, retain_trade_identity=breadth)
        number = ledger.counted_sessions() + 1
        bindings = []
        for index, row in enumerate(selected, 1):
            band_directory = directory / ('band-' + str(index))
            band_directory.mkdir()
            client = build_client(fields, timeout=max(timeouts.values()))
            try:
                raw = OwnerVenue(client, fields, guard, condition=row['condition_id'], tokens=row['token_ids'],
                    directory=band_directory, timeouts=timeouts, size=policy.raw['shares_per_leg'],
                    reserve_cap=policy.raw['per_band_cap_pusd'], profile=authority.profile, stream_factory=factory)
            except BaseException:
                client.close()
                raise
            raws.append(raw)
            raw.allowed_trade_tokens = tuple(row['token_ids'][leg] for leg in row['trade_legs'])
            guard_signed_orders(raw)
            bindings.append((index, row, band_directory, raw))
            status.progress()
        # Every exact-pair stream exists before either can receive an event.
        for raw in raws:
            raw.start()
            status.progress()
        if breadth:
            read = authority.refresh_go(progress=status.progress)
            balances = read['balances']
            refusals = authority.start_gates(ledger=ledger, now=runtime.clock.now(), maker_address=runtime.state.maker,
                                            open_orders=read['open_orders'], positions=read['positions'])
            if refusals:
                raise RuntimeError('f2_start_gates')
            selected = validate_table(table, now=runtime.clock.now(), policy=policy)
            reserve = sum(Decimal(row['quote']['reserve_pusd']) for row in selected)
            CapitalBook(ledger).gate(reserve=reserve, available_cash=balances['available_collateral'])
            for row in selected:
                selection_account_screen(band_table(table, row['condition_id']), balances)
            go_evidence = guard.clean({'read': read, 'proof': authority.go_proof,
                'attempt_id': claim['attempt_id'], 'source_prepared_file': authority.prepared.get('file'),
                'source_prepared_sha256': authority.prepared.get('sha256')})
            # B090-H: the guard drops 'owner' fields that carry our API key, so on any
            # account with own trades the stored read can never hash like the proven
            # raw read. Bind the proof to the raw read and record both hashes.
            if digest(read) != authority.go_proof['read_sha256']:
                raise RuntimeError('go_read_changed_after_proof')
            go_evidence['raw_read_sha256'] = authority.go_proof['read_sha256']
            go_evidence['redacted_read_sha256'] = digest(go_evidence['read'])
            go_path = directory / 'go_account.json'
            from weather.market.lfc_recording_io import STATE_JSON_LIMIT
            write_new(go_path, go_evidence, max_bytes=STATE_JSON_LIMIT)
            coordinator.scope['go_account_sha256'] = file_sha(go_path)
            coordinator.journal.record('go_account_proven', sha256=coordinator.scope['go_account_sha256'])
        for index, row, band_directory, raw in bindings:
            sid = root_id + '-b' + str(index)
            arm_fields = ({key: row[key] for key in arm_field_keys(policy)}
                          if breadth else {})
            day_fields = ({'quote_day_utc': runtime.clock.now().date().isoformat(),
                           'per_band_daily_filled_cap_pusd': policy.raw['per_band_daily_filled_cap_pusd']} if breadth else {})
            attempt = {'session_id': sid, 'session_number': number, 'number': number,
                       'counted': index == 1, 'protocol': protocol, **status.policy_metadata, **arm_fields, **day_fields}
            from weather.market.lfc_f2_pinb import enabled as pinb
            limit_fields = ({'autostart_policy_schema': policy.raw['schema_version'],
                'max_submits_per_band': policy.raw['max_submits_per_band'],
                'max_requotes_per_band': policy.raw['max_requotes_per_band']} if pinb(policy) else {})
            attempt.update(limit_fields)
            write_new(band_directory / 'attempt.json', attempt)
            ledger.record('session_start', session_id=sid, counted=index == 1, session_number=number,
                    owner_local_date=entry.local_date, directory=band_directory.relative_to(runtime.pilot_root).as_posix(),
                    condition_id=row['condition_id'], market_id=row['market_id'], event_date=row['target_date'],
                    event_slug=row['event_slug'], selection_sha256=digest(table), protocol=protocol, **arm_fields, **day_fields,
                    **({'go_account_sha256': coordinator.scope['go_account_sha256']} if breadth else {}),
                    autostart_attempt_id=claim['attempt_id'], autostart_policy_sha256=policy.sha256, **limit_fields)
            band = F2Band(policy=policy, entry=entry, ledger=ledger, session_id=sid, profile=authority.profile,
                    root=runtime.pilot_root, exclusion={'event_slug': row['event_slug'],
                        'condition_ids': row['event_condition_ids'], 'timezone_name': row['market_timezone']},
                    baselines={'t40_sha256': digest(authority.baseline)},
                    venue=ScopedVenue(raw, coordinator, sid), public=public, table=band_table(table, row['condition_id']),
                    clock=runtime.clock, directory=band_directory, guard=guard, mode='live',
                    confirmation=authority.confirmation(band_table(table, row['condition_id']), ledger),
                    attempt=attempt, scheduled_authority=authority)
            coordinator.bands.append(band)
        authority.check(starting=True)
        result = coordinator.run()
        status.open_rows, status.reason = coordinator.open_rows, result['reason']
        return 0 if result['cleanup_ok'] and result['failure_type'] is None and not status.stop_seen else 1
    finally:
        # Setup failure cannot have posted: run() is the only POST-capable
        # phase. The claim and any unfinished packet stay sticky for recovery.
        if coordinator is not None:
            status.open_rows = coordinator.open_rows
        closing_error = None
        for raw in reversed(raws):
            try:
                raw.close()
            except BaseException as exc:
                closing_error = closing_error or exc
        try:
            reader.close()
        except BaseException as exc:
            closing_error = closing_error or exc
        if closing_error is not None:
            raise closing_error
