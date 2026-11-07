"""Fixture-only public outcome paths; tests never touch the owner's STOP or status directory.

Guards: T004 B018 filesystem and cancellation boundary.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_lfc_status(tmp_path, monkeypatch):
    from weather.market import lfc_session_status
    monkeypatch.setattr(lfc_session_status, 'STATUS_DIRECTORY', tmp_path / 'public-status')
    monkeypatch.setattr(lfc_session_status, 'OWNER_STOP_FILE', tmp_path / 'owner-stop')
