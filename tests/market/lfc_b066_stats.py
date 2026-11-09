"""Guards: B066 fixture/replay uncertainty rates, without operational inputs."""
from collections import Counter
from pathlib import Path
import json

CURRENT = ''
APPLICATIONS = Counter()
ACTIVITIES = {}
VIEWS = {}


def pytest_addoption(parser):
    parser.addoption('--lfc-unknown-statistics', default=None)


def pytest_runtest_setup(item):
    global CURRENT
    CURRENT = item.nodeid


def pytest_configure(config):
    if not config.getoption('--lfc-unknown-statistics'):
        return
    from weather.market.lfc_capital import CapitalBook
    apply, figures = CapitalBook.apply, CapitalBook.figures
    def counted_apply(book, row):
        result = apply(book, row)
        if row['event'] == 'capital_activity':
            activity = row['activity']
            if book.incoming(activity):
                unknown = activity['cash_native'] is None
                phase = 'replay' if getattr(book.ledger, '_replaying', False) else 'fixture_write'
                APPLICATIONS[(phase, activity['type'], unknown)] += 1
                key = (CURRENT, activity['id'])
                ACTIVITIES[key] = (activity['type'], unknown)
        return result
    def counted_figures(book, *args, **kwargs):
        row = figures(book, *args, **kwargs)
        incoming = [book.activities[k] for k in book.unknown if book.incoming(book.activities[k])]
        VIEWS[(CURRENT, book.ledger.previous, tuple(sorted(book.unknown)))] = bool(incoming)
        return row
    CapitalBook.apply, CapitalBook.figures = counted_apply, counted_figures


def pytest_sessionfinish(session, exitstatus):
    argument = session.config.getoption('--lfc-unknown-statistics')
    if not argument:
        return
    output = Path(argument).absolute()
    assert output.parent == Path(r'C:\t\codex\T004\out') and output.name.startswith('b066-')
    by_type = {}
    for kind, unknown in ACTIVITIES.values():
        counts = by_type.setdefault(kind, {'incoming_activities': 0, 'initially_cash_unknown': 0})
        counts['incoming_activities'] += 1
        counts['initially_cash_unknown'] += int(unknown)
    row = {'fixture_only': True, 'exit_code': exitstatus, 'test_count': len(session.items),
        'unique_test_activity_observations': len(ACTIVITIES), 'by_type': by_type,
        'apply_occurrences': [{'phase': p, 'type': k, 'cash_unknown': u, 'count': n}
                              for (p,k,u),n in sorted(APPLICATIONS.items())],
        'distinct_observed_book_states': len(VIEWS),
        'states_with_unknown_incoming': sum(VIEWS.values()),
        'tests_with_unknown_incoming': len({key[0] for key,value in VIEWS.items() if value})}
    output.write_text(json.dumps(row, indent=2))
