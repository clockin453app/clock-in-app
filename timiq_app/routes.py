# routes.py

import os
import json
import io
import base64
import hashlib
import binascii
import secrets
import string
import math
import re
import html
import time
import random
import logging
from urllib.parse import urlparse

try:
    from google.oauth2.service_account import Credentials as SACredentials
except Exception:
    SACredentials = None

try:
    import gspread
except Exception:
    gspread = None

from flask import jsonify
from flask import request, session, redirect, url_for, render_template_string, abort, make_response, send_file
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from datetime import date

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
except Exception:
    build = None
    MediaIoBaseUpload = None

try:
    from google_auth_oauthlib.flow import Flow
except Exception:
    Flow = None

try:
    from google.oauth2.credentials import Credentials as UserCredentials
except Exception:
    UserCredentials = None

try:
    from google.auth.transport.requests import Request
except Exception:
    Request = None

if gspread is None:
    class _FallbackGspreadUtils:
        @staticmethod
        def rowcol_to_a1(row, col):
            col_num = int(col)
            letters = ""
            while col_num > 0:
                col_num, rem = divmod(col_num - 1, 26)
                letters = chr(65 + rem) + letters
            return f"{letters}{int(row)}"

        @staticmethod
        def a1_to_rowcol(a1):
            a1 = str(a1 or "").strip().upper()
            letters = ""
            digits = ""
            for ch in a1:
                if ch.isalpha():
                    letters += ch
                elif ch.isdigit():
                    digits += ch
            col = 0
            for ch in letters:
                col = col * 26 + (ord(ch) - 64)
            return int(digits or 1), int(col or 1)


    class _FallbackGspread:
        utils = _FallbackGspreadUtils()


    gspread = _FallbackGspread()
from sqlalchemy import and_, or_, inspect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ================= PERFORMANCE: gspread caching =================
import time as _time
from collections import OrderedDict as _OrderedDict

_SHEETS_CACHE_TTL = int(os.environ.get("SHEETS_CACHE_TTL_SECONDS", "15") or "15")
_SHEETS_CACHE_MAX = int(os.environ.get("SHEETS_CACHE_MAX_ENTRIES", "256") or "256")
_sheets_cache = _OrderedDict()  # key -> (expires_at, value)


def _cache_get(key):
    now = _time.time()
    item = _sheets_cache.get(key)
    if not item:
        return None
    expires_at, value = item
    if expires_at < now:
        _sheets_cache.pop(key, None)
        return None
    # refresh LRU
    _sheets_cache.move_to_end(key, last=True)
    return value


def _cache_set(key, value, ttl=_SHEETS_CACHE_TTL):
    now = _time.time()
    expires_at = now + max(0, int(ttl))
    _sheets_cache[key] = (expires_at, value)
    _sheets_cache.move_to_end(key, last=True)
    while len(_sheets_cache) > _SHEETS_CACHE_MAX:
        _sheets_cache.popitem(last=False)


def _cache_invalidate_prefix(prefix):
    # prefix: tuple prefix
    for k in list(_sheets_cache.keys()):
        if isinstance(k, tuple) and k[:len(prefix)] == prefix:
            _sheets_cache.pop(k, None)


try:
    from gspread.worksheet import Worksheet as _Worksheet

    _orig_get_all_values = _Worksheet.get_all_values
    _orig_get_all_records = _Worksheet.get_all_records


    def _ws_key(ws, op, args, kwargs):
        # Spreadsheet ID is stable; Worksheet.id is numeric sheet id
        sid = getattr(getattr(ws, "spreadsheet", None), "id", None)
        wid = getattr(ws, "id", None)
        return (sid, wid, op, args, tuple(sorted(kwargs.items())))


    def cached_get_all_values(self, *args, **kwargs):
        key = _ws_key(self, "get_all_values", args, kwargs)
        hit = _cache_get(key)
        if hit is not None:
            return hit
        val = _orig_get_all_values(self, *args, **kwargs)
        _cache_set(key, val)
        return val


    def cached_get_all_records(self, *args, **kwargs):
        key = _ws_key(self, "get_all_records", args, kwargs)
        hit = _cache_get(key)
        if hit is not None:
            return hit
        val = _orig_get_all_records(self, *args, **kwargs)
        _cache_set(key, val)
        return val


    _Worksheet.get_all_values = cached_get_all_values
    _Worksheet.get_all_records = cached_get_all_records


    # Invalidate cache on common writes
    def _wrap_invalidate(method_name):
        orig = getattr(_Worksheet, method_name, None)
        if not orig:
            return

        def wrapped(self, *args, **kwargs):
            res = orig(self, *args, **kwargs)
            sid = getattr(getattr(self, "spreadsheet", None), "id", None)
            wid = getattr(self, "id", None)
            _cache_invalidate_prefix((sid, wid))
            return res

        setattr(_Worksheet, method_name, wrapped)


    for _m in ("update", "update_cell", "update_cells", "append_row", "append_rows", "batch_update", "delete_rows",
               "insert_row", "insert_rows", "clear"):
        _wrap_invalidate(_m)
except Exception:
    pass


# ============ GOOGLE SHEETS SAFE WRITE ============

def _gs_write_with_retry(fn, *, tries: int = 3, base_sleep: float = 0.6):
    """
    Retry wrapper for transient Google Sheets / network errors.
    """
    last_err = None
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            sleep_s = base_sleep * (2 ** attempt) + random.uniform(0, 0.25)
            time.sleep(sleep_s)
    raise last_err


# ================= APP =================
from .config import Settings
from .extensions import db
from .routing import DeferredRouteRegistry
from .models import (
    AuditLog,
    Employee,
    Location,
    OnboardingRecord,
    PayrollReport,
    WorkHour,
    WorkplaceSetting,
)

BASE_DIR = str(Settings.BASE_DIR)

APP_ENV = Settings.APP_ENV
DEBUG_MODE = Settings.DEBUG_MODE
IS_PRODUCTION = Settings.IS_PRODUCTION
SECRET_KEY = Settings.SECRET_KEY
DB_DEBUG_EXPORTS_ENABLED = Settings.DB_DEBUG_EXPORTS_ENABLED
DESTRUCTIVE_ADMIN_CONFIRM_VALUE = Settings.DESTRUCTIVE_ADMIN_CONFIRM_VALUE
MAX_CLOCK_LOCATION_ACCURACY_M = Settings.MAX_CLOCK_LOCATION_ACCURACY_M
MAX_CLOCK_LOCATION_AGE_S = Settings.MAX_CLOCK_LOCATION_AGE_S
ALLOWED_EMPLOYEE_ROLES = Settings.ALLOWED_EMPLOYEE_ROLES

DATABASE_URL = Settings.DATABASE_URL
DATABASE_ENABLED = Settings.DATABASE_ENABLED
USE_DATABASE = Settings.USE_DATABASE
DB_MIGRATION_MODE = Settings.DB_MIGRATION_MODE

_logger = logging.getLogger(__name__)
routes = DeferredRouteRegistry()

TZ = ZoneInfo(Settings.TZ_NAME)

# ================= DATABASE VIEW / IMPORT ROUTES =================


# ================= DATABASE READ HELPERS =================

def get_locations():
    return get_locations_data(USE_DATABASE, Location, _get_import_sheet)


def get_settings():
    return get_settings_data(USE_DATABASE, WorkplaceSetting, _get_import_sheet)


def get_employees():
    return get_employees_data(USE_DATABASE, Employee, _get_import_sheet)


def get_employees_compat():
    return employee_records_compat(get_employees())




def _find_employee_record(username: str, workplace_id: str | None = None):
    return find_employee_record(
        username=username,
        workplace_id=workplace_id,
        session_workplace_id=_session_workplace_id(),
        workplace_ids_for_read=_workplace_ids_for_read,
        password_is_hashed=_password_is_hashed,
        ensure_password_hash_for_user=_ensure_password_hash_for_user,
        employee_model=Employee if DB_MIGRATION_MODE else None,
        import_sheet=_get_import_sheet("employees"),
    )


def _list_employee_records_for_workplace(workplace_id: str | None = None, include_inactive: bool = True):
    return list_employee_records_for_workplace(
        workplace_id=workplace_id,
        include_inactive=include_inactive,
        session_workplace_id=_session_workplace_id(),
        workplace_ids_for_read=_workplace_ids_for_read,
        employee_model=Employee if DB_MIGRATION_MODE else None,
        import_sheet=_get_import_sheet("employees"),
    )


def get_workhours_rows():
    return get_workhours_rows_data(
        db_migration_mode=DB_MIGRATION_MODE,
        work_sheet=work_sheet,
        workhour_model=WorkHour,
        workplace_ids_for_read=_workplace_ids_for_read,
        round_to_half_hour_func=_round_to_half_hour,
        apply_unpaid_break_func=_apply_unpaid_break,
        get_user_rate_func=_get_user_rate,
    )


def get_payroll_rows():
    return get_payroll_rows_data(
        db_migration_mode=DB_MIGRATION_MODE,
        payroll_sheet=payroll_sheet,
        payroll_report_model=PayrollReport,
        workplace_ids_for_read=_workplace_ids_for_read,
    )


@routes.route("/db-test")
def db_test():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate

    try:
        tables = inspect(db.engine).get_table_names()
        return {"database": "connected", "tables": tables}
    except Exception as e:
        return {"database": "error", "message": str(e)}, 500


