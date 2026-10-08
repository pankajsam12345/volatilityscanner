"""
BreezeProvider: a live MarketDataProvider backed by ICICI Direct's Breeze
Connect API. Every other module in the app only ever talks to the
MarketDataProvider ABC (app/market_data/base.py), so this is a drop-in
alternative to MockProvider/CSVProvider selected via
MARKET_DATA_PROVIDER=BREEZE.

Field-name parsing (Breeze's raw JSON -> our typed dataclasses) is
concentrated in the small `_parse_option_row`/`_parse_breeze_date` helpers
below so a mismatch against the installed SDK version is a one-place fix.
These field names match ICICI's public Breeze Connect API docs but have not
been smoke-tested against a live account - do that before trusting this in
production (see README known limitations).

Breeze session tokens expire daily and require an interactive browser
login - there is no safe way to automate that without handling the user's
broker OTP/credentials directly, so it isn't attempted here. Run
scripts/breeze_login.py once a day to refresh BREEZE_SESSION_TOKEN.
"""
from __future__ import annotations

import asyncio
import datetime as dt

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.market_data.base import (
    ExpiryInfo,
    MarketDataProvider,
    MarketDepth,
    MarketDepthLevel,
    OHLCBar,
    OptionQuote,
    UnderlyingQuote,
)


class BreezeSessionError(RuntimeError):
    """Breeze credentials missing, the SDK isn't installed, or login failed."""


