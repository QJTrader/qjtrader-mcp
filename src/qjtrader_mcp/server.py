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
        "are namespaced (e.g. CA:RY, CA:RY.PT, MX:CRAU26) — call `explain_symbol` "
        "if unsure. Prefer digests (`get_stats`) over raw dumps. Every result "
        "begins with an environment tag."
    ),
)


# --------------------------------------------------------------------- helpers
def _client() -> qjtrader.Client:
    """Build a Client from the environment (raises QJError if creds are missing)."""
    return qjtrader.Client()


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
async def get_quote(symbols: list[str], seconds: float = 4.0) -> dict[str, Any]:
    """Get the current top-of-book (best bid/ask) for one or more symbols.

    Symbols are namespaced, e.g. ["CA:RY", "CA:RY.PT", "MX:CRAU26"]. This opens a
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
    """Get the Level-2 order book (price/size by level) for a single symbol.

    On consolidated equity symbols (e.g. "CA:RY") each level is tagged with its
    venue; use a venue-scoped symbol (e.g. "CA:RY.PT") for one exchange only.
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
                    account: str, tif: str) -> dict[str, Any]:
    with _client().orders() as oe:
        user = oe.user
        result = oe.order_and_wait(sym=sym, side=side, qty=qty, price=price,
                                   account=account, tif=tif)
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
                      account: str = "SIM", tif: str = "day") -> dict[str, Any]:
    """Submit a limit order and wait for it to reach a terminal state.

    side: "buy" | "sell".  tif: "day" | "ioc" | "fok".  Returns the final
    execution/order message (a fill, cancel, reject, or the resting order if it
    is still open after a short wait).

    SAFETY: runs against a SANDBOX credential by default (simulated fills only).
    A live credential is refused unless QJ_MCP_ALLOW_LIVE=1 is set. Quantity is
    capped client-side by QJ_MCP_MAX_QTY (default 25).
    """
    ok, reason = _guard.mutations_allowed()
    if not ok:
        return {"tag": _guard.tag(), "refused": True, "reason": reason}
    if side not in ("buy", "sell"):
        return {"tag": _guard.tag(), "error": "side must be 'buy' or 'sell'"}
    if tif not in ("day", "ioc", "fok"):
        return {"tag": _guard.tag(), "error": "tif must be 'day', 'ioc', or 'fok'"}
    if qty < 1:
        return {"tag": _guard.tag(), "error": "qty must be >= 1"}
    cap = _guard.max_qty()
    if qty > cap:
        return {"tag": _guard.tag(), "refused": True,
                "reason": f"qty {qty} exceeds the client-side cap of {cap} "
                          f"(raise QJ_MCP_MAX_QTY to allow larger orders)"}
    if price <= 0:
        return {"tag": _guard.tag(), "error": "price must be > 0"}
    try:
        res = await anyio.to_thread.run_sync(
            _blocking_place, sym, side, qty, price, account, tif)
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    res["tag"] = _guard.tag()
    res["allowed_because"] = reason
    return res


@mcp.tool()
async def cancel_order(orig_cid: str) -> dict[str, Any]:
    """Cancel a working order by its client order id (cid)."""
    ok, reason = _guard.mutations_allowed()
    if not ok:
        return {"tag": _guard.tag(), "refused": True, "reason": reason}
    try:
        res = await anyio.to_thread.run_sync(_blocking_cancel, orig_cid)
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    res["tag"] = _guard.tag()
    return res


