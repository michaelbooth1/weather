import pytest

from weather.market.mm_live_attendance import confirm_attended_session, session_confirmation_literal
from weather.market.mm_stage2_hold import CONFIRMATION


def test_exact_single_typed_session_confirmation():
    calls = []
    def read(prompt):
        calls.append(prompt)
        return session_confirmation_literal(CONFIRMATION, 'a' * 64)
    result = confirm_attended_session(CONFIRMATION, 'a' * 64, read_input=read)
    assert len(calls) == 1
    assert result['physical_location_eligible'] and result['no_circumvention']
    assert result['scope_sha256'] == 'a' * 64


@pytest.mark.parametrize('answer', ['', 'yes', CONFIRMATION, ' '])
def test_missing_or_wrong_confirmation_refuses(answer):
    with pytest.raises(RuntimeError, match='did not match'):
        confirm_attended_session(CONFIRMATION, 'a' * 64, read_input=lambda _: answer)
