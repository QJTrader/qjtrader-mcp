# qjtrader-mcp

> For Claude web, mobile, or another hosted assistant, prefer the hosted QJTrader OAuth connector offered inside [QJ Gateway](https://gateway.qjtrader.ai). It provides delegated per-user access without putting `QJ_CLIENT_SECRET` in chat. This package is the local/stdio implementation for Claude Code and controlled local runtimes.

[![PyPI version](https://img.shields.io/pypi/v/qjtrader-mcp)](https://pypi.org/project/qjtrader-mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/qjtrader-mcp)](https://pypi.org/project/qjtrader-mcp/)
[![License](https://img.shields.io/pypi/l/qjtrader-mcp)](https://github.com/QJTrader/qjtrader-mcp/blob/main/LICENSE)

**Model Context Protocol server for the [QJ Trader](https://qjtrader.ai) AI Trading APIs.**
Point your LLM at your QJ credential and it can watch live Canadian and selected US market data and place
**simulated** orders — no code, no manual API testing.

Built on the official [`qjtrader`](https://github.com/QJTrader/qjtrader-python) Python SDK. Talk to
it from Claude Code, Claude Desktop, or any MCP-capable client:

> *"Check market availability, then compare CA:RY, MX:CRAU26, and US:@ESU26 in the sandbox.
> Show the books and explain which production permissions would be separate."*

> **Verifiable releases.** `qjtrader-mcp` is published straight from this repository via [PyPI Trusted
> Publishing](https://docs.pypi.org/trusted-publishers/) with signed [PEP 740](https://peps.python.org/pep-0740/)
> provenance — no manual uploads, no stored tokens. Before you let an agent install it, you (or the agent)
> can confirm each release was built by `QJTrader/qjtrader-mcp` from the **Provenance** section on
> [PyPI](https://pypi.org/project/qjtrader-mcp/). See [SECURITY.md](SECURITY.md).

## Safety model — AI trades simulated by default

Order-mutating tools (`place_order`, `cancel_order`, `replace_order`, `cancel_all`) use the
Gateway's authenticated session response as the authority. Sandbox, paper, and shadow credentials
cannot be mistaken for live credentials by a stale local setting. Canary and live credentials are
refused unless you explicitly opt in.

| Server-declared order environment | Read tools (quotes/depth/status) | Order tools |
|---|---|---|
| `sandbox` | ✅ | ✅ simulated |
| `paper` / `shadow` | ✅ | ✅ non-exchange mutation path |
| `canary` / `live` | ✅ | ⛔ unless `QJ_MCP_ALLOW_LIVE=1` |
| unavailable or mismatched | ✅ where possible | ⛔ fail closed |

`QJ_ENV` is now an optional expected-environment assertion, not the source of truth. If it disagrees
with the Gateway, mutations stop with an explanation. Every tool result includes an environment tag,
and order quantity is capped client-side by `QJ_MCP_MAX_QTY` (default 25).

## Install

Get a free sandbox credential (no approval) at [gateway.qjtrader.ai](https://gateway.qjtrader.ai).

The zero-install path is:

```bash
uvx qjtrader-mcp        # or: pipx run qjtrader-mcp
```

For local development against the SDK checkout:

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
| `market_availability` | read, offline | Product-by-product sandbox vs production data/order support, verified examples, and known gaps. **Call before assuming a product has depth or order authority.** |
| `access_status` | human account read | Shows products and requests after `qjtrader login`; machine trading keys do not grant this authority. |
| `request_production_access` | human request | Submits through the signed-in user API, or returns a safe browser handoff when login is absent. It cannot approve or promote itself. |
| `search_universe` | read | Search current symbol forms and capability metadata by market or text |
| `describe_instrument` | read | Describe one symbol, its product identity, venue scope, and available operations |

`market_availability` also returns an `observation_contract` and source-aware
`data_shapes`. Agents must preserve `null` or silence as "unquoted now," treat
`orders`/`venues` on depth levels as optional, and never infer Greeks, NAV,
contract terms, depth, or order authority from the security type alone. Canadian
`get_depth` results include rounded Top5, odd/special-lot views, entitled
`order_bids`/`order_asks` QJ/TMX TL2 rows, and source timing/provenance.
| `get_quote` | read | Top-of-book (best bid/ask) for one or more symbols |
| `get_depth` | read | Level-2 order book for a symbol (venue-tagged on consolidated books) |
| `watch` | read | Sample the live stream for a bounded window; returns a digest + last messages |
| `list_orders` | read | Open orders + session state |
| `get_positions` | read | Broker-truth positions (broker + fill = total), risk envelope + admserv hard caps, capital-required, order plane |
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
| `QJ_ENV` | Optional expected environment; mismatch refuses mutations | unset |
| `QJ_MCP_ALLOW_LIVE` | set `1` to authorize live order actions | off |
| `QJ_MCP_MAX_QTY` | client-side max order quantity | `25` |
| `QJ_DATA_HOST` / `QJ_ORDERS_HOST` | endpoint overrides | public QJ hosts |
| `QJ_CA_FILE` | pin a CA/cert (pilot order endpoint) | none |

## License

Apache-2.0. See [LICENSE](LICENSE).
