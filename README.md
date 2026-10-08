# Volatility Opportunity Scanner

A relative-value volatility research platform: for every option expiry it compares
IV, realized volatility, forward volatility, term structure, skew, risk reversal,
butterfly, and calendar spreads against their own historical distributions, then
estimates a transaction-cost-adjusted net edge for the resulting candidate trades.
It also includes a strategy builder, a delta-hedge and Monte Carlo simulator,
a signal backtester, portfolio risk/what-if, and an alert engine — all wired to
the same real, IV-solved option-chain data the scanner uses.

**Nothing here is a guarantee of profit.** Every figure is a *model-based estimate*
against a synthetic demo dataset (clearly tagged `DEMO DATA` end-to-end). The core
product is the relative-value opportunity engine — the dashboard is the window into
its reasoning (observed value → fair value → deviation → z-score/percentile →
liquidity → transaction cost → net edge → WHY/RISK explanation).

This build implements **Phases 1–5** of the spec's own phase order — market
data/IV/Greeks/RV → term structure/skew/RR/BF → the relative-value engine,
transaction costs, and opportunity scanner (Phases 1–3), plus the Strategy
Builder, Backtesting Engine, Delta-Hedge Simulator + P&L attribution, Monte
Carlo, Regime Detection, Portfolio Risk/What-If, and an Alert Engine (Phases
4–5) — and is hardened with JWT auth, structured logging, a global error
envelope, request IDs, Prometheus metrics, rate limiting, hardened
(non-root, multi-stage, health-checked) Docker images, and CI. Beyond that,
it also has a **live ICICI Breeze market-data provider** (§5) and a **full
option-chain backtest replay mode** (§5) that marks real multi-leg
strategies to market against real historical option chains rather than a
scalar signal series. See [Known Limitations](#known-limitations) for
what's still explicitly out of scope (WebSocket streaming, k8s manifests,
and the specific gaps in the two features above).

---

## 1. Architecture

```
Next.js UI (client components, fetch, JWT in localStorage)
        │  REST (JSON)
        ▼
Middleware: CORS → request-ID/logging → rate limiting → error envelope
        │
        ▼
FastAPI routers (app/api/routers/*)  ← auth-gated on every mutating route
        │
        ▼
Services (app/services/*)                    Simulation/risk (app/simulation, app/risk)
  snapshot_service    — chain → IV → Greeks     pnl_attribution   — 2nd-order Taylor P&L split
  volatility_service  — per-expiry smile/skew    hedge_simulator   — rehedge-frequency simulator
  history_service     — z-score/percentile ctx   monte_carlo       — GBM+stochvol P&L distribution
  opportunity_service — full pipeline → persist  portfolio_risk    — delta-vega parametric VaR/CVaR
  backtest_service     — walk-forward signal backtest
  alert_service         — condition evaluation + web/webhook/email/telegram delivery
        │
        ▼
Analytics engine (app/analytics/*) — pure functions, no DB/HTTP imports,
independently unit-tested:
  black_scholes → iv_solver → greeks → realized_vol → smile → term_structure
  → skew → risk_reversal → butterfly → calendar → stats → no_arbitrage
  → fair_value → relative_value → regime
        │
        ▼
Opportunity engine (app/opportunities/*) + Strategy engine (app/strategies/*)
  strategies/templates → builder (payoff, breakevens, risk/reward)
  opportunities: strategies (candidates) → pipeline (liquidity + cost +
  score + explain) → greeks_aggregator
        │
        ▼
Market data abstraction (app/market_data/*)
  MarketDataProvider (ABC) ← MockProvider | CSVProvider | BreezeProvider (live)
        │
        ▼
PostgreSQL + TimescaleDB (Underlying, Expiry, Option, VolatilitySnapshot,
HistoricalVolatility, MetricHistory, Opportunity, User, BacktestRun,
BacktestTrade, Position, Alert, AlertEvent)
        │
        ▼
Celery worker + beat (Redis broker) — periodic snapshot refresh, opportunity
recompute, and alert checks
```

**Pipeline (§54):** Market Data → Data Cleaning → Option Validation → IV
Calculation → Greeks → Realized Volatility → Volatility Surface → Term
Structure → Forward Volatility → Skew → Risk Reversal → Butterfly → Calendar
Relationships → Historical Distributions → Fair Value Models → Relative-Value
Deviations → Liquidity Filter → Transaction Cost Model → Risk Analysis →
Expected Net Edge → Opportunity Generator → Opportunity Dashboard.

The analytics/simulation/risk/strategies engines never talk to a database or
the market-data layer, so they're all unit-tested with plain Python values —
168 tests total (§6).

---

## 2. Folder structure

