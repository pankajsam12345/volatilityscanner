"""
Master demo-data seed script (§59).

For each demo symbol (NIFTY, BANKNIFTY, SPX):
  1. Walks a ~2-year synthetic daily path of the parametric vol surface
     (app.market_data.vol_surface_model), producing a spot OHLC history.
  2. Writes that OHLC history + a handful of full option-chain snapshots to
     CSV (app.market_data.csv_provider's expected layout) so CSVProvider has
     real fixtures to serve.
  3. For the last ~1 year of that path (the "analysis window" — the first
     ~1 year is pure warm-up so HV252 and the percentile engine have enough
     trailing history), computes and persists HistoricalVolatility rows
     (5 estimators) and MetricHistory rows (ATM IV / skew / RR / BF per
     tenor, calendar spreads, forward vol, term-structure slope/curvature)
     via the analytic surface-metrics shortcut (§ see market_data/
     surface_metrics.py for why this avoids a full IV solve per historical
     day).
  4. For every day in the analysis window EXCEPT "today" (i.e. surfaces[
     WARMUP_DAYS:-1]), also runs that same real chain -> IV solver -> Greeks
     pipeline against a single rolling near-month expiry (a fixed ~30-day
     calendar ladder, not the full multi-expiry ladder "today" gets — see
     README known limitations) and persists those Option +
     VolatilitySnapshot rows too, so the chain-replay backtester has real
     historical option prices to mark positions to market against.
  5. For "today" (the final day of the path), generates a full multi-expiry
     option chain the normal way and persists Option + VolatilitySnapshot
     rows by running the REAL pipeline: chain -> IV solver -> Greeks. This
     is what the Option Chain / Opportunity Scanner / Strategy Builder
     pages read — `volatility_service.build_expiry_snapshot` always scopes
     to `max(timestamp)` per expiry, so today's rows are what's returned
     regardless of how much older historical data now shares these tables.

All persisted rows are tagged DEMO DATA. Run with:
    python -m scripts.seed
"""
from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import delete, insert

from app.analytics.black_scholes import BSInputs
from app.analytics.black_scholes import delta as bs_delta, gamma as bs_gamma, rho as bs_rho, theta as bs_theta, vega as bs_vega
from app.analytics.calendar import calendar_matrix
from app.analytics.greeks import charm, color, speed, vanna, volga, zomma
from app.analytics.iv_solver import IVStatus, solve_iv
from app.analytics.realized_vol import historical_volatility_suite
from app.analytics.term_structure import term_structure_curvature, term_structure_slope
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.market_data.chain_generator import generate_chain
from app.market_data.surface_metrics import surface_metrics_for_tenor
from app.market_data.vol_surface_model import (
    DEFAULT_PROFILES,
    TENOR_DAYS,
    evolve_surface,
    expiry_dates_from,
    init_surface,
    nearest_tenor_days,
    stable_seed,
    strike_grid,
    surface_to_state,
)
from app.models import Expiry, HistoricalVolatility, MetricHistory, Option, Opportunity, Underlying, VolatilitySnapshot

WARMUP_DAYS = 260  # HV252 needs a full trailing year before its first valid reading
ANALYSIS_WINDOW_DAYS = 1260  # matches settings.percentile_lookback_days's ~5y-of-trading-days default
TOTAL_DAYS = WARMUP_DAYS + ANALYSIS_WINDOW_DAYS
METRIC_TENORS = [7, 14, 30, 60, 90, 180, 270, 365]
TENOR_LABEL = {7: "1W", 14: "2W", 30: "1M", 60: "2M", 90: "3M", 180: "6M", 270: "9M", 365: "1Y"}
CALENDAR_PAIRS = [(7, 30), (30, 60), (30, 90), (60, 90), (30, 180), (90, 180)]
CSV_CHAIN_DAYS = 3  # how many recent days get a full CSV chain export
HISTORICAL_STRIKE_HALF_WIDTH = 15  # narrower than "today"'s 20-per-side grid — ~260 historical days x 3 symbols already multiplies row volume substantially

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "csv"


def _build_ohlc(surfaces: list, profile) -> pd.DataFrame:
    rng = np.random.default_rng(stable_seed(profile.symbol) % (2 ** 31 - 1))
    rows = []
    for i, s in enumerate(surfaces):
        open_ = surfaces[i - 1].spot if i > 0 else s.spot
        close = s.spot
        intraday = rng.uniform(0.001, profile.daily_return_vol * 0.8)
        high = max(open_, close) * (1 + intraday)
        low = min(open_, close) * (1 - intraday)
        rows.append({
            "date": s.as_of, "open": round(open_, 2), "high": round(high, 2),
            "low": round(low, 2), "close": round(close, 2), "volume": int(rng.uniform(1e5, 5e5)),
        })
    return pd.DataFrame(rows)


