"""O9 book-summary staging tool for the 16 GB capture host.

Plan: night-plans/o9/O9-TRANSFER-PLAN.md (sections 1-5). Owner approval: DECISION_LOG 2026-10-07,
"O9 book-summary transfer yes". Master-agent runs this; the workstation never runs it against production.

Subcommands
-----------
preflight      Stat only: exactly 552 ``os.stat`` calls, one per allowlisted
               ``order_books_summary.csv``. With ``--probe-gz``, one more stat of
               ``order_books_summary.csv.gz`` for each folder whose .csv is absent. No open, no read, no
               directory listing. Prints one JSON line per folder plus a totals line. Writes nothing.
stage          Writes ``SOURCE-MANIFEST.json`` (stat-only source list) into ``--out`` BEFORE any file is
               copied, then filters and gzips each present summary into
               ``--out/books/<slug>/order_books_summary.csv.gz``. Resumable; stops between files at
               ``--stop-at`` (exit 75) and continues on the next run.
verify-staged  Re-decodes every staged file, re-applies the cutoff, checks every count and hash, and only
               then writes ``SHA256SUMS`` and ``MANIFEST.json`` (the manifest last). Prints the manifest
               sha256, which master relays to the workstation out of band.

Safety properties (each is enforced in code below)
--------------------------------------------------
* Stdlib only. Run as ``python -I -B o9_stage.py ...``. Imports nothing from ``weather``.
* Paths are constructed from the literal 552-slug allowlist; ``data\\snapshots`` is never listed and
  no folder dated 2026-09-30 or later is ever constructed, stat'ed or opened (self_check).
* Rows are dropped, and only counted, if any timestamp is at or after 2026-09-30T00:00:00Z
  (strict UTC). Unparseable rows are dropped and counted separately (fail closed).
* Sources are opened only through CreateFileW with FILE_SHARE_READ|WRITE|DELETE, read-only, never
  locked, never written, moved, renamed or deleted. The only files this tool writes or deletes are
  inside ``--out``, which must lie outside ``--repo-root``.
* Each source is read up to its stat size only; a size/mtime change or a missing final newline marks
  the file ``unstable`` (no output kept, retried on the next run, never in the same run).
* Every subcommand refuses outside the 00:30-09:00 local window. The tool takes no lease: master holds
  ``Enter-WeatherHeavyWorkloadLease`` in the parent PowerShell for stage and verify-staged.

Exit codes: 0 done, 2 refused, 3 error, 4 disk floor abort, 75 partial (stop-at, max-files, or
incomplete staging for verify-staged).
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import datetime as dt
import gzip
import hashlib
import io
import json
import msvcrt
import os
import re
import shutil
import stat
import sys
import time
import zlib
from ctypes import wintypes

# --------------------------------------------------------------------------------------------
# Fixed scope
# --------------------------------------------------------------------------------------------

SCHEMA_SOURCE = "o9_book_summary_source_manifest.v1"
SCHEMA_STATE = "o9_book_summary_file_state.v1"
SCHEMA_MANIFEST = "o9_book_summary_transfer.v1"

CUTOFF_UTC = dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc)
CUTOFF_ISO = "2026-09-30T00:00:00Z"
CUTOFF_DATE = "2026-09-30"
CUTOFF_EPOCH_MS = 1790726400000  # == CUTOFF_UTC in epoch milliseconds (self_check verifies)

SUMMARY_NAME = "order_books_summary.csv"
GZ_NAME = SUMMARY_NAME + ".gz"

MARKETS = (
    "atlanta", "austin", "chicago", "dallas", "denver", "houston",
    "los-angeles", "miami", "nyc", "san-francisco", "seattle", "toronto",
)

DATES = (
    "2026-08-15", "2026-08-16", "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20",
    "2026-08-21", "2026-08-22", "2026-08-23", "2026-08-24", "2026-08-25", "2026-08-26",
    "2026-08-27", "2026-08-28", "2026-08-29", "2026-08-30", "2026-08-31",
    "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06",
    "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12",
    "2026-09-13", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    "2026-09-19", "2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24",
    "2026-09-25", "2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29",
)

# The 552 event folders, written out literally (date-major, market order as MARKETS).
# self_check() proves this equals the MARKETS x DATES product and that every date is < 2026-09-30.
ALLOWLIST_SLUGS = (
    # 2026-08-15
    "highest-temperature-in-atlanta-on-august-15-2026",
    "highest-temperature-in-austin-on-august-15-2026",
    "highest-temperature-in-chicago-on-august-15-2026",
    "highest-temperature-in-dallas-on-august-15-2026",
    "highest-temperature-in-denver-on-august-15-2026",
    "highest-temperature-in-houston-on-august-15-2026",
    "highest-temperature-in-los-angeles-on-august-15-2026",
    "highest-temperature-in-miami-on-august-15-2026",
    "highest-temperature-in-nyc-on-august-15-2026",
    "highest-temperature-in-san-francisco-on-august-15-2026",
    "highest-temperature-in-seattle-on-august-15-2026",
    "highest-temperature-in-toronto-on-august-15-2026",
    # 2026-08-16
    "highest-temperature-in-atlanta-on-august-16-2026",
    "highest-temperature-in-austin-on-august-16-2026",
    "highest-temperature-in-chicago-on-august-16-2026",
    "highest-temperature-in-dallas-on-august-16-2026",
    "highest-temperature-in-denver-on-august-16-2026",
    "highest-temperature-in-houston-on-august-16-2026",
    "highest-temperature-in-los-angeles-on-august-16-2026",
    "highest-temperature-in-miami-on-august-16-2026",
    "highest-temperature-in-nyc-on-august-16-2026",
    "highest-temperature-in-san-francisco-on-august-16-2026",
    "highest-temperature-in-seattle-on-august-16-2026",
    "highest-temperature-in-toronto-on-august-16-2026",
    # 2026-08-17
    "highest-temperature-in-atlanta-on-august-17-2026",
    "highest-temperature-in-austin-on-august-17-2026",
    "highest-temperature-in-chicago-on-august-17-2026",
    "highest-temperature-in-dallas-on-august-17-2026",
    "highest-temperature-in-denver-on-august-17-2026",
    "highest-temperature-in-houston-on-august-17-2026",
    "highest-temperature-in-los-angeles-on-august-17-2026",
    "highest-temperature-in-miami-on-august-17-2026",
    "highest-temperature-in-nyc-on-august-17-2026",
    "highest-temperature-in-san-francisco-on-august-17-2026",
    "highest-temperature-in-seattle-on-august-17-2026",
    "highest-temperature-in-toronto-on-august-17-2026",
    # 2026-08-18
    "highest-temperature-in-atlanta-on-august-18-2026",
    "highest-temperature-in-austin-on-august-18-2026",
    "highest-temperature-in-chicago-on-august-18-2026",
    "highest-temperature-in-dallas-on-august-18-2026",
    "highest-temperature-in-denver-on-august-18-2026",
    "highest-temperature-in-houston-on-august-18-2026",
    "highest-temperature-in-los-angeles-on-august-18-2026",
    "highest-temperature-in-miami-on-august-18-2026",
    "highest-temperature-in-nyc-on-august-18-2026",
    "highest-temperature-in-san-francisco-on-august-18-2026",
    "highest-temperature-in-seattle-on-august-18-2026",
    "highest-temperature-in-toronto-on-august-18-2026",
    # 2026-08-19
    "highest-temperature-in-atlanta-on-august-19-2026",
    "highest-temperature-in-austin-on-august-19-2026",
    "highest-temperature-in-chicago-on-august-19-2026",
    "highest-temperature-in-dallas-on-august-19-2026",
    "highest-temperature-in-denver-on-august-19-2026",
    "highest-temperature-in-houston-on-august-19-2026",
    "highest-temperature-in-los-angeles-on-august-19-2026",
    "highest-temperature-in-miami-on-august-19-2026",
    "highest-temperature-in-nyc-on-august-19-2026",
    "highest-temperature-in-san-francisco-on-august-19-2026",
    "highest-temperature-in-seattle-on-august-19-2026",
    "highest-temperature-in-toronto-on-august-19-2026",
    # 2026-08-20
    "highest-temperature-in-atlanta-on-august-20-2026",
    "highest-temperature-in-austin-on-august-20-2026",
    "highest-temperature-in-chicago-on-august-20-2026",
    "highest-temperature-in-dallas-on-august-20-2026",
    "highest-temperature-in-denver-on-august-20-2026",
    "highest-temperature-in-houston-on-august-20-2026",
    "highest-temperature-in-los-angeles-on-august-20-2026",
    "highest-temperature-in-miami-on-august-20-2026",
    "highest-temperature-in-nyc-on-august-20-2026",
    "highest-temperature-in-san-francisco-on-august-20-2026",
    "highest-temperature-in-seattle-on-august-20-2026",
    "highest-temperature-in-toronto-on-august-20-2026",
    # 2026-08-21
    "highest-temperature-in-atlanta-on-august-21-2026",
    "highest-temperature-in-austin-on-august-21-2026",
    "highest-temperature-in-chicago-on-august-21-2026",
    "highest-temperature-in-dallas-on-august-21-2026",
    "highest-temperature-in-denver-on-august-21-2026",
    "highest-temperature-in-houston-on-august-21-2026",
    "highest-temperature-in-los-angeles-on-august-21-2026",
    "highest-temperature-in-miami-on-august-21-2026",
    "highest-temperature-in-nyc-on-august-21-2026",
    "highest-temperature-in-san-francisco-on-august-21-2026",
    "highest-temperature-in-seattle-on-august-21-2026",
    "highest-temperature-in-toronto-on-august-21-2026",
    # 2026-08-22
    "highest-temperature-in-atlanta-on-august-22-2026",
    "highest-temperature-in-austin-on-august-22-2026",
    "highest-temperature-in-chicago-on-august-22-2026",
    "highest-temperature-in-dallas-on-august-22-2026",
    "highest-temperature-in-denver-on-august-22-2026",
    "highest-temperature-in-houston-on-august-22-2026",
    "highest-temperature-in-los-angeles-on-august-22-2026",
    "highest-temperature-in-miami-on-august-22-2026",
    "highest-temperature-in-nyc-on-august-22-2026",
    "highest-temperature-in-san-francisco-on-august-22-2026",
    "highest-temperature-in-seattle-on-august-22-2026",
    "highest-temperature-in-toronto-on-august-22-2026",
    # 2026-08-23
    "highest-temperature-in-atlanta-on-august-23-2026",
    "highest-temperature-in-austin-on-august-23-2026",
    "highest-temperature-in-chicago-on-august-23-2026",
    "highest-temperature-in-dallas-on-august-23-2026",
    "highest-temperature-in-denver-on-august-23-2026",
    "highest-temperature-in-houston-on-august-23-2026",
    "highest-temperature-in-los-angeles-on-august-23-2026",
    "highest-temperature-in-miami-on-august-23-2026",
    "highest-temperature-in-nyc-on-august-23-2026",
    "highest-temperature-in-san-francisco-on-august-23-2026",
    "highest-temperature-in-seattle-on-august-23-2026",
    "highest-temperature-in-toronto-on-august-23-2026",
    # 2026-08-24
    "highest-temperature-in-atlanta-on-august-24-2026",
    "highest-temperature-in-austin-on-august-24-2026",
    "highest-temperature-in-chicago-on-august-24-2026",
    "highest-temperature-in-dallas-on-august-24-2026",
    "highest-temperature-in-denver-on-august-24-2026",
    "highest-temperature-in-houston-on-august-24-2026",
    "highest-temperature-in-los-angeles-on-august-24-2026",
    "highest-temperature-in-miami-on-august-24-2026",
    "highest-temperature-in-nyc-on-august-24-2026",
    "highest-temperature-in-san-francisco-on-august-24-2026",
    "highest-temperature-in-seattle-on-august-24-2026",
    "highest-temperature-in-toronto-on-august-24-2026",
    # 2026-08-25
    "highest-temperature-in-atlanta-on-august-25-2026",
    "highest-temperature-in-austin-on-august-25-2026",
    "highest-temperature-in-chicago-on-august-25-2026",
    "highest-temperature-in-dallas-on-august-25-2026",
    "highest-temperature-in-denver-on-august-25-2026",
    "highest-temperature-in-houston-on-august-25-2026",
    "highest-temperature-in-los-angeles-on-august-25-2026",
    "highest-temperature-in-miami-on-august-25-2026",
    "highest-temperature-in-nyc-on-august-25-2026",
    "highest-temperature-in-san-francisco-on-august-25-2026",
    "highest-temperature-in-seattle-on-august-25-2026",
    "highest-temperature-in-toronto-on-august-25-2026",
    # 2026-08-26
    "highest-temperature-in-atlanta-on-august-26-2026",
    "highest-temperature-in-austin-on-august-26-2026",
    "highest-temperature-in-chicago-on-august-26-2026",
    "highest-temperature-in-dallas-on-august-26-2026",
    "highest-temperature-in-denver-on-august-26-2026",
    "highest-temperature-in-houston-on-august-26-2026",
    "highest-temperature-in-los-angeles-on-august-26-2026",
    "highest-temperature-in-miami-on-august-26-2026",
    "highest-temperature-in-nyc-on-august-26-2026",
    "highest-temperature-in-san-francisco-on-august-26-2026",
    "highest-temperature-in-seattle-on-august-26-2026",
    "highest-temperature-in-toronto-on-august-26-2026",
    # 2026-08-27
    "highest-temperature-in-atlanta-on-august-27-2026",
    "highest-temperature-in-austin-on-august-27-2026",
    "highest-temperature-in-chicago-on-august-27-2026",
    "highest-temperature-in-dallas-on-august-27-2026",
    "highest-temperature-in-denver-on-august-27-2026",
    "highest-temperature-in-houston-on-august-27-2026",
    "highest-temperature-in-los-angeles-on-august-27-2026",
    "highest-temperature-in-miami-on-august-27-2026",
    "highest-temperature-in-nyc-on-august-27-2026",
    "highest-temperature-in-san-francisco-on-august-27-2026",
    "highest-temperature-in-seattle-on-august-27-2026",
    "highest-temperature-in-toronto-on-august-27-2026",
    # 2026-08-28
    "highest-temperature-in-atlanta-on-august-28-2026",
    "highest-temperature-in-austin-on-august-28-2026",
    "highest-temperature-in-chicago-on-august-28-2026",
    "highest-temperature-in-dallas-on-august-28-2026",
    "highest-temperature-in-denver-on-august-28-2026",
    "highest-temperature-in-houston-on-august-28-2026",
    "highest-temperature-in-los-angeles-on-august-28-2026",
    "highest-temperature-in-miami-on-august-28-2026",
    "highest-temperature-in-nyc-on-august-28-2026",
    "highest-temperature-in-san-francisco-on-august-28-2026",
    "highest-temperature-in-seattle-on-august-28-2026",
    "highest-temperature-in-toronto-on-august-28-2026",
    # 2026-08-29
    "highest-temperature-in-atlanta-on-august-29-2026",
    "highest-temperature-in-austin-on-august-29-2026",
    "highest-temperature-in-chicago-on-august-29-2026",
    "highest-temperature-in-dallas-on-august-29-2026",
    "highest-temperature-in-denver-on-august-29-2026",
    "highest-temperature-in-houston-on-august-29-2026",
    "highest-temperature-in-los-angeles-on-august-29-2026",
    "highest-temperature-in-miami-on-august-29-2026",
    "highest-temperature-in-nyc-on-august-29-2026",
    "highest-temperature-in-san-francisco-on-august-29-2026",
    "highest-temperature-in-seattle-on-august-29-2026",
    "highest-temperature-in-toronto-on-august-29-2026",
    # 2026-08-30
    "highest-temperature-in-atlanta-on-august-30-2026",
    "highest-temperature-in-austin-on-august-30-2026",
    "highest-temperature-in-chicago-on-august-30-2026",
    "highest-temperature-in-dallas-on-august-30-2026",
    "highest-temperature-in-denver-on-august-30-2026",
    "highest-temperature-in-houston-on-august-30-2026",
    "highest-temperature-in-los-angeles-on-august-30-2026",
    "highest-temperature-in-miami-on-august-30-2026",
    "highest-temperature-in-nyc-on-august-30-2026",
    "highest-temperature-in-san-francisco-on-august-30-2026",
    "highest-temperature-in-seattle-on-august-30-2026",
    "highest-temperature-in-toronto-on-august-30-2026",
    # 2026-08-31
    "highest-temperature-in-atlanta-on-august-31-2026",
    "highest-temperature-in-austin-on-august-31-2026",
    "highest-temperature-in-chicago-on-august-31-2026",
    "highest-temperature-in-dallas-on-august-31-2026",
    "highest-temperature-in-denver-on-august-31-2026",
    "highest-temperature-in-houston-on-august-31-2026",
    "highest-temperature-in-los-angeles-on-august-31-2026",
    "highest-temperature-in-miami-on-august-31-2026",
    "highest-temperature-in-nyc-on-august-31-2026",
    "highest-temperature-in-san-francisco-on-august-31-2026",
    "highest-temperature-in-seattle-on-august-31-2026",
    "highest-temperature-in-toronto-on-august-31-2026",
    # 2026-09-01
    "highest-temperature-in-atlanta-on-september-1-2026",
    "highest-temperature-in-austin-on-september-1-2026",
    "highest-temperature-in-chicago-on-september-1-2026",
    "highest-temperature-in-dallas-on-september-1-2026",
    "highest-temperature-in-denver-on-september-1-2026",
    "highest-temperature-in-houston-on-september-1-2026",
    "highest-temperature-in-los-angeles-on-september-1-2026",
    "highest-temperature-in-miami-on-september-1-2026",
    "highest-temperature-in-nyc-on-september-1-2026",
    "highest-temperature-in-san-francisco-on-september-1-2026",
    "highest-temperature-in-seattle-on-september-1-2026",
    "highest-temperature-in-toronto-on-september-1-2026",
    # 2026-09-02
    "highest-temperature-in-atlanta-on-september-2-2026",
    "highest-temperature-in-austin-on-september-2-2026",
    "highest-temperature-in-chicago-on-september-2-2026",
    "highest-temperature-in-dallas-on-september-2-2026",
    "highest-temperature-in-denver-on-september-2-2026",
    "highest-temperature-in-houston-on-september-2-2026",
    "highest-temperature-in-los-angeles-on-september-2-2026",
    "highest-temperature-in-miami-on-september-2-2026",
    "highest-temperature-in-nyc-on-september-2-2026",
    "highest-temperature-in-san-francisco-on-september-2-2026",
    "highest-temperature-in-seattle-on-september-2-2026",
    "highest-temperature-in-toronto-on-september-2-2026",
    # 2026-09-03
    "highest-temperature-in-atlanta-on-september-3-2026",
    "highest-temperature-in-austin-on-september-3-2026",
    "highest-temperature-in-chicago-on-september-3-2026",
    "highest-temperature-in-dallas-on-september-3-2026",
    "highest-temperature-in-denver-on-september-3-2026",
    "highest-temperature-in-houston-on-september-3-2026",
    "highest-temperature-in-los-angeles-on-september-3-2026",
    "highest-temperature-in-miami-on-september-3-2026",
    "highest-temperature-in-nyc-on-september-3-2026",
    "highest-temperature-in-san-francisco-on-september-3-2026",
    "highest-temperature-in-seattle-on-september-3-2026",
    "highest-temperature-in-toronto-on-september-3-2026",
    # 2026-09-04
    "highest-temperature-in-atlanta-on-september-4-2026",
    "highest-temperature-in-austin-on-september-4-2026",
    "highest-temperature-in-chicago-on-september-4-2026",
    "highest-temperature-in-dallas-on-september-4-2026",
    "highest-temperature-in-denver-on-september-4-2026",
    "highest-temperature-in-houston-on-september-4-2026",
    "highest-temperature-in-los-angeles-on-september-4-2026",
    "highest-temperature-in-miami-on-september-4-2026",
    "highest-temperature-in-nyc-on-september-4-2026",
    "highest-temperature-in-san-francisco-on-september-4-2026",
    "highest-temperature-in-seattle-on-september-4-2026",
    "highest-temperature-in-toronto-on-september-4-2026",
    # 2026-09-05
    "highest-temperature-in-atlanta-on-september-5-2026",
    "highest-temperature-in-austin-on-september-5-2026",
    "highest-temperature-in-chicago-on-september-5-2026",
    "highest-temperature-in-dallas-on-september-5-2026",
    "highest-temperature-in-denver-on-september-5-2026",
    "highest-temperature-in-houston-on-september-5-2026",
    "highest-temperature-in-los-angeles-on-september-5-2026",
    "highest-temperature-in-miami-on-september-5-2026",
    "highest-temperature-in-nyc-on-september-5-2026",
    "highest-temperature-in-san-francisco-on-september-5-2026",
    "highest-temperature-in-seattle-on-september-5-2026",
    "highest-temperature-in-toronto-on-september-5-2026",
    # 2026-09-06
    "highest-temperature-in-atlanta-on-september-6-2026",
    "highest-temperature-in-austin-on-september-6-2026",
    "highest-temperature-in-chicago-on-september-6-2026",
    "highest-temperature-in-dallas-on-september-6-2026",
    "highest-temperature-in-denver-on-september-6-2026",
    "highest-temperature-in-houston-on-september-6-2026",
    "highest-temperature-in-los-angeles-on-september-6-2026",
    "highest-temperature-in-miami-on-september-6-2026",
    "highest-temperature-in-nyc-on-september-6-2026",
    "highest-temperature-in-san-francisco-on-september-6-2026",
    "highest-temperature-in-seattle-on-september-6-2026",
    "highest-temperature-in-toronto-on-september-6-2026",
    # 2026-09-07
    "highest-temperature-in-atlanta-on-september-7-2026",
    "highest-temperature-in-austin-on-september-7-2026",
    "highest-temperature-in-chicago-on-september-7-2026",
    "highest-temperature-in-dallas-on-september-7-2026",
    "highest-temperature-in-denver-on-september-7-2026",
    "highest-temperature-in-houston-on-september-7-2026",
    "highest-temperature-in-los-angeles-on-september-7-2026",
    "highest-temperature-in-miami-on-september-7-2026",
    "highest-temperature-in-nyc-on-september-7-2026",
    "highest-temperature-in-san-francisco-on-september-7-2026",
    "highest-temperature-in-seattle-on-september-7-2026",
    "highest-temperature-in-toronto-on-september-7-2026",
    # 2026-09-08
    "highest-temperature-in-atlanta-on-september-8-2026",
    "highest-temperature-in-austin-on-september-8-2026",
    "highest-temperature-in-chicago-on-september-8-2026",
    "highest-temperature-in-dallas-on-september-8-2026",
    "highest-temperature-in-denver-on-september-8-2026",
    "highest-temperature-in-houston-on-september-8-2026",
    "highest-temperature-in-los-angeles-on-september-8-2026",
    "highest-temperature-in-miami-on-september-8-2026",
    "highest-temperature-in-nyc-on-september-8-2026",
    "highest-temperature-in-san-francisco-on-september-8-2026",
    "highest-temperature-in-seattle-on-september-8-2026",
    "highest-temperature-in-toronto-on-september-8-2026",
    # 2026-09-09
    "highest-temperature-in-atlanta-on-september-9-2026",
    "highest-temperature-in-austin-on-september-9-2026",
    "highest-temperature-in-chicago-on-september-9-2026",
    "highest-temperature-in-dallas-on-september-9-2026",
    "highest-temperature-in-denver-on-september-9-2026",
    "highest-temperature-in-houston-on-september-9-2026",
    "highest-temperature-in-los-angeles-on-september-9-2026",
    "highest-temperature-in-miami-on-september-9-2026",
    "highest-temperature-in-nyc-on-september-9-2026",
    "highest-temperature-in-san-francisco-on-september-9-2026",
    "highest-temperature-in-seattle-on-september-9-2026",
    "highest-temperature-in-toronto-on-september-9-2026",
    # 2026-09-10
    "highest-temperature-in-atlanta-on-september-10-2026",
    "highest-temperature-in-austin-on-september-10-2026",
    "highest-temperature-in-chicago-on-september-10-2026",
    "highest-temperature-in-dallas-on-september-10-2026",
    "highest-temperature-in-denver-on-september-10-2026",
    "highest-temperature-in-houston-on-september-10-2026",
    "highest-temperature-in-los-angeles-on-september-10-2026",
    "highest-temperature-in-miami-on-september-10-2026",
    "highest-temperature-in-nyc-on-september-10-2026",
    "highest-temperature-in-san-francisco-on-september-10-2026",
    "highest-temperature-in-seattle-on-september-10-2026",
    "highest-temperature-in-toronto-on-september-10-2026",
    # 2026-09-11
    "highest-temperature-in-atlanta-on-september-11-2026",
    "highest-temperature-in-austin-on-september-11-2026",
    "highest-temperature-in-chicago-on-september-11-2026",
    "highest-temperature-in-dallas-on-september-11-2026",
    "highest-temperature-in-denver-on-september-11-2026",
    "highest-temperature-in-houston-on-september-11-2026",
    "highest-temperature-in-los-angeles-on-september-11-2026",
    "highest-temperature-in-miami-on-september-11-2026",
    "highest-temperature-in-nyc-on-september-11-2026",
    "highest-temperature-in-san-francisco-on-september-11-2026",
    "highest-temperature-in-seattle-on-september-11-2026",
    "highest-temperature-in-toronto-on-september-11-2026",
    # 2026-09-12
    "highest-temperature-in-atlanta-on-september-12-2026",
    "highest-temperature-in-austin-on-september-12-2026",
    "highest-temperature-in-chicago-on-september-12-2026",
    "highest-temperature-in-dallas-on-september-12-2026",
    "highest-temperature-in-denver-on-september-12-2026",
    "highest-temperature-in-houston-on-september-12-2026",
    "highest-temperature-in-los-angeles-on-september-12-2026",
    "highest-temperature-in-miami-on-september-12-2026",
    "highest-temperature-in-nyc-on-september-12-2026",
    "highest-temperature-in-san-francisco-on-september-12-2026",
    "highest-temperature-in-seattle-on-september-12-2026",
    "highest-temperature-in-toronto-on-september-12-2026",
    # 2026-09-13
    "highest-temperature-in-atlanta-on-september-13-2026",
    "highest-temperature-in-austin-on-september-13-2026",
    "highest-temperature-in-chicago-on-september-13-2026",
    "highest-temperature-in-dallas-on-september-13-2026",
    "highest-temperature-in-denver-on-september-13-2026",
    "highest-temperature-in-houston-on-september-13-2026",
    "highest-temperature-in-los-angeles-on-september-13-2026",
    "highest-temperature-in-miami-on-september-13-2026",
    "highest-temperature-in-nyc-on-september-13-2026",
    "highest-temperature-in-san-francisco-on-september-13-2026",
    "highest-temperature-in-seattle-on-september-13-2026",
    "highest-temperature-in-toronto-on-september-13-2026",
    # 2026-09-14
    "highest-temperature-in-atlanta-on-september-14-2026",
    "highest-temperature-in-austin-on-september-14-2026",
    "highest-temperature-in-chicago-on-september-14-2026",
    "highest-temperature-in-dallas-on-september-14-2026",
    "highest-temperature-in-denver-on-september-14-2026",
    "highest-temperature-in-houston-on-september-14-2026",
    "highest-temperature-in-los-angeles-on-september-14-2026",
    "highest-temperature-in-miami-on-september-14-2026",
    "highest-temperature-in-nyc-on-september-14-2026",
    "highest-temperature-in-san-francisco-on-september-14-2026",
    "highest-temperature-in-seattle-on-september-14-2026",
    "highest-temperature-in-toronto-on-september-14-2026",
    # 2026-09-15
    "highest-temperature-in-atlanta-on-september-15-2026",
    "highest-temperature-in-austin-on-september-15-2026",
    "highest-temperature-in-chicago-on-september-15-2026",
    "highest-temperature-in-dallas-on-september-15-2026",
    "highest-temperature-in-denver-on-september-15-2026",
    "highest-temperature-in-houston-on-september-15-2026",
    "highest-temperature-in-los-angeles-on-september-15-2026",
    "highest-temperature-in-miami-on-september-15-2026",
    "highest-temperature-in-nyc-on-september-15-2026",
    "highest-temperature-in-san-francisco-on-september-15-2026",
    "highest-temperature-in-seattle-on-september-15-2026",
    "highest-temperature-in-toronto-on-september-15-2026",
    # 2026-09-16
    "highest-temperature-in-atlanta-on-september-16-2026",
    "highest-temperature-in-austin-on-september-16-2026",
    "highest-temperature-in-chicago-on-september-16-2026",
    "highest-temperature-in-dallas-on-september-16-2026",
    "highest-temperature-in-denver-on-september-16-2026",
    "highest-temperature-in-houston-on-september-16-2026",
    "highest-temperature-in-los-angeles-on-september-16-2026",
    "highest-temperature-in-miami-on-september-16-2026",
    "highest-temperature-in-nyc-on-september-16-2026",
    "highest-temperature-in-san-francisco-on-september-16-2026",
    "highest-temperature-in-seattle-on-september-16-2026",
    "highest-temperature-in-toronto-on-september-16-2026",
    # 2026-09-17
    "highest-temperature-in-atlanta-on-september-17-2026",
    "highest-temperature-in-austin-on-september-17-2026",
    "highest-temperature-in-chicago-on-september-17-2026",
    "highest-temperature-in-dallas-on-september-17-2026",
    "highest-temperature-in-denver-on-september-17-2026",
    "highest-temperature-in-houston-on-september-17-2026",
    "highest-temperature-in-los-angeles-on-september-17-2026",
    "highest-temperature-in-miami-on-september-17-2026",
    "highest-temperature-in-nyc-on-september-17-2026",
    "highest-temperature-in-san-francisco-on-september-17-2026",
    "highest-temperature-in-seattle-on-september-17-2026",
    "highest-temperature-in-toronto-on-september-17-2026",
    # 2026-09-18
    "highest-temperature-in-atlanta-on-september-18-2026",
    "highest-temperature-in-austin-on-september-18-2026",
    "highest-temperature-in-chicago-on-september-18-2026",
    "highest-temperature-in-dallas-on-september-18-2026",
    "highest-temperature-in-denver-on-september-18-2026",
    "highest-temperature-in-houston-on-september-18-2026",
    "highest-temperature-in-los-angeles-on-september-18-2026",
    "highest-temperature-in-miami-on-september-18-2026",
    "highest-temperature-in-nyc-on-september-18-2026",
    "highest-temperature-in-san-francisco-on-september-18-2026",
    "highest-temperature-in-seattle-on-september-18-2026",
    "highest-temperature-in-toronto-on-september-18-2026",
    # 2026-09-19
    "highest-temperature-in-atlanta-on-september-19-2026",
    "highest-temperature-in-austin-on-september-19-2026",
    "highest-temperature-in-chicago-on-september-19-2026",
    "highest-temperature-in-dallas-on-september-19-2026",
    "highest-temperature-in-denver-on-september-19-2026",
    "highest-temperature-in-houston-on-september-19-2026",
    "highest-temperature-in-los-angeles-on-september-19-2026",
    "highest-temperature-in-miami-on-september-19-2026",
    "highest-temperature-in-nyc-on-september-19-2026",
    "highest-temperature-in-san-francisco-on-september-19-2026",
    "highest-temperature-in-seattle-on-september-19-2026",
    "highest-temperature-in-toronto-on-september-19-2026",
    # 2026-09-20
    "highest-temperature-in-atlanta-on-september-20-2026",
    "highest-temperature-in-austin-on-september-20-2026",
    "highest-temperature-in-chicago-on-september-20-2026",
    "highest-temperature-in-dallas-on-september-20-2026",
    "highest-temperature-in-denver-on-september-20-2026",
    "highest-temperature-in-houston-on-september-20-2026",
    "highest-temperature-in-los-angeles-on-september-20-2026",
    "highest-temperature-in-miami-on-september-20-2026",
    "highest-temperature-in-nyc-on-september-20-2026",
    "highest-temperature-in-san-francisco-on-september-20-2026",
    "highest-temperature-in-seattle-on-september-20-2026",
    "highest-temperature-in-toronto-on-september-20-2026",
    # 2026-09-21
    "highest-temperature-in-atlanta-on-september-21-2026",
    "highest-temperature-in-austin-on-september-21-2026",
    "highest-temperature-in-chicago-on-september-21-2026",
    "highest-temperature-in-dallas-on-september-21-2026",
    "highest-temperature-in-denver-on-september-21-2026",
    "highest-temperature-in-houston-on-september-21-2026",
    "highest-temperature-in-los-angeles-on-september-21-2026",
    "highest-temperature-in-miami-on-september-21-2026",
    "highest-temperature-in-nyc-on-september-21-2026",
    "highest-temperature-in-san-francisco-on-september-21-2026",
    "highest-temperature-in-seattle-on-september-21-2026",
    "highest-temperature-in-toronto-on-september-21-2026",
    # 2026-09-22
    "highest-temperature-in-atlanta-on-september-22-2026",
    "highest-temperature-in-austin-on-september-22-2026",
    "highest-temperature-in-chicago-on-september-22-2026",
    "highest-temperature-in-dallas-on-september-22-2026",
    "highest-temperature-in-denver-on-september-22-2026",
    "highest-temperature-in-houston-on-september-22-2026",
    "highest-temperature-in-los-angeles-on-september-22-2026",
    "highest-temperature-in-miami-on-september-22-2026",
    "highest-temperature-in-nyc-on-september-22-2026",
    "highest-temperature-in-san-francisco-on-september-22-2026",
    "highest-temperature-in-seattle-on-september-22-2026",
    "highest-temperature-in-toronto-on-september-22-2026",
    # 2026-09-23
    "highest-temperature-in-atlanta-on-september-23-2026",
    "highest-temperature-in-austin-on-september-23-2026",
    "highest-temperature-in-chicago-on-september-23-2026",
    "highest-temperature-in-dallas-on-september-23-2026",
    "highest-temperature-in-denver-on-september-23-2026",
    "highest-temperature-in-houston-on-september-23-2026",
    "highest-temperature-in-los-angeles-on-september-23-2026",
    "highest-temperature-in-miami-on-september-23-2026",
    "highest-temperature-in-nyc-on-september-23-2026",
    "highest-temperature-in-san-francisco-on-september-23-2026",
    "highest-temperature-in-seattle-on-september-23-2026",
    "highest-temperature-in-toronto-on-september-23-2026",
    # 2026-09-24
    "highest-temperature-in-atlanta-on-september-24-2026",
    "highest-temperature-in-austin-on-september-24-2026",
    "highest-temperature-in-chicago-on-september-24-2026",
    "highest-temperature-in-dallas-on-september-24-2026",
    "highest-temperature-in-denver-on-september-24-2026",
    "highest-temperature-in-houston-on-september-24-2026",
    "highest-temperature-in-los-angeles-on-september-24-2026",
    "highest-temperature-in-miami-on-september-24-2026",
    "highest-temperature-in-nyc-on-september-24-2026",
    "highest-temperature-in-san-francisco-on-september-24-2026",
    "highest-temperature-in-seattle-on-september-24-2026",
    "highest-temperature-in-toronto-on-september-24-2026",
    # 2026-09-25
    "highest-temperature-in-atlanta-on-september-25-2026",
    "highest-temperature-in-austin-on-september-25-2026",
    "highest-temperature-in-chicago-on-september-25-2026",
    "highest-temperature-in-dallas-on-september-25-2026",
    "highest-temperature-in-denver-on-september-25-2026",
    "highest-temperature-in-houston-on-september-25-2026",
    "highest-temperature-in-los-angeles-on-september-25-2026",
    "highest-temperature-in-miami-on-september-25-2026",
    "highest-temperature-in-nyc-on-september-25-2026",
    "highest-temperature-in-san-francisco-on-september-25-2026",
    "highest-temperature-in-seattle-on-september-25-2026",
    "highest-temperature-in-toronto-on-september-25-2026",
    # 2026-09-26
    "highest-temperature-in-atlanta-on-september-26-2026",
    "highest-temperature-in-austin-on-september-26-2026",
    "highest-temperature-in-chicago-on-september-26-2026",
    "highest-temperature-in-dallas-on-september-26-2026",
    "highest-temperature-in-denver-on-september-26-2026",
    "highest-temperature-in-houston-on-september-26-2026",
    "highest-temperature-in-los-angeles-on-september-26-2026",
    "highest-temperature-in-miami-on-september-26-2026",
    "highest-temperature-in-nyc-on-september-26-2026",
    "highest-temperature-in-san-francisco-on-september-26-2026",
    "highest-temperature-in-seattle-on-september-26-2026",
    "highest-temperature-in-toronto-on-september-26-2026",
    # 2026-09-27
    "highest-temperature-in-atlanta-on-september-27-2026",
    "highest-temperature-in-austin-on-september-27-2026",
    "highest-temperature-in-chicago-on-september-27-2026",
    "highest-temperature-in-dallas-on-september-27-2026",
    "highest-temperature-in-denver-on-september-27-2026",
    "highest-temperature-in-houston-on-september-27-2026",
    "highest-temperature-in-los-angeles-on-september-27-2026",
    "highest-temperature-in-miami-on-september-27-2026",
    "highest-temperature-in-nyc-on-september-27-2026",
    "highest-temperature-in-san-francisco-on-september-27-2026",
    "highest-temperature-in-seattle-on-september-27-2026",
    "highest-temperature-in-toronto-on-september-27-2026",
    # 2026-09-28
    "highest-temperature-in-atlanta-on-september-28-2026",
    "highest-temperature-in-austin-on-september-28-2026",
    "highest-temperature-in-chicago-on-september-28-2026",
    "highest-temperature-in-dallas-on-september-28-2026",
    "highest-temperature-in-denver-on-september-28-2026",
    "highest-temperature-in-houston-on-september-28-2026",
    "highest-temperature-in-los-angeles-on-september-28-2026",
    "highest-temperature-in-miami-on-september-28-2026",
    "highest-temperature-in-nyc-on-september-28-2026",
    "highest-temperature-in-san-francisco-on-september-28-2026",
    "highest-temperature-in-seattle-on-september-28-2026",
    "highest-temperature-in-toronto-on-september-28-2026",
    # 2026-09-29
    "highest-temperature-in-atlanta-on-september-29-2026",
    "highest-temperature-in-austin-on-september-29-2026",
    "highest-temperature-in-chicago-on-september-29-2026",
    "highest-temperature-in-dallas-on-september-29-2026",
    "highest-temperature-in-denver-on-september-29-2026",
    "highest-temperature-in-houston-on-september-29-2026",
    "highest-temperature-in-los-angeles-on-september-29-2026",
    "highest-temperature-in-miami-on-september-29-2026",
    "highest-temperature-in-nyc-on-september-29-2026",
    "highest-temperature-in-san-francisco-on-september-29-2026",
    "highest-temperature-in-seattle-on-september-29-2026",
    "highest-temperature-in-toronto-on-september-29-2026",
)

MONTHS = {"august": 8, "september": 9}
SLUG_RE = re.compile(
    r"^highest-temperature-in-(" + "|".join(re.escape(m) for m in MARKETS) + r")"
    r"-on-(august|september)-(\d{1,2})-(2026)$"
)
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$")
EPOCH_MS_RE = re.compile(r"^\d{1,16}$")
REQUIRED_COLUMNS = ("captured_at_utc", "captured_at_local", "event_slug", "book_time_utc", "book_timestamp")

# Host resource gates (HOST_LOAD_POLICY: 20 GiB capture reserve, >= 4 GiB available RAM, commit < 70%).
GIB = 1024 ** 3
CAPTURE_RESERVE_BYTES = 20 * GIB
DISK_MARGIN_BYTES = 1 * GIB
DISK_RECHECK_BYTES = 64 * 1024 ** 2
MIN_AVAILABLE_PHYS_BYTES = 4 * GIB
MAX_COMMIT_FRACTION = 0.70
EXPECTED_GZIP_RATIO = 13.9           # measured on the 79a book sample (4,754,771,146 / 341,690,746)
PRIOR_RATE_BYTES_PER_SECOND = 10 * 1024 ** 2   # conservative until 5 files have been measured
PROJECTION_SAFETY = 1.5
WINDOW_START_MINUTE = 30             # 00:30 local
WINDOW_END_MINUTE = 9 * 60           # 09:00 local
READ_CHUNK = 1024 * 1024

EXIT_OK, EXIT_REFUSED, EXIT_ERROR, EXIT_DISK, EXIT_PARTIAL = 0, 2, 3, 4, 75


class Refusal(Exception):
    """The run (or one file) is refused; ``code`` names why."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Unstable(Exception):
    """The source changed or ended unexpectedly while it was read."""


