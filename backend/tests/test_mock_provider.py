import datetime as dt

import pytest

from app.market_data.mock_provider import MockProvider
from app.market_data.vol_surface_model import state_to_surface, surface_to_state


@pytest.mark.asyncio
async def test_underlying_quote_returns_positive_spot():
    provider = MockProvider(seed=1)
    quote = await provider.get_underlying_quote("NIFTY")
    assert quote.spot_price > 0
    assert quote.symbol == "NIFTY"


@pytest.mark.asyncio
async def test_unknown_symbol_raises():
    provider = MockProvider(seed=1)
    with pytest.raises(ValueError):
        await provider.get_underlying_quote("NOT_A_SYMBOL")


@pytest.mark.asyncio
async def test_expiries_are_in_the_future_and_sorted():
    provider = MockProvider(seed=1)
    expiries = await provider.get_expiries("NIFTY")
    assert len(expiries) > 0
    assert all(e.days_to_expiry > 0 for e in expiries)
    days = [e.days_to_expiry for e in expiries]
    assert days == sorted(days)


@pytest.mark.asyncio
async def test_option_chain_has_calls_and_puts_with_valid_quotes():
    provider = MockProvider(seed=1)
    expiries = await provider.get_expiries("NIFTY")
    chain = await provider.get_option_chain("NIFTY", expiries[0].expiry_date)
    assert len(chain) > 0
    assert any(o.option_type == "CALL" for o in chain)
    assert any(o.option_type == "PUT" for o in chain)
    for o in chain:
        assert o.ask >= o.bid > 0
        assert o.source == "DEMO DATA"


@pytest.mark.asyncio
async def test_historical_prices_within_requested_range():
    provider = MockProvider(seed=1)
    end = dt.date.today()
    start = end - dt.timedelta(days=30)
    bars = await provider.get_historical_prices("NIFTY", start, end)
    assert len(bars) > 0
    assert all(start <= b.date <= end for b in bars)
    assert all(b.high >= b.low > 0 for b in bars)


def _next_weekday(d: dt.date) -> dt.date:
    d += dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def test_surface_state_round_trips_through_serialization():
    provider = MockProvider(seed=1)
    as_of, spot, state = provider.export_surface("NIFTY")
    restored = state_to_surface(as_of, spot, state)
    assert restored.as_of == as_of
    assert restored.spot == spot
    assert surface_to_state(restored) == state


def test_advance_to_moves_surface_forward_one_business_day():
    provider = MockProvider(seed=1)
    as_of_before, spot_before, _ = provider.export_surface("NIFTY")
    target = _next_weekday(as_of_before)

    provider.advance_to("NIFTY", target)

    as_of_after, spot_after, _ = provider.export_surface("NIFTY")
    assert as_of_after == target
    assert spot_after != spot_before  # AR(1) step almost surely moves spot


def test_advance_to_same_day_is_a_no_op():
    provider = MockProvider(seed=1)
    as_of_before, spot_before, state_before = provider.export_surface("NIFTY")

    provider.advance_to("NIFTY", as_of_before)

    as_of_after, spot_after, state_after = provider.export_surface("NIFTY")
    assert (as_of_after, spot_after, state_after) == (as_of_before, spot_before, state_before)


def test_advance_to_skips_weekend_and_stops_at_it():
    provider = MockProvider(seed=1)
    as_of_before, spot_before, _ = provider.export_surface("NIFTY")
    saturday = as_of_before
    while saturday.weekday() != 5:
        saturday += dt.timedelta(days=1)

    provider.advance_to("NIFTY", saturday)

    as_of_after, _, _ = provider.export_surface("NIFTY")
    assert as_of_after < saturday
    assert as_of_after.weekday() < 5


def test_sync_surface_always_adopts_the_first_checkpoint_even_if_same_date():
    """
    Regression test: __init__'s init_surface() placeholder is stamped
    dt.date.today() too, so a naive "only accept newer" guard would silently
    reject the very first real checkpoint whenever it shares today's date —
    exactly the common case right after a fresh MockProvider is constructed
    the same day the DB was last updated. This is the bug that made the
    live snapshot refresh always serve the untouched profile baseline
    instead of the persisted, evolved spot.
    """
    provider = MockProvider(seed=1)
    as_of_before, spot_before, state_before = provider.export_surface("NIFTY")

    provider.sync_surface("NIFTY", as_of_before, spot_before + 1000.0, state_before)

    as_of_after, spot_after, _ = provider.export_surface("NIFTY")
    assert as_of_after == as_of_before
    assert spot_after == spot_before + 1000.0


def test_sync_surface_resumes_from_a_newer_checkpoint():
    provider = MockProvider(seed=1)
    as_of_before, _, state_before = provider.export_surface("NIFTY")
    future = as_of_before + dt.timedelta(days=10)

    provider.sync_surface("NIFTY", future, 99999.0, state_before)

    as_of_after, spot_after, state_after = provider.export_surface("NIFTY")
    assert as_of_after == future
    assert spot_after == 99999.0
    assert state_after == state_before


def test_sync_surface_ignores_a_stale_checkpoint_once_already_synced():
    provider = MockProvider(seed=1)
    as_of_before, spot_before, state_before = provider.export_surface("NIFTY")
    future = as_of_before + dt.timedelta(days=10)
    provider.sync_surface("NIFTY", future, 12345.0, state_before)  # establishes _synced

    provider.sync_surface("NIFTY", as_of_before, 99999.0, state_before)  # older than what's loaded

    as_of_after, spot_after, _ = provider.export_surface("NIFTY")
    assert as_of_after == future
    assert spot_after == 12345.0  # the stale 99999.0 checkpoint was rejected