@mcp.tool()
async def replace_order(orig_cid: str, qty: int | None = None,
                        price: float | None = None) -> dict[str, Any]:
    """Amend a working order's quantity and/or price by its client order id."""
    ok, reason = _guard.mutations_allowed()
    if not ok:
        return {"tag": _guard.tag(), "refused": True, "reason": reason}
    if qty is None and price is None:
        return {"tag": _guard.tag(), "error": "provide qty and/or price to change"}
    if qty is not None:
        if qty < 1:
            return {"tag": _guard.tag(), "error": "qty must be >= 1"}
        cap = _guard.max_qty()
        if qty > cap:
            return {"tag": _guard.tag(), "refused": True,
                    "reason": f"qty {qty} exceeds the client-side cap of {cap}"}
    if price is not None and price <= 0:
        return {"tag": _guard.tag(), "error": "price must be > 0"}
    try:
        res = await anyio.to_thread.run_sync(_blocking_replace, orig_cid, qty, price)
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    res["tag"] = _guard.tag()
    return res


@mcp.tool()
async def cancel_all() -> dict[str, Any]:
    """Cancel every working order on this credential (the kill switch)."""
    ok, reason = _guard.mutations_allowed()
    if not ok:
        return {"tag": _guard.tag(), "refused": True, "reason": reason}
    try:
        res = await anyio.to_thread.run_sync(_blocking_cancel_all)
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    res["tag"] = _guard.tag()
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
    - `envelope` / `admserv_limits` — the caps an order is checked against; admserv
      limits are the hard broker-sourced floor/ceiling (an order projecting past them
      is rejected before it transmits).
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
    if _guard.environment() != "sandbox":
        return {"tag": _guard.tag(), "refused": True,
                "reason": "scenarios are sandbox-only"}
    try:
        res = await anyio.to_thread.run_sync(
            lambda: _client().set_scenario(name, symbol, seconds))
    except QJError as e:
        return {"tag": _guard.tag(), "error": str(e)}
    return {"tag": _guard.tag(), **res}


@mcp.tool()
async def start_paper_run(symbol: str, auto_tool: str = "scalper",
                          strategy_file: str | None = None, tag: str | None = None,
                          params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start a strategy running unattended against this credential (paper = zero
    risk). Returns a run id; poll `run_status` and stop with `stop_run`. Refused on
    a live credential unless order actions are enabled (the arming flow, §6.4)."""
    ok, reason = _guard.mutations_allowed()
    if not ok:
        return {"tag": _guard.tag(), "refused": True, "reason": reason}

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
        return {"tag": _guard.tag(), "error": str(e)}
    return {"tag": _guard.tag(), **res}


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
def explain_symbol(symbol: str) -> dict[str, Any]:
    """Explain a QJ symbol (or how to build one): asset-class prefix, root, and
    venue suffix, plus consolidated-vs-venue semantics. Use this before
    subscribing or ordering if you are unsure how to name an instrument."""
    return {"tag": _guard.tag(), **_explain_symbol(symbol)}


@mcp.tool()
async def session_info() -> dict[str, Any]:
    """Report the current environment, whether live order actions are enabled,
    the endpoints in use, and the authenticated principal. Call this first."""
    env = _guard.environment()
    allowed, reason = _guard.mutations_allowed()
    info: dict[str, Any] = {
        "tag": _guard.tag(),
        "environment": env,
        "order_actions_allowed": allowed,
        "order_actions_note": reason,
        "allow_live_flag": _guard.allow_live(),
        "max_qty": _guard.max_qty(),
        "data_host": os.environ.get("QJ_DATA_HOST", "data-feed.qjtrader.ai"),
        "orders_host": os.environ.get("QJ_ORDERS_HOST", "orders.qjtrader.ai"),
    }
    # Best-effort auth to confirm the credential works and report the principal.
    try:
        client = _client()
    except QJError as e:
        info["credential"] = f"not configured: {e}"
        return info
    try:
        info["authenticated_user"] = await anyio.to_thread.run_sync(
            lambda: _auth_probe(client))
    except QJError as e:
        info["authenticated_user"] = f"auth failed: {e}"
    return info


def _auth_probe(client: qjtrader.Client) -> str | None:
    with client.market_data() as md:
        return md.user


def main() -> None:
    """Entry point for the ``qjtrader-mcp`` console script (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