class DiskFloor(Exception):
    """Free space fell below the capture reserve plus margin."""


# --------------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------------

def emit(obj):
    print(json.dumps(obj, sort_keys=True), flush=True)


def utc_now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def fmt_utc(value):
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ns_to_utc_iso(ns):
    return fmt_utc(dt.datetime.fromtimestamp(ns / 1e9, tz=dt.timezone.utc))


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_own_file(path):
    with open(path, "rb") as handle:  # our own file or our own staging output, never a source
        return hashlib.sha256(handle.read()).hexdigest()


def write_json_atomic(path, payload):
    data = (json.dumps(payload, sort_keys=True, indent=1) + "\n").encode("utf-8")
    tmp = path + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return sha256_bytes(data)


def read_json_own(path):
    with open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def slug_date(slug):
    match = SLUG_RE.match(slug)
    if not match:
        raise Refusal("name_not_allowlisted:" + slug)
    month = MONTHS[match.group(2)]
    day = int(match.group(3))
    return dt.date(int(match.group(4)), month, day).isoformat()


def slug_market(slug):
    return SLUG_RE.match(slug).group(1)


def allowlist_sha256():
    return sha256_bytes(("\n".join(ALLOWLIST_SLUGS) + "\n").encode("ascii"))


def self_check():
    """Prove the literal scope before anything is touched. Raises Refusal on any doubt."""
    if len(MARKETS) != 12 or len(set(MARKETS)) != 12:
        raise Refusal("self_check_markets")
    if len(DATES) != 46 or DATES[0] != "2026-08-15" or DATES[-1] != "2026-09-29":
        raise Refusal("self_check_dates_bounds")
    for previous, current in zip(DATES, DATES[1:]):
        if dt.date.fromisoformat(current) - dt.date.fromisoformat(previous) != dt.timedelta(days=1):
            raise Refusal("self_check_dates_not_consecutive")
    if any(day >= CUTOFF_DATE for day in DATES):
        raise Refusal("self_check_date_at_or_after_cutoff")
    expected = tuple(
        f"highest-temperature-in-{market}-on-{_month_name(day)}-{int(day[8:])}-2026"
        for day in DATES for market in MARKETS
    )
    if len(ALLOWLIST_SLUGS) != 552 or ALLOWLIST_SLUGS != expected:
        raise Refusal("self_check_allowlist_literal_mismatch")
    for slug in ALLOWLIST_SLUGS:
        day = slug_date(slug)
        if day not in DATES or day >= CUTOFF_DATE:
            raise Refusal("self_check_slug_date:" + slug)
    if int(CUTOFF_UTC.timestamp() * 1000) != CUTOFF_EPOCH_MS:
        raise Refusal("self_check_cutoff_epoch")
    return allowlist_sha256()


