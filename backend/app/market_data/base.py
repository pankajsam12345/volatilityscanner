"""
MarketDataProvider abstraction (§4). Nothing in the app talks to a broker
directly — everything goes through this interface, so swapping MockProvider
for a real NSE/broker feed later touches nothing else.
"""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class UnderlyingQuote:
    symbol: str
    exchange: str
    spot_price: float
    lot_size: int
    timestamp: dt.datetime
    is_demo: bool = True


@dataclass(frozen=True)
class ExpiryInfo:
    expiry_date: dt.date
    days_to_expiry: int
    business_days_to_expiry: int


@dataclass(frozen=True)
class OptionQuote:
    strike: float
    option_type: str  # "CALL" | "PUT"
    bid: float
    ask: float
    ltp: float
    volume: int
    open_interest: int
    bid_quantity: int
    ask_quantity: int
    timestamp: dt.datetime
    source: str = "DEMO DATA"


@dataclass(frozen=True)
class OHLCBar:
    date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


@dataclass(frozen=True)
class MarketDepthLevel:
    price: float
    quantity: int


@dataclass(frozen=True)
class MarketDepth:
    bids: list[MarketDepthLevel] = field(default_factory=list)
    asks: list[MarketDepthLevel] = field(default_factory=list)


class MarketDataProvider(ABC):
    """Every method is async so a real broker adapter can hit the network."""

    @abstractmethod
    async def get_underlying_quote(self, symbol: str) -> UnderlyingQuote: ...

    @abstractmethod
    async def get_expiries(self, symbol: str) -> list[ExpiryInfo]: ...

    @abstractmethod
    async def get_option_chain(self, symbol: str, expiry_date: dt.date) -> list[OptionQuote]: ...

    @abstractmethod
    async def get_historical_prices(self, symbol: str, start: dt.date, end: dt.date) -> list[OHLCBar]: ...

    @abstractmethod
    async def get_historical_option_data(
        self, symbol: str, expiry_date: dt.date, as_of: dt.date
    ) -> list[OptionQuote]: ...

    @abstractmethod
    async def get_market_depth(
        self, symbol: str, strike: float, option_type: str, expiry_date: dt.date
    ) -> MarketDepth: ...

    @abstractmethod
    async def get_interest_rates(self) -> float: ...

    @abstractmethod
    async def get_dividends(self, symbol: str) -> float: ...

    @abstractmethod
    async def get_trading_calendar(self, symbol: str, start: dt.date, end: dt.date) -> list[dt.date]: ...
