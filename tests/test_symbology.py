from qjtrader_mcp import _symbology


def test_namespaced_consolidated_equity():
    r = _symbology.explain("CA:RY")
    assert r["namespace"] == "CA"
    assert r["root"] == "RY"
    assert r["security_type"].startswith("stock")
    assert r["venue"] is None


def test_venue_scoped_equity():
    r = _symbology.explain("CA:RY.PT")
    assert r["root"] == "RY"
    assert r["venue"] == "PT"
    assert "PURE" in r["venue_meaning"]
    assert r["consolidated"] is False


def test_consolidated_suffix():
    r = _symbology.explain("RY.CA")
    assert r["venue"] == "CA"
    assert r["consolidated"] is True


def test_future_prefix():
    r = _symbology.explain("/CGB Z26.ME")
    assert r["security_type"] == "future"
    assert r["root"] == "CGB Z26"
    assert r["venue"] == "ME"


def test_fx_prefix():
    r = _symbology.explain("$EURUSD.FX")
    assert r["security_type"] == "foreign exchange"
    assert r["root"] == "EURUSD"


def test_mx_namespace_future():
    r = _symbology.explain("MX:CRAU26")
    assert r["namespace"] == "MX"
    assert r["root"] == "CRAU26"


def test_us_treasury_future_prefix_and_names():
    expected = {
        "US:@USU26": ("US", "30-Year U.S. Treasury Bond future"),
        "US:@TYU26": ("TY", "10-Year U.S. Treasury Note future"),
        "US:@FVU26": ("FV", "5-Year U.S. Treasury Note future"),
    }
    for symbol, (root, name) in expected.items():
        result = _symbology.explain(symbol)
        assert result["security_type"] == "future"
        assert result["contract_root"] == root
        assert result["contract_name"] == name
        assert result["contract_month_code"] == "U"
        assert result["contract_year"] == 2026


def test_empty_symbol_gives_help():
    r = _symbology.explain("")
    assert "help" in r
    assert "namespaces" in r