def _month_name(day):
    return {8: "august", 9: "september"}[int(day[5:7])]


def source_relpath(slug, name):
    return "data/snapshots/" + slug + "/" + name


def source_abspath(repo_root, slug, name):
    if slug_date(slug) >= CUTOFF_DATE:  # unreachable after self_check; kept as a second fence
        raise Refusal("name_date_refused:" + slug)
    return os.path.join(repo_root, "data", "snapshots", slug, name)


def check_window(now=None):
    now = now or dt.datetime.now()
    minute = now.hour * 60 + now.minute
    if not (WINDOW_START_MINUTE <= minute < WINDOW_END_MINUTE):
        raise Refusal("outside_00:30-09:00_window")


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


_K32 = ctypes.WinDLL("kernel32", use_last_error=True)


def memory_sample():
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not _K32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise Refusal("memory_status_unavailable")
    commit = 1.0 - (status.ullAvailPageFile / status.ullTotalPageFile)
    return {"available_phys_bytes": int(status.ullAvailPhys), "commit_fraction": round(commit, 4)}


def check_memory():
    sample = memory_sample()
    if sample["available_phys_bytes"] < MIN_AVAILABLE_PHYS_BYTES:
        raise Refusal("available_ram_below_4_gib")
    if sample["commit_fraction"] >= MAX_COMMIT_FRACTION:
        raise Refusal("commit_at_or_above_70_percent")
    return sample