```
backend/
  app/
    core/            config (every tunable threshold), async SQLAlchemy engine
                     (pooled), JWT/password hashing, structured JSON logging,
                     request-ID + error-envelope middleware, rate limiting
    models/          ORM: Underlying, Expiry, Option, VolatilitySnapshot,
                     HistoricalVolatility, MetricHistory, Opportunity, User,
                     BacktestRun, BacktestTrade, Position, Alert, AlertEvent
    analytics/        pure quant functions incl. regime.py (see §5)
    market_data/       MarketDataProvider ABC, MockProvider, CSVProvider,
                      BreezeProvider (live ICICI Direct feed), parametric
                      vol-surface model, chain generator
    liquidity/         bid/ask/OI/volume → HIGH/MEDIUM/LOW/REJECTED
    costs/             transaction-cost engine
    opportunities/     strategy generators, scoring, explanation, pipeline
    strategies/        Strategy Builder: templates, leg resolution (shared
                      by the live builder and the chain-replay backtester),
                      payoff/breakeven/risk-reward math
    simulation/        pnl_attribution (Taylor P&L split), hedge_simulator,
                      monte_carlo
    risk/              portfolio_risk (Greeks aggregation, parametric VaR/
                      CVaR, what-if shock grid)
    backtesting/       engine (walk-forward signal backtest + shared
                      find_trade_windows), chain_replay (option-chain
                      replay backtest), stats
    alerts/            condition evaluation (pure)
    services/          DB-aware orchestration wired to the pure layers above
    api/routers/       FastAPI endpoints, incl. auth.py
    tasks/             Celery app + periodic jobs (snapshot refresh,
                      opportunity recompute, alert checks)
  alembic/             migrations (0001: core schema + TimescaleDB
                      hypertables; 0002: users/backtesting/positions/alerts;
                      0003: chain-replay's replay_mode/legs columns; 0004:
                      alerts.recipient for email/telegram delivery; 0005:
                      underlyings.surface_state for MockProvider day-to-day
                      continuity; 0006: expiries.source, LIVE vs
                      HISTORICAL_REPLAY)
  scripts/seed.py       demo-data generator, incl. the historical
                      option-chain backfill (see §4)
  scripts/breeze_login.py  one-time-per-day helper to refresh the Breeze
                      session token (see §5)
  tests/                pytest suite (168 tests, see §6)
  data/csv/             CSV fixtures written by scripts/seed.py (CSVProvider format)
  Dockerfile             multi-stage, non-root, healthcheck delegated to compose
frontend/
  app/                 Next.js App Router pages, one per nav item (see §7)
  components/          OpportunityCard, TopBar (+ regime badge, login
                      widget), Sidebar, AuthContext, ui/* primitives
  lib/                 typed API client (attaches JWT to mutating calls),
                      TS types, auth helpers, formatting helpers
  Dockerfile             multi-stage, runs as the image's built-in non-root
                      "node" user, healthcheck
docker-compose.yml      db (Timescale) + redis + backend + celery-worker +
                      celery-beat + frontend, all health-checked
.github/workflows/ci.yml  backend (Postgres+Timescale service, migrate,
                      pytest) and frontend (lint, build) jobs
```

---

## 3. Quick start (Docker — recommended)

```bash
docker compose up -d --build
```

This builds and starts everything: Postgres/TimescaleDB, Redis, the FastAPI
backend (runs Alembic migrations, then `scripts/seed.py` automatically on
first boot, including a default admin user, ~1260 days — 5 years — of
historical option-chain rows for the chain-replay backtester, and today's
live chain — on the order of 2 minutes per symbol, ~6 minutes total for the
default 3 demo symbols), Celery worker + beat, and the Next.js frontend.
The backend's `healthcheck` only starts polling once uvicorn is up, which
on first boot is *after* that seed run completes (`entrypoint.sh` runs it
synchronously) — `start_period: 600s` in `docker-compose.yml` gives that
enough headroom; celery-worker/celery-beat/frontend all depend on the
backend's healthcheck, so a too-short `start_period` here previously made a
slow first boot fail the whole stack (fixed empirically against a real
`docker compose up`, not just estimated — see §10). `docker compose ps`
should show all six as `healthy`, which subsequent boots (data already
seeded) reach in seconds.

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000/api (interactive docs at `/docs`,
  Prometheus metrics at `/metrics`)
- Postgres (host access): `localhost:5433` (mapped to avoid clashing with a
  locally-running Postgres on the default 5432)
- **Demo login: `admin` / `admin`** (top-right of the UI, or `POST
  /api/auth/login`) — required for anything that writes (settings, running a
  backtest, saving a portfolio position, creating an alert, refreshing
  opportunities). Change `default_admin_password` / re-hash before any real
  deployment — this is a demo credential, not a security boundary.

To force a clean re-seed (wipes all data and volumes):

```bash
docker compose down -v
docker compose up -d --build
```

Watch the backend seed logs:

```bash
docker compose logs -f backend
```

## 4. Local (non-Docker) development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# Start a local Postgres/TimescaleDB, e.g.:
docker run -d --name volscanner-db -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=volscanner -p 5432:5432 timescale/timescaledb:latest-pg16

cp .env.example backend/.env   # edit DATABASE_URL if needed

cd backend
alembic upgrade head
python -m scripts.seed          # ~1-2 min: walks a 520-day synthetic vol
                                 # surface per symbol, backfills history,
                                 # runs today's real chain->IV->Greeks
                                 # pipeline, generates opportunities, and
                                 # creates the default admin user
