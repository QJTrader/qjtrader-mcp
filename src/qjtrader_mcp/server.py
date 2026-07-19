"""qjtrader-mcp — a Model Context Protocol server over the QJ Trader APIs.

Exposes the QJ market-data and order-entry APIs as MCP tools so an LLM
(Claude Code, Claude Desktop, or any MCP client) can watch quotes and place
**simulated** orders on your own credential — without you writing any code.

Safety posture (see ``_guard``): read-only tools always work; order-mutating
tools run against a **sandbox** credential by default and refuse a live
credential unless ``QJ_MCP_ALLOW_LIVE=1`` is set. Every result is tagged with
the environment it acted in.

Configuration (same env vars as the ``qjtrader`` SDK, plus MCP-specific ones):

    QJ_CLIENT_ID / QJ_CLIENT_SECRET   your credential (required)
    QJ_ENV                            sandbox | live   (declares the environment)
    QJ_MCP_ALLOW_LIVE=1               authorize real order actions (default: off)
    QJ_MCP_MAX_QTY                    client-side max order qty (default: 25)
    QJ_DATA_HOST / QJ_ORDERS_HOST     endpoint overrides (default: public hosts)
    QJ_CA_FILE                        pin a CA/cert (pilot order endpoint)

Run it:  ``qjtrader-mcp``   (stdio transport)
"""
from __future__ import annotations

import os
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP

import qjtrader
from qjtrader.errors import QJError

from . import _guard
from ._symbology import explain as _explain_symbol

mcp = FastMCP(
    "qjtrader",
    instructions=(
        "Tools for QJ Trader: research Canadian markets, then stream data and "
        "place orders. You are a quant developer here, not a trader: use the "
        "research tools (`get_history`, `get_stats`, `get_chain`, `compare`, "
        "`read_events`) to analyse the market and debug strategies; order actions "
        "run against a SANDBOX credential by default (simulated fills). Always "
        "check `session_info` first to see which environment you are in. Symbols "
        "have product-specific availability: call `market_availability` before "
        "assuming a quote or depth book exists. Symbols "
        "are namespaced (e.g. CA:RY, MX:CRAU26, US:SPY, US:@ESU26) — call `explain_symbol` "
        "if unsure. Prefer digests (`get_stats`) over raw dumps. Every result "
        "begins with an environment tag."
    ),
)


# --------------------------------------------------------------------- helpers
def _client() -> qjtrader.Client:
    """Build a Client from the environment (raises QJError if creds are missing)."""
    return qjtrader.Client()


async def _server_session() -> dict[str, Any]:
    """Resolve both environments from the authenticated server handshakes."""
    return await anyio.to_thread.run_sync(lambda: _client().session_info())


async def _order_guard() -> tuple[bool, str, str, dict[str, Any]]:
    """Authoritative mutation guard; local QJ_ENV can only make it stricter."""
    try:
        session = await _server_session()
    except (QJError, OSError) as e:
        reason = f"Could not confirm the server order environment; mutation refused: {e}"
        return False, reason, _guard.tag(), {}
    env = str(session.get("orders_environment") or "unknown")
    ok, reason = _guard.mutations_allowed(env)
    return ok, reason, _guard.tag(env), session


def _top_of_book(msg: dict[str, Any]) -> dict[str, Any]:
    """Best bid/ask from a snapshot or quote message, defensively."""
    data = msg.get("data") or {}
    bid = data.get("bid")
    ask = data.get("ask")
    bid_sz = data.get("bid_size") or data.get("bidSize")
    ask_sz = data.get("ask_size") or data.get("askSize")
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    if bid is None and bids:
        top = bids[0]
        bid = top.get("price") if isinstance(top, dict) else top
        bid_sz = top.get("size") if isinstance(top, dict) else bid_sz
    if ask is None and asks:
        top = asks[0]
        ask = top.get("price") if isinstance(top, dict) else top
        ask_sz = top.get("size") if isinstance(top, dict) else ask_sz
    out: dict[str, Any] = {"bid": bid, "ask": ask}
    if bid_sz is not None:
        out["bid_size"] = bid_sz
    if ask_sz is not None:
        out["ask_size"] = ask_sz
    if msg.get("type") == "trade":
        out["last"] = data.get("price") or data.get("last")
    return out


