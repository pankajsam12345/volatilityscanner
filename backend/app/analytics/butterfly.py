"""Butterfly (§14): BF_d = 0.5*(IV(dΔ Put) + IV(dΔ Call)) - ATM IV, for configurable delta buckets."""
from __future__ import annotations


def butterfly_metrics(
    delta_grid_ivs: dict[str, float | None], atm_iv: float | None, deltas: list[int]
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for d in deltas:
        put_iv = delta_grid_ivs.get(f"put_{d}d_iv")
        call_iv = delta_grid_ivs.get(f"call_{d}d_iv")
        if put_iv is not None and call_iv is not None and atm_iv is not None:
            out[f"bf_{d}"] = 0.5 * (put_iv + call_iv) - atm_iv
        else:
            out[f"bf_{d}"] = None
    return out
