# API layout (backend ↔ Expo frontend)

HTTP handlers are grouped under `hypatia/routes/` to match where the mobile app calls them in `Hypatia/hooks/api/`. Domain logic (FRED/GNews aggregation, pagination, etc.) lives in `hypatia/services/`.

## Route packages

| Expo `hooks/api/` module | Backend package | Paths |
|--------------------------|-----------------|-------|
| `flaskMainApi.ts` | `hypatia/routes/civic/` | `/api/civic/*` |
| `flaskMainApi.ts` | `hypatia/routes/economy/dashboard.py` | `/api/economy/dashboard`, `/api/economy/<sector>/dashboard` |
| `economyDetailApi.ts` | `hypatia/routes/economy/detail.py` | `/api/economy/detail` |
| `economySectorApi.ts` | `hypatia/routes/economy/labor_sector.py` | `/api/economy/labor/sector` |
| `fredObservations.ts` | `hypatia/routes/economy/fred.py` | `/api/economy/fred/*` |
| `newsApi.ts` | `hypatia/routes/news/` | `/api/news/*` |
| `fecCandidatesApi.ts` | `hypatia/routes/fec/` | `/api/fec/candidates`, `/api/fec/v1/names/candidates` |
| (load balancers / legacy Expo probe) | `hypatia/routes/health.py` | `/health`, `/hello` (alias) |

## Services

| Service module | Role |
|----------------|------|
| `hypatia/services/economy/core.py` | FRED overview, sector dashboards, payroll-by-industry |
| `hypatia/services/economy/detail.py` | Premium detail payload (`topic`, `charts`, `headline`) |
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