def _blocking_snapshot(symbols: list[str], depth: int | None,
                       seconds: float) -> dict[str, Any]:
    """Subscribe, then keep the latest book per symbol for `seconds`."""
    latest: dict[str, dict[str, Any]] = {}
    with _client().market_data() as md:
        user = md.user
        md.subscribe(symbols, depth=depth)
        for msg in md.messages(timeout=seconds):
            sym = msg.get("symbol")
            if sym and msg.get("type") in ("snapshot", "quote", "level2", "trade"):
                latest[sym] = msg
    quotes = {sym: _top_of_book(msg) for sym, msg in latest.items()}
    missing = [s for s in symbols if s not in quotes]
    return {"user": user, "quotes": quotes, "missing": missing}


def _blocking_depth(symbol: str, levels: int, seconds: float) -> dict[str, Any]:
    book: dict[str, Any] = {}
    with _client().market_data() as md:
        user = md.user
        md.subscribe([symbol], depth=levels)
        for msg in md.messages(timeout=seconds):
            if msg.get("symbol") == symbol and msg.get("type") in ("snapshot", "level2"):
                data = msg.get("data") or {}
                book = {
                    "bids": (data.get("bids") or [])[:levels],
                    "asks": (data.get("asks") or [])[:levels],
                    "odd_lot_bids": (data.get("odd_lot_bids") or [])[:levels],
                    "odd_lot_asks": (data.get("odd_lot_asks") or [])[:levels],
                    "special_lot_bids": (data.get("special_lot_bids") or [])[:levels],
                    "special_lot_asks": (data.get("special_lot_asks") or [])[:levels],
                    "order_bids": data.get("order_bids") or [],
                    "order_asks": data.get("order_asks") or [],
                    "meta": msg.get("meta") or {},
                }
    return {"user": user, "symbol": symbol, "book": book}


def _blocking_watch(symbols: list[str], seconds: float, limit: int) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {}
    tail: list[dict[str, Any]] = []
    with _client().market_data() as md:
        user = md.user
        md.subscribe(symbols)
        for msg in md.messages(timeout=seconds):
            sym = msg.get("symbol") or "?"
            typ = msg.get("type") or "?"
            counts.setdefault(sym, {}).setdefault(typ, 0)
            counts[sym][typ] += 1
            tail.append(msg)
            if len(tail) > limit:
                tail.pop(0)
    total = sum(sum(c.values()) for c in counts.values())
    return {"user": user, "seconds": seconds, "total_messages": total,
            "by_symbol": counts, "last_messages": tail}


# ----------------------------------------------------------------- data tools
@mcp.tool()
async def market_availability() -> dict[str, Any]:
    """Return the current market-data and order-entry support matrix.

    Call this before interpreting a silent subscription as an error. It lists
    verified CA/MX/US capabilities and known product-specific limitations,
    including symbol-dependent US depth. This tool is offline and needs no
    network connection or credential.
    """
    result = qjtrader.market_availability()
    result["tag"] = _guard.tag()
    return result


@mcp.tool()
async def get_quote(symbols: list[str], seconds: float = 4.0) -> dict[str, Any]:
    """Get the current top-of-book (best bid/ask) for one or more symbols.

    Symbols are namespaced, e.g. ["CA:RY", "MX:CRAU26", "US:@ESU26"]. This opens a
    short market-data subscription and returns the latest book seen within
    `seconds`. Symbols with no data in that window are listed under "missing"
    (they may be untraded, misspelled, or outside the sandbox's synthetic set).
    """
    seconds = min(max(seconds, 1.0), 15.0)
    try:
        res = await anyio.to_thread.run_sync(_blocking_snapshot, symbols, None, seconds)
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    res["tag"] = _guard.tag()
    return res


