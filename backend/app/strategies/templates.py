"""
Strategy templates (§34): each resolves to a concrete list of
StrategyLegSpec at a single expiry, which builder.analyze_strategy then
prices uniformly. Calendar/Diagonal are intentionally NOT here — they're
inherently cross-expiry and are already covered by the Calendar Analyzer
page (§32, /api/calendar); folding them into a single-expiry payoff diagram
would be misleading (the near leg expires before the far leg).
"""
from __future__ import annotations

from app.strategies.builder import StrategyLegSpec

TEMPLATES = {
    "straddle": {
        "label": "Straddle",
        "description": "Buy or sell an ATM call and an ATM put — a pure bet on realized volatility.",
        "build": lambda action="BUY", delta=0.5: [
            StrategyLegSpec("CALL", delta, action), StrategyLegSpec("PUT", delta, action),
        ],
    },
    "strangle": {
        "label": "Strangle",
        "description": "Buy or sell an OTM call and an OTM put — cheaper than a straddle, needs a bigger move.",
        "build": lambda action="BUY", call_delta=0.25, put_delta=0.25: [
            StrategyLegSpec("CALL", call_delta, action), StrategyLegSpec("PUT", put_delta, action),
        ],
    },
    "iron_condor": {
        "label": "Iron Condor",
        "description": "Sell a call and a put closer to ATM, buy further-OTM wings to cap risk.",
        "build": lambda short_delta=0.25, wing_delta=0.10: [
            StrategyLegSpec("CALL", short_delta, "SELL"), StrategyLegSpec("CALL", wing_delta, "BUY"),
            StrategyLegSpec("PUT", short_delta, "SELL"), StrategyLegSpec("PUT", wing_delta, "BUY"),
        ],
    },
    "butterfly": {
        "label": "Butterfly (calls)",
        "description": "Buy 1 near-the-money call, sell 2 ATM calls, buy 1 further OTM call.",
        "build": lambda near_delta=0.35, wing_delta=0.15: [
            StrategyLegSpec("CALL", near_delta, "BUY"),
            StrategyLegSpec("CALL", 0.5, "SELL", quantity=2),
            StrategyLegSpec("CALL", wing_delta, "BUY"),
        ],
    },
    "risk_reversal_bullish": {
        "label": "Risk Reversal (Bullish)",
        "description": "Sell an OTM put, buy an OTM call — synthetic long exposure funded by the put.",
        "build": lambda delta=0.25: [
            StrategyLegSpec("PUT", delta, "SELL"), StrategyLegSpec("CALL", delta, "BUY"),
        ],
    },
    "risk_reversal_bearish": {
        "label": "Risk Reversal (Bearish)",
        "description": "Buy an OTM put, sell an OTM call — synthetic short exposure funded by the call.",
        "build": lambda delta=0.25: [
            StrategyLegSpec("PUT", delta, "BUY"), StrategyLegSpec("CALL", delta, "SELL"),
        ],
    },
    "bull_call_spread": {
        "label": "Bull Call Spread",
        "description": "Buy a near-the-money call, sell a further OTM call — defined-risk bullish view.",
        "build": lambda near_delta=0.5, far_delta=0.25: [
            StrategyLegSpec("CALL", near_delta, "BUY"), StrategyLegSpec("CALL", far_delta, "SELL"),
        ],
    },
    "bear_put_spread": {
        "label": "Bear Put Spread",
        "description": "Buy a near-the-money put, sell a further OTM put — defined-risk bearish view.",
        "build": lambda near_delta=0.5, far_delta=0.25: [
            StrategyLegSpec("PUT", near_delta, "BUY"), StrategyLegSpec("PUT", far_delta, "SELL"),
        ],
    },
}


def list_templates() -> list[dict]:
    return [{"key": key, "label": t["label"], "description": t["description"]} for key, t in TEMPLATES.items()]


def build_template_legs(key: str, **kwargs) -> list[StrategyLegSpec]:
    if key not in TEMPLATES:
        raise ValueError(f"Unknown template '{key}'. Available: {list(TEMPLATES)}")
    return TEMPLATES[key]["build"](**kwargs)
