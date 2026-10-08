import sys
import types

import pytest

from app.market_data.breeze_provider import (
    BreezeProvider,
    BreezeSessionError,
    _parse_option_row,
    _unwrap,
)

import datetime as dt


class _FakeBreezeClient:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.session_calls = []
        self.option_chain_calls = []

    def generate_session(self, api_secret=None, session_token=None):
        self.session_calls.append((api_secret, session_token))

    def get_quotes(self, **kwargs):
        return {"Success": [{"ltp": "24500.5", "lot_size": "75"}], "Error": None}

    def get_option_chain_quotes(self, **kwargs):
        self.option_chain_calls.append(kwargs)
        right = kwargs.get("right")
        if right == "Call":
            return {"Success": [{"strike_price": "24500", "right": "Call", "best_bid_price": "100",
                                  "best_offer_price": "102", "ltp": "101", "open_interest": "1000",
                                  "total_quantity_traded": "500", "best_bid_quantity": "10",
                                  "best_offer_quantity": "12", "expiry_date": "29-Jan-2026"}], "Error": None}
        return {"Success": [{"strike_price": "24500", "right": "Put", "best_bid_price": "90",
                              "best_offer_price": "93", "ltp": "91", "open_interest": "800",
                              "total_quantity_traded": "400", "best_bid_quantity": "8",
                              "best_offer_quantity": "9", "expiry_date": "29-Jan-2026"}], "Error": None}

    def get_historical_data_v2(self, **kwargs):
        return {"Success": [{"datetime": "2026-01-01", "open": "100", "high": "110", "low": "95",
                              "close": "105", "volume": "1000"}], "Error": None}


@pytest.fixture
def fake_breeze_module(monkeypatch):
    fake_module = types.ModuleType("breeze_connect")
    fake_module.BreezeConnect = _FakeBreezeClient
    monkeypatch.setitem(sys.modules, "breeze_connect", fake_module)
    return fake_module


def _make_provider(fake_breeze_module):
    return BreezeProvider(
        api_key="key", api_secret="secret", session_token="token",
        symbol_map={"BANKNIFTY": "CNXBAN"}, exchange_code="NFO", cash_exchange_code="NSE",
    )


def test_missing_credentials_raises_session_error():
    with pytest.raises(BreezeSessionError):
        BreezeProvider(api_key="", api_secret="secret", session_token="token", symbol_map={})


def test_missing_sdk_raises_session_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "breeze_connect", None)
    with pytest.raises(BreezeSessionError):
        BreezeProvider(api_key="key", api_secret="secret", session_token="token", symbol_map={})


def test_login_failure_raises_session_error(monkeypatch):
    fake_module = types.ModuleType("breeze_connect")

    class _FailingClient(_FakeBreezeClient):
        def generate_session(self, api_secret=None, session_token=None):
            raise RuntimeError("bad session token")

    fake_module.BreezeConnect = _FailingClient
    monkeypatch.setitem(sys.modules, "breeze_connect", fake_module)
    with pytest.raises(BreezeSessionError):
        BreezeProvider(api_key="key", api_secret="secret", session_token="token", symbol_map={})


def test_stock_code_uses_symbol_map(fake_breeze_module):
    provider = _make_provider(fake_breeze_module)
    assert provider._stock_code("BANKNIFTY") == "CNXBAN"
    assert provider._stock_code("NIFTY") == "NIFTY"


@pytest.mark.asyncio
async def test_get_underlying_quote(fake_breeze_module):
    provider = _make_provider(fake_breeze_module)
    quote = await provider.get_underlying_quote("NIFTY")
    assert quote.spot_price == 24500.5
    assert quote.is_demo is False


@pytest.mark.asyncio
async def test_get_option_chain_merges_calls_and_puts(fake_breeze_module):
    provider = _make_provider(fake_breeze_module)
    chain = await provider.get_option_chain("NIFTY", dt.date(2026, 1, 29))
    assert len(chain) == 2
    assert {o.option_type for o in chain} == {"CALL", "PUT"}
    for o in chain:
        assert o.source == "BREEZE"
        assert o.ask >= o.bid > 0


@pytest.mark.asyncio
async def test_get_historical_option_data_not_implemented(fake_breeze_module):
    provider = _make_provider(fake_breeze_module)
    with pytest.raises(NotImplementedError):
        await provider.get_historical_option_data("NIFTY", dt.date(2026, 1, 29), dt.date(2025, 6, 1))


@pytest.mark.asyncio
async def test_get_historical_prices(fake_breeze_module):
    provider = _make_provider(fake_breeze_module)
    bars = await provider.get_historical_prices("NIFTY", dt.date(2026, 1, 1), dt.date(2026, 1, 2))
    assert len(bars) == 1
    assert bars[0].close == 105.0


def test_parse_option_row_call():
    ts = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    row = {"strike_price": "24500", "right": "Call", "best_bid_price": "100", "best_offer_price": "102"}
    quote = _parse_option_row(row, ts)
    assert quote.option_type == "CALL"
    assert quote.strike == 24500.0
    assert quote.ltp == 101.0  # falls back to bid/ask midpoint when ltp absent


def test_unwrap_raises_on_error():
    with pytest.raises(RuntimeError):
        _unwrap({"Success": None, "Error": "invalid session"})


def test_unwrap_returns_success_list():
    assert _unwrap({"Success": [1, 2, 3], "Error": None}) == [1, 2, 3]