def _write_csv_fixtures(symbol: str, profile, surfaces: list, ohlc: pd.DataFrame, rate: float, q: float) -> None:
    out_dir = DATA_DIR / symbol
    out_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame([{"exchange": profile.exchange, "lot_size": profile.lot_size, "strike_step": profile.strike_step}]).to_csv(
        out_dir / "meta.csv", index=False
    )
    ohlc.to_csv(out_dir / "underlying_history.csv", index=False)

    rng = np.random.default_rng(stable_seed(symbol + "csv") % (2 ** 31 - 1))
    for surface in surfaces[-CSV_CHAIN_DAYS:]:
        as_of = surface.as_of
        strikes = strike_grid(surface.spot, profile.strike_step)
        rows = []
        for expiry in expiry_dates_from(as_of):
            quotes = generate_chain(surface, profile, expiry, as_of, rate, q, rng, strikes)
            for quote in quotes:
                rows.append({
                    "expiry_date": expiry.isoformat(), "strike": quote.strike, "option_type": quote.option_type,
                    "bid": quote.bid, "ask": quote.ask, "ltp": quote.ltp, "volume": quote.volume,
                    "open_interest": quote.open_interest, "bid_quantity": quote.bid_quantity,
                    "ask_quantity": quote.ask_quantity,
                })
        pd.DataFrame(rows).to_csv(out_dir / f"chain_{as_of:%Y%m%d}.csv", index=False)


def _historical_volatility_rows(underlying_id: int, ohlc: pd.DataFrame, settings) -> list[dict]:
    rows = []
    estimators = ["CLOSE_CLOSE", "PARKINSON", "GARMAN_KLASS", "ROGERS_SATCHELL", "YANG_ZHANG"]
    for i in range(WARMUP_DAYS, len(ohlc)):
        window_df = ohlc.iloc[: i + 1]
        ts = dt.datetime.combine(ohlc.iloc[i]["date"], dt.time(15, 30))
        for estimator in estimators:
            suite = historical_volatility_suite(window_df, settings.hv_windows, settings.trading_days_per_year, estimator)
            rows.append({"underlying_id": underlying_id, "estimator": estimator, "timestamp": ts, **suite})
    return rows


def _metric_history_rows(underlying_id: int, surfaces: list, rate: float, q: float, settings) -> list[dict]:
    rows = []
    for surface in surfaces[WARMUP_DAYS:]:
        ts = dt.datetime.combine(surface.as_of, dt.time(15, 30))
        tenor_atm: list[tuple[float, float]] = []
        for tenor in METRIC_TENORS:
            m = surface_metrics_for_tenor(surface, tenor, rate, q, settings.rr_bf_deltas)
            label = TENOR_LABEL[tenor]
            if m["atm_iv"] is not None:
                rows.append({"underlying_id": underlying_id, "metric_name": "atm_iv", "bucket": label, "value": m["atm_iv"], "timestamp": ts})
                tenor_atm.append((tenor / 365.0, m["atm_iv"]))
            for d in settings.rr_bf_deltas:
                for key in (f"skew_{d}", f"rr_{d}", f"bf_{d}"):
                    val = m.get(key)
                    if val is not None:
                        rows.append({"underlying_id": underlying_id, "metric_name": key, "bucket": label, "value": val, "timestamp": ts})

        if tenor_atm:
            slope = term_structure_slope(tenor_atm)
            curvature = term_structure_curvature(tenor_atm)
            if slope is not None:
                rows.append({"underlying_id": underlying_id, "metric_name": "term_slope", "bucket": "", "value": slope, "timestamp": ts})
            if curvature is not None:
                rows.append({"underlying_id": underlying_id, "metric_name": "term_curvature", "bucket": "", "value": curvature, "timestamp": ts})

        expiries_for_calendar = [(TENOR_LABEL[t], t / 365.0, surface.smile_iv(t, surface.spot)) for t in METRIC_TENORS]
        for cell in calendar_matrix(expiries_for_calendar):
            bucket = f"{cell.near_label}_{cell.far_label}"
            rows.append({"underlying_id": underlying_id, "metric_name": "calendar_spread", "bucket": bucket, "value": cell.calendar_spread, "timestamp": ts})
            if cell.forward_vol is not None:
                rows.append({"underlying_id": underlying_id, "metric_name": "forward_vol", "bucket": bucket, "value": cell.forward_vol, "timestamp": ts})
    return rows