def _breeze_datetime(d: dt.date) -> str:
    return dt.datetime.combine(d, dt.time(6, 0)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_breeze_date(raw) -> dt.date | None:
    if not raw:
        return None
    raw = str(raw).strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.000Z", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_option_row(row: dict, timestamp: dt.datetime) -> OptionQuote:
    right = str(row.get("right", "")).upper()
    option_type = "CALL" if right.startswith("C") else "PUT"
    bid = _to_float(row.get("best_bid_price") or row.get("bid_price"))
    ask = _to_float(row.get("best_offer_price") or row.get("ask_price"))
    ltp = _to_float(row.get("ltp") or row.get("last_traded_price"))
    if not ltp and (bid or ask):
        ltp = round((bid + ask) / 2, 2)
    return OptionQuote(
        strike=_to_float(row.get("strike_price")),
        option_type=option_type,
        bid=bid,
        ask=ask,
        ltp=ltp,
        volume=_to_int(row.get("total_quantity_traded") or row.get("volume")),
        open_interest=_to_int(row.get("open_interest")),
        bid_quantity=_to_int(row.get("best_bid_quantity") or row.get("bid_qty")),
        ask_quantity=_to_int(row.get("best_offer_quantity") or row.get("ask_qty")),
        timestamp=timestamp,
        source="BREEZE",
    )


def _unwrap(result):
    """Breeze responses are typically {"Success": [...], "Error": ..., "Status": 200}."""
    if isinstance(result, dict):
        if result.get("Error"):
            raise RuntimeError(f"Breeze API error: {result['Error']}")
        return result.get("Success") or []
    return result or []


class BreezeProvider(MarketDataProvider):
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        session_token: str,
        symbol_map: dict[str, str],
        exchange_code: str = "NFO",
        cash_exchange_code: str = "NSE",
    ):
        if not (api_key and api_secret and session_token):
            raise BreezeSessionError(
                "Breeze credentials missing - set BREEZE_API_KEY / BREEZE_API_SECRET / "
                "BREEZE_SESSION_TOKEN (run scripts/breeze_login.py for a fresh daily session token)."
            )
        try:
            from breeze_connect import BreezeConnect
        except ImportError as exc:
            raise BreezeSessionError("breeze-connect is not installed - add it to requirements.txt") from exc

        self._client = BreezeConnect(api_key=api_key)
        try:
            self._client.generate_session(api_secret=api_secret, session_token=session_token)
        except Exception as exc:
            raise BreezeSessionError(
                f"Breeze session login failed: {exc}. Session tokens expire daily - "
                "run scripts/breeze_login.py to get a fresh one."
            ) from exc

        self._symbol_map = symbol_map
        self._exchange_code = exchange_code
        self._cash_exchange_code = cash_exchange_code

    def _stock_code(self, symbol: str) -> str:
        return self._symbol_map.get(symbol, symbol)

    async def _call(self, fn, **kwargs):
        result = await asyncio.to_thread(fn, **kwargs)
        return _unwrap(result)

    async def get_underlying_quote(self, symbol: str) -> UnderlyingQuote:
        rows = await self._call(
            self._client.get_quotes,
            stock_code=self._stock_code(symbol), exchange_code=self._cash_exchange_code, product_type="cash",
        )
        row = rows[0] if rows else {}
        return UnderlyingQuote(
            symbol=symbol, exchange=self._cash_exchange_code,
            spot_price=_to_float(row.get("ltp")), lot_size=_to_int(row.get("lot_size"), default=1),
            timestamp=dt.datetime.now(dt.timezone.utc), is_demo=False,
        )

    async def get_expiries(self, symbol: str) -> list[ExpiryInfo]:
        rows = await self._call(
            self._client.get_option_chain_quotes,
            stock_code=self._stock_code(symbol), exchange_code=self._exchange_code,
            product_type="options", expiry_date="", right="Call", strike_price="",
        )
        today = dt.date.today()
        seen: set[dt.date] = set()
        out: list[ExpiryInfo] = []
        for row in rows:
            d = _parse_breeze_date(row.get("expiry_date"))
            if d is None or d in seen:
                continue
            seen.add(d)
            out.append(ExpiryInfo(d, (d - today).days, int(np.busday_count(today, d))))
        return sorted(out, key=lambda e: e.expiry_date)

    async def get_option_chain(self, symbol: str, expiry_date: dt.date) -> list[OptionQuote]:
        stock_code = self._stock_code(symbol)
        expiry_str = _breeze_datetime(expiry_date)
        timestamp = dt.datetime.now(dt.timezone.utc)
        quotes: list[OptionQuote] = []
        for right in ("Call", "Put"):
            rows = await self._call(
                self._client.get_option_chain_quotes,
                stock_code=stock_code, exchange_code=self._exchange_code,
                product_type="options", expiry_date=expiry_str, right=right, strike_price="",
            )
            quotes.extend(_parse_option_row(row, timestamp) for row in rows)
        return quotes

    async def get_historical_prices(self, symbol: str, start: dt.date, end: dt.date) -> list[OHLCBar]:
        rows = await self._call(
            self._client.get_historical_data_v2,
            interval="1day", from_date=_breeze_datetime(start), to_date=_breeze_datetime(end),
            stock_code=self._stock_code(symbol), exchange_code=self._cash_exchange_code, product_type="cash",
        )
        out: list[OHLCBar] = []
        for row in rows:
            d = _parse_breeze_date(row.get("datetime") or row.get("date"))
            if d is None:
                continue
            out.append(OHLCBar(
                date=d, open=_to_float(row.get("open")), high=_to_float(row.get("high")),
                low=_to_float(row.get("low")), close=_to_float(row.get("close")),
                volume=_to_int(row.get("volume")),
            ))
        return out

    async def get_historical_option_data(
        self, symbol: str, expiry_date: dt.date, as_of: dt.date
    ) -> list[OptionQuote]:
        raise NotImplementedError(
            "Breeze has no point-in-time historical option-chain endpoint (only historical "
            "OHLC for an already-known contract). Historical percentile/backtest data must "
            "come from a separately maintained source (e.g. the seeded Mock data), not a live "
            "broker feed - see README known limitations."
        )

    async def get_market_depth(
        self, symbol: str, strike: float, option_type: str, expiry_date: dt.date
    ) -> MarketDepth:
        chain = await self.get_option_chain(symbol, expiry_date)
        opt = next((o for o in chain if o.strike == strike and o.option_type == option_type), None)
        if opt is None:
            return MarketDepth()
        bids = [MarketDepthLevel(round(opt.bid - i * 0.05, 2), max(1, opt.bid_quantity // (i + 1))) for i in range(5)]
        asks = [MarketDepthLevel(round(opt.ask + i * 0.05, 2), max(1, opt.ask_quantity // (i + 1))) for i in range(5)]
        return MarketDepth(bids=bids, asks=asks)

    async def get_interest_rates(self) -> float:
        return get_settings().risk_free_rate

    async def get_dividends(self, symbol: str) -> float:
        return get_settings().dividend_yield

    async def get_trading_calendar(self, symbol: str, start: dt.date, end: dt.date) -> list[dt.date]:
        return [d.date() for d in pd.bdate_range(start, end)]
