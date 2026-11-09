"""Guards: B072 owner-approved Pin B policy inputs, entirely synthetic."""
from weather.market.lfc_f2_breadth import example_policy


def pinb_row():
    return {**example_policy(), 'schema_version': 'lfc_campaign_policy_v0.4',
        'policy_name': 'Builtin-T1-PairedCheap20-Continue30', 'policy_revision': 5, 'revision': 2,
        'trading_end_toronto': '18:45:00', 'max_session_seconds': 35100,
        'learning_dates': ['2026-11-09', '2026-11-22'], 'transition_no_entry_date': None,
        'confirmation_dates': ['2026-11-23', '2026-12-22'], 'nominal_confirmation_dates': 30,
        'freeze_deadline_toronto': '2026-11-22T18:00:00-05:00',
        'max_submits_per_band': 40, 'max_requotes_per_band': 16,
        'learning_leg_arms': ['paired', 'cheap'], 'confirmation_leg_arm': 'paired',
        'per_band_daily_filled_cap_pusd': '30'}