@mcp.tool()
async def get_depth(symbol: str, levels: int = 5, seconds: float = 4.0) -> dict[str, Any]:
    """Get all Level-2 views for a single symbol.

    Canadian equity results include rounded Top5, full-size odd/special lots,
    entitled QJ/TMX order-level TL2 rows, and source timing/provenance. Use a venue-scoped
    symbol such as "CA:RY.PT" to isolate one exchange.
    """
    levels = min(max(levels, 1), 20)
    seconds = min(max(seconds, 1.0), 15.0)
    try:
        res = await anyio.to_thread.run_sync(_blocking_depth, symbol, levels, seconds)
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    res["tag"] = _guard.tag()
    return res


@mcp.tool()
async def watch(symbols: list[str], seconds: float = 10.0,
                last: int = 20) -> dict[str, Any]:
    """Sample the live market-data stream for `symbols` for a bounded window.

    Returns a digest — message counts per symbol and type — plus the last `last`
    raw messages. Useful to confirm data is flowing and to see the wire format.
    `seconds` is capped at 30 to keep the call bounded.
    """
    seconds = min(max(seconds, 1.0), 30.0)
    last = min(max(last, 1), 100)
    try:
        res = await anyio.to_thread.run_sync(_blocking_watch, symbols, seconds, last)
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    res["tag"] = _guard.tag()
    return res


# --------------------------------------------------------------- order tools
def _blocking_place(sym: str, side: str, qty: int, price: float,
                    account: str, tif: str, venue: str | None) -> dict[str, Any]:
    with _client().orders() as oe:
        user = oe.user
        result = oe.order_and_wait(sym=sym, side=side, qty=qty, price=price,
                                   account=account, tif=tif, venue=venue)
    return {"user": user, "result": result}


def _blocking_cancel(orig_cid: str) -> dict[str, Any]:
    with _client().orders() as oe:
        cid = oe.cancel(orig_cid)
        terminal = None
        for msg in oe.updates(timeout=10.0):
            if msg.get("orig_cid") == orig_cid or msg.get("cid") == cid:
                terminal = msg
                if msg.get("status") in ("canceled", "rejected"):
                    break
        return {"user": oe.user, "cancel_cid": cid, "result": terminal}


def _blocking_replace(orig_cid: str, qty: int | None,
                      price: float | None) -> dict[str, Any]:
    with _client().orders() as oe:
        cid = oe.replace(orig_cid, qty=qty, price=price)
        terminal = None
        for msg in oe.updates(timeout=10.0):
            if msg.get("orig_cid") == orig_cid or msg.get("cid") in (cid, orig_cid) \
                    or msg.get("new_cid") == cid:
                terminal = msg
                if msg.get("status") in ("replaced", "rejected", "canceled"):
                    break
        return {"user": oe.user, "replace_cid": cid, "result": terminal}


def _blocking_cancel_all() -> dict[str, Any]:
    with _client().orders() as oe:
        oe.cancel_all()
        seen = []
        for msg in oe.updates(timeout=5.0):
            seen.append(msg)
        return {"user": oe.user, "events": seen}


def _blocking_status() -> dict[str, Any]:
    with _client().orders() as oe:
        return {"user": oe.user, "status": oe.status(timeout=10.0)}