@routes.route("/db/employees")
def db_view_employees():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not is_sensitive_debug_export_enabled(DB_DEBUG_EXPORTS_ENABLED):
        abort(404)

    try:
        return jsonify(rows_to_dicts(Employee, allowed_columns=DB_DEBUG_ALLOWED_COLUMNS["employees"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@routes.route("/db/workhours")
def db_view_workhours():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not is_sensitive_debug_export_enabled(DB_DEBUG_EXPORTS_ENABLED):
        abort(404)

    try:
        return jsonify(rows_to_dicts(WorkHour, allowed_columns=DB_DEBUG_ALLOWED_COLUMNS["workhours"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@routes.route("/db/audit")
def db_view_audit():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not is_sensitive_debug_export_enabled(DB_DEBUG_EXPORTS_ENABLED):
        abort(404)

    try:
        return jsonify(rows_to_dicts(AuditLog, allowed_columns=DB_DEBUG_ALLOWED_COLUMNS["audit_logs"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@routes.route("/db/payroll")
def db_view_payroll():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not is_sensitive_debug_export_enabled(DB_DEBUG_EXPORTS_ENABLED):
        abort(404)

    try:
        return jsonify(rows_to_dicts(PayrollReport, allowed_columns=DB_DEBUG_ALLOWED_COLUMNS["payroll_reports"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@routes.route("/db/onboarding")
def db_view_onboarding():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not is_sensitive_debug_export_enabled(DB_DEBUG_EXPORTS_ENABLED):
        abort(404)

    try:
        return jsonify(
            rows_to_dicts(OnboardingRecord, allowed_columns=DB_DEBUG_ALLOWED_COLUMNS["onboarding_records"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@routes.route("/db/locations")
def db_view_locations():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not is_sensitive_debug_export_enabled(DB_DEBUG_EXPORTS_ENABLED):
        abort(404)

    try:
        return jsonify(rows_to_dicts(Location, allowed_columns=DB_DEBUG_ALLOWED_COLUMNS["locations"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@routes.route("/db/settings")
def db_view_settings():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not is_sensitive_debug_export_enabled(DB_DEBUG_EXPORTS_ENABLED):
        abort(404)

    try:
        return jsonify(
            rows_to_dicts(WorkplaceSetting, allowed_columns=DB_DEBUG_ALLOWED_COLUMNS["workplace_settings"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@routes.post("/db/upgrade-employees-table")
def db_upgrade_employees_table():
    gate = require_destructive_admin_post("db_upgrade_employees_table")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403

    try:
        statements = [
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS username VARCHAR(255)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS first_name VARCHAR(255)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS last_name VARCHAR(255)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS password TEXT",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS rate NUMERIC(10,2)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS early_access VARCHAR(10)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS active VARCHAR(10)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS workplace_id VARCHAR(255)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS active_session_token VARCHAR(255)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS site VARCHAR(255)",
        ]

        with db.engine.begin() as conn:
            for sql in statements:
                conn.exec_driver_sql(sql)

            cols = [
                row[0]
                for row in conn.exec_driver_sql(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'employees'
                    ORDER BY ordinal_position
                    """
                ).fetchall()
            ]

        return {
            "status": "ok",
            "table": "employees",
            "columns": cols,
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@routes.post("/db/upgrade-onboarding-table")
def db_upgrade_onboarding_table():
    gate = require_destructive_admin_post("db_upgrade_onboarding_table")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403

    try:
        statements = [
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS workplace_id VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS phone_country_code VARCHAR(20)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS phone_number VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS street_address TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS city VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS postcode VARCHAR(50)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS emergency_contact_phone_country_code VARCHAR(20)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS emergency_contact_phone_number VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS medical_details TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS cscs_number VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS cscs_expiry_date VARCHAR(50)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS employment_type VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS right_to_work_uk VARCHAR(20)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS national_insurance VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS utr VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS start_date VARCHAR(50)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS bank_account_number VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS sort_code VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS account_holder_name VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS company_trading_name VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS company_registration_no VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS date_of_contract VARCHAR(50)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS site_address TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS passport_or_birth_cert_link TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS cscs_front_back_link TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS public_liability_link TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS share_code_link TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS contract_accepted VARCHAR(20)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS signature_name VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS signature_date_time VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS submitted_at VARCHAR(100)",
        ]

        with db.engine.begin() as conn:
            for sql in statements:
                conn.exec_driver_sql(sql)

            cols = [
                row[0]
                for row in conn.exec_driver_sql(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'onboarding_records'
                    ORDER BY ordinal_position
                    """
                ).fetchall()
            ]

        return {"status": "ok", "table": "onboarding_records", "columns": cols}
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@routes.post("/import-employees")
def import_employees():
    gate = require_destructive_admin_post("import_employees")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        return import_employees_data(
            employee_model=Employee,
            get_import_sheet_func=_get_import_sheet,
            normalize_password_hash_value_func=_normalize_password_hash_value,
            db_session=db.session,
        )
    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


# ================= REMAINING IMPORT ROUTES =================

from decimal import Decimal
from .services.import_parsers import pick, to_str, to_decimal, to_int, to_date, to_datetime
from .services.db_debug import DB_DEBUG_ALLOWED_COLUMNS, is_sensitive_debug_export_enabled, rows_to_dicts
from .services.employee_records import employee_record_from_model, employee_records_compat, find_employee_record, list_employee_records_for_workplace, get_employee_display_name_data
from .services.read_helpers import get_locations_data, get_settings_data, get_employees_data
from .services.user_rates import get_user_rate_data
from .services.payroll_charts import build_payroll_chart_and_kpis
from .services.payroll_cards import build_payroll_employee_card
from .services.upload_validation import (detect_upload_kind, validate_upload_file, validate_clock_selfie_data_impl)
from .services.clock_storage import save_clock_selfie_locally, store_clock_selfie_impl
from .services.drive_oauth import make_oauth_flow, ensure_instance_dir, fernet_instance, save_drive_token_impl, load_drive_token_impl, get_service_account_drive_service_impl, get_user_drive_service_impl
from .services.ui_constants import VIEWPORT, PWA_TAGS, STYLE, CONTRACT_TEXT
from .services.sheets_runtime import get_import_sheet_by_name, init_google_sheets_runtime
from .services.ui_icons import (
    _svg_clock,
    _svg_clipboard,
    _svg_chart,
    _svg_doc,
    _svg_user,
    _svg_grid,
    _svg_logout,
    _svg_shield,
    _app_icon,
    _icon_dashboard,
    _icon_clock,
    _icon_timelogs,
    _icon_timesheets,
    _icon_payments,
    _icon_starter_form,
    _icon_admin,
    _icon_workplaces,
    _icon_profile,
    _icon_onboarding,
    _icon_payroll_report,
    _icon_company_settings,
    _icon_employee_sites,
    _icon_employees,
    _icon_connect_drive,
    _icon_locations,
    _icon_clock_selfies,
)
from .services.report_rows import get_payroll_rows_data, get_workhours_rows_data
from .services.clock_geo import sanitize_clock_geo, validate_recent_clock_capture, validate_user_location, get_site_config, get_active_locations, get_employee_sites, get_employee_site, haversine_m, ensure_workhours_geo_headers
from .services.import_actions import import_onboarding_data, import_workhours_data, import_payroll_data, import_employees_data, import_settings_data, import_locations_data, import_audit_data
from .services.clock_page_route import clock_page_impl
from .services.admin_employees_route import admin_employees_impl
from .services.admin_payroll_route import admin_payroll_impl
from .services.my_reports_print_route import my_reports_print_impl
from .services.admin_workplaces_route import admin_workplaces_impl
from .services.my_reports_pdf_route import my_reports_pdf_impl
from .services.payments_page_route import payments_page_impl
from .services.my_reports_csv_route import my_reports_csv_impl
from .services.onboarding_route import onboarding_impl
from .services.home_route import home_impl
from .services.my_reports_route import my_reports_impl
from .services.my_times_route import my_times_impl
from .services.admin_log_activities_route import admin_log_activities_impl
from .services.admin_route import admin_impl
from .services.admin_onboarding_download_route import admin_onboarding_download_impl
from .services.admin_locations_route import admin_locations_impl
from .services.my_week_report_route import my_week_report_impl
from .services.login_route import login_impl
from .services.change_password_route import change_password_impl
from .services.admin_company_route import admin_company_impl
from .services.admin_onboarding_list_route import admin_onboarding_list_impl
from .services.admin_onboarding_detail_route import admin_onboarding_detail_impl
from .services.admin_employee_sites_route import admin_employee_sites_impl
from .services.admin_employee_sites_save_route import admin_employee_sites_save_impl
from .services.admin_save_shift_route import admin_save_shift_impl
from .services.admin_force_clockin_route import admin_force_clockin_impl
from .services.admin_force_clockout_route import admin_force_clockout_impl
from .services.admin_mark_paid_route import admin_mark_paid_impl
from .services.admin_payroll_report_csv_route import admin_payroll_report_csv_impl
from .services.admin_locations_save_route import admin_locations_save_impl
from .services.admin_locations_deactivate_route import admin_locations_deactivate_impl
from .services.admin_clock_selfies_route import admin_clock_selfies_impl


@routes.post("/import-locations")
def import_locations():
    gate = require_destructive_admin_post("import_locations")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        return import_locations_data(
            location_model=Location,
            get_locations_func=get_locations,
            to_str_func=to_str,
            to_decimal_func=to_decimal,
            to_int_func=to_int,
            pick_func=pick,
            db_session=db.session,
        )
    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@routes.post("/import-settings")
def import_settings():
    gate = require_destructive_admin_post("import_settings")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        return import_settings_data(
            workplace_setting_model=WorkplaceSetting,
            get_import_sheet_func=_get_import_sheet,
            to_str_func=to_str,
            to_decimal_func=to_decimal,
            pick_func=pick,
            db_session=db.session,
        )
    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@routes.post("/import-audit")
def import_audit():
    gate = require_destructive_admin_post("import_audit")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        return import_audit_data(
            audit_log_model=AuditLog,
            get_import_sheet_func=_get_import_sheet,
            to_str_func=to_str,
            to_datetime_func=to_datetime,
            pick_func=pick,
            db_session=db.session,
        )
    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500

@routes.post("/import-payroll")
def import_payroll():
    gate = require_destructive_admin_post("import_payroll")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        return import_payroll_data(
            payroll_report_model=PayrollReport,
            get_import_sheet_func=_get_import_sheet,
            to_str_func=to_str,
            to_date_func=to_date,
            to_datetime_func=to_datetime,
            to_decimal_func=to_decimal,
            pick_func=pick,
            db_session=db.session,
        )
    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@routes.post("/import-onboarding")
def import_onboarding():
    gate = require_destructive_admin_post("import_onboarding")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        return import_onboarding_data(
            onboarding_record_model=OnboardingRecord,
            get_import_sheet_func=_get_import_sheet,
            to_str_func=to_str,
            pick_func=pick,
            db_session=db.session,
        )
    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@routes.post("/import-workhours")
def import_workhours():
    gate = require_destructive_admin_post("import_workhours")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        return import_workhours_data(
            workhour_model=WorkHour,
            get_import_sheet_func=_get_import_sheet,
            to_str_func=to_str,
            to_date_func=to_date,
            pick_func=pick,
            datetime_cls=datetime,
            db_session=db.session,
        )
    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


# ================= GOOGLE SHEETS (SERVICE ACCOUNT) =================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEETS_RUNTIME_ENABLED = os.environ.get("ENABLE_SHEETS_RUNTIME", "1" if not DATABASE_ENABLED else "0") == "1"
SHEETS_IMPORT_ENABLED = os.environ.get("ENABLE_SHEETS_IMPORT", "1" if not DATABASE_ENABLED else "0") == "1"
ENABLE_GOOGLE_SHEETS = SHEETS_RUNTIME_ENABLED or SHEETS_IMPORT_ENABLED

creds_json = os.environ.get("GOOGLE_CREDENTIALS", "").strip()


def _get_import_sheet(sheet_name: str):
    return get_import_sheet_by_name(
        sheet_name,
        {
            "employees": employees_sheet,
            "workhours": work_sheet,
            "payroll": payroll_sheet,
            "onboarding": onboarding_sheet,
            "settings": settings_sheet,
            "audit": audit_sheet,
            "locations": locations_sheet,
        },
    )


_sheets_runtime = init_google_sheets_runtime(
    enable_google_sheets=ENABLE_GOOGLE_SHEETS,
    gspread_mod=gspread,
    sa_credentials_cls=SACredentials,
    creds_json=creds_json,
    scopes=SCOPES,
    spreadsheet_id=os.environ.get("SPREADSHEET_ID", "").strip(),
    logger=_logger,
)

creds = _sheets_runtime["creds"]
client = _sheets_runtime["client"]
spreadsheet = _sheets_runtime["spreadsheet"]
employees_sheet = _sheets_runtime["employees_sheet"]
work_sheet = _sheets_runtime["work_sheet"]
payroll_sheet = _sheets_runtime["payroll_sheet"]
onboarding_sheet = _sheets_runtime["onboarding_sheet"]
settings_sheet = _sheets_runtime["settings_sheet"]
audit_sheet = _sheets_runtime["audit_sheet"]
locations_sheet = _sheets_runtime["locations_sheet"]

# ================= GOOGLE DRIVE UPLOAD (OAUTH USER) =================
OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive"]

UPLOAD_FOLDER_ID = os.environ.get("ONBOARDING_DRIVE_FOLDER_ID", "").strip()
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "").strip()
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "").strip()
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "").strip()


def _make_oauth_flow():
    return make_oauth_flow(
        client_id=OAUTH_CLIENT_ID,
        client_secret=OAUTH_CLIENT_SECRET,
        redirect_uri=OAUTH_REDIRECT_URI,
        flow_cls=Flow,
        oauth_scopes=OAUTH_SCOPES,
    )


# ---- Drive OAuth token storage (SERVER-SIDE) ----

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:
    Fernet = None
    InvalidToken = Exception

DRIVE_TOKEN_STORE_PATH = os.environ.get(
    "DRIVE_TOKEN_STORE_PATH",
    os.path.join(BASE_DIR, "instance", "drive_token.enc"),
)
DRIVE_TOKEN_ENV = os.environ.get("DRIVE_TOKEN_JSON", "").strip()
DRIVE_TOKEN_ENCRYPTION_KEY = os.environ.get("DRIVE_TOKEN_ENCRYPTION_KEY", "").strip()


def _ensure_instance_dir():
    return ensure_instance_dir(DRIVE_TOKEN_STORE_PATH)


def _fernet():
    return fernet_instance(Fernet, DRIVE_TOKEN_ENCRYPTION_KEY, SECRET_KEY)


def _save_drive_token(token_dict: dict):
    return save_drive_token_impl(token_dict, DRIVE_TOKEN_STORE_PATH, _fernet)


def _load_drive_token() -> dict | None:
    return load_drive_token_impl(DRIVE_TOKEN_STORE_PATH, _fernet, DRIVE_TOKEN_ENV, InvalidToken)


def get_service_account_drive_service():
    return get_service_account_drive_service_impl(build, creds)


def get_user_drive_service():
    return get_user_drive_service_impl(
        load_drive_token_func=_load_drive_token,
        user_credentials_cls=UserCredentials,
        request_cls=Request,
        save_drive_token_func=_save_drive_token,
        build_func=build,
    )


UPLOAD_MAX_BYTES = int(os.environ.get("UPLOAD_MAX_BYTES", str(10 * 1024 * 1024)) or str(10 * 1024 * 1024))
_ALLOWED_UPLOAD_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
_ALLOWED_UPLOAD_MIMES = {"application/pdf", "image/jpeg", "image/png", "image/webp", "application/octet-stream"}

WORKPLACE_ID_MIGRATION_FROM = "default"
WORKPLACE_ID_MIGRATION_TO = "newera"


def _workplace_ids_for_read(workplace_id: str | None = None):
    wp = (workplace_id or _session_workplace_id() or "default").strip() or "default"
    ids = [wp]
    if wp == WORKPLACE_ID_MIGRATION_TO and WORKPLACE_ID_MIGRATION_FROM not in ids:
        ids.append(WORKPLACE_ID_MIGRATION_FROM)
    return ids


def _allowed_workplace_ids_for_admin_write(workplace_id: str | None = None):
    """Exact workplace only for writes. Reads may remain migration-tolerant."""
    wp = (workplace_id or _session_workplace_id() or "default").strip() or "default"
    return [wp]


def _employee_query_for_write(username: str, workplace_id: str | None = None):
    target_user = (username or "").strip()
    allowed_wps = _allowed_workplace_ids_for_admin_write(workplace_id)

    return Employee.query.filter(
        and_(
            or_(Employee.username == target_user, Employee.email == target_user),
            or_(
                Employee.workplace_id.in_(allowed_wps),
                and_(Employee.workplace_id.is_(None), Employee.workplace.in_(allowed_wps)),
                Employee.workplace.in_(allowed_wps),
            ),
        )
    )


def _workhour_query_for_user(username: str, workplace_id: str | None = None):
    target_user = (username or "").strip()
    allowed_wps = _allowed_workplace_ids_for_admin_write(workplace_id)

    return WorkHour.query.filter(
        and_(
            WorkHour.employee_email == target_user,
            or_(
                WorkHour.workplace_id.in_(allowed_wps),
                and_(WorkHour.workplace_id.is_(None), WorkHour.workplace.in_(allowed_wps)),
                WorkHour.workplace.in_(allowed_wps),
            ),
        )
    )
def _get_canonical_workhour_for_day(username: str, shift_date, workplace_id: str | None = None):
    wp = (workplace_id or _session_workplace_id() or "default").strip() or "default"

    rows = (
        _workhour_query_for_user(username, wp)
        .filter(WorkHour.date == shift_date)
        .order_by(WorkHour.id.asc())
        .all()
    )

    if not rows:
        rec = WorkHour(
            employee_email=username,
            date=shift_date,
            workplace=wp,
            workplace_id=wp,
        )
        db.session.add(rec)
        return rec

    keep = rows[-1]  # keep newest row

    def copy_if_missing(attr: str):
        current = getattr(keep, attr, None)
        if current not in (None, ""):
            return
        for old in reversed(rows[:-1]):
            val = getattr(old, attr, None)
            if val not in (None, ""):
                setattr(keep, attr, val)
                return

    for attr in (
        "clock_in",
        "clock_out",
        "hours",
        "pay",
        "in_lat",
        "in_lon",
        "in_acc",
        "in_site",
        "in_dist_m",
        "in_selfie_url",
        "out_lat",
        "out_lon",
        "out_acc",
        "out_site",
        "out_dist_m",
        "out_selfie_url",
    ):
        copy_if_missing(attr)

    keep.employee_email = username
    keep.date = shift_date
    keep.workplace = wp
    keep.workplace_id = wp

    for old in rows[:-1]:
        db.session.delete(old)

    return keep


def _payroll_query_for_user(username: str, workplace_id: str | None = None):
    target_user = (username or "").strip()
    allowed_wps = _allowed_workplace_ids_for_admin_write(workplace_id)

    return PayrollReport.query.filter(
        and_(
            PayrollReport.username == target_user,
            PayrollReport.workplace_id.in_(allowed_wps),
        )
    )


def _onboarding_query_for_user(username: str, workplace_id: str | None = None):
    target_user = (username or "").strip()
    allowed_wps = _allowed_workplace_ids_for_admin_write(workplace_id)

    return OnboardingRecord.query.filter(
        and_(
            OnboardingRecord.username == target_user,
            OnboardingRecord.workplace_id.in_(allowed_wps),
        )
    )

# Clock selfie settings
CLOCK_SELFIE_REQUIRED = str(os.environ.get("CLOCK_SELFIE_REQUIRED", "true") or "true").strip().lower() in ("1", "true",
                                                                                                           "yes", "on")
CLOCK_SELFIE_MAX_BYTES = int(os.environ.get("CLOCK_SELFIE_MAX_BYTES", str(1 * 1024 * 1024)) or str(1 * 1024 * 1024))
CLOCK_SELFIE_BASE_DIR = os.environ.get(
    "CLOCK_SELFIE_BASE_DIR",
    os.path.join(BASE_DIR, "instance"),
).strip()

CLOCK_SELFIE_DIR = os.path.join(CLOCK_SELFIE_BASE_DIR, "clock_selfies")
_ALLOWED_CLOCK_SELFIE_MIMES = {"image/jpeg", "image/png", "image/webp"}


def upload_to_drive(file_storage, filename_prefix: str) -> str:

    drive_service = get_user_drive_service()


    if not drive_service:
        drive_service = get_service_account_drive_service()

    if not drive_service:
        raise RuntimeError("Drive upload is not available.")

    if UPLOAD_FOLDER_ID:
        try:
            drive_service.files().get(
                fileId=UPLOAD_FOLDER_ID,
                fields="id,name",
                supportsAllDrives=True
            ).execute()
        except Exception as e:
            raise RuntimeError("Upload folder not found or not shared with app account.") from e

    file_bytes, detected_mime, safe_name = validate_upload_file(
        file_storage,
        UPLOAD_MAX_BYTES,
        _ALLOWED_UPLOAD_EXTS,
        _ALLOWED_UPLOAD_MIMES,
    )
    name = f"{filename_prefix}_{safe_name}"

    media = MediaIoBaseUpload(
        io.BytesIO(file_bytes),
        mimetype=detected_mime,
        resumable=False,
    )

    metadata = {"name": name}
    if UPLOAD_FOLDER_ID:
        metadata["parents"] = [UPLOAD_FOLDER_ID]

    created = drive_service.files().create(
        body=metadata,
        media_body=media,
        fields="id, webViewLink",
        supportsAllDrives=True,
    ).execute()

    file_id = created["id"]
    return created.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"


def _upload_bytes_to_drive(file_bytes: bytes, filename_prefix: str, safe_name: str, mime_type: str) -> str:
    drive_service = get_user_drive_service()
    if not drive_service:
        drive_service = get_service_account_drive_service()
    if not drive_service:
        raise RuntimeError("Drive upload is not available.")

    if UPLOAD_FOLDER_ID:
        try:
            drive_service.files().get(
                fileId=UPLOAD_FOLDER_ID,
                fields="id,name",
                supportsAllDrives=True
            ).execute()
        except Exception as e:
            raise RuntimeError("Upload folder not found or not shared with app account.") from e

    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=False)
    metadata = {"name": f"{filename_prefix}_{safe_name}"}
    if UPLOAD_FOLDER_ID:
        metadata["parents"] = [UPLOAD_FOLDER_ID]

    created = drive_service.files().create(
        body=metadata,
        media_body=media,
        fields="id, webViewLink",
        supportsAllDrives=True,
    ).execute()

    file_id = created["id"]
    return created.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"

def _save_clock_selfie_locally(file_bytes: bytes, safe_name: str) -> str:
    return save_clock_selfie_locally(
        file_bytes=file_bytes,
        safe_name=safe_name,
        clock_selfie_dir=CLOCK_SELFIE_DIR,
        token_hex_func=secrets.token_hex,
        url_for_func=url_for,
    )

def _validate_clock_selfie_data(selfie_data_url: str):
    return validate_clock_selfie_data_impl(
        selfie_data_url=selfie_data_url,
        allowed_clock_selfie_mimes=_ALLOWED_CLOCK_SELFIE_MIMES,
        clock_selfie_max_bytes=CLOCK_SELFIE_MAX_BYTES,
        detect_upload_kind_func=detect_upload_kind,
    )

def _store_clock_selfie(selfie_data_url: str, username: str, action: str, now_dt: datetime) -> str:
    return store_clock_selfie_impl(
        selfie_data_url=selfie_data_url,
        username=username,
        action=action,
        now_dt=now_dt,
        validate_clock_selfie_data_func=_validate_clock_selfie_data,
        upload_bytes_to_drive_func=_upload_bytes_to_drive,
        save_clock_selfie_locally_func=_save_clock_selfie_locally,
        secure_filename_func=secure_filename,
    )

@routes.get("/admin/clock-selfies")
def admin_clock_selfies():
    return admin_clock_selfies_impl(core=globals())


@routes.get("/clock-selfie/<path:filename>")
def view_clock_selfie(filename):
    gate = require_admin()
    if gate:
        return gate

    safe_filename = os.path.basename(filename or "")
    if not safe_filename:
        abort(404)

    full_path = os.path.abspath(os.path.join(CLOCK_SELFIE_DIR, safe_filename))
    base_path = os.path.abspath(CLOCK_SELFIE_DIR)
    if not full_path.startswith(base_path + os.sep):
        abort(403)
    if not os.path.exists(full_path):
        abort(404)

    ext = os.path.splitext(safe_filename)[1].lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(ext,
                                                                                                         "application/octet-stream")
    return send_file(full_path, mimetype=mime)


# ================= CONSTANTS =================
COL_USER = 0
COL_DATE = 1
COL_IN = 2
COL_OUT = 3
COL_HOURS = 4
COL_PAY = 5

# Extra columns (optional; appended after Pay). Used for geolocation.
COL_IN_LAT = 6
COL_IN_LON = 7
COL_IN_ACC = 8
COL_IN_SITE = 9
COL_OUT_LAT = 10
COL_OUT_LON = 11
COL_OUT_ACC = 12
COL_OUT_SITE = 13
TAX_RATE = 0.20
CLOCKIN_EARLIEST = dtime(8, 0, 0)

# Break rules:
UNPAID_BREAK_HOURS = 0.5  # deduct 30 minutes
BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS = 6.0  # safety threshold

# Overtime highlight:
OVERTIME_HOURS = 8.5


# ================= PWA =================
@routes.get("/manifest.webmanifest")
def manifest():
    return {
        "name": "TimIQ",
        "short_name": "TimIQ",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#1f2d63",
        "theme_color": "#1f2d63",
        "icons": [
            {"src": "/static/icon-192.png?v=3", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png?v=3", "sizes": "512x512", "type": "image/png"},
        ],
    }, 200, {"Content-Type": "application/manifest+json"}


# ================= HELPERS =================

def _ensure_employees_columns():
    """Ensure Employees sheet has required columns (append-only)."""
    if not employees_sheet:
        return
    needed = [
        "Username", "Password", "Role", "Rate",
        "EarlyAccess", "OnboardingCompleted",
        "FirstName", "LastName", "Site", "Workplace_ID",
    ]
    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return
        headers = vals[0] or []
        if not headers:
            return
        missing = [h for h in needed if h not in headers]
        if not missing:
            return
        new_headers = headers + missing
        end_col = gspread.utils.rowcol_to_a1(1, len(new_headers)).replace("1", "")
        employees_sheet.update(f"A1:{end_col}1", [new_headers])
    except Exception:
        return


def _employees_usernames_for_workplace(wp: str) -> set[str]:
    """Return lowercase set of usernames in Employees for this workplace."""
    out = set()
    target_wp = (wp or "").strip() or "default"

    if DB_MIGRATION_MODE:
        try:
            rows = Employee.query.filter(
                or_(
                    Employee.workplace_id == target_wp,
                    and_(Employee.workplace_id.is_(None), Employee.workplace == target_wp),
                    Employee.workplace == target_wp,
                )
            ).all()
            for rec in rows:
                u = str(getattr(rec, "username", None) or getattr(rec, "email", None) or "").strip().lower()
                if u:
                    out.add(u)
            return out
        except Exception:
            pass

    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return out
        headers = vals[0] or []
        if "Username" not in headers:
            return out
        ucol = headers.index("Username")
        wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None

        for r in vals[1:]:
            u = (r[ucol] if ucol < len(r) else "").strip()
            if not u:
                continue
            if wp_col is not None:
                row_wp = (r[wp_col] if wp_col < len(r) else "").strip() or "default"
                if row_wp != target_wp:
                    continue
            out.add(u.lower())
    except Exception:
        pass
    return out


def _slug_login(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _generate_unique_username(first: str, last: str, wp: str) -> str:
    existing = _employees_usernames_for_workplace(wp)

    base = _slug_login((first[:1] if first else "") + (last or ""))
    if not base:
        base = _slug_login(first or last or "user")
    if not base:
        base = "user"

    cand = base
    if cand.lower() not in existing:
        return cand

    # Try random numeric suffixes (fast, avoids long loops)
    for _ in range(200):
        suffix = 1000 + secrets.randbelow(9000)
        cand = f"{base}{suffix}"
        if cand.lower() not in existing:
            return cand

    # Worst-case fallback
    return f"{base}{secrets.token_hex(2)}"


def _generate_temp_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(max(8, int(length or 10))))


# --- Break policy (unpaid break) ---------------------------------------------
# Default: subtract 30 minutes from shifts >= 6 hours.
UNPAID_BREAK_ENABLED = True
UNPAID_BREAK_THRESHOLD_HOURS = 6.0
UNPAID_BREAK_MINUTES = 30


def _session_workplace_id():
    wp = (session.get("workplace_id") or "").strip()
    if wp:
        return wp

    try:
        if DB_MIGRATION_MODE:
            has_old = WorkplaceSetting.query.filter_by(workplace_id=WORKPLACE_ID_MIGRATION_OLD).first() is not None
            has_new = WorkplaceSetting.query.filter_by(workplace_id=WORKPLACE_ID_MIGRATION_NEW).first() is not None
            if has_new and not has_old:
                return WORKPLACE_ID_MIGRATION_NEW
        else:
            vals = settings_sheet.get_all_values() if settings_sheet else []
            headers = vals[0] if vals else []
            i_wp = headers.index("Workplace_ID") if headers and "Workplace_ID" in headers else None

            if i_wp is not None:
                has_old = False
                has_new = False
                for r in (vals[1:] if len(vals) > 1 else []):
                    row_wp = (r[i_wp] if i_wp < len(r) else "").strip()
                    if row_wp == WORKPLACE_ID_MIGRATION_OLD:
                        has_old = True
                    elif row_wp == WORKPLACE_ID_MIGRATION_NEW:
                        has_new = True

                if has_new and not has_old:
                    return WORKPLACE_ID_MIGRATION_NEW
    except Exception:
        pass

    return WORKPLACE_ID_MIGRATION_OLD


def _migrate_workplace_id_in_sheet(ws, old_wp: str, new_wp: str) -> int:
    if not ws:
        return 0

    try:
        vals = ws.get_all_values()
    except Exception:
        return 0

    if not vals:
        return 0

    hdr = vals[0] if vals else []
    if not hdr:
        return 0

    wp_cols = [i for i, h in enumerate(hdr) if str(h or "").strip() in ("Workplace_ID", "workplace_id")]
    if not wp_cols:
        return 0

    max_cols = max(len(r) for r in vals) if vals else len(hdr)
    for r in vals:
        if len(r) < max_cols:
            r.extend([""] * (max_cols - len(r)))

    changed = 0
    for r_idx in range(1, len(vals)):
        for c_idx in wp_cols:
            raw = vals[r_idx][c_idx] if c_idx < len(vals[r_idx]) else ""
            current = (str(raw or "").strip() or "default")
            if current == old_wp:
                vals[r_idx][c_idx] = new_wp
                changed += 1

    if changed:
        end_a1 = gspread.utils.rowcol_to_a1(len(vals), max_cols)
        _gs_write_with_retry(lambda: ws.update(f"A1:{end_a1}", vals))

    return changed


WORKPLACE_ID_MIGRATION_OLD = "default"
WORKPLACE_ID_MIGRATION_NEW = "newera"
WORKPLACE_ID_MIGRATION_CONFIRM = "MIGRATE"


def _normalize_workplace_id_value(value):
    return (str(value or "").strip() or "default")


def _migrate_workplace_id_in_model(model, field_names, old_wp: str, new_wp: str):
    valid_fields = [field_name for field_name in field_names if hasattr(model, field_name)]
    if not valid_fields:
        return {
            "rows_updated": 0,
            "field_updates": 0,
        }

    row_ids = set()

    if hasattr(model, "id"):
        for field_name in valid_fields:
            col = getattr(model, field_name)
            flt = (col == old_wp)
            if old_wp == WORKPLACE_ID_MIGRATION_OLD:
                flt = flt | (col == "") | col.is_(None)

            for row_id, in model.query.with_entities(model.id).filter(flt).all():
                row_ids.add(row_id)

    field_updates = 0

    for field_name in valid_fields:
        col = getattr(model, field_name)
        flt = (col == old_wp)
        if old_wp == WORKPLACE_ID_MIGRATION_OLD:
            flt = flt | (col == "") | col.is_(None)

        count = model.query.filter(flt).update(
            {field_name: new_wp},
            synchronize_session=False,
        )
        field_updates += int(count or 0)

    return {
        "rows_updated": len(row_ids),
        "field_updates": field_updates,
    }


def _run_workplace_id_migration(old_wp: str | None = None, new_wp: str | None = None):
    old_wp = _normalize_workplace_id_value(old_wp or WORKPLACE_ID_MIGRATION_OLD)
    new_wp = _normalize_workplace_id_value(new_wp or WORKPLACE_ID_MIGRATION_NEW)

    report = {
        "ok": True,
        "old_workplace_id": old_wp,
        "new_workplace_id": new_wp,
        "sheets": {},
        "db": {},
    }

    if DB_MIGRATION_MODE:
        try:
            existing_old = WorkplaceSetting.query.filter_by(workplace_id=old_wp).first()
            existing_new = WorkplaceSetting.query.filter_by(workplace_id=new_wp).first()
            if existing_old and existing_new and existing_old.id != existing_new.id:
                report["db"]["WorkplaceSetting"] = {
                    "rows_updated": 0,
                    "field_updates": 0,
                    "error": f"Target workplace_id {new_wp!r} already exists in workplace_settings.",
                }
                report["ok"] = False
                return report
        except Exception as e:
            report["db"]["_error"] = str(e)
            report["ok"] = False
            return report

    sheet_targets = [
        ("settings_sheet", settings_sheet),
        ("employees_sheet", employees_sheet),
        ("work_sheet", work_sheet),
        ("payroll_sheet", payroll_sheet),
        ("onboarding_sheet", onboarding_sheet),
        ("locations_sheet", locations_sheet),
        ("audit_sheet", audit_sheet),
    ]

    for label, ws in sheet_targets:
        try:
            report["sheets"][label] = {
                "updated": _migrate_workplace_id_in_sheet(ws, old_wp, new_wp)
            }
        except Exception as e:
            report["sheets"][label] = {
                "updated": 0,
                "error": str(e),
            }
            report["ok"] = False

    if DB_MIGRATION_MODE:
        try:
            db_targets = [
                ("WorkplaceSetting", WorkplaceSetting, ("workplace_id",)),
                ("Employee", Employee, ("workplace_id", "workplace")),
                ("WorkHour", WorkHour, ("workplace_id", "workplace")),
                ("PayrollReport", PayrollReport, ("workplace_id",)),
                ("OnboardingRecord", OnboardingRecord, ("workplace_id",)),
                ("Location", Location, ("workplace_id",)),
                ("AuditLog", AuditLog, ("workplace_id",)),
            ]

            for label, model, field_names in db_targets:
                report["db"][label] = _migrate_workplace_id_in_model(model, field_names, old_wp, new_wp)

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            report["db"]["_error"] = str(e)
            report["ok"] = False
    else:
        report["db"]["_skipped"] = "DB_MIGRATION_MODE is off"

    return report


def _row_workplace_id(row):
    return (row.get("Workplace_ID") or "").strip() or "default"


def _same_workplace(row):
    return _row_workplace_id(row) == _session_workplace_id()


def _round_to_half_hour(value: float) -> float:
    try:
        n = max(0.0, float(value or 0.0))
    except Exception:
        return 0.0
    return math.floor((n * 2.0) + 0.5) / 2.0


def _apply_unpaid_break(raw_hours: float) -> float:
    """Return payable hours after applying unpaid break policy."""
    try:
        h = float(raw_hours or 0.0)
    except Exception:
        return 0.0

    if not UNPAID_BREAK_ENABLED:
        return max(0.0, h)

    if h >= float(UNPAID_BREAK_THRESHOLD_HOURS):
        h -= float(UNPAID_BREAK_MINUTES) / 60.0

    return max(0.0, h)


from datetime import timedelta


def user_in_same_workplace(username: str) -> bool:
    target = (username or "").strip()
    if not target:
        return False

    current_wp = _session_workplace_id()

    if DB_MIGRATION_MODE:
        try:
            rec = Employee.query.filter(
                and_(
                    or_(Employee.username == target, Employee.email == target),
                    or_(
                        Employee.workplace_id == current_wp,
                        and_(Employee.workplace_id.is_(None), Employee.workplace == current_wp),
                        Employee.workplace == current_wp,
                    ),
                )
            ).first()
            return rec is not None
        except Exception:
            return False

    try:
        for rec in _get_import_sheet("employees").get_all_records():
            rec_user = (rec.get("Username") or "").strip()
            if rec_user != target:
                continue
            rec_wp = (rec.get("Workplace_ID") or "").strip() or "default"
            if rec_wp == current_wp:
                return True
        return False
    except Exception:
        return False


def get_company_settings() -> dict:
    """Return current workplace settings with safe defaults."""
    defaults = {
        "Workplace_ID": _session_workplace_id(),
        "Tax_Rate": 20.0,
        "Currency_Symbol": "£",
        "Company_Name": "Main",
        "Company_Logo_URL": "",
        "Overtime_After_Hours": 8.5,
        "Overtime_Multiplier": 1.5,
    }

    current_wp = _session_workplace_id()
    preferred_wps = _workplace_ids_for_read(current_wp)

    try:
        records = WorkplaceSetting.query.all() if DB_MIGRATION_MODE else (get_settings() or [])

        best = None
        best_rank = 999

        for rec in records:
            if isinstance(rec, dict):
                row_wp = str(rec.get("Workplace_ID") or rec.get("workplace_id") or "default").strip() or "default"
                tax_raw = str(rec.get("Tax_Rate") or rec.get("tax_rate") or "").strip()
                cur = str(
                    rec.get("Currency_Symbol") or rec.get("currency_symbol") or defaults["Currency_Symbol"]
                ).strip() or defaults["Currency_Symbol"]
                name = str(
                    rec.get("Company_Name") or rec.get("company_name") or defaults["Company_Name"]
                ).strip() or defaults["Company_Name"]
                logo = str(rec.get("Company_Logo_URL") or rec.get("company_logo_url") or "").strip()
                overtime_after_raw = str(
                    rec.get("Overtime_After_Hours") or rec.get("overtime_after_hours") or ""
                ).strip()
                overtime_mult_raw = str(
                    rec.get("Overtime_Multiplier") or rec.get("overtime_multiplier") or ""
                ).strip()
            else:
                row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip() or "default"
                tax_val = getattr(rec, "tax_rate", None)
                tax_raw = "" if tax_val is None else str(tax_val).strip()
                cur = str(
                    getattr(rec, "currency_symbol", defaults["Currency_Symbol"]) or defaults["Currency_Symbol"]
                ).strip() or defaults["Currency_Symbol"]
                name = str(
                    getattr(rec, "company_name", defaults["Company_Name"]) or defaults["Company_Name"]
                ).strip() or defaults["Company_Name"]
                logo = str(getattr(rec, "company_logo_url", "") or "").strip()
                overtime_after_val = getattr(rec, "overtime_after_hours", None)
                overtime_mult_val = getattr(rec, "overtime_multiplier", None)
                overtime_after_raw = "" if overtime_after_val is None else str(overtime_after_val).strip()
                overtime_mult_raw = "" if overtime_mult_val is None else str(overtime_mult_val).strip()

            if row_wp not in preferred_wps:
                continue

            rank = preferred_wps.index(row_wp)
            if rank >= best_rank:
                continue

            try:
                tax = float(tax_raw) if tax_raw != "" else defaults["Tax_Rate"]
            except Exception:
                tax = defaults["Tax_Rate"]

            try:
                overtime_after = float(overtime_after_raw) if overtime_after_raw != "" else defaults["Overtime_After_Hours"]
            except Exception:
                overtime_after = defaults["Overtime_After_Hours"]

            try:
                overtime_mult = float(overtime_mult_raw) if overtime_mult_raw != "" else defaults["Overtime_Multiplier"]
            except Exception:
                overtime_mult = defaults["Overtime_Multiplier"]

            best = {
                "Workplace_ID": current_wp,
                "Tax_Rate": tax,
                "Currency_Symbol": cur,
                "Company_Name": name,
                "Company_Logo_URL": logo,
                "Overtime_After_Hours": overtime_after,
                "Overtime_Multiplier": overtime_mult,
            }
            best_rank = rank

        return best or defaults
    except Exception:
        return defaults


def _calculate_shift_pay(hours_value: float, rate_value: float) -> float:
    settings = get_company_settings()

    try:
        hours_num = max(0.0, float(hours_value or 0.0))
    except Exception:
        hours_num = 0.0

    try:
        rate_num = max(0.0, float(rate_value or 0.0))
    except Exception:
        rate_num = 0.0

    try:
        overtime_after = max(0.0, float(settings.get("Overtime_After_Hours", 8.5) or 8.5))
    except Exception:
        overtime_after = 8.5

    try:
        overtime_mult = max(1.0, float(settings.get("Overtime_Multiplier", 1.5) or 1.5))
    except Exception:
        overtime_mult = 1.5

    normal_hours = min(hours_num, overtime_after)
    overtime_hours = max(0.0, hours_num - overtime_after)

    total = (normal_hours * rate_num) + (overtime_hours * rate_num * overtime_mult)
    return round(total, 2)



def _compute_hours_from_times(date_str: str, cin: str, cout: str) -> float | None:
    """
    Compute payable hours between cin and cout on date_str.
    Accepts HH:MM or HH:MM:SS. Supports overnight (clock-out past midnight).
    Applies unpaid break policy and returns a rounded float.
    """
    try:
        d = (date_str or "").strip()
        t_in = (cin or "").strip()
        t_out = (cout or "").strip()
        if not d or not t_in or not t_out:
            return None

        # Normalize times to HH:MM:SS
        if len(t_in.split(":")) == 2:
            t_in = t_in + ":00"
        if len(t_out.split(":")) == 2:
            t_out = t_out + ":00"

        start_dt = datetime.strptime(f"{d} {t_in}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
        end_dt = datetime.strptime(f"{d} {t_out}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)

        # If clock-out earlier than clock-in, assume it crossed midnight
        if end_dt < start_dt:
            end_dt = end_dt + timedelta(days=1)

        raw_hours = max(0.0, (end_dt - start_dt).total_seconds() / 3600.0)

        # Apply your unpaid break policy
        payable = _apply_unpaid_break(raw_hours)

        return _round_to_half_hour(payable)
    except Exception:
        return None


def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def parse_bool(v) -> bool:
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def escape(s: str) -> str:
    return html.escape(str(s or ""), quote=True)


def linkify(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    p = urlparse(u)
    if p.scheme not in ("http", "https"):
        return ""
    uesc = escape(u)
    return (
        f'<a href="{uesc}" target="_blank" rel="noopener noreferrer" '
        f'style="color:var(--navy);font-weight:600;">Open</a>'
    )


# ================= GEOLOCATION (GEOFENCE) =================

WORKHOURS_GEO_HEADERS = [
    "InLat", "InLon", "InAcc", "InSite", "InDistM", "InSelfieURL",
    "OutLat", "OutLon", "OutAcc", "OutSite", "OutDistM", "OutSelfieURL",
]


def _ensure_workhours_geo_headers():
    return ensure_workhours_geo_headers(
        work_sheet_obj=work_sheet,
        gspread_mod=gspread,
        workhours_geo_headers=WORKHOURS_GEO_HEADERS,
    )


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    return haversine_m(lat1, lon1, lat2, lon2)


def _get_employee_sites(username: str) -> list[str]:
    return get_employee_sites(
        username=username,
        session_workplace_id_func=_session_workplace_id,
        workplace_ids_for_read_func=_workplace_ids_for_read,
        db_migration_mode=DB_MIGRATION_MODE,
        employee_model=Employee,
        employees_sheet_obj=employees_sheet,
    )

def _get_employee_site(username: str) -> str:
    return get_employee_site(
        username=username,
        get_employee_sites_func=_get_employee_sites,
    )


def _get_active_locations() -> list[dict]:
    return get_active_locations(
        session_workplace_id_func=_session_workplace_id,
        workplace_ids_for_read_func=_workplace_ids_for_read,
        db_migration_mode=DB_MIGRATION_MODE,
        location_model=Location,
        safe_float_func=safe_float,
        locations_sheet_obj=locations_sheet,
    )

def _get_site_config(site_name: str):
    return get_site_config(
        site_name=site_name,
        get_active_locations_func=_get_active_locations,
    )


def _sanitize_clock_geo(lat_v, lon_v, acc_v):
    return sanitize_clock_geo(
        lat_v=lat_v,
        lon_v=lon_v,
        acc_v=acc_v,
        max_clock_location_accuracy_m=MAX_CLOCK_LOCATION_ACCURACY_M,
    )


def _validate_recent_clock_capture(captured_at_raw: str, now_dt: datetime):
    return validate_recent_clock_capture(
        captured_at_raw=captured_at_raw,
        now_dt=now_dt,
        max_clock_location_age_s=MAX_CLOCK_LOCATION_AGE_S,
    )


def _validate_user_location(username: str, lat: float | None, lon: float | None, acc_m: float | None = None) -> tuple[bool, dict, float]:
    return validate_user_location(
        username=username,
        lat=lat,
        lon=lon,
        acc_m=acc_m,
        get_employee_sites_func=_get_employee_sites,
        get_active_locations_func=_get_active_locations,
        get_site_config_func=_get_site_config,
        haversine_m_func=_haversine_m,
        max_clock_location_accuracy_m=MAX_CLOCK_LOCATION_ACCURACY_M,
    )

def initials(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return "?"
    parts = [p for p in s.replace("_", " ").replace("-", " ").split(" ") if p]
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


def money(x: float) -> str:
    try:
        return f"{float(x):.2f}"
    except Exception:
        return "0.00"


def fmt_hours(x) -> str:
    try:
        n = _round_to_half_hour(float(x or 0))
        return f"{n:.1f}".rstrip("0").rstrip(".")
    except Exception:
        return ""


def role_label(role: str) -> str:
    r = (role or "").strip().lower()
    if r == "master_admin":
        return "MASTER ADMIN"
    if r == "admin":
        return "ADMIN"
    if r == "manager":
        return "MANAGER"
    return r.upper() if r else ""


def _get_employee_db_row(username: str, workplace_id: str | None = None):
    target_user = (username or "").strip()
    target_wp = (workplace_id or _session_workplace_id() or "default").strip() or "default"
    if not target_user or not DB_MIGRATION_MODE:
        return None

    allowed_wps = _workplace_ids_for_read(target_wp)
    candidates = Employee.query.filter(
        and_(
            or_(Employee.username == target_user, Employee.email == target_user),
            or_(
                Employee.workplace_id.in_(allowed_wps),
                and_(Employee.workplace_id.is_(None), Employee.workplace.in_(allowed_wps)),
                Employee.workplace.in_(allowed_wps),
            ),
        )
    ).all()
    if not candidates:
        return None

    def _score(rec):
        row_wp = str(getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default")
        exact = 1 if row_wp == target_wp else 0
        return (exact, getattr(rec, "id", 0))

    return sorted(candidates, key=_score, reverse=True)[0]


def _ensure_employee_security_headers():
    if DB_MIGRATION_MODE or not employees_sheet:
        return
    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return
        headers = vals[0]
        missing = [h for h in ["ActiveSessionToken"] if h not in headers]
        if not missing:
            return
        new_headers = headers + missing
        end_col = gspread.utils.rowcol_to_a1(1, len(new_headers)).replace("1", "")
        employees_sheet.update(f"A1:{end_col}1", [new_headers])
    except Exception:
        return


def _sheet_employee_row_info(username: str, workplace_id: str | None = None):
    _ensure_employee_security_headers()
    target_user = (username or "").strip()
    target_wp = (workplace_id or _session_workplace_id() or "default").strip() or "default"
    vals = employees_sheet.get_all_values() if employees_sheet else []
    if not vals:
        return None, None, None, None
    headers = vals[0]
    if "Username" not in headers:
        return vals, headers, None, None
    ucol = headers.index("Username")
    wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
    tok_col = headers.index("ActiveSessionToken") if "ActiveSessionToken" in headers else None
    info = {"ucol": ucol, "wp_col": wp_col, "tok_col": tok_col}
    for i in range(1, len(vals)):
        row = vals[i]
        row_user = (row[ucol] if len(row) > ucol else "").strip()
        row_wp = ((row[wp_col] if (wp_col is not None and len(row) > wp_col) else "").strip() or "default")
        if row_user == target_user and row_wp == target_wp:
            return vals, headers, i + 1, info
    return vals, headers, None, info


def _issue_active_session_token(username: str, workplace_id: str | None = None):
    target_user = (username or "").strip()
    target_wp = (workplace_id or _session_workplace_id() or "default").strip() or "default"
    token = secrets.token_urlsafe(32)

    if DB_MIGRATION_MODE:
        rec = _get_employee_db_row(target_user, target_wp)
        if not rec:
            return None
        try:
            rec.active_session_token = token
            rec.workplace = target_wp
            rec.workplace_id = target_wp
            db.session.commit()
            return token
        except Exception:
            db.session.rollback()
            return None

    vals, headers, rownum, info = _sheet_employee_row_info(target_user, target_wp)
    if not rownum or not info or info.get("tok_col") is None:
        return None
    try:
        employees_sheet.update_cell(rownum, info["tok_col"] + 1, token)
        return token
    except Exception:
        return None


def _clear_active_session_token(username: str, workplace_id: str | None = None, expected_token: str | None = None):
    target_user = (username or "").strip()
    target_wp = (workplace_id or _session_workplace_id() or "default").strip() or "default"

    if not target_user:
        return False

    if DB_MIGRATION_MODE:
        rec = _get_employee_db_row(target_user, target_wp)
        if not rec:
            return False
        current = str(getattr(rec, "active_session_token", "") or "")
        if expected_token and current and current != expected_token:
            return False
        try:
            rec.active_session_token = None
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False

    vals, headers, rownum, info = _sheet_employee_row_info(target_user, target_wp)
    if not rownum or not info or info.get("tok_col") is None:
        return False
    current = ""
    if vals and len(vals) >= rownum:
        row = vals[rownum - 1]
        tok_col = info["tok_col"]
        current = (row[tok_col] if len(row) > tok_col else "").strip()
    if expected_token and current and current != expected_token:
        return False
    try:
        employees_sheet.update_cell(rownum, info["tok_col"] + 1, "")
        return True
    except Exception:
        return False


def _logout_to_login(login_notice: str = ""):
    session.clear()
    if login_notice:
        session["_login_notice"] = login_notice
    return redirect(url_for("login"))


def _validate_active_session():
    username = (session.get("username") or "").strip()
    if not username:
        return False, ""

    workplace_id = _session_workplace_id()
    session_token = str(session.get("active_session_token") or "")
    if not session_token:
        return False, "Your session has expired. Please log in again."

    if DB_MIGRATION_MODE:
        rec = _get_employee_db_row(username, workplace_id)
        if not rec:
            return False, "Your account is no longer available. Please log in again."
        active_raw = str(getattr(rec, "active", "TRUE") or "TRUE").strip().lower()
        if active_raw in ("false", "0", "no", "n", "off"):
            return False, "Your account is inactive. Please log in again."
        db_token = str(getattr(rec, "active_session_token", "") or "")
        if not db_token or db_token != session_token:
            return False, "Your account was signed in on another device. Please log in again."
        return True, ""

    vals, headers, rownum, info = _sheet_employee_row_info(username, workplace_id)
    if not rownum:
        return False, "Your account is no longer available. Please log in again."

    row = vals[rownum - 1] if vals and len(vals) >= rownum else []
    active_col = headers.index("Active") if headers and "Active" in headers else None
    active_raw = ((row[active_col] if active_col is not None and len(
        row) > active_col else "TRUE") or "TRUE").strip().lower()
    if active_raw in ("false", "0", "no", "n", "off"):
        return False, "Your account is inactive. Please log in again."

    tok_col = info.get("tok_col") if info else None
    sheet_token = ((row[tok_col] if tok_col is not None and len(row) > tok_col else "") or "").strip()
    if not sheet_token or sheet_token != session_token:
        return False, "Your account was signed in on another device. Please log in again."

    return True, ""


def require_login():
    if "username" not in session:
        return redirect(url_for("login"))

    ok, login_notice = _validate_active_session()
    if not ok:
        return _logout_to_login(login_notice)

    return None


def require_admin():
    gate = require_login()
    if gate:
        return gate
    if session.get("role") not in ("admin", "master_admin"):
        return redirect(url_for("home"))
    return None


def require_master_admin():
    gate = require_login()
    if gate:
        return gate
    if session.get("role") != "master_admin":
        return redirect(url_for("home"))
    return None


def require_sensitive_tools_admin():
    gate = require_master_admin()
    if gate:
        return gate
    return None


def require_destructive_admin_post(action_name: str):
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    require_csrf()
    confirm = (request.form.get("confirm") or "").strip()
    if confirm != DESTRUCTIVE_ADMIN_CONFIRM_VALUE:
        return {
            "status": "error",
            "message": f"Confirmation required. Submit the POST form field confirm={DESTRUCTIVE_ADMIN_CONFIRM_VALUE!r}.",
            "action": action_name,
        }, 400
    return None


def normalized_clock_in_time(now_dt: datetime, early_access: bool) -> str:
    if (not early_access) and (now_dt.time() < CLOCKIN_EARLIEST):
        return CLOCKIN_EARLIEST.strftime("%H:%M:%S")
    return now_dt.strftime("%H:%M:%S")


def has_any_row_today(rows, username: str, today_str: str) -> bool:
    u = (username or "").strip()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    for r in rows[1:]:
        if len(r) <= COL_DATE or len(r) <= COL_USER:
            continue

        row_user = (r[COL_USER] or "").strip()
        if row_user != u:
            continue

        # Prefer WorkHours row workplace if the column exists
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            # Backward compat (older sheets)
            if not user_in_same_workplace(row_user):
                continue

        if (r[COL_DATE] or "").strip() == today_str:
            return True

    return False


def find_open_shift(rows, username: str):

    u = (username or "").strip()

    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    for i in range(len(rows) - 1, 0, -1):
        r = rows[i]
        if len(r) <= COL_OUT:
            continue

        row_user = (r[COL_USER] or "").strip()
        if row_user != u:
            continue

        # Prefer WorkHours row workplace if the column exists
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            # Backward-compat fallback (older sheets)
            if not user_in_same_workplace(row_user):
                continue

        if (r[COL_OUT] or "").strip() == "":
            return i, (r[COL_DATE] or "").strip(), (r[COL_IN] or "").strip()

    return None


def get_sheet_headers(sheet):
    vals = sheet.get_all_values()
    return vals[0] if vals else []


def _find_workhours_row_by_user_date(vals, username: str, date_str: str):
    """Return the 1-based row number in WorkHours matching (Username, Date)."""
    if not vals or len(vals) < 2:
        return None
    headers = vals[0]
    wp_idx = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))
    try:
        uidx = headers.index("Username")
    except Exception:
        uidx = COL_USER
    try:
        didx = headers.index("Date")
    except Exception:
        didx = COL_DATE

    u = (username or "").strip()
    d = (date_str or "").strip()
    for i in range(1, len(vals)):
        r = vals[i]
        if len(r) <= max(uidx, didx):
            continue
        row_u = (r[uidx] or "").strip()
        row_d = (r[didx] or "").strip()
        row_wp = ((r[wp_idx] if (wp_idx is not None and wp_idx < len(r)) else "").strip() or "default")

        if row_u == u and row_d == d and row_wp == current_wp:
            return i + 1
    return None


def find_row_by_username(sheet, username: str):
    vals = sheet.get_all_values()
    if not vals:
        return None

    headers = vals[0]
    if "Username" not in headers:
        return None

    ucol = headers.index("Username")
    wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))
    target = (username or "").strip()

    for i in range(1, len(vals)):
        row = vals[i]
        row_user = (row[ucol] if len(row) > ucol else "").strip()
        if row_user != target:
            continue

        # If the sheet has Workplace_ID, require it to match the session workplace
        if wp_col is not None:
            row_wp = (row[wp_col] if len(row) > wp_col else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

        return i + 1  # gspread row number (1-based)

    return None


def get_employee_display_name(username: str) -> str:
    return get_employee_display_name_data(
        username=username,
        session_workplace_id=_session_workplace_id(),
        workplace_ids_for_read=_workplace_ids_for_read,
        db_migration_mode=DB_MIGRATION_MODE,
        employee_model=Employee,
        employees_sheet=employees_sheet,
    )


def set_employee_field(username: str, field: str, value: str):
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    if DB_MIGRATION_MODE:
        try:
            db_row = _employee_query_for_write(username, current_wp).first()
            if not db_row:
                return False

            if field == "Site" and hasattr(db_row, "site"):
                db_row.site = value
            elif field == "Site2" and hasattr(db_row, "site2"):
                db_row.site2 = value
            elif field == "Role" and hasattr(db_row, "role"):
                db_row.role = value
            elif field == "Rate" and hasattr(db_row, "rate"):
                db_row.rate = Decimal(str(value)) if str(value).strip() != "" else None
            elif field == "EarlyAccess" and hasattr(db_row, "early_access"):
                db_row.early_access = value
            elif field == "Active" and hasattr(db_row, "active"):
                db_row.active = value
                if value == "FALSE" and hasattr(db_row, "active_session_token"):
                    db_row.active_session_token = None
            elif field == "Workplace_ID":
                if hasattr(db_row, "workplace_id"):
                    db_row.workplace_id = value
                if hasattr(db_row, "workplace"):
                    db_row.workplace = value
            elif field == "OnboardingCompleted" and hasattr(db_row, "onboarding_completed"):
                db_row.onboarding_completed = value
            else:
                return False

            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False

    vals = employees_sheet.get_all_values()
    if not vals:
        return False
    headers = vals[0]
    if "Username" not in headers or field not in headers:
        return False

    ucol = headers.index("Username")
    wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
    fcol = headers.index(field) + 1
    rownum = None

    for i in range(1, len(vals)):
        row = vals[i]
        row_user = (row[ucol] if len(row) > ucol else "").strip()
        row_wp = ((row[wp_col] if (wp_col is not None and len(row) > wp_col) else "").strip() or "default")
        if row_user == username and row_wp == current_wp:
            rownum = i + 1
            break

    if not rownum:
        return False

    employees_sheet.update_cell(rownum, fcol, value)
    return True


def set_employee_first_last(username: str, first: str, last: str):
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    if DB_MIGRATION_MODE:
        try:
            db_row = Employee.query.filter_by(username=username, workplace_id=current_wp).first()
            if not db_row:
                db_row = Employee.query.filter_by(email=username, workplace_id=current_wp).first()
            if not db_row:
                return
            db_row.first_name = first or ""
            db_row.last_name = last or ""
            full_name = (" ".join([first or "", last or ""])).strip()
            if full_name:
                db_row.name = full_name
            db_row.workplace = current_wp
            db_row.workplace_id = current_wp
            db.session.commit()
        except Exception:
            db.session.rollback()
        return

    vals = employees_sheet.get_all_values()
    if not vals:
        return
    headers = vals[0]
    if "Username" not in headers:
        return

    ucol = headers.index("Username")
    wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
    fn_col = headers.index("FirstName") + 1 if "FirstName" in headers else None
    ln_col = headers.index("LastName") + 1 if "LastName" in headers else None
    if not fn_col and not ln_col:
        return

    rownum = None
    for i in range(1, len(vals)):
        row = vals[i]
        row_user = row[ucol].strip() if len(row) > ucol else ""
        row_wp = (row[wp_col].strip() if (wp_col is not None and len(row) > wp_col) else "") or "default"
        if row_user == username and row_wp == current_wp:
            rownum = i + 1
            break

    if rownum:
        if fn_col:
            employees_sheet.update_cell(rownum, fn_col, first or "")
        if ln_col:
            employees_sheet.update_cell(rownum, ln_col, last or "")


def _allowed_assignable_roles_for_actor(actor_role: str) -> set[str]:
    actor = (actor_role or "").strip().lower()

    # These are only DEFAULT SUGGESTIONS in the UI, not a hard limit.
    default_worker_roles = {
        "employee",
        "bricklayer",
        "fixer",
        "labourer",
        "supervisor/foreman",
        "manager",
    }

    if actor == "master_admin":
        return default_worker_roles | {"admin"}
    if actor == "admin":
        return default_worker_roles
    return {"employee"}


def _sanitize_requested_role(raw_role: str, actor_role: str) -> str | None:
    role = (raw_role or "").strip()
    if not role:
        return None

    role_l = role.lower()
    actor = (actor_role or "").strip().lower()

    # Never allow creating master_admin from this screen
    if role_l == "master_admin":
        return None

    # Only master_admin can create admin
    if role_l == "admin":
        return "admin" if actor == "master_admin" else None

    # Any other non-empty role is allowed as typed
    return role


def update_employee_password(username: str, new_password: str, workplace_id: str | None = None) -> bool:
    hashed = generate_password_hash(new_password)
    current_wp = (workplace_id or _session_workplace_id() or "default").strip() or "default"
    target_user = (username or "").strip()

    if not target_user:
        return False

    if DB_MIGRATION_MODE:
        try:
            db_row = _employee_query_for_write(target_user, current_wp).first()
            if not db_row:
                return False
            db_row.password = hashed
            db_row.active_session_token = None
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False

    vals = employees_sheet.get_all_values() if employees_sheet else []
    if not vals:
        return False
    headers = vals[0]
    if "Username" not in headers or "Password" not in headers:
        return False
    ucol = headers.index("Username")
    wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
    pcol = headers.index("Password") + 1
    tok_col = headers.index("ActiveSessionToken") + 1 if "ActiveSessionToken" in headers else None

    for i in range(1, len(vals)):
        row = vals[i]
        row_user = row[ucol].strip() if len(row) > ucol else ""
        row_wp = (row[wp_col].strip() if (wp_col is not None and len(row) > wp_col) else "") or "default"
        if row_user == target_user and row_wp == current_wp:
            employees_sheet.update_cell(i + 1, pcol, hashed)
            if tok_col:
                employees_sheet.update_cell(i + 1, tok_col, "")
            return True
    return False


@routes.post("/admin/employees/reset-password")
def admin_employee_reset_password():
    gate = require_master_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("username") or "").strip()
    new_password = (request.form.get("new_password") or "").strip()

    if not username or len(new_password) < 8:
        session["_pwreset_ok"] = False
        session["_pwreset_msg"] = "Enter a valid username and a password with at least 8 characters."
        session.pop("_pwreset_user", None)
        session.pop("_pwreset_password", None)
        return redirect("/admin/employees")

    ok = update_employee_password(username, new_password, workplace_id=_session_workplace_id())

    actor = session.get("username", "master_admin")
    if ok:
        log_audit("RESET_PASSWORD", actor=actor, username=username, date_str="", details="current workplace")
        session["_pwreset_ok"] = True
        session["_pwreset_msg"] = f"Password reset successfully for {username}."
        session["_pwreset_user"] = username
        session.pop("_pwreset_password", None)
    else:
        log_audit("RESET_PASSWORD_FAILED", actor=actor, username=username, date_str="", details="current workplace")
        session["_pwreset_ok"] = False
        session["_pwreset_msg"] = f"Could not reset password for {username}."
        session.pop("_pwreset_user", None)
        session.pop("_pwreset_password", None)

    return redirect("/admin/employees")


from sqlalchemy import or_, and_


@routes.post("/admin/employees/clear-history")
def admin_clear_employee_history():
    gate = require_master_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("username") or "").strip()
    wp = (_session_workplace_id() or "default").strip() or "default"

    if not username:
        session["_emp_msg"] = "Choose an employee first."
        session["_emp_ok"] = False
        return redirect("/admin/employees")

    try:
        workhours_deleted = _workhour_query_for_user(username, wp).delete(synchronize_session=False)
        payroll_deleted = _payroll_query_for_user(username, wp).delete(synchronize_session=False)

        db.session.commit()

        session["_emp_msg"] = (
            f"Clear history ran for {username}. "
            f"Deleted workhours={int(workhours_deleted or 0)}, "
            f"payroll={int(payroll_deleted or 0)}."
        )
        session["_emp_ok"] = True

    except Exception as e:
        db.session.rollback()
        session["_emp_msg"] = f"Clear history failed: {str(e)}"
        session["_emp_ok"] = False

    return redirect("/admin/employees")


@routes.post("/admin/employees/delete")
def admin_delete_employee():
    gate = require_master_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("username") or "").strip()
    wp = (_session_workplace_id() or "default").strip() or "default"

    if not username:
        session["_emp_msg"] = "Choose an employee first."
        session["_emp_ok"] = False
        return redirect("/admin/employees")

    if username == session.get("username"):
        session["_emp_msg"] = "You cannot delete your own account."
        session["_emp_ok"] = False
        return redirect("/admin/employees")
    target_employee = _employee_query_for_write(username, wp).first()

    if target_employee and (target_employee.role or "").strip().lower() == "master_admin":
        session["_emp_msg"] = "Master admin account cannot be deleted."
        session["_emp_ok"] = False
        return redirect("/admin/employees")

    try:
        workhours_deleted = _workhour_query_for_user(username, wp).delete(synchronize_session=False)
        payroll_deleted = _payroll_query_for_user(username, wp).delete(synchronize_session=False)
        onboarding_deleted = _onboarding_query_for_user(username, wp).delete(synchronize_session=False)
        employees_deleted = _employee_query_for_write(username, wp).delete(synchronize_session=False)

        db.session.commit()

        session["_emp_msg"] = (
            f"Delete ran for {username}. "
            f"Deleted employees={int(employees_deleted or 0)}, "
            f"workhours={int(workhours_deleted or 0)}, "
            f"payroll={int(payroll_deleted or 0)}, "
            f"onboarding={int(onboarding_deleted or 0)}."
        )
        session["_emp_ok"] = True

    except Exception as e:
        db.session.rollback()
        session["_emp_msg"] = f"Delete failed: {str(e)}"
        session["_emp_ok"] = False

    return redirect("/admin/employees")


@routes.route("/admin/migrate-workplace-id", methods=["GET", "POST"])
def admin_migrate_workplace_id():
    gate = require_master_admin()
    if gate:
        return gate

    csrf = get_csrf()
    ok = None
    msg = ""
    report = None

    if request.method == "POST":
        require_csrf()
        confirm_text = (request.form.get("confirm_text") or "").strip()

        if confirm_text != WORKPLACE_ID_MIGRATION_CONFIRM:
            ok = False
            msg = f'Type "{WORKPLACE_ID_MIGRATION_CONFIRM}" to confirm the migration.'
        else:
            report = _run_workplace_id_migration(
                old_wp=WORKPLACE_ID_MIGRATION_OLD,
                new_wp=WORKPLACE_ID_MIGRATION_NEW,
            )
            ok = bool(report.get("ok"))
            if ok:
                session["workplace_id"] = WORKPLACE_ID_MIGRATION_NEW

            actor = session.get("username", "master_admin")
            try:
                log_audit(
                    "WORKPLACE_ID_MIGRATION",
                    actor=actor,
                    username="",
                    date_str="",
                    details=f"{WORKPLACE_ID_MIGRATION_OLD} -> {WORKPLACE_ID_MIGRATION_NEW}",
                )
            except Exception:
                pass

            if ok:
                msg = (
                    f"Migration completed: "
                    f"{WORKPLACE_ID_MIGRATION_OLD} → {WORKPLACE_ID_MIGRATION_NEW}"
                )
            else:
                msg = "Migration completed with errors. Review the report below."

    sheet_rows = []
    if report:
        for label, data in (report.get("sheets") or {}).items():
            updated = int((data or {}).get("updated") or 0)
            err = str((data or {}).get("error") or "").strip()
            sheet_rows.append(f"""
              <tr>
                <td>{escape(label)}</td>
                <td class="num">{updated}</td>
                <td>{escape(err)}</td>
              </tr>
            """)

    db_rows = []
    if report:
        for label, data in (report.get("db") or {}).items():
            if isinstance(data, dict):
                rows_updated = int(data.get("rows_updated") or 0)
                field_updates = int(data.get("field_updates") or 0)
                err = str(data.get("error") or "").strip()
            else:
                rows_updated = 0
                field_updates = 0
                err = str(data or "").strip()

            db_rows.append(f"""
              <tr>
                <td>{escape(label)}</td>
                <td class="num">{rows_updated}</td>
                <td class="num">{field_updates}</td>
                <td>{escape(err)}</td>
              </tr>
            """)

    report_card = ""
    if report:
        report_card = f"""
          <div class="card" style="padding:12px; margin-top:12px;">
            <h2>Migration Report</h2>
            <div class="sub" style="margin-top:4px;">
              Old workplace ID: <strong>{escape(report.get("old_workplace_id", ""))}</strong><br>
              New workplace ID: <strong>{escape(report.get("new_workplace_id", ""))}</strong>
            </div>

            <div class="tablewrap" style="margin-top:12px;">
              <table style="min-width:720px;">
                <thead>
                  <tr>
                    <th>Sheet</th>
                    <th class="num">Updated</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(sheet_rows) or "<tr><td colspan='3' class='sub'>No sheet updates recorded.</td></tr>"}
                </tbody>
              </table>
            </div>

            <div class="tablewrap" style="margin-top:12px;">
              <table style="min-width:840px;">
                <thead>
                  <tr>
                    <th>DB store</th>
                    <th class="num">Rows updated</th>
                    <th class="num">Field updates</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(db_rows) or "<tr><td colspan='4' class='sub'>No DB updates recorded.</td></tr>"}
                </tbody>
              </table>
            </div>
          </div>
        """

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Workplace ID Migration</h1>
          <p class="sub">One-time migration from <strong>{escape(WORKPLACE_ID_MIGRATION_OLD)}</strong> to <strong>{escape(WORKPLACE_ID_MIGRATION_NEW)}</strong></p>
        </div>
        <div class="badge admin">MASTER ADMIN</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and ok is False) else ""}

      <div class="card" style="padding:12px;">
        <h2>Run Migration</h2>
        <p class="sub">This updates workplace ID values across configured sheets and database tables.</p>

        <form method="POST" style="margin-top:12px;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">

          <label class="sub">Old workplace ID</label>
          <input class="input" value="{escape(WORKPLACE_ID_MIGRATION_OLD)}" readonly>

          <label class="sub" style="margin-top:12px;">New workplace ID</label>
          <input class="input" value="{escape(WORKPLACE_ID_MIGRATION_NEW)}" readonly>

          <label class="sub" style="margin-top:12px;">Type {escape(WORKPLACE_ID_MIGRATION_CONFIRM)} to confirm</label>
          <input class="input" name="confirm_text" autocomplete="off" required>

          <button class="btnSoft" type="submit" style="margin-top:12px; background:#7f1d1d; border-color:#7f1d1d;"
                  onclick="return confirm('Run workplace ID migration now? This should only be done once.');">
            Run migration
          </button>
        </form>
      </div>

      {report_card}
    """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )


def get_reset_user_options_html() -> str:
    current_wp = (_session_workplace_id() or "default").strip() or "default"
    options = []
    seen = set()

    try:
        records = get_employees_compat()
        for rec in records:
            username = str(rec.get("Username") or "").strip()
            if not username:
                continue

            workplace_id = str(rec.get("Workplace_ID") or "default").strip() or "default"
            role = str(rec.get("Role") or "").strip()
            role_key = role.lower()
            first_name = str(rec.get("FirstName") or "").strip()
            last_name = str(rec.get("LastName") or "").strip()
            display_name = (first_name + " " + last_name).strip() or username

            include = (workplace_id == current_wp) or (role_key in ("admin", "master_admin"))
            if not include:
                continue

            key = (workplace_id, username)
            if key in seen:
                continue
            seen.add(key)

            packed = f"{workplace_id}||{username}"
            label = f"{display_name} ({username}) — {role or 'employee'} — {workplace_id}"
            options.append((
                0 if workplace_id == current_wp else 1,
                workplace_id.lower(),
                label.lower(),
                f"<option value='{escape(packed)}'>{escape(label)}</option>",
            ))
    except Exception:
        return "<option value='' selected disabled>Select user</option>"

    options.sort(key=lambda item: (item[0], item[1], item[2]))
    return "<option value='' selected disabled>Select user</option>" + "".join(item[3] for item in options)


def _password_is_hashed(stored: str) -> bool:
    stored = (stored or "").strip()
    return stored.startswith("pbkdf2:") or stored.startswith("scrypt:")


def _normalize_password_hash_value(raw_password: str) -> str:
    raw_password = (raw_password or "").strip()
    if not raw_password:
        return ""
    if _password_is_hashed(raw_password):
        return raw_password
    return generate_password_hash(raw_password)


def _ensure_password_hash_for_user(username: str, stored: str, workplace_id: str | None = None) -> str:
    stored = (stored or "").strip()
    if not stored:
        return ""
    if _password_is_hashed(stored):
        return stored

    try:
        update_employee_password(username, stored, workplace_id=workplace_id)
    except Exception:
        pass

    return generate_password_hash(stored)


def is_password_valid(stored: str, provided: str) -> bool:
    stored = (stored or "").strip()
    return bool(stored) and _password_is_hashed(stored) and check_password_hash(stored, provided)


def migrate_password_if_plain(username: str, stored: str, provided: str, workplace_id: str | None = None):
    stored = (stored or "").strip()
    if stored and not _password_is_hashed(stored):
        _ensure_password_hash_for_user(username, stored, workplace_id=workplace_id)


def _ensure_onboarding_workplace_header():
    """Ensure legacy Onboarding sheet has the expected headers, including Workplace_ID."""
    if not onboarding_sheet:
        return

    required = [
        "Username", "Workplace_ID", "FirstName", "LastName", "BirthDate", "PhoneCountryCode", "PhoneNumber", "Email",
        "StreetAddress", "City", "Postcode", "EmergencyContactName", "EmergencyContactPhoneCountryCode",
        "EmergencyContactPhoneNumber", "MedicalCondition", "MedicalDetails", "Position", "CSCSNumber",
        "CSCSExpiryDate", "EmploymentType", "RightToWorkUK", "NationalInsurance", "UTR", "StartDate",
        "BankAccountNumber", "SortCode", "AccountHolderName", "CompanyTradingName", "CompanyRegistrationNo",
        "DateOfContract", "SiteAddress", "PassportOrBirthCertLink", "CSCSFrontBackLink", "PublicLiabilityLink",
        "ShareCodeLink", "ContractAccepted", "SignatureName", "SignatureDateTime", "SubmittedAt",
    ]

    try:
        vals = onboarding_sheet.get_all_values()
        if not vals:
            onboarding_sheet.append_row(required)
            return

        headers = vals[0]
        if not headers or "Username" not in headers:
            onboarding_sheet.insert_row(required, 1)
            return

        if headers[:len(required)] != required:
            new_headers = required + [h for h in headers if h not in required]
            end_col = gspread.utils.rowcol_to_a1(1, len(new_headers)).replace("1", "")
            onboarding_sheet.update(f"A1:{end_col}1", [new_headers])
    except Exception:
        return


def update_or_append_onboarding(username: str, data: dict):
    current_wp = _session_workplace_id()

    # DB-first path
    if DB_MIGRATION_MODE:
        try:
            rec = OnboardingRecord.query.filter_by(
                username=username,
                workplace_id=current_wp
            ).first()

            if not rec:
                rec = OnboardingRecord(username=username, workplace_id=current_wp)
                db.session.add(rec)

            mapping = {
                "first_name": "FirstName",
                "last_name": "LastName",
                "birth_date": "BirthDate",
                "phone_country_code": "PhoneCountryCode",
                "phone": "PhoneNumber",
                "email": "Email",
                "street_address": "StreetAddress",
                "city": "City",
                "postcode": "Postcode",
                "emergency_contact_name": "EmergencyContactName",
                "emergency_contact_phone_country_code": "EmergencyContactPhoneCountryCode",
                "emergency_contact_phone": "EmergencyContactPhoneNumber",
                "medical_condition": "MedicalCondition",
                "medical_details": "MedicalDetails",
                "position": "Position",
                "cscs_number": "CSCSNumber",
                "cscs_expiry_date": "CSCSExpiryDate",
                "employment_type": "EmploymentType",
                "right_to_work_uk": "RightToWorkUK",
                "national_insurance": "NationalInsurance",
                "utr": "UTR",
                "start_date": "StartDate",
                "bank_account_number": "BankAccountNumber",
                "sort_code": "SortCode",
                "account_holder_name": "AccountHolderName",
                "company_trading_name": "CompanyTradingName",
                "company_registration_no": "CompanyRegistrationNo",
                "date_of_contract": "DateOfContract",
                "site_address": "SiteAddress",
                "passport_or_birth_cert_link": "PassportOrBirthCertLink",
                "cscs_front_back_link": "CSCSFrontBackLink",
                "public_liability_link": "PublicLiabilityLink",
                "share_code_link": "ShareCodeLink",
                "contract_accepted": "ContractAccepted",
                "signature_name": "SignatureName",
                "signature_datetime": "SignatureDateTime",
                "submitted_at": "SubmittedAt",
                "address": "StreetAddress",
                "emergency_contact_phone_number": "EmergencyContactPhoneNumber",
            }

            for attr, key in mapping.items():
                if hasattr(rec, attr):
                    setattr(rec, attr, str(data.get(key, "")))

            if hasattr(rec, "workplace_id"):
                rec.workplace_id = current_wp

            db.session.commit()
            return
        except Exception:
            db.session.rollback()
            raise

    # Legacy sheet fallback only when DB mode is off
    _ensure_onboarding_workplace_header()
    headers = get_sheet_headers(onboarding_sheet)
    if not headers or "Username" not in headers:
        raise RuntimeError("Onboarding storage is not initialized.")

    vals = onboarding_sheet.get_all_values()
    if not vals:
        raise RuntimeError("Onboarding storage is empty (missing headers).")

    ucol = headers.index("Username")
    wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None

    rownum = None
    for i in range(1, len(vals)):
        row = vals[i]
        row_u = (row[ucol] if ucol < len(row) else "").strip()
        if row_u != (username or "").strip():
            continue

        if wp_col is not None:
            row_wp = (row[wp_col] if wp_col < len(row) else "").strip() or current_wp
            if row_wp != current_wp:
                continue

        rownum = i + 1
        break

    row_values = []
    for h in headers:
        if h == "Username":
            row_values.append(username)
        elif h == "Workplace_ID":
            row_values.append(current_wp)
        else:
            row_values.append(str(data.get(h, "")))

    end_col = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
    if rownum:
        onboarding_sheet.update(f"A{rownum}:{end_col}{rownum}", [row_values])
    else:
        onboarding_sheet.append_row(row_values)


def get_onboarding_record(username: str):
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    if DB_MIGRATION_MODE:
        try:
            rec = OnboardingRecord.query.filter_by(username=username, workplace_id=current_wp).first()
            if rec:
                def gv(attr):
                    return "" if not hasattr(rec, attr) or getattr(rec, attr) is None else str(getattr(rec, attr))

                return {
                    "Username": username,
                    "Workplace_ID": current_wp,
                    "FirstName": gv("first_name"),
                    "LastName": gv("last_name"),
                    "BirthDate": gv("birth_date"),
                    "PhoneCountryCode": gv("phone_country_code"),
                    "PhoneNumber": gv("phone"),
                    "Email": gv("email"),
                    "StreetAddress": gv("street_address") or gv("address"),
                    "City": gv("city"),
                    "Postcode": gv("postcode"),
                    "EmergencyContactName": gv("emergency_contact_name"),
                    "EmergencyContactPhoneCountryCode": gv("emergency_contact_phone_country_code"),
                    "EmergencyContactPhoneNumber": gv("emergency_contact_phone"),
                    "MedicalCondition": gv("medical_condition"),
                    "MedicalDetails": gv("medical_details"),
                    "Position": gv("position"),
                    "CSCSNumber": gv("cscs_number"),
                    "CSCSExpiryDate": gv("cscs_expiry_date"),
                    "EmploymentType": gv("employment_type"),
                    "RightToWorkUK": gv("right_to_work_uk"),
                    "NationalInsurance": gv("national_insurance"),
                    "UTR": gv("utr"),
                    "StartDate": gv("start_date"),
                    "BankAccountNumber": gv("bank_account_number"),
                    "SortCode": gv("sort_code"),
                    "AccountHolderName": gv("account_holder_name"),
                    "CompanyTradingName": gv("company_trading_name"),
                    "CompanyRegistrationNo": gv("company_registration_no"),
                    "DateOfContract": gv("date_of_contract"),
                    "SiteAddress": gv("site_address"),
                    "PassportOrBirthCertLink": gv("passport_or_birth_cert_link"),
                    "CSCSFrontBackLink": gv("cscs_front_back_link"),
                    "PublicLiabilityLink": gv("public_liability_link"),
                    "ShareCodeLink": gv("share_code_link"),
                    "ContractAccepted": gv("contract_accepted"),
                    "SignatureName": gv("signature_name"),
                    "SignatureDateTime": gv("signature_datetime"),
                    "SubmittedAt": gv("submitted_at"),
                }
        except Exception:
            pass

    headers = get_sheet_headers(onboarding_sheet)
    vals = onboarding_sheet.get_all_values()
    if not vals or "Username" not in headers:
        return None

    ucol = headers.index("Username")
    wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None

    for i in range(1, len(vals)):
        row = vals[i]
        row_u = (row[ucol] if ucol < len(row) else "").strip()
        if row_u != (username or "").strip():
            continue

        if wp_col is not None:
            row_wp = (row[wp_col] if wp_col < len(row) else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

        rec = {}
        for j, h in enumerate(headers):
            rec[h] = row[j] if j < len(row) else ""
        return rec

    return None


def onboarding_details_block(username: str) -> str:
    rec = get_onboarding_record(username)
    if not rec:
        return "<div class='sub'>No onboarding details saved yet.</div>"

    fields = [
        ("First name", "FirstName"),
        ("Last name", "LastName"),
        ("Phone", "PhoneNumber"),
        ("Email", "Email"),
        ("Emergency contact", "EmergencyContactName"),
        ("Emergency phone", "EmergencyContactPhoneNumber"),
        ("Position", "Position"),
        ("CSCS number", "CSCSNumber"),
        ("CSCS expiry", "CSCSExpiryDate"),
        ("Employment type", "EmploymentType"),
        ("Right to work UK", "RightToWorkUK"),
        ("National Insurance number (NIno)", "NationalInsurance"),
        ("UTR number", "UTR"),
        ("Start date", "StartDate"),
        ("Account holder", "AccountHolderName"),
        ("Company trading name", "CompanyTradingName"),
        ("Company reg no.", "CompanyRegistrationNo"),
        ("Date of contract", "DateOfContract"),
        ("Last saved", "SubmittedAt"),
    ]

    def _masked_value(key: str, raw: str) -> str:
        val = (raw or "").strip()
        if not val:
            return ""
        sensitive_full = {"BirthDate", "StreetAddress", "City", "Postcode", "MedicalCondition", "MedicalDetails",
                          "SiteAddress"}
        sensitive_last4 = {"BankAccountNumber", "SortCode"}
        if key in sensitive_full:
            return "••••"
        if key in sensitive_last4:
            return ("••••" + val[-4:]) if len(val) > 4 else "••••"
        return val

    rows = []
    for label, key in fields:
        val = _masked_value(key, rec.get(key, ""))
        if val:
            rows.append(f"<tr><th style='width:260px;'>{escape(label)}</th><td>{escape(val)}</td></tr>")

    if not rows:
        return "<div class='sub'>Onboarding record exists, but no details were found.</div>"

    return f"""
      <div class="tablewrap" style="margin-top:10px;">
        <table style="min-width:640px;">
          <tbody>
            {''.join(rows)}
          </tbody>
        </table>
      </div>
    """


def get_csrf() -> str:
    tok = session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(24)
        session["csrf"] = tok
    return tok


def require_csrf():
    if request.method == "POST":
        if request.form.get("csrf") != session.get("csrf"):
            abort(400)


# ================= LOGIN RATE LIMIT =================
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 10 * 60
_login_attempts = {}  # ip -> [timestamps]


def _client_ip():
    # ProxyFix has already normalized the trusted upstream address into remote_addr.
    return (request.remote_addr or "").strip() or "unknown"


def _login_rate_limit_check(ip):
    now = time.time()
    window_start = now - LOGIN_WINDOW_SECONDS
    arr = _login_attempts.get(ip, [])
    arr = [t for t in arr if t >= window_start]
    _login_attempts[ip] = arr

    if len(arr) >= LOGIN_MAX_ATTEMPTS:
        retry_after = int(max(0, (arr[0] + LOGIN_WINDOW_SECONDS) - now))
        return False, retry_after
    return True, 0


def _login_rate_limit_hit(ip):
    arr = _login_attempts.get(ip, [])
    arr.append(time.time())
    _login_attempts[ip] = arr


def _login_rate_limit_clear(ip):
    _login_attempts.pop(ip, None)


# ================= ADMIN / SHEET HELPERS =================
AUDIT_HEADERS = ["Timestamp", "Actor", "Action", "Username", "Date", "Details", "Workplace_ID"]
PAYROLL_HEADERS = ["WeekStart", "WeekEnd", "Username", "Gross", "Tax", "Net", "DisplayTax", "DisplayNet", "PaymentMode",
                   "PaidAt", "PaidBy", "Paid",
                   "Workplace_ID"]


def _ensure_audit_headers():
    if not audit_sheet:
        return
    try:
        vals = audit_sheet.get_all_values()
        if not vals:
            audit_sheet.append_row(AUDIT_HEADERS)
            return
        headers = vals[0]
        if headers[:len(AUDIT_HEADERS)] != AUDIT_HEADERS:
            audit_sheet.update(range_name="A1:G1", values=[AUDIT_HEADERS])
    except Exception:
        return


def _legacy_log_audit_before_db_patch(action: str, actor: str = "", username: str = "", date_str: str = "",
                                      details: str = ""):
    """Legacy pre-DB-patch audit logger kept only for reference; runtime uses the later log_audit()."""
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

    if audit_sheet:
        try:
            _ensure_audit_headers()
            audit_sheet.append_row(
                [ts, actor or "", action or "", username or "", date_str or "", details or "", _session_workplace_id()]
            )
        except Exception:
            pass

    if DB_MIGRATION_MODE:
        try:
            db.session.add(
                AuditLog(
                    action=action or "unknown",
                    user_email=(username or actor or ""),
                    created_at=datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()


def _ensure_locations_headers():
    """Ensure Locations sheet has required headers."""
    if not locations_sheet:
        return
    required = ["SiteName", "Lat", "Lon", "RadiusMeters", "Active", "Workplace_ID"]
    try:
        vals = locations_sheet.get_all_values()
        if not vals:
            locations_sheet.append_row(required)
            return
        headers = vals[0]
        if "SiteName" not in headers:
            # treat current as data, insert header at top
            locations_sheet.insert_row(required, 1)
            return
        # ensure at least required columns in correct order (without deleting extras)
        if headers[:len(required)] != required:
            new_headers = required + [h for h in headers if h not in required]
            end_col = gspread.utils.rowcol_to_a1(1, len(new_headers)).replace("1", "")
            locations_sheet.update(f"A1:{end_col}1", [new_headers])
    except Exception:
        return


def _ensure_payroll_headers():
    try:
        vals = get_payroll_rows()
        if not vals:
            payroll_sheet.append_row(PAYROLL_HEADERS)
            return
        headers = vals[0]
        if "WeekStart" not in headers:
            payroll_sheet.insert_row(PAYROLL_HEADERS, 1)
            return
        if headers[:len(PAYROLL_HEADERS)] != PAYROLL_HEADERS:
            new_headers = PAYROLL_HEADERS + [h for h in headers if h not in PAYROLL_HEADERS]
            end_col = gspread.utils.rowcol_to_a1(1, len(new_headers)).replace("1", "")
            payroll_sheet.update(f"A1:{end_col}1", [new_headers])
    except Exception:
        return


def _legacy_append_paid_record_safe_before_db_patch(week_start: str, week_end: str, username: str, gross: float,
                                                    tax: float, net: float,
                                                    paid_by: str):
    """Legacy pre-DB-patch payroll appender kept only for reference; runtime uses the later _append_paid_record_safe()."""
    try:
        _ensure_payroll_headers()
        paid, _ = _is_paid_for_week(week_start, week_end, username)
        if paid:
            return

        paid_at = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        payroll_sheet.append_row(
            [week_start, week_end, username, money(gross), money(tax), money(net), paid_at, paid_by, "",
             _session_workplace_id()]
        )

        if DB_MIGRATION_MODE:
            try:
                wp = _session_workplace_id()
                allowed_wps = set(_workplace_ids_for_read(wp))
                ws_date = datetime.strptime(week_start, "%Y-%m-%d").date()
                we_date = datetime.strptime(week_end, "%Y-%m-%d").date()
                paid_at_dt = datetime.strptime(paid_at, "%Y-%m-%d %H:%M:%S")

                db_row = PayrollReport.query.filter_by(
                    username=username,
                    week_start=ws_date,
                    week_end=we_date,
                    workplace_id=wp,
                ).first()

                if db_row:
                    db_row.gross = Decimal(str(gross))
                    db_row.tax = Decimal(str(tax))
                    db_row.net = Decimal(str(net))
                    db_row.paid_at = paid_at_dt
                    db_row.paid_by = paid_by
                    db_row.paid = "TRUE"
                else:
                    db.session.add(
                        PayrollReport(
                            username=username,
                            week_start=ws_date,
                            week_end=we_date,
                            gross=Decimal(str(gross)),
                            tax=Decimal(str(tax)),
                            net=Decimal(str(net)),
                            paid_at=paid_at_dt,
                            paid_by=paid_by,
                            paid="TRUE",
                            workplace_id=wp,
                        )
                    )

                db.session.commit()
            except Exception:
                db.session.rollback()

        log_audit(
            "MARK_PAID",
            actor=paid_by,
            username=username,
            date_str=f"{week_start}..{week_end}",
            details=f"gross={gross} tax={tax} net={net}",
        )
    except Exception:
        return


def _get_paid_record_for_week(week_start: str, week_end: str, username: str) -> dict:
    try:
        _ensure_payroll_headers()
        vals = get_payroll_rows()
        if not vals or len(vals) < 2:
            return {"paid": False, "paid_at": "", "gross": 0.0, "tax": 0.0, "net": 0.0, "display_tax": 0.0,
                    "display_net": 0.0, "payment_mode": "net"}

        headers = vals[0]

        def idx(name):
            return headers.index(name) if name in headers else None

        i_ws = idx("WeekStart")
        i_we = idx("WeekEnd")
        i_u = idx("Username")
        i_g = idx("Gross")
        i_t = idx("Tax")
        i_n = idx("Net")
        i_dt = idx("DisplayTax")
        i_dn = idx("DisplayNet")
        i_pm = idx("PaymentMode")
        i_pa = idx("PaidAt")
        i_paid = idx("Paid")
        i_wp = idx("Workplace_ID")

        current_wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(current_wp))

        for r in vals[1:]:
            ws = (r[i_ws] if i_ws is not None and i_ws < len(r) else "").strip()
            we = (r[i_we] if i_we is not None and i_we < len(r) else "").strip()
            uu = (r[i_u] if i_u is not None and i_u < len(r) else "").strip()
            wp = ((r[i_wp] if i_wp is not None and i_wp < len(r) else "").strip() or "default")

            if ws != week_start or we != week_end or uu != username or wp not in allowed_wps:
                continue

            paid_at = (r[i_pa] if i_pa is not None and i_pa < len(r) else "").strip()
            paid_flag = (r[i_paid] if i_paid is not None and i_paid < len(r) else "").strip().lower()
            is_paid = bool(paid_at) or paid_flag in {"true", "1", "yes", "paid"}
            if not is_paid:
                continue

            gross = safe_float(r[i_g] if i_g is not None and i_g < len(r) else "0", 0.0)
            tax = safe_float(r[i_t] if i_t is not None and i_t < len(r) else "0", 0.0)
            net = safe_float(r[i_n] if i_n is not None and i_n < len(r) else "0", 0.0)

            display_tax = safe_float(r[i_dt] if i_dt is not None and i_dt < len(r) else "", tax)
            display_net = safe_float(r[i_dn] if i_dn is not None and i_dn < len(r) else "", net)
            payment_mode = (r[i_pm] if i_pm is not None and i_pm < len(r) else "").strip().lower()

            if payment_mode not in {"gross", "net"}:
                payment_mode = "gross" if abs(display_tax) < 0.005 and abs(display_net - gross) < 0.005 else "net"

            return {
                "paid": True,
                "paid_at": paid_at,
                "gross": round(gross, 2),
                "tax": round(tax, 2),
                "net": round(net, 2),
                "display_tax": round(display_tax, 2),
                "display_net": round(display_net, 2),
                "payment_mode": payment_mode,
            }

        return {"paid": False, "paid_at": "", "gross": 0.0, "tax": 0.0, "net": 0.0, "display_tax": 0.0,
                "display_net": 0.0, "payment_mode": "net"}
    except Exception:
        return {"paid": False, "paid_at": "", "gross": 0.0, "tax": 0.0, "net": 0.0, "display_tax": 0.0,
                "display_net": 0.0, "payment_mode": "net"}


def _is_paid_for_week(week_start: str, week_end: str, username: str) -> tuple[bool, str]:
    rec = _get_paid_record_for_week(week_start, week_end, username)
    return (bool(rec.get("paid")), str(rec.get("paid_at") or ""))


# ================= NAV / LAYOUT =================
def bottom_nav(active: str, role: str) -> str:
    return ""


def sidebar_html(active: str, role: str) -> str:
    items = [
        ("home", "/", "Dashboard", _icon_dashboard(28)),
        ("clock", "/clock", "Clock In & Out", _icon_clock(28)),
        ("times", "/my-times", "Time logs", _icon_timelogs(28)),
        ("reports", "/my-reports", "Timesheets", _icon_timesheets(28)),
        ("payments", "/payments", "Payments", _icon_payments(28)),
    ]

    if role in ("admin", "master_admin"):
        items.append(("admin", "/admin", "Admin", _icon_admin(28)))

    if role == "master_admin":
        items.append(("workplaces", "/admin/workplaces", "Workplaces", _icon_workplaces(28)))

    links = []
    for key, href, label, icon in items:
        links.append(f"""
          <a class="sideItem nav-{key} {'active' if active == key else ''}" href="{href}">
            <div class="sideLeft">
              <div class="sideIcon">{icon}</div>
              <div class="sideText">{escape(label)}</div>
            </div>
            <div class="chev">›</div>
          </a>
        """)

    return f"""
      <div class="sidebar">
        <div style="padding:4px 0 4px; display:flex; justify-content:center; align-items:center;">
          <img
            src="/static/original-logo.png"
            alt="TimIQ"
            style="
              width:180px;
              max-width:180px;
              height:auto;
              display:block;
            "
          >
        </div>
        {''.join(links)}
      </div>
    """


def page_back_button(href: str | None = None, label: str = "Back") -> str:
    text = escape(label or "Back")
    if href:
        return f'''
        <div class="pageBackRow">
          <a href="{escape(href)}"
             aria-label="{text}"
             title="{text}"
             style="
               display:inline-block;
               color:#000;
               text-decoration:none;
               font-size:14px;
               font-weight:400;
               line-height:1.2;
               background:none;
               border:0;
               padding:0;
               box-shadow:none;
             ">
            Back
          </a>
        </div>
        '''
    return f'''
    <div class="pageBackRow">
      <button type="button"
              aria-label="{text}"
              title="{text}"
              onclick="window.history.back()"
              style="
                display:inline-block;
                color:#000;
                text-decoration:none;
                font-size:14px;
                font-weight:400;
                line-height:1.2;
                background:none;
                border:0;
                padding:0;
                box-shadow:none;
                cursor:pointer;
              ">
        Back
      </button>
    </div>
    '''

def layout_shell(active: str, role: str, content_html: str, shell_class: str = "") -> str:
    extra = f" {shell_class}" if shell_class else ""

    try:
        company_name = (get_company_settings().get("Company_Name") or "").strip() or "Main"
    except Exception:
        company_name = "Main"

    company_bar = f"""
      <div class="topBarFixed">
        <a href="/" class="mobileTopLogo" aria-label="TimIQ home">
  <img src="/static/original-logo.png" alt="TimIQ">
</a>
        <span class="topBrandBadge">{escape(company_name)}</span>
        <div class="topAccountWrap">
          <button type="button" class="topAccountTrigger" aria-label="Account menu" onclick="(function(btn){{var wrap=btn.closest('.topAccountWrap'); if(!wrap) return; document.querySelectorAll('.topAccountWrap.open').forEach(function(el){{if(el!==wrap) el.classList.remove('open');}}); wrap.classList.toggle('open');}})(this)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="5" r="1.5"></circle><circle cx="12" cy="12" r="1.5"></circle><circle cx="12" cy="19" r="1.5"></circle></svg>
          </button>
          <div class="topAccountMenu">
            <a class="topAccountMenuItem" href="/onboarding"><span>Starter Form</span><span class="topAccountMenuMark">›</span></a>
            <a class="topAccountMenuItem" href="/password"><span>Profile</span><span class="topAccountMenuMark">›</span></a>
            <a class="topAccountMenuItem danger" href="/logout"><span>Log out</span><span class="topAccountMenuMark">›</span></a>
          </div>
        </div>
      </div>
      <script>
      (function(){{
        if (window.__topAccountMenuBound) return;
        window.__topAccountMenuBound = true;
        document.addEventListener('click', function(e){{
          document.querySelectorAll('.topAccountWrap.open').forEach(function(wrap){{
            if (!wrap.contains(e.target)) wrap.classList.remove('open');
          }});
        }});
        document.addEventListener('keydown', function(e){{
          if (e.key === 'Escape') {{
            document.querySelectorAll('.topAccountWrap.open').forEach(function(wrap){{
              wrap.classList.remove('open');
            }});
          }}
        }});
      }})();
      </script>
    """

    return f"""
      <div class="shell{extra}">
        {sidebar_html(active, role)}
        <div class="main">
          {company_bar}
          {content_html}
          <div class="safeBottom"></div>
        </div>
      </div>
    """


# ================= ROUTES =================
@routes.get("/ping")
def ping():
    return "pong", 200


# ----- OAUTH CONNECT (ADMIN ONLY) -----
@routes.get("/connect-drive")
def connect_drive():
    gate = require_login()
    if gate:
        return gate
    if session.get("role") != "master_admin":
        return redirect(url_for("home"))

    flow = _make_oauth_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["oauth_code_verifier"] = getattr(flow, "code_verifier", None)
    session["oauth_state"] = state
    return redirect(auth_url)


@routes.get("/oauth2callback")
def oauth2callback():
    gate = require_login()
    if gate:
        return gate
    if session.get("role") != "master_admin":
        return redirect(url_for("home"))

    returned_state = request.args.get("state")
    expected_state = session.get("oauth_state")
    if not expected_state or returned_state != expected_state:
        abort(400)
    session.pop("oauth_state", None)

    flow = _make_oauth_flow()
    flow.code_verifier = session.get("oauth_code_verifier")
    flow.fetch_token(authorization_response=request.url)
    session.pop("oauth_code_verifier", None)
    creds_user = flow.credentials

    token_dict = {
        "token": creds_user.token,
        "refresh_token": creds_user.refresh_token,
        "token_uri": creds_user.token_uri,
        "client_id": creds_user.client_id,
        "client_secret": creds_user.client_secret,
        "scopes": creds_user.scopes,
    }
    session["drive_connected"] = True
    _save_drive_token(token_dict)
    return redirect(url_for("home"))


# ---------- LOGIN ----------
@routes.route("/login", methods=["GET", "POST"])
def login():
    return login_impl(core=globals())

@routes.get("/logout")
def logout_confirm():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    role = session.get("role", "employee")

    content = f"""
      {page_back_button("/", "Back to dashboard")}

      <div class="headerTop">
        <div>
          <h1>Logout</h1>
          <p class="sub">Are you sure you want to log out?</p>
        </div>
        <div class="badge {'admin' if role == 'admin' else ''}">{escape(role.upper())}</div>
      </div>

      <div class="card" style="padding:14px;">
        <form method="POST" action="/logout" style="margin:0;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <div class="actionRow" style="grid-template-columns: 1fr 1fr;">
            <a href="/" style="display:block;">
              <button class="btnSoft" type="button" style="width:100%;">Cancel</button>
            </a>
            <button class="btnOut" type="submit" style="width:100%;">Logout</button>
          </div>
        </form>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("home", role, content))


@routes.post("/logout")
def logout():
    require_csrf()
    username = (session.get("username") or "").strip()
    workplace_id = _session_workplace_id()
    active_session_token = str(session.get("active_session_token") or "")
    if username and active_session_token:
        _clear_active_session_token(username, workplace_id, expected_token=active_session_token)
    session.clear()
    return redirect(url_for("login"))


@routes.get("/api/dashboard-snapshot")
def api_dashboard_snapshot():
    gate = require_login()
    if gate:
        return gate

    if session.get("role") not in ("admin", "master_admin"):
        abort(403)

    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    employee_count = 0
    clocked_in_count = 0
    active_locations_count = 0
    onboarding_pending_count = 0

    try:
        emp_vals = employees_sheet.get_all_values()
        if emp_vals:
            emp_headers = emp_vals[0]
            i_user = emp_headers.index("Username") if "Username" in emp_headers else None
            i_wp = emp_headers.index("Workplace_ID") if "Workplace_ID" in emp_headers else None
            i_onb = emp_headers.index("OnboardingCompleted") if "OnboardingCompleted" in emp_headers else None

            for r in emp_vals[1:]:
                if i_user is None or i_user >= len(r):
                    continue

                u = (r[i_user] or "").strip()
                if not u:
                    continue

                if i_wp is not None:
                    row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                    if row_wp not in allowed_wps:
                        continue

                employee_count += 1

                if i_onb is not None:
                    done_flag = (r[i_onb] if i_onb < len(r) else "").strip().lower()
                    if done_flag not in ("true", "1", "yes"):
                        onboarding_pending_count += 1
    except Exception:
        pass

    try:
        clocked_in_count = sum(1 for _ in _get_open_shifts())
    except Exception:
        clocked_in_count = 0

    try:
        active_locations_count = len(_get_active_locations())
    except Exception:
        active_locations_count = 0

    return jsonify({
        "employee_count": employee_count,
        "clocked_in_count": clocked_in_count,
        "active_locations_count": active_locations_count,
        "onboarding_pending_count": onboarding_pending_count,
        "updated_at": datetime.now(TZ).strftime("%H:%M:%S"),
    })


@routes.get("/")
def home():
    return home_impl(core=globals())

# ---------- CLOCK PAGE ----------
@routes.route("/clock", methods=["GET", "POST"])
def clock_page():
    return clock_page_impl(core=globals())


@routes.get("/my-times")
def my_times():
    return my_times_impl(core=globals())


@routes.get("/admin/log-activities")
def admin_log_activities():
    return admin_log_activities_impl(core=globals())


@routes.get("/my-reports")
def my_reports():
    return my_reports_impl(core=globals())



@routes.get("/my-week-report")
def my_week_report():
    return my_week_report_impl(core=globals())

@routes.get("/payments")
def payments_page():
    return payments_page_impl(core=globals())

@routes.get("/my-reports-print")
def my_reports_print():
    return my_reports_print_impl(core=globals())

@routes.get("/my-reports.pdf")
def my_reports_pdf():
    return my_reports_pdf_impl(core=globals())

@routes.get("/my-reports.csv")
def my_reports_csv():
    return my_reports_csv_impl(core=globals())


@routes.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    return onboarding_impl(core=globals())


def _render_onboarding_page(display_name, role, csrf, existing, msg, msg_ok, typed, missing_fields):
    typed = typed or {}

    def val(input_name, existing_key):
        if input_name in typed and typed[input_name] is not None:
            return typed[input_name]
        return (existing or {}).get(existing_key, "")

    def bad(input_name):
        return "bad" if input_name in (missing_fields or set()) else ""

    def bad_label(input_name):
        return "badLabel" if input_name in (missing_fields or set()) else ""

    def checked_radio(input_name, existing_key, value):
        return "checked" if val(input_name, existing_key) == value else ""

    def selected(input_name, existing_key, value):
        return "selected" if val(input_name, existing_key) == value else ""

    drive_hint = ""
    if role == "master_admin" and (OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and OAUTH_REDIRECT_URI):
        drive_hint = "<p class='sub'>Master admin: if uploads fail, click <a href='/connect-drive' style='color:#1d4ed8;font-weight:700;'>Connect Drive</a> once.</p>"

    page_css = """
      <style>
        .onboardIntroCard, .onboardShell{
          border:1px solid rgba(15,23,42,.08);
          background:linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
          box-shadow:0 18px 40px rgba(15,23,42,.08), inset 0 1px 0 rgba(255,255,255,.78);
        }
        .onboardIntroCard{ padding:18px; border-radius: 0 !important; margin-bottom:12px; }
        .onboardHeroTop{ display:flex; justify-content:space-between; gap:14px; align-items:flex-start; flex-wrap:wrap; }
        .onboardEyebrow{ display:inline-flex; align-items:center; gap:8px; padding:7px 12px; border-radius: 0 !important; font-size:12px; font-weight:800; letter-spacing:.05em; text-transform:uppercase; color:#1d4ed8; background:rgba(59,130,246,.10); border:1px solid rgba(96,165,250,.18); margin-bottom:10px; }
        .onboardIntroCard h1{ color:var(--text); margin:0; }
        .onboardIntroCard .sub{ color:var(--muted); }
        .onboardMiniGrid{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-top:14px; }
        .onboardMiniStat{ padding:12px 14px; border-radius: 0 !important; background:linear-gradient(180deg, rgba(248,250,252,.98), rgba(241,245,249,.98)); border:1px solid rgba(15,23,42,.08); }
        .onboardMiniStat .k{ font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.05em; color:#64748b; }
        .onboardMiniStat .v{ margin-top:6px; font-size:15px; font-weight:700; color:var(--text); }
        .onboardShell{ padding:16px; border-radius: 0 !important; }
        .onboardShell form > h2{ margin:18px 0 10px; padding:10px 14px; border-radius: 0 !important; background:linear-gradient(180deg, rgba(241,245,249,.98), rgba(226,232,240,.96)); border:1px solid rgba(148,163,184,.18); color:var(--text); font-size:18px; font-weight:800; }
        .onboardShell .sub, .onboardShell label{ color:#64748b; }
        .onboardShell .uploadTitle{ margin-top:12px; font-size:13px; font-weight:800; letter-spacing:.03em; color:var(--text); }
        .onboardShell .row2{ display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:12px; align-items:start; }
        .onboardShell .input{ background:rgba(255,255,255,.96); border:1px solid rgba(15,23,42,.10); color:var(--text); box-shadow:none; }
        .onboardShell .input::placeholder{ color:#94a3b8; }
        .onboardShell .input:focus{ border-color:rgba(96,165,250,.34); box-shadow:0 0 0 3px rgba(37,99,235,.10); }
        .onboardShell .contractBox{ background:rgba(248,250,252,.96); border:1px solid rgba(15,23,42,.08); color:var(--text); }
        .onboardActionRow{ position:sticky; bottom:10px; z-index:3; margin-top:18px !important; padding:12px; border-radius: 0 !important; background:rgba(255,255,255,.92); border:1px solid rgba(15,23,42,.08); box-shadow:0 18px 36px rgba(15,23,42,.08); backdrop-filter:blur(10px); }
        .onboardDraftBtn, .onboardFinalBtn{ min-height:52px; width:100%; }
        .onboardDraftBtn{ background:rgba(255,255,255,.96); color:#1e40af; border:1px solid rgba(30,64,175,.14); }
        .onboardFinalBtn{ background:linear-gradient(90deg, #2563eb, #4f7cff) !important; color:#fff; box-shadow:0 14px 28px rgba(37,99,235,.20); }
        .onboardShell .bad{ border-color:rgba(248,113,113,.42) !important; }
        .onboardShell .badLabel{ color:#dc2626 !important; }
        @media (max-width: 860px){ .onboardMiniGrid{ grid-template-columns:1fr; } }
        @media (max-width: 700px){ .onboardShell .row2{ grid-template-columns:1fr; } .onboardActionRow{ position:static; padding:0; border:0; background:transparent; box-shadow:none; backdrop-filter:none; } }
      </style>
    """
    return f"""
      {page_css}
      {page_back_button("/", "Back to dashboard")}
      <div class="onboardIntroCard card">
        <div class="onboardHeroTop">
          <div>
            <div class="onboardEyebrow">Starter Form</div>
            <h1>Starter Form</h1>
            <p class="sub">{escape(display_name)} • Save draft anytime • Submit final when complete.</p>
            {drive_hint}
          </div>
          <div class="badge {'admin' if role == 'admin' else ''}">{escape(role.upper())}</div>
        </div>
        <div class="onboardMiniGrid">
          <div class="onboardMiniStat"><div class="k">Workflow</div><div class="v">Draft → Final submission</div></div>
          <div class="onboardMiniStat"><div class="k">Uploads</div><div class="v">4 documents required for final</div></div>
          <div class="onboardMiniStat"><div class="k">Status</div><div class="v">Review each section before sending</div></div>
        </div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and msg_ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not msg_ok) else ""}

      <div class="card onboardShell">
        <form method="POST" enctype="multipart/form-data">
          <input type="hidden" name="csrf" value="{escape(csrf)}">

          <h2>Personal details</h2>
          <div class="row2">
            <div>
              <label class="sub {bad_label('first')}">First Name</label>
              <input class="input {bad('first')}" name="first" value="{escape(val('first', 'FirstName'))}">
            </div>
            <div>
              <label class="sub {bad_label('last')}">Last Name</label>
              <input class="input {bad('last')}" name="last" value="{escape(val('last', 'LastName'))}">
            </div>
          </div>

          <label class="sub {bad_label('birth')}" style="margin-top:10px; display:block;">Birth Date</label>
          <input class="input {bad('birth')}" type="date" name="birth" value="{escape(val('birth', 'BirthDate'))}">

          <label class="sub {bad_label('phone_num')}" style="margin-top:10px; display:block;">Phone Number</label>
          <input type="hidden" name="phone_cc" value="">
          <input class="input {bad('phone_num')}" name="phone_num" value="{escape(val('phone_num', 'PhoneNumber'))}">


          <h2 style="margin-top:14px;">Address</h2>
          <input class="input" name="street" placeholder="Street Address" value="{escape(val('street', 'StreetAddress'))}">
          <div class="row2">
            <input class="input" name="city" placeholder="City" value="{escape(val('city', 'City'))}">
            <input class="input" name="postcode" placeholder="Postcode" value="{escape(val('postcode', 'Postcode'))}">
          </div>

          <div class="row2">
            <div>
              <label class="sub {bad_label('email')}">Email</label>
              <input class="input {bad('email')}" name="email" type="email" value="{escape(val('email', 'Email'))}">
            </div>
            <div>
              <label class="sub {bad_label('ec_name')}">Emergency Contact Name</label>
              <input class="input {bad('ec_name')}" name="ec_name" value="{escape(val('ec_name', 'EmergencyContactName'))}">
            </div>
          </div>

          <label class="sub {bad_label('ec_phone')}" style="margin-top:10px; display:block;">Emergency Contact Phone</label>
          <input type="hidden" name="ec_cc" value="">
          <input class="input {bad('ec_phone')}" name="ec_phone" value="{escape(val('ec_phone', 'EmergencyContactPhoneNumber'))}">


          <h2 style="margin-top:14px;">Medical</h2>
          <label class="sub {bad_label('medical')}">Do you have any medical condition that may affect you at work?</label>
          <div class="row2">
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="medical" value="no" {checked_radio('medical', 'MedicalCondition', 'no')}> No
            </label>
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="medical" value="yes" {checked_radio('medical', 'MedicalCondition', 'yes')}> Yes
            </label>
          </div>
          <label class="sub" style="margin-top:10px; display:block;">Details</label>
          <input class="input" name="medical_details" value="{escape(val('medical_details', 'MedicalDetails'))}">

          <h2 style="margin-top:14px;">Position</h2>
          <div class="row2">
            <label class="sub {bad_label('position')}" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Bricklayer" {"checked" if val('position', 'Position') == 'Bricklayer' else ""}> Bricklayer
            </label>
            <label class="sub {bad_label('position')}" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Labourer" {"checked" if val('position', 'Position') == 'Labourer' else ""}> Labourer
            </label>
            <label class="sub {bad_label('position')}" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Fixer" {"checked" if val('position', 'Position') == 'Fixer' else ""}> Fixer
            </label>
            <label class="sub {bad_label('position')}" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Supervisor/Foreman" {"checked" if val('position', 'Position') == 'Supervisor/Foreman' else ""}> Supervisor/Foreman
            </label>
          </div>

          <div class="row2">
            <div>
              <label class="sub {bad_label('cscs_no')}">CSCS Number</label>
              <input class="input {bad('cscs_no')}" name="cscs_no" value="{escape(val('cscs_no', 'CSCSNumber'))}">
            </div>
            <div>
              <label class="sub {bad_label('cscs_exp')}">CSCS Expiry</label>
              <input class="input {bad('cscs_exp')}" type="date" name="cscs_exp" value="{escape(val('cscs_exp', 'CSCSExpiryDate'))}">
            </div>
          </div>

          <label class="sub {bad_label('emp_type')}" style="margin-top:10px; display:block;">Employment Type</label>
          <select class="input {bad('emp_type')}" name="emp_type">
            <option value="">Please Select</option>
            <option value="Self-employed" {selected('emp_type', 'EmploymentType', 'Self-employed')}>Self-employed</option>
            <option value="Ltd Company" {selected('emp_type', 'EmploymentType', 'Ltd Company')}>Ltd Company</option>
            <option value="Agency" {selected('emp_type', 'EmploymentType', 'Agency')}>Agency</option>
            <option value="PAYE" {selected('emp_type', 'EmploymentType', 'PAYE')}>PAYE</option>
          </select>

          <label class="sub {bad_label('rtw')}" style="margin-top:10px; display:block;">Right to work in UK?</label>
          <div class="row2">
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="rtw" value="yes" {checked_radio('rtw', 'RightToWorkUK', 'yes')}> Yes
            </label>
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="rtw" value="no" {checked_radio('rtw', 'RightToWorkUK', 'no')}> No
            </label>
          </div>

          <div class="row2">
            <div>
              <label class="sub {bad_label('ni')}">National Insurance</label>
              <input class="input {bad('ni')}" name="ni" value="{escape(val('ni', 'NationalInsurance'))}">
            </div>
            <div>
              <label class="sub {bad_label('utr')}">UTR</label>
              <input class="input {bad('utr')}" name="utr" value="{escape(val('utr', 'UTR'))}">
            </div>
          </div>

          <label class="sub {bad_label('start_date')}" style="margin-top:10px; display:block;">Start Date</label>
          <input class="input {bad('start_date')}" type="date" name="start_date" value="{escape(val('start_date', 'StartDate'))}">

          <h2 style="margin-top:14px;">Bank details</h2>
          <div class="row2">
            <div>
              <label class="sub {bad_label('acc_no')}">Account Number</label>
              <input class="input {bad('acc_no')}" name="acc_no" value="{escape(val('acc_no', 'BankAccountNumber'))}">
            </div>
            <div>
              <label class="sub {bad_label('sort_code')}">Sort Code</label>
              <input class="input {bad('sort_code')}" name="sort_code" value="{escape(val('sort_code', 'SortCode'))}">
            </div>
          </div>
          <label class="sub {bad_label('acc_name')}" style="margin-top:10px; display:block;">Account Holder Name</label>
          <input class="input {bad('acc_name')}" name="acc_name" value="{escape(val('acc_name', 'AccountHolderName'))}">

          <h2 style="margin-top:14px;">Company details</h2>
          <input class="input" name="comp_trading" placeholder="Trading name" value="{escape(val('comp_trading', 'CompanyTradingName'))}">
          <input class="input" name="comp_reg" placeholder="Company reg no." value="{escape(val('comp_reg', 'CompanyRegistrationNo'))}">

          <h2 style="margin-top:14px;">Contract & site</h2>
          <div class="row2">
            <div>
              <label class="sub {bad_label('contract_date')}">Date of Contract</label>
              <input class="input {bad('contract_date')}" type="date" name="contract_date" value="{escape(val('contract_date', 'DateOfContract'))}">
            </div>
            <div>
              <label class="sub {bad_label('site_address')}">Site address</label>
              <input class="input {bad('site_address')}" name="site_address" value="{escape(val('site_address', 'SiteAddress'))}">
            </div>
          </div>

          <h2 style="margin-top:14px;">Upload documents</h2>
          <p class="sub">Draft: optional uploads. Final: all 4 required. (If Final fails, re-select files.)</p>

          <div class="uploadTitle {bad_label('passport_file')}">Passport or Birth Certificate</div>
          <input class="input {bad('passport_file')}" type="file" name="passport_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('PassportOrBirthCertLink', ''))}</p>

          <div class="uploadTitle {bad_label('cscs_file')}">CSCS Card (front & back)</div>
          <input class="input {bad('cscs_file')}" type="file" name="cscs_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('CSCSFrontBackLink', ''))}</p>

          <div class="uploadTitle {bad_label('pli_file')}">Public Liability Insurance</div>
          <input class="input {bad('pli_file')}" type="file" name="pli_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('PublicLiabilityLink', ''))}</p>

          <div class="uploadTitle {bad_label('share_file')}">Share Code / Confirmation</div>
          <input class="input {bad('share_file')}" type="file" name="share_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('ShareCodeLink', ''))}</p>

          <h2 style="margin-top:14px;">Contract</h2>
          <div class="contractBox">{escape(CONTRACT_TEXT)}</div>

          <label class="sub {bad_label('contract_accept')}" style="display:flex; gap:10px; align-items:center; margin-top:10px;">
            <input type="checkbox" name="contract_accept" value="yes" {"checked" if typed.get('contract_accept') == 'yes' else ""}>
            I have read and accept the contract terms (required for Final)
          </label>

          <label class="sub {bad_label('signature_name')}" style="margin-top:10px; display:block;">Signature (type your full name)</label>
          <input class="input {bad('signature_name')}" name="signature_name" value="{escape(val('signature_name', 'SignatureName'))}">

          <div class="row2 onboardActionRow">
            <button class="btnSoft onboardDraftBtn" name="submit_type" value="draft" type="submit">Save Draft</button>
            <button class="btnSoft onboardFinalBtn" name="submit_type" value="final" type="submit">Submit Final</button>
          </div>
        </form>
      </div>
    """


@routes.route("/password", methods=["GET", "POST"])
def change_password():
    return change_password_impl(core=globals())


def _get_user_rate(username: str) -> float:
    return get_user_rate_data(
        username=username,
        session_workplace_id=_session_workplace_id(),
        workplace_ids_for_read=_workplace_ids_for_read,
        db_migration_mode=DB_MIGRATION_MODE,
        employee_model=Employee,
        employees_sheet=employees_sheet,
        session_obj=session,
        safe_float_func=safe_float,
    )

def _get_open_shifts() -> list[dict]:
    """Return currently open shifts (ClockOut empty) with display metadata for Admin dashboard."""
    out = []
    try:
        rows = get_workhours_rows()
        if not rows or len(rows) < 2:
            return out
        headers = rows[0]

        # fall back to fixed indexes if headers are missing
        def hidx(name, default_idx):
            return headers.index(name) if (headers and name in headers) else default_idx

        i_user = hidx("Username", COL_USER)
        i_date = hidx("Date", COL_DATE)
        i_in = hidx("ClockIn", COL_IN)
        i_out = hidx("ClockOut", COL_OUT)
        i_wp = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
        current_wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(current_wp))

        for r in rows[1:]:
            if len(r) <= max(i_user, i_date, i_in, i_out):
                continue
            u = (r[i_user] or "").strip()
            # Tenant-safe: only show open shifts for this workplace
            if i_wp is not None:
                row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                if row_wp not in allowed_wps:
                    continue
            else:
                # Backward compat: if WorkHours has no Workplace_ID column
                # prevent cross-workplace bleed when usernames overlap
                if u and not user_in_same_workplace(u):
                    continue
            d = (r[i_date] or "").strip()
            t_in = (r[i_in] or "").strip()
            t_out = (r[i_out] or "").strip()
            if not u or not d or not t_in:
                continue
            if t_out != "":
                continue
            # Parse start
            start_iso = ""
            start_label = f"{d} {t_in}"
            try:
                start_dt = datetime.strptime(start_label, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
                start_iso = start_dt.isoformat()
            except Exception:
                # Accept HH:MM without seconds
                try:
                    start_dt = datetime.strptime(f"{d} {t_in}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                    start_iso = start_dt.isoformat()
                    start_label = start_dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    start_iso = ""

            out.append({
                "user": u,
                "name": get_employee_display_name(u),
                "start_label": start_label,
                "start_iso": start_iso or start_label,
            })
    except Exception:
        return []
    return out


# ---------- ADMIN ----------
@routes.get("/admin")
def admin():
    return admin_impl(core=globals())


def admin_back_link(href: str = "/admin") -> str:
    return f"""
      <div style="margin:8px 0 14px;">
        <a href="{href}"
           aria-label="Back"
           title="Back"
           style="
             display:inline-block;
             color:#000;
             text-decoration:none;
             font-size:14px;
             font-weight:400;
             line-height:1.2;
             background:none;
             border:0;
             padding:0;
             box-shadow:none;
           ">
          Back
        </a>
      </div>
    """

@routes.route("/admin/company", methods=["GET", "POST"])
def admin_company():
    return admin_company_impl(core=globals())


@routes.post("/admin/save-shift")
def admin_save_shift():
    return admin_save_shift_impl(core=globals())



@routes.post("/admin/force-clockin")
def admin_force_clockin():
    return admin_force_clockin_impl(core=globals())

@routes.post("/admin/force-clockout")
def admin_force_clockout():
    return admin_force_clockout_impl(core=globals())

@routes.post("/admin/mark-paid")
def admin_mark_paid():
    return admin_mark_paid_impl(core=globals())

@routes.get("/admin/payroll")
def admin_payroll():
    return admin_payroll_impl(core=globals())


def _get_week_range(wk_offset: int):
    """
    Returns (week_start_str, week_end_str) for a Monday->Sunday week,
    offset by wk_offset weeks (0=this week, 1=previous week, etc.).
    """
    today = datetime.now(TZ).date()
    monday = today - timedelta(days=today.weekday())  # Monday
    week_start = monday - timedelta(days=7 * int(wk_offset))
    week_end = week_start + timedelta(days=6)  # Sunday
    return week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d")


@routes.get("/admin/payroll-report.csv")
def admin_payroll_report_csv():
    return admin_payroll_report_csv_impl(core=globals())

@routes.get("/admin/onboarding")
def admin_onboarding_list():
    return admin_onboarding_list_impl(core=globals())

@routes.get("/admin/onboarding/<username>")
def admin_onboarding_detail(username):
    return admin_onboarding_detail_impl(core=globals(), username=username)

@routes.get("/admin/onboarding/<username>/download")
def admin_onboarding_download(username):
    return admin_onboarding_download_impl(core=globals(), username=username)


@routes.get("/admin/locations")
def admin_locations():
    return admin_locations_impl(core=globals())


def _find_location_row_by_name(name: str):
    if not locations_sheet:
        return None
    try:
        vals = locations_sheet.get_all_values()
        if not vals:
            return None

        headers = vals[0]
        start_idx = 1 if "SiteName" in headers else 0

        wp_idx = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
        current_wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(current_wp))

        target = (name or "").strip().lower()
        if not target:
            return None

        for i in range(start_idx, len(vals)):
            r = vals[i]
            n = (r[0] if len(r) > 0 else "").strip().lower()
            if n != target:
                continue

            if wp_idx is not None:
                row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

            return i + 1
    except Exception:
        return None
    return None

@routes.post("/admin/locations/save")
def admin_locations_save():
    return admin_locations_save_impl(core=globals())

@routes.post("/admin/locations/deactivate")
def admin_locations_deactivate():
    return admin_locations_deactivate_impl(core=globals())

@routes.get("/admin/employee-sites")
def admin_employee_sites():
    return admin_employee_sites_impl(core=globals())

@routes.post("/admin/employee-sites/save")
def admin_employee_sites_save():
    return admin_employee_sites_save_impl(core=globals())

@routes.route("/admin/employees", methods=["GET", "POST"])
def admin_employees():
    return admin_employees_impl(core=globals())

# ================= LOCAL RUN =================


@routes.route("/admin/workplaces", methods=["GET", "POST"])
def admin_workplaces():
    return admin_workplaces_impl(core=globals())


def _db_parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _db_parse_datetime(date_value, time_value):
    d = _db_parse_date(date_value) if not isinstance(date_value, date) else date_value
    t = str(time_value or "").strip()
    if not d or not t:
        return None
    if len(t.split(":")) == 2:
        t = t + ":00"
    try:
        return datetime.strptime(f"{d.isoformat()} {t}", "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _db_format_decimal(val):
    if val in (None, ""):
        return ""
    try:
        return str(val)
    except Exception:
        return ""


def _db_bool_text(v, default="TRUE"):
    txt = str(v if v not in (None, "") else default).strip()
    return txt or default


def _db_workhour_metrics(rec):
    hours_val = getattr(rec, "hours", None)
    pay_val = getattr(rec, "pay", None)

    hours_txt = "" if hours_val in (None, "") else str(hours_val)
    pay_txt = "" if pay_val in (None, "") else str(pay_val)

    if hours_txt == "" and rec.clock_in and rec.clock_out:
        try:
            raw_hours = max(0.0, (rec.clock_out - rec.clock_in).total_seconds() / 3600.0)
            computed_hours = _round_to_half_hour(_apply_unpaid_break(raw_hours))
            hours_txt = str(computed_hours)
        except Exception:
            pass

    if pay_txt == "" and hours_txt != "":
        try:
            pay_txt = str(
                _calculate_shift_pay(
                    float(hours_txt),
                    _get_user_rate(rec.employee_email or "")
                )
            )
        except Exception:
            pass

    return hours_txt, pay_txt


def _db_workhour_order_key(rec):
    d = getattr(rec, "date", None) or date.min
    cin = getattr(rec, "clock_in", None) or datetime.min
    user = str(getattr(rec, "employee_email", "") or "")
    return (str(getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"), d, user, cin,
            getattr(rec, "id", 0))


class _ProxySheetBase:
    headers = []
    model = None
    _proxy_id_seed = 1000

    def __init__(self, title):
        self.title = title
        self.id = self._proxy_id_seed
        type(self)._proxy_id_seed += 1
        self.spreadsheet = None

    def get_all_values(self):
        return [self.headers[:]] + [self._row_from_record(rec) for rec in self._records()]

    def get_all_records(self):
        out = []
        for row in self.get_all_values()[1:]:
            out.append({self.headers[i]: row[i] if i < len(row) else "" for i in range(len(self.headers))})
        return out

    def row_values(self, row):
        vals = self.get_all_values()
        if row <= 0 or row > len(vals):
            return []
        return vals[row - 1]

    def append_rows(self, rows, value_input_option=None):
        for row in rows:
            self.append_row(row, value_input_option=value_input_option)

    def insert_row(self, row, index=1):
        if index == 1:
            return
        return self.append_row(row)

    def clear(self):
        return

    def update(self, range_name=None, values=None, **kwargs):
        if values is None:
            values = kwargs.get("values")
        if not range_name or values is None:
            return
        start, end = self._parse_range(range_name)
        start_row, start_col = start
        end_row, end_col = end
        if start_row == 1 and end_row == 1:
            return
        for r_offset, row_vals in enumerate(values):
            rownum = start_row + r_offset
            for c_offset, value in enumerate(row_vals):
                colnum = start_col + c_offset
                self.update_cell(rownum, colnum, value)

    def batch_update(self, updates):
        for upd in updates or []:
            rng = upd.get("range")
            vals = upd.get("values")
            if rng and vals is not None:
                self.update(rng, vals)

    def update_cell(self, row, col, value):
        if row <= 1:
            return
        records = self._records()
        idx = row - 2
        if idx < 0 or idx >= len(records):
            return
        rec = records[idx]
        if col <= 0 or col > len(self.headers):
            return
        self._set_field(rec, self.headers[col - 1], value)
        db.session.commit()

    def _parse_range(self, rng):
        if ":" in rng:
            a, b = rng.split(":", 1)
        else:
            a = b = rng
        return gspread.utils.a1_to_rowcol(a), gspread.utils.a1_to_rowcol(b)

    def _normalize_row(self, row):
        row = list(row or [])
        if len(row) < len(self.headers):
            row += [""] * (len(self.headers) - len(row))
        return row[:len(self.headers)]


class _EmployeesProxy(_ProxySheetBase):
    headers = ["Username", "Password", "Role", "Rate", "EarlyAccess", "OnboardingCompleted", "FirstName", "LastName",
               "Site", "Active", "Workplace_ID", "Site2"]
    model = Employee

    def _records(self):
        return sorted(Employee.query.all(), key=lambda r: (
            str(getattr(r, "workplace_id", None) or getattr(r, "workplace", None) or "default"),
            str(getattr(r, "username", None) or getattr(r, "email", None) or ""), getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            str(getattr(rec, "username", None) or getattr(rec, "email", None) or ""),
            str(getattr(rec, "password", "") or ""),
            str(getattr(rec, "role", "") or ""),
            _db_format_decimal(getattr(rec, "rate", None)),
            _db_bool_text(getattr(rec, "early_access", "TRUE")),
            str(getattr(rec, "onboarding_completed", "") or ""),
            str(getattr(rec, "first_name", "") or ""),
            str(getattr(rec, "last_name", "") or ""),
            str(getattr(rec, "site", "") or ""),
            _db_bool_text(getattr(rec, "active", "TRUE")),
            str(getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"),
            str(getattr(rec, "site2", "") or ""),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        username = str(data.get("Username") or "").strip()
        wp = str(data.get("Workplace_ID") or "default").strip() or "default"
        if not username:
            return
        rec = Employee.query.filter_by(username=username, workplace_id=wp).first()
        if not rec:
            rec = Employee.query.filter_by(email=username, workplace_id=wp).first()
        if not rec:
            rec = Employee(username=username, email=username, workplace_id=wp, workplace=wp)
            db.session.add(rec)
        self._apply_data(rec, data)
        db.session.commit()

    def _apply_data(self, rec, data):
        username = str(
            data.get("Username") or getattr(rec, "username", None) or getattr(rec, "email", None) or "").strip()
        wp = str(data.get("Workplace_ID") or getattr(rec, "workplace_id", None) or getattr(rec, "workplace",
                                                                                           None) or "default").strip() or "default"
        rec.username = username
        rec.email = username
        rec.workplace_id = wp
        rec.workplace = wp
        rec.password = str(data.get("Password") or getattr(rec, "password", "") or "")
        rec.role = str(data.get("Role") or getattr(rec, "role", "") or "")
        rate_txt = str(data.get("Rate") or "").strip()
        rec.rate = Decimal(rate_txt) if rate_txt else None
        rec.early_access = _db_bool_text(data.get("EarlyAccess"), getattr(rec, "early_access", "TRUE"))
        rec.onboarding_completed = str(
            data.get("OnboardingCompleted") or getattr(rec, "onboarding_completed", "") or "")
        rec.first_name = str(data.get("FirstName") or getattr(rec, "first_name", "") or "")
        rec.last_name = str(data.get("LastName") or getattr(rec, "last_name", "") or "")
        rec.name = (" ".join([rec.first_name or "", rec.last_name or ""]).strip() or username)
        rec.site = str(data.get("Site") or getattr(rec, "site", "") or "")
        rec.site2 = str(data.get("Site2") or getattr(rec, "site2", "") or "")
        rec.active = _db_bool_text(data.get("Active"), getattr(rec, "active", "TRUE"))

    def _set_field(self, rec, column, value):
        data = {self.headers[i]: self._row_from_record(rec)[i] for i in range(len(self.headers))}
        data[column] = "" if value is None else str(value)
        self._apply_data(rec, data)


class _SettingsProxy(_ProxySheetBase):
    headers = [
        "Workplace_ID",
        "Tax_Rate",
        "Currency_Symbol",
        "Company_Name",
        "Company_Logo_URL",
        "Overtime_After_Hours",
        "Overtime_Multiplier",
    ]
    model = WorkplaceSetting

    def _records(self):
        return sorted(
            WorkplaceSetting.query.all(),
            key=lambda r: (str(getattr(r, "workplace_id", "") or ""), getattr(r, "id", 0))
        )

    def _row_from_record(self, rec):
        return [
            str(getattr(rec, "workplace_id", "") or ""),
            _db_format_decimal(getattr(rec, "tax_rate", None)),
            str(getattr(rec, "currency_symbol", "") or ""),
            str(getattr(rec, "company_name", "") or ""),
            str(getattr(rec, "company_logo_url", "") or ""),
            _db_format_decimal(getattr(rec, "overtime_after_hours", None)),
            _db_format_decimal(getattr(rec, "overtime_multiplier", None)),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        wp = str(data.get("Workplace_ID") or "default").strip() or "default"
        rec = WorkplaceSetting.query.filter_by(workplace_id=wp).first()
        if not rec:
            rec = WorkplaceSetting(workplace_id=wp)
            db.session.add(rec)
        self._apply_data(rec, data)
        db.session.commit()

    def _apply_data(self, rec, data):
        rec.workplace_id = str(
            data.get("Workplace_ID") or getattr(rec, "workplace_id", "default") or "default"
        ).strip() or "default"

        tax_txt = str(data.get("Tax_Rate") or "").strip()
        rec.tax_rate = Decimal(tax_txt) if tax_txt else Decimal("20")

        rec.currency_symbol = str(data.get("Currency_Symbol") or getattr(rec, "currency_symbol", "£") or "£")
        rec.company_name = str(data.get("Company_Name") or getattr(rec, "company_name", "Main") or "Main")
        rec.company_logo_url = str(data.get("Company_Logo_URL") or getattr(rec, "company_logo_url", "") or "")

        overtime_after_txt = str(data.get("Overtime_After_Hours") or "").strip()
        rec.overtime_after_hours = Decimal(overtime_after_txt) if overtime_after_txt else Decimal("8.5")

        overtime_mult_txt = str(data.get("Overtime_Multiplier") or "").strip()
        rec.overtime_multiplier = Decimal(overtime_mult_txt) if overtime_mult_txt else Decimal("1.5")

    def _set_field(self, rec, column, value):
        data = {self.headers[i]: self._row_from_record(rec)[i] for i in range(len(self.headers))}
        data[column] = "" if value is None else str(value)
        self._apply_data(rec, data)


class _LocationsProxy(_ProxySheetBase):
    headers = ["SiteName", "Lat", "Lon", "RadiusMeters", "Active", "Workplace_ID"]
    model = Location

    def _records(self):
        return sorted(Location.query.all(), key=lambda r: (str(getattr(r, "workplace_id", None) or "default"),
                                                           str(getattr(r, "site_name", "") or ""), getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            str(getattr(rec, "site_name", "") or ""),
            _db_format_decimal(getattr(rec, "lat", None)),
            _db_format_decimal(getattr(rec, "lon", None)),
            "" if getattr(rec, "radius_meters", None) is None else str(getattr(rec, "radius_meters")),
            _db_bool_text(getattr(rec, "active", "TRUE")),
            str(getattr(rec, "workplace_id", None) or "default"),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        wp = str(data.get("Workplace_ID") or "default").strip() or "default"
        name = str(data.get("SiteName") or "").strip()
        if not name:
            return
        rec = Location.query.filter_by(workplace_id=wp, site_name=name).first()
        if not rec:
            rec = Location(workplace_id=wp, site_name=name)
            db.session.add(rec)
        self._apply_data(rec, data)
        db.session.commit()

    def _apply_data(self, rec, data):
        rec.site_name = str(data.get("SiteName") or getattr(rec, "site_name", "") or "")
        rec.lat = Decimal(str(data.get("Lat") or getattr(rec, "lat", "0") or "0"))
        rec.lon = Decimal(str(data.get("Lon") or getattr(rec, "lon", "0") or "0"))
        rec.radius_meters = int(float(str(data.get("RadiusMeters") or getattr(rec, "radius_meters", 0) or 0)))
        rec.active = _db_bool_text(data.get("Active"), getattr(rec, "active", "TRUE"))
        rec.workplace_id = str(
            data.get("Workplace_ID") or getattr(rec, "workplace_id", "default") or "default").strip() or "default"

    def _set_field(self, rec, column, value):
        data = {self.headers[i]: self._row_from_record(rec)[i] for i in range(len(self.headers))}
        data[column] = "" if value is None else str(value)
        self._apply_data(rec, data)


class _WorkHoursProxy(_ProxySheetBase):
    headers = ["Username", "Date", "ClockIn", "ClockOut", "Hours", "Pay", "InLat", "InLon", "InAcc", "InSite",
               "InDistM", "InSelfieURL", "OutLat", "OutLon", "OutAcc", "OutSite", "OutDistM", "OutSelfieURL",
               "Workplace_ID"]
    model = WorkHour

    def _records(self):
        return sorted(WorkHour.query.all(), key=_db_workhour_order_key)

    def _row_from_record(self, rec):
        hours_txt, pay_txt = _db_workhour_metrics(rec)
        cin = rec.clock_in.strftime("%H:%M:%S") if getattr(rec, "clock_in", None) else ""
        cout = rec.clock_out.strftime("%H:%M:%S") if getattr(rec, "clock_out", None) else ""
        d = rec.date.isoformat() if getattr(rec, "date", None) else ""
        return [
            str(getattr(rec, "employee_email", "") or ""),
            d,
            cin,
            cout,
            hours_txt,
            pay_txt,
            _db_format_decimal(getattr(rec, "in_lat", None)),
            _db_format_decimal(getattr(rec, "in_lon", None)),
            _db_format_decimal(getattr(rec, "in_acc", None)),
            str(getattr(rec, "in_site", "") or ""),
            "" if getattr(rec, "in_dist_m", None) is None else str(getattr(rec, "in_dist_m")),
            str(getattr(rec, "in_selfie_url", "") or ""),
            _db_format_decimal(getattr(rec, "out_lat", None)),
            _db_format_decimal(getattr(rec, "out_lon", None)),
            _db_format_decimal(getattr(rec, "out_acc", None)),
            str(getattr(rec, "out_site", "") or ""),
            "" if getattr(rec, "out_dist_m", None) is None else str(getattr(rec, "out_dist_m")),
            str(getattr(rec, "out_selfie_url", "") or ""),
            str(getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        username = str(data.get("Username") or "").strip()
        shift_date = _db_parse_date(data.get("Date"))
        wp = str(data.get("Workplace_ID") or _session_workplace_id() or "default").strip() or "default"
        if not username or not shift_date:
            return
        rec = WorkHour.query.filter_by(employee_email=username, date=shift_date, workplace=wp).order_by(
            WorkHour.id.desc()).first()
        if not rec:
            rec = WorkHour(employee_email=username, date=shift_date, workplace=wp, workplace_id=wp)
            db.session.add(rec)
        self._apply_data(rec, data)
        db.session.commit()

    def _apply_data(self, rec, data):
        username = str(data.get("Username") or getattr(rec, "employee_email", "") or "").strip()
        shift_date = _db_parse_date(data.get("Date")) or getattr(rec, "date", None)
        wp = str(data.get("Workplace_ID") or getattr(rec, "workplace_id", None) or getattr(rec, "workplace",
                                                                                           None) or _session_workplace_id() or "default").strip() or "default"
        rec.employee_email = username
        rec.date = shift_date
        rec.workplace = wp
        rec.workplace_id = wp
        cin_txt = str(data.get("ClockIn") or "").strip()
        cout_txt = str(data.get("ClockOut") or "").strip()
        rec.clock_in = _db_parse_datetime(shift_date, cin_txt) if cin_txt else None
        rec.clock_out = _db_parse_datetime(shift_date, cout_txt) if cout_txt else None
        if rec.clock_in and rec.clock_out and rec.clock_out < rec.clock_in:
            rec.clock_out = rec.clock_out + timedelta(days=1)
        hours_txt = str(data.get("Hours") or "").strip()
        pay_txt = str(data.get("Pay") or "").strip()
        rec.hours = Decimal(hours_txt) if hours_txt else None
        rec.pay = Decimal(pay_txt) if pay_txt else None
        for col, attr in {
            "InLat": "in_lat", "InLon": "in_lon", "InAcc": "in_acc", "InSite": "in_site", "InDistM": "in_dist_m",
            "InSelfieURL": "in_selfie_url",
            "OutLat": "out_lat", "OutLon": "out_lon", "OutAcc": "out_acc", "OutSite": "out_site",
            "OutDistM": "out_dist_m", "OutSelfieURL": "out_selfie_url",
        }.items():
            raw = data.get(col)
            if attr.endswith("_site") or attr.endswith("_url"):
                setattr(rec, attr, str(raw or ""))
            elif attr.endswith("_dist_m"):
                setattr(rec, attr, int(float(raw)) if str(raw or "").strip() else None)
            else:
                setattr(rec, attr, Decimal(str(raw)) if str(raw or "").strip() else None)

    def _set_field(self, rec, column, value):
        data = {self.headers[i]: self._row_from_record(rec)[i] for i in range(len(self.headers))}
        data[column] = "" if value is None else str(value)
        self._apply_data(rec, data)


class _PayrollProxy(_ProxySheetBase):
    headers = PAYROLL_HEADERS[:]
    model = PayrollReport

    def _records(self):
        return sorted(PayrollReport.query.all(), key=lambda r: (str(getattr(r, "workplace_id", None) or "default"),
                                                                getattr(r, "week_start", None) or date.min,
                                                                str(getattr(r, "username", "") or ""),
                                                                getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            rec.week_start.isoformat() if getattr(rec, "week_start", None) else "",
            rec.week_end.isoformat() if getattr(rec, "week_end", None) else "",
            str(getattr(rec, "username", "") or ""),
            _db_format_decimal(getattr(rec, "gross", None)),
            _db_format_decimal(getattr(rec, "tax", None)),
            _db_format_decimal(getattr(rec, "net", None)),
            getattr(rec, "paid_at", None).strftime("%Y-%m-%d %H:%M:%S") if getattr(rec, "paid_at", None) else "",
            str(getattr(rec, "paid_by", "") or ""),
            str(getattr(rec, "paid", "") or ""),
            str(getattr(rec, "workplace_id", None) or "default"),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        rec = PayrollReport(
            username=str(data.get("Username") or "").strip(),
            week_start=_db_parse_date(data.get("WeekStart")),
            week_end=_db_parse_date(data.get("WeekEnd")),
            gross=Decimal(str(data.get("Gross") or "0")),
            tax=Decimal(str(data.get("Tax") or "0")),
            net=Decimal(str(data.get("Net") or "0")),
            paid_at=_db_parse_datetime(data.get("WeekEnd") or date.today().isoformat(),
                                       data.get("PaidAt").split(" ")[1] if " " in str(
                                           data.get("PaidAt") or "") else "00:00:00") if str(
                data.get("PaidAt") or "").strip() else None,
            paid_by=str(data.get("PaidBy") or ""),
            paid=str(data.get("Paid") or ""),
            workplace_id=str(data.get("Workplace_ID") or _session_workplace_id() or "default"),
        )
        if str(data.get("PaidAt") or "").strip():
            try:
                rec.paid_at = datetime.strptime(str(data.get("PaidAt")).strip(), "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        db.session.add(rec)
        db.session.commit()

    def _set_field(self, rec, column, value):
        val = "" if value is None else str(value)
        if column == "Paid":
            rec.paid = val
        elif column == "PaidBy":
            rec.paid_by = val
        elif column == "PaidAt":
            rec.paid_at = datetime.strptime(val, "%Y-%m-%d %H:%M:%S") if val else None
        db.session.commit()


class _AuditProxy(_ProxySheetBase):
    headers = AUDIT_HEADERS[:]
    model = AuditLog

    def _records(self):
        return sorted(AuditLog.query.all(),
                      key=lambda r: (getattr(r, "created_at", None) or datetime.min, getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            getattr(rec, "created_at", None).strftime("%Y-%m-%d %H:%M:%S") if getattr(rec, "created_at", None) else "",
            str(getattr(rec, "actor", "") or ""),
            str(getattr(rec, "action", "") or ""),
            str(getattr(rec, "username", None) or getattr(rec, "user_email", "") or ""),
            str(getattr(rec, "date_text", "") or ""),
            str(getattr(rec, "details", "") or ""),
            str(getattr(rec, "workplace_id", None) or "default"),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        ts = str(row[0] or datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")).strip()
        rec = AuditLog(
            created_at=datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") if ts else datetime.now(TZ),
            actor=str(row[1] or ""),
            action=str(row[2] or ""),
            username=str(row[3] or ""),
            user_email=str(row[3] or ""),
            date_text=str(row[4] or ""),
            details=str(row[5] or ""),
            workplace_id=str(row[6] or _session_workplace_id() or "default"),
        )
        db.session.add(rec)
        db.session.commit()

    def _set_field(self, rec, column, value):
        return


class _OnboardingProxy(_ProxySheetBase):
    headers = [
        "Username", "Workplace_ID", "FirstName", "LastName", "BirthDate", "PhoneCountryCode", "PhoneNumber", "Email",
        "StreetAddress", "City", "Postcode", "EmergencyContactName", "EmergencyContactPhoneCountryCode",
        "EmergencyContactPhoneNumber",
        "MedicalCondition", "MedicalDetails", "Position", "CSCSNumber", "CSCSExpiryDate", "EmploymentType",
        "RightToWorkUK",
        "NationalInsurance", "UTR", "StartDate", "BankAccountNumber", "SortCode", "AccountHolderName",
        "CompanyTradingName",
        "CompanyRegistrationNo", "DateOfContract", "SiteAddress", "PassportOrBirthCertLink", "CSCSFrontBackLink",
        "PublicLiabilityLink",
        "ShareCodeLink", "ContractAccepted", "SignatureName", "SignatureDateTime", "SubmittedAt"
    ]
    model = OnboardingRecord

    def _records(self):
        return sorted(OnboardingRecord.query.all(), key=lambda r: (str(getattr(r, "workplace_id", None) or "default"),
                                                                   str(getattr(r, "username", "") or ""),
                                                                   getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            str(getattr(rec, "username", "") or ""),
            str(getattr(rec, "workplace_id", None) or "default"),
            str(getattr(rec, "first_name", "") or ""),
            str(getattr(rec, "last_name", "") or ""),
            str(getattr(rec, "birth_date", "") or ""),
            str(getattr(rec, "phone_country_code", "") or ""),
            str(getattr(rec, "phone_number", None) or getattr(rec, "phone", "") or ""),
            str(getattr(rec, "email", "") or ""),
            str(getattr(rec, "street_address", None) or getattr(rec, "address", "") or ""),
            str(getattr(rec, "city", "") or ""),
            str(getattr(rec, "postcode", "") or ""),
            str(getattr(rec, "emergency_contact_name", "") or ""),
            str(getattr(rec, "emergency_contact_phone_country_code", "") or ""),
            str(getattr(rec, "emergency_contact_phone_number", None) or getattr(rec, "emergency_contact_phone",
                                                                                "") or ""),
            str(getattr(rec, "medical_condition", "") or ""),
            str(getattr(rec, "medical_details", "") or ""),
            str(getattr(rec, "position", "") or ""),
            str(getattr(rec, "cscs_number", "") or ""),
            str(getattr(rec, "cscs_expiry_date", "") or ""),
            str(getattr(rec, "employment_type", "") or ""),
            str(getattr(rec, "right_to_work_uk", "") or ""),
            str(getattr(rec, "national_insurance", "") or ""),
            str(getattr(rec, "utr", "") or ""),
            str(getattr(rec, "start_date", "") or ""),
            str(getattr(rec, "bank_account_number", "") or ""),
            str(getattr(rec, "sort_code", "") or ""),
            str(getattr(rec, "account_holder_name", "") or ""),
            str(getattr(rec, "company_trading_name", "") or ""),
            str(getattr(rec, "company_registration_no", "") or ""),
            str(getattr(rec, "date_of_contract", "") or ""),
            str(getattr(rec, "site_address", "") or ""),
            str(getattr(rec, "passport_or_birth_cert_link", "") or ""),
            str(getattr(rec, "cscs_front_back_link", "") or ""),
            str(getattr(rec, "public_liability_link", "") or ""),
            str(getattr(rec, "share_code_link", "") or ""),
            str(getattr(rec, "contract_accepted", "") or ""),
            str(getattr(rec, "signature_name", "") or ""),
            str(getattr(rec, "signature_datetime", "") or ""),
            str(getattr(rec, "submitted_at", "") or ""),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        username = str(data.get("Username") or "").strip()
        wp = str(data.get("Workplace_ID") or _session_workplace_id() or "default").strip() or "default"
        if not username:
            return
        rec = OnboardingRecord.query.filter_by(username=username, workplace_id=wp).first()
        if not rec:
            rec = OnboardingRecord(username=username, workplace_id=wp)
            db.session.add(rec)
        self._apply_data(rec, data)
        db.session.commit()

    def _apply_data(self, rec, data):
        mapping = {
            "FirstName": "first_name", "LastName": "last_name", "BirthDate": "birth_date",
            "PhoneCountryCode": "phone_country_code",
            "PhoneNumber": "phone_number", "Email": "email", "StreetAddress": "street_address", "City": "city",
            "Postcode": "postcode",
            "EmergencyContactName": "emergency_contact_name",
            "EmergencyContactPhoneCountryCode": "emergency_contact_phone_country_code",
            "EmergencyContactPhoneNumber": "emergency_contact_phone_number", "MedicalCondition": "medical_condition",
            "MedicalDetails": "medical_details",
            "Position": "position", "CSCSNumber": "cscs_number", "CSCSExpiryDate": "cscs_expiry_date",
            "EmploymentType": "employment_type",
            "RightToWorkUK": "right_to_work_uk", "NationalInsurance": "national_insurance", "UTR": "utr",
            "StartDate": "start_date",
            "BankAccountNumber": "bank_account_number", "SortCode": "sort_code",
            "AccountHolderName": "account_holder_name",
            "CompanyTradingName": "company_trading_name", "CompanyRegistrationNo": "company_registration_no",
            "DateOfContract": "date_of_contract",
            "SiteAddress": "site_address", "PassportOrBirthCertLink": "passport_or_birth_cert_link",
            "CSCSFrontBackLink": "cscs_front_back_link",
            "PublicLiabilityLink": "public_liability_link", "ShareCodeLink": "share_code_link",
            "ContractAccepted": "contract_accepted",
            "SignatureName": "signature_name", "SignatureDateTime": "signature_datetime", "SubmittedAt": "submitted_at",
        }
        rec.username = str(data.get("Username") or getattr(rec, "username", "") or "")
        rec.workplace_id = str(
            data.get("Workplace_ID") or getattr(rec, "workplace_id", None) or _session_workplace_id() or "default")
        for col, attr in mapping.items():
            setattr(rec, attr, str(data.get(col) or getattr(rec, attr, "") or ""))
        rec.phone = rec.phone_number
        rec.address = rec.street_address
        rec.emergency_contact_phone = rec.emergency_contact_phone_number

    def _set_field(self, rec, column, value):
        data = {self.headers[i]: self._row_from_record(rec)[i] for i in range(len(self.headers))}
        data[column] = "" if value is None else str(value)
        self._apply_data(rec, data)


def _ensure_database_schema(app):
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
            "ALTER TABLE payroll_reports ADD COLUMN IF NOT EXISTS display_tax NUMERIC(10,2)",
            "ALTER TABLE payroll_reports ADD COLUMN IF NOT EXISTS display_net NUMERIC(10,2)",
            "ALTER TABLE payroll_reports ADD COLUMN IF NOT EXISTS payment_mode VARCHAR(20)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS signature_datetime VARCHAR(100)",
            "ALTER TABLE workplace_settings ADD COLUMN IF NOT EXISTS company_logo_url TEXT",
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


def log_audit(action: str, actor: str = "", username: str = "", date_str: str = "", details: str = ""):
    ts = datetime.now(TZ)
    if DATABASE_ENABLED:
        try:
            db.session.add(
                AuditLog(
                    action=action or "unknown",
                    user_email=(username or actor or ""),
                    actor=actor or "",
                    username=username or "",
                    date_text=date_str or "",
                    details=details or "",
                    workplace_id=_session_workplace_id(),
                    created_at=ts,
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
        return

    if audit_sheet:
        try:
            _ensure_audit_headers()
            audit_sheet.append_row(
                [ts.strftime("%Y-%m-%d %H:%M:%S"), actor or "", action or "", username or "", date_str or "",
                 details or "", _session_workplace_id()])
        except Exception:
            pass


def _append_paid_record_safe(
        week_start: str,
        week_end: str,
        username: str,
        gross: float,
        tax: float,
        net: float,
        paid_by: str,
        payment_mode: str = "net",
        display_tax: float | None = None,
        display_net: float | None = None,
):
    try:
        _ensure_payroll_headers()
        paid, _ = _is_paid_for_week(week_start, week_end, username)
        if paid:
            return

        payment_mode = (payment_mode or "net").strip().lower()
        if payment_mode not in {"gross", "net"}:
            payment_mode = "net"

        gross = round(float(gross or 0.0), 2)
        tax = round(float(tax or 0.0), 2)
        net = round(float(net or 0.0), 2)

        if display_tax is None:
            display_tax = 0.0 if payment_mode == "gross" else tax
        if display_net is None:
            display_net = gross if payment_mode == "gross" else net

        display_tax = round(float(display_tax or 0.0), 2)
        display_net = round(float(display_net or 0.0), 2)

        paid_at = datetime.now(TZ)

        if DATABASE_ENABLED:
            db.session.add(
                PayrollReport(
                    username=username,
                    week_start=datetime.strptime(week_start, "%Y-%m-%d").date(),
                    week_end=datetime.strptime(week_end, "%Y-%m-%d").date(),
                    gross=Decimal(str(gross)),
                    tax=Decimal(str(tax)),
                    net=Decimal(str(net)),
                    display_tax=Decimal(str(display_tax)),
                    display_net=Decimal(str(display_net)),
                    payment_mode=payment_mode,
                    paid_at=paid_at,
                    paid_by=paid_by,
                    paid="TRUE",
                    workplace_id=_session_workplace_id(),
                )
            )
            db.session.commit()
            return

        payroll_sheet.append_row([
            week_start,
            week_end,
            username,
            money(gross),
            money(tax),
            money(net),
            money(display_tax),
            money(display_net),
            payment_mode,
            paid_at.strftime("%Y-%m-%d %H:%M:%S"),
            paid_by,
            "TRUE",
            _session_workplace_id(),
        ])
    except Exception:
        if DATABASE_ENABLED:
            db.session.rollback()


def _patch_admin_only_endpoints(app):
    protected = [
        "db_view_employees", "db_view_workhours", "db_view_audit", "db_view_payroll",
        "db_view_onboarding", "db_view_locations", "db_view_settings",
        "db_upgrade_employees_table", "db_upgrade_onboarding_table",
    ]

    import_endpoints = set()
    if ENABLE_GOOGLE_SHEETS:
        import_endpoints = {
            "import_employees", "import_locations", "import_settings",
            "import_audit", "import_payroll", "import_onboarding", "import_workhours",
        }
        protected.extend(sorted(import_endpoints))

    for endpoint in protected:
        original = app.view_functions.get(endpoint)
        if not original:
            continue

        def wrapped(*args, _original=original, _endpoint=endpoint, **kwargs):
            gate = require_admin()
            if gate:
                return gate
            if _endpoint in import_endpoints and not ENABLE_GOOGLE_SHEETS:
                return {
                    "status": "error",
                    "message": "Google Sheets import is disabled. Set ENABLE_SHEETS_IMPORT=1 for one-time import.",
                }, 400
            return _original(*args, **kwargs)

        app.view_functions[endpoint] = wrapped


def init_runtime(app):
    _ensure_database_schema(app)

    global employees_sheet, work_sheet, payroll_sheet, onboarding_sheet, settings_sheet, audit_sheet, locations_sheet
    if DATABASE_ENABLED:
        employees_sheet = _EmployeesProxy("Employees")
        work_sheet = _WorkHoursProxy("WorkHours")
        payroll_sheet = _PayrollProxy("PayrollReports")
        onboarding_sheet = _OnboardingProxy("Onboarding")
        settings_sheet = _SettingsProxy("Settings")
        audit_sheet = _AuditProxy("AuditLog")
        locations_sheet = _LocationsProxy("Locations")


def finalize_app(app):
    _patch_admin_only_endpoints(app)


def init_app(app):
    """Backward-compatible bootstrap for earlier refactor revisions."""
    init_runtime(app)
    routes.register(app)
    finalize_app(app)
