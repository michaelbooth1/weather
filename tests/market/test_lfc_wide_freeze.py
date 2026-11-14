"""Guards: T114 same-revision deletion, city-split economics and immutable seals."""
from copy import deepcopy

import pytest

from tests.market.lfc_wide_fixtures import policy_row
from tests.market.test_lfc_wide_successor import crossover
from tests.market.test_lfc_pinb_migration import existing_pina, stamp
from tests.market.test_lfc_campaign import MAKER, Mutexes
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_campaign_recovery import close_empty
from weather.market.lfc_campaign_state import StateRefused
from weather.market.lfc_f2_freeze import capture, economic_digest, labels, verify
from weather.market.lfc_wide_policy import successor_row


def claim_day(state, clock, policy, day):
    clock.value = stamp(day+'T14:00:00Z')
    claim = state.claim(next(e for e in policy.entries if e.local_date == day), policy, clock.now())
    close_empty(state, claim, clock.now())


def split_policy():
    source = policy_row('complete_pairs')
    return parse_policy(successor_row(source, post_fill_mode='complete_pairs', quote_offset_mode='standard',
        city_assignments=crossover(source['market_ids'])) | {'policy_revision': 9})


def test_claim_requires_next_revision_even_when_wide_fields_are_deleted(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, *_ = existing_pina(tmp_path)
        old = parse_policy(policy_row())
        claim_day(state, clock, old, '2026-11-16')
        wide = parse_policy(successor_row(old, post_fill_mode='continue', quote_offset_mode='wide'))
        claim_day(state, clock, wide, '2026-11-17')
        rollback = parse_policy({k: v for k, v in wide.raw.items() if k not in {'quote_offset_mode', 'wide_offset_cents'}})
        with pytest.raises(StateRefused, match='economic_policy_change_requires_revision'):
            claim_day(state, clock, rollback, '2026-11-18')
        claim_day(state, clock, parse_policy(rollback.raw | {'policy_revision': 8, 'revision': rollback.raw['revision']+1}),
                  '2026-11-18')


def test_city_assignment_edit_requires_a_new_revision(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, *_ = existing_pina(tmp_path)
        old = split_policy()
        claim_day(state, clock, old, '2026-11-20')
        changed = deepcopy(old.raw)
        item = changed['city_quote_offset_assignments'][1]
        item['wide_cities'], item['standard_cities'] = item['standard_cities'], item['wide_cities']
        changed = parse_policy(changed)
        assert economic_digest(changed) != economic_digest(old)
        with pytest.raises(StateRefused, match='economic_policy_change_requires_revision'):
            claim_day(state, clock, changed, '2026-11-21')


def test_frozen_split_binds_modes_and_lists_without_rewriting_the_original(tmp_path):
    with account_lease(MAKER, backend=Mutexes()):
        state, clock, *_ = existing_pina(tmp_path)
        frozen = split_policy()
        clock.value = stamp('2026-11-22T22:55:00Z')
        capture(state, frozen, clock.now())
        path = state.root/'policies'/'freeze-pinb.json'; original = path.read_bytes()
        equivalent = parse_policy(frozen.raw | {'policy_revision': 10, 'revision': frozen.raw['revision']+1})
        assert labels(state, equivalent, '2026-11-23')['evidence_lane'] == 'confirmation'
        changed = parse_policy(successor_row(frozen, post_fill_mode='complete_pairs', quote_offset_mode='wide',
                                             city_assignments=[]))
        assert labels(state, changed, '2026-11-23')['evidence_lane'] == 'successor_learning'
        capture(state, changed, clock.now())
        assert path.read_bytes() == original and verify(state, policy=frozen)['on_time']
