"""
Shared historical-distribution statistics (§18): every "current value vs its
own history" comparison in the app (ATM IV, IV-RV, skew, RR, BF, calendar
spread, forward vol, term-structure slope/curvature) goes through here so
the definition of z-score/percentile is consistent everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class DistributionContext:
    current: float
    mean: float
    median: float
    std: float
    min: float
    max: float
    percentile: float  # 0-100: % of historical observations <= current
    zscore: float
    sample_size: int


def zscore(current: float, history: Sequence[float]) -> float | None:
    arr = np.asarray([h for h in history if h is not None], dtype=float)
    if arr.size < 2:
        return None
    std = arr.std(ddof=1)
    if std == 0:
        return 0.0
    return float((current - arr.mean()) / std)


def percentile_rank(current: float, history: Sequence[float]) -> float | None:
    """% of historical observations at or below `current` (0-100)."""
    arr = np.asarray([h for h in history if h is not None], dtype=float)
    if arr.size == 0:
        return None
    return float((arr <= current).sum() / arr.size * 100)


def distribution_context(current: float, history: Sequence[float]) -> DistributionContext | None:
    arr = np.asarray([h for h in history if h is not None], dtype=float)
    if arr.size < 2:
        return None
    return DistributionContext(
        current=float(current),
        mean=float(arr.mean()),
        median=float(np.median(arr)),
        std=float(arr.std(ddof=1)),
        min=float(arr.min()),
        max=float(arr.max()),
        percentile=float((arr <= current).sum() / arr.size * 100),
        zscore=float((current - arr.mean()) / arr.std(ddof=1)) if arr.std(ddof=1) > 0 else 0.0,
        sample_size=int(arr.size),
    )
