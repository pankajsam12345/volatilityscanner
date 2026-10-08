"""
Central configuration for the Volatility Opportunity Scanner.

Every "magic number" referenced in the spec (risk-free rate, lookback
windows, liquidity thresholds, transaction-cost assumptions, score weights)
lives here, not hard-coded in the analytics engine, so it can be tuned from
the Settings page / API without touching calculation code.
"""
from functools import lru_cache
from typing import Dict, List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Infra -----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/volscanner"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: List[str] = ["http://localhost:3000"]
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800

    # --- Auth (JWT) --------------------------------------------------------
    jwt_secret_key: str = "CHANGE_ME_dev_only_secret_do_not_use_in_real_prod"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    default_admin_username: str = "admin"
    default_admin_password: str = "admin"

    # --- Rate limiting -------------------------------------------------------
    rate_limit_default: str = "120/minute"
    rate_limit_auth: str = "10/minute"

    # --- Market data provider ------------------------------------------------
    market_data_provider: str = "MOCK"  # "MOCK" | "CSV" | "BREEZE"
    csv_data_dir: str = "data/csv"
    demo_symbols: List[str] = ["NIFTY", "BANKNIFTY", "SPX"]

    # --- ICICI Breeze live provider ------------------------------------------
    # Breeze session tokens are short-lived and require a manual daily
    # browser login (see scripts/breeze_login.py) - there is no safe way to
    # automate this without handling the user's broker OTP/credentials
    # directly, so it is deliberately not attempted here.
    breeze_api_key: str = ""
    breeze_api_secret: str = ""
    breeze_session_token: str = ""
    breeze_exchange_code: str = "NFO"
    breeze_cash_exchange_code: str = "NSE"
    # Our SYMBOL -> ICICI's own stock_code, since they don't always match
    # (e.g. Breeze uses "CNXBAN" for BANKNIFTY, not "BANKNIFTY").
    breeze_symbol_map: Dict[str, str] = {"NIFTY": "NIFTY", "BANKNIFTY": "CNXBAN"}

    # --- Market conventions ------------------------------------------------
    risk_free_rate: float = 0.065
    dividend_yield: float = 0.0
    trading_days_per_year: int = 252
    calendar_days_per_year: int = 365

    # --- Realized vol ------------------------------------------------------
    hv_windows: List[int] = [5, 10, 20, 30, 60, 90, 252]
    ewma_lambda: float = 0.94

    # --- Historical / percentile engine -------------------------------------
    historical_lookback_years: int = 5
    percentile_lookback_days: int = 1260  # ~5y of trading days
    zscore_extreme_threshold: float = 2.0

    # --- Smile / skew / RR / BF ---------------------------------------------
    rr_bf_deltas: List[int] = [10, 15, 25, 30]

    # --- IV solver -----------------------------------------------------------
    iv_solver_max_iter: int = 100
    iv_solver_tol: float = 1e-6
    iv_min_bound: float = 0.001
    iv_max_bound: float = 5.0
    wide_spread_pct_threshold: float = 25.0  # bid-ask / mid, in %

    # --- Liquidity filter ------------------------------------------------------
    min_open_interest: int = 50
    min_volume: int = 10
    max_bid_ask_spread_pct: float = 15.0
    high_liquidity_oi: int = 500
    high_liquidity_volume: int = 200
    high_liquidity_spread_pct: float = 5.0
    medium_liquidity_oi: int = 100
    medium_liquidity_volume: int = 25
    medium_liquidity_spread_pct: float = 10.0

    # --- Transaction cost model ------------------------------------------------
    brokerage_per_lot: float = 20.0
    exchange_fee_pct: float = 0.0005
    tax_pct: float = 0.0006
    slippage_vol_points: float = 0.15
    market_impact_vol_points: float = 0.10
    hedging_cost_vol_points: float = 0.05
    default_lot_size: int = 50
    default_position_size_lots: int = 1

    # --- Opportunity thresholds ------------------------------------------------
    min_net_edge_vol_points: float = 0.5
    min_confidence_pct: float = 60.0
    max_risk_score: float = 80.0

    # --- Opportunity scoring weights (must sum to 1.0; enforced at use-site) ---
    score_weight_statistical_edge: float = 0.30
    score_weight_historical_consistency: float = 0.15
    score_weight_liquidity: float = 0.15
    score_weight_cost_efficiency: float = 0.15
    score_weight_model_confidence: float = 0.15
    score_weight_risk: float = 0.10

    # --- Regime detection (§38) ---------------------------------------------
    regime_low_percentile: float = 25.0
    regime_high_percentile: float = 75.0
    regime_extreme_percentile: float = 95.0

    # --- Backtesting defaults (§36-37) --------------------------------------
    backtest_rolling_window_days: int = 120
    backtest_max_holding_days: int = 20
    backtest_transaction_cost_vol_points: float = 0.35

    # --- Delta-hedge simulator (§17) -----------------------------------------
    hedge_sim_default_days: int = 20
    hedge_sim_default_paths: int = 200
    hedge_sim_cost_bps: float = 0.0005
    hedge_sim_vol_of_vol_points: float = 0.3
    hedge_sim_mean_reversion: float = 0.05

    # --- Monte Carlo (§41) ----------------------------------------------------
    monte_carlo_default_paths: int = 2000
    monte_carlo_default_horizon_days: int = 20

    # --- Portfolio risk / what-if (§39-40) ------------------------------------
    var_confidence: float = 0.95
    whatif_spot_shocks_pct: List[float] = [-0.03, -0.01, 0.01, 0.03]
    whatif_vol_shocks_pts: List[float] = [-3.0, -1.0, 1.0, 3.0]
    whatif_time_shocks_days: List[int] = [1, 5, 10]

    # --- Alerts (§42) -----------------------------------------------------------
    alert_check_interval_seconds: int = 60

    # --- Alert channels: Email (SMTP) ----------------------------------------
    # Blank smtp_host means the EMAIL channel is unconfigured; alert_service
    # logs and skips delivery rather than raising, same as a broken webhook.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_from_email: str = "alerts@volscanner.local"

    # --- Alert channels: Telegram --------------------------------------------
    # Blank telegram_bot_token means the TELEGRAM channel is unconfigured;
    # alert_service logs and skips delivery rather than raising.
    telegram_bot_token: str = ""

    @property
    def score_weights(self) -> dict:
        return {
            "statistical_edge": self.score_weight_statistical_edge,
            "historical_consistency": self.score_weight_historical_consistency,
            "liquidity": self.score_weight_liquidity,
            "cost_efficiency": self.score_weight_cost_efficiency,
            "model_confidence": self.score_weight_model_confidence,
            "risk": self.score_weight_risk,
        }


@lru_cache
def _env_settings() -> Settings:
    return Settings()


_runtime_overrides: dict = {}


def get_settings() -> Settings:
    """
    Base Settings come from env/.env, read once. Anything set via the
    Settings API (§45, app/api/routers/settings.py) is layered on top as a
    runtime override so the UI can tune thresholds without a restart.
    """
    base = _env_settings()
    if _runtime_overrides:
        return base.model_copy(update=_runtime_overrides)
    return base


def update_settings(patch: dict) -> Settings:
    valid_fields = set(Settings.model_fields)
    unknown = set(patch) - valid_fields
    if unknown:
        raise ValueError(f"Unknown setting(s): {sorted(unknown)}")
    _runtime_overrides.update(patch)
    return get_settings()


def reset_settings_overrides() -> Settings:
    _runtime_overrides.clear()
    return get_settings()
