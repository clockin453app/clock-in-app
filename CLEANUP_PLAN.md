# Cleanup plan for the refactor

This plan is intentionally tied to the current files so you can work through it
incrementally without risking the live app.

## Phase 1 — Safe cleanup completed in this package
1. `workhours_app/routes/public_routes.py`
   - remove wildcard import from `core.py`
   - import only the symbols used by the module
2. `workhours_app/routes/admin_routes.py`
   - remove wildcard import from `core.py`
   - import only the symbols used by the module
3. `workhours_app/routes/debug_routes.py`
   - remove wildcard import from `core.py`
   - import only the symbols used by the module
4. `workhours_app/route_dependencies.py`
   - add a single audited compatibility surface for route imports
   - keep all runtime behavior sourced from `core.py`
5. `workhours_app/routes/__init__.py`
   - add `register_routes()` instead of relying on scattered side effects
6. `workhours_app/__init__.py`
   - call `register_routes()` and `initialize_runtime()` in one visible place
7. `workhours_app/core.py`
   - add `_get_import_sheet()` so import/debug endpoints resolve sheet proxies consistently
   - remove one duplicate `datetime/timedelta` import
8. repository cleanup
   - remove `__pycache__/` directories from the distributable package

## Phase 2 — Next cleanup targets
1. `workhours_app/core.py`
   - extract Google Sheets bootstrap into `services/sheets_runtime.py`
   - extract Drive OAuth/token storage into `services/drive_service.py`
   - extract HTML rendering helpers into `ui/rendering.py`
2. `workhours_app/routes/public_routes.py`
   - move login/logout/account logic into `services/auth_service.py`
   - move clock-in/out validation into `services/clock_service.py`
   - move onboarding save/final-submit normalization into `services/onboarding_service.py`
3. `workhours_app/routes/admin_routes.py`
   - split into `employees_routes.py`, `payroll_routes.py`, `locations_routes.py`, `settings_routes.py`
   - convert repeated POST validation into helpers
4. `workhours_app/routes/debug_routes.py`
   - isolate import endpoints from debug export endpoints
   - make destructive actions require one shared confirmation helper
5. `tests/`
   - add regression tests for login, clock in/out, onboarding submit, mark-paid flow, and employee edits

## Phase 3 — Structural improvements
1. add a real `create_app()` factory
2. register Blueprints instead of route-import side effects
3. move remaining business rules out of `core.py`
4. make database mode the primary path and Sheets import an explicit admin-only tool
