"""Guards: explicit reuse of a task-owned synthetic B065 fixture, never live state."""


def pytest_addoption(parser):
    parser.addoption('--lfc-existing-scale', default=None)
    parser.addoption('--lfc-build-scale', action='store_true', default=False)
    parser.addoption('--lfc-scale-archive', default=None)
