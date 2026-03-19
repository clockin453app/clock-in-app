# WorkHours Refactor

This package keeps the existing business logic while moving the app toward a safer production structure.

## What changed
- extracted shared UI wrapper into real Jinja templates
- extracted shared CSS into `static/css/app.css`
- moved database models into `workhours_app/models/entities.py`
- added real service modules in `workhours_app/services/`
- added Alembic migration scaffolding in `migrations/`
- disabled runtime schema patching by default; enable only with `AUTO_CREATE_DB_SCHEMA=1`
- added starter automated tests in `tests/`

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY=dev-secret
export DATABASE=1
export DATABASE_URL=sqlite:///local.db
python app.py
```

## Run migrations
```bash
alembic upgrade head
```

## Run tests
```bash
pytest -q
```


## Cleanup status
- route modules now use explicit imports instead of wildcard imports
- route registration is centralized in `workhours_app.routes.register_routes()`
- legacy import/debug endpoints now resolve sheet adapters through `_get_import_sheet()`
- build artifacts like `__pycache__/` were removed from the packaged project
