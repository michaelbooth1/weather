"""Pure W policy terms and frozen city assignment; no runtime capability."""
from copy import deepcopy
from datetime import date

from weather.market.lfc_accounting import quantity
from weather.market.lfc_campaign_policy import PolicyRefused


FIELDS = frozenset({'quote_offset_mode', 'wide_offset_cents', 'city_quote_offset_assignments'})
DEFAULTS = {'quote_offset_mode': 'standard', 'wide_offset_cents': '3.0',
            'city_quote_offset_assignments': []}
ARM_FIELDS = ('quote_offset_mode', 'wide_offset_cents', 'offset_assignment_source', 'standard_quote_offset_pusd')


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
    if (mode == 'wide' or assignments) and row.get('schema_version') != 'lfc_campaign_policy_v0.4':
        raise PolicyRefused('wide_requires_pinb')
    if (mode == 'wide' or assignments) and (
            type(row.get('policy_revision')) is not int or row['policy_revision'] < 7):
        raise PolicyRefused('wide_requires_policy_revision_7')


def economic_values(row):
    """Canonical defaults preserve all historical standard economic hashes."""
    result = {key: deepcopy(row.get(key, value)) for key, value in DEFAULTS.items()}
    result['wide_offset_cents'] = '3.0'
    return result


def field_keys(row, keys):
    """Historical snapshots gain no implicit serialized fields."""
    return set(keys) | (FIELDS & row.keys())


def economic_keys(row, keys):
    return set(keys) | FIELDS if configured(row) else set(keys) - FIELDS


def economic_value(row, key):
    return economic_values(row)[key] if key in FIELDS else row.get(key)


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
    """Compatibility helper for a carried post-fill mode and a new distance."""
    return successor_row(row, post_fill_mode=row.get('post_fill_mode', 'continue'), quote_offset_mode=mode)


def successor_row(policy, *, post_fill_mode, quote_offset_mode, wide_offset_cents='3.0', city_assignments=None):
    """Prepare current+1 economics, disabled, carrying every unrelated term."""
    row = getattr(policy, 'raw', policy)
    if (row.get('enabled') is not False or type(row.get('policy_revision')) is not int or
            row['policy_revision'] < 6 or row.get('schema_version') != 'lfc_campaign_policy_v0.4'):
        raise PolicyRefused('wide_successor_requires_disabled_revision_6_or_later')
    result = deepcopy(row)
    result.update(revision=row['revision'] + 1, policy_revision=row['policy_revision'] + 1,
                  post_fill_mode=post_fill_mode, quote_offset_mode=quote_offset_mode,
                  wide_offset_cents=wide_offset_cents)
    if city_assignments is not None:
        result['city_quote_offset_assignments'] = deepcopy(city_assignments)
    from weather.market.lfc_pair_policy import validate as validate_pairs
    validate_pairs(result)
    validate(result)
    return result


def main(argv=None):
    """Create one disabled successor from an owner-supplied policy copy."""
    import argparse
    from pathlib import Path
    from weather.market.lfc_campaign_policy import load_policy, parse_policy
    from weather.market.lfc_recording_io import read_bytes, strict_json, write_new
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('--upgrade-from', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--post-fill-mode', choices=['continue', 'complete_pairs'], required=True)
    parser.add_argument('--quote-offset-mode', choices=['standard', 'wide'], required=True)
    parser.add_argument('--wide-offset-cents', default='3.0')
    parser.add_argument('--city-assignments', type=Path)
    args = parser.parse_args(argv)
    if (not args.upgrade_from.is_absolute() or not args.output.is_absolute() or
            args.city_assignments is not None and not args.city_assignments.is_absolute()):
        parser.error('absolute paths required')
    assignments = strict_json(read_bytes(args.city_assignments, 65536)) if args.city_assignments is not None else None
    row = successor_row(load_policy(args.upgrade_from), post_fill_mode=args.post_fill_mode,
        quote_offset_mode=args.quote_offset_mode, wide_offset_cents=args.wide_offset_cents,
        city_assignments=assignments)
    write_new(args.output, parse_policy(row).raw)
    print('Prepared disabled current+1 policy; no runtime state changed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
