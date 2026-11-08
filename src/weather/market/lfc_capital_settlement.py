"""Book proved zero payouts without requiring an ERC-1155 burn."""
from pathlib import Path

from weather.market.lfc_capital import CapitalBook
from weather.market.lfc_recording_io import read_recovered, response_bytes
from weather.market.lfc_settlement_record import envelope, validate_settlement
from weather.market.mm_stage2_hold import digest
from weather.operations.live_path_security import validate_contained_regular_file


def record_zero_payouts(ledger, root):
    count = 0
    conditions = sorted({lot['condition_id'] for lot in CapitalBook(ledger).lots.values()
                         if lot['remaining_basis'] and lot['remaining_quantity']})
    for condition in conditions:
        path = Path(root) / 'settlement' / (condition + '.json')
        if not path.exists():
            continue
        validate_contained_regular_file(Path(root), path)
        record, _ = read_recovered(path, lambda p: validate_settlement(
            validate_contained_regular_file(Path(root), p), condition))
        if not record['terminal']:
            continue
        payouts = envelope(response_bytes(record['resolution']))['data'][0]['payouts']
        zeros = {token for token, payout in zip(record['token_ids'], payouts) if payout == 0}
        keys = sorted(key for key, lot in CapitalBook(ledger).lots.items() if lot['condition_id'] == condition and
                      lot['token_id'] in zeros and lot['remaining_basis'] and lot['remaining_quantity'])
        if keys:
            ledger.record('capital_zero_resolution', condition_id=condition, intent_keys=keys,
                          settlement=record, settlement_sha256=digest(record))
            count += len(keys)
    return count
