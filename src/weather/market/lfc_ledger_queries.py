"""Replay-derived row indexes; legacy in-memory evidence views retain scan semantics."""


def event_rows(ledger, event, *, field=None, value=None):
    indexed = getattr(ledger, 'event_rows', None)
    if callable(indexed):
        return indexed(event, field=field, value=value)
    return tuple(row for row in ledger.rows if row['event'] == event and
                 (field is None or row.get(field) == value))
