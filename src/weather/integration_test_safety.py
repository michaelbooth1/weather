"""Fail-closed external-I/O boundary for repository integration tests.

The production host's bounded suite and hosted CI set the environment marker
below. Real transports and mutation surfaces check it at their last local
boundary; explicitly injected fixture transports remain available to
deterministic tests.
"""

from __future__ import annotations

import os


INTEGRATION_TEST_OFFLINE_ENV = "WEATHER_INTEGRATION_TEST_OFFLINE"
_OFFLINE_LATCHED = os.environ.get(INTEGRATION_TEST_OFFLINE_ENV) == "1"


def integration_test_offline() -> bool:
    """Return the sticky process-level qualification safety state."""

    return _OFFLINE_LATCHED or os.environ.get(INTEGRATION_TEST_OFFLINE_ENV) == "1"


def require_real_external_io_allowed(operation: str) -> None:
    """Reject a real external-I/O operation inside guarded test execution."""

    if integration_test_offline():
        raise RuntimeError(
            f"{operation} is forbidden by the integration-test offline boundary"
        )


__all__ = [
    "INTEGRATION_TEST_OFFLINE_ENV",
    "integration_test_offline",
    "require_real_external_io_allowed",
]
