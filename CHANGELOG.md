# Changelog

## 0.4.12

- Added `list_trades` as the execution-level counterpart to working orders and positions.
- Added opaque cursor support to `read_events` so equal-timestamp events are not skipped.
- Requires `qjtrader>=0.5.16` for the dedicated execution projection.

## 0.4.11

- Added provider-neutral US Treasury futures explanations and verified availability for
  `US:@USU26`, `US:@TYU26`, and `US:@FVU26`.
- Corrected the cloud `@` marker so `explain_symbol` classifies selected US futures as
  futures instead of stock-like instruments.

## 0.4.9

- Clarified the positions-and-risk tool contract: weighted Desktop RiskPoints are monitoring
  context, not raw share or contract caps; Gateway and directly comparable route checks remain
  cloud pre-trade controls, with full broker/Desktop safeguards downstream.

## 0.4.8

- Added agent-readable market-memory status and safe keep/stop recording tools.
- Recording pins create no order authority: they only keep an entitled production market-data
  watch alive and return to automatic bar capture when removed.

## 0.4.7

- `get_history` and `get_stats` now tell agents to branch on explicit synthetic, recorded, or
  unavailable provenance. Missing production capture is an empty honest result, never generated data.
- Requires `qjtrader>=0.5.9` for the matching live-sampled availability contract.

## 0.4.5

- Added `request_limit_change` for human-authorized, product-specific cloud API safeguard requests.
- Requires `qjtrader>=0.5.7`; directly comparable route size/open-order fields remain cloud
  prechecks, while weighted broker/Desktop RiskPoints are monitoring context and downstream
  legacy safeguards remain independent.

## 0.4.4

- `get_depth` now returns price-aggregated, round/odd/special-lot, and QJ/TMX
  order-level TL2 views together with feed provenance.
- Requires `qjtrader>=0.5.6` for the matching availability contract.

## 0.4.2

- Added payload-shape and observation-honesty guidance to `market_availability`
  and `describe_instrument`, including sparse/unquoted states and optional depth fields.

## 0.4.1

- Requires `qjtrader>=0.5.1`, allowing server-authoritative mutation checks to work correctly for
  an orders-only credential while still failing closed when order authority itself is unavailable.

## 0.4.0

- Mutation guards now trust the Gateway's authenticated order environment and authority version,
  not a local `QJ_ENV` declaration. Missing authority or a declaration mismatch fails closed.
- Added `search_universe` and `describe_instrument` tools for agent-readable product discovery.
- Local quantity and input errors remain immediate; any valid mutation still requires confirmed
  server authority, with explicit opt-in for canary and live credentials.

## 0.3.4

- Requires `qjtrader>=0.4.3` and exposes its product-by-product sandbox versus production
  availability contract to agents.
- Cross-market prompts and symbol help now cover `CA:`, `MX:`, and `US:` without implying that
  market data, Level 2, accounts, routes, and order authority are interchangeable.
- Installation guidance now reflects the already-published PyPI package while preserving the
  editable sibling-checkout workflow for contributors.