def _today_pipeline_rows(underlying_id: int, expiry_id_by_date: dict, surface, profile, rate: float, q: float):
    """Full chain -> IV solver -> Greeks pipeline for the most recent day (§54, real path)."""
    rng = np.random.default_rng(stable_seed(profile.symbol + "today") % (2 ** 31 - 1))
    strikes = strike_grid(surface.spot, profile.strike_step)
    option_rows, snapshot_rows = [], []
    ts = dt.datetime.combine(surface.as_of, dt.time(15, 30))

    for expiry in expiry_dates_from(surface.as_of):
        expiry_id = expiry_id_by_date[expiry]
        t_years = max((expiry - surface.as_of).days, 1) / 365.0
        quotes = generate_chain(surface, profile, expiry, surface.as_of, rate, q, rng, strikes)
        for quote in quotes:
            option_rows.append({
                "underlying_id": underlying_id, "expiry_id": expiry_id, "strike": quote.strike,
                "option_type": quote.option_type, "bid": quote.bid, "ask": quote.ask, "ltp": quote.ltp,
                "volume": quote.volume, "open_interest": quote.open_interest, "bid_quantity": quote.bid_quantity,
                "ask_quantity": quote.ask_quantity, "timestamp": ts, "source": "DEMO DATA",
            })

            mid = (quote.bid + quote.ask) / 2
            iv_result = solve_iv(
                market_price=mid, spot=surface.spot, strike=quote.strike, time_to_expiry=t_years,
                rate=rate, dividend_yield=q, option_type=quote.option_type, bid=quote.bid, ask=quote.ask,
            )
            row = {
                "underlying_id": underlying_id, "expiry_id": expiry_id, "strike": quote.strike,
                "option_type": quote.option_type, "iv": iv_result.iv, "iv_status": iv_result.status.value,
                "iv_error": iv_result.error, "timestamp": ts,
                "data_quality": "GOOD" if iv_result.status == IVStatus.VALID else "MISSING_IV",
            }
            if iv_result.status == IVStatus.VALID:
                inputs = BSInputs(surface.spot, quote.strike, t_years, rate, q, iv_result.iv, quote.option_type)
                row.update({
                    "delta": bs_delta(inputs), "gamma": bs_gamma(inputs), "vega": bs_vega(inputs),
                    "theta": bs_theta(inputs) / 365.0, "rho": bs_rho(inputs),
                    "vanna": vanna(inputs), "volga": volga(inputs), "charm": charm(inputs) / 365.0,
                    "speed": speed(inputs), "color": color(inputs) / 365.0, "zomma": zomma(inputs),
                })
            snapshot_rows.append(row)
    return option_rows, snapshot_rows


def _monthly_expiry_ladder(start: dt.date, end: dt.date) -> list[dt.date]:
    """
    Fixed ~30-day-cadence calendar of expiry dates spanning [start, end]
    plus one date past `end`, so every historical day up to `end` has a
    strictly-later upcoming expiry to resolve against. Not a real NSE
    last-Thursday-of-month calendar — a deliberately simple fixed cadence,
    sufficient for a demo chain-replay backtest of a rolled monthly
    strategy (see README known limitations). generate_chain() snaps
    (expiry_date - as_of) to the surface's nearest tenor bucket internally,
    so any fixed calendar date works here, not just the day-relative
    offsets expiry_dates_from() produces for "today".
    """
    ladder = []
    d = start + dt.timedelta(days=30)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    while True:
        ladder.append(d)
        if d > end:
            break
        d = d + dt.timedelta(days=30)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
    return ladder


def _expiry_for_day(ladder: list[dt.date], as_of: dt.date) -> dt.date:
    """The nearest upcoming ladder expiry as of a given historical day — this
    is what makes a single expiry_id get repeatedly re-priced across ~30
    consecutive historical days (a "held position"), rolling to the next
    ladder date once the current one has passed."""
    for d in ladder:
        if d > as_of:
            return d
    return ladder[-1]