def set_below_normal_priority():
    below_normal = 0x00004000
    _K32.GetCurrentProcess.restype = wintypes.HANDLE
    _K32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    if not _K32.SetPriorityClass(_K32.GetCurrentProcess(), below_normal):
        raise Refusal("cannot_set_below_normal_priority")


def free_bytes(path):
    return shutil.disk_usage(path).free


# --------------------------------------------------------------------------------------------
# Shared-mode, read-only source access
# --------------------------------------------------------------------------------------------

_GENERIC_READ = 0x80000000
_FILE_SHARE_ALL = 0x1 | 0x2 | 0x4   # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
_OPEN_EXISTING = 3
_FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_K32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
_K32.CreateFileW.restype = wintypes.HANDLE
_K32.CloseHandle.argtypes = [wintypes.HANDLE]


def open_shared_read(path):
    """Return a read-only CRT fd for ``path`` that never denies other readers, writers or deleters."""
    handle = _K32.CreateFileW(
        path, _GENERIC_READ, _FILE_SHARE_ALL, None, _OPEN_EXISTING, _FILE_FLAG_SEQUENTIAL_SCAN, None
    )
    if handle is None or handle == _INVALID_HANDLE:
        raise OSError(ctypes.get_last_error(), "CreateFileW(shared read) failed", path)
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        _K32.CloseHandle(handle)
        raise


