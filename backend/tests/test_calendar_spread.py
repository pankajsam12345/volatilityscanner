from app.analytics.calendar import calendar_matrix, calendar_spread


def test_calendar_spread_matches_spec_example():
    # §15 example: 1M ATM IV=16%, 3M ATM IV=17% -> Calendar = +1 vol
    spread = calendar_spread(near_iv=0.16, far_iv=0.17)
    assert abs(spread - 0.01) < 1e-9


def test_calendar_matrix_covers_every_pair():
    expiries = [("1M", 1 / 12, 0.16), ("2M", 2 / 12, 0.165), ("3M", 3 / 12, 0.17)]
    cells = calendar_matrix(expiries)
    pairs = {(c.near_label, c.far_label) for c in cells}
    assert pairs == {("1M", "2M"), ("1M", "3M"), ("2M", "3M")}
    assert len(cells) == 3


def test_calendar_matrix_cell_has_forward_vol_when_valid():
    expiries = [("1M", 1 / 12, 0.14), ("3M", 3 / 12, 0.18)]
    cells = calendar_matrix(expiries)
    assert len(cells) == 1
    cell = cells[0]
    assert cell.forward_vol_valid
    assert cell.forward_vol is not None
    assert abs(cell.calendar_spread - 0.04) < 1e-9
