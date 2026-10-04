"""Suite-wide pytest hooks. Keep this file to test infrastructure only."""

from tests.quarantine_plugin import (  # noqa: F401  (pytest discovers hooks by name)
    pytest_collection_modifyitems,
    pytest_configure,
    pytest_runtest_makereport,
    pytest_terminal_summary,
)
