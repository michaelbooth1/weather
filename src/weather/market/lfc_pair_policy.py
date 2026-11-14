"""Economic policy contract for Pin B's complete-pairs successor (T113)."""
from copy import deepcopy

from weather.market.lfc_campaign_policy import PolicyRefused
from weather.market.lfc_pair_completion import COMPLETE_PAIRS, CONTINUE, MODES, mode


FIELD = 'post_fill_mode'
FIRST_REVISION = 6


def validate(raw):
    try:
        selected = mode(raw)
    except ValueError:
        raise PolicyRefused('unsupported_post_fill_mode') from None
    if selected == COMPLETE_PAIRS:
        revision = raw.get('policy_revision')
        if type(revision) is not int or revision < FIRST_REVISION:
            raise PolicyRefused('complete_pairs_requires_policy_revision_6')
        if raw.get('schema_version') != 'lfc_campaign_policy_v0.4':
            raise PolicyRefused('complete_pairs_requires_pinb')
        from weather.market.lfc_f2_breadth import CONTINUE as FILL_CONTINUE
        if raw.get('on_first_band_fill') != FILL_CONTINUE:
            raise PolicyRefused('complete_pairs_requires_fill_continuation')
    return selected


def field_keys(raw, keys):
    """Omitted historical snapshots keep their original key set and bytes."""
    return set(keys) | ({FIELD} if FIELD in raw else set())


def economic_value(raw, key):
    return mode(raw) if key == FIELD else raw.get(key)


def economic_keys(raw, keys):
    """Explicit/omitted continue retain one historical economic identity."""
    return set(keys)-{FIELD} if mode(raw) == CONTINUE else set(keys) | {FIELD}


def successor_row(policy):
    """Prepare exactly revision 6, disabled, with all money/clock terms carried.

    This is a pure dictionary transformation. Enrollment, task state, live
    policy files, freezes and claims are never read or changed here.
    """
    if (policy.raw.get('schema_version') != 'lfc_campaign_policy_v0.4' or
            policy.raw.get('policy_revision') != 5 or mode(policy.raw) != CONTINUE):
        raise PolicyRefused('complete_pairs_successor_requires_revision_5')
    row = deepcopy(policy.raw)
    row.update(post_fill_mode=COMPLETE_PAIRS, policy_revision=FIRST_REVISION,
               revision=row['revision']+1, enabled=False)
    validate(row)
    return row


def support():
    return {'values': list(MODES), 'historical_default': CONTINUE,
            'complete_pairs_min_policy_revision': FIRST_REVISION, 'economic': True}


def main(argv=None):
    """Prepare a create-only disabled B successor from an owner-supplied copy."""
    import argparse
    from pathlib import Path
    from weather.market.lfc_campaign_policy import load_policy, parse_policy
    from weather.market.lfc_recording_io import write_new
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('--upgrade-from', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.upgrade_from.is_absolute() or not args.output.is_absolute():
        parser.error('absolute paths required')
    successor = parse_policy(successor_row(load_policy(args.upgrade_from)))
    write_new(args.output, successor.raw)
    print('Prepared disabled revision-6 complete-pairs policy; no runtime state changed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
