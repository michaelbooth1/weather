"""Archive synthetic market-day files through the real catalog for reader tests.

Reuses the full proof-chain ``corpus`` fixture from the catalog tests: the
markers, entries and caches below are produced by the production publishers,
never hand-written JSON. Parametrize ``corpus`` indirectly with the files to
archive; the day is ``highest-temperature-in-toronto-on-june-15-2026``.
"""
from pathlib import Path

from tests.operations.test_cold_archive_catalog import cached, corpus, recovery, register  # noqa: F401
from weather import cold_archive_locations as locations
from weather.operations import cold_archive_catalog as catalog

SLUG = "highest-temperature-in-toronto-on-june-15-2026"


def archive_day(corpus, *, cache=False):
    """Publish the first chunk's markers, optionally a verified cache, then remove those originals.

    The fixture stages one chunk, so with several file families only the first
    family's files are archived; the others stay local.
    """
    if cache:
        catalog.publish_cache(**cached(corpus))
    else:
        register(corpus)
    for path in locations.registered_sources(corpus.day):
        path.unlink()
    return corpus.day


def snapshots_root(corpus) -> Path:
    return corpus.root / "snapshots"