def _historical_chain_rows(
    underlying_id: int, history_days: list, profile, ladder: list, ladder_expiry_id: dict, rate: float, q: float,
) -> tuple[list[dict], list[dict]]:
    """
    Same real chain -> IV solver -> Greeks pipeline as _today_pipeline_rows,
    applied to a single rolling near-month expiry per historical day (not
    the full multi-expiry ladder "today" gets) so the chain-replay
    backtester has genuine historical option prices to mark positions to
    market against.
    """
    rng = np.random.default_rng(stable_seed(profile.symbol + "hist") % (2 ** 31 - 1))
    option_rows, snapshot_rows = [], []
    for surface in history_days:
        expiry = _expiry_for_day(ladder, surface.as_of)
        expiry_id = ladder_expiry_id[expiry]
        t_years = max((expiry - surface.as_of).days, 1) / 365.0
        strikes = strike_grid(surface.spot, profile.strike_step, n_each_side=HISTORICAL_STRIKE_HALF_WIDTH)
        ts = dt.datetime.combine(surface.as_of, dt.time(15, 30))
        quotes = generate_chain(surface, profile, expiry, surface.as_of, rate, q, rng, strikes)
        for quote in quotes:
            option_rows.append({
                "underlying_id": underlying_id, "expiry_id": expiry_id, "strike": quote.strike,
                "option_type": quote.option_type, "bid": quote.bid, "ask": quote.ask, "ltp": quote.ltp,
                "volume": quote.volume, "open_interest": quote.open_interest, "bid_quantity": quote.bid_quantity,
                "ask_quantity": quote.ask_quantity, "timestamp": ts, "source": "DEMO DATA",
            })

            mid = (quote.bid + quote.ask) / 2
            iv_result = solve_iv(
                market_price=mid, spot=surface.spot, strike=quote.strike, time_to_expiry=t_years,
                rate=rate, dividend_yield=q, option_type=quote.option_type, bid=quote.bid, ask=quote.ask,
            )
            row = {
                "underlying_id": underlying_id, "expiry_id": expiry_id, "strike": quote.strike,
                "option_type": quote.option_type, "iv": iv_result.iv, "iv_status": iv_result.status.value,
                "iv_error": iv_result.error, "timestamp": ts,
                "data_quality": "GOOD" if iv_result.status == IVStatus.VALID else "MISSING_IV",
            }
            if iv_result.status == IVStatus.VALID:
                inputs = BSInputs(surface.spot, quote.strike, t_years, rate, q, iv_result.iv, quote.option_type)
                row.update({
                    "delta": bs_delta(inputs), "gamma": bs_gamma(inputs), "vega": bs_vega(inputs),
                    "theta": bs_theta(inputs) / 365.0, "rho": bs_rho(inputs),
                    "vanna": vanna(inputs), "volga": volga(inputs), "charm": charm(inputs) / 365.0,
                    "speed": speed(inputs), "color": color(inputs) / 365.0, "zomma": zomma(inputs),
                })
            snapshot_rows.append(row)
    return option_rows, snapshot_rows