@mcp.tool()
async def place_order(sym: str, side: str, qty: int, price: float,
                      account: str = "SIM", tif: str = "day",
                      venue: str | None = None) -> dict[str, Any]:
    """Submit a limit order and wait for it to reach a terminal state.

    side: "buy" | "sell".  tif: "day" | "ioc" | "fok".  ``venue`` selects a
    Canadian equity route (for example TO, PT, LY, TL, SOR, or DARK). Returns the final
    execution/order message (a fill, cancel, reject, or the resting order if it
    is still open after a short wait).

    SAFETY: runs against a SANDBOX credential by default (simulated fills only).
    A live credential is refused unless QJ_MCP_ALLOW_LIVE=1 is set. Quantity is
    capped client-side by QJ_MCP_MAX_QTY (default 25).
    """
    # Explain deterministic local input failures before opening a connection.
    # Any order that survives these checks is still gated by server authority below.
    local_tag = _guard.tag()
    if side not in ("buy", "sell"):
        return {"tag": local_tag, "error": "side must be 'buy' or 'sell'"}
    if tif not in ("day", "ioc", "fok"):
        return {"tag": local_tag, "error": "tif must be 'day', 'ioc', or 'fok'"}
    if qty < 1:
        return {"tag": local_tag, "error": "qty must be >= 1"}
    cap = _guard.max_qty()
    if qty > cap:
        return {"tag": local_tag, "refused": True,
                "reason": f"qty {qty} exceeds the client-side cap of {cap} "
                          f"(raise QJ_MCP_MAX_QTY to allow larger orders)"}
    if price <= 0:
        return {"tag": local_tag, "error": "price must be > 0"}
    ok, reason, env_tag, _session = await _order_guard()
    if not ok:
        return {"tag": env_tag, "refused": True, "reason": reason}
    try:
        res = await anyio.to_thread.run_sync(
            _blocking_place, sym, side, qty, price, account, tif, venue)
    except QJError as e:
        return {"tag": env_tag, "error": str(e)}
    res["tag"] = env_tag
    res["allowed_because"] = reason
    return res


@mcp.tool()
async def cancel_order(orig_cid: str) -> dict[str, Any]:
    """Cancel a working order by its client order id (cid)."""
    ok, reason, env_tag, _session = await _order_guard()
    if not ok:
        return {"tag": env_tag, "refused": True, "reason": reason}
    try:
        res = await anyio.to_thread.run_sync(_blocking_cancel, orig_cid)
    except QJError as e:
        return {"tag": env_tag, "error": str(e)}
    res["tag"] = env_tag
    return res


@mcp.tool()
async def replace_order(orig_cid: str, qty: int | None = None,
                        price: float | None = None) -> dict[str, Any]:
    """Amend a working order's quantity and/or price by its client order id."""
    ok, reason, env_tag, _session = await _order_guard()
    if not ok:
        return {"tag": env_tag, "refused": True, "reason": reason}
    if qty is None and price is None:
        return {"tag": env_tag, "error": "provide qty and/or price to change"}
    if qty is not None:
        if qty < 1:
            return {"tag": env_tag, "error": "qty must be >= 1"}
        cap = _guard.max_qty()
        if qty > cap:
            return {"tag": env_tag, "refused": True,
                    "reason": f"qty {qty} exceeds the client-side cap of {cap}"}
    if price is not None and price <= 0:
        return {"tag": env_tag, "error": "price must be > 0"}
    try:
        res = await anyio.to_thread.run_sync(_blocking_replace, orig_cid, qty, price)
    except QJError as e:
        return {"tag": env_tag, "error": str(e)}
    res["tag"] = env_tag
    return res


@mcp.tool()
async def cancel_all() -> dict[str, Any]:
    """Cancel every working order on this credential (the kill switch)."""
    ok, reason, env_tag, _session = await _order_guard()
    if not ok:
        return {"tag": env_tag, "refused": True, "reason": reason}
    try:
        res = await anyio.to_thread.run_sync(_blocking_cancel_all)
    except QJError as e:
        return {"tag": env_tag, "error": str(e)}
    res["tag"] = env_tag
    return res


@mcp.tool()
async def list_orders() -> dict[str, Any]:
    """List open orders and session state for this credential (read-only)."""
    try:
        res = await anyio.to_thread.run_sync(_blocking_status)
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    res["tag"] = _guard.tag()
    return res


