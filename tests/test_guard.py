"""The sandbox/live guard — the safety-critical logic, tested without network."""
import importlib

import pytest


@pytest.fixture
def guard(monkeypatch):
    # Clear all relevant env, then re-import so module-level reads are fresh.
    for k in ("QJ_ENV", "QJ_MCP_ALLOW_LIVE", "QJ_MCP_MAX_QTY"):
        monkeypatch.delenv(k, raising=False)
    import qjtrader_mcp._guard as g
    return importlib.reload(g)


def test_unknown_env_refuses_mutations(guard, monkeypatch):
    monkeypatch.delenv("QJ_ENV", raising=False)
    assert guard.environment() == guard.UNKNOWN
    ok, reason = guard.mutations_allowed()
    assert ok is False
    assert "unknown" in reason.lower()


def test_sandbox_allows_mutations(guard, monkeypatch):
    monkeypatch.setenv("QJ_ENV", "sandbox")
    assert guard.environment() == guard.SANDBOX
    ok, _ = guard.mutations_allowed()
    assert ok is True
    assert guard.tag() == "[SANDBOX]"


def test_live_refuses_without_flag(guard, monkeypatch):
    monkeypatch.setenv("QJ_ENV", "live")
    ok, reason = guard.mutations_allowed()
    assert ok is False
    assert "QJ_MCP_ALLOW_LIVE" in reason


def test_live_allows_with_flag(guard, monkeypatch):
    monkeypatch.setenv("QJ_ENV", "live")
    monkeypatch.setenv("QJ_MCP_ALLOW_LIVE", "1")
    ok, reason = guard.mutations_allowed()
    assert ok is True
    assert "explicitly enabled" in reason
    assert "REAL MONEY" in guard.tag()


def test_allow_live_flag_overrides_unknown(guard, monkeypatch):
    monkeypatch.delenv("QJ_ENV", raising=False)
    monkeypatch.setenv("QJ_MCP_ALLOW_LIVE", "1")
    ok, _ = guard.mutations_allowed()
    assert ok is True


@pytest.mark.parametrize("alias", ["sandbox", "sim", "demo", "TEST", "Simulated"])
def test_sandbox_aliases(guard, monkeypatch, alias):
    monkeypatch.setenv("QJ_ENV", alias)
    assert guard.environment() == guard.SANDBOX


@pytest.mark.parametrize("alias", ["live", "real", "production", "PROD"])
def test_live_aliases(guard, monkeypatch, alias):
    monkeypatch.setenv("QJ_ENV", alias)
    assert guard.environment() == guard.LIVE


def test_max_qty_default_and_override(guard, monkeypatch):
    assert guard.max_qty() == 25
    monkeypatch.setenv("QJ_MCP_MAX_QTY", "5")
    assert guard.max_qty() == 5
    monkeypatch.setenv("QJ_MCP_MAX_QTY", "garbage")
    assert guard.max_qty() == 25
