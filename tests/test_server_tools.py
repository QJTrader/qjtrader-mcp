"""Server wiring — skipped if the `mcp` package (or SDK) isn't installed."""
import pytest

pytest.importorskip("mcp")
pytest.importorskip("qjtrader")


@pytest.mark.anyio
async def test_all_tools_registered():
    from qjtrader_mcp import server

    names = {t.name for t in await server.mcp.list_tools()}
    assert {
        "session_info", "market_availability", "get_quote", "get_depth", "watch", "list_orders",
        "request_production_access", "request_limit_change",
        "get_feed_limits", "set_feed_limits",
        "place_order", "cancel_order", "replace_order", "cancel_all",
        "explain_symbol",
        # v2 research/analytics tools (plan §9.2)
        "read_events", "get_history", "get_stats", "get_chain", "list_expiries",
        "compare", "get_recording_status", "keep_recording", "stop_recording",
        # v2 tier-3 experiment tools (plan §9.2 / §10.4)
        "run_backtest", "set_scenario", "start_paper_run", "run_status", "stop_run",
    } <= names


@pytest.mark.anyio
async def test_market_availability_is_offline_and_describes_us_limits():
    from qjtrader_mcp import server
    res = await server.market_availability()
    assert res["markets"]["US"]["limitations"]
    assert "order_bids" in res["data_shapes"]["equity_book"]
    assert "provenance" in res["observation_contract"]
    assert "never falls back" in res["observation_contract"]["history"]
    assert "US:@TYU26" in " ".join(res["markets"]["US"]["verified"])
    assert "tag" in res


def test_production_request_is_a_human_handoff_not_a_promotion():
    from qjtrader_mcp import server
    res = server.request_production_access("data", ["ca-equities"], "M3alpha CSU shadow")
    assert res["status"] == "human_action_required"
    assert "gateway.qjtrader.ai/credentials" in res["url"]
    assert "secret" not in res["url"].lower()


@pytest.mark.anyio
async def test_run_backtest_local(monkeypatch):
    from qjtrader_mcp import server
    res = await server.run_backtest("MX:CRAU26", auto_tool="scalper", bars=100, seed=3,
                                    params={"edge": 0.01, "target": 0.01})
    assert "total_pnl" in res and res["bars"] == 100 and "tag" in res


@pytest.mark.anyio
async def test_set_scenario_refused_outside_sandbox(monkeypatch):
    monkeypatch.setenv("QJ_ENV", "live")
    from qjtrader_mcp import server
    res = await server.set_scenario("fast")
    assert res["refused"] is True


@pytest.mark.anyio
async def test_run_status_empty(monkeypatch):
    from qjtrader_mcp import server
    res = await server.run_status()
    assert "runs" in res and "tag" in res


class _FakeClient:
    def feed_limits(self, user=None):
        return {"user": user or "admin", "limits": {"max_symbols": 250,
                                                       "max_connections": 3}}

    def set_feed_limits(self, user=None, **limits):
        return {"user": user or "admin", "limits": {
            key: value for key, value in limits.items() if value is not None}}

    def events(self, since, limit, cursor=None):
        return {"events": [{"cid": "a", "status": "filled"}], "cursor": "t9"}

    def executions(self, since, limit, cursor=None):
        return {"executions": [{"execution_id": "E1", "last_qty": 2}],
                "next_cursor": "opaque"}

    def history(self, sym, interval, start, end, limit):
        return {"symbol": sym, "interval": interval, "source": "recorded",
                "availability": "available", "bars": [{"close": 1.0}]}

    def stats(self, sym, interval, window):
        vwap = {"A": 10.0, "B": 5.0}.get(sym, 1.0)
        return {"symbol": sym, "stats": {"vwap": vwap, "volume": 100,
                                         "spread": {"mean": 0.2}}}

    def chain(self, underlying, expiry, at):
        from qjtrader.errors import QJError
        raise QJError("no chain snapshot")

    def expiries(self, underlying):
        return {"underlying": underlying, "expiries": ["202608", "202609", "202610"]}

    def recording_status(self, symbol):
        return {"symbol": symbol, "mode": "observed", "pinned": False}

    def pin_recording(self, symbol):
        return {"symbol": symbol, "mode": "continuous", "pinned": True}

    def unpin_recording(self, symbol):
        return {"symbol": symbol, "mode": "ready", "pinned": False}


def test_feed_admin_limit_tools_are_explicit_and_scoped(monkeypatch):
    from qjtrader_mcp import server
    monkeypatch.setattr(server, "_client", lambda: _FakeClient())
    assert server.get_feed_limits("strategy-client")["limits"]["max_symbols"] == 250
    changed = server.set_feed_limits("strategy-client", max_symbols=300)
    assert changed["limits"] == {"max_symbols": 300}


@pytest.mark.anyio
async def test_read_events_and_history(monkeypatch):
    from qjtrader_mcp import server
    monkeypatch.setattr(server, "_client", lambda: _FakeClient())

    ev = await server.read_events()
    assert ev["events"][0]["cid"] == "a" and ev["cursor"] == "t9" and "tag" in ev
    trades = await server.list_trades()
    assert trades["executions"][0]["execution_id"] == "E1"
    h = await server.get_history("MX:CGBU26", interval="1m")
    assert h["symbol"] == "MX:CGBU26" and h["bars"][0]["close"] == 1.0
    assert h["source"] == "recorded"

    status = await server.get_recording_status("MX:CGBU26")
    assert status["mode"] == "observed"
    assert (await server.keep_recording("MX:CGBU26"))["pinned"] is True
    assert (await server.stop_recording("MX:CGBU26"))["pinned"] is False


@pytest.mark.anyio
async def test_compare_ranks_symbols(monkeypatch):
    from qjtrader_mcp import server
    monkeypatch.setattr(server, "_client", lambda: _FakeClient())

    res = await server.compare(["A", "B"], metric="vwap")
    assert res["ranked"] == ["A", "B"]              # A(10) > B(5)
    assert res["values"] == {"A": 10.0, "B": 5.0}
    bad = await server.compare(["A"], metric="bogus")
    assert "error" in bad


@pytest.mark.anyio
async def test_get_chain_missing_returns_note(monkeypatch):
    from qjtrader_mcp import server
    monkeypatch.setattr(server, "_client", lambda: _FakeClient())

    res = await server.get_chain("MX:RY", "202609")
    assert "note" in res and "no chain snapshot" in res["note"]


@pytest.mark.anyio
async def test_list_expiries(monkeypatch):
    from qjtrader_mcp import server
    monkeypatch.setattr(server, "_client", lambda: _FakeClient())

    res = await server.list_expiries("MX:RY")
    assert res["expiries"] == ["202608", "202609", "202610"] and "tag" in res


@pytest.mark.anyio
async def test_place_order_refused_in_unknown_env(monkeypatch):
    monkeypatch.delenv("QJ_ENV", raising=False)
    monkeypatch.delenv("QJ_MCP_ALLOW_LIVE", raising=False)
    from qjtrader_mcp import server

    res = await server.place_order(sym="CA:RY", side="buy", qty=1, price=10.0)
    assert res["refused"] is True


@pytest.mark.anyio
async def test_place_order_qty_cap(monkeypatch):
    monkeypatch.setenv("QJ_ENV", "sandbox")
    monkeypatch.setenv("QJ_MCP_MAX_QTY", "5")
    from qjtrader_mcp import server

    res = await server.place_order(sym="CA:RY", side="buy", qty=999, price=10.0)
    assert res["refused"] is True
    assert "cap" in res["reason"]


@pytest.fixture
def anyio_backend():
    return "asyncio"
