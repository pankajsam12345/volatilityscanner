"""
CSVProvider: reads exported option-chain / underlying-history datasets from
disk so the full analytics engine can be exercised against historical CSV
option-chain data (§4). Directory layout, per symbol, under `base_dir`:

  {SYMBOL}/meta.csv               exchange,lot_size,strike_step
  {SYMBOL}/underlying_history.csv date,open,high,low,close,volume
  {SYMBOL}/chain_YYYYMMDD.csv     expiry_date,strike,option_type,bid,ask,
                                   ltp,volume,open_interest,bid_quantity,ask_quantity

This is exactly the format the synthetic seed generator (`scripts/seed.py`)
writes, so the demo dataset doubles as a CSVProvider fixture.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

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


class CSVProvider(MarketDataProvider):
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self._underlying_cache: dict[str, pd.DataFrame] = {}
        self._meta_cache: dict[str, dict] = {}

    def _symbol_dir(self, symbol: str) -> Path:
        d = self.base_dir / symbol
        if not d.is_dir():
            raise ValueError(f"No CSV dataset found for '{symbol}' under {self.base_dir}")
        return d

    def _meta(self, symbol: str) -> dict:
        if symbol not in self._meta_cache:
            path = self._symbol_dir(symbol) / "meta.csv"
            row = pd.read_csv(path).iloc[0]
            self._meta_cache[symbol] = row.to_dict()
        return self._meta_cache[symbol]

    def _underlying_history(self, symbol: str) -> pd.DataFrame:
        if symbol not in self._underlying_cache:
            path = self._symbol_dir(symbol) / "underlying_history.csv"
            df = pd.read_csv(path, parse_dates=["date"])
            df["date"] = df["date"].dt.date
            self._underlying_cache[symbol] = df.sort_values("date").reset_index(drop=True)
        return self._underlying_cache[symbol]

    def _latest_chain_file(self, symbol: str) -> Path:
        files = sorted(self._symbol_dir(symbol).glob("chain_*.csv"))
        if not files:
            raise ValueError(f"No chain_*.csv files found for '{symbol}'")
        return files[-1]

    def _chain_file_for_date(self, symbol: str, as_of: dt.date) -> Path | None:
        path = self._symbol_dir(symbol) / f"chain_{as_of:%Y%m%d}.csv"
        return path if path.exists() else None

    def _read_chain(self, path: Path) -> pd.DataFrame:
        return pd.read_csv(path, parse_dates=["expiry_date"])

    async def get_underlying_quote(self, symbol: str) -> UnderlyingQuote:
        meta = self._meta(symbol)
        hist = self._underlying_history(symbol)
        last = hist.iloc[-1]
        return UnderlyingQuote(
            symbol=symbol, exchange=meta["exchange"], spot_price=float(last["close"]),
            lot_size=int(meta["lot_size"]),
            timestamp=dt.datetime.combine(last["date"], dt.time(15, 30)),
        )

    async def get_expiries(self, symbol: str) -> list[ExpiryInfo]:
        chain_path = self._latest_chain_file(symbol)
        as_of = dt.datetime.strptime(chain_path.stem.replace("chain_", ""), "%Y%m%d").date()
        df = self._read_chain(chain_path)
        out = []
        for expiry in sorted(df["expiry_date"].dt.date.unique()):
            dte = (expiry - as_of).days
            bdays = int(pd.bdate_range(as_of, expiry).size) if dte > 0 else 0
            out.append(ExpiryInfo(expiry, dte, bdays))
        return out

    async def get_option_chain(self, symbol: str, expiry_date: dt.date) -> list[OptionQuote]:
        chain_path = self._latest_chain_file(symbol)
        as_of = dt.datetime.strptime(chain_path.stem.replace("chain_", ""), "%Y%m%d").date()
        return self._quotes_from_chain_file(chain_path, expiry_date, as_of)

    async def get_historical_prices(self, symbol: str, start: dt.date, end: dt.date) -> list[OHLCBar]:
        hist = self._underlying_history(symbol)
        sub = hist[(hist["date"] >= start) & (hist["date"] <= end)]
        return [
            OHLCBar(row.date, float(row.open), float(row.high), float(row.low), float(row.close), int(row.volume))
            for row in sub.itertuples()
        ]

    async def get_historical_option_data(
        self, symbol: str, expiry_date: dt.date, as_of: dt.date
    ) -> list[OptionQuote]:
        path = self._chain_file_for_date(symbol, as_of)
        if path is None:
            return []
        return self._quotes_from_chain_file(path, expiry_date, as_of)

    def _quotes_from_chain_file(self, path: Path, expiry_date: dt.date, as_of: dt.date) -> list[OptionQuote]:
        df = self._read_chain(path)
        sub = df[df["expiry_date"].dt.date == expiry_date]
        timestamp = dt.datetime.combine(as_of, dt.time(15, 30))
        return [
            OptionQuote(
                strike=float(row.strike), option_type=row.option_type, bid=float(row.bid), ask=float(row.ask),
                ltp=float(row.ltp), volume=int(row.volume), open_interest=int(row.open_interest),
                bid_quantity=int(row.bid_quantity), ask_quantity=int(row.ask_quantity),
                timestamp=timestamp, source="DEMO DATA (CSV)",
            )
            for row in sub.itertuples()
        ]

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
        self._meta(symbol)
        return get_settings().dividend_yield

    async def get_trading_calendar(self, symbol: str, start: dt.date, end: dt.date) -> list[dt.date]:
        hist = self._underlying_history(symbol)
        return [d for d in hist["date"] if start <= d <= end]
