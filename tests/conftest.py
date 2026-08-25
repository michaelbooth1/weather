"""Repository-wide deterministic test safety boundary.

Ordinary tests already use injected transports.  Qualification and CI set the
guard below so an accidental real transport cannot silently turn a test into
external I/O.  This module is tracked and loaded before test-module imports;
ignored or untracked conftest shadows are separately forbidden by the bounded
runner.
"""

from __future__ import annotations

import os
import socket


OFFLINE_ENV = "WEATHER_INTEGRATION_TEST_OFFLINE"
OFFLINE_BOOTSTRAP_READY_ENV = "WEATHER_INTEGRATION_TEST_BOOTSTRAP_READY"


def _blocked_external_io(*_args, **_kwargs):
    raise RuntimeError("network access is forbidden by the integration-test offline boundary")


if os.environ.get(OFFLINE_ENV) == "1":
    if os.environ.get(OFFLINE_BOOTSTRAP_READY_ENV) != "1":
        raise RuntimeError(
            "tracked integration-test offline bootstrap did not complete"
        )
    for name in (
        "create_connection",
        "getaddrinfo",
        "gethostbyaddr",
        "gethostbyname",
        "gethostbyname_ex",
    ):
        if hasattr(socket, name):
            setattr(socket, name, _blocked_external_io)
    for name in ("connect", "connect_ex", "sendall", "sendmsg", "sendto"):
        if hasattr(socket.socket, name):
            setattr(socket.socket, name, _blocked_external_io)
