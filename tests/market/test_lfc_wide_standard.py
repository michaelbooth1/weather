"""Guards: T114 standard proposals, economic hashes and inert T113 traces."""
import hashlib
import json
from pathlib import Path

import pytest

from tests.market.lfc_wide_fixtures import controller_fixture, policy_row, trace
from tests.market.test_lfc_f2_selection import universe, NOW
from weather.market.lfc_campaign_policy import parse_policy
from weather.market.lfc_f2_freeze import economic_digest
from weather.market.lfc_f2_selection import candidate


GOLDEN = json.loads((Path(__file__).parents[1]/'fixtures'/'lfc_wide_standard_8f2b018f.json').read_text())


def sha(value):
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@pytest.mark.parametrize('mode', ['continue', 'complete_pairs'])
@pytest.mark.parametrize('extra', [{}, {'quote_offset_mode': 'standard', 'wide_offset_cents': '3.0'},
                                  {'quote_offset_mode': 'standard', 'city_quote_offset_assignments': []}])
def test_standard_is_exactly_the_accepted_t113_path(tmp_path, mode, extra):
    row = policy_row(mode, **extra)
    policy = parse_policy(row)
    expected = GOLDEN['modes'][mode]
    assert economic_digest(policy) == expected['digest']
    values = [candidate(band, now=NOW, policy=policy, held=set()) for band in universe()]
    assert sha(values) == expected['candidate_sha256']
    controller, account, *_ = controller_fixture(tmp_path, row)
    assert sha(trace(controller, account)) == expected['trace_sha256']
    assert all('quote_offset_mode' not in band.scope for band in controller.bands)
