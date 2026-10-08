"""Risk reversal (§13): RR_d = IV(dΔ Call) - IV(dΔ Put), for configurable delta buckets."""
from __future__ import annotations


def risk_reversal_metrics(delta_grid_ivs: dict[str, float | None], deltas: list[int]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for d in deltas:
        put_iv = delta_grid_ivs.get(f"put_{d}d_iv")
        call_iv = delta_grid_ivs.get(f"call_{d}d_iv")
        out[f"rr_{d}"] = (call_iv - put_iv) if (put_iv is not None and call_iv is not None) else None
    return out