# ----------------------------------------------------- analytics/research tools
@mcp.tool()
async def read_events(since: str | None = None, limit: int = 200) -> dict[str, Any]:
    """Read this credential's order journal — the cross-order event history.

    The single highest-leverage research tool: post-trade analysis and debugging
    the strategy you wrote ("14 rejects, all price-band violations at the open").
    `since` is an ISO-8601 ts cursor (pass back the returned `cursor` to page
    forward). Read-only; works in every environment.
    """
    limit = min(max(limit, 1), 1000)
    try:
        res = await anyio.to_thread.run_sync(lambda: _client().events(since, limit))
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    return {"tag": _guard.tag(), **res}


@mcp.tool()
async def get_positions() -> dict[str, Any]:
    """Where this credential stands: broker-truth positions, risk envelope, and plane.

    The supervision counterpart to `list_orders` (which shows *working* orders):
    this shows what you actually *hold* and what you're *allowed* to hold.

    - `positions` — flat fill-only net per symbol (today's fills this session).
    - `positions_detail` — per canonical symbol, `{broker_qty, fill_qty, total_qty}`,
      i.e. `TotalVolume = InitVolume (broker start-of-day) + NetVolume (today's fills)`.
      This is the number that matters for "how exposed am I right now".
    - `positions_by_account` — the same broker/fill/total view without merging
      different trading accounts that happen to hold the same symbol.
    - `account_financials` — broker morning account value and related fields.
      Account value supports capital monitoring but is not guaranteed cash
      available or buying power; those remain empty unless supplied authoritatively.
    - `envelope` / `admserv_limits` — the caps an order is checked against; admserv
      values are broker/Desktop safeguards. Futures risk-point values are weighted
      exposure, not raw contract counts, so they cannot be compared one-for-one with
      the cloud quantity caps.
    - `capital_required` — margin the current futures book ties up.
    - `orders_env` — the order plane (`sandbox`/`paper`/`shadow`/`real`). On a
      simulated plane there is no broker book: `positions_detail` is fill-only
      (`broker_qty` 0) and the admserv/capital fields are omitted — by design.

    Read-only; works in every environment.
    """
    try:
        res = await anyio.to_thread.run_sync(lambda: _client().positions())
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    return {"tag": _guard.tag(), **res}


@mcp.tool()
async def get_history(symbol: str, interval: str = "1m", start: str | None = None,
                      end: str | None = None, limit: int = 500) -> dict[str, Any]:
    """Historical OHLCV bars for a symbol (interval "1s" or "1m").

    `start`/`end` are ISO-8601 or epoch seconds (default: the last hour). Sandbox
    credentials get deterministic, reproducible synthetic days — rerun the same
    range after a code change and get identical bars. Read-only.
    """
    limit = min(max(limit, 1), 5000)
    try:
        res = await anyio.to_thread.run_sync(
            lambda: _client().history(symbol, interval, start, end, limit))
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    return {"tag": _guard.tag(), **res}


@mcp.tool()
async def get_stats(symbol: str, interval: str = "1m",
                    window: float = 3600.0) -> dict[str, Any]:
    """Server-computed digest for a symbol over the last `window` seconds:
    VWAP, spread distribution, volume, realized vol, OHLC. A digest, not a dump —
    drill down with `get_history`. Read-only."""
    try:
        res = await anyio.to_thread.run_sync(
            lambda: _client().stats(symbol, interval, window))
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    return {"tag": _guard.tag(), **res}


@mcp.tool()
async def get_chain(underlying: str, expiry: str,
                    at: str | None = None) -> dict[str, Any]:
    """Options chain snapshot for an `underlying` at an `expiry` month.

    `expiry` is the expiry MONTH as `YYYYMM` (e.g. "202608" for Aug 2026); the
    server derives the third-Friday expiry day itself. Common spellings
    ("2026-08-21", "20260821", "26AUG21") are normalized. Use `list_expiries`
    to discover valid months. Returns per-strike quotes (and IV/greeks as the
    feed carries them), latest or nearest at/before `at`. Read-only."""
    try:
        res = await anyio.to_thread.run_sync(
            lambda: _client().chain(underlying, expiry, at))
    except QJError as e:
        return {"tag": _guard.tag(), "note": f"no chain snapshot available ({e})"}
    return {"tag": _guard.tag(), **res}


