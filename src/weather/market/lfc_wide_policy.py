"""Pure W policy terms and frozen city assignment; no runtime capability."""
from copy import deepcopy
from datetime import date

from weather.market.lfc_accounting import quantity
from weather.market.lfc_campaign_policy import PolicyRefused


FIELDS = frozenset({'quote_offset_mode', 'wide_offset_cents', 'city_quote_offset_assignments'})
DEFAULTS = {'quote_offset_mode': 'standard', 'wide_offset_cents': '3.0',
            'city_quote_offset_assignments': []}


def validate(row):
    """Validate only W's additions; the existing parser owns all other rails."""
    mode = row.get('quote_offset_mode', 'standard')
    if not isinstance(mode, str) or mode not in ('standard', 'wide'):
        raise PolicyRefused('unsupported_quote_offset_mode')
    value = row.get('wide_offset_cents', '3.0')
    try:
        valid = not isinstance(value, bool) and quantity(value) == 3
    except (ValueError, TypeError, ArithmeticError):
        valid = False
    if not valid:
        raise PolicyRefused('unsupported_wide_offset_cents')
    assignments = row.get('city_quote_offset_assignments', [])
    if not isinstance(assignments, list):
        raise PolicyRefused('unsupported_city_quote_offset_assignments')
    days = []
    for item in assignments:
        if not isinstance(item, dict) or set(item) != {'date', 'standard_cities', 'wide_cities'}:
            raise PolicyRefused('unsupported_city_quote_offset_assignments')
        try:
            day = date.fromisoformat(item['date'])
            first, last = map(date.fromisoformat, row['learning_dates'])
        except (TypeError, ValueError, KeyError):
            raise PolicyRefused('unsupported_city_quote_date') from None
        if item['date'] != day.isoformat() or not first <= day <= last:
            raise PolicyRefused('unsupported_city_quote_date')
        days.append(item['date'])
        groups = [item['standard_cities'], item['wide_cities']]
        for group in groups:
            if (not isinstance(group, list) or any(not isinstance(city, str) for city in group) or
                    group != sorted(set(group))):
                raise PolicyRefused('unsupported_city_quote_partition')
        if set(groups[0]) & set(groups[1]) or sorted(groups[0] + groups[1]) != row['market_ids']:
            raise PolicyRefused('unsupported_city_quote_partition')
    if days != sorted(set(days)):
        raise PolicyRefused('unsupported_city_quote_date')
    if (mode == 'wide' or assignments) and (
            type(row.get('policy_revision')) is not int or row['policy_revision'] < 7):
        raise PolicyRefused('wide_requires_policy_revision_7')


def economic_values(row):
    """Canonical defaults preserve all historical standard economic hashes."""
    result = {key: deepcopy(row.get(key, value)) for key, value in DEFAULTS.items()}
    result['wide_offset_cents'] = '3.0'
    return result


def configured(row):
    return row.get('quote_offset_mode', 'standard') == 'wide' or bool(row.get('city_quote_offset_assignments'))


def apply_arm(row, local_date, city, original):
    """Preserve the original hash arms, applying only the declared distance."""
    if not configured(row):
        return original
    result = {**original, **assignment(row, local_date, city),
              'standard_quote_offset_pusd': original['quote_offset_pusd']}
    if result['quote_offset_mode'] == 'wide':
        result['quote_offset_pusd'] = '0.030'
    return result


def assignment(row, local_date, city):
    """A declared partition overrides the global mode for its exact date only."""
    mode, source = row.get('quote_offset_mode', 'standard'), 'policy'
    for item in row.get('city_quote_offset_assignments', []):
        if item['date'] == local_date:
            if city not in item['standard_cities'] + item['wide_cities']:
                raise PolicyRefused('city_quote_assignment_missing')
            mode = 'wide' if city in item['wide_cities'] else 'standard'
            source = 'city_quote_offset_assignments'
            break
    return {'quote_offset_mode': mode, 'wide_offset_cents': '3.0', 'offset_assignment_source': source}


def disabled_successor(row, *, mode='wide'):
    """Return a reviewable revision-7 dict, changing only the requested terms."""
    if row.get('enabled') is not False or row.get('policy_revision') != 6:
        raise PolicyRefused('wide_successor_requires_disabled_revision_6')
    result = deepcopy(row)
    result.update(revision=row['revision'] + 1, policy_revision=7,
                  quote_offset_mode=mode, wide_offset_cents='3.0')
    validate(result)
    return result
