"""Legacy one-off schema patching helpers.

Prefer Alembic migrations for normal deployments. This module remains available
only as an opt-in escape hatch for older databases.
"""

from __future__ import annotations

import workhours_app.core as core

app = core.app
db = core.db
DATABASE_ENABLED = core.DATABASE_ENABLED

def _ensure_database_schema():
    if not DATABASE_ENABLED:
        return
    with app.app_context():
        db.create_all()
        statements = [
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS onboarding_completed VARCHAR(20)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS site2 VARCHAR(255)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS active_session_token VARCHAR(255)",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS hours NUMERIC(10,2)",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS pay NUMERIC(10,2)",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS in_lat NUMERIC(12,8)",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS in_lon NUMERIC(12,8)",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS in_acc NUMERIC(10,2)",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS in_site VARCHAR(255)",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS in_dist_m INTEGER",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS out_lat NUMERIC(12,8)",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS out_lon NUMERIC(12,8)",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS out_acc NUMERIC(10,2)",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS out_site VARCHAR(255)",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS out_dist_m INTEGER",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS in_selfie_url TEXT",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS out_selfie_url TEXT",
            "ALTER TABLE workhours ADD COLUMN IF NOT EXISTS workplace_id VARCHAR(255)",
            "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS actor VARCHAR(255)",
            "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS username VARCHAR(255)",
            "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS date_text VARCHAR(50)",
            "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS details TEXT",
            "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS workplace_id VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS signature_datetime VARCHAR(100)",
        ]
        try:
            with db.engine.begin() as conn:
                for sql in statements:
                    try:
                        conn.exec_driver_sql(sql)
                    except Exception:
                        pass
        except Exception:
            pass


__all__ = ["_ensure_database_schema"]
