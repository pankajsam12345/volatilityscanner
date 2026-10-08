"""
Finalizes an OpportunityCandidate (app.opportunities.strategies) into
something ready to persist/serve: attaches liquidity, transaction cost,
a transparent component score, and a WHY/RISKS explanation (§21/§24/§25).

`max_risk` here is a **simplified heuristic** (breakeven cost scaled by a
structure-type multiplier), not a real margin/VaR calculation — that's the
Risk Engine / Monte Carlo work explicitly deferred to a later phase (see
README "Known Limitations"). Never presented to the user as a guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analytics.no_arbitrage import NoArbFlag
from app.costs.transaction_cost import LegCost, StrategyCost, leg_transaction_cost, strategy_transaction_cost
from app.liquidity.filters import LiquidityAssessment, aggregate_liquidity, assess_leg_liquidity, liquidity_score
from app.opportunities.explain import build_risks, build_why
from app.opportunities.scoring import (
    ScoreBreakdown,
    cost_efficiency_score,
    historical_consistency_score,
    model_confidence_score,
    risk_score,
    score_opportunity,
    statistical_edge_score,
)
from app.opportunities.strategies import OpportunityCandidate

UNDEFINED_RISK_STRATEGIES = {"IV_VS_RV", "SKEW", "RISK_REVERSAL", "FORWARD_VOL"}


@dataclass(frozen=True)
class LegMarketData:
    bid: float
    ask: float
    vega: float | None
    lot_size: int
    volume: int
    open_interest: int


@dataclass(frozen=True)
class FinalizedOpportunity:
    strategy: str
    signal_type: str
    direction: str
    score: ScoreBreakdown
    confidence: float
    gross_edge: float
    transaction_cost: float
    net_edge: float
    max_risk: float
    expected_return: float
    risk_reward: float
    liquidity_status: str
    data_quality: str
    legs: list[dict]
    historical_context: dict
    no_arbitrage_flags: list[dict]
    why: list[str]
    risks: list[str]


def finalize_opportunity(
    candidate: OpportunityCandidate,
    leg_market_data: list[LegMarketData],
    settings,
    no_arb_flags: list[NoArbFlag] | None = None,
    data_quality: str = "GOOD",
) -> FinalizedOpportunity:
    no_arb_flags = no_arb_flags or []

    leg_liquidity: list[LiquidityAssessment] = [
        assess_leg_liquidity(l.bid, l.ask, l.volume, l.open_interest, settings) for l in leg_market_data
    ]
    overall_liquidity = aggregate_liquidity([la.status for la in leg_liquidity]) if leg_liquidity else "REJECTED"
    liq_score = liquidity_score(overall_liquidity)

    leg_costs: list[LegCost] = [
        leg_transaction_cost(l.bid, l.ask, l.vega, l.lot_size, settings) for l in leg_market_data
    ]
    strategy_cost: StrategyCost = strategy_transaction_cost(candidate.gross_edge, leg_costs, settings)

    failed_flags = sum(1 for f in no_arb_flags if not f.passed)
    risk_multiplier = 4.0 if candidate.strategy in UNDEFINED_RISK_STRATEGIES else 1.5
    max_risk = max(strategy_cost.breakeven_cost * risk_multiplier, 0.01)
    expected_return = max(strategy_cost.net_edge, 0.0)
    risk_reward = strategy_cost.net_edge / max_risk if max_risk > 0 else 0.0

    hist = candidate.signal.history
    statistical_edge = statistical_edge_score(hist.zscore if hist else None, cap=settings.zscore_extreme_threshold * 1.5)
    historical_consistency = historical_consistency_score(hist.percentile if hist else None)
    cost_eff = cost_efficiency_score(strategy_cost.net_edge, strategy_cost.gross_edge)
    model_conf = model_confidence_score(hist.sample_size if hist else 0, failed_flags, data_quality, settings.percentile_lookback_days)
    risk_norm = min(0.5 + 0.1 * failed_flags + (0.2 if overall_liquidity in ("LOW", "REJECTED") else 0.0), 1.0)
    if candidate.strategy not in UNDEFINED_RISK_STRATEGIES:
        risk_norm = max(risk_norm - 0.25, 0.05)
    risk_sc = risk_score(risk_norm)

    score = score_opportunity(statistical_edge, historical_consistency, liq_score, cost_eff, model_conf, risk_sc, settings.score_weights)

    why = build_why(candidate.signal, candidate.extra_context)
    risks = build_risks(candidate.signal_type, None)

    historical_context = {
        "metric": candidate.signal.metric_name,
        "observed": candidate.signal.observed,
        "fair_value": candidate.signal.fair_value,
        "fair_value_model": candidate.signal.fair_value_model,
        "deviation": candidate.signal.deviation,
        "zscore": hist.zscore if hist else None,
        "percentile": hist.percentile if hist else None,
        "mean": hist.mean if hist else None,
        "median": hist.median if hist else None,
        "std": hist.std if hist else None,
        "sample_size": hist.sample_size if hist else 0,
    }

    legs = [
        {
            "description": leg.description, "action": leg.action, "tenor": leg.tenor_label,
            "delta_bucket": leg.delta_bucket, "option_type": leg.option_type, "iv": leg.iv,
            "liquidity": la.status, "spread_pct": la.spread_pct,
        }
        for leg, la in zip(candidate.legs, leg_liquidity)
    ]

    return FinalizedOpportunity(
        strategy=candidate.strategy, signal_type=candidate.signal_type, direction=candidate.direction,
        score=score, confidence=round(model_conf, 1),
        gross_edge=strategy_cost.gross_edge, transaction_cost=strategy_cost.breakeven_cost,
        net_edge=strategy_cost.net_edge, max_risk=max_risk, expected_return=expected_return,
        risk_reward=risk_reward, liquidity_status=overall_liquidity, data_quality=data_quality,
        legs=legs, historical_context=historical_context,
        no_arbitrage_flags=[{"check": f.check, "passed": f.passed, "detail": f.detail} for f in no_arb_flags],
        why=why, risks=risks,
    )
