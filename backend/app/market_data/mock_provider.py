"""
MockProvider: the default MarketDataProvider. Requires no external API or
DB seed — everything is generated on the fly from the parametric vol
surface model, so the whole application runs immediately (§4). All output
carries source="DEMO DATA".
"""
from __future__ import annotations

import datetime as dt
import math

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
from app.market_data.chain_generator import generate_chain
from app.market_data.vol_surface_model import (
    DEFAULT_PROFILES,
    evolve_surface,
    expiry_dates_from,
    init_surface,
    stable_seed,
    state_to_surface,
    strike_grid,
    surface_to_state,
)


class MockProvider(MarketDataProvider):
    def __init__(self, seed: int = 7):
        self._seed = seed
        self._surfaces = {}
        self._history: dict[str, list[OHLCBar]] = {}
        # Tracks which symbols have adopted a real persisted checkpoint via
        # sync_surface — until then, self._surfaces holds only the throwaway
        # init_surface() placeholder below, which must always be replaced by
        # the first sync_surface() call regardless of its date (that
        # placeholder is stamped "today" too, so a naive date comparison
        # would wrongly treat it as already up to date — see sync_surface).
        self._synced: set[str] = set()
        for symbol, profile in DEFAULT_PROFILES.items():
            rng = np.random.default_rng(self._symbol_seed(symbol))
            self._surfaces[symbol] = init_surface(dt.date.today(), profile, rng)

    def _symbol_seed(self, symbol: str, salt: int = 0) -> int:
        return (self._seed + stable_seed(symbol) + salt) % (2 ** 31 - 1)

    def _profile(self, symbol: str):
        if symbol not in DEFAULT_PROFILES:
            raise ValueError(f"Unknown demo symbol '{symbol}'. Available: {list(DEFAULT_PROFILES)}")
        return DEFAULT_PROFILES[symbol]

    def sync_surface(self, symbol: str, as_of: dt.date, spot: float, tenor_state: dict) -> None:
        """
        Resumes this symbol's surface from a persisted checkpoint (see
        services/snapshot_service.py) instead of the fresh `init_surface`
        baseline computed in __init__ — the fix for the "reinitializes a
        fresh surface each calendar day" discontinuity (README known
        limitations). Always adopts the first checkpoint seen for a symbol
        (replacing the meaningless __init__ placeholder); after that, a
        checkpoint no newer than what's already loaded is a no-op, so a
        stale/duplicate sync can't roll an already-advanced walk backwards.
        """
        current = self._surfaces.get(symbol)
        if symbol in self._synced and current is not None and current.as_of >= as_of:
            return
        self._surfaces[symbol] = state_to_surface(as_of, spot, tenor_state)
        self._synced.add(symbol)

    def advance_to(self, symbol: str, target_date: dt.date) -> None:
        """
        Evolves this symbol's surface forward one `evolve_surface` AR(1)
        step per business day strictly between its current `as_of` and
        `target_date` — a no-op if already caught up (e.g. a second refresh
        tick on the same day), and self-healing across however many days a
        process was down for. Each missed day's step is seeded
        deterministically off (symbol, date) so re-deriving the same
        catch-up twice (e.g. from two processes) is reproducible.
        """
        profile = self._profile(symbol)
        surface = self._surfaces[symbol]
        d = surface.as_of
        while d < target_date:
            d += dt.timedelta(days=1)
            if d.weekday() >= 5:
                continue
            rng = np.random.default_rng(stable_seed(f"{symbol}|{d.isoformat()}") % (2 ** 31 - 1))
            surface = evolve_surface(surface, d, profile, rng)
        self._surfaces[symbol] = surface

    def export_surface(self, symbol: str) -> tuple[dt.date, float, dict]:
        surface = self._surfaces[symbol]
        return surface.as_of, surface.spot, surface_to_state(surface)

    async def get_underlying_quote(self, symbol: str) -> UnderlyingQuote:
        profile = self._profile(symbol)
        surface = self._surfaces[symbol]
        return UnderlyingQuote(
            symbol=symbol, exchange=profile.exchange, spot_price=surface.spot,
            lot_size=profile.lot_size, timestamp=dt.datetime.now(dt.timezone.utc),
        )

    async def get_expiries(self, symbol: str) -> list[ExpiryInfo]:
        self._profile(symbol)
        today = dt.date.today()
        out = []
        for d in expiry_dates_from(today):
            dte = (d - today).days
            bdays = int(np.busday_count(today, d))
            out.append(ExpiryInfo(d, dte, bdays))
        return out

    async def get_option_chain(self, symbol: str, expiry_date: dt.date) -> list[OptionQuote]:
        profile = self._profile(symbol)
        surface = self._surfaces[symbol]
        settings = get_settings()
        rng = np.random.default_rng(self._symbol_seed(symbol, salt=expiry_date.toordinal()))
        strikes = strike_grid(surface.spot, profile.strike_step)
        return generate_chain(
            surface, profile, expiry_date, dt.date.today(),
            settings.risk_free_rate, settings.dividend_yield, rng, strikes,
        )

    async def get_historical_prices(self, symbol: str, start: dt.date, end: dt.date) -> list[OHLCBar]:
        hist = self._get_or_build_history(symbol)
        return [b for b in hist if start <= b.date <= end]

    async def get_historical_option_data(
        self, symbol: str, expiry_date: dt.date, as_of: dt.date
    ) -> list[OptionQuote]:
        profile = self._profile(symbol)
        settings = get_settings()
        rng = np.random.default_rng(self._symbol_seed(symbol, salt=as_of.toordinal()))
        surface = init_surface(as_of, profile, rng)
        strikes = strike_grid(surface.spot, profile.strike_step)
        return generate_chain(
            surface, profile, expiry_date, as_of,
            settings.risk_free_rate, settings.dividend_yield, rng, strikes,
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
        self._profile(symbol)
        return get_settings().dividend_yield

    async def get_trading_calendar(self, symbol: str, start: dt.date, end: dt.date) -> list[dt.date]:
        self._profile(symbol)
        return [d.date() for d in pd.bdate_range(start, end)]

    def _get_or_build_history(self, symbol: str, days: int = 300) -> list[OHLCBar]:
        if symbol in self._history:
            return self._history[symbol]
        profile = self._profile(symbol)
        rng = np.random.default_rng(self._symbol_seed(symbol, salt=999))
        end = dt.date.today()
        dates = [d.date() for d in pd.bdate_range(end - pd.Timedelta(days=int(days * 1.6)), end)][-days:]

        vol = profile.daily_return_vol
        close = profile.spot / math.exp(rng.normal(0, vol * math.sqrt(days)) * 0.3)
        bars = []
        for d in dates:
            ret = rng.normal(-0.5 * vol ** 2, vol)
            open_ = close
            close = open_ * math.exp(ret)
            intraday = rng.uniform(0.001, vol * 0.8)
            high = max(open_, close) * (1 + intraday)
            low = min(open_, close) * (1 - intraday)
            bars.append(OHLCBar(d, round(open_, 2), round(high, 2), round(low, 2), round(close, 2), int(rng.uniform(1e5, 5e5))))
        self._history[symbol] = bars
        return bars
