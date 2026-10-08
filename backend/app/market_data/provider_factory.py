from functools import lru_cache

from app.core.config import get_settings
from app.market_data.base import MarketDataProvider
from app.market_data.breeze_provider import BreezeProvider
from app.market_data.csv_provider import CSVProvider
from app.market_data.mock_provider import MockProvider


@lru_cache
def get_market_data_provider() -> MarketDataProvider:
    settings = get_settings()
    provider = settings.market_data_provider.upper()
    if provider == "CSV":
        return CSVProvider(settings.csv_data_dir)
    if provider == "BREEZE":
        return BreezeProvider(
            api_key=settings.breeze_api_key,
            api_secret=settings.breeze_api_secret,
            session_token=settings.breeze_session_token,
            symbol_map=settings.breeze_symbol_map,
            exchange_code=settings.breeze_exchange_code,
            cash_exchange_code=settings.breeze_cash_exchange_code,
        )
    return MockProvider()
