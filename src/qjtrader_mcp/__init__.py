"""qjtrader-mcp — Model Context Protocol server for the QJ Trader AI Trading APIs.

Run ``qjtrader-mcp`` (stdio) and point an MCP client at it. See ``server`` for the
tool surface and ``_guard`` for the sandbox/live safety model.
"""
from __future__ import annotations

from ._version import __version__

__all__ = ["__version__", "main"]


def main() -> None:
    # Imported lazily so ``import qjtrader_mcp`` doesn't require the mcp package.
    from .server import main as _main

    _main()
