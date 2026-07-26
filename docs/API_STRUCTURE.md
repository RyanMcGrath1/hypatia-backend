# API layout (backend ↔ Expo frontend)

HTTP handlers are grouped under `hypatia/routes/` to match where the mobile app calls them in `Hypatia/hooks/api/`. Domain logic (FRED/GNews aggregation, pagination, etc.) lives in `hypatia/services/`.

## Route packages

| Expo `hooks/api/` module | Backend package | Paths |
|--------------------------|-----------------|-------|
| `economyDashboardApi.ts` | `hypatia/routes/economy/economy_controller.py` | `/api/economy/dashboard` |
| `economyGdpGrowthRateApi.ts` | `hypatia/routes/economy/detail.py` | `/api/economy/gdp/growth-rate`, `/api/economy/gdp/growth-headwinds` |
| `economyGdpSectorContributionApi.ts` | `hypatia/routes/economy/detail.py` | `/api/economy/gdp/sector-contribution` |
| `economyCpiApi.ts` | `hypatia/routes/economy/cpi.py` | `/api/economy/cpi` |
| `economyInflationPceVsTargetApi.ts` | `hypatia/routes/economy/inflation_pce_vs_target.py` | `/api/economy/inflation/pce-vs-target` |
| `economyInflationCpiComponentsApi.ts` | `hypatia/routes/economy/inflation_controller.py` | `/api/economy/inflation/cpi-components` |
| `economyRatesFedFundsTargetApi.ts` | `hypatia/routes/economy/rates_fed_funds_target.py` | `/api/economy/rates/fed-funds-target` |
| `economyRatesKeyMetricsApi.ts` | `hypatia/routes/economy/rates_key_metrics.py` | `/api/economy/rates/key-metrics` |
| `economySectorApi.ts` | `hypatia/routes/economy/labor_market_controller.py` | `/api/economy/labor/sector` |
| `economyLaborEarningsInflationApi.ts` | `hypatia/routes/economy/labor_market_controller.py` | `/api/economy/labor/earnings-inflation` |
| `economyLaborAgeMetricsApi.ts` | `hypatia/routes/economy/labor_market_controller.py` | `/api/economy/labor/age-metrics` |
| `fredObservations.ts` | `hypatia/routes/economy/labor_market_controller.py` | `/api/economy/labor/payems/delta` |
| `newsApi.ts` | `hypatia/routes/news/` | `/api/news/top-headlines` |
| `fecCandidatesApi.ts` | `hypatia/routes/fec/` | `/api/fec/candidates` |
| (load balancers) | `hypatia/routes/health.py` | `/health` |

## Services

| Service module | Role |
|----------------|------|
| `hypatia/services/economy/core.py` | FRED overview, CPI recent, payroll-by-industry, earnings/CPI, shared YTD observation window helper |
| `hypatia/services/economy/labor_age_metrics.py` | Unemployment / participation / emp-pop by age |
| `hypatia/services/economy/detail.py` | GDP growth rate, sector contribution, growth headwinds |
| `hypatia/services/economy/fed_funds_target.py` | FOMC fed funds target range |
| `hypatia/services/economy/rates_key_metrics.py` | Rates KEY METRICS (DGS10 / mortgage / DGS2) |
| `hypatia/services/economy/pce_vs_target.py` | Headline/core PCE vs 2% target |
| `hypatia/services/economy/cpi_components.py` | Headline CPI + component YoY |
| `hypatia/services/news/core.py` | GNews fetch + top-headlines pagination envelope |

Root `economy.py` and `news.py` re-export service modules so existing tests can keep patching `economy.*`.

## Adding a new frontend API client

1. Add a path constant to `Hypatia/hooks/api/hypatiaPaths.ts` (`HYPATIA_API_PATHS`).
2. Add `Hypatia/hooks/api/<feature>Api.ts` using `fetchApiGet` + `getHypatiaBackendBaseUrl()`.
3. Add `hypatia/routes/<feature>/` (or extend an existing package if it is the same tab).
4. Put non-trivial logic in `hypatia/services/<feature>/`.
5. Document the path in `docs/FRONTEND_API.md`, this file, and `Hypatia/docs/HYPATIA_BACKEND.md`.

## Expo coordination doc

`Hypatia/docs/HYPATIA_BACKEND.md` mirrors this table from the mobile app side.
