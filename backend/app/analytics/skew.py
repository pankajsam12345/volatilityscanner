"""IV skew (§12): put/call wings relative to ATM, and put-call skew, per delta bucket."""
from __future__ import annotations


def skew_metrics(delta_grid_ivs: dict[str, float | None], atm_iv: float | None, deltas: list[int]) -> dict:
    out: dict[str, float | None] = {}
    for d in deltas:
        put_iv = delta_grid_ivs.get(f"put_{d}d_iv")
        call_iv = delta_grid_ivs.get(f"call_{d}d_iv")
        put_wing = (put_iv - atm_iv) if (put_iv is not None and atm_iv is not None) else None
        call_wing = (call_iv - atm_iv) if (call_iv is not None and atm_iv is not None) else None
        skew = (put_iv - call_iv) if (put_iv is not None and call_iv is not None) else None
        out[f"put_wing_{d}"] = put_wing
        out[f"call_wing_{d}"] = call_wing
        out[f"skew_{d}"] = skew
    return out
