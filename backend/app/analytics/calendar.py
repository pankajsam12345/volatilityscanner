"""Calendar spread analysis (§15): pairwise ATM IV spread + forward vol across every expiry pair."""
from __future__ import annotations

from dataclasses import dataclass

from app.analytics.term_structure import forward_vol


@dataclass(frozen=True)
class CalendarCell:
    near_label: str
    far_label: str
    near_t: float
    far_t: float
    near_iv: float
    far_iv: float
    calendar_spread: float  # far_iv - near_iv, "far vol over near vol"
    forward_vol: float | None
    forward_vol_valid: bool


def calendar_spread(near_iv: float, far_iv: float) -> float:
    return far_iv - near_iv


def calendar_matrix(expiries: list[tuple[str, float, float]]) -> list[CalendarCell]:
    """expiries: [(label, T_years, atm_iv), ...], any order. Produces every near<far pair."""
    ordered = sorted(expiries, key=lambda e: e[1])
    cells: list[CalendarCell] = []
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            near_label, near_t, near_iv = ordered[i]
            far_label, far_t, far_iv = ordered[j]
            fv = forward_vol(near_iv, near_t, far_iv, far_t)
            cells.append(
                CalendarCell(
                    near_label=near_label,
                    far_label=far_label,
                    near_t=near_t,
                    far_t=far_t,
                    near_iv=near_iv,
                    far_iv=far_iv,
                    calendar_spread=calendar_spread(near_iv, far_iv),
                    forward_vol=fv.forward_vol,
                    forward_vol_valid=fv.valid,
                )
            )
    return cells
