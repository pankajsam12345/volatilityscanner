"""
Opportunity generators (§21). Each function turns a relative-value
deviation into a concrete, directional candidate structure — never a bare
"IV is high, sell it" heuristic. Every candidate carries the RelativeValueSignal
that produced it (observed/fair/deviation/z-score/percentile) so the caller
(opportunities/pipeline.py) can attach liquidity, transaction cost, score,
and a WHY/RISK narrative before anything is shown to a user.

Opportunities H (calendar-arbitrage) and I (butterfly-arbitrage) from the
spec are intentionally NOT separate generators here — they're no-arbitrage
*flags* (app.analytics.no_arbitrage) attached to the Calendar/Butterfly
candidates below, per spec §21/§53: "Do NOT label something as risk-free
arbitrage unless mathematical arbitrage conditions are actually satisfied."
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.analytics.fair_value import historical_mean_fair_value, iv_rv_fair_spread
from app.analytics.relative_value import RelativeValueSignal, evaluate_relative_value
from app.analytics.term_structure import ForwardVolResult


@dataclass(frozen=True)
class OpportunityLeg:
    description: str
    action: str  # BUY | SELL
    tenor_label: str
    delta_bucket: str
    option_type: str | None
    iv: float | None


@dataclass(frozen=True)
class OpportunityCandidate:
    strategy: str
    signal_type: str
    direction: str
    signal: RelativeValueSignal
    legs: list[OpportunityLeg]
    gross_edge: float
    extra_context: list[str] = field(default_factory=list)


def _deviation_magnitude(signal: RelativeValueSignal) -> float:
    if signal.deviation is not None:
        return abs(signal.deviation)
    if signal.history is not None:
        return abs(signal.observed - signal.history.mean)
    return 0.0


# All IV-derived metrics (ATM IV, skew, RR, BF, calendar spread, forward vol)
# are decimal fractions everywhere in the analytics layer (0.095 = 9.5%,
# matching the IV solver/Greeks convention). §22's transaction-cost model and
# every "+2.3 vol" figure in the spec's worked examples are denominated in
# *vol points* (percentage points: 1.00 = 1 percentage point of IV). Convert
# at this boundary — the one place decimal-fraction analytics numbers become
# user-facing "vol point" edge/cost figures — so gross_edge nets correctly
# against settings.slippage_vol_points etc. without a silent 100x unit bug.
_VOL_POINT_SCALE = 100.0


def _vp(x: float | None) -> float | None:
    return None if x is None else x * _VOL_POINT_SCALE


def _vp_series(xs: list[float]) -> list[float]:
    return [x * _VOL_POINT_SCALE for x in xs if x is not None]


def opportunity_iv_vs_rv(
    tenor_label: str, atm_iv: float, rv_reference: float,
    iv_history: list[float], rv_history: list[float], zscore_threshold: float,
) -> OpportunityCandidate | None:
    observed_spread = atm_iv - rv_reference
    spread_history = [iv - rv for iv, rv in zip(iv_history, rv_history) if iv is not None and rv is not None]
    fair_spread, model = iv_rv_fair_spread(rv_history, iv_history, rv_reference)
    signal = evaluate_relative_value(
        f"{tenor_label} IV-RV spread", _vp(observed_spread), _vp_series(spread_history), _vp(fair_spread), model, zscore_threshold,
    )

    if signal.signal in ("NEUTRAL", "INSUFFICIENT_DATA"):
        return None

    edge = _deviation_magnitude(signal)
    if signal.signal == "RICH":
        direction = f"SHORT_{tenor_label}_VOL"
        legs = [OpportunityLeg(f"SELL {tenor_label} ATM straddle/strangle", "SELL", tenor_label, "ATM", None, atm_iv)]
    else:
        direction = f"LONG_{tenor_label}_VOL"
        legs = [OpportunityLeg(f"BUY {tenor_label} ATM straddle/strangle", "BUY", tenor_label, "ATM", None, atm_iv)]

    return OpportunityCandidate("IV_VS_RV", "IV_RV_SPREAD", direction, signal, legs, edge)


def opportunity_calendar(
    near_label: str, far_label: str, near_iv: float, far_iv: float,
    spread_history: list[float], zscore_threshold: float, forward_vol: ForwardVolResult | None = None,
) -> OpportunityCandidate | None:
    observed = far_iv - near_iv
    fair = historical_mean_fair_value(spread_history)
    signal = evaluate_relative_value(
        f"Calendar {near_label}->{far_label}", _vp(observed), _vp_series(spread_history), _vp(fair), "historical_mean", zscore_threshold,
    )

    if signal.signal in ("NEUTRAL", "INSUFFICIENT_DATA"):
        return None

    edge = _deviation_magnitude(signal)
    extra = []
    if forward_vol is not None and not forward_vol.valid:
        extra.append(
            f"Forward variance between {near_label} and {far_label} is negative ({forward_vol.error}) — "
            "a no-arbitrage/data-quality flag; treat this signal with reduced confidence."
        )

    if signal.signal == "CHEAP":  # near relatively rich vs far
        direction = f"SELL_{near_label}_BUY_{far_label}_VOL"
        legs = [
            OpportunityLeg(f"SELL {near_label} ATM vol", "SELL", near_label, "ATM", None, near_iv),
            OpportunityLeg(f"BUY {far_label} ATM vol", "BUY", far_label, "ATM", None, far_iv),
        ]
    else:  # RICH: far relatively rich vs near
        direction = f"BUY_{near_label}_SELL_{far_label}_VOL"
        legs = [
            OpportunityLeg(f"BUY {near_label} ATM vol", "BUY", near_label, "ATM", None, near_iv),
            OpportunityLeg(f"SELL {far_label} ATM vol", "SELL", far_label, "ATM", None, far_iv),
        ]

    return OpportunityCandidate("CALENDAR", "CALENDAR_SPREAD", direction, signal, legs, edge, extra)


def opportunity_risk_reversal(
    tenor_label: str, delta_bucket: int, rr_value: float, put_iv: float, call_iv: float,
    rr_history: list[float], zscore_threshold: float,
) -> OpportunityCandidate | None:
    fair = historical_mean_fair_value(rr_history)
    signal = evaluate_relative_value(
        f"{tenor_label} {delta_bucket}d Risk Reversal", _vp(rr_value), _vp_series(rr_history), _vp(fair), "historical_mean", zscore_threshold,
    )

    if signal.signal in ("NEUTRAL", "INSUFFICIENT_DATA"):
        return None

    edge = _deviation_magnitude(signal)
    if signal.signal == "RICH":  # calls unusually rich vs puts
        direction = f"SELL_{delta_bucket}D_CALL_BUY_{delta_bucket}D_PUT"
        legs = [
            OpportunityLeg(f"SELL {delta_bucket}Δ call", "SELL", tenor_label, str(delta_bucket), "CALL", call_iv),
            OpportunityLeg(f"BUY {delta_bucket}Δ put", "BUY", tenor_label, str(delta_bucket), "PUT", put_iv),
        ]
    else:  # puts unusually rich vs calls
        direction = f"SELL_{delta_bucket}D_PUT_BUY_{delta_bucket}D_CALL"
        legs = [
            OpportunityLeg(f"SELL {delta_bucket}Δ put", "SELL", tenor_label, str(delta_bucket), "PUT", put_iv),
            OpportunityLeg(f"BUY {delta_bucket}Δ call", "BUY", tenor_label, str(delta_bucket), "CALL", call_iv),
        ]

    return OpportunityCandidate("RISK_REVERSAL", "RISK_REVERSAL", direction, signal, legs, edge)


def opportunity_butterfly(
    tenor_label: str, delta_bucket: int, bf_value: float, put_iv: float, call_iv: float, atm_iv: float,
    bf_history: list[float], zscore_threshold: float, convexity_flag_passed: bool = True,
) -> OpportunityCandidate | None:
    fair = historical_mean_fair_value(bf_history)
    signal = evaluate_relative_value(
        f"{tenor_label} {delta_bucket}d Butterfly", _vp(bf_value), _vp_series(bf_history), _vp(fair), "historical_mean", zscore_threshold,
    )

    if signal.signal in ("NEUTRAL", "INSUFFICIENT_DATA"):
        return None

    edge = _deviation_magnitude(signal)
    extra = []
    if not convexity_flag_passed:
        extra.append("Butterfly value falls outside the expected convexity tolerance — smile-consistency flag, treat with reduced confidence.")

    if signal.signal == "RICH":  # wings expensive vs atm
        direction = f"SELL_{delta_bucket}D_BUTTERFLY"
        legs = [
            OpportunityLeg(f"SELL {delta_bucket}Δ put wing", "SELL", tenor_label, str(delta_bucket), "PUT", put_iv),
            OpportunityLeg(f"SELL {delta_bucket}Δ call wing", "SELL", tenor_label, str(delta_bucket), "CALL", call_iv),
            OpportunityLeg("BUY 2x ATM", "BUY", tenor_label, "ATM", None, atm_iv),
        ]
    else:  # wings cheap vs atm
        direction = f"BUY_{delta_bucket}D_BUTTERFLY"
        legs = [
            OpportunityLeg(f"BUY {delta_bucket}Δ put wing", "BUY", tenor_label, str(delta_bucket), "PUT", put_iv),
            OpportunityLeg(f"BUY {delta_bucket}Δ call wing", "BUY", tenor_label, str(delta_bucket), "CALL", call_iv),
            OpportunityLeg("SELL 2x ATM", "SELL", tenor_label, "ATM", None, atm_iv),
        ]

    return OpportunityCandidate("BUTTERFLY", "BUTTERFLY", direction, signal, legs, edge, extra)


def opportunity_skew(
    tenor_label: str, delta_bucket: int, put_wing_value: float, put_iv: float, atm_iv: float,
    put_wing_history: list[float], zscore_threshold: float,
) -> OpportunityCandidate | None:
    fair = historical_mean_fair_value(put_wing_history)
    signal = evaluate_relative_value(
        f"{tenor_label} {delta_bucket}d put wing", _vp(put_wing_value), _vp_series(put_wing_history), _vp(fair), "historical_mean", zscore_threshold,
    )

    if signal.signal in ("NEUTRAL", "INSUFFICIENT_DATA"):
        return None

    edge = _deviation_magnitude(signal)
    if signal.signal == "RICH":  # put skew unusually steep
        direction = f"SELL_{delta_bucket}D_PUT_SKEW"
        legs = [
            OpportunityLeg(f"SELL {delta_bucket}Δ put", "SELL", tenor_label, str(delta_bucket), "PUT", put_iv),
            OpportunityLeg("BUY ATM (delta hedge)", "BUY", tenor_label, "ATM", None, atm_iv),
        ]
    else:  # put skew unusually flat/cheap
        direction = f"BUY_{delta_bucket}D_PUT_SKEW"
        legs = [
            OpportunityLeg(f"BUY {delta_bucket}Δ put", "BUY", tenor_label, str(delta_bucket), "PUT", put_iv),
            OpportunityLeg("SELL ATM (delta hedge)", "SELL", tenor_label, "ATM", None, atm_iv),
        ]

    return OpportunityCandidate("SKEW", "PUT_SKEW", direction, signal, legs, edge)


def opportunity_forward_vol(
    near_label: str, far_label: str, forward_vol_value: float,
    forward_vol_history: list[float], zscore_threshold: float,
) -> OpportunityCandidate | None:
    fair = historical_mean_fair_value(forward_vol_history)
    signal = evaluate_relative_value(
        f"{near_label}->{far_label} forward vol", _vp(forward_vol_value), _vp_series(forward_vol_history), _vp(fair), "historical_mean", zscore_threshold,
    )

    if signal.signal in ("NEUTRAL", "INSUFFICIENT_DATA"):
        return None

    edge = _deviation_magnitude(signal)
    direction = f"FORWARD_VOL_{signal.signal}_{near_label}_{far_label}"
    legs = [
        OpportunityLeg(f"Implied via calendar: {near_label}/{far_label}", "N/A", near_label, "ATM", None, None),
    ]
    extra = ["Forward vol is a model construct, not directly tradeable — realize this view via the corresponding calendar structure."]
    return OpportunityCandidate("FORWARD_VOL", "FORWARD_VOL", direction, signal, legs, edge, extra)