@mcp.tool()
async def list_expiries(underlying: str) -> dict[str, Any]:
    """List the upcoming valid option-chain expiry months for an `underlying`, as
    `YYYYMM` strings (e.g. "202608"). Pass one of these as the `expiry` to
    `get_chain` instead of guessing a full date. Read-only."""
    try:
        res = await anyio.to_thread.run_sync(
            lambda: _client().expiries(underlying))
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    return {"tag": _guard.tag(), **res}


@mcp.tool()
async def compare(symbols: list[str], metric: str = "vwap", interval: str = "1m",
                  window: float = 3600.0) -> dict[str, Any]:
    """Compare a digest metric across symbols over the last `window` seconds.

    metric: "vwap" | "volume" | "realized_vol" | "spread_mean". Returns each
    symbol's value, ranked. Read-only.
    """
    valid = {"vwap", "volume", "realized_vol", "spread_mean"}
    if metric not in valid:
        return {"tag": _guard.tag(),
                "error": f"metric must be one of {sorted(valid)}"}

    def _run() -> dict[str, Any]:
        client = _client()
        out: dict[str, Any] = {}
        for sym in symbols[:25]:
            try:
                s = client.stats(sym, interval, window).get("stats", {})
            except QJError as e:
                out[sym] = {"error": str(e)}
                continue
            if metric == "spread_mean":
                out[sym] = (s.get("spread") or {}).get("mean")
            else:
                out[sym] = s.get(metric)
        return out

    try:
        values = await anyio.to_thread.run_sync(_run)
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    ranked = sorted(
        ((k, v) for k, v in values.items() if isinstance(v, (int, float))),
        key=lambda kv: kv[1], reverse=True)
    return {"tag": _guard.tag(), "metric": metric, "window": window,
            "values": values, "ranked": [k for k, _ in ranked]}


# ------------------------------------------------------ experiment tools (tier 3)
_RUNS = None  # lazy RunRegistry (paper runs)


def _runs():
    global _RUNS
    if _RUNS is None:
        from qjtrader import RunRegistry
        _RUNS = RunRegistry()
    return _RUNS


