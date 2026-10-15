"""Suite-wide pytest hooks. Keep this file to test infrastructure only.

tests/test_quarantine_registry.py fails if a merge drops any of these hooks.
"""

from tests.quarantine_plugin import (  # noqa: F401  (pytest discovers hooks by name)
    pytest_addoption,
    pytest_collection_modifyitems,
    pytest_configure,
    pytest_runtest_makereport,
    pytest_terminal_summary,
)
