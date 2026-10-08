"""Turns a DailySurface into a full synthetic option chain (quotes, OI, volume, spreads)."""
from __future__ import annotations

import datetime as dt

import numpy as np

from app.analytics.black_scholes import BSInputs, price as bs_price
from app.market_data.base import OptionQuote
from app.market_data.vol_surface_model import DailySurface, UnderlyingProfile, nearest_tenor_days

MIN_TICK = 0.05
BASE_SPREAD_PCT = 0.03  # 3% of theoretical price at the money


def generate_chain(
    surface: DailySurface,
    profile: UnderlyingProfile,
    expiry_date: dt.date,
    as_of: dt.date,
    rate: float,
    dividend_yield: float,
    rng: np.random.Generator,
    strikes: list[float],
) -> list[OptionQuote]:
    tenor_days = max((expiry_date - as_of).days, 1)
    t_years = tenor_days / 365.0
    tenor_key = nearest_tenor_days(tenor_days)
    timestamp = dt.datetime.combine(as_of, dt.time(15, 30))

    quotes: list[OptionQuote] = []
    for strike in strikes:
        log_moneyness = float(np.log(strike / surface.spot))
        for option_type in ("CALL", "PUT"):
            iv = surface.smile_iv(tenor_key, strike)
            theo = bs_price(BSInputs(surface.spot, strike, t_years, rate, dividend_yield, iv, option_type))
            theo = max(theo, MIN_TICK)

            spread_pct = min(BASE_SPREAD_PCT * (1 + 6 * abs(log_moneyness)), 0.60)
            half_spread = max(theo * spread_pct / 2, MIN_TICK / 2)
            bid = max(round(theo - half_spread, 2), MIN_TICK)
            ask = round(theo + half_spread, 2)
            if ask <= bid:
                ask = bid + MIN_TICK
            ltp = round((bid + ask) / 2, 2)

            liquidity_decay = np.exp(-6 * log_moneyness ** 2)
            oi = int(max(50, 20000 * liquidity_decay) * rng.uniform(0.4, 1.6))
            volume = int(oi * rng.uniform(0.03, 0.25))
            bid_qty = int(max(1, volume * rng.uniform(0.3, 1.5)))
            ask_qty = int(max(1, volume * rng.uniform(0.3, 1.5)))

            quotes.append(
                OptionQuote(
                    strike=strike,
                    option_type=option_type,
                    bid=bid,
                    ask=ask,
                    ltp=ltp,
                    volume=volume,
                    open_interest=oi,
                    bid_quantity=bid_qty,
                    ask_quantity=ask_qty,
                    timestamp=timestamp,
                    source="DEMO DATA",
                )
            )
    return quotes