@mcp.tool()
async def run_backtest(symbol: str, auto_tool: str = "scalper",
                       strategy_file: str | None = None, bars: int = 390,
                       interval_s: int = 60, seed: int | None = None,
                       params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Backtest a strategy over deterministic synthetic bars — no network, no risk.

    Runs a built-in `auto_tool` (default "scalper") or a `strategy_file` you wrote,
    and returns the report (fills, positions, PnL). This is how you close your own
    loop: write/tune → backtest → read the result → adjust. Reproducible (same
    `seed` => same market), so you can compare code changes fairly.
    """
    def _run() -> dict[str, Any]:
        import qjtrader
        from qjtrader import make_auto_tool, run_backtest as _bt, synthetic_bars
        strat = (qjtrader.load_strategy(strategy_file) if strategy_file
                 else make_auto_tool(auto_tool))
        p = dict(params or {})
        p.setdefault("symbol", symbol)
        rep = _bt(strat, synthetic_bars(symbol, bars, interval_s=interval_s, seed=seed),
                  params=p)
        rep.pop("equity_curve", None)   # keep the payload compact
        return dict(rep)

    try:
        res = await anyio.to_thread.run_sync(_run)
    except (QJError, KeyError, FileNotFoundError) as e:
        return {"tag": _guard.tag(), "error": str(e)}
    return {"tag": _guard.tag(), **res}


@mcp.tool()
async def set_scenario(name: str, symbol: str | None = None,
                       seconds: float = 30.0) -> dict[str, Any]:
    """Inject a scripted market scenario into the SANDBOX feed and watch a strategy
    cope: "halt", "fast" (fast market), "gap", or "normal". Sandbox only — refused
    elsewhere. Stress-test your own code without waiting for a real fast market."""
    try:
        session = await _server_session()
    except (QJError, OSError) as e:
        return {"tag": _guard.tag(), "refused": True,
                "reason": f"could not confirm the server data environment: {e}"}
    data_env = str(session.get("data_environment") or "unknown")
    data_tag = _guard.tag(data_env)
    if data_env != "sandbox" or _guard.declaration_mismatch(data_env):
        return {"tag": data_tag, "refused": True,
                "reason": "scenarios require a server-confirmed sandbox data environment"}
    try:
        res = await anyio.to_thread.run_sync(
            lambda: _client().set_scenario(name, symbol, seconds))
    except QJError as e:
        return {"tag": data_tag, "error": str(e)}
    return {"tag": data_tag, **res}


@mcp.tool()
async def start_paper_run(symbol: str, auto_tool: str = "scalper",
                          strategy_file: str | None = None, tag: str | None = None,
                          params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start a strategy running unattended against this credential (paper = zero
    risk). Returns a run id; poll `run_status` and stop with `stop_run`. Refused on
    a live credential unless order actions are enabled (the arming flow, §6.4)."""
    ok, reason, env_tag, _session = await _order_guard()
    if not ok:
        return {"tag": env_tag, "refused": True, "reason": reason}

    def _start() -> dict[str, Any]:
        import qjtrader
        from qjtrader import make_auto_tool
        strat = (qjtrader.load_strategy(strategy_file) if strategy_file
                 else make_auto_tool(auto_tool))
        p = dict(params or {})
        p.setdefault("symbol", symbol)
        return _runs().start(_client(), strat, symbols=[symbol], params=p,
                             tag=tag, account="SIM")

    try:
        res = await anyio.to_thread.run_sync(_start)
    except (QJError, KeyError, FileNotFoundError) as e:
        return {"tag": env_tag, "error": str(e)}
    return {"tag": env_tag, **res}


@mcp.tool()
async def run_status(run_id: str | None = None) -> dict[str, Any]:
    """Status of a paper run (or all runs if no id). Read-only."""
    return {"tag": _guard.tag(), **_runs().status(run_id)}


@mcp.tool()
async def stop_run(run_id: str) -> dict[str, Any]:
    """Stop a running strategy (cancels its working orders on exit)."""
    return {"tag": _guard.tag(), **_runs().stop(run_id)}


# --------------------------------------------------------------- meta tools
@mcp.tool()
def access_status() -> dict[str, Any]:
    """Show live products and requests for the browser-signed-in QJ user."""
    try:
        return {"tag": _guard.tag(), **qjtrader.AccessClient().status()}
    except (RuntimeError, OSError) as e:
        return {"tag": _guard.tag(), "status": "login_required", "error": str(e),
                "next": "Run `qjtrader login`; trading keys intentionally do not grant user/admin authority."}


@mcp.tool()
def request_production_access(plane: str = "data", markets: list[str] | None = None,
                              label: str = "", use_case: str = "") -> dict[str, Any]:
    """Request account-level Data or Order Entry access; approval remains human-controlled."""
    try:
        result = qjtrader.AccessClient().request(plane=plane, markets=markets or [],
                                                 label=label, use_case=use_case)
        return {"tag": _guard.tag(), **result,
                "safety": "The request entered human review. No market or order authority changed."}
    except RuntimeError:
        url = qjtrader.production_access_url(plane=plane, markets=markets or (), label=label)
    except (ValueError, OSError) as e:
        return {"tag": _guard.tag(), "error": str(e)}
    return {
        "tag": _guard.tag(),
        "status": "human_action_required",
        "url": url,
        "safety": "Sign in to Gateway, review the least-privilege scope, and submit it. A QJ admin must approve and provision production access separately.",
    }


@mcp.tool()
def request_limit_change(product: str, client_id: str = "", max_qty: int | None = None,
                         max_open: int | None = None, msgs_per_sec: float | None = None,
                         daily_qty: int | None = None, reason: str = "") -> dict[str, Any]:
    """Request a production cloud API limit change; broker/desktop risk is unchanged."""
    try:
        result = qjtrader.AccessClient().request_limit_change(
            product=product, client_id=client_id, max_qty=max_qty, max_open=max_open,
            msgs_per_sec=msgs_per_sec, daily_qty=daily_qty, reason=reason)
        return {"tag": _guard.tag(), **result}
    except (RuntimeError, ValueError, OSError) as e:
        return {"tag": _guard.tag(), "error": str(e),
                "next": "Run `qjtrader login` to submit this human-authorized request."}


@mcp.tool()
async def search_universe(query: str = "", limit: int = 50) -> dict[str, Any]:
    """Search instruments visible to this credential and return capability-aware descriptions."""
    try:
        result = await anyio.to_thread.run_sync(lambda: _client().search_universe(query, limit))
    except (QJError, OSError) as e:
        return {"tag": _guard.tag(), "error": str(e)}
    return {"tag": _guard.tag(str(result.get("orders_environment") or "unknown")), **result}


@mcp.tool()
async def describe_instrument(symbol: str) -> dict[str, Any]:
    """Explain one QJ symbol in the context of this credential's current authority."""
    try:
        result = await anyio.to_thread.run_sync(lambda: _client().describe_instrument(symbol))
    except (QJError, OSError) as e:
        return {"tag": _guard.tag(), "error": str(e)}
    return {"tag": _guard.tag(str(result.get("orders_environment") or "unknown")), **result}


@mcp.tool()
def explain_symbol(symbol: str) -> dict[str, Any]:
    """Explain a QJ symbol (or how to build one): asset-class prefix, root, and
    venue suffix, plus consolidated-vs-venue semantics. Use this before
    subscribing or ordering if you are unsure how to name an instrument."""
    return {"tag": _guard.tag(), **_explain_symbol(symbol)}


@mcp.tool()
async def session_info() -> dict[str, Any]:
    """Report authoritative environments and this key's active Data products,
    Order Entry products and trading accounts. Also reports whether live order
    actions are enabled. Call this first."""
    declared = _guard.environment()
    info: dict[str, Any] = {
        "declared_environment": declared,
        "allow_live_flag": _guard.allow_live(),
        "max_qty": _guard.max_qty(),
        "data_host": os.environ.get("QJ_DATA_HOST", "data-feed.qjtrader.ai"),
        "orders_host": os.environ.get("QJ_ORDERS_HOST", "orders.qjtrader.ai"),
    }
    # Server truth is mandatory for mutation safety, but session_info remains
    # useful when credentials or a service are misconfigured.
    try:
        client = _client()
    except QJError as e:
        info["credential"] = f"not configured: {e}"
        return info
    try:
        session = await anyio.to_thread.run_sync(client.session_info)
        info.update(session)
        orders_env = str(session.get("orders_environment") or "unknown")
        allowed, reason = _guard.mutations_allowed(orders_env)
        info["tag"] = _guard.tag(orders_env)
        info["order_actions_allowed"] = allowed
        info["order_actions_note"] = reason
        info["environment_mismatch"] = _guard.declaration_mismatch(orders_env)
    except (QJError, OSError) as e:
        info["tag"] = _guard.tag()
        info["order_actions_allowed"] = False
        info["order_actions_note"] = f"server environment unavailable; mutations refused: {e}"
    return info


def _auth_probe(client: qjtrader.Client) -> str | None:
    with client.market_data() as md:
        return md.user


def main() -> None:
    """Entry point for the ``qjtrader-mcp`` console script (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
