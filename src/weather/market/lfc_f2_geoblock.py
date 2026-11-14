"""One immutable, actually collected pass/fail receipt per account cadence."""
from dataclasses import asdict, dataclass

from weather.market.mm_stage2_hold import HoldEnd, digest, utc
from weather.market.re1_resilience import transient


@dataclass(frozen=True)
class GeoblockReceipt:
    blocked: object
    collected_at_utc: str
    collected_monotonic: float

    def get(self, key, default=None):
        return getattr(self, key, default)

    @property
    def sha256(self):
        return digest(asdict(self))


class SharedGeoblock:
    CADENCE = 30

    def __init__(self, clock, journal):
        self.clock, self.journal = clock, journal
        self.receipt, self.next_read = None, float('-inf')

    def read(self, fetch):
        if self.clock.monotonic() >= self.next_read:
            # Failed attempts spend the same cadence. Reusing a receipt never
            # moves its collection time; each band enforces its ordinary budget.
            self.next_read = self.clock.monotonic() + self.CADENCE
            self.journal.record('geoblock_request')
            try:
                result = fetch()
            except Exception as exc:
                self.journal.record('read_unavailable', fact='geoblock', exception_type=type(exc).__name__)
                if not transient(exc):
                    raise
            else:
                # Never retain or inspect geography values beyond pass/fail.
                blocked = result.get('blocked') if isinstance(result, dict) else None
                blocked = False if blocked is False else True if blocked is True else None
                self.receipt = GeoblockReceipt(blocked, utc(self.clock.now()).isoformat(),
                                                self.clock.monotonic())
                self.next_read = self.receipt.collected_monotonic + self.CADENCE
                self.journal.record('geoblock_response', response=asdict(self.receipt),
                                    receipt_sha256=self.receipt.sha256)
        return self.receipt


def read_for_band(band):
    coordinator = band.venue.coordinator
    receipt = coordinator.geoblock.read(band.venue.raw.geography)
    if receipt is not None:
        band.freshness.success['geoblock'] = receipt.collected_monotonic
        band.freshness.next_read['geoblock'] = receipt.collected_monotonic + 30
        if getattr(band, '_geoblock_receipt_sha256', None) != receipt.sha256:
            band.journal.record('geoblock_receipt', **asdict(receipt), receipt_sha256=receipt.sha256)
            band._geoblock_receipt_sha256 = receipt.sha256
        if receipt.blocked is not False:
            coordinator.account_fault_reason = 'geoblock'
            raise HoldEnd('geoblock')
    return receipt
