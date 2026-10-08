import datetime as dt

from scripts.seed import _expiry_for_day, _monthly_expiry_ladder


def test_ladder_covers_full_range_with_no_weekend_dates():
    start = dt.date(2025, 1, 1)
    end = dt.date(2025, 6, 30)
    ladder = _monthly_expiry_ladder(start, end)
    assert ladder[-1] > end
    assert all(d.weekday() < 5 for d in ladder)
    assert ladder == sorted(ladder)


def test_ladder_is_roughly_monthly_cadence():
    ladder = _monthly_expiry_ladder(dt.date(2025, 1, 1), dt.date(2025, 12, 31))
    gaps = [(b - a).days for a, b in zip(ladder, ladder[1:])]
    assert all(28 <= g <= 32 for g in gaps)


def test_expiry_for_day_picks_nearest_upcoming_date():
    ladder = [dt.date(2025, 1, 30), dt.date(2025, 3, 3), dt.date(2025, 3, 31)]
    assert _expiry_for_day(ladder, dt.date(2025, 1, 1)) == dt.date(2025, 1, 30)
    assert _expiry_for_day(ladder, dt.date(2025, 1, 30)) == dt.date(2025, 3, 3)
    assert _expiry_for_day(ladder, dt.date(2025, 3, 3)) == dt.date(2025, 3, 31)


def test_expiry_for_day_rolls_forward_across_the_whole_range():
    ladder = _monthly_expiry_ladder(dt.date(2025, 1, 1), dt.date(2025, 12, 31))
    seen = set()
    d = dt.date(2025, 1, 1)
    while d <= dt.date(2025, 12, 31):
        expiry = _expiry_for_day(ladder, d)
        assert expiry > d
        seen.add(expiry)
        d += dt.timedelta(days=1)
    assert len(seen) >= 11  # ~one new expiry roughly every 30 days across a year
