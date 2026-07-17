"""Offline symbology helper for the ``explain_symbol`` tool.

Mirrors the public symbology reference (https://docs.qjtrader.ai/docs/ai/symbology)
so an agent can name instruments without a round-trip. A QJ symbol is a
security-type prefix (derivatives only), a root, and an exchange suffix. The
cloud market-data/order APIs also accept a namespace form used in the SDK
examples: ``CA:RY``, ``MX:CRAU26``, ``US:SPY``, ``US:@ESU26``.
"""
from __future__ import annotations

from typing import Any

# Security-type prefixes (everything except a plain stock/ETF).
_TYPE_PREFIX = {
    "/": "future",
    "#": "option (equity or on a future)",
    "$": "foreign exchange",
    "%": "strategy / spread",
    "!": "implied (exchange-generated leg)",
}

# Canadian venue (exchange-suffix) codes.
_VENUE = {
    "CA": "Consolidated — best bid/offer across all venues (lit aggregate)",
    "TO": "Toronto Stock Exchange (TSX) — senior listings (also TX)",
    "TX": "Toronto Stock Exchange (TSX)",
    "V": "TSX Venture Exchange — junior listings",
    "PT": "PURE — Canadian Securities Exchange (CSE)",
    "AQN": "NEO Exchange (Cboe Canada)",
    "AQL": "Cboe Canada — lit book (Aequitas)",
    "AL": "Alpha",
    "OG": "Omega",
    "CH": "Chi-X Canada",
    "CX": "CX2",
    "LY": "Lynx",
    "TL": "MatchNow (TriAct) — dark",
    "CXD": "Nasdaq CXD — dark",
    "TLM": "MatchNow (TriAct) — MarketFlow route",
    "SOR": "Canadian smart order router (order route; no single-venue data book)",
    "DARK": "Canadian smart router dark-only sweep (order route; no lit data book)",
    "ME": "Montréal Exchange — derivatives (futures & options)",
    "FX": "Foreign exchange",
    "CME": "CME",
    "CBO": "CBOT",
    "N": "NYSE",
    "Q": "Nasdaq",
}

# Cloud API namespaces (the ``NS:`` prefix in SDK examples).
_NAMESPACE = {
    "CA": "Canadian equities (consolidated unless a venue suffix is given)",
    "MX": "Montréal Exchange derivatives (futures & options)",
    "US": "US equities",
}

_REFERENCE = "https://docs.qjtrader.ai/docs/ai/symbology"

# Option chains are keyed by the expiry MONTH, not a full date: pass `expiry`
# as YYYYMM (e.g. "202608") to get_chain — the exchange's 3rd-Friday expiry day
# is derived for you. Use list_expiries to discover valid months.
_CHAIN_EXPIRY = (
    "Option chains take an expiry MONTH as YYYYMM (e.g. '202608'); the "
    "exchange's 3rd-Friday day is derived for you — do not pass a full date. "
    "Call list_expiries(underlying) to discover valid months."
)


def explain(symbol: str) -> dict[str, Any]:
    """Parse a symbol into its parts and describe them; never raises."""
    raw = (symbol or "").strip()
    out: dict[str, Any] = {"input": raw, "reference": _REFERENCE,
                           "chain_expiry": _CHAIN_EXPIRY}
    if not raw:
        out["help"] = (
            "Provide a symbol like 'CA:RY' (Royal Bank consolidated), "
            "'CA:RY.PT' (on PURE/CSE), 'MX:CRAU26' (a Montréal future), "
            "or 'US:@ESU26' (a selected US future). "
            "Format: [namespace:] [type-prefix] ROOT [.VENUE]."
        )
        out["namespaces"] = _NAMESPACE
        out["security_types"] = _TYPE_PREFIX
        return out

    body = raw
    if ":" in body:
        ns, body = body.split(":", 1)
        out["namespace"] = ns.upper()
        out["namespace_meaning"] = _NAMESPACE.get(
            ns.upper(), "unknown namespace — see the reference")

    type_prefix = ""
    if body[:1] in _TYPE_PREFIX:
        type_prefix = body[0]
        out["security_type"] = _TYPE_PREFIX[type_prefix]
        body = body[1:]
    else:
        out["security_type"] = "stock / ETF (no prefix)"

    venue = None
    root = body
    if "." in body:
        root, venue = body.rsplit(".", 1)
    out["root"] = root.strip()
    if venue:
        out["venue"] = venue
        out["venue_meaning"] = _VENUE.get(
            venue.upper(), "unknown venue code — see the reference")
        out["consolidated"] = venue.upper() == "CA"
    else:
        out["venue"] = None
        out["note"] = (
            "No explicit venue. For a namespaced equity like 'CA:RY' this is the "
            "consolidated book; add a venue suffix (e.g. 'CA:RY.PT') for one "
            "exchange. Futures/options are venue-native."
        )
    return out
