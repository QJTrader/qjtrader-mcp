# Changelog

## 0.4.5

- Added `request_limit_change` for human-authorized, product-specific cloud API safeguard requests.
- Requires `qjtrader>=0.5.7`; broker/Desktop limits remain a distinct read-only backstop.

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