class BoundedHashingReader(io.RawIOBase):
    """Reads at most ``limit`` bytes from ``fd`` and hashes them; a short read means the file shrank."""

    def __init__(self, fd, limit):
        super().__init__()
        self._fd = fd
        self._remaining = limit
        self.sha = hashlib.sha256()
        self.bytes_read = 0

    def readable(self):
        return True

    def readinto(self, buffer):
        if self._remaining <= 0:
            return 0
        want = min(len(buffer), self._remaining, READ_CHUNK)
        data = os.read(self._fd, want)
        if not data:
            raise Unstable("short_read")
        buffer[:len(data)] = data
        self.sha.update(data)
        self._remaining -= len(data)
        self.bytes_read += len(data)
        return len(data)

    def close(self):  # the fd is owned and closed by the caller
        super().close()


class HashingWriter(io.RawIOBase):
    """Write-through wrapper that hashes and counts the stored (gzip) bytes."""

    def __init__(self, handle):
        super().__init__()
        self._handle = handle
        self.sha = hashlib.sha256()
        self.bytes_written = 0

    def writable(self):
        return True

    def write(self, data):
        data = bytes(data)
        self._handle.write(data)
        self.sha.update(data)
        self.bytes_written += len(data)
        return len(data)

    def close(self):  # the underlying handle is closed by the caller
        super().close()


