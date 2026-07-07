# Parametric MOSFET search

Browser UI for filtering/sorting the part database in `dslib.store.parts_db`.

- **Backend**: FastAPI app in `backend/`, loads `data/parts-lib.pkl` once at startup, exposes `/api/parts` and `/api/parts/meta`.
- **Frontend**: SvelteKit app in `frontend/`, fetches all rows on load and does all filter/sort client-side.

## First-time setup

The backend imports `dslib.store`, which transitively pulls most of the project's runtime deps (numpy, pandas, etc.). Use the same Python venv you use for `main.py`, plus the few extra web deps:

```bash
# from repo root, with the project venv activated
pip install -r web/backend/requirements.txt

# install frontend deps
cd web/frontend && npm install
```

## Run (two terminals)

```bash
# terminal 1 — backend on :8000
# --loop asyncio is required: dslib/cache.py calls nest_asyncio.apply()
# at import time, which can't patch uvicorn's default uvloop event loop.
python -m uvicorn web.backend.app:app --reload --loop asyncio --port 8000

# terminal 2 — frontend on :5173 (proxies /api → :8000)
cd web/frontend && npm run dev
```

Open <http://localhost:5173>.

## Smoke test

```bash
curl -s http://localhost:8000/api/parts | python -m json.tool | head -40
curl -s http://localhost:8000/api/parts/meta | python -m json.tool
```

## Files

```
backend/
  app.py             FastAPI app + serialization
  schema.py          Pydantic response models
  requirements.txt   fastapi, uvicorn, pydantic
frontend/
  src/routes/
    +layout.ts       disables SSR (CSR-only)
    +layout.svelte
    +page.svelte     main view
  src/lib/
    api.ts           fetch wrappers
    types.ts         shared TypeScript types
    filters.ts       client-side filter + sort
    format.ts        unit/number formatters
    Sidebar.svelte   filter form
    Table.svelte     sortable table
    RangeSlider.svelte  wraps svelte-range-slider-pips
  vite.config.ts     /api → :8000 proxy
```

Production deployment (static build of the frontend served alongside the API) is out of scope for v1.
