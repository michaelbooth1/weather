"""Guards: B084 a bounded retained account proof reopens at the 25,000-row cap."""
from tests.market.test_lfc_account_pages_b079 import trade_row
from tests.market.test_lfc_campaign import MAKER, Mutexes
from tests.market.test_lfc_evidence_budgets_b083 import recovery
from tests.market.test_lfc_unattended_account_reads import sdk_client
from weather.market.lfc_campaign_guard import account_lease
from weather.market.lfc_campaign_history import history_refusals, validate_recovery
from weather.market.lfc_ledger import Ledger
from weather.market.lfc_recording_io import ACCOUNT_EVIDENCE_JSON_LIMIT, STATE_JSON_LIMIT, file_sha
from weather.market.re1_transport import OwnerVenue


def test_owner_recovery_reopens_full_25000_sdk_trade_proof(tmp_path, record_testsuite_property):
    def page(number):
        start = (number - 1)*5000
        return dict(data=[trade_row(n) for n in range(start, start + 5000)],
                    next_cursor='LTE=' if number == 5 else str(number), limit=5000, count=5000)
    client, _, http, calls = sdk_client(page)
    venue = object.__new__(OwnerVenue)
    venue.client, venue.condition = client, None
    venue.trades_after, venue.trades_seconds = '1791583200', 60
    try:
        rows = venue.trades()
    finally:
        http.close()
    assert len(rows) == 25000 and len(calls) == 5
    with account_lease(MAKER, backend=Mutexes()):
        ledger, read, event = recovery(tmp_path, rows)
        target = tmp_path/event['file']
        before = file_sha(target)
        size = target.stat().st_size
        record_testsuite_property('retained_25000_trade_bytes', size)
        assert 25_000_000 < size < ACCOUNT_EVIDENCE_JSON_LIMIT == STATE_JSON_LIMIT == 256_000_000
        saved = validate_recovery(ledger, tmp_path, event)
        assert saved['account_read'] == read
        reopened = Ledger.open(ledger.path, clock=ledger.clock)
        assert history_refusals(reopened, tmp_path) == {}
        assert validate_recovery(reopened, tmp_path, event) == saved
        assert file_sha(target) == before
