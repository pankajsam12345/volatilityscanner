"""
Forward volatility extraction and term-structure shape analysis (§9/§10).

ForwardVariance = (sigma2^2 * T2 - sigma1^2 * T1) / (T2 - T1)
ForwardVol      = sqrt(ForwardVariance)

A negative forward variance is a no-arbitrage violation in the variance
term structure (§53) — flagged, never silently sqrt'd.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

RegimeLabel = Literal["CONTANGO", "BACKWARDATION", "MIXED"]


@dataclass(frozen=True)
class ForwardVolResult:
    forward_variance: float
    forward_vol: float | None
    valid: bool
    error: str | None = None


def forward_variance(sigma1: float, t1: float, sigma2: float, t2: float) -> float:
    if t2 <= t1:
        raise ValueError("t2 must be greater than t1")
    return (sigma2 ** 2 * t2 - sigma1 ** 2 * t1) / (t2 - t1)


def forward_vol(sigma1: float, t1: float, sigma2: float, t2: float) -> ForwardVolResult:
    fv = forward_variance(sigma1, t1, sigma2, t2)
    if fv < 0:
        return ForwardVolResult(
            forward_variance=fv, forward_vol=None, valid=False,
            error="Negative forward variance: near-term IV too high relative to far-term IV for this T1/T2 pair",
        )
    return ForwardVolResult(forward_variance=fv, forward_vol=math.sqrt(fv), valid=True)


def term_structure_slope(points: list[tuple[float, float]]) -> float | None:
    """points: [(T_years, atm_iv), ...]. Slope of a linear fit, IV per year."""
    if len(points) < 2:
        return None
    ts = np.array([p[0] for p in points])
    ivs = np.array([p[1] for p in points])
    slope, _ = np.polyfit(ts, ivs, 1)
    return float(slope)


def term_structure_curvature(points: list[tuple[float, float]]) -> float | None:
    """Quadratic coefficient of a degree-2 fit; captures convex/concave term structure."""
    if len(points) < 3:
        return None
    ts = np.array([p[0] for p in points])
    ivs = np.array([p[1] for p in points])
    a, _, _ = np.polyfit(ts, ivs, 2)
    return float(a)


def classify_regime(points: list[tuple[float, float]], tolerance: float = 0.0025) -> RegimeLabel:
    """points sorted by T ascending. tolerance in vol points (e.g. 0.0025 = 0.25 vol pt)."""
    pts = sorted(points, key=lambda p: p[0])
    diffs = [pts[i + 1][1] - pts[i][1] for i in range(len(pts) - 1)]
    if all(d >= -tolerance for d in diffs) and any(d > tolerance for d in diffs):
        return "CONTANGO"
    if all(d <= tolerance for d in diffs) and any(d < -tolerance for d in diffs):
        return "BACKWARDATION"
    return "MIXED"


def detect_local_inversions(points: list[tuple[float, float]], threshold: float = 0.01) -> list[float]:
    """
    Returns the T values of expiries whose ATM IV deviates from the average
    of its immediate neighbors by more than `threshold` (vol points) —
    candidates for a local term-structure inversion (§10).
    """
    pts = sorted(points, key=lambda p: p[0])
    flagged = []
    for i in range(1, len(pts) - 1):
        neighbor_avg = (pts[i - 1][1] + pts[i + 1][1]) / 2
        if abs(pts[i][1] - neighbor_avg) > threshold:
            flagged.append(pts[i][0])
    return flagged
