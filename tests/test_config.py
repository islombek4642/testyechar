import pytest

from bot.config import load_settings


def _set_base_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:abc")
    monkeypatch.setenv("BOT_ADMIN_ID", "111")
    monkeypatch.setenv("BOT_ALLOWED_USERS", "222, 333, ,junk")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


def test_load_settings_parses_env(monkeypatch):
    _set_base_env(monkeypatch)
    s = load_settings()
    assert s.bot_token == "123:abc"
    assert s.admin_id == 111
    assert s.allowed_users == frozenset({222, 333})
    assert s.anthropic_api_key == "sk-test"
    assert s.model == "claude-opus-4-8"


def test_is_allowed(monkeypatch):
    _set_base_env(monkeypatch)
    s = load_settings()
    assert s.is_allowed(111)      # admin
    assert s.is_allowed(222)      # listed
    assert not s.is_allowed(999)  # stranger


def test_missing_token_raises(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.delenv("BOT_TOKEN")
    with pytest.raises(RuntimeError):
        load_settings()


def test_bad_admin_id_raises(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("BOT_ADMIN_ID", "abc")
    with pytest.raises(RuntimeError):
        load_settings()
