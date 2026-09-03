"""Startup guards: placeholder-secret refusal."""

import pytest

from evalbench.api.main import _check_secrets


@pytest.fixture
def _settings(monkeypatch):
    from evalbench.api import main as m

    # Start from a fully-real config; each test dirties one field.
    monkeypatch.setattr(m.settings, "secret_key", "a-real-secret-value-here")
    monkeypatch.setattr(m.settings, "admin_password", "a-real-password")
    monkeypatch.setattr(m.settings, "admin_api_key", "eb_real_key_value")
    monkeypatch.delenv("EVALBENCH_ALLOW_INSECURE", raising=False)
    return m.settings


def test_passes_with_real_secrets(_settings):
    _check_secrets()  # no raise


def test_raises_on_placeholder_secret_key(_settings, monkeypatch):
    monkeypatch.setattr(
        _settings, "secret_key", "change-this-to-a-random-32-char-string"
    )
    with pytest.raises(RuntimeError, match="secret_key"):
        _check_secrets()


def test_raises_on_placeholder_admin_api_key(_settings, monkeypatch):
    monkeypatch.setattr(
        _settings, "admin_api_key", "eb_admin_change_me_in_production"
    )
    with pytest.raises(RuntimeError, match="admin_api_key"):
        _check_secrets()


def test_allow_insecure_downgrades_to_warning(_settings, monkeypatch, caplog):
    monkeypatch.setattr(
        _settings, "admin_password", "change-me-in-production"
    )
    monkeypatch.setenv("EVALBENCH_ALLOW_INSECURE", "1")
    _check_secrets()  # no raise
    assert "placeholder" in caplog.text.lower()
