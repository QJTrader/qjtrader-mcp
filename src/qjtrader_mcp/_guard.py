"""Environment detection and the live-trade guard.

The QJ wire protocol does **not** tell a connected client whether its credential
is sandbox or production (the `auth_success` ack carries only `user`/`compid`, and
`status` carries only orders/sessions). So the MCP server cannot sniff the
environment off the socket — it is told, explicitly, via ``QJ_ENV``:

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


def allow_live() -> bool:
    """Whether the operator has explicitly authorized live order actions."""
    return os.environ.get("QJ_MCP_ALLOW_LIVE") == "1"


def tag() -> str:
    """A short banner prefixed to every tool result so the model can never lose
    track of which environment it is acting in."""
    env = environment()
    if env == SANDBOX:
        return "[SANDBOX]"
    if env == LIVE:
        return "[LIVE — REAL MONEY]"
    return "[ENV UNKNOWN — set QJ_ENV=sandbox or live]"


def mutations_allowed() -> tuple[bool, str]:
    """Return ``(allowed, reason)`` for order-mutating tools.

    Allowed when the environment is sandbox, or when live actions are explicitly
    enabled. Refused (safely) for live-or-unknown environments otherwise.
    """
    env = environment()
    if env == SANDBOX:
        return True, "sandbox credential — simulated orders only"
    if allow_live():
        return True, "live order actions explicitly enabled via QJ_MCP_ALLOW_LIVE=1"
    if env == LIVE:
        return (
            False,
            "This credential is LIVE (real money) and live order actions are "
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
