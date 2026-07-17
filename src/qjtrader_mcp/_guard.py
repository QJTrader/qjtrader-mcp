"""Environment detection and the live-trade guard.

Current QJ servers report the authoritative environment in the authenticated
session. ``QJ_ENV`` remains a declaration for compatibility and as a useful
stale-configuration check, but it is never the authority for a mutation.

    QJ_ENV=sandbox   → simulated data + simulated fills; order tools allowed
    QJ_ENV=live      → real venues; order tools refuse unless QJ_MCP_ALLOW_LIVE=1
    (unset)          → unknown; order tools refuse (fail safe), read tools work

The console's "Connect your AI" panel injects ``QJ_ENV`` when it generates the
config, so sandbox works out of the box. For hand-written configs the default is
deliberately safe: an unknown environment is treated like production, because a
live and a sandbox credential are indistinguishable to us and silently placing a
real order would be the worst possible failure.
"""
from __future__ import annotations

import os

SANDBOX = "sandbox"
LIVE = "live"
UNKNOWN = "unknown"
PAPER = "paper"
SHADOW = "shadow"
CANARY = "canary"

_LIVE_ALIASES = {"live", "real", "production", "prod"}
_SANDBOX_ALIASES = {"sandbox", "sim", "simulated", "demo", "test"}


def environment() -> str:
    """The credential's environment as declared by ``QJ_ENV`` (best-effort)."""
    raw = (os.environ.get("QJ_ENV") or "").strip().lower()
    if raw in _SANDBOX_ALIASES:
        return SANDBOX
    if raw in _LIVE_ALIASES:
        return LIVE
    return UNKNOWN


def risk_class(env: str | None) -> str:
    """Collapse detailed server rungs into simulated-vs-exchange safety."""
    value = (env or "").strip().lower()
    if value in {SANDBOX, PAPER, SHADOW, "sim", "simulated", "demo", "test"}:
        return SANDBOX
    if value in {CANARY, LIVE, "real", "production", "prod"}:
        return LIVE
    return UNKNOWN


def declaration_mismatch(server_environment: str | None) -> bool:
    """True only when a configured QJ_ENV contradicts server safety class."""
    declared = environment()
    authoritative = risk_class(server_environment)
    return declared != UNKNOWN and authoritative != UNKNOWN and declared != authoritative


def allow_live() -> bool:
    """Whether the operator has explicitly authorized live order actions."""
    return os.environ.get("QJ_MCP_ALLOW_LIVE") == "1"


def tag(server_environment: str | None = None) -> str:
    """A short banner prefixed to every tool result so the model can never lose
    track of which environment it is acting in."""
    raw = (server_environment or "").strip().lower()
    env = risk_class(raw) if server_environment is not None else environment()
    if env == SANDBOX:
        label = raw.upper() if raw in {PAPER, SHADOW} else "SANDBOX"
        return f"[{label} — NO EXCHANGE]"
    if env == LIVE:
        label = "CANARY" if raw == CANARY else "LIVE"
        return f"[{label} — REAL MONEY]"
    if environment() == SANDBOX:
        return "[SANDBOX — DECLARED; SERVER UNCONFIRMED]"
    if environment() == LIVE:
        return "[LIVE — REAL MONEY]"
    return "[ENV UNKNOWN — SERVER CONFIRMATION REQUIRED]"


def mutations_allowed(server_environment: str | None = None) -> tuple[bool, str]:
    """Return ``(allowed, reason)`` for order-mutating tools.

    Allowed when the environment is sandbox, or when live actions are explicitly
    enabled. Refused (safely) for live-or-unknown environments otherwise.
    """
    if server_environment is None:
        env = environment()
    else:
        env = risk_class(server_environment)
        if env == UNKNOWN:
            return False, "The server did not provide a recognized order environment; mutation refused."
        if declaration_mismatch(server_environment):
            return (False,
                    f"QJ_ENV declares {environment()} but the server reports "
                    f"{server_environment}; mutation refused until the local "
                    "configuration is refreshed.")
    if env == SANDBOX:
        return True, f"server-confirmed {server_environment or 'sandbox'} — no exchange transmission"
    if env == LIVE and allow_live():
        return True, (f"server-confirmed {server_environment or 'live'} and live order "
                      "actions explicitly enabled via QJ_MCP_ALLOW_LIVE=1")
    if env == LIVE:
        return (
            False,
            f"The server reports {server_environment or 'live'} (real money) and live order actions are "
            "disabled by default. To authorize real orders through this MCP "
            "server, set QJ_MCP_ALLOW_LIVE=1 in its environment and restart it.",
        )
    return (
        False,
        "The environment for this credential is unknown, so order actions are "
        "refused as a safety default. If this is a sandbox credential, set "
        "QJ_ENV=sandbox. If it is live and you intend to place real orders, set "
        "QJ_MCP_ALLOW_LIVE=1. Restart the server after changing the environment.",
    )


def max_qty() -> int:
    """Client-side fat-finger cap on order quantity (mirrors the bridge guards).

    Overridable with ``QJ_MCP_MAX_QTY``; defaults to a small number because an
    AI-authored order should never be large by accident.
    """
    try:
        return max(1, int(os.environ.get("QJ_MCP_MAX_QTY", "25")))
    except ValueError:
        return 25
