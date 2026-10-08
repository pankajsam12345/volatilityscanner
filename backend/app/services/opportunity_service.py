"""
Runs the full §54 pipeline for one underlying: loads today's real option-
chain-derived smile per expiry (from VolatilitySnapshot, already IV-solved
by snapshot_service), pairs it with precomputed historical distributions
(history_service), generates every applicable opportunity type
(opportunities/strategies.py), grounds each candidate's legs in real bid/
ask/vega/liquidity, finalizes it (opportunities/pipeline.py), and persists
Opportunity rows.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.no_arbitrage import NoArbFlag, check_butterfly_convexity, check_calendar_variance
from app.analytics.term_structure import ForwardVolResult, forward_vol
from app.models import Expiry, Opportunity, Underlying
from app.opportunities.greeks_aggregator import aggregate_strategy_greeks
from app.opportunities.pipeline import LegMarketData, finalize_opportunity
from app.opportunities.strategies import (
    OpportunityCandidate,
    opportunity_butterfly,
    opportunity_calendar,
    opportunity_forward_vol,
    opportunity_iv_vs_rv,
    opportunity_risk_reversal,
    opportunity_skew,
)
from app.services import history_service
from app.services.volatility_service import TENOR_LABEL, ExpirySnapshot, get_all_expiry_snapshots

CALENDAR_PAIRS_DAYS = [(7, 30), (30, 60), (30, 90), (60, 90), (30, 180), (90, 180)]


def _leg_market_data(es: ExpirySnapshot, leg, lot_size: int) -> tuple[LegMarketData, dict] | None:
    if leg.delta_bucket == "ATM":
        match = es.find_nearest_by_delta(None, 0.5)
    else:
        match = es.find_nearest_by_delta(leg.option_type, float(leg.delta_bucket) / 100)
    if match is None:
        return None
    key, snap = match

    opt = es.option_by_key.get(key)
    if opt is None:
        return None

    greeks = {
        "delta": snap.delta, "gamma": snap.gamma, "vega": snap.vega, "theta": snap.theta,
        "rho": snap.rho, "vanna": snap.vanna, "volga": snap.volga, "charm": snap.charm,
    }
    lmd = LegMarketData(bid=opt.bid, ask=opt.ask, vega=snap.vega, lot_size=lot_size, volume=opt.volume, open_interest=opt.open_interest)
    return lmd, greeks


async def _register(
    session: AsyncSession, underlying: Underlying, candidate: OpportunityCandidate | None,
    label_to_es: dict, primary_expiry_id: int | None, settings, extra_no_arb: list[NoArbFlag] | None = None,
) -> None:
    if candidate is None:
        return
    leg_market_data, leg_greeks = [], []
    for leg in candidate.legs:
        es = label_to_es.get(leg.tenor_label)
        if es is None:
            return
        result = _leg_market_data(es, leg, underlying.lot_size)
        if result is None:
            return
        lmd, greeks = result
        leg_market_data.append(lmd)
        leg_greeks.append(greeks)

    finalized = finalize_opportunity(candidate, leg_market_data, settings, no_arb_flags=extra_no_arb or [])
    leg_actions = [leg.action for leg in candidate.legs]
    aggregated_greeks = aggregate_strategy_greeks(leg_actions, leg_greeks)

    session.add(Opportunity(
        underlying_id=underlying.id, expiry_id=primary_expiry_id, timestamp=underlying.timestamp,
        strategy=finalized.strategy, signal_type=finalized.signal_type, direction=finalized.direction,
        score=finalized.score.total, score_components=finalized.score.as_dict(), confidence=finalized.confidence,
        gross_edge=finalized.gross_edge, transaction_cost=finalized.transaction_cost, net_edge=finalized.net_edge,
        max_risk=finalized.max_risk, expected_return=finalized.expected_return, risk_reward=finalized.risk_reward,
        liquidity_status=finalized.liquidity_status, data_quality=finalized.data_quality,
        legs=finalized.legs, greeks=aggregated_greeks, historical_context=finalized.historical_context,
        no_arbitrage_flags=finalized.no_arbitrage_flags,
        explanation={"why": finalized.why, "risks": finalized.risks},
        is_demo=underlying.is_demo,
    ))


async def generate_opportunities(session: AsyncSession, symbol: str, settings) -> int:
    underlying = (await session.execute(select(Underlying).where(Underlying.symbol == symbol))).scalar_one_or_none()
    if underlying is None:
        return 0

    # Idempotent per (underlying, timestamp): a scan re-run at the exact same
    # underlying timestamp (e.g. Celery's recompute firing before that tick's
    # snapshot refresh has advanced Underlying.timestamp) replaces rather than
    # duplicates that batch. Opportunities at genuinely different timestamps
    # still accumulate, preserving a history for future backtesting.
    await session.execute(
        delete(Opportunity).where(Opportunity.underlying_id == underlying.id, Opportunity.timestamp == underlying.timestamp)
    )

    expiries = (
        await session.execute(
            select(Expiry).where(Expiry.underlying_id == underlying.id, Expiry.source == "LIVE").order_by(Expiry.days_to_expiry)
        )
    ).scalars().all()

    expiry_snapshots: dict[int, ExpirySnapshot] = await get_all_expiry_snapshots(session, underlying, settings)
    label_to_es: dict[str, ExpirySnapshot] = {}
    for es in expiry_snapshots.values():
        label_to_es.setdefault(es.tenor_label, es)

    # Opportunity A: IV vs RV, per expiry
    rv20 = await history_service.get_latest_hv(session, underlying.id, 20)
    for expiry in expiries:
        es = expiry_snapshots.get(expiry.id)
        if es is None or rv20 is None:
            continue
        iv_hist, rv_hist = await history_service.get_aligned_iv_rv_history(session, underlying.id, es.tenor_label, 20)
        candidate = opportunity_iv_vs_rv(es.tenor_label, es.smile.atm_iv, rv20, iv_hist, rv_hist, settings.zscore_extreme_threshold)
        await _register(session, underlying, candidate, {es.tenor_label: es}, expiry.id, settings)

    # Opportunities D/E/F: RR / Butterfly / Skew, per expiry per delta bucket
    for expiry in expiries:
        es = expiry_snapshots.get(expiry.id)
        if es is None:
            continue
        for d in settings.rr_bf_deltas:
            put_iv, call_iv = es.grid.get(f"put_{d}d_iv"), es.grid.get(f"call_{d}d_iv")

            rr_val = es.rr.get(f"rr_{d}")
            if rr_val is not None and put_iv is not None and call_iv is not None:
                hist = await history_service.get_metric_history(session, underlying.id, f"rr_{d}", es.tenor_label)
                candidate = opportunity_risk_reversal(es.tenor_label, d, rr_val, put_iv, call_iv, hist, settings.zscore_extreme_threshold)
                await _register(session, underlying, candidate, {es.tenor_label: es}, expiry.id, settings)

            bf_val = es.bf.get(f"bf_{d}")
            if bf_val is not None and put_iv is not None and call_iv is not None:
                hist = await history_service.get_metric_history(session, underlying.id, f"bf_{d}", es.tenor_label)
                convexity = check_butterfly_convexity(bf_val, str(d))
                candidate = opportunity_butterfly(
                    es.tenor_label, d, bf_val, put_iv, call_iv, es.smile.atm_iv, hist,
                    settings.zscore_extreme_threshold, convexity.passed,
                )
                await _register(session, underlying, candidate, {es.tenor_label: es}, expiry.id, settings, [convexity])

            put_wing = es.skew.get(f"put_wing_{d}")
            if put_wing is not None and put_iv is not None:
                hist = await history_service.get_metric_history(session, underlying.id, f"skew_{d}", es.tenor_label)
                candidate = opportunity_skew(es.tenor_label, d, put_wing, put_iv, es.smile.atm_iv, hist, settings.zscore_extreme_threshold)
                await _register(session, underlying, candidate, {es.tenor_label: es}, expiry.id, settings)

    # Opportunities C/G: Calendar + Forward Vol, across configured tenor pairs
    for near_td, far_td in CALENDAR_PAIRS_DAYS:
        near_label, far_label = TENOR_LABEL[near_td], TENOR_LABEL[far_td]
        es_near, es_far = label_to_es.get(near_label), label_to_es.get(far_label)
        if es_near is None or es_far is None:
            continue

        spread_hist = await history_service.get_metric_history(session, underlying.id, "calendar_spread", f"{near_label}_{far_label}")
        fv_result: ForwardVolResult | None = None
        try:
            fv_result = forward_vol(es_near.smile.atm_iv, es_near.t_years, es_far.smile.atm_iv, es_far.t_years)
        except ValueError:
            fv_result = None

        no_arb = [check_calendar_variance(fv_result, near_label, far_label)] if fv_result else []
        cal_candidate = opportunity_calendar(
            near_label, far_label, es_near.smile.atm_iv, es_far.smile.atm_iv, spread_hist,
            settings.zscore_extreme_threshold, fv_result,
        )
        await _register(session, underlying, cal_candidate, {near_label: es_near, far_label: es_far}, es_far.expiry_id, settings, no_arb)

        if fv_result is not None and fv_result.valid:
            fwd_hist = await history_service.get_metric_history(session, underlying.id, "forward_vol", f"{near_label}_{far_label}")
            fwd_candidate = opportunity_forward_vol(near_label, far_label, fv_result.forward_vol, fwd_hist, settings.zscore_extreme_threshold)
            await _register(session, underlying, fwd_candidate, {near_label: es_near, far_label: es_far}, es_far.expiry_id, settings)

    await session.commit()
    return 1