# --------------------------------------------------------------------------------------------
# Row rules (identical in verify_o9.py; any change must be made in both)
# --------------------------------------------------------------------------------------------

def parse_iso(text):
    if not ISO_RE.match(text):
        return None
    try:
        value = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else None


def parse_header(line):
    raw = line[3:] if line.startswith(b"\xef\xbb\xbf") else line
    text = raw.decode("latin-1").rstrip("\r\n")
    try:
        names = next(csv.reader([text], strict=True))
    except (csv.Error, StopIteration):
        raise Refusal("header_unparseable")
    index = {}
    for column in REQUIRED_COLUMNS:
        if names.count(column) != 1:
            raise Refusal("header_missing_or_duplicate:" + column)
        index[column] = names.index(column)
    return len(names), index


# classify_row returns (kind, captured_at_utc, book_time_utc); kind is keep | ge_cutoff | unparseable |
# slug_mismatch. Values of a ge_cutoff row are never returned or recorded: callers only count it.
def classify_row(line, ncols, index, folder_slug):
    text = line.decode("latin-1").rstrip("\r\n")
    try:
        fields = next(csv.reader([text], strict=True))
    except (csv.Error, StopIteration):
        return "unparseable", None, None
    if len(fields) != ncols:
        return "unparseable", None, None
    if fields[index["event_slug"]] != folder_slug:
        return "slug_mismatch", None, None

    unparseable = False
    after = False

    captured = parse_iso(fields[index["captured_at_utc"]])
    if captured is None:
        unparseable = True
    elif captured >= CUTOFF_UTC:
        after = True

    local_text = fields[index["captured_at_local"]]
    local = parse_iso(local_text)
    if local is None:
        unparseable = True
    elif local >= CUTOFF_UTC or local_text[:10] >= CUTOFF_DATE:
        after = True

    book_text = fields[index["book_time_utc"]]
    book = None
    if book_text:
        book = parse_iso(book_text)
        if book is None:
            unparseable = True
        elif book >= CUTOFF_UTC:
            after = True

    stamp_text = fields[index["book_timestamp"]]
    if stamp_text:
        if not EPOCH_MS_RE.match(stamp_text):
            unparseable = True
        elif int(stamp_text) >= CUTOFF_EPOCH_MS:
            after = True

    if after:
        return "ge_cutoff", None, None
    if unparseable:
        return "unparseable", None, None
    return "keep", captured, book


class RowStats:
    def __init__(self):
        self.rows_total = 0
        self.rows_kept = 0
        self.rows_dropped_ge_cutoff = 0
        self.rows_dropped_unparseable = 0
        self.kept_min = None
        self.kept_max = None
        self.book_max = None

    def keep(self, captured, book):
        self.rows_kept += 1
        if self.kept_min is None or captured < self.kept_min:
            self.kept_min = captured
        if self.kept_max is None or captured > self.kept_max:
            self.kept_max = captured
        if book is not None and (self.book_max is None or book > self.book_max):
            self.book_max = book

    def as_dict(self):
        return {
            "rows_total": self.rows_total,
            "rows_kept": self.rows_kept,
            "rows_dropped_ge_cutoff": self.rows_dropped_ge_cutoff,
            "rows_dropped_unparseable": self.rows_dropped_unparseable,
            "kept_captured_at_utc_min": fmt_utc(self.kept_min) if self.kept_min else None,
            "kept_captured_at_utc_max": fmt_utc(self.kept_max) if self.kept_max else None,
            "kept_book_time_utc_max": fmt_utc(self.book_max) if self.book_max else None,
        }


def filter_lines(lines, folder_slug, sink, on_bytes):
    """Copy the header and every kept row (original bytes) to ``sink``; count the rest.

    ``sink(bytes)`` receives kept bytes; ``on_bytes(n)`` is called with every line's length.
    Returns (header_sha256, RowStats).
    """
    iterator = iter(lines)
    header = next(iterator, None)
    if header is None:
        raise Refusal("empty_file")
    if not header.endswith(b"\n"):
        raise Unstable("no_trailing_newline")
    ncols, index = parse_header(header)
    sink(header)
    on_bytes(len(header))
    stats = RowStats()
    for line in iterator:
        on_bytes(len(line))
        if not line.endswith(b"\n"):
            raise Unstable("no_trailing_newline")
        stats.rows_total += 1
        kind, captured, book = classify_row(line, ncols, index, folder_slug)
        if kind == "keep":
            sink(line)
            stats.keep(captured, book)
        elif kind == "ge_cutoff":
            stats.rows_dropped_ge_cutoff += 1
        elif kind == "unparseable":
            stats.rows_dropped_unparseable += 1
        else:
            raise Refusal("event_slug_mismatch")
    return sha256_bytes(header), stats


# --------------------------------------------------------------------------------------------
# Stat-only source listing (preflight and SOURCE-MANIFEST)
# --------------------------------------------------------------------------------------------

def stat_sources(repo_root, probe_gz):
    """One stat per folder for the .csv; with ``probe_gz`` one more for the .csv.gz only when the .csv is absent."""
    entries = []
    stat_calls = 0
    for slug in ALLOWLIST_SLUGS:
        entry = {"slug": slug, "market": slug_market(slug), "target_date": slug_date(slug)}
        found = None
        candidates = (("csv", SUMMARY_NAME), ("csv.gz", GZ_NAME)) if probe_gz else (("csv", SUMMARY_NAME),)
        for variant, name in candidates:
            stat_calls += 1
            try:
                info = os.stat(source_abspath(repo_root, slug, name), follow_symlinks=False)
            except (FileNotFoundError, NotADirectoryError):
                continue
            except OSError as exc:
                found = {"status": "error:stat_" + str(exc.errno), "variant": variant}
                break
            if not stat.S_ISREG(info.st_mode) or (getattr(info, "st_file_attributes", 0) & 0x400):
                found = {"status": "refused:not_regular_file", "variant": variant}
                break
            found = {
                "status": "present",
                "variant": variant,
                "relpath": source_relpath(slug, name),
                "bytes": info.st_size,
                "mtime_ns": info.st_mtime_ns,
                "mtime_utc": ns_to_utc_iso(info.st_mtime_ns),
            }
            break
        entry.update(found or {"status": "missing"})
        entries.append(entry)
    return entries, stat_calls


def source_totals(entries, stat_calls):
    present = [e for e in entries if e["status"] == "present"]
    total = sum(e["bytes"] for e in present)
    return {
        "expected": len(ALLOWLIST_SLUGS),
        "present": len(present),
        "present_csv": sum(1 for e in present if e["variant"] == "csv"),
        "present_csv_gz": sum(1 for e in present if e["variant"] == "csv.gz"),
        "missing": sum(1 for e in entries if e["status"] == "missing"),
        "other": sum(1 for e in entries if e["status"] not in ("present", "missing")),
        "source_bytes_total": total,
        "projected_gzip_bytes": int(total / EXPECTED_GZIP_RATIO),
        "stat_calls": stat_calls,
    }


# --------------------------------------------------------------------------------------------
# Common argument checks
# --------------------------------------------------------------------------------------------

def resolve_roots(repo_root, out_dir):
    # abspath, not realpath: realpath opens a handle on Windows; this only joins strings.
    repo = os.path.abspath(repo_root)
    if not os.path.isdir(os.path.join(repo, "data", "snapshots")):  # one stat of the directory
        raise Refusal("repo_root_has_no_data_snapshots")
    if out_dir is None:
        return repo, None
    out = os.path.abspath(out_dir)
    repo_cmp = os.path.normcase(repo).rstrip("\\/") + os.sep
    out_cmp = os.path.normcase(out).rstrip("\\/") + os.sep
    if out_cmp.startswith(repo_cmp) or repo_cmp.startswith(out_cmp):
        raise Refusal("out_dir_overlaps_repo_root")
    return repo, out


def parse_stop_at(text):
    match = re.fullmatch(r"(\d{2}):(\d{2})", text)
    if not match:
        raise Refusal("stop_at_format_HH:MM")
    hour, minute = int(match.group(1)), int(match.group(2))
    total = hour * 60 + minute
    if not (WINDOW_START_MINUTE < total <= WINDOW_END_MINUTE) or minute > 59:
        raise Refusal("stop_at_outside_00:31-09:00")
    now = dt.datetime.now()
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


# --------------------------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------------------------

def cmd_preflight(args):
    allow_sha = self_check()
    check_window()
    repo, _ = resolve_roots(args.repo_root, None)
    entries, stat_calls = stat_sources(repo, probe_gz=args.probe_gz)
    for entry in entries:
        emit({k: entry.get(k) for k in ("slug", "target_date", "market", "status", "variant", "bytes", "mtime_utc")})
    totals = source_totals(entries, stat_calls)
    totals.update({"kind": "preflight_totals", "gz_twins_probed": args.probe_gz,
                   "allowlist_sha256": allow_sha, "repo_root": repo,
                   "at_utc": utc_now_iso(), "cutoff_utc": CUTOFF_ISO})
    emit(totals)
    return EXIT_OK


# --------------------------------------------------------------------------------------------
# stage
# --------------------------------------------------------------------------------------------

def out_paths(out):
    return {
        "source_manifest": os.path.join(out, "SOURCE-MANIFEST.json"),
        "receipts": os.path.join(out, "RUN-RECEIPTS.jsonl"),
        "state": os.path.join(out, "state"),
        "books": os.path.join(out, "books"),
        "sums": os.path.join(out, "SHA256SUMS"),
        "manifest": os.path.join(out, "MANIFEST.json"),
    }