uvicorn app.main:app --reload
```

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000
```

`frontend/.env.local` must point `NEXT_PUBLIC_API_URL` at a browser-reachable
backend URL (`http://localhost:8000/api` by default) — and the backend's
`CORS_ORIGINS` setting must include the frontend's *origin* (`http://localhost:3000`
by default; if you run the frontend dev server on a different port, update both).

### Sample dataset / CSVProvider

`scripts/seed.py` writes `backend/data/csv/{SYMBOL}/` fixtures (`meta.csv`,
`underlying_history.csv`, a few `chain_YYYYMMDD.csv` full option-chain
snapshots) in exactly the layout `CSVProvider` reads. To exercise the whole
analytics pipeline against those CSVs instead of `MockProvider`, set:

```
MARKET_DATA_PROVIDER=CSV
CSV_DATA_DIR=data/csv
```

### Live ICICI Breeze provider

A third `MarketDataProvider` (`app/market_data/breeze_provider.py`) hits
ICICI Direct's Breeze Connect API for the **live snapshot/opportunity
pipeline only** — it cannot backfill history (see §5/§10). To use it:

```
MARKET_DATA_PROVIDER=BREEZE
BREEZE_API_KEY=...
BREEZE_API_SECRET=...
BREEZE_SESSION_TOKEN=...          # expires daily — see below
BREEZE_EXCHANGE_CODE=NFO
BREEZE_CASH_EXCHANGE_CODE=NSE
BREEZE_SYMBOL_MAP={"NIFTY": "NIFTY", "BANKNIFTY": "CNXBAN"}
```

Breeze session tokens expire daily and can only be obtained via an
interactive browser login — there's no safe way to automate that without
handling your broker OTP/credentials directly, so this isn't attempted.
Instead, run once a day:

```bash
python -m scripts.breeze_login
```

It prints a login URL, you log in in a browser, and paste back the
redirected `apisession` token; it's written straight into `backend/.env`.
Field-name parsing from Breeze's raw JSON is concentrated in one small
`_parse_option_row` seam in `breeze_provider.py` — it matches Breeze's
public API docs but **has not been smoke-tested against a live account**;
verify it once you have real credentials before trusting it.

### Running tests

```bash
cd backend
pytest tests/ -v
```