async def seed_symbol(session) -> None:
    settings = get_settings()
    for symbol in settings.demo_symbols:
        profile = DEFAULT_PROFILES[symbol]
        print(f"[seed] {symbol}: walking {TOTAL_DAYS}-day synthetic vol surface path...")
        rng = np.random.default_rng(stable_seed(symbol) % (2 ** 31 - 1))
        dates = [d.date() for d in pd.bdate_range(end=dt.date.today(), periods=TOTAL_DAYS)]

        surfaces = [init_surface(dates[0], profile, rng)]
        for d in dates[1:]:
            surfaces.append(evolve_surface(surfaces[-1], d, profile, rng))

        ohlc = _build_ohlc(surfaces, profile)
        _write_csv_fixtures(symbol, profile, surfaces, ohlc, settings.risk_free_rate, settings.dividend_yield)

        today_surface = surfaces[-1]
        underlying_res = await session.execute(
            insert(Underlying).values(
                symbol=symbol, exchange=profile.exchange, spot_price=today_surface.spot,
                lot_size=profile.lot_size, timestamp=dt.datetime.combine(today_surface.as_of, dt.time(15, 30)),
                is_demo=True, surface_state=surface_to_state(today_surface),
            ).returning(Underlying.id)
        )
        underlying_id = underlying_res.scalar_one()

        expiry_id_by_date = {}
        expiry_rows = []
        for expiry in expiry_dates_from(today_surface.as_of):
            dte = (expiry - today_surface.as_of).days
            bdays = int(np.busday_count(today_surface.as_of, expiry))
            expiry_rows.append({"underlying_id": underlying_id, "expiry_date": expiry, "days_to_expiry": dte, "business_days_to_expiry": bdays, "source": "LIVE"})
        expiry_res = await session.execute(insert(Expiry).values(expiry_rows).returning(Expiry.id, Expiry.expiry_date))
        for row_id, expiry_date in expiry_res.all():
            expiry_id_by_date[expiry_date] = row_id

        print(f"[seed] {symbol}: computing {TOTAL_DAYS - WARMUP_DAYS} days of historical volatility + metric history...")
        hv_rows = _historical_volatility_rows(underlying_id, ohlc, settings)
        if hv_rows:
            await session.execute(insert(HistoricalVolatility), hv_rows)

        metric_rows = _metric_history_rows(underlying_id, surfaces, settings.risk_free_rate, settings.dividend_yield, settings)
        if metric_rows:
            await session.execute(insert(MetricHistory), metric_rows)

        history_days = surfaces[WARMUP_DAYS:-1]  # excludes "today" itself — handled separately below
        print(f"[seed] {symbol}: generating {len(history_days)} days of historical option-chain rows (chain-replay backtest data)...")
        ladder = _monthly_expiry_ladder(history_days[0].as_of, history_days[-1].as_of)
        ladder_expiry_id: dict = {}
        new_ladder_dates = [d for d in ladder if d not in expiry_id_by_date]
        if new_ladder_dates:
            hist_expiry_rows = [
                {
                    "underlying_id": underlying_id, "expiry_date": d,
                    "days_to_expiry": (d - today_surface.as_of).days,
                    "business_days_to_expiry": int(np.busday_count(today_surface.as_of, d)),
                    "source": "HISTORICAL_REPLAY",
                }
                for d in new_ladder_dates
            ]
            hist_expiry_res = await session.execute(insert(Expiry).values(hist_expiry_rows).returning(Expiry.id, Expiry.expiry_date))
            for row_id, expiry_date in hist_expiry_res.all():
                ladder_expiry_id[expiry_date] = row_id
        for d in ladder:
            if d in expiry_id_by_date:
                ladder_expiry_id[d] = expiry_id_by_date[d]

        hist_option_rows, hist_snapshot_rows = _historical_chain_rows(
            underlying_id, history_days, profile, ladder, ladder_expiry_id, settings.risk_free_rate, settings.dividend_yield,
        )
        chunk = 5000
        for i in range(0, len(hist_option_rows), chunk):
            await session.execute(insert(Option), hist_option_rows[i:i + chunk])
            await session.execute(insert(VolatilitySnapshot), hist_snapshot_rows[i:i + chunk])
            await session.commit()

        print(f"[seed] {symbol}: running today's real chain -> IV solver -> Greeks pipeline...")
        option_rows, snapshot_rows = _today_pipeline_rows(
            underlying_id, expiry_id_by_date, today_surface, profile, settings.risk_free_rate, settings.dividend_yield
        )
        await session.execute(insert(Option), option_rows)
        await session.execute(insert(VolatilitySnapshot), snapshot_rows)

        await session.commit()
        print(
            f"[seed] {symbol}: done ({len(hv_rows)} HV rows, {len(metric_rows)} metric rows, "
            f"{len(option_rows)} live options, {len(hist_option_rows)} historical options)."
        )

        print(f"[seed] {symbol}: running opportunity engine...")
        from app.services.opportunity_service import generate_opportunities  # local import: avoids a service->script import at module load

        await generate_opportunities(session, symbol, settings)
        print(f"[seed] {symbol}: opportunities generated.")


async def _ensure_admin_user(session) -> None:
    """Idempotent: does nothing if an admin user already exists (never resets a changed password)."""
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.models import User

    settings = get_settings()
    existing = (await session.execute(select(User).where(User.username == settings.default_admin_username))).scalar_one_or_none()
    if existing is not None:
        print(f"[seed] admin user '{settings.default_admin_username}' already exists, leaving as-is.")
        return
    session.add(User(
        username=settings.default_admin_username,
        hashed_password=hash_password(settings.default_admin_password),
        is_active=True,
        created_at=dt.datetime.now(dt.timezone.utc),
    ))
    await session.commit()
    print(f"[seed] created default admin user '{settings.default_admin_username}' (demo credentials — change in production).")


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        print("[seed] clearing existing demo data...")
        for model in (Opportunity, VolatilitySnapshot, Option, MetricHistory, HistoricalVolatility, Expiry, Underlying):
            await session.execute(delete(model))
        await session.commit()

        await seed_symbol(session)
        await _ensure_admin_user(session)

    print("[seed] complete.")


if __name__ == "__main__":
    asyncio.run(main())
