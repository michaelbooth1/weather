"""Check-only BLAS/OpenMP thread pins for v2 export processes (B-defender D12/D13, owner decision 2).

OpenBLAS reads ``OPENBLAS_NUM_THREADS`` once, when its DLL loads, and the exporter's imports load numpy through
scipy before ``main`` runs. Setting the variable in-process is therefore too late, and would make a receipt claim a
pin that is not in force. The launcher (the nightly wrapper) sets all four variables to ``1`` in the child's
environment; the process only **verifies** them and records what is actually running:

- ``environment``: the four variables as the process saw them;
- ``logical_cpus``: ``os.cpu_count()`` (each unpinned OpenBLAS thread commits about 47 MiB at import);
- ``pools``: ``threadpoolctl.threadpool_info()`` reduced to API, library and ``num_threads``, or ``None`` with
  ``threadpoolctl: "absent"`` when it is not installed.

Nothing here sets an environment variable.
"""
from __future__ import annotations

import os

from maker_core.replay.bundle import BundleError

PINNED_VARIABLES = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
REFUSAL_CODES = ("blas_threads_not_pinned",)


def _pools():
    try:
        from threadpoolctl import __version__, threadpool_info
    except ImportError:
        return "absent", None
    pools = sorted((dict(user_api=str(p.get("user_api")), internal_api=str(p.get("internal_api")),
                         prefix=str(p.get("prefix")), num_threads=p.get("num_threads"))
                    for p in threadpool_info()),
                   key=lambda p: (p["user_api"], p["internal_api"], p["prefix"]))
    return str(__version__), pools


def thread_record(environ) -> dict:
    """What the receipt records: the pins as seen, the logical CPU count and the actual thread pools."""
    pins = {name: environ.get(name) for name in PINNED_VARIABLES}
    version, pools = _pools()
    return dict(environment=pins, pinned=all(value == "1" for value in pins.values()), logical_cpus=os.cpu_count(),
                threadpoolctl=version, pools=pools)


def check_thread_pins(environ) -> dict:
    """The record, or ``blas_threads_not_pinned`` unless all four variables were ``1`` at process start."""
    record = thread_record(environ)
    if not record["pinned"]:
        raise BundleError("blas_threads_not_pinned")
    return record
