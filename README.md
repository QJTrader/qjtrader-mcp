# qjtrader-mcp

**Model Context Protocol server for the [QJ Trader](https://qjtrader.ai) AI Trading APIs.**
Point your LLM at your QJ credential and it can watch live Canadian market data and place
**simulated** orders — no code, no manual API testing.

Built on the official [`qjtrader`](https://github.com/QJTrader/qjtrader-python) Python SDK. Talk to
it from Claude Code, Claude Desktop, or any MCP-capable client:

> *"Subscribe to CA:RY and MX:CRAU26, show me the books, then buy 1 CRAU26 at 97 in the sandbox
> and tell me the fill."*

## Safety model — AI trades simulated by default

Order-mutating tools (`place_order`, `cancel_order`, `replace_order`, `cancel_all`) run against a
**sandbox** credential by default and return simulated fills. A **live** credential is refused
unless you explicitly opt in. The server never sniffs this off the wire (the protocol doesn't
expose it) — you declare it:

| `QJ_ENV` | Read tools (quotes/depth/status) | Order tools |
|---|---|---|
| `sandbox` | ✅ | ✅ simulated |
| `live` | ✅ | ⛔ unless `QJ_MCP_ALLOW_LIVE=1` |
| *(unset)* | ✅ | ⛔ (fail-safe: unknown is treated as live) |

Every tool result is prefixed with an environment tag (`[SANDBOX]` / `[LIVE — REAL MONEY]` /
`[ENV UNKNOWN]`), and order quantity is capped client-side by `QJ_MCP_MAX_QTY` (default 25).

## Install

Get a free sandbox credential (no approval) at [console.qjtrader.ai](https://console.qjtrader.ai).

Once published to PyPI, the zero-install path is:

```bash
uvx qjtrader-mcp        # or: pipx run qjtrader-mcp
```

Until then (or for local development against the SDK checkout):

```bash
# from the qjtrader-mcp/ directory, with the qjtrader-python sibling checked out:
uv sync && uv run qjtrader-mcp          # uv resolves qjtrader from ../qjtrader-python
# — or with pip —
pip install -e ../qjtrader-python -e .
qjtrader-mcp
```

## Configure your client

### Claude Code

```bash
claude mcp add qjtrader -- uvx qjtrader-mcp
# then set the credential + environment for the server:
claude mcp add qjtrader \
  -e QJ_CLIENT_ID=your-client-id \
  -e QJ_CLIENT_SECRET=your-client-secret \
  -e QJ_ENV=sandbox \
  -- uvx qjtrader-mcp
```

### Claude Desktop / generic stdio

Add to your MCP config (`claude_desktop_config.json` or equivalent):

```json
{
  "mcpServers": {
    "qjtrader": {
      "command": "uvx",
      "args": ["qjtrader-mcp"],
      "env": {
        "QJ_CLIENT_ID": "your-client-id",
        "QJ_CLIENT_SECRET": "your-client-secret",
        "QJ_ENV": "sandbox"
      }
    }
  }
}
```

The console's "Connect your AI" panel generates these blocks pre-filled, including
`QJ_ENV=sandbox`.

## Tools

| Tool | Kind | Description |
|---|---|---|
| `session_info` | read | Environment, whether order actions are allowed, endpoints, authenticated user. **Call first.** |
| `get_quote` | read | Top-of-book (best bid/ask) for one or more symbols |
| `get_depth` | read | Level-2 order book for a symbol (venue-tagged on consolidated books) |
| `watch` | read | Sample the live stream for a bounded window; returns a digest + last messages |
| `list_orders` | read | Open orders + session state |
| `place_order` | write | Submit a limit order and wait for a terminal state |
| `cancel_order` | write | Cancel a working order by `cid` |
| `replace_order` | write | Amend a working order's qty/price |
| `cancel_all` | write | Cancel every working order (kill switch) |
| `explain_symbol` | util | Parse/explain a symbol (prefix + root + venue), offline |
| `read_events` | read | Order journal — cross-order event history; post-trade analysis & strategy debugging |
| `get_history` | read | Historical OHLCV bars (1s/1m); sandbox = deterministic synthetic days |
| `get_stats` | read | Server digest for a symbol: VWAP, spread, volume, realized vol (a digest, not a dump) |
| `get_chain` | read | Options chain snapshot for an underlying/expiry (latest or historical) |
| `compare` | read | Rank a digest metric (vwap/volume/realized_vol/spread_mean) across symbols |

The `read_*`/`get_*` research tools make the LLM a **quant developer**: analyse the
market and debug the strategy it wrote, without touching the production order path.

## Configuration reference

| Env var | Purpose | Default |
|---|---|---|
| `QJ_CLIENT_ID` / `QJ_CLIENT_SECRET` | credential | — (required) |
| `QJ_ENV` | `sandbox` \| `live` — declares the environment | unset → treated as live |
| `QJ_MCP_ALLOW_LIVE` | set `1` to authorize live order actions | off |
| `QJ_MCP_MAX_QTY` | client-side max order quantity | `25` |
| `QJ_DATA_HOST` / `QJ_ORDERS_HOST` | endpoint overrides | public QJ hosts |
| `QJ_CA_FILE` | pin a CA/cert (pilot order endpoint) | none |

## License

Apache-2.0. See [LICENSE](LICENSE).