def staged_relpath(slug):
    return "books/" + slug + "/" + GZ_NAME


def load_or_create_source_manifest(repo, out, allow_sha, script_sha):
    paths = out_paths(out)
    if os.path.exists(paths["source_manifest"]):
        doc = read_json_own(paths["source_manifest"])
        if (doc.get("schema") != SCHEMA_SOURCE or doc.get("allowlist_sha256") != allow_sha
                or os.path.normcase(doc.get("repo_root", "")) != os.path.normcase(repo)
                or doc.get("script_sha256") != script_sha
                or [e["slug"] for e in doc.get("entries", [])] != list(ALLOWLIST_SLUGS)):
            raise Refusal("source_manifest_mismatch_start_a_fresh_out_dir")
        return doc, False
    if os.path.isdir(out) and os.listdir(out):
        raise Refusal("out_dir_not_empty_and_has_no_source_manifest")
    os.makedirs(paths["state"], exist_ok=True)
    os.makedirs(paths["books"], exist_ok=True)
    entries, stat_calls = stat_sources(repo, probe_gz=True)  # stage always takes the .csv.gz twin
    doc = {
        "schema": SCHEMA_SOURCE,
        "created_utc": utc_now_iso(),
        "host": os.environ.get("COMPUTERNAME", ""),
        "repo_root": repo,
        "script_sha256": script_sha,
        "allowlist_sha256": allow_sha,
        "dates": list(DATES),
        "markets": list(MARKETS),
        "cutoff_utc": CUTOFF_ISO,
        "cutoff_epoch_ms": CUTOFF_EPOCH_MS,
        "totals": source_totals(entries, stat_calls),
        "entries": entries,
    }
    # Written before any source file is opened or copied.
    write_json_atomic(paths["source_manifest"], doc)
    return doc, True


def state_path(out, slug):
    return os.path.join(out_paths(out)["state"], slug + ".json")


def load_state(out, slug):
    path = state_path(out, slug)
    return read_json_own(path) if os.path.exists(path) else None


def staged_file_matches(out, record):
    path = os.path.join(out, *record["staged_relpath"].split("/"))
    if not os.path.isfile(path) or os.path.getsize(path) != record["staged_bytes"]:
        return False
    return sha256_own_file(path) == record["staged_sha256"]


