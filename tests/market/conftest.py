"""Fixture-only public paths and toast transport; no owner desktop interaction.

Guards: T004 B018 filesystem and cancellation boundary.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_lfc_status(tmp_path, monkeypatch):
    from weather.market import lfc_session_status
    monkeypatch.setattr(lfc_session_status, 'STATUS_DIRECTORY', tmp_path / 'public-status')
    monkeypatch.setattr(lfc_session_status, 'OWNER_STOP_FILE', tmp_path / 'owner-stop')


@pytest.fixture(autouse=True)
def isolated_lfc_notification_transport(monkeypatch):
    from types import SimpleNamespace
    import threading
    from weather.market.lfc_pilot import notify_owner
    # Replace the default OS transport/output. Explicit injected runners still
    # test notify_owner's arguments, timeout and failure handling normally.
    defaults = {**notify_owner.__kwdefaults__, 'runner': lambda *a, **kw: SimpleNamespace(returncode=0),
                'printer': lambda *a, **kw: None}
    monkeypatch.setattr(notify_owner, '__kwdefaults__', defaults)
    yield
    # A late notification must finish before the transport fixture is restored.
    for thread in threading.enumerate():
        if thread.name == 'lfc-incident-notice':
            thread.join(2)
            assert not thread.is_alive(), 'notification test worker did not finish'
