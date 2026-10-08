import math

import pytest

from app.analytics.term_structure import forward_variance, forward_vol


def test_forward_vol_matches_spec_example():
    # §9 example: 1M IV=14%, 3M IV=18% -> forward vol from 1M to 3M
    t1, t2 = 1 / 12, 3 / 12
    sigma1, sigma2 = 0.14, 0.18
    result = forward_vol(sigma1, t1, sigma2, t2)
    assert result.valid
    expected_var = (sigma2 ** 2 * t2 - sigma1 ** 2 * t1) / (t2 - t1)
    assert abs(result.forward_variance - expected_var) < 1e-12
    assert abs(result.forward_vol - math.sqrt(expected_var)) < 1e-12
    # Forward vol from 1M->3M should exceed the 3M spot vol here since IV is rising with tenor
    assert result.forward_vol > sigma2


def test_forward_vol_negative_variance_flagged_not_raised():
    # Near-term IV far higher than far-term IV over a short far tenor can make
    # the implied forward variance negative — must be flagged, not silently sqrt'd.
    t1, t2 = 0.25, 0.30
    sigma1, sigma2 = 0.60, 0.20
    result = forward_vol(sigma1, t1, sigma2, t2)
    assert not result.valid
    assert result.forward_vol is None
    assert result.error is not None


def test_forward_variance_requires_t2_greater_than_t1():
    with pytest.raises(ValueError):
        forward_variance(0.2, 0.5, 0.18, 0.25)