def stage_one(repo, out, entry):
    """Filter one source into the staging dir. Returns the state record (never raises Unstable/Refusal)."""
    slug = entry["slug"]
    record = {
        "schema": SCHEMA_STATE, "slug": slug, "market": entry["market"], "target_date": entry["target_date"],
        "source_variant": entry["variant"], "source_relpath": entry["relpath"],
        "source_bytes": entry["bytes"], "source_mtime_ns": entry["mtime_ns"], "source_mtime_utc": entry["mtime_utc"],
        "started_utc": utc_now_iso(),
    }
    source = os.path.join(repo, *entry["relpath"].split("/"))
    if slug_date(slug) >= CUTOFF_DATE:
        raise Refusal("name_date_refused:" + slug)
    dest_dir = os.path.join(out, "books", slug)
    final = os.path.join(dest_dir, GZ_NAME)
    partial = final + ".partial"
    os.makedirs(dest_dir, exist_ok=True)
    started = time.monotonic()
    floor = CAPTURE_RESERVE_BYTES + DISK_MARGIN_BYTES
    progress = {"next": DISK_RECHECK_BYTES, "seen": 0}

    def on_bytes(count):
        progress["seen"] += count
        if progress["seen"] >= progress["next"]:
            progress["next"] += DISK_RECHECK_BYTES
            if free_bytes(out) < floor:
                raise DiskFloor()

    fd = None
    try:
        before = os.stat(source, follow_symlinks=False)
        if (before.st_size, before.st_mtime_ns) != (entry["bytes"], entry["mtime_ns"]):
            raise Unstable("stat_changed_since_source_manifest")
        fd = open_shared_read(source)
        raw = BoundedHashingReader(fd, before.st_size)
        buffered = io.BufferedReader(raw, buffer_size=READ_CHUNK)
        decoded_sha = hashlib.sha256()
        decoded_bytes = [0]
        source_decoded_sha = hashlib.sha256() if entry["variant"] == "csv.gz" else None
        with open(partial, "wb") as handle:
            writer = HashingWriter(handle)
            with gzip.GzipFile(filename="", mode="wb", compresslevel=6, fileobj=writer, mtime=0) as gz_out:
                def sink(data):
                    gz_out.write(data)
                    decoded_sha.update(data)
                    decoded_bytes[0] += len(data)

                if source_decoded_sha is not None:
                    gz_in = gzip.GzipFile(fileobj=buffered, mode="rb")

                    def decoded_lines():
                        for line in gz_in:
                            source_decoded_sha.update(line)
                            yield line

                    header_sha, stats = filter_lines(decoded_lines(), slug, sink, on_bytes)
                else:
                    header_sha, stats = filter_lines(buffered, slug, sink, on_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        # Whole stat size consumed, nothing beyond it, and size/mtime unchanged.
        while buffered.read(READ_CHUNK):
            pass
        if raw.bytes_read != before.st_size or os.read(fd, 1):
            raise Unstable("size_changed_during_read")
        after = os.fstat(fd)
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise Unstable("stat_changed_during_read")
        os.close(fd)
        fd = None
        os.replace(partial, final)
        source_sha = raw.sha.hexdigest()
        identity = source_decoded_sha.hexdigest() if source_decoded_sha is not None else source_sha
        dropped = stats.rows_dropped_ge_cutoff + stats.rows_dropped_unparseable
        record.update(stats.as_dict())
        record.update({
            "status": "staged",
            "source_sha256": source_sha,
            "source_decoded_sha256": source_decoded_sha.hexdigest() if source_decoded_sha is not None else None,
            "header_sha256": header_sha,
            "staged_relpath": staged_relpath(slug),
            "staged_bytes": writer.bytes_written,
            "staged_sha256": writer.sha.hexdigest(),
            "decoded_bytes": decoded_bytes[0],
            "decoded_sha256": decoded_sha.hexdigest(),
            "byte_identical_to_source": dropped == 0 and decoded_sha.hexdigest() == identity,
        })
    except Unstable as exc:
        record.update({"status": "unstable", "detail": str(exc)})
    except Refusal as exc:
        record.update({"status": "refused:" + exc.code})
    except (EOFError, gzip.BadGzipFile, zlib.error):
        record.update({"status": "refused:gzip_corrupt"})
    except OSError as exc:  # e.g. source vanished between stat and open; retried on the next run
        record.update({"status": "error:os_" + str(exc.errno), "detail": str(exc)[:200]})
    finally:
        if fd is not None:
            os.close(fd)
        if record.get("status") != "staged" and os.path.exists(partial):
            os.remove(partial)  # our own partial output only
    record["seconds"] = round(time.monotonic() - started, 3)
    if record["status"] != "staged" and os.path.exists(final):
        os.remove(final)  # a stale staged copy from an earlier attempt must not survive a failed retry
    return record


def append_receipt(out, receipt):
    with open(out_paths(out)["receipts"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")


def cmd_stage(args):
    allow_sha = self_check()
    check_window()
    deadline = parse_stop_at(args.stop_at)
    repo, out = resolve_roots(args.repo_root, args.out)
    script_sha = sha256_own_file(os.path.abspath(__file__))
    set_below_normal_priority()
    run_started = time.monotonic()
    receipt = {"kind": "stage", "started_utc": utc_now_iso(), "pid": os.getpid(), "script_sha256": script_sha,
               "stop_at": args.stop_at, "max_files": args.max_files,
               "max_runtime_minutes": args.max_runtime_minutes}
    os.makedirs(out, exist_ok=True)
    try:
        receipt["memory_start"] = check_memory()
        doc, created = load_or_create_source_manifest(repo, out, allow_sha, script_sha)
        receipt["source_manifest_created"] = created
        pending = []
        for entry in doc["entries"]:
            if entry["status"] != "present":
                continue
            state = load_state(out, entry["slug"])
            if state and state["status"] == "staged" and staged_file_matches(out, state):
                continue
            if state and state["status"].startswith("refused:"):
                continue
            pending.append(entry)
        remaining_bytes = sum(e["bytes"] for e in pending)
        need = CAPTURE_RESERVE_BYTES + DISK_MARGIN_BYTES + 2 * int(remaining_bytes / EXPECTED_GZIP_RATIO)
        receipt["free_bytes_start"] = free_bytes(out)
        if receipt["free_bytes_start"] < need:
            raise DiskFloor()
        processed, staged_now, read_bytes, busy_seconds = 0, 0, 0, 0.0
        outcome, code = "COMPLETE", EXIT_OK
        for entry in pending:
            if args.max_files is not None and processed >= args.max_files:
                outcome, code = "PARTIAL_MAX_FILES", EXIT_PARTIAL
                break
            measured = read_bytes / busy_seconds if busy_seconds > 0 else None
            rate = measured if (measured and processed >= 5) else min(PRIOR_RATE_BYTES_PER_SECOND,
                                                                       measured or PRIOR_RATE_BYTES_PER_SECOND)
            projected = PROJECTION_SAFETY * entry["bytes"] / rate
            now = dt.datetime.now()
            if now + dt.timedelta(seconds=projected) > deadline:
                outcome, code = "PARTIAL_STOP_AT", EXIT_PARTIAL
                break
            if (time.monotonic() - run_started + projected) > args.max_runtime_minutes * 60:
                outcome, code = "PARTIAL_MAX_RUNTIME", EXIT_PARTIAL
                break
            check_window()
            check_memory()
            record = stage_one(repo, out, entry)
            write_json_atomic(state_path(out, entry["slug"]), record)
            processed += 1
            read_bytes += entry["bytes"]
            busy_seconds += record["seconds"]
            staged_now += record["status"] == "staged"
            emit({"slug": entry["slug"], "status": record["status"], "seconds": record["seconds"],
                  "rows_dropped_ge_cutoff": record.get("rows_dropped_ge_cutoff"),
                  "rows_dropped_unparseable": record.get("rows_dropped_unparseable")})
            if processed == 5:
                left = sum(e["bytes"] for e in pending[processed:])
                emit({"kind": "projection_after_5_files", "bytes_per_second": int(read_bytes / max(busy_seconds, 1e-6)),
                      "projected_remaining_seconds": int(left / max(read_bytes / max(busy_seconds, 1e-6), 1))})
        receipt.update({"outcome": outcome, "exit_code": code, "files_processed": processed,
                        "files_staged": staged_now, "source_bytes_read": read_bytes,
                        "busy_seconds": round(busy_seconds, 3), "free_bytes_end": free_bytes(out),
                        "pending_at_start": len(pending)})
    except DiskFloor:
        receipt.update({"outcome": "ABORT_DISK_FLOOR", "exit_code": EXIT_DISK})
        code = EXIT_DISK
    except Refusal as exc:
        receipt.update({"outcome": "REFUSED", "refusal": exc.code, "exit_code": EXIT_REFUSED})
        code = EXIT_REFUSED
    receipt["ended_utc"] = utc_now_iso()
    receipt["seconds"] = round(time.monotonic() - run_started, 3)
    if os.path.isdir(out):
        append_receipt(out, receipt)
    emit(receipt)
    return code


# --------------------------------------------------------------------------------------------
# verify-staged
# --------------------------------------------------------------------------------------------

def check_staged_file(out, record):
    """Decode one staged file and re-derive everything the record claims. Returns a list of problems."""
    problems = []
    path = os.path.join(out, *record["staged_relpath"].split("/"))
    with open(path, "rb") as handle:
        stored = handle.read()
    if len(stored) != record["staged_bytes"] or sha256_bytes(stored) != record["staged_sha256"]:
        problems.append("staged_hash_or_bytes")
    decoded_sha = hashlib.sha256()
    decoded_bytes = [0]

    def sink(data):
        decoded_sha.update(data)
        decoded_bytes[0] += len(data)

    try:
        header_sha, stats = filter_lines(gzip.GzipFile(fileobj=io.BytesIO(stored), mode="rb"),
                                         record["slug"], sink, lambda count: None)
    except (Refusal, Unstable, EOFError, gzip.BadGzipFile, zlib.error) as exc:
        return problems + ["decode_or_rules:" + str(exc)]
    if stats.rows_dropped_ge_cutoff:
        problems.append("content_after_cutoff")
    if stats.rows_dropped_unparseable:
        problems.append("unparseable_rows_in_staged")
    if decoded_sha.hexdigest() != record["decoded_sha256"] or decoded_bytes[0] != record["decoded_bytes"]:
        problems.append("decoded_hash_or_bytes")
    if header_sha != record["header_sha256"]:
        problems.append("header_sha256")
    derived = stats.as_dict()
    if derived["rows_total"] != record["rows_kept"]:
        problems.append("rows_kept")
    for key in ("kept_captured_at_utc_min", "kept_captured_at_utc_max", "kept_book_time_utc_max"):
        if derived[key] != record[key]:
            problems.append(key)
    return problems


def cmd_verify_staged(args):
    allow_sha = self_check()
    check_window()
    out = os.path.abspath(args.out)
    paths = out_paths(out)
    if not os.path.exists(paths["source_manifest"]):
        raise Refusal("no_source_manifest")
    script_sha = sha256_own_file(os.path.abspath(__file__))
    with open(paths["source_manifest"], "rb") as handle:
        source_bytes = handle.read()
    doc = json.loads(source_bytes.decode("utf-8"))
    if doc.get("schema") != SCHEMA_SOURCE or doc.get("allowlist_sha256") != allow_sha \
            or doc.get("script_sha256") != script_sha:
        raise Refusal("source_manifest_mismatch")
    set_below_normal_priority()
    check_memory()
    files, pending, failures = [], [], []
    for entry in doc["entries"]:
        if entry["status"] != "present":
            files.append({"slug": entry["slug"], "market": entry["market"], "target_date": entry["target_date"],
                          "status": entry["status"]})
            continue
        record = load_state(out, entry["slug"])
        if record is None:
            pending.append(entry["slug"])
            continue
        if record["status"] == "staged":
            problems = check_staged_file(out, record)
            if problems:
                failures.append({"slug": entry["slug"], "problems": problems})
        files.append(record)
    if pending:
        emit({"kind": "verify_staged", "outcome": "INCOMPLETE", "pending": len(pending)})
        return EXIT_PARTIAL
    staged = [r for r in files if r["status"] == "staged"]
    expected_names = {r["staged_relpath"] for r in staged}
    found_names = set()
    for root, _dirs, names in os.walk(paths["books"]):
        for name in names:
            rel = os.path.relpath(os.path.join(root, name), out).replace(os.sep, "/")
            found_names.add(rel)
    extra = sorted(found_names - expected_names)
    missing = sorted(expected_names - found_names)
    if failures or extra or missing:
        emit({"kind": "verify_staged", "outcome": "REFUSED", "failures": failures[:20],
              "extra_files": extra[:20], "missing_files": missing[:20]})
        return EXIT_REFUSED

    sums_lines = "".join(f"{r['staged_sha256']}  {r['staged_relpath']}\n"
                         for r in sorted(staged, key=lambda r: r["staged_relpath"]))
    sums_data = sums_lines.encode("ascii")
    with open(paths["sums"], "wb") as handle:
        handle.write(sums_data)

    def count(prefix):
        return sum(1 for r in files if r["status"].startswith(prefix))

    manifest = {
        "schema": SCHEMA_MANIFEST,
        "created_utc": utc_now_iso(),
        "plan": "night-plans/o9/O9-TRANSFER-PLAN.md",
        "plan_sha256": args.plan_sha256,
        "host_id": args.host_id or doc.get("host", ""),
        "production_git_head": args.production_git_head,
        "script_sha256": script_sha,
        "source_manifest_sha256": sha256_bytes(source_bytes),
        "allowlist_sha256": allow_sha,
        "dates": list(DATES),
        "markets": list(MARKETS),
        "cutoff_utc": CUTOFF_ISO,
        "cutoff_epoch_ms": CUTOFF_EPOCH_MS,
        "no_folder_dated_on_or_after_2026_09_30_constructed_or_opened": True,
        "counts": {"expected": len(ALLOWLIST_SLUGS), "staged": len(staged), "missing": count("missing"),
                   "unstable": count("unstable"), "refused": count("refused:"), "error": count("error:")},
        "totals": {
            "source_bytes_staged": sum(r["source_bytes"] for r in staged),
            "staged_bytes": sum(r["staged_bytes"] for r in staged),
            "decoded_bytes": sum(r["decoded_bytes"] for r in staged),
            "rows_kept": sum(r["rows_kept"] for r in staged),
            "rows_dropped_ge_cutoff": sum(r["rows_dropped_ge_cutoff"] for r in staged),
            "rows_dropped_unparseable": sum(r["rows_dropped_unparseable"] for r in staged),
        },
        "sha256sums_sha256": sha256_bytes(sums_data),
        "files": files,
    }
    manifest_sha = write_json_atomic(paths["manifest"], manifest)  # written last
    emit({"kind": "verify_staged", "outcome": "PASS", "manifest_sha256": manifest_sha,
          "counts": manifest["counts"], "totals": manifest["totals"]})
    return EXIT_OK


# --------------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(description="O9 book-summary staging (capture host; plan section 5).")
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight", help="stat-only presence and size report; writes nothing")
    pre.add_argument("--repo-root", required=True)
    pre.add_argument("--probe-gz", action="store_true",
                     help="also stat order_books_summary.csv.gz where the .csv is absent (default: exactly 552 stats)")
    stg = sub.add_parser("stage", help="write SOURCE-MANIFEST.json, then filter and gzip into --out")
    stg.add_argument("--repo-root", required=True)
    stg.add_argument("--out", required=True)
    stg.add_argument("--stop-at", default="08:30", help="local HH:MM, 00:31-09:00; stop between files")
    stg.add_argument("--max-files", type=int, default=None, help="process at most N files this run")
    stg.add_argument("--max-runtime-minutes", type=int, default=120)
    ver = sub.add_parser("verify-staged", help="re-check staged files, then write SHA256SUMS and MANIFEST.json")
    ver.add_argument("--out", required=True)
    ver.add_argument("--plan-sha256", default=None)
    ver.add_argument("--host-id", default=None)
    ver.add_argument("--production-git-head", default=None)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {"preflight": cmd_preflight, "stage": cmd_stage, "verify-staged": cmd_verify_staged}
    try:
        return handlers[args.command](args)
    except Refusal as exc:
        emit({"kind": args.command, "outcome": "REFUSED", "refusal": exc.code})
        return EXIT_REFUSED
    except DiskFloor:
        emit({"kind": args.command, "outcome": "ABORT_DISK_FLOOR"})
        return EXIT_DISK
    except Exception as exc:  # noqa: BLE001 - report and exit non-zero; never swallow silently
        emit({"kind": args.command, "outcome": "ERROR", "error": type(exc).__name__, "detail": str(exc)[:300]})
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