168 tests covering Black-Scholes/Greeks, the IV solver's every status
branch, all 5 realized-vol estimators, forward volatility (incl. the
negative-variance no-arbitrage case), risk reversal, butterfly, calendar
spreads, z-score/percentile, no-arbitrage flags, transaction costs, net
edge, strategy Greeks aggregation, relative-value signal generation,
opportunity scoring (incl. `model_confidence_score`'s saturation/
proportional-scaling/no-arb-flag/data-quality/clamping behavior — see
§10 for why this needed fixing), MockProvider (incl. its
`sync_surface`/`advance_to`/`export_surface` day-to-day continuity —
round-trip serialization, one-business-day advancement, weekend-skip,
same-day no-op, and the "first checkpoint is always adopted even if
same-dated as the placeholder" regression test — see §10), JWT auth,
strategy payoff/risk-reward (incl. a regression test
for the "coarse grid wrongly flags bounded risk as undefined" bug found
during development), P&L attribution, the backtesting engine + stats, the
hedge simulator, Monte Carlo, portfolio risk/what-if, regime detection, the
alert engine's fire-once-per-transition logic and its Email/Telegram
delivery helpers (mocked SMTP/Telegram, config-unset skip path, and
delivery-failure-is-swallowed path), the Breeze provider (against a mocked
SDK client, no real credentials needed), and the chain-replay backtester's
leg-direction-flip logic and historical expiry-ladder selector.
DB-touching code paths (e.g. `analyze_strategy`,
`replay_strategy_trades`) follow this project's existing convention of
being verified live against Docker + curl/browser rather than via a DB
test fixture — see §3's verification notes in the project history.

### CI

`.github/workflows/ci.yml` runs on every push/PR: a backend job spins up
Postgres+TimescaleDB and Redis service containers, runs `alembic upgrade
head` then the full pytest suite; a separate frontend job runs `npm run
lint` and `npm run build`.

### Last verified

**2026-09-25:** `pytest tests/ -v` → 168/168 passing; `npm run lint` → clean
(0 errors, same 7 pre-existing `react-hooks/set-state-in-effect` warnings in
`SymbolContext.tsx`/`TopBar.tsx`); `npm run build` → succeeds, all 14 routes
in §7 present. Folder structure, Alembic migration files (0001–0006), API
router modules, and ORM models all checked against this document.

This pass also caught two **stale** Known Limitations bullets that
contradicted features already implemented elsewhere in this same document —
"no live broker integration" (`BreezeProvider` exists, §5/§9) and "signal-
level only" backtesting (the `CHAIN` replay mode exists, §5) — both
corrected to describe what's actually implemented vs. what's still
genuinely out of scope.

Three more limitations were then actually **implemented** (not just
re-documented), end-to-end against a real `docker compose up` (Postgres +
Redis + Celery, not just pytest): 5-year historical depth
(`ANALYSIS_WINDOW_DAYS=1260`), 2W/9M metric-history backfill
(`METRIC_TENORS`, all 8 tenors), and MockProvider day-to-day surface
continuity (`Underlying.surface_state`, `sync_surface`/`advance_to`). Live
verification directly caused two real bugs to surface and get fixed before
being called done — a stale-`Expiry` contamination bug (bogus "1W" entries
years in the past, `0006_expiry_source.py`) and a `sync_surface`
same-date-checkpoint bug that silently discarded real persisted state on
the most common refresh path — both are written up in detail in §10, since
neither would have been caught by the existing pytest suite alone (both
needed a real Postgres + multiple Celery ticks to reproduce). New pytest
coverage was added for both fixes afterward. See §10 for the full story on
each.

**2026-09-25:** Inspecting a live Scanner table surfaced a third real bug
from the same 5-year-depth change: `model_confidence_score`'s sample-
adequacy term was scored against a hard-coded floor of 120 samples, which
saturated to 100 for essentially *every* opportunity once seeded history
reached ~1200+ samples per metric — the "Confidence" column had quietly
become a constant, providing zero discriminating signal despite computing
a real number. Fixed by scoring against `settings.percentile_lookback_days`
(the actual configured target) instead — verified live, confidence values
across a fresh opportunity recompute now spread meaningfully (77.0–100.0)
rather than sitting at 100.0 uniformly. 6 new tests added
(`tests/test_scoring.py`); 168/168 passing.

---

## 5. Quantitative methodology

### Phases 1–3 (market data, IV/Greeks, relative-value engine)

- **IV solver** (`analytics/iv_solver.py`): Brent's method against
  Black-Scholes, bounded in σ∈[0.001, 5.0]. Never silently returns a value —
  returns `(iv, status, error)` with status ∈ `VALID / NO_CONVERGENCE /
  INVALID_PRICE / WIDE_SPREAD / ARBITRAGE_VIOLATION / INSUFFICIENT_DATA`.
- **Greeks** (`analytics/black_scholes.py`, `analytics/greeks.py`): delta,
  gamma, vega, theta, rho, plus second/third-order vanna, volga, charm,
  speed, color, zomma (Haug's closed forms).
- **Realized volatility** (`analytics/realized_vol.py`): close-to-close,
  Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang, EWMA; configurable
  annualization (252/365) and windows (5/10/20/30/60/90/252).
- **Smile** (`analytics/smile.py`): OTM-only smile (puts below spot, calls
  above), interpolated in |delta| space so 10/15/25/30Δ and ATM read off
  directly; `strike_for_target_delta` inverts BS delta→strike analytically
  (fixed-point iteration), reused by both the historical seed shortcut and
  the Strategy Builder's leg resolution.
- **Term structure & forward vol** (`analytics/term_structure.py`):
  `ForwardVariance = (σ2²T2 - σ1²T1)/(T2-T1)`; a negative result is flagged
  (`ForwardVolResult.valid=False`), never silently sqrt'd. Regime
  classification (contango/backwardation/mixed) and local-inversion
  detection.
- **Skew / Risk Reversal / Butterfly** (`analytics/skew.py`,
  `risk_reversal.py`, `butterfly.py`): standard definitions,
  `RR = IV(Δcall) - IV(Δput)`, `BF = 0.5*(IV(Δput)+IV(Δcall)) - IV(ATM)`.
- **No-arbitrage checks** (`analytics/no_arbitrage.py`): put-call parity,
  calendar variance consistency, butterfly convexity, bid/ask consistency —
  these produce *flags* attached to opportunities, never a fabricated
  "risk-free arbitrage" trade (spec §21/§53).
- **Fair-value models** (`analytics/fair_value.py`): configurable, not
  hard-coded — `historical_mean` (mean-reversion) is the default for
  skew/RR/BF/calendar; an OLS `regression` model (`fair IV = a + b·RV`) is
  used for IV/RV when it explains enough variance (R²>0.1), else falls back
  to `historical_mean`.
- **Relative-value signal** (`analytics/relative_value.py`): the single
  generic function every opportunity type is built on — Observed / Fair
  Value / Deviation / Z-score / Percentile / Signal (RICH/CHEAP/NEUTRAL).
  All IV-derived metrics are converted to **vol points** (percentage
  points) at this boundary so edges net correctly against transaction costs
  — a real 100x unit bug here (edges computed 100x too small) was caught
  and fixed by inspecting a live Scanner card in the browser, not by unit
  tests alone; see the git history / commit messages for the story.
- **Liquidity filter** (`liquidity/filters.py`): per-leg
  HIGH/MEDIUM/LOW/REJECTED from OI/volume/spread% thresholds; an
  opportunity's overall liquidity is its worst leg.
- **Transaction costs** (`costs/transaction_cost.py`): bid-ask cost
  (converted price→vol-points via the leg's vega), slippage, market impact,
  hedging cost, plus a parallel cash estimate (brokerage/fees/tax).
  `Net Edge = Gross Edge − (bid-ask + slippage + market impact + hedging)`.
- **Opportunity types** (`opportunities/strategies.py`): IV-vs-RV, Calendar,
  Risk Reversal, Butterfly, Skew, Forward Vol — each only fires when
  `|z-score| ≥ zscore_extreme_threshold` (default 2.0), never on raw
  level alone.
- **Scoring** (`opportunities/scoring.py`): transparent weighted sum of six
  disclosed components (statistical edge, historical consistency, liquidity,
  cost efficiency, model confidence, risk) — weights are configurable via
  Settings. `model_confidence_score`'s sample-adequacy term is scored
  against `settings.percentile_lookback_days` (the actual configured
  historical target), not a fixed floor — an earlier hard-coded floor of
  120 samples saturated to 100 for essentially every opportunity once the
  5-year seed depth (§10) made ~1200+-sample histories the norm, which
  silently turned "model confidence" into a constant that stopped
  discriminating between opportunities. Scoring against the real target
  restores the spread (e.g. a calendar-pair history shortened by
  forward-vol validity filtering now scores visibly below 100 instead of
  also saturating).

### Phases 4–5 (strategy builder, simulation, backtesting, risk, alerts)

- **Strategy Builder** (`strategies/builder.py`, `templates.py`): resolves
  abstract leg specs (option type + target delta + action + quantity)
  against today's real, IV-solved option chain via the same
  `ExpirySnapshot.find_nearest_by_delta` matcher the opportunity engine
  uses. Computes net premium, aggregated Greeks, a full expiry payoff curve
  (`strategies/payoff.py`), breakevens, and max risk/reward. **Undefined
  risk/reward is decided analytically from the leg composition** (net CALL
  exposure — the only thing that can make S→∞ unbounded), not by checking a
  finite grid's edge slope: an earlier numeric-slope version wrongly
  flagged a plain long straddle as "undefined risk" because the grid's
  lower bound wasn't close enough to the true spot→0 asymptote — caught by
  a regression test (`test_strategy_payoff.py`) before it ever reached the
  UI. Templates: Straddle, Strangle, Iron Condor, Butterfly, Risk Reversal
  (bullish/bearish), Bull Call Spread, Bear Put Spread. Calendar/Diagonal
  are intentionally *not* templates here — they're inherently cross-expiry,
  and the existing Calendar Analyzer page already covers that analysis.
- **P&L Attribution** (`simulation/pnl_attribution.py`): a 2nd-order Taylor
  expansion of option value in (spot, sigma, time) — spot/gamma/theta/vega/
  vanna/volga P&L plus a "carry" term (financing cost/benefit on net
  premium at the risk-free rate — a distinct concept from theta, per the
  spec's line-item list). Pure and framework-independent; reused by both
  simulators below.
- **Delta-Hedge Simulator** (`simulation/hedge_simulator.py`): holds a
  strategy's Greeks fixed ("frozen Greeks" — no full re-pricing) and
  applies the attribution to a simulated spot+vol path. Rehedge frequency
  (daily → 5-minute) is modeled by subdividing each simulated day into N
  sub-steps (5-minute ≈ 84 sub-steps) rather than true tick data — more
  frequent rehedging visibly reduces discrete-hedging P&L noise, the
  textbook gamma-scalping result this is meant to demonstrate. A day count
  longer than the option's own DTE is clamped, not silently simulated past
  expiry.
- **Monte Carlo** (`simulation/monte_carlo.py`): N GBM + mean-reverting,
  leverage-correlated stochastic-vol paths to the horizon, then one
  attribution call per path from the horizon-end (dSpot, dSigma) — a
  terminal P&L *distribution* estimate (VaR, CVaR/Expected Shortfall,
  P(profit)/P(loss)), not a path-dependent rehedged P&L (that's what the
  hedge simulator is for). Always labeled a model-based estimate in the UI.
- **Regime Detection** (`analytics/regime.py`): LOW/NORMAL/HIGH/EXTREME
  from RV20's own historical percentile (<25th/25–75th/75–95th/>95th,
  configurable) — reuses `analytics/stats.distribution_context`, so
  "regime" is just another view onto the same percentile engine, not a
  separate model. Feeds the TopBar regime badge and the backtest regime
  breakdown.
- **Backtesting Engine** (`backtesting/engine.py`, `stats.py`,
  `chain_replay.py`) — two `replay_mode`s sharing the same walk-forward
  `find_trade_windows` entry/exit timing (a *rolling* z-score computed only
  from strictly-prior days — no look-ahead bias possible):
  - **SIGNAL** (default): walks the **already-stored historical
    MetricHistory/HistoricalVolatility series** (the same ~260-day-per-symbol
    history the opportunity engine reads) and marks P&L from the *scalar
    metric's* own delta, cost-adjusted after a configured round-trip cost —
    does the metric mean-revert, not what a real position would have earned.
    Supports IV_RV, CALENDAR, FORWARD_VOL, SKEW, RR, BF signals.
  - **CHAIN**: resolves a user-specified multi-leg strategy's actual strikes
    at entry against the **real historical option chain** `scripts/seed.py`
    backfills (delta lookup via `strategies/resolve_legs`), then marks those
    *same held contracts* to market at exit — a real historical option-chain
    P&L replay, not a scalar proxy. Trade windows whose entry/exit day falls
    outside the seeded chain coverage (a single rolling near-month expiry
    per historical day) are silently skipped.
  Stats (both modes): win rate, avg/median return, max drawdown, an
  annualized Sharpe (scaled by average holding period), profit factor
  (`None` rather than `∞` when there are no losing trades), and
  5th-percentile tail loss. Results persist (`BacktestRun`/`BacktestTrade`)
  and are idempotent per run — each POST creates a new run rather than
  mutating history.
- **Portfolio Risk + What-If** (`risk/portfolio_risk.py`): aggregates
  Greeks across saved `Position` rows; VaR/CVaR use a **parametric
  delta-vega ("delta-normal") approximation** — explicitly *not* full
  historical simulation, and ignores gamma's (non-normal) contribution to
  the variance — a standard, named, clearly-labeled simplification
  appropriate for a quick risk snapshot. The what-if shock grid
  (spot ±1/3%, IV ±1/3 vol pts, time +1/5/10 days, all configurable) reuses
  `pnl_attribution` directly on the aggregated portfolio Greeks.
- **Alert Engine** (`alerts/engine.py`, `services/alert_service.py`):
  supports raw-value alerts (`atm_iv`, `calendar_spread`, `forward_vol`,
  `rv20`, `skew_{d}`, `rr_{d}`, `bf_{d}`) and z-score alerts (any of the
  above suffixed `_zscore`, matching the same z-score convention used
  everywhere else). Fires **at most once per condition-become-true
  transition** — no repeat spam while the condition stays true. Four
  channels, all real: **Web** (a persisted, polled `AlertEvent` feed),
  **Webhook** (an async HTTP POST to `webhook_url`), **Email** (SMTP via
  `smtplib`, configured by `SMTP_HOST`/`SMTP_PORT`/`SMTP_USERNAME`/
  `SMTP_PASSWORD`/`SMTP_USE_TLS`/`SMTP_FROM_EMAIL`), and **Telegram** (a bot
  API POST, configured by `TELEGRAM_BOT_TOKEN`) to the alert's `recipient`
  (an email address or a chat ID, respectively). All four are best-effort —
  a delivery failure (or an unconfigured SMTP host / bot token) is logged
  and never crashes the alert check; the alert still fires and its
  `AlertEvent` is still persisted either way.

### Worked example (matches the spec's §55 scenario shape)

Open the Scanner, expand any card. A real one from the seeded demo data
(NIFTY, IV vs RV):

```
NIFTY · IV_VS_RV · SHORT_1M_VOL
Legs: SELL 1M ATM straddle/strangle  (IV 14.6%, liquidity HIGH)

Historical Context
  1M IV-RV spread          observed  +12.35 vol pts
  Historical mean           +0.31 vol pts   (260 obs)
  Z-score                    +4.9σ            Percentile  100%

Edge
  Gross Edge     +12.35
  Transaction Cost -0.64
  NET EDGE       +11.71 vol pts

Why?
  1. 1M IV-RV spread is +4.9 standard deviations from its 260-observation
     historical mean, at the 100th percentile.
  2. Fair-value model (regression) estimates the fair spread from the
     historical RV→IV relationship; observed value deviates well beyond it.

Risks
  Realized volatility spikes above the level implied by the historical
  IV-RV relationship · Earnings/event risk not reflected in the trailing RV
  window · IV regime change · Spot gap risk · ...
```

---

## 6. API

All endpoints are under `/api`. Interactive docs: `GET /docs`. Prometheus
metrics: `GET /metrics`. Liveness/readiness: `GET /api/healthz` (process is
up) / `GET /api/readyz` (checks DB + Redis connectivity).

```
POST /api/auth/login                        GET  /api/auth/me

GET  /api/underlyings                       GET  /api/underlyings/{symbol}
GET  /api/option-chain/{symbol}/expiries     GET  /api/option-chain/{symbol}?expiry=YYYY-MM-DD
GET  /api/volatility/{symbol}                GET  /api/term-structure/{symbol}
GET  /api/skew/{symbol}                      GET  /api/risk-reversal/{symbol}
GET  /api/butterfly/{symbol}                 GET  /api/calendar/{symbol}
GET  /api/forward-vol/{symbol}               GET  /api/realized-vol/{symbol}?estimator=CLOSE_CLOSE
GET  /api/regime/{symbol}
GET  /api/opportunities                      GET  /api/opportunities/{symbol}
                                              POST /api/opportunities/{symbol}/refresh   [auth]
GET  /api/settings                           PATCH /api/settings   [auth]   POST /api/settings/reset   [auth]

GET  /api/strategy/templates                 POST /api/strategy/analyze
POST /api/backtest   [auth]                  GET  /api/backtest?symbol=      GET /api/backtest/{run_id}
POST /api/simulation/hedge                   POST /api/simulation/monte-carlo

POST /api/portfolio/positions   [auth]        GET  /api/portfolio/positions
DELETE /api/portfolio/positions/{id}   [auth]  GET /api/portfolio/risk
POST /api/portfolio/what-if

POST /api/alerts   [auth]                     GET  /api/alerts?symbol=
DELETE /api/alerts/{id}   [auth]              GET  /api/alerts/events
POST /api/alerts/check   [auth]  (manually trigger the periodic check)
```

`[auth]` routes require `Authorization: Bearer <token>` from `POST
/api/auth/login`. Opportunity list filters: `min_net_edge`,
`min_confidence`, `max_risk`, `liquidity`, `strategy`, `sort_by`, `sort_dir`.

---

## 7. Frontend pages

Overview (incl. regime badge) · Opportunity Scanner (filterable table + full
Opportunity Card) · Option Chain · Strategy Builder (payoff diagram,
breakevens, risk/reward) · Backtest (equity curve, regime breakdown, trade
list) · Trade Simulator (Delta-Hedge tab + Monte Carlo tab) · Portfolio
(positions, aggregated Greeks, VaR/CVaR, what-if grid) · Alerts (create/list/
delete, recent events) · Term Structure · Skew/RR/Butterfly (tabbed) ·
Calendar Analyzer · RV Analysis · Settings. Dark, dense, terminal-style UI; a
`DEMO DATA` badge and a Login widget are always visible in the top bar.

---

## 8. Database schema

See `backend/app/models/*.py` for the SQLAlchemy source of truth, or
`backend/alembic/versions/0001_initial.py` (core schema) and `0002_phase4_5.py`
(users, backtesting, positions, alerts) for the exact DDL. `options`,
`volatility_snapshots`, `historical_volatility`, and `metric_history` are
TimescaleDB hypertables partitioned on `timestamp` (composite primary key
`(id, timestamp)`, since Timescale requires the partition column in every
unique index).

---

## 9. Production hardening

- **Auth**: `User` (bcrypt-hashed password), `POST /api/auth/login` issues a
  PyJWT HS256 token (12h expiry), `get_current_user` FastAPI dependency
  guards every mutating route. A default `admin` user is seeded — see §3.
- **Structured logging**: JSON lines (`app/core/logging.py`) with
  request_id/method/path/status_code/duration_ms on every access log line.
- **Error handling**: global handlers for validation errors, HTTP
  exceptions, and unhandled exceptions all return the same
  `{"error": {"code","message","request_id"}}` envelope — no raw traceback
  ever reaches the client.
- **Request IDs**: a UUID per request, echoed as `X-Request-ID`, included in
  every log line and error body for correlation.
- **Metrics**: `prometheus-fastapi-instrumentator` at `/metrics`.
- **Rate limiting**: Redis-backed (`slowapi`), a default limit across all
  routes.
- **DB pooling**: explicit `pool_size`/`max_overflow`/`pool_recycle` on the
  async engine.
- **Docker**: both Dockerfiles are multi-stage (compilers isolated to a
  build stage) and run as a non-root user (`appuser` uid 1000 for the
  backend/Celery image; the `node` image's built-in non-root user for the
  frontend). Every compose service has a `healthcheck`.
- **Liveness/readiness**: `/api/healthz` vs `/api/readyz` (the latter
  actually pings Postgres and Redis).
- **CI**: `.github/workflows/ci.yml` (see §4).

---

## 10. Known limitations

Deliberately out of scope (left as clean extension points, not half-built):

- **Live broker integration exists but is narrow.** `BreezeProvider` (§5)
  covers only the live snapshot/opportunity pipeline against ICICI Direct —
  it cannot backfill history (that still comes from `scripts/seed.py`'s
  synthetic surface), requires a manual daily browser login for its session
  token (`scripts/breeze_login.py`), and its field-parsing has **not been
  smoke-tested against a live account**. `MockProvider` and `CSVProvider`
  remain the two fully-exercised providers; adding another live feed means
  writing one more `MarketDataProvider` implementation — nothing else
  changes.
- **The backtesting engine's default mode (SIGNAL) is signal-level**, not a
  real position P&L — it marks the scalar metric's own delta, not option
  prices (see §5). A second mode (**CHAIN**) *does* replay real historical
  option-chain P&L for a user-specified multi-leg strategy, but only over
  the single rolling near-month expiry per day that `scripts/seed.py`
  backfills — a full daily multi-expiry chain archive is out of scope.
- **Portfolio VaR/CVaR is a parametric delta-vega approximation**, not full
  historical simulation, and ignores gamma's contribution to the variance.
- **`max_risk` on an Opportunity card is a simplified heuristic**
  (transaction-cost breakeven × a structure-type multiplier), not a real
  margin calculation — genuine position-level margin belongs to a fuller
  Risk Engine.
- **No WebSocket streaming, k8s manifests, or Calendar/Diagonal templates in
  the Strategy Builder** (the existing Calendar Analyzer page covers that
  analysis instead — see §5).
- **Auth is a real but minimal JWT layer** — single demo user, no
  roles/refresh tokens/password reset flow. Fine for a demo; change the
  secret key and default password before anything resembling a real
  deployment.
- **Email/Telegram alert channels are real but unconfigured by default** —
  no SMTP host or Telegram bot token ships in this build's `.env.example`
  (see §5/§9); set `SMTP_HOST`+friends or `TELEGRAM_BOT_TOKEN` to enable
  delivery. Left unset, those alerts still fire and persist an `AlertEvent`
  exactly like Web/Webhook — delivery is just skipped (logged, not crashed).
- ~~**Historical depth: ~520 business days, not the full 5-year default.**~~
  **Resolved.** `scripts/seed.py`'s `ANALYSIS_WINDOW_DAYS` now matches
  `percentile_lookback_days=1260` exactly (plus the existing 260-day HV252
  warm-up, `TOTAL_DAYS=1520`) — every metric's z-score/percentile context is
  computed from the full 5 years the settings default implies, verified
  live (`sample_size: 1260` in `/api/volatility/{symbol}`). Costs real seed
  time — see §3.
- ~~**Historical MetricHistory only backfilled for a curated tenor subset.**~~
  **Resolved.** `METRIC_TENORS` now covers all 8 `TENOR_DAYS` (adds 2W/9M) —
  every tenor gets full historical z-score/percentile context, no more
  `INSUFFICIENT_DATA` for those two buckets. Fixing this **surfaced a real,
  pre-existing data-correctness bug**, not introduced by this change but
  made far more visible by it: `Expiry` rows had no way to distinguish
  today's live multi-expiry ladder from the chain-replay backtester's
  historical rolling-expiry ladder, and every "list this symbol's expiries"
  query (`volatility_service.get_all_expiry_snapshots`, the Option Chain
  page's expiries endpoint, the opportunity engine's expiry loop) read both
  ladders together. A historical replay expiry's `days_to_expiry` is
  negative, and `nearest_tenor_label`'s `min(TENOR_DAYS, key=lambda td:
  abs(td - dte))` has no sane bucket for a negative number — it always
  collapses to the *smallest* tenor (7 days, "1W") instead. With only ~9
  monthly historical rungs (the old 260-day window) this was easy to miss;
  at 5 years' depth (~42 rungs) it reliably surfaced as bogus "1W" entries
  dated *years* in the past sitting next to today's real data — caught
  immediately on inspecting a live `/api/volatility` response, not by unit
  tests (none of which exercised both ladders in the same query). Fixed by
  a new `Expiry.source` column (`LIVE` | `HISTORICAL_REPLAY`,
  `0006_expiry_source.py`) and filtering every live-page query to `LIVE`.
- ~~**Live Celery refresh reinitializes a fresh surface each calendar day
  instead of continuing the seeded walk.**~~ **Resolved.**
  `Underlying.surface_state` (`0005_surface_continuity.py`) now persists
  `MockProvider`'s full per-tenor AR(1) state after every refresh;
  `snapshot_service.refresh_underlying` loads it back
  (`MockProvider.sync_surface`) and evolves forward exactly one
  `evolve_surface` step per elapsed business day (`MockProvider.advance_to`)
  instead of calling `init_surface` from scratch — deterministic per missed
  day (seeded off `symbol + date`), so it's reproducible and self-healing
  across however long a process was down. Verified live: spot stayed at the
  correct evolved value (not the raw profile baseline) across three
  successive manual `/refresh` calls. This surfaced a **second real bug**
  while verifying it live: the first version of `sync_surface` rejected any
  checkpoint "no newer than" the surface already in memory — but
  `MockProvider.__init__`'s throwaway placeholder is *also* stamped
  `dt.date.today()`, so on the (extremely common) first sync of the day
  the dates compared equal and the real persisted checkpoint was silently
  discarded in favor of the placeholder every time, quietly resetting
  `spot_price`/`surface_state` back to the raw, un-evolved profile baseline
  on the very first Celery tick. Caught by checking `/api/underlyings/{
  symbol}` before and after a manual refresh and noticing the spot was
  exactly `profile.spot` (24800.0 for NIFTY) rather than the ~5-year-evolved
  value seed.py had just written — fixed by always adopting a symbol's
  *first* checkpoint unconditionally, then comparing dates only afterward
  (see `MockProvider._synced`). This app's stable_seed() story from an
  earlier round of hardening (Python's randomized-per-process `hash()`
  made the old day-reinit approach inconsistent between processes even
  before this fix) is why the walk is deterministic per `(symbol, date)` at
  all — this round made that walk actually get *continued* rather than
  restarted.
- **`Opportunity` and alert-check idempotency:** Opportunity rows are
  idempotent per `(underlying, timestamp)` — a re-scan at the exact same
  timestamp replaces rather than duplicates that batch (this was also
  caught live: Celery's first periodic recompute duplicated every
  opportunity because it ran before that tick's snapshot refresh had
  advanced the underlying's timestamp). Alerts fire at most once per
  condition-become-true transition by the same kind of state tracking.
