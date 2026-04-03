# ===================== app.py (FULL - Premium UI + Dashboard + Desktop Wide Layout + Admin Payroll Edit + Paid + Overtime + Dark Mode + Live Admin Timers) =====================
# Notes:
# - NO reportlab usage in app runtime (Render-friendly).
# - Admin Payroll page printable in browser (Ctrl+P / Save as PDF).
# - Starter Form (Onboarding) is at /onboarding and viewable by Admin.
# - Profile shows onboarding details (text only) + change password.
# - Logout separated at bottom of desktop sidebar; on mobile it's a small icon in bottom nav.
#
# ✅ Added:
# - Desktop layout uses full screen width (no small centered UI).
# - Payroll: KPI strip, better numeric formatting, row emphasis, weekly net badge.
# - Overtime highlight > 8.5h/day.
# - Dark mode toggle (localStorage)
# - Admin dashboard: live timers for currently clocked-in employees.
# - Unpaid break deduction: subtract 0.5h on shifts >= 6h (so 8am–5pm => 8.5h recorded).
#
# ✅ Fix:
# - Escaped JS curly braces inside f-strings to avoid Render SyntaxError.

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
from urllib.parse import urlparse
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    from google.oauth2.service_account import Credentials as SACredentials
except Exception:
    SACredentials = None

try:
    import gspread
except Exception:
    gspread = None

from flask import jsonify
from flask import Flask, request, session, redirect, url_for, render_template_string, abort, make_response, send_file
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from datetime import date, timedelta

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

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy

# ================= PERFORMANCE: gspread caching (TTL) =================
# Google Sheets reads are slow + rate-limited. This monkeypatch caches common
# full-sheet reads for a short TTL and invalidates cache on writes.
#
# Configure with env vars:
#   SHEETS_CACHE_TTL_SECONDS (default 15)
#   SHEETS_CACHE_MAX_ENTRIES (default 256)
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
    # If gspread internals change, app still runs without caching.
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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _env_flag(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def _is_sqlite_url(url: str) -> bool:
    return str(url or "").strip().lower().startswith("sqlite:")


APP_ENV = os.environ.get("APP_ENV", os.environ.get("FLASK_ENV", "production")).strip().lower() or "production"
DEBUG_MODE = _env_flag("FLASK_DEBUG", default=False) or _env_flag("APP_DEBUG", default=False)
IS_PRODUCTION = APP_ENV == "production" and not DEBUG_MODE
DB_DEBUG_EXPORTS_ENABLED = _env_flag("DB_DEBUG_EXPORTS_ENABLED", default=not IS_PRODUCTION)
DESTRUCTIVE_ADMIN_CONFIRM_VALUE = os.environ.get("DESTRUCTIVE_ADMIN_CONFIRM_VALUE", "CONFIRM").strip() or "CONFIRM"
MAX_CLOCK_LOCATION_ACCURACY_M = float(
    os.environ.get("MAX_CLOCK_LOCATION_ACCURACY_M", os.environ.get("CLOCK_GEO_MAX_ACCURACY_METERS", "250")) or "250"
)
MAX_CLOCK_LOCATION_AGE_S = int(
    os.environ.get("MAX_CLOCK_LOCATION_AGE_S", os.environ.get("CLOCK_GEO_MAX_AGE_SECONDS", "180")) or "180"
)
ALLOWED_EMPLOYEE_ROLES = {"employee", "admin"}

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static",
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable must be set (do not use a default in production).")

app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "15")) * 1024 * 1024
app.config["PREFERRED_URL_SCHEME"] = "https" if IS_PRODUCTION else "http"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_env_flag("SESSION_COOKIE_SECURE", default=IS_PRODUCTION),
)


@app.after_request
def _set_security_headers(response):
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(self)")
    if IS_PRODUCTION:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DATABASE_ENABLED = (
        _env_flag("DATABASE")
        or _env_flag("USE_DATABASE")
        or _env_flag("DB_MIGRATION_MODE")
)
USE_DATABASE = DATABASE_ENABLED
DB_MIGRATION_MODE = DATABASE_ENABLED

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

if DATABASE_ENABLED and not DATABASE_URL:
    raise RuntimeError("DATABASE_ENABLED is on but DATABASE_URL is not set. Refusing to fall back to in-memory SQLite.")

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL if DATABASE_URL else "sqlite:///:memory:"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
if DATABASE_URL and not _is_sqlite_url(DATABASE_URL):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", "1800")),
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "10")),
    }

db = SQLAlchemy(app)
TZ = ZoneInfo(os.environ.get("APP_TZ", "Europe/London"))

# ================= DATABASE VIEW / IMPORT ROUTES =================

_DB_DEBUG_ALLOWED_COLUMNS = {
    "employees": [
        "id", "username", "role", "first_name", "last_name", "rate", "early_access", "active", "site",
        "site2", "workplace_id", "created_at"
    ],
    "workhours": [
        "id", "employee_email", "date", "clock_in", "clock_out", "hours", "pay", "in_site", "in_dist_m",
        "out_site", "out_dist_m", "workplace", "workplace_id", "created_at"
    ],
    "audit_logs": [
        "id", "action", "user_email", "actor", "username", "date_text", "details", "workplace_id",
        "created_at"
    ],
    "payroll_reports": [
        "id", "username", "week_start", "week_end", "gross", "tax", "net", "paid_at", "paid_by", "paid",
        "workplace_id", "created_at"
    ],
    "onboarding_records": [
        "id", "username", "workplace_id", "first_name", "last_name", "position", "employment_type",
        "right_to_work_uk", "start_date", "contract_accepted", "signature_datetime", "submitted_at"
    ],
    "locations": ["id", "site_name", "radius_meters", "active", "workplace_id", "created_at"],
    "workplace_settings": ["id", "workplace_id", "tax_rate", "currency_symbol", "company_name", "created_at"],
}


def _is_sensitive_debug_export_enabled() -> bool:
    return bool(DB_DEBUG_EXPORTS_ENABLED)


def _redact_value(column_name: str, value):
    col = str(column_name or "").strip().lower()
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        value = value.isoformat()

    secret_markers = (
        "password", "token", "secret", "hash", "bank", "sort_code", "sortcode",
        "national_insurance", "ni", "utr", "passport", "birth_cert", "share_code",
        "public_liability", "cscs_front_back", "selfie", "lat", "lon", "acc",
        "signature", "document", "geo", "medical_details",
    )
    if any(marker in col for marker in secret_markers):
        return "[REDACTED]"

    if col.endswith("_link") or col.endswith("_url"):
        return "[REDACTED]"

    if col in {"email", "phone", "phone_number", "emergency_contact_phone", "emergency_contact_phone_number"}:
        return "[REDACTED]"

    if col in {"bank_account_number", "sort_code", "national_insurance", "utr"}:
        return "[REDACTED]"

    if col in {"birth_date", "street_address", "address", "postcode", "city"}:
        return "[REDACTED]"

    if isinstance(value, str) and len(value) > 500:
        return value[:497] + "..."
    return value


def _rows_to_dicts(model, limit=200, allowed_columns=None):
    rows = model.query.limit(limit).all()
    out = []
    allowed = set(allowed_columns or [])
    for row in rows:
        item = {}
        for col in row.__table__.columns:
            if allowed and col.name not in allowed:
                continue
            val = getattr(row, col.name)
            item[col.name] = _redact_value(col.name, val)
        out.append(item)
    return out


# ================= DATABASE READ HELPERS =================

def get_locations():
    if USE_DATABASE:
        return Location.query.all()
    return _get_import_sheet("locations").get_all_records()


def get_settings():
    if USE_DATABASE:
        return WorkplaceSetting.query.all()
    return _get_import_sheet("settings").get_all_records()


def get_employees():
    if USE_DATABASE:
        return Employee.query.all()
    return _get_import_sheet("employees").get_all_records()


def get_employees_compat():
    out = []

    for rec in (get_employees() or []):
        if isinstance(rec, dict):
            username = str(rec.get("Username") or rec.get("username") or rec.get("email") or "").strip()
            first_name = str(rec.get("FirstName") or rec.get("first_name") or "").strip()
            last_name = str(rec.get("LastName") or rec.get("last_name") or "").strip()
            full_name = str(rec.get("Name") or rec.get("name") or "").strip()
            role = str(rec.get("Role") or rec.get("role") or "").strip()

            rate_raw = rec.get("Rate")
            if rate_raw in (None, ""):
                rate_raw = rec.get("rate")
            rate = "" if rate_raw in (None, "") else str(rate_raw).strip()

            early_access = str(rec.get("EarlyAccess") or rec.get("early_access") or "").strip()
            active = str(rec.get("Active") or rec.get("active") or "TRUE").strip() or "TRUE"
            workplace_id = str(
                rec.get("Workplace_ID") or rec.get("workplace_id") or rec.get("workplace") or "default"
            ).strip() or "default"
            site = str(rec.get("Site") or rec.get("site") or "").strip()
        else:
            username = str(getattr(rec, "username", None) or getattr(rec, "email", "") or "").strip()
            first_name = str(getattr(rec, "first_name", "") or "").strip()
            last_name = str(getattr(rec, "last_name", "") or "").strip()
            full_name = str(getattr(rec, "name", "") or "").strip()
            role = str(getattr(rec, "role", "") or "").strip()

            rate_val = getattr(rec, "rate", None)
            rate = "" if rate_val is None else str(rate_val).strip()

            early_access = str(getattr(rec, "early_access", "") or "").strip()
            active = str(getattr(rec, "active", "TRUE") or "TRUE").strip() or "TRUE"
            workplace_id = str(
                getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"
            ).strip() or "default"
            site = str(getattr(rec, "site", "") or "").strip()

        if (not first_name and not last_name) and full_name:
            parts = [p for p in full_name.split() if p]
            if parts:
                first_name = parts[0]
                last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        if not username:
            continue

        out.append({
            "Username": username,
            "FirstName": first_name,
            "LastName": last_name,
            "Role": role,
            "Rate": rate,
            "EarlyAccess": early_access,
            "Active": active,
            "Workplace_ID": workplace_id,
            "Site": site,
        })

    return out


# ================= FINAL DATABASE COMPAT HELPERS =================

def _employee_record_from_model(rec):
    if not rec:
        return None

    username = str(getattr(rec, "username", None) or getattr(rec, "email", "") or "").strip()
    full_name = str(getattr(rec, "name", "") or "").strip()
    first_name = str(getattr(rec, "first_name", "") or "").strip()
    last_name = str(getattr(rec, "last_name", "") or "").strip()

    if (not first_name and not last_name) and full_name:
        parts = [p for p in full_name.split() if p]
        if parts:
            first_name = parts[0]
            last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    rate_val = getattr(rec, "rate", None)
    rate_str = "" if rate_val in (None, "") else str(rate_val).strip()

    return {
        "Username": username,
        "Password": str(getattr(rec, "password", "") or "").strip(),
        "Role": str(getattr(rec, "role", "") or "").strip(),
        "Rate": rate_str,
        "EarlyAccess": str(getattr(rec, "early_access", "") or "").strip(),
        "Active": str(getattr(rec, "active", "TRUE") or "TRUE").strip() or "TRUE",
        "FirstName": first_name,
        "LastName": last_name,
        "Site": str(getattr(rec, "site", "") or "").strip(),
        "Workplace_ID": str(
            getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"
        ).strip() or "default",
        "OnboardingCompleted": str(getattr(rec, "onboarding_completed", "") or "").strip(),
    }


def _find_employee_record(username: str, workplace_id: str | None = None):
    target_user = (username or "").strip()
    target_wp = (workplace_id or _session_workplace_id() or "default").strip() or "default"
    allowed_wps = set(_workplace_ids_for_read(target_wp))

    if not target_user:
        return None

    if DB_MIGRATION_MODE:
        try:
            for rec in Employee.query.all():
                row = _employee_record_from_model(rec)
                if not row:
                    continue
                if (row.get("Username", "") or "").strip() != target_user:
                    continue
                row_wp = (row.get("Workplace_ID", "") or "default").strip()
                if row_wp not in allowed_wps:
                    continue
                stored_pw = str(row.get("Password", "") or "").strip()
                if stored_pw and not _password_is_hashed(stored_pw):
                    row = dict(row)
                    row["Password"] = _ensure_password_hash_for_user(target_user, stored_pw, workplace_id=target_wp)
                return row
        except Exception:
            pass

    try:
        for user in _get_import_sheet("employees").get_all_records():
            row_user = (user.get("Username") or "").strip()
            row_wp = (user.get("Workplace_ID") or "").strip() or "default"
            if row_user == target_user and row_wp in allowed_wps:
                stored_pw = str(user.get("Password", "") or "").strip()
                if stored_pw and not _password_is_hashed(stored_pw):
                    user = dict(user)
                    user["Password"] = _ensure_password_hash_for_user(target_user, stored_pw, workplace_id=target_wp)
                return user
    except Exception:
        pass

    return None


def _list_employee_records_for_workplace(workplace_id: str | None = None, include_inactive: bool = True):
    target_wp = (workplace_id or _session_workplace_id() or "default").strip() or "default"
    allowed_wps = set(_workplace_ids_for_read(target_wp))
    out = []

    if DB_MIGRATION_MODE:
        try:
            for rec in Employee.query.all():
                row = _employee_record_from_model(rec)
                if not row:
                    continue
                row_wp = (row.get("Workplace_ID", "") or "default").strip()
                if row_wp not in allowed_wps:
                    continue

                if not include_inactive:
                    active_raw = str(row.get("Active", "TRUE") or "TRUE").strip().lower()
                    if active_raw in ("false", "0", "no", "n", "off"):
                        continue

                out.append(row)
            return out
        except Exception:
            pass

    try:
        for user in _get_import_sheet("employees").get_all_records():
            row_wp = (user.get("Workplace_ID") or "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

            if not include_inactive:
                active_raw = str(user.get("Active", "TRUE") or "TRUE").strip().lower()
                if active_raw in ("false", "0", "no", "n", "off"):
                    continue

            out.append(user)
    except Exception:
        pass

    return out


def get_workhours_rows():
    if not DB_MIGRATION_MODE:
        return work_sheet.get_all_values()

    headers = ["Username", "Date", "ClockIn", "ClockOut", "Hours", "Pay", "Workplace_ID"]
    out = [headers]
    allowed_wps = set(_workplace_ids_for_read())

    try:
        rows = WorkHour.query.all()
    except Exception:
        return out

    def _to_time_str(v):
        if not v:
            return ""
        try:
            return v.strftime("%H:%M:%S")
        except Exception:
            return ""

    def _to_date_str(v):
        if not v:
            return ""
        try:
            return v.isoformat()
        except Exception:
            return str(v)

    items = []
    for rec in rows:
        username = str(
            getattr(rec, "employee_email", None)
            or getattr(rec, "username", None)
            or getattr(rec, "user_email", None)
            or ""
        ).strip()
        if not username:
            continue

        row_wp = str(
            getattr(rec, "workplace_id", None)
            or getattr(rec, "workplace", None)
            or "default"
        ).strip() or "default"

        allowed_wps = set(_workplace_ids_for_read())
        if row_wp not in allowed_wps:
            continue

        d = getattr(rec, "date", None)
        cin = getattr(rec, "clock_in", None)
        cout = getattr(rec, "clock_out", None)

        hours_val = ""
        pay_val = ""

        if cin and cout:
            try:
                raw_hours = max(0.0, (cout - cin).total_seconds() / 3600.0)
                hours_num = _round_to_half_hour(_apply_unpaid_break(raw_hours))
                pay_num = round(hours_num * float(_get_user_rate(username)), 2)
                hours_val = str(hours_num)
                pay_val = str(pay_num)
            except Exception:
                hours_val = ""
                pay_val = ""

        items.append([
            username,
            _to_date_str(d),
            _to_time_str(cin),
            _to_time_str(cout),
            hours_val,
            pay_val,
            row_wp,
        ])

    items.sort(key=lambda r: ((r[1] or ""), (r[0] or ""), (r[2] or "")))
    out.extend(items)
    return out


def get_payroll_rows():
    if not DB_MIGRATION_MODE:
        return payroll_sheet.get_all_values()

    headers = ["WeekStart", "WeekEnd", "Username", "Gross", "Tax", "Net", "PaidAt", "PaidBy", "Paid", "Workplace_ID"]
    out = [headers]
    allowed_wps = set(_workplace_ids_for_read())

    try:
        rows = PayrollReport.query.all()
    except Exception:
        return out

    def _date_str(v):
        if not v:
            return ""
        try:
            return v.isoformat()
        except Exception:
            return str(v)

    def _dt_str(v):
        if not v:
            return ""
        try:
            return v.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                return v.isoformat(sep=" ")
            except Exception:
                return str(v)

    items = []
    for rec in rows:
        row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip() or "default"

        allowed_wps = set(_workplace_ids_for_read())
        if row_wp not in allowed_wps:
            continue

        items.append([
            str(getattr(rec, "week_start", "") and _date_str(getattr(rec, "week_start")) or ""),
            str(getattr(rec, "week_end", "") and _date_str(getattr(rec, "week_end")) or ""),
            str(getattr(rec, "username", "") or "").strip(),
            "" if getattr(rec, "gross", None) is None else str(getattr(rec, "gross")),
            "" if getattr(rec, "tax", None) is None else str(getattr(rec, "tax")),
            "" if getattr(rec, "net", None) is None else str(getattr(rec, "net")),
            _dt_str(getattr(rec, "paid_at", None)),
            str(getattr(rec, "paid_by", "") or "").strip(),
            str(getattr(rec, "paid", "") or "").strip(),
            row_wp,
        ])

    items.sort(key=lambda r: ((r[0] or ""), (r[2] or "")))
    out.extend(items)
    return out


@app.route("/db-test")
def db_test():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate

    try:
        with app.app_context():
            tables = db.inspect(db.engine).get_table_names()
        return {"database": "connected", "tables": tables}
    except Exception as e:
        return {"database": "error", "message": str(e)}, 500


@app.route("/db/employees")
def db_view_employees():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(Employee, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["employees"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/workhours")
def db_view_workhours():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(WorkHour, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["workhours"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/audit")
def db_view_audit():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(AuditLog, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["audit_logs"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/payroll")
def db_view_payroll():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(PayrollReport, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["payroll_reports"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/onboarding")
def db_view_onboarding():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(
            _rows_to_dicts(OnboardingRecord, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["onboarding_records"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/locations")
def db_view_locations():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(Location, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["locations"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/settings")
def db_view_settings():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(
            _rows_to_dicts(WorkplaceSetting, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["workplace_settings"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.post("/db/upgrade-employees-table")
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


@app.post("/db/upgrade-onboarding-table")
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


@app.post("/import-employees")
def import_employees():
    gate = require_destructive_admin_post("import_employees")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        records = _get_import_sheet("employees").get_all_records()
        count = 0

        for rec in records:
            username = str(rec.get("Username", "")).strip()
            if not username:
                continue

            first_name = str(rec.get("FirstName", "")).strip()
            last_name = str(rec.get("LastName", "")).strip()
            full_name = (" ".join([first_name, last_name])).strip()

            role = str(rec.get("Role", "")).strip()
            workplace_id = str(rec.get("Workplace_ID", "")).strip() or "default"
            password = _normalize_password_hash_value(str(rec.get("Password", "")).strip())
            early_access = str(rec.get("EarlyAccess", "")).strip()
            active = str(rec.get("Active", "")).strip() or "TRUE"
            site = str(rec.get("Site", "")).strip()

            rate_raw = str(rec.get("Rate", "")).strip()
            rate_val = None
            if rate_raw != "":
                try:
                    rate_val = Decimal(rate_raw.replace("£", "").replace(",", "").strip())
                except Exception:
                    rate_val = None

            employee = Employee(
                email=username,
                name=full_name,
                role=role,
                workplace=workplace_id,
                created_at=None,
                username=username,
                first_name=first_name,
                last_name=last_name,
                password=password,
                rate=rate_val,
                early_access=early_access,
                active=active,
                workplace_id=workplace_id,
                site=site,
            )
            db.session.add(employee)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


# ================= REMAINING IMPORT ROUTES =================

from decimal import Decimal


def _pick(rec, *keys, default=""):
    for k in keys:
        if k in rec and rec.get(k) not in (None, ""):
            return rec.get(k)
    return default


def _to_str(v):
    return str(v).strip() if v is not None else ""


def _to_decimal(v, default=None):
    s = _to_str(v)
    if not s:
        return default
    s = s.replace("£", "").replace(",", "").strip()
    try:
        return Decimal(s)
    except Exception:
        return default


def _to_int(v, default=None):
    s = _to_str(v)
    if not s:
        return default
    try:
        return int(float(s))
    except Exception:
        return default


def _to_date(v):
    s = _to_str(v)
    if not s:
        return None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass

    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None


def _to_datetime(v):
    s = _to_str(v)
    if not s:
        return None

    candidates = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%H:%M:%S",
        "%H:%M",
    ]
    for fmt in candidates:
        try:
            parsed = datetime.strptime(s, fmt)
            if fmt in ("%H:%M:%S", "%H:%M"):
                return parsed
            return parsed
        except Exception:
            pass

    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


@app.post("/import-locations")
def import_locations():
    gate = require_destructive_admin_post("import_locations")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        Location.query.delete(synchronize_session=False)

        records = get_locations()
        count = 0

        for rec in records:
            site_name = _to_str(_pick(rec, "Site", "SiteName", "site_name", "Name"))
            if not site_name:
                continue

            row = Location(
                site_name=site_name,
                lat=_to_decimal(_pick(rec, "Lat", "Latitude", "lat")),
                lon=_to_decimal(_pick(rec, "Lon", "Lng", "Longitude", "lon")),
                radius_meters=_to_int(_pick(rec, "Radius", "RadiusMeters", "radius_meters")),
                active=_to_str(_pick(rec, "Active", "active", default="yes")),
                workplace_id=_to_str(_pick(rec, "Workplace_ID", "workplace_id", default="default")),
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-settings")
def import_settings():
    gate = require_destructive_admin_post("import_settings")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        WorkplaceSetting.query.delete(synchronize_session=False)

        records = _get_import_sheet("settings").get_all_records()
        count = 0

        for rec in records:
            workplace_id = _to_str(_pick(rec, "Workplace_ID", "workplace_id", default="default"))
            if not workplace_id:
                workplace_id = "default"

            row = WorkplaceSetting(
                workplace_id=workplace_id,
                tax_rate=_to_decimal(_pick(rec, "Tax_Rate", "TaxRate", "tax_rate")),
                currency_symbol=_to_str(_pick(rec, "Currency_Symbol", "Currency", "currency_symbol")),
                company_name=_to_str(_pick(rec, "Company_Name", "Company", "company_name")),
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-audit")
def import_audit():
    gate = require_destructive_admin_post("import_audit")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        AuditLog.query.delete(synchronize_session=False)

        records = _get_import_sheet("audit").get_all_records()
        count = 0

        for rec in records:
            action = _to_str(_pick(rec, "Action", "action"))
            user_email = _to_str(_pick(rec, "Username", "User", "Actor", "user_email"))

            if not action and not user_email:
                continue

            row = AuditLog(
                action=action or "unknown",
                user_email=user_email,
                created_at=_to_datetime(_pick(rec, "Timestamp", "Created_At", "DateTime", "created_at")),
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-payroll")
def import_payroll():
    gate = require_destructive_admin_post("import_payroll")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        records = _get_import_sheet("payroll").get_all_records()
        count = 0

        for rec in records:
            username = _to_str(_pick(rec, "Username", "username", "User"))
            if not username:
                continue

            row = PayrollReport(
                username=username,
                week_start=_to_date(_pick(rec, "Week_Start", "WeekStart", "week_start")),
                week_end=_to_date(_pick(rec, "Week_End", "WeekEnd", "week_end")),
                gross=_to_decimal(_pick(rec, "Gross", "Gross_Pay", "gross")),
                tax=_to_decimal(_pick(rec, "Tax", "Tax_Amount", "tax")),
                net=_to_decimal(_pick(rec, "Net", "Net_Pay", "net")),
                paid_at=_to_datetime(_pick(rec, "Paid_At", "PaidAt", "paid_at")),
                paid_by=_to_str(_pick(rec, "Paid_By", "PaidBy", "paid_by")),
                paid=_to_str(_pick(rec, "Paid", "paid")),
                workplace_id=_to_str(_pick(rec, "Workplace_ID", "workplace_id", default="default")),
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-onboarding")
def import_onboarding():
    gate = require_destructive_admin_post("import_onboarding")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        OnboardingRecord.query.delete(synchronize_session=False)

        records = _get_import_sheet("onboarding").get_all_records()
        count = 0

        for rec in records:
            username = _to_str(_pick(rec, "Username", "username"))
            if not username:
                continue

            phone_cc = _to_str(_pick(rec, "PhoneCountryCode", "phone_country_code"))
            phone_num = _to_str(_pick(rec, "PhoneNumber", "Phone", "phone_number", "phone"))
            ec_cc = _to_str(_pick(rec, "EmergencyContactPhoneCountryCode", "emergency_contact_phone_country_code"))
            ec_num = _to_str(
                _pick(rec, "EmergencyContactPhoneNumber", "EmergencyContactPhone", "Emergency_Contact_Phone",
                      "emergency_contact_phone_number"))

            street = _to_str(_pick(rec, "StreetAddress", "street_address"))
            city = _to_str(_pick(rec, "City", "city"))
            postcode = _to_str(_pick(rec, "Postcode", "postcode"))

            address_joined = ", ".join([x for x in [street, city, postcode] if x]).strip()
            phone_joined = " ".join([x for x in [phone_cc, phone_num] if x]).strip()
            ec_phone_joined = " ".join([x for x in [ec_cc, ec_num] if x]).strip()

            row = OnboardingRecord(
                username=username,
                workplace_id=_to_str(_pick(rec, "Workplace_ID", "workplace_id", default="default")),

                first_name=_to_str(_pick(rec, "FirstName", "First_Name", "first_name")),
                last_name=_to_str(_pick(rec, "LastName", "Last_Name", "last_name")),
                birth_date=_to_str(_pick(rec, "BirthDate", "Birth_Date", "birth_date")),

                phone_country_code=phone_cc,
                phone_number=phone_num,
                phone=phone_joined,

                email=_to_str(_pick(rec, "Email", "email")),

                street_address=street,
                city=city,
                postcode=postcode,
                address=address_joined,

                emergency_contact_name=_to_str(_pick(rec, "EmergencyContactName", "Emergency_Contact_Name")),
                emergency_contact_phone_country_code=ec_cc,
                emergency_contact_phone_number=ec_num,
                emergency_contact_phone=ec_phone_joined,

                medical_condition=_to_str(_pick(rec, "MedicalCondition", "Medical_Condition", "medical_condition")),
                medical_details=_to_str(_pick(rec, "MedicalDetails", "medical_details")),

                position=_to_str(_pick(rec, "Position", "position")),
                cscs_number=_to_str(_pick(rec, "CSCSNumber", "cscs_number")),
                cscs_expiry_date=_to_str(_pick(rec, "CSCSExpiryDate", "cscs_expiry_date")),
                employment_type=_to_str(_pick(rec, "EmploymentType", "employment_type")),
                right_to_work_uk=_to_str(_pick(rec, "RightToWorkUK", "right_to_work_uk")),
                national_insurance=_to_str(_pick(rec, "NationalInsurance", "national_insurance")),
                utr=_to_str(_pick(rec, "UTR", "utr")),
                start_date=_to_str(_pick(rec, "StartDate", "start_date")),

                bank_account_number=_to_str(_pick(rec, "BankAccountNumber", "bank_account_number")),
                sort_code=_to_str(_pick(rec, "SortCode", "sort_code")),
                account_holder_name=_to_str(_pick(rec, "AccountHolderName", "account_holder_name")),

                company_trading_name=_to_str(_pick(rec, "CompanyTradingName", "company_trading_name")),
                company_registration_no=_to_str(_pick(rec, "CompanyRegistrationNo", "company_registration_no")),

                date_of_contract=_to_str(_pick(rec, "DateOfContract", "date_of_contract")),
                site_address=_to_str(_pick(rec, "SiteAddress", "site_address")),

                passport_or_birth_cert_link=_to_str(
                    _pick(rec, "PassportOrBirthCertLink", "passport_or_birth_cert_link")),
                cscs_front_back_link=_to_str(_pick(rec, "CSCSFrontBackLink", "cscs_front_back_link")),
                public_liability_link=_to_str(_pick(rec, "PublicLiabilityLink", "public_liability_link")),
                share_code_link=_to_str(_pick(rec, "ShareCodeLink", "share_code_link")),

                contract_accepted=_to_str(_pick(rec, "ContractAccepted", "contract_accepted")),
                signature_name=_to_str(_pick(rec, "SignatureName", "signature_name")),
                signature_datetime=_to_str(
                    _pick(rec, "SignatureDateTime", "signature_datetime", "signature_date_time")),
                submitted_at=_to_str(_pick(rec, "SubmittedAt", "submitted_at")),
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-workhours")
def import_workhours():
    gate = require_destructive_admin_post("import_workhours")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        records = _get_import_sheet("workhours").get_all_records()
        count = 0

        for rec in records:
            username = _to_str(_pick(rec, "Username", "username", "User"))
            if not username:
                continue

            shift_date = _to_date(_pick(rec, "Date", "date"))
            clock_in_raw = _to_str(_pick(rec, "Clock In", "ClockIn", "Clock_In", "clock_in"))
            clock_out_raw = _to_str(_pick(rec, "Clock Out", "ClockOut", "Clock_Out", "clock_out"))

            clock_in_val = None
            clock_out_val = None

            if shift_date and clock_in_raw:
                for fmt in ("%H:%M:%S", "%H:%M"):
                    try:
                        t = datetime.strptime(clock_in_raw, fmt).time()
                        clock_in_val = datetime.combine(shift_date, t)
                        break
                    except Exception:
                        pass

            if shift_date and clock_out_raw:
                for fmt in ("%H:%M:%S", "%H:%M"):
                    try:
                        t = datetime.strptime(clock_out_raw, fmt).time()
                        clock_out_val = datetime.combine(shift_date, t)
                        break
                    except Exception:
                        pass

            _workplace_id = _to_str(_pick(rec, "Workplace_ID", "workplace_id", default="default")) or "default"

            row = WorkHour(
                employee_email=username,
                date=shift_date,
                clock_in=clock_in_val,
                clock_out=clock_out_val,
                workplace=_workplace_id,
                workplace_id=_workplace_id,
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

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
client = None
spreadsheet = None
employees_sheet = None
work_sheet = None
payroll_sheet = None
onboarding_sheet = None
settings_sheet = None
audit_sheet = None
locations_sheet = None
raw_employees_sheet = None
raw_work_sheet = None
raw_payroll_sheet = None
raw_onboarding_sheet = None
raw_settings_sheet = None
raw_audit_sheet = None
raw_locations_sheet = None

if ENABLE_GOOGLE_SHEETS:
    if gspread is None or SACredentials is None:
        raise RuntimeError("Google Sheets runtime/import is enabled but required Google libraries are not installed.")
    try:
        if creds_json:
            service_account_info = json.loads(creds_json)
            creds = SACredentials.from_service_account_info(service_account_info, scopes=SCOPES)
        else:
            CREDENTIALS_FILE = "credentials.json"
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError("credentials.json not found locally and GOOGLE_CREDENTIALS not set.")
            creds = SACredentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)

        client = gspread.authorize(creds)

        SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "").strip()
        if SPREADSHEET_ID:
            spreadsheet = client.open_by_key(SPREADSHEET_ID)
        else:
            spreadsheet = client.open("WorkHours")

        employees_sheet = spreadsheet.worksheet("Employees")
        work_sheet = spreadsheet.worksheet("WorkHours")
        payroll_sheet = spreadsheet.worksheet("PayrollReports")
        onboarding_sheet = spreadsheet.worksheet("Onboarding")
        try:
            settings_sheet = spreadsheet.worksheet("Settings")
        except Exception:
            settings_sheet = None
        try:
            audit_sheet = spreadsheet.worksheet("AuditLog")
        except Exception:
            audit_sheet = None
        try:
            locations_sheet = spreadsheet.worksheet("Locations")
        except Exception:
            locations_sheet = None
    except Exception as e:
        app.logger.warning("Google Sheets disabled: %s", e)
        client = None
        spreadsheet = None
        employees_sheet = None
        work_sheet = None
        payroll_sheet = None
        onboarding_sheet = None
        settings_sheet = None
        audit_sheet = None
        locations_sheet = None

# ================= GOOGLE DRIVE UPLOAD (OAUTH USER) =================
OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive"]

UPLOAD_FOLDER_ID = os.environ.get("ONBOARDING_DRIVE_FOLDER_ID", "").strip()
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "").strip()
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "").strip()
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "").strip()


def _make_oauth_flow():
    # Only used by /connect-drive and /oauth2callback
    if not (OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and OAUTH_REDIRECT_URI):
        raise RuntimeError(
            "Missing Drive OAuth env vars. Set OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, OAUTH_REDIRECT_URI."
        )

    client_config = {
        "web": {
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [OAUTH_REDIRECT_URI],
        }
    }

    return Flow.from_client_config(
        client_config,
        scopes=OAUTH_SCOPES,
        redirect_uri=OAUTH_REDIRECT_URI,
    )


# ---- Drive OAuth token storage (SERVER-SIDE) ----
# Avoid storing OAuth tokens in Flask sessions (client-side cookies by default).
# We keep tokens server-side in an encrypted file (recommended) or plaintext file as fallback.
#
# Env vars:
#   DRIVE_TOKEN_STORE_PATH (default: ./instance/drive_token.enc)
#   DRIVE_TOKEN_ENCRYPTION_KEY (recommended): urlsafe base64 32-byte key (Fernet).
#   DRIVE_TOKEN_JSON (optional): bootstrap token JSON (e.g., for migration), but prefer file store.
#   If DRIVE_TOKEN_ENCRYPTION_KEY is not set, the app derives an encryption key from SECRET_KEY.
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
    d = os.path.dirname(DRIVE_TOKEN_STORE_PATH)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def _fernet():
    if not Fernet:
        return None

    try:
        if DRIVE_TOKEN_ENCRYPTION_KEY:
            return Fernet(DRIVE_TOKEN_ENCRYPTION_KEY.encode("utf-8"))

        if SECRET_KEY:
            derived_key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode("utf-8")).digest())
            return Fernet(derived_key)
    except Exception:
        return None

    return None


def _save_drive_token(token_dict: dict):
    _ensure_instance_dir()
    payload = json.dumps(token_dict).encode("utf-8")
    f = _fernet()
    if not f:
        raise RuntimeError(
            "Encrypted Drive token storage is unavailable. Install cryptography and configure token encryption.")
    with open(DRIVE_TOKEN_STORE_PATH, "wb") as fp:
        fp.write(f.encrypt(payload))


def _load_drive_token() -> dict | None:
    # 1) Encrypted file only
    try:
        if os.path.exists(DRIVE_TOKEN_STORE_PATH):
            f = _fernet()
            if not f:
                return None
            blob = open(DRIVE_TOKEN_STORE_PATH, "rb").read()
            try:
                blob = f.decrypt(blob)
            except InvalidToken:
                return None
            return json.loads(blob.decode("utf-8"))
    except Exception:
        pass

    # 2) Optional env bootstrap (migration only)
    if DRIVE_TOKEN_ENV:
        try:
            return json.loads(DRIVE_TOKEN_ENV)
        except Exception:
            return None
    return None


def get_service_account_drive_service():
    try:
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        return None


def get_user_drive_service():
    token_data = _load_drive_token()
    if not token_data:
        return None

    creds_user = UserCredentials(**token_data)
    if creds_user.expired and creds_user.refresh_token:
        creds_user.refresh(Request())
        token_data["token"] = creds_user.token
        if creds_user.refresh_token:
            token_data["refresh_token"] = creds_user.refresh_token
        _save_drive_token(token_data)

    return build("drive", "v3", credentials=creds_user, cache_discovery=False)


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
CLOCK_SELFIE_MAX_BYTES = int(os.environ.get("CLOCK_SELFIE_MAX_BYTES", str(3 * 1024 * 1024)) or str(3 * 1024 * 1024))
CLOCK_SELFIE_DIR = os.path.join(BASE_DIR, "instance", "clock_selfies")
_ALLOWED_CLOCK_SELFIE_MIMES = {"image/jpeg", "image/png", "image/webp"}


def _detect_upload_kind(file_bytes: bytes):
    if file_bytes.startswith(b"%PDF-"):
        return (".pdf", "application/pdf")
    if file_bytes.startswith(b"\xff\xd8\xff"):
        return (".jpg", "image/jpeg")
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return (".png", "image/png")
    if len(file_bytes) >= 12 and file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
        return (".webp", "image/webp")
    return None


def _validate_upload_file(file_storage):
    if not file_storage or not getattr(file_storage, "filename", ""):
        raise RuntimeError("Missing upload file.")

    original = secure_filename(file_storage.filename or "upload") or "upload"
    _, ext = os.path.splitext(original)
    ext = (ext or "").lower()

    file_bytes = file_storage.read()
    file_storage.stream.seek(0)

    if not file_bytes:
        raise RuntimeError("Uploaded file is empty.")
    if len(file_bytes) > UPLOAD_MAX_BYTES:
        raise RuntimeError(f"File too large. Max size is {UPLOAD_MAX_BYTES // (1024 * 1024)}MB.")

    detected = _detect_upload_kind(file_bytes)
    if not detected:
        raise RuntimeError("Unsupported file type. Upload PDF, JPG, PNG, or WEBP only.")

    detected_ext, detected_mime = detected
    claimed_mime = (getattr(file_storage, "mimetype", "") or "application/octet-stream").lower()

    if ext and ext not in _ALLOWED_UPLOAD_EXTS:
        raise RuntimeError("Unsupported file extension. Upload PDF, JPG, PNG, or WEBP only.")
    if claimed_mime not in _ALLOWED_UPLOAD_MIMES:
        raise RuntimeError("Unsupported upload content type.")

    safe_base = os.path.splitext(original)[0] or "upload"
    safe_name = f"{safe_base}{detected_ext}"
    return file_bytes, detected_mime, safe_name


def upload_to_drive(file_storage, filename_prefix: str) -> str:
    # First try OAuth user Drive (connected via /connect-drive by master admin)
    drive_service = get_user_drive_service()

    # Fallback to service account only if no user token exists
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

    file_bytes, detected_mime, safe_name = _validate_upload_file(file_storage)
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
    os.makedirs(CLOCK_SELFIE_DIR, exist_ok=True)
    token = secrets.token_hex(8)
    final_name = f"{token}_{safe_name}"
    full_path = os.path.join(CLOCK_SELFIE_DIR, final_name)
    with open(full_path, "wb") as fh:
        fh.write(file_bytes)
    return url_for("view_clock_selfie", filename=final_name)


def _validate_clock_selfie_data(selfie_data_url: str):
    raw = (selfie_data_url or "").strip()
    if not raw:
        raise RuntimeError("Selfie is required before clocking in or out.")
    if not raw.startswith("data:image/") or "," not in raw:
        raise RuntimeError("Invalid selfie image data.")

    header, b64_data = raw.split(",", 1)
    declared_mime = header.split(";", 1)[0][5:].lower()
    if declared_mime not in _ALLOWED_CLOCK_SELFIE_MIMES:
        raise RuntimeError("Unsupported selfie format. Use JPG, PNG, or WEBP.")

    try:
        file_bytes = base64.b64decode(b64_data, validate=True)
    except (binascii.Error, ValueError):
        raise RuntimeError("Could not read selfie image.")

    if not file_bytes:
        raise RuntimeError("Captured selfie image is empty.")
    if len(file_bytes) > CLOCK_SELFIE_MAX_BYTES:
        raise RuntimeError(f"Selfie image is too large. Max size is {CLOCK_SELFIE_MAX_BYTES // (1024 * 1024)}MB.")

    detected = _detect_upload_kind(file_bytes)
    if not detected:
        raise RuntimeError("Unsupported selfie format. Use JPG, PNG, or WEBP.")
    detected_ext, detected_mime = detected
    if detected_mime not in _ALLOWED_CLOCK_SELFIE_MIMES:
        raise RuntimeError("Selfie must be an image file.")

    safe_name = f"selfie{detected_ext}"
    return file_bytes, detected_mime, safe_name


def _store_clock_selfie(selfie_data_url: str, username: str, action: str, now_dt: datetime) -> str:
    file_bytes, mime_type, safe_name = _validate_clock_selfie_data(selfie_data_url)
    stamp = now_dt.strftime("%Y%m%d_%H%M%S")
    prefix = f"{secure_filename(username or 'employee')}_{action}_{stamp}"
    try:
        return _upload_bytes_to_drive(file_bytes, prefix, safe_name, mime_type)
    except Exception:
        return _save_clock_selfie_locally(file_bytes, safe_name)


@app.get("/clock-selfie/<path:filename>")
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
@app.get("/manifest.webmanifest")
def manifest():
    return {
        "name": "WorkHours",
        "short_name": "WorkHours",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f6f8fb",
        "theme_color": "#ffffff",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }, 200, {"Content-Type": "application/manifest+json"}


VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
PWA_TAGS = """
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#ffffff">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<script>
(function(){
  function syncBottomNav(){
    var vv = window.visualViewport;
    var gap = 0;

    if (vv) {
      gap = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    }

    document.documentElement.style.setProperty('--bottom-nav-offset', gap + 'px');
  }

  function initMobileRail(){
    var shell = document.querySelector('.shell');
    var sidebar = shell ? shell.querySelector('.sidebar') : null;
    var oldBtn = document.getElementById('mobileRailToggle');

    if (window.innerWidth > 979 || !shell || !sidebar) {
      document.body.classList.remove('mobileRailClosed');
      if (oldBtn) oldBtn.remove();
      return;
    }

    var btn = oldBtn;
    if (!btn) {
      btn = document.createElement('button');
      btn.type = 'button';
      btn.id = 'mobileRailToggle';
      btn.setAttribute('aria-label', 'Toggle menu');
      document.body.appendChild(btn);
    }

    var storageKey = 'mobileRailClosed';

    function syncRail(){
      var closed = localStorage.getItem(storageKey) === '1';
      document.body.classList.toggle('mobileRailClosed', closed);
    }

    if (btn.dataset.bound !== '1') {
      btn.dataset.bound = '1';
      btn.addEventListener('click', function(e){
        e.preventDefault();
        e.stopPropagation();
        var closed = localStorage.getItem(storageKey) === '1';
        localStorage.setItem(storageKey, closed ? '0' : '1');
        syncRail();
      });
    }

    syncRail();
  }

  if (!window.__mobileRailSwipeBound) {
    window.__mobileRailSwipeBound = true;

    var touchStartX = 0;
    var touchStartY = 0;
    var touchLastX = 0;
    var trackingSwipe = false;
    var swipeMode = '';

    document.addEventListener('touchstart', function(e){
      if (window.innerWidth > 979) return;

      var shell = document.querySelector('.shell');
      var sidebar = shell ? shell.querySelector('.sidebar') : null;
      if (!shell || !sidebar) return;

      var t = e.touches && e.touches[0];
      if (!t) return;

      var target = e.target;
      if (target && target.closest('input, select, textarea, button, a, .tablewrap')) return;

      var closed = document.body.classList.contains('mobileRailClosed');

      trackingSwipe = false;
      swipeMode = '';
      touchStartX = t.clientX;
      touchStartY = t.clientY;
      touchLastX = t.clientX;

      if (closed) {
        if (t.clientX <= 18) {
          trackingSwipe = true;
          swipeMode = 'open';
        }
        return;
      }

      if (sidebar.contains(target) || t.clientX <= 90) {
        trackingSwipe = true;
        swipeMode = 'close';
      }
    }, { passive: true });

    document.addEventListener('touchmove', function(e){
      if (!trackingSwipe || window.innerWidth > 979) return;

      var t = e.touches && e.touches[0];
      if (!t) return;

      var dx = t.clientX - touchStartX;
      var dy = t.clientY - touchStartY;

      if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 8) {
        e.preventDefault();
      }

      touchLastX = t.clientX;
    }, { passive: false });

    document.addEventListener('touchend', function(){
      if (!trackingSwipe || window.innerWidth > 979) return;

      var dx = touchLastX - touchStartX;

      if (swipeMode === 'open' && dx > 45) {
        localStorage.setItem('mobileRailClosed', '0');
        document.body.classList.remove('mobileRailClosed');
      } else if (swipeMode === 'close' && dx < -45) {
        localStorage.setItem('mobileRailClosed', '1');
        document.body.classList.add('mobileRailClosed');
      }

      trackingSwipe = false;
      swipeMode = '';
      touchStartX = 0;
      touchStartY = 0;
      touchLastX = 0;
    }, { passive: true });
  }

  window.addEventListener('load', function(){
    syncBottomNav();
    initMobileRail();
  });

  window.addEventListener('resize', function(){
    syncBottomNav();
    initMobileRail();
  });

  window.addEventListener('pageshow', function(){
    syncBottomNav();
    initMobileRail();
    setTimeout(syncBottomNav, 120);
    setTimeout(syncBottomNav, 320);
  });

  window.addEventListener('orientationchange', function(){
    setTimeout(function(){
      syncBottomNav();
      initMobileRail();
    }, 250);
  });

  document.addEventListener('focusout', function(){
    setTimeout(syncBottomNav, 180);
  });

  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', syncBottomNav);
    window.visualViewport.addEventListener('scroll', syncBottomNav);
  }

  syncBottomNav();
  initMobileRail();
})();
</script>
"""
# ================= PREMIUM UI (CLEAN + STABLE) =================
STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root{
  --bg:#f7f9fc;
  --card:#ffffff;
  --text:#0f172a;
  --muted:#64748b;
  --border:rgba(15,23,42,.10);
  --shadow: 0 10px 28px rgba(15,23,42,.06);
  --shadow2: 0 16px 46px rgba(15,23,42,.10);
  --radius: 18px;

  /* Brand (finance blue) */
  --navy:#1e40af;
  --navy2:#1e3a8a;
  --navySoft:rgba(30,64,175,.08);

  --green:#16a34a;
  --red:#dc2626;
  --amber:#f59e0b;

  --h1: clamp(26px, 5vw, 38px);
  --h2: clamp(16px, 3vw, 20px);
  --small: clamp(12px, 2vw, 14px);
}

*{ box-sizing:border-box; }
html,body{ height:100%; }

body{
  margin:0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  background:
    radial-gradient(900px 520px at 18% 0%, rgba(10,42,94,.08) 0%, rgba(10,42,94,0) 60%),
    linear-gradient(180deg, rgba(255,255,255,.90), rgba(255,255,255,0) 45%),
    var(--bg);
  color: var(--text);
  padding: 16px 14px calc(90px + env(safe-area-inset-bottom)) 14px;
}

a{ color:inherit; text-decoration:none; }

h1{ font-size:var(--h1); margin:0; font-weight:700; letter-spacing:.2px; }
h2{ font-size:var(--h2); margin:0 0 8px 0; font-weight:600; }
.sub{ color:var(--muted); margin:6px 0 0 0; font-size:var(--small); line-height:1.35; font-weight:400; }

.card{
  min-width: 0;
  max-width: 100%;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  transition: transform .16s ease, box-shadow .16s ease, background .16s ease, border-color .16s ease;
}

/* Small badge */
.badge{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  padding:6px 12px;
  border-radius:999px;
  font-size:12px;
  font-weight:800;
  letter-spacing:.02em;
  background: rgba(239,246,255,.96);
  color: var(--navy);
  border:1px solid rgba(30,64,175,.16);
  box-shadow: 0 2px 8px rgba(15,23,42,.05);
}
.badge.admin{
  background: rgba(239,246,255,.96);
  color: #1d4ed8;
  border:1px solid rgba(59,130,246,.18);
}

/* Shell */
.shell{ max-width: 560px; margin: 0 auto; }
.sidebar{ display:none; }
.main{
  width: 100%;
  min-width: 0;   /* IMPORTANT: allows wide content to scroll instead of overflowing */
}

.topBrandBadge{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-height:38px;
  padding:8px 18px;
  border-radius:16px;
  font-size:13px;
  font-weight:800;
  letter-spacing:.04em;
  text-transform:uppercase;
  color:#dbeafe;
  border:1px solid rgba(147,197,253,.34);
  background:linear-gradient(180deg, rgba(29,78,216,.26), rgba(15,23,42,.78));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.12), 0 10px 24px rgba(2,6,23,.22);
  backdrop-filter:blur(10px);
  -webkit-backdrop-filter:blur(10px);
}
.topBrandBadge:hover{
  border-color:rgba(147,197,253,.42);
}

.topBarFixed{
  display:flex;
  align-items:center;
  justify-content:flex-end;
  gap:10px;
  margin-bottom:10px;
}

.topAccountWrap{
  position:relative;
}

.topAccountTrigger{
  width:40px;
  height:40px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  border-radius:999px;
  border:1px solid rgba(109,40,217,.10);
  background:rgba(255,255,255,.92);
  color:#6d28d9;
  cursor:pointer;
  box-shadow:0 8px 18px rgba(41,25,86,.08);
}

.topAccountTrigger svg{
  width:18px;
  height:18px;
}

.topAccountMenu{
  position:absolute;
  top:calc(100% + 8px);
  right:0;
  min-width:190px;
  padding:8px;
  border-radius:18px;
  border:1px solid rgba(109,40,217,.10);
  background:linear-gradient(180deg, rgba(255,255,255,.98), rgba(249,247,255,.98));
  box-shadow:0 18px 36px rgba(41,25,86,.14);
  display:none;
  z-index:700;
}

.topAccountWrap.open .topAccountMenu{
  display:block;
}

.topAccountMenuItem{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding:12px 14px;
  border-radius:14px;
  text-decoration:none;
  color:#1f2547;
  font-size:14px;
  font-weight:600;
}

.topAccountMenuItem:hover{
  background:rgba(109,40,217,.06);
}

.topAccountMenuItem.danger{
  color:#dc2626;
}

.topAccountMenuMark{
  color:#8b84a8;
  font-size:16px;
  line-height:1;
}

/* Header top */
.headerTop{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:12px;
  margin-bottom:14px;
}

/* KPI cards */
.kpiRow{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 12px;
}
.kpi{ padding:14px; }
.kpi .label{ font-size:var(--small); color:var(--muted); margin:0; font-weight:400; }
.kpi .value{ font-size: 28px; font-weight:700; margin: 6px 0 0 0; font-variant-numeric: tabular-nums; }

/* Graph */
.graphCard{
  margin-top: 12px;
  padding: 18px;
  border-radius: 24px;
  border: 1px solid rgba(56,189,248,.14);
  background:
    linear-gradient(180deg, #06142b 0%, #0a2342 55%, #0d2f52 100%);
  box-shadow:
    0 18px 40px rgba(2,6,23,.22),
    inset 0 1px 0 rgba(255,255,255,.04);
}

.graphTop{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:12px;
}

.graphTitle{
  font-weight:800;
  font-size: 20px;
  color: #f8fafc;
}

.graphCard .sub{
  color: rgba(191,219,254,.78);
}

.graphRange{
  color: #93c5fd;
  font-size: 13px;
  font-weight:700;
}

.graphShell{
  margin-top: 14px;
  padding: 14px 14px 10px 14px;
  border-radius: 22px;
  border: 1px solid rgba(56,189,248,.12);
  background:
    linear-gradient(180deg, rgba(3,14,33,.72), rgba(5,23,48,.62)),
    radial-gradient(circle at top right, rgba(34,211,238,.12), transparent 38%),
    radial-gradient(circle at top left, rgba(59,130,246,.12), transparent 42%);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.05),
    inset 0 -20px 60px rgba(2,132,199,.05);
}

.bars{
  height: 240px;
  display:flex;
  align-items:flex-end;
  justify-content:space-between;
  gap: 14px;
  padding: 8px 6px 0 6px;
  position: relative;
}

.barCol{
  flex: 1 1 0;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:flex-end;
  gap:8px;
  min-width: 0;
}

.barValue{
  font-size: 12px;
  font-weight: 800;
  color: #67e8f9;
  min-height: 16px;
  white-space: nowrap;
  text-shadow: 0 0 10px rgba(34,211,238,.18);
}

.barTrack{
  width: 100%;
  height: 180px;
  display:flex;
  align-items:flex-end;
  justify-content:center;
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.01)),
    linear-gradient(180deg, rgba(14,165,233,.06), rgba(14,165,233,0));
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.02);
  position: relative;
}

.bar{
  width: 72%;
  min-width: 24px;
  border-radius: 18px 18px 12px 12px;
  background: linear-gradient(180deg, #155eef 0%, #22d3ee 100%);
  box-shadow:
    0 14px 26px rgba(8,145,178,.22),
    0 0 18px rgba(34,211,238,.10);
}

.barLabels{
  display:flex;
  justify-content:space-between;
  gap:14px;
  margin-top: 8px;
  color: rgba(191,219,254,.88);
  font-weight:700;
  font-size: 13px;
}

.barLabels div{
  flex:1 1 0;
  text-align:center;
}

.graphMeta{
  margin-top: 14px;
  display:grid;
  grid-template-columns: repeat(3, 1fr);
  gap:10px;
}

@media (max-width: 900px){
  .graphMeta{
    grid-template-columns: 1fr;
  }
}

.graphStat{
  padding: 10px 12px;
  border-radius: 16px;
  border: 1px solid rgba(11,18,32,.08);
  background: rgba(255,255,255,.82);
}

.graphStat .k{
  font-size: 12px;
  color: var(--muted);
  font-weight:700;
}

.graphStat .v{
  margin-top: 4px;
  font-size: 18px;
  font-weight:800;
  color: rgba(15,23,42,.95);
}

.grossChartCard{
  margin-top: 12px;
  padding: 16px;
  border-radius: 24px;
  border: 1px solid rgba(109,40,217,.12);
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(246,243,255,.98));
  box-shadow: 0 16px 36px rgba(41,25,86,.08);
}

.grossChartSummaryRow{
  display:grid;
  grid-template-columns: repeat(2, minmax(0,1fr));
  gap:10px;
}

.grossSummaryBox{
  min-width:0;
  padding:14px 16px;
  border-radius:18px;
  border:1px solid rgba(109,40,217,.10);
  background: rgba(255,255,255,.92);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.9);
}

.grossSummaryLabel{
  font-size:12px;
  color:#6f6c85;
  font-weight:700;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}

.grossSummaryValue{
  margin-top:4px;
  font-size:18px;
  line-height:1.1;
  color:#1f2547;
  font-weight:800;
  font-variant-numeric: tabular-nums;
}

.grossSummaryDelta{
  margin-top:4px;
  font-size:12px;
  font-weight:800;
}

.grossSummaryDelta.up{ color:#15803d; }
.grossSummaryDelta.down{ color:#e11d48; }

.grossChartNav{
  margin-top:14px;
  display:flex;
  align-items:center;
  justify-content:center;
  gap:18px;
}

.grossChartArrow{
  width:24px;
  text-align:center;
  color:#5f5b7a;
  font-size:24px;
  line-height:1;
  user-select:none;
}

.grossChartRangeTitle{
  color:#1f172f;
  font-size:18px;
  font-weight:800;
  letter-spacing:-.01em;
}

.grossChartPlot{
  margin-top:10px;
  display:grid;
  grid-template-columns: 48px minmax(0,1fr);
  gap:10px;
  align-items:end;
}

.grossChartYAxis{
  height:230px;
  display:grid;
  grid-template-rows: repeat(6, 1fr);
}

.grossChartTick{
  display:flex;
  align-items:flex-end;
  justify-content:flex-end;
  padding-right:2px;
  color:#6b6f88;
  font-size:11px;
  font-weight:700;
  font-variant-numeric: tabular-nums;
}

.grossChartCanvas{
  position:relative;
  height:230px;
  border-bottom:1px solid rgba(109,40,217,.16);
}

.grossChartGridLine{
  position:absolute;
  left:0;
  right:0;
  border-top:1px dashed rgba(109,40,217,.18);
}

.grossChartBars{
  position:absolute;
  inset:0;
  display:flex;
  align-items:flex-end;
  justify-content:space-around;
  gap:12px;
  padding:0 8px 0 8px;
}

.grossChartBarCol{
  flex:1 1 0;
  min-width:0;
  height:100%;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:flex-end;
}

.grossChartBarWrap{
  width:min(52px, 100%);
  height:100%;
  display:flex;
  align-items:flex-end;
  justify-content:center;
}

.grossChartBar{
  width:100%;
  max-width:52px;
  background:#000;
  border-radius:0;
}

.grossChartBarLabel{
  margin-top:8px;
  color:#656b86;
  font-size:12px;
  font-weight:800;
}

@media (max-width: 700px){
  .grossChartCard{
    padding: 14px 12px 12px;
  }

  .grossSummaryBox{
    padding:12px 14px;
  }

  .grossSummaryLabel{
    font-size:11px;
  }

  .grossSummaryValue{
    font-size:16px;
  }

  .grossChartNav{
    gap:14px;
  }

  .grossChartRangeTitle{
    font-size:16px;
  }

  .grossChartPlot{
    grid-template-columns: 40px minmax(0,1fr);
    gap:8px;
  }

  .grossChartYAxis,
  .grossChartCanvas{
    height:200px;
  }

  .grossChartBars{
    gap:10px;
    padding:0 2px;
  }

  .grossChartBarWrap{
    width:min(38px, 100%);
  }

  .grossChartBar{
    max-width:38px;
  }

  .grossChartBarLabel{
    font-size:11px;
  }
}

.dashboardLower{
  margin-top: 12px;
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}

@media (max-width: 1100px){
  .dashboardLower{
    grid-template-columns: 1fr;
  }
}

.quickCard,
.activityCard,
.sideInfoCard{
  padding: 14px;
}

.quickCard{
  background:
    linear-gradient(180deg, rgba(239,246,255,.96), rgba(255,255,255,.96));
  border: 1px solid rgba(59,130,246,.14);
}

.activityCard{
  background:
    linear-gradient(180deg, rgba(245,243,255,.96), rgba(255,255,255,.96));
  border: 1px solid rgba(139,92,246,.14);
}

.sideInfoCard{
  background:
    linear-gradient(180deg, rgba(236,253,245,.96), rgba(255,255,255,.96));
  border: 1px solid rgba(34,197,94,.14);
}

.quickCard h2{
  color: #1d4ed8;
}

.activityCard h2{
  color: #7c3aed;
}

.sideInfoCard h2{
  color: #15803d;
}

.quickGrid{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap:10px;
  margin-top:10px;
}

.quickMini{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  padding:12px 12px;
  border-radius:16px;
  border:1px solid rgba(59,130,246,.12);
  background: rgba(255,255,255,.88);
  transition: transform .16s ease, box-shadow .16s ease;
}
.dashboardProgressRow{
  margin-top: 12px;
  padding: 12px;
  border-radius: 16px;
  border: 1px solid rgba(109,40,217,.10);
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,246,255,.96));
}

.dashboardProgressMeta{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  margin-bottom:8px;
  font-size:13px;
  font-weight:700;
  color:#5b5573;
}

.dashboardProgressMeta strong{
  color:#2a2540;
  font-weight:800;
}

.dashboardProgressBar{
  width:100%;
  height:10px;
  border-radius:999px;
  background: rgba(109,40,217,.10);
  overflow:hidden;
}

.dashboardProgressBar span{
  display:block;
  height:100%;
  border-radius:999px;
  background: linear-gradient(90deg, #7c3aed 0%, #5b21b6 100%);
  transition: width .25s ease;
}
.quickMini:hover{
  transform: translateY(-1px);
  box-shadow: var(--shadow2);
}

.quickMini .left{
  display:flex;
  align-items:center;
  gap:10px;
}

.quickMini .miniIcon{
  width:36px;
  height:36px;
  border-radius:12px;
  display:grid;
  place-items:center;
  color: var(--navy);
  background: rgba(30,64,175,.10);
  border:1px solid rgba(30,64,175,.14);
}

.quickMini .miniText{
  font-weight:800;
  font-size:14px;
  color: rgba(15,23,42,.92);
}

.activityList{
  margin-top:10px;
  display:flex;
  flex-direction:column;
  gap:10px;
}

.activityRow{
  display:grid;
  grid-template-columns: 92px 54px 54px 48px 64px;
  gap:8px;
  align-items:center;
  padding:10px 10px;
  border-radius:14px;
  border:1px solid rgba(139,92,246,.12);
  background: rgba(255,255,255,.88);
  font-size:12px;
  font-weight:700;
  color: rgba(15,23,42,.88);
  font-variant-numeric: tabular-nums;
}

.activityHead{
  color: var(--muted);
  font-size:11px;
  font-weight:800;
  background: transparent;
  border:none;
  padding:0 2px;
}

.activityEmpty{
  margin-top:10px;
  padding:14px;
  border-radius:14px;
  border:1px dashed rgba(11,18,32,.14);
  color: var(--muted);
  font-weight:600;
  background: rgba(255,255,255,.60);
}
.dashboardBottom{
  margin-top: 12px;
  display: grid;
  grid-template-columns: 1.35fr .85fr;
  gap: 12px;
  align-items: start;
}

@media (max-width: 1100px){
  .dashboardBottom{
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px){
  .dashboardBottom .activityCard{
    display:none;
  }
}

.sideInfoCard{
  padding: 14px;
  border-radius: 18px;
  border: 1px solid rgba(11,18,32,.08);
  background: rgba(255,255,255,.82);
}

.sideInfoList{
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sideInfoRow{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  padding:10px 12px;
  border-radius:14px;
  border:1px solid rgba(34,197,94,.12);
  background: rgba(255,255,255,.88);
}

.sideInfoLabel{
  font-size: 13px;
  font-weight: 700;
  color: rgba(15,23,42,.78);
}

.sideInfoValue{
  font-size: 18px;
  font-weight: 800;
  color: rgba(15,23,42,.96);
}
.weeklyEditTable{
  width:100%;
  min-width:100%;
  table-layout: fixed;
  border-collapse:separate;
  border-spacing:0;
  border-radius:18px;
  background: rgba(255,255,255,.94);
  border:1px solid rgba(96,165,250,.14);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.92),
    0 8px 18px rgba(15,23,42,.06);
}
.payrollEmployeeCard{
  width:100%;
  box-sizing:border-box;
  border: 1px solid rgba(96,165,250,.16);
  background: linear-gradient(180deg, rgba(248,251,255,.99), rgba(242,247,255,.98));
  box-shadow:
    0 20px 40px rgba(2,6,23,.16),
    inset 0 1px 0 rgba(255,255,255,.88);
}

.payrollEmployeeCard .tablewrap{
  width:100%;
  box-sizing:border-box;
  overflow-x:auto;
}

.payrollEmployeeCard .weeklyEditTable{
  width:100%;
}
.payrollSummaryBar{
  margin-top:12px;
  display:grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap:10px;
}

@media (max-width: 1100px){
  .payrollSummaryBar{
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}

.payrollSummaryItem{
  padding:12px 14px;
  border-radius:16px;
  border:1px solid rgba(11,18,32,.08);
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
  box-shadow: 0 4px 12px rgba(15,23,42,.05);
}

.payrollSummaryItem .k{
  font-size:12px;
  font-weight:800;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing:.04em;
}

.payrollSummaryItem .v{
  margin-top:4px;
  font-size:20px;
  font-weight:800;
  color: rgba(15,23,42,.96);
  line-height:1.15;
}

.payrollSummaryItem.net .v{
  color:#111827;
}

.payrollSummaryItem.paidat .v{
  font-size:16px;
}

.payrollEmployeeCard .payrollSummaryBar{
  margin-top: 10px;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
}

.payrollEmployeeCard .payrollSummaryItem{
  padding: 3px 5px;
  border-radius: 8px;
}

.payrollEmployeeCard .payrollSummaryItem .k{
  font-size: 8px;
}

.payrollEmployeeCard .payrollSummaryItem .v{
  font-size: 11px;
  line-height: 1;
}

.payrollEmployeeCard .payrollSummaryItem:nth-child(1),
.payrollEmployeeCard .payrollSummaryItem:nth-child(2),
.payrollEmployeeCard .payrollSummaryItem:nth-child(3),
.payrollEmployeeCard .payrollSummaryItem:nth-child(4),
.payrollEmployeeCard .payrollSummaryItem:nth-child(5){
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
  border-color: rgba(11,18,32,.08);
}

.payrollEmployeeCard .payrollSummaryItem:nth-child(1) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(2) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(3) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(4) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(5) .k{
  color: var(--muted);
}

.payrollEmployeeCard .payrollSummaryItem:nth-child(1) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(2) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(3) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(4) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(5) .v{
  color: rgba(15,23,42,.96);
}

.weeklyEditTable thead th{
  background: linear-gradient(180deg, rgba(231,240,255,.98), rgba(221,234,254,.98));
  color: rgba(15,23,42,.88);
  font-size:12px;
  font-weight:900;
  letter-spacing:.03em;
  text-transform:uppercase;
  padding:13px 10px;
  border-bottom:1px solid rgba(148,163,184,.18);
}

.weeklyEditTable tbody td{
  padding:14px 10px;
  border-bottom:1px solid rgba(191,219,254,.50);
  color: rgba(15,23,42,.92);
  font-size:14px;
  background: rgba(255,255,255,.92);
  vertical-align:middle;
}

.weeklyEditTable tbody tr:nth-child(even) td{
  background: rgba(248,251,255,.92);
}

.weeklyEditTable tbody tr:hover td{
  background: rgba(239,246,255,.86);
}

.weeklyEditTable td.num,
.weeklyEditTable th.num{
  text-align:center;
  font-variant-numeric: tabular-nums;
  font-feature-settings:"tnum";
}

.weeklyEditTable thead th:nth-child(3),
.weeklyEditTable thead th:nth-child(4),
.weeklyEditTable thead th:nth-child(5),
.weeklyEditTable thead th:nth-child(6),
.weeklyEditTable thead th:nth-child(7),
.weeklyEditTable tbody td:nth-child(3),
.weeklyEditTable tbody td:nth-child(4),
.weeklyEditTable tbody td:nth-child(5),
.weeklyEditTable tbody td:nth-child(6),
.weeklyEditTable tbody td:nth-child(7){
  text-align:center;
  font-variant-numeric: tabular-nums;
  font-feature-settings:"tnum";
}

.weeklyEditTable tbody td:first-child{
  font-weight:800;
  width:70px;
}

.weeklyEditTable tbody td:nth-child(2){
  color: var(--muted);
  width:120px;
}

.weeklyEditTable tbody td:empty::after{
  content:"";
}

.weeklyEditTable tbody tr:last-child td{
  border-bottom:none;
}
.sectionHead{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  margin-bottom:8px;
}

.sectionHeadLeft{
  display:flex;
  align-items:center;
  gap:10px;
}

.sectionIcon{
  width:36px;
  height:36px;
  border-radius:12px;
  display:grid;
  place-items:center;
  border:1px solid rgba(11,18,32,.08);
}

.sectionIcon svg{
  width:18px;
  height:18px;
}

.sectionBadge{
  font-size:12px;
  font-weight:800;
  padding:6px 10px;
  border-radius:999px;
  border:1px solid rgba(11,18,32,.08);
  background: rgba(255,255,255,.88);
  white-space:nowrap;
}

.activityCard .sectionIcon{
  background: rgba(139,92,246,.14);
  color: #7c3aed;
  border-color: rgba(139,92,246,.18);
}

.activityCard .sectionBadge{
  color: #7c3aed;
  border-color: rgba(139,92,246,.18);
  background: rgba(139,92,246,.08);
}

.sideInfoCard .sectionIcon{
  background: rgba(34,197,94,.14);
  color: #15803d;
  border-color: rgba(34,197,94,.18);
}

.sideInfoCard .sectionBadge{
  color: #15803d;
  border-color: rgba(34,197,94,.18);
  background: rgba(34,197,94,.08);
}

/* Menu */
.menu{ margin-top: 14px; padding: 12px; }

.adminGrid{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 6px;
}

.adminToolsShell{
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
  border: 1px solid rgba(15,23,42,.08);
  box-shadow: 0 18px 40px rgba(15,23,42,.08);
}

.adminToolsShell .adminGrid{
  margin-top: 0;
}

.adminGrid .menuItem{ margin-top: 0; height:100%; }
.adminToolCard{
  padding: 16px;
  border-radius: 18px;
  border: 1px solid rgba(15,23,42,.10);
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
  box-shadow: 0 10px 26px rgba(15,23,42,.08);
  display:flex;
  flex-direction:column;
  gap:12px;
  min-height: 132px;
  transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
.adminToolCard:hover{
  transform: translateY(-2px);
  box-shadow: 0 16px 34px rgba(15,23,42,.12);
}
.adminToolTop{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
}

.adminToolIcon{
  width: 50px;
  height: 50px;
  border-radius: 14px;
  display:flex;
  align-items:center;
  justify-content:center;
  border: 1px solid rgba(15,23,42,.08);
  overflow:hidden;
}
.adminToolIcon svg{
  width: 22px;
  height: 22px;
}
.adminToolIcon img{
  width: 26px;
  height: 26px;
  object-fit:contain;
  display:block;
}

.adminToolTitle{
  font-size: 16px;
  font-weight: 800;
  color: rgba(15,23,42,.94);
}
.adminToolSub{
  font-size: 13px;
  line-height: 1.4;
  color: var(--muted);
}

/* Different colors for admin cards */
.adminToolCard.payroll .adminToolIcon{
  background: linear-gradient(180deg, rgba(219,234,254,.95), rgba(191,219,254,.92));
  color: #1d4ed8;
  border-color: rgba(37,99,235,.16);
}
.adminToolCard.company .adminToolIcon{
  background: linear-gradient(180deg, rgba(220,252,231,.95), rgba(187,247,208,.92));
  color: #15803d;
  border-color: rgba(22,163,74,.18);
}
.adminToolCard.onboarding .adminToolIcon{
  background: linear-gradient(180deg, rgba(224,231,255,.95), rgba(199,210,254,.92));
  color: #4338ca;
  border-color: rgba(79,70,229,.18);
}
.adminToolCard.locations .adminToolIcon{
  background: linear-gradient(180deg, rgba(207,250,254,.95), rgba(165,243,252,.92));
  color: #0e7490;
  border-color: rgba(8,145,178,.18);
}
.adminToolCard.sites .adminToolIcon{
  background: linear-gradient(180deg, rgba(254,243,199,.95), rgba(253,230,138,.92));
  color: #b45309;
  border-color: rgba(217,119,6,.18);
}
.adminToolCard.employees .adminToolIcon{
  background: linear-gradient(180deg, rgba(252,231,243,.95), rgba(251,207,232,.92));
  color: #be185d;
  border-color: rgba(219,39,119,.16);
}
.adminToolCard.drive .adminToolIcon{
  background: linear-gradient(180deg, rgba(226,232,240,.95), rgba(203,213,225,.92));
  color: #0f172a;
  border-color: rgba(51,65,85,.18);
}
/* Admin lower section panels */
.adminSectionCard{
  padding: 14px;
  border-radius: 20px;
  border: 1px solid rgba(15,23,42,.10);
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
  box-shadow: 0 10px 26px rgba(15,23,42,.07);
}

.adminSectionHead{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:12px;
  flex-wrap:wrap;
  margin-bottom: 12px;
}

.adminSectionHeadLeft{
  display:flex;
  align-items:flex-start;
  gap:12px;
}

.adminSectionIcon{
  width: 46px;
  height: 46px;
  border-radius: 14px;
  display:grid;
  place-items:center;
  border: 1px solid rgba(15,23,42,.08);
  flex: 0 0 auto;
}
.adminSectionIcon svg{
  width: 22px;
  height: 22px;
}

.adminSectionIcon.clockin{
  background: linear-gradient(180deg, rgba(219,234,254,.95), rgba(191,219,254,.92));
  color: #1d4ed8;
  border-color: rgba(37,99,235,.16);
}
.adminSectionIcon.live{
  background: linear-gradient(180deg, rgba(220,252,231,.95), rgba(187,247,208,.92));
  color: #15803d;
  border-color: rgba(22,163,74,.18);
}

.adminSectionTitle{
  font-size: 16px;
  font-weight: 800;
  color: rgba(15,23,42,.95);
  margin: 0;
}

.adminSectionSub{
  font-size: 13px;
  line-height: 1.45;
  color: var(--muted);
  margin: 4px 0 0 0;
}

.adminFormRow{
  display:block;
  width:100%;
}
.adminFormRow .input{
  margin-top:0;
}
.adminActionBar{
  display:grid;
  grid-template-columns: 190px minmax(220px, 260px) 170px max-content;
  gap:10px;
  align-items:center;
  width: 100%;
  padding: 12px;
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(248,250,252,.95), rgba(241,245,249,.92));
  border: 1px solid rgba(15,23,42,.08);
}

.adminActionBar .input{
  width: 100%;
  height: 44px;
  border-radius: 14px;
  background: rgba(255,255,255,.96);
}

@media (max-width: 1200px){
  .adminActionBar{
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 700px){
  .adminActionBar{
    grid-template-columns: 1fr;
  }
}

.adminPrimaryBtn{
  height: 44px;
  min-width: 150px;
  padding: 0 18px;
  justify-self: start;
  border: none;
  border-radius: 14px;
  font-weight: 800;
  font-size: 14px;
  cursor: pointer;
  background: linear-gradient(180deg, rgba(30,64,175,1), rgba(37,99,235,.96));
  color: #fff;
  box-shadow: 0 10px 22px rgba(30,64,175,.18);
  transition: transform .16s ease, box-shadow .16s ease, filter .16s ease;
}
.adminPrimaryBtn:hover{
  transform: translateY(-1px);
  box-shadow: 0 14px 26px rgba(30,64,175,.22);
}
.adminPrimaryBtn:active{
  transform: translateY(0);
  filter: brightness(.98);
}

.adminHintChip{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding: 7px 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
  background: rgba(30,64,175,.08);
  border: 1px solid rgba(30,64,175,.14);
  color: var(--navy);
}
@media (max-width: 780px){
  .adminGrid{ grid-template-columns: 1fr; }
}

.menuItem{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding: 14px 14px;
  border-radius: 18px;
  background: rgba(255,255,255,.85);
  border: 1px solid rgba(11,18,32,.08);
  margin-top: 10px;
  transition: transform .16s ease, box-shadow .16s ease, background .16s ease, border-color .16s ease;
}
.menuItem:hover{ transform: translateY(-1px); box-shadow: var(--shadow2); }
.menuItem.active{
  background: var(--navySoft);
  border-color: rgba(30,64,175,.20);
}

.menuItem.nav-home .icoBox{
  background: linear-gradient(180deg, rgba(219,234,254,.95), rgba(191,219,254,.92));
  border-color: rgba(37,99,235,.16);
  color: #1d4ed8;
}

.menuItem.nav-clock .icoBox{
  background: linear-gradient(180deg, rgba(220,252,231,.95), rgba(187,247,208,.92));
  border-color: rgba(22,163,74,.18);
  color: #15803d;
}

.menuItem.nav-times .icoBox{
  background: linear-gradient(180deg, rgba(254,243,199,.95), rgba(253,230,138,.92));
  border-color: rgba(217,119,6,.18);
  color: #b45309;
}

.menuItem.nav-reports .icoBox{
  background: linear-gradient(180deg, rgba(224,231,255,.95), rgba(199,210,254,.92));
  border-color: rgba(79,70,229,.18);
  color: #4338ca;
}

.menuItem.nav-agreements .icoBox{
  background: linear-gradient(180deg, rgba(207,250,254,.95), rgba(165,243,252,.92));
  border-color: rgba(8,145,178,.18);
  color: #0e7490;
}

.menuItem.nav-profile .icoBox{
  background: linear-gradient(180deg, rgba(252,231,243,.95), rgba(251,207,232,.92));
  border-color: rgba(219,39,119,.16);
  color: #be185d;
}

.menuItem.nav-admin .icoBox{
  background: linear-gradient(180deg, rgba(226,232,240,.95), rgba(203,213,225,.92));
  border-color: rgba(51,65,85,.18);
  color: #0f172a;
}

.menuItem.nav-home.active{
  background: linear-gradient(180deg, rgba(37,99,235,.14), rgba(96,165,250,.08));
  border-color: rgba(37,99,235,.24);
}

.menuItem.nav-clock.active{
  background: linear-gradient(180deg, rgba(22,163,74,.14), rgba(74,222,128,.08));
  border-color: rgba(22,163,74,.24);
}

.menuItem.nav-times.active{
  background: linear-gradient(180deg, rgba(245,158,11,.14), rgba(251,191,36,.08));
  border-color: rgba(245,158,11,.24);
}

.menuItem.nav-reports.active{
  background: linear-gradient(180deg, rgba(79,70,229,.14), rgba(129,140,248,.08));
  border-color: rgba(79,70,229,.24);
}

.menuItem.nav-agreements.active{
  background: linear-gradient(180deg, rgba(8,145,178,.14), rgba(34,211,238,.08));
  border-color: rgba(8,145,178,.24);
}

.menuItem.nav-profile.active{
  background: linear-gradient(180deg, rgba(219,39,119,.14), rgba(244,114,182,.08));
  border-color: rgba(219,39,119,.22);
}

.menuItem.nav-admin.active{
  background: linear-gradient(180deg, rgba(51,65,85,.16), rgba(148,163,184,.08));
  border-color: rgba(51,65,85,.24);
}
.menuLeft{ display:flex; align-items:center; gap:12px; }
.icoBox{
  width: 44px; height: 44px;
  border-radius: 14px;
  background: rgba(255,255,255,.92);
  border: 1px solid rgba(11,18,32,.08);
  display:grid; place-items:center;
  color: var(--navy);
}
.icoBox svg{ width:22px; height:22px; }

.menuText{
  font-weight:700;
  font-size: 16px;
  letter-spacing:.1px;
  color: var(--navy);
}
.chev{
  font-size: 26px;
  color: rgba(30,64,175,.95);
  font-weight:700;
  opacity:.85;
}

/* Inputs */
.input{
  width:100%;
  padding: 12px 12px;
  border-radius: 16px;
  border: 1px solid rgba(11,18,32,.12);
  background: rgba(255,255,255,.92);
  font-size: 15px;
  outline:none;
  margin-top: 8px;
}
.input:focus{
  border-color: rgba(30,64,175,.45);
  box-shadow: 0 0 0 3px rgba(30,64,175,.10);
}

/* Buttons */
.btn{
  border:none;
  border-radius: 18px;
  padding: 14px 12px;
  font-weight:700;
  font-size: 15px;
  cursor:pointer;
  box-shadow: 0 10px 18px rgba(11,18,32,.08);
  transition: transform .16s ease, box-shadow .16s ease, filter .16s ease;
}
.btn:hover{ transform: translateY(-1px); filter: brightness(1.02); }
.btn:active{ transform: translateY(0px); filter: brightness(.98); }
.btnIn{ background: var(--green); color:#fff; }
.btnOut{ background: var(--red); color:#fff; }

.btnSoft{
  width:100%;
  border:none;
  border-radius: 18px;
  padding: 12px 12px;
  font-weight:700;
  font-size: 14px;
  cursor:pointer;
  background: rgba(30,64,175,.10);
  color: var(--navy);
  transition: transform .16s ease, box-shadow .16s ease;
}
.btnSoft:hover{ transform: translateY(-1px); box-shadow: var(--shadow2); }
/* Download CSV button styled like light export action */
.btnTiny.csvDownload{
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(244,248,255,.96));
  border-color: rgba(96,165,250,.18);
  color: rgba(29,78,216,.96);
  box-shadow:
    0 8px 16px rgba(15,23,42,.06),
    inset 0 1px 0 rgba(255,255,255,.85);
}
.btnTiny.csvDownload:hover{
  background: linear-gradient(180deg, rgba(255,255,255,.99), rgba(239,246,255,.98));
  border-color: rgba(59,130,246,.24);
}
.btnTiny{
  border: 1px solid rgba(15,23,42,.14);
  border-radius: 999px;
  padding: 6px 10px;
  font-weight:700;
  font-size: 12px;
  cursor:pointer;
  background: rgba(30,64,175,.08);
  color: rgba(30,64,175,1);
  white-space: nowrap;
}
.btnTiny:hover{
  background: rgba(30,64,175,.14);
  border-color: rgba(30,64,175,.35);
}
.btnTiny.paidDone{
  background: rgba(22,163,74,.15);
  border-color: rgba(22,163,74,.22);
  color: rgba(21,128,61,.95);
  cursor: default;
}
/* Payroll: unpaid "Paid" button = neutral */
.payrollSheet form .btnTiny:not(.paidDone),
.payrollSheet form .btnTiny.dark:not(.paidDone){
  background: transparent;
  border-color: rgba(15,23,42,.22);
  color: rgba(15,23,42,.72);
}

.payrollSheet form .btnTiny:not(.paidDone):hover,
.payrollSheet form .btnTiny.dark:not(.paidDone):hover{
  background: rgba(15,23,42,.06);
  border-color: rgba(15,23,42,.32);
  color: rgba(15,23,42,.86);
}
/* Messages */
.message{
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 18px;
  font-weight:700;
  text-align:center;
  background: rgba(22,163,74,.10);
  border: 1px solid rgba(22,163,74,.18);
}
.message.error{ background: rgba(220,38,38,.10); border-color: rgba(220,38,38,.20); }
#geoStatus{
  display:inline-flex;
  align-items:center;
  gap:8px;
  min-height:34px;
  padding:0 12px;
  background:#f8fafc;
  border:1px solid #e2e8f0;
  border-radius:999px;
  color:#334155;
  font-size:13px;
  font-weight:700;
  width:auto;
  max-width:100%;
}
/* Clock */
.clockCard{ margin-top: 12px; padding: 14px; }
.timerBig{
  font-weight:800;
  font-size:44px !important;
  margin-top: 6px;
  font-variant-numeric: tabular-nums;
}
.timerSub{ color: var(--muted); font-weight:500; font-size: 13px; margin-top: 6px; }
.actionRow{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 14px;
}

.tablewrap{
  margin-top:14px;
  width: 100%;
  max-width: 100%;
  min-width: 0;                 /* IMPORTANT inside flex layouts */
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  border-radius: 18px;
  border:1px solid rgba(11,18,32,.10);
  background: rgba(255,255,255,.65);
  backdrop-filter: blur(8px);
}
/* Ensure the table scrolls inside .tablewrap instead of widening the page */
.tablewrap table{
  width: max-content;
  min-width: 100%;
}

.tablewrap table{
  width:100%;
  border-collapse: collapse;
  min-width: 720px;
  background:#fff;
}

.tablewrap th,
.tablewrap td{
  padding: 10px 12px;
  border-bottom: 1px solid rgba(11,18,32,.08);
  text-align:left;
  font-size: 14px;
  vertical-align: middle;
  color: rgba(11,18,32,.88);
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}

.tablewrap th{
  position: sticky;
  top:0;
  background: rgba(248,250,252,.96);
  font-weight: 700;
  color: rgba(11,18,32,.95);
  letter-spacing:.2px;
  z-index: 2;
}

.tablewrap table tbody tr:nth-child(even){ background: rgba(11,18,32,.02); }
.tablewrap table tbody tr:hover{ background: rgba(30,64,175,.05); }

/* Numeric cells helper */
.num{
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
  white-space: nowrap;
}

/* Make action buttons (Mark Paid / etc.) consistent inside ANY tablewrap */
.tablewrap td:last-child button{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:6px;
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid rgba(15,23,42,.14);
  background: rgba(30,64,175,.08);
  color: rgba(30,64,175,1);
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: all .15s ease;
  white-space: nowrap;
}
/* Employee weekly tables (below): make ALL table inputs readable
   (Hours/Pay are <input class="input" ...> with NO type) */
.tablewrap input.input{
  font-weight: 800;
  color: rgba(2,6,23,.95);
  opacity: 1; /* prevent faded disabled text */
  -webkit-text-fill-color: rgba(2,6,23,.95); /* Safari/Chrome */
}
/* Employee weekly tables: center column headers (keep first column like Date left) */
.tablewrap table thead th:not(:first-child),
.tablewrap table thead td:not(:first-child){
  text-align: center;
}
/* Right-align numeric inputs inside numeric cells (Hours/Pay columns) */
.tablewrap td.num input.input{
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}
/* Numbers (hours/pay) easier to scan */
.tablewrap input[type="number"]{
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}
.tablewrap td:last-child button:hover,
.tablewrap td:last-child a:hover{
  background: rgba(30,64,175,.14);
  border-color: rgba(30,64,175,.35);
}
.workplacesTable{
  min-width: 860px;
}

@media (max-width: 700px){
  .workplacesTable{
    min-width: 100% !important;
    table-layout: auto !important;
  }

  .workplacesTable thead{
    display: none;
  }

  .workplacesTable,
  .workplacesTable tbody,
  .workplacesTable tr,
  .workplacesTable td{
    display: block;
    width: 100%;
  }

  .workplacesTable tr{
    padding: 12px;
    border-bottom: 1px solid rgba(11,18,32,.08);
    background: #fff;
  }

  .workplacesTable td{
    border: none;
    padding: 8px 0;
    text-align: left !important;
  }

  .workplacesTable td:last-child{
    padding-top: 10px;
  }
}

.employeesTable{
  width:100% !important;
  min-width:980px !important;
  table-layout:fixed !important;
  border-collapse:separate;
  border-spacing:0;
}

.employeesTable th,
.employeesTable td{
  padding:14px 16px !important;
  vertical-align:middle !important;
}

.employeesTable th{
  font-weight:800 !important;
}

.employeesTable th:nth-child(1),
.employeesTable td:nth-child(1){
  width:30% !important;
  text-align:left !important;
}

.employeesTable th:nth-child(2),
.employeesTable td:nth-child(2){
  width:20% !important;
  text-align:left !important;
}

.employeesTable th:nth-child(3),
.employeesTable td:nth-child(3){
  width:20% !important;
  text-align:left !important;
}

.employeesTable th:nth-child(4),
.employeesTable td:nth-child(4){
  width:15% !important;
  text-align:center !important;
}

.employeesTable th:nth-child(5),
.employeesTable td:nth-child(5){
  width:15% !important;
  text-align:right !important;
}

.employeesTable td:nth-child(2),
.employeesTable td:nth-child(3),
.employeesTable td:nth-child(4),
.employeesTable td:nth-child(5){
  white-space:nowrap;
}

@media (max-width: 700px){
  .employeesTable{
    min-width:100% !important;
    table-layout:auto !important;
  }

  .employeesTable thead{
    display:none;
  }

  .employeesTable,
  .employeesTable tbody,
  .employeesTable tr,
  .employeesTable td{
    display:block;
    width:100%;
  }

  .employeesTable tr{
    padding:12px;
    border-bottom:1px solid rgba(11,18,32,.08);
    background:#fff;
  }

  .employeesTable td{
    border:none;
    padding:8px 0 !important;
    text-align:left !important;
  }
}
.adminLiveTable{
  min-width: 1100px;
}

@media (max-width: 700px){
  .adminLiveTable{
    min-width: 100% !important;
    table-layout: auto !important;
  }

  .adminLiveTable thead{
    display: none;
  }

  .adminLiveTable,
  .adminLiveTable tbody,
  .adminLiveTable tr,
  .adminLiveTable td{
    display: block;
    width: 100%;
  }

  .adminLiveTable tr{
    padding: 12px;
    border-bottom: 1px solid rgba(11,18,32,.08);
    background: #fff;
  }

  .adminLiveTable td{
    border: none;
    padding: 8px 0;
    text-align: left !important;
  }

  .adminLiveTable td:last-child{
    padding-top: 10px;
  }

  .adminLiveTable form{
    width: 100%;
  }

  .adminLiveTable input.input{
    max-width: 100% !important;
    width: 100%;
  }
}

@media (max-width: 700px){
  .row2{
    display: grid !important;
    grid-template-columns: 1fr !important;
    gap: 10px !important;
  }

  .row2 .input,
  .row2 button,
  .row2 a{
    width: 100% !important;
    max-width: 100% !important;
  }

  .headerTop{
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .badge{
    max-width: 100%;
  }

  .adminGrid{
    grid-template-columns: 1fr !important;
  }

  .adminToolCard{
    min-height: auto;
  }

  .menuItem{
    align-items: center;
  }

  .tablewrap{
    border-radius: 14px;
  }
}
/* Status chips */
.chip{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight:700;
  border: 1px solid rgba(11,18,32,.12);
  background: rgba(255,255,255,.85);
  color: rgba(11,18,32,.74);
  white-space: nowrap;
}
.chip.ok{
  background: rgba(22,163,74,.15);
  border-color: rgba(22,163,74,.22);
  color: rgba(21,128,61,.95);
}
.chip.warn{
  background: rgba(234,179,8,.16);
  border-color: rgba(234,179,8,.20);
  color: rgba(146,64,14,.95);
}
.chip.bad{
  background: rgba(220,38,38,.12);
  border-color: rgba(220,38,38,.20);
  color: rgba(185,28,28,.98);
}

/* Avatar */
.avatar{
  width: 34px;
  height: 34px;
  border-radius: 999px;
  display:grid;
  place-items:center;
  font-weight:800;
  color: var(--navy);
  background: rgba(30,64,175,.08);
  border: 1px solid rgba(30,64,175,.14);
}

/* Week selector row */
.weekRow{
  margin-top: 10px;
  display:flex;
  flex-wrap: wrap;
  gap: 8px;
}
.weekPill{
  font-size: 12px;
  padding: 7px 10px;
  border-radius: 999px;
  font-weight:700;
  border: 1px solid rgba(11,18,32,.12);
  background: rgba(255,255,255,.75);
  color: rgba(11,18,32,.72);
}
.weekPill.active{
  background: var(--navySoft);
  border-color: rgba(30,64,175,.20);
  color: var(--navy);
}

/* KPI strip */
.kpiStrip{
  margin-top: 12px;
  display:grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.payrollTopGrid{
  margin-top: 12px;
  display: grid;
  grid-template-columns: 1.15fr .85fr;
  gap: 14px;
  align-items: stretch;
}

@media (max-width: 1100px){
  .payrollTopGrid{
    grid-template-columns: 1fr;
  }
}

.payrollFiltersCard,
.payrollChartCard{
  padding: 16px;
}

.payrollWeekBar{
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid rgba(129,140,248,.32);
  background:
    radial-gradient(circle at top right, rgba(56,189,248,.16), transparent 34%),
    linear-gradient(135deg, rgba(19,31,58,.96), rgba(34,44,79,.96));
  box-shadow:
    0 18px 34px rgba(2,6,23,.18),
    inset 0 1px 0 rgba(255,255,255,.08);
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:14px;
  flex-wrap:wrap;
}

.payrollWeekLead{
  min-width: 0;
  display:grid;
  gap:6px;
}

.payrollWeekBadge{
  display:inline-flex;
  align-items:center;
  width:max-content;
  max-width:100%;
  padding:6px 10px;
  border-radius:999px;
  border:1px solid rgba(125,211,252,.26);
  background: rgba(37,99,235,.18);
  color:#dbeafe;
  font-size:12px;
  font-weight:800;
  letter-spacing:.08em;
  text-transform:uppercase;
}

.payrollWeekHint{
  color: rgba(226,232,240,.84);
  font-size: 14px;
  line-height:1.45;
}

.payrollWeekControl{
  display:grid;
  gap:6px;
  min-width: 270px;
  max-width: 360px;
  flex:1 1 320px;
}

.payrollWeekLabel{
  color:#f8fafc;
  font-size:13px;
  font-weight:800;
  letter-spacing:.08em;
  text-transform:uppercase;
}

.payrollWeekBar .input{
  margin-top:0;
  background: rgba(255,255,255,.12);
  border: 1px solid rgba(191,219,254,.22);
  color:#f8fafc;
  font-weight:700;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.06);
}

.payrollWeekBar .input:focus{
  border-color: rgba(96,165,250,.7);
  box-shadow: 0 0 0 4px rgba(37,99,235,.18);
}


@media (max-width: 860px){
  .payrollWeekBar{
    padding: 14px;
  }

  .payrollWeekControl{
    min-width: 100%;
    max-width: 100%;
  }
}

.payrollFiltersCard{
  overflow: hidden;
}

.payrollFiltersCard .input,
.payrollFiltersCard .btnSoft,
.payrollFiltersCard input,
.payrollFiltersCard select{
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.payrollFiltersCard .row2{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap:10px;
}

.payrollFiltersCard .row2 > *{
  min-width:0;
}
.payrollDateRow > div{
  min-width: 0;
}

.payrollDateRow input[type="date"]{
  display: block;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
  -webkit-appearance: none;
  appearance: none;
}

@media (max-width: 600px){
  .payrollDateRow{
    grid-template-columns: 1fr !important;
  }
}

@media (max-width: 600px){
  .payrollFiltersCard{
    padding: 12px;
  }

  .payrollFiltersCard .row2{
    grid-template-columns: 1fr;
  }

  .payrollFiltersCard .input,
  .payrollFiltersCard input,
  .payrollFiltersCard select{
    font-size: 16px;
  }
}

.payrollFiltersCard{
  border: 1px solid rgba(96,165,250,.16);
  background:
    linear-gradient(180deg, rgba(248,251,255,.98) 0%, rgba(241,247,255,.98) 100%);
  box-shadow:
    0 18px 36px rgba(2,6,23,.16),
    inset 0 1px 0 rgba(255,255,255,.78);
}
.payrollFiltersCard .sub{
  color: rgba(71,85,105,.88);
}

.payrollFiltersCard .input,
.payrollFiltersCard input[type="date"],
.payrollFiltersCard select{
  margin-top:0;
  background: rgba(255,255,255,.12);
  border: 1px solid rgba(191,219,254,.22);
  color:#f8fafc;
  font-weight:700;
  box-shadow:none;
}

.payrollFiltersCard .input::placeholder,
.payrollFiltersCard input[type="date"]::placeholder{
  color: rgba(226,232,240,.72);
}

.payrollFiltersCard .input:focus,
.payrollFiltersCard input[type="date"]:focus,
.payrollFiltersCard select:focus{
  border-color: rgba(96,165,250,.7);
  box-shadow: 0 0 0 4px rgba(37,99,235,.18);
}

.payrollFiltersCard .input option,
.payrollFiltersCard select option,
.payrollWeekBar .input option{
  background:#0f172a;
  color:#f8fafc;
}

.payrollFiltersCard input[type="date"]::-webkit-calendar-picker-indicator{
  filter: invert(1) brightness(1.05);
  opacity:.92;
}

.payrollFiltersCard .btnSoft{
  background: linear-gradient(180deg, #3b82f6 0%, #2563eb 100%);
  border: 1px solid rgba(37,99,235,.24);
  color: #fff;
  box-shadow:
    0 12px 24px rgba(37,99,235,.20),
    inset 0 1px 0 rgba(255,255,255,.18);
}

.payrollFiltersCard .btnSoft:hover{
  filter: brightness(1.03);
  box-shadow:
    0 14px 28px rgba(37,99,235,.24),
    inset 0 1px 0 rgba(255,255,255,.20);
}

.payrollFiltersCard .kpiMini{
  border: 1px solid rgba(191,219,254,.95);
  background:
    linear-gradient(180deg, rgba(255,255,255,.98), rgba(244,248,255,.96));
  box-shadow:
    0 8px 18px rgba(15,23,42,.07),
    inset 0 1px 0 rgba(255,255,255,.88);
}

.payrollFiltersCard .kpiMini .k{
  color: rgba(71,85,105,.82);
}

.payrollFiltersCard .kpiMini .v{
  color: rgba(15,23,42,.96);
}

.payrollChartCard{
  background:
    linear-gradient(180deg, rgba(248,251,255,.98), rgba(242,247,255,.98));
  border: 1px solid rgba(96,165,250,.16);
  box-shadow:
    0 18px 36px rgba(2,6,23,.16),
    inset 0 1px 0 rgba(255,255,255,.78);
}

.payrollPieSection{
  margin-top: 10px;
  display:flex;
  justify-content:center;
  align-items:center;
  min-height: 360px;
}

.payrollPieWrap{
  position: relative;
  width: 330px;
  height: 330px;
}

.payrollPie{
  width: 330px;
  height: 330px;
  border-radius: 999px;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.28),
    0 18px 34px rgba(37,99,235,.16);
  border: 1px solid rgba(148,163,184,.14);
}

.payrollPieLabel{
  position: absolute;
  transform: translate(-50%, -50%);
  width: 82px;
  text-align: center;
  color: #ffffff;
  text-shadow: 0 1px 2px rgba(15,23,42,.38);
  pointer-events: none;
  line-height: 1.05;
}

.payrollPieLabel .pct{
  font-size: 15px;
  font-weight: 800;
}

.payrollPieLabel .amt{
  margin-top: 3px;
  font-size: 13px;
  font-weight: 800;
}

.payrollPieLabel .name{
  margin-top: 3px;
  font-size: 10px;
  font-weight: 700;
}

@media (max-width: 900px){
  .payrollPieSection{
    min-height: 300px;
  }

  .payrollPieWrap{
    width: 280px;
    height: 280px;
  }

  .payrollPie{
    width: 280px;
    height: 280px;
  }

  .payrollPieLabel{
  width: 74px;
}

.payrollPieLabel .pct{
  font-size: 13px;
}

.payrollPieLabel .amt{
  font-size: 11px;
}

.payrollPieLabel .name{
  font-size: 9px;
}
}

@media (max-width: 600px){
  .payrollPieSection{
    min-height: 260px;
  }

  .payrollPieWrap{
    width: 240px;
    height: 240px;
  }

  .payrollPie{
    width: 240px;
    height: 240px;
  }

  .payrollPieLabel{
  width: 64px;
}

.payrollPieLabel .pct{
  font-size: 11px;
}

.payrollPieLabel .amt{
  font-size: 10px;
}

.payrollPieLabel .name{
  font-size: 8px;
}
}


@media (max-width: 800px){
  .kpiStrip{ grid-template-columns: 1fr 1fr; }
}

@media (max-width: 480px){
  .kpiStrip{ grid-template-columns: 1fr; }
}

.kpiMini{
  padding: 12px;
  border-radius: 18px;
  border: 1px solid rgba(11,18,32,.10);
  background: rgba(255,255,255,.80);
}
.kpiMini .k{ font-size: 12px; color: var(--muted); font-weight:600; }
.kpiMini .v{ margin-top:6px; font-size: 18px; font-weight:800; font-variant-numeric: tabular-nums; }

/* Admin summary cards - same theme as dashboard chart */
.adminStats .adminStatCard{
  border-radius: 18px;
  border: 1px solid rgba(56,189,248,.14);
  box-shadow:
    0 18px 40px rgba(2,6,23,.22),
    inset 0 1px 0 rgba(255,255,255,.04);
  background:
    linear-gradient(180deg, #06142b 0%, #0a2342 55%, #0d2f52 100%);
}

.adminStats .adminStatCard .k{
  font-size: 12px;
  font-weight: 700;
  color: rgba(191,219,254,.82);
}

.adminStats .adminStatCard .v{
  font-size: 18px;
  font-weight: 900;
  color: #67e8f9;
  text-shadow: 0 0 10px rgba(34,211,238,.18);
}

/* keep all 4 cards the same dark chart theme */
.adminStats .adminStatCard.employees,
.adminStats .adminStatCard.clocked,
.adminStats .adminStatCard.locations,
.adminStats .adminStatCard.onboarding{
  background:
    linear-gradient(180deg, #06142b 0%, #0a2342 55%, #0d2f52 100%);
  border-color: rgba(56,189,248,.14);
}

.adminStats .adminStatCard.employees .k,
.adminStats .adminStatCard.employees .v,
.adminStats .adminStatCard.clocked .k,
.adminStats .adminStatCard.clocked .v,
.adminStats .adminStatCard.locations .k,
.adminStats .adminStatCard.locations .v,
.adminStats .adminStatCard.onboarding .k,
.adminStats .adminStatCard.onboarding .v{
  color: #67e8f9;
}

/* Weekly net badge */
.netBadge{
  display:inline-flex;
  align-items:center;
  gap:8px;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid rgba(30,64,175,.18);
  background: rgba(30,64,175,.10);
  color: var(--navy);
  font-weight:800;
  font-variant-numeric: tabular-nums;
}

/* Row emphasis if gross > 0 */
.rowHasValue{ background: rgba(30,64,175,.035) !important; }

/* Overtime highlight (thin left marker, no ugly full-row fill) */
.overtimeRow{
  background: transparent !important;
  box-shadow: inset 4px 0 0 rgba(245,158,11,.75);
}
.overtimeChip{
  display:inline-flex;
  align-items:center;
  padding: 4px 10px;
  border-radius:999px;
  font-size:12px;
  font-weight:800;
  background: rgba(245,158,11,.14);
  border: 1px solid rgba(245,158,11,.22);
  color: rgba(146,64,14,.95);
}

/* Contract box */
.contractBox{
  margin-top: 12px;
  padding: 12px;
  border-radius: 18px;
  border: 1px solid rgba(11,18,32,.10);
  background: rgba(248,250,252,.90);
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 13px;
  color: rgba(11,18,32,.88);
  line-height: 1.4;
}
.bad{ border: 1px solid rgba(220,38,38,.55) !important; box-shadow: 0 0 0 3px rgba(220,38,38,.10) !important; }
.badLabel{ color: rgba(220,38,38,.92) !important; font-weight:800 !important; }

/* Mobile layout: no left sidebar */
.bottomNav{
  display:block !important;
}

.safeBottom{
  display:block !important;
  height:0 !important;
}

#mobileRailToggle{
  display:none !important;
}

@media (max-width: 979px){
  body{
    padding:12px 12px 96px 12px !important;
  }

  .shell{
    width:100% !important;
    max-width:none !important;
    margin:0 !important;
    display:block !important;
  }

  .sidebar{
    display:none !important;
  }

  .main{
    min-width:0 !important;
    padding-right:0 !important;
  }

  .topBarFixed{
    position:sticky;
    top:0;
    z-index:120;
    padding:4px 0 10px;
    background:linear-gradient(180deg, rgba(245,247,252,.98), rgba(245,247,252,.85) 70%, rgba(245,247,252,0));
    backdrop-filter:blur(8px);
    -webkit-backdrop-filter:blur(8px);
  }
}

.navIcon.nav-home{ color:#1d4ed8; }
.navIcon.nav-clock{ color:#15803d; }
.navIcon.nav-times{ color:#b45309; }
.navIcon.nav-reports{ color:#4338ca; }
.navIcon.nav-admin{ color:#0f172a; }
.navIcon.nav-workplaces{ color:#0e7490; }
.navIcon.nav-logout{ color:rgba(220,38,38,.92); }

.navIcon.nav-home.active{
  background: linear-gradient(180deg, rgba(37,99,235,.14), rgba(96,165,250,.08));
}
.navIcon.nav-clock.active{
  background: linear-gradient(180deg, rgba(22,163,74,.14), rgba(74,222,128,.08));
}
.navIcon.nav-times.active{
  background: linear-gradient(180deg, rgba(245,158,11,.14), rgba(251,191,36,.08));
}
.navIcon.nav-reports.active{
  background: linear-gradient(180deg, rgba(79,70,229,.14), rgba(129,140,248,.08));
}
.navIcon.nav-admin.active{
  background: linear-gradient(180deg, rgba(51,65,85,.16), rgba(148,163,184,.08));
}
.navIcon.nav-workplaces.active{
  background: linear-gradient(180deg, rgba(8,145,178,.14), rgba(34,211,238,.08));
}
/* Desktop wide layout */
@media (min-width: 980px){
  body{ padding: 18px 18px 22px 18px; }
    .shell{
    max-width: none;
    width: calc(100vw - 36px);
    margin: 0 auto;
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr);
    gap: 16px;
    align-items: start;
  }
  .bottomNav{ display:none; }
    .sidebar{
    display:flex;
    flex-direction:column;
    gap: 8px;
    position: sticky;
    top: 18px;
    height: calc(100vh - 36px);
    overflow: hidden;
    padding: 12px;
    background: linear-gradient(180deg, rgba(255,255,255,.88), rgba(248,250,252,.92));
    border: 1px solid rgba(30,64,175,.10);
    border-radius: 16px;
    box-shadow: 0 10px 30px rgba(15,23,42,.08);
  }
  .sideScroll{
    overflow:auto;
    padding-right: 4px;
    flex: 1 1 auto;
  }
  .sideTitle{
    font-weight:800;
    font-size: 14px;
    color: rgba(11,18,32,.80);
    margin: 0 0 10px 2px;
  }
    .sideItem{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:10px;
    padding: 10px 11px;
    border-radius: 14px;
    background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(248,250,252,.96));
    border: 1px solid rgba(30,64,175,.08);
    margin-top: 8px;
    position: relative;
    overflow: hidden;
    transition: transform .16s ease, box-shadow .16s ease, background .16s ease, border-color .16s ease;
  }
    .sideItem:hover{
    transform: translateY(-1px);
    box-shadow: 0 12px 26px rgba(30,64,175,.14);
    border-color: rgba(30,64,175,.18);
  }

  .sideItem.active{
    background: linear-gradient(180deg, rgba(30,64,175,.16), rgba(59,130,246,.10));
    border-color: rgba(30,64,175,.26);
    box-shadow: 0 12px 30px rgba(30,64,175,.16);
  }
  .sideItem.active:before{
    content:"";
    position:absolute;
    left:0;
    top:10px;
    bottom:10px;
    width:4px;
    border-radius: 999px;
    background: linear-gradient(180deg, rgba(30,64,175,1), rgba(30,64,175,.55));
    box-shadow: 0 0 0 3px rgba(30,64,175,.10);
  }
  .sideLeft{ display:flex; align-items:center; gap:12px; }
    .sideText{ font-weight:800; font-size: 14px; letter-spacing:.1px; }

  .sideIcon{
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(239,246,255,.95), rgba(219,234,254,.90));
  border: 1px solid rgba(30,64,175,.12);
  display:flex;
  align-items:center;
  justify-content:center;
  color: var(--navy);
  overflow:hidden;
}
.sideIcon svg{
  width: 20px;
  height: 20px;
}
.sideIcon img{
  width: 22px;
  height: 22px;
  object-fit:contain;
  display:block;
}

    /* Different colors for each sidebar item */
  .sideItem.nav-home .sideIcon{
    background: linear-gradient(180deg, rgba(219,234,254,.95), rgba(191,219,254,.92));
    border-color: rgba(37,99,235,.16);
    color: #1d4ed8;
  }

  .sideItem.nav-clock .sideIcon{
    background: linear-gradient(180deg, rgba(220,252,231,.95), rgba(187,247,208,.92));
    border-color: rgba(22,163,74,.18);
    color: #15803d;
  }

  .sideItem.nav-times .sideIcon{
    background: linear-gradient(180deg, rgba(254,243,199,.95), rgba(253,230,138,.92));
    border-color: rgba(217,119,6,.18);
    color: #b45309;
  }

  .sideItem.nav-reports .sideIcon{
    background: linear-gradient(180deg, rgba(224,231,255,.95), rgba(199,210,254,.92));
    border-color: rgba(79,70,229,.18);
    color: #4338ca;
  }

  .sideItem.nav-agreements .sideIcon{
    background: linear-gradient(180deg, rgba(207,250,254,.95), rgba(165,243,252,.92));
    border-color: rgba(8,145,178,.18);
    color: #0e7490;
  }

  .sideItem.nav-profile .sideIcon{
    background: linear-gradient(180deg, rgba(252,231,243,.95), rgba(251,207,232,.92));
    border-color: rgba(219,39,119,.16);
    color: #be185d;
  }

  .sideItem.nav-admin .sideIcon{
    background: linear-gradient(180deg, rgba(226,232,240,.95), rgba(203,213,225,.92));
    border-color: rgba(51,65,85,.18);
    color: #0f172a;
  }

  .sideItem.nav-home.active{
    background: linear-gradient(180deg, rgba(37,99,235,.14), rgba(96,165,250,.08));
    border-color: rgba(37,99,235,.24);
  }

  .sideItem.nav-clock.active{
    background: linear-gradient(180deg, rgba(22,163,74,.14), rgba(74,222,128,.08));
    border-color: rgba(22,163,74,.24);
  }

  .sideItem.nav-times.active{
    background: linear-gradient(180deg, rgba(245,158,11,.14), rgba(251,191,36,.08));
    border-color: rgba(245,158,11,.24);
  }

  .sideItem.nav-reports.active{
    background: linear-gradient(180deg, rgba(79,70,229,.14), rgba(129,140,248,.08));
    border-color: rgba(79,70,229,.24);
  }

  .sideItem.nav-agreements.active{
    background: linear-gradient(180deg, rgba(8,145,178,.14), rgba(34,211,238,.08));
    border-color: rgba(8,145,178,.24);
  }

  .sideItem.nav-profile.active{
    background: linear-gradient(180deg, rgba(219,39,119,.14), rgba(244,114,182,.08));
    border-color: rgba(219,39,119,.22);
  }

  .sideItem.nav-admin.active{
    background: linear-gradient(180deg, rgba(51,65,85,.16), rgba(148,163,184,.08));
    border-color: rgba(51,65,85,.24);
  }

  .sideDivider{
    height: 1px;
    background: rgba(11,18,32,.12);
    margin: 10px 0 6px 0;
  }

  .logoutBtn{
    margin-top: 2px;
    background: rgba(220,38,38,.08);
    border-color: rgba(220,38,38,.12);
  }
  .logoutBtn .sideIcon, .logoutBtn .chev{ color: rgba(220,38,38,.95); }
  .logoutBtn .sideText{ color: rgba(220,38,38,.95); }
}

/* ================= PAYROLL SHEET (condensed week design) ================= */
.payrollWrap{
  margin-top:16px;
  width:100%;
  max-width:100%;
  min-width:0;
  background: linear-gradient(180deg, rgba(248,251,255,.99), rgba(243,248,255,.99));
  border:1px solid rgba(96,165,250,.16);
  border-radius:22px;
  overflow-x:auto;
  overflow-y:hidden;
  -webkit-overflow-scrolling:touch;
  box-shadow:
    0 20px 40px rgba(2,6,23,.18),
    inset 0 1px 0 rgba(255,255,255,.86);
  padding-right:18px;
  box-sizing:border-box;
}

.payrollSheet{
  width:100%;
  min-width:0;
  table-layout:fixed;
  border-collapse:separate;
  border-spacing:0;
  background:transparent;
}

.payrollSheet th,
.payrollSheet td{
  border:none;
  border-bottom:1px solid rgba(191,219,254,.56);
  font-variant-numeric:tabular-nums;
  font-feature-settings:"tnum" 1;
}

.payrollSheet thead th{
  position:sticky;
  top:0;
  z-index:5;
  background: linear-gradient(180deg, rgba(231,240,255,.98), rgba(221,234,254,.98));
  color:rgba(15,23,42,.86);
  font-size:13px;
  font-weight:900;
  letter-spacing:.02em;
  text-transform:uppercase;
  padding:16px 12px;
  white-space:nowrap;
  border-bottom:1px solid rgba(148,163,184,.22);
  text-align:left;
}

.payrollSheet thead th:not(:first-child){
  text-align:center;
}

.payrollSheet tbody td{
  padding:12px 10px;
  font-size:14px;
  line-height:1.35;
  vertical-align:top;
  background:rgba(255,255,255,.92);
  color:rgba(2,6,23,.92);
}

.payrollSheet tbody tr:nth-child(even) td{
  background:rgba(248,251,255,.92);
}

.payrollSheet tbody tr:hover td{
  background:rgba(239,246,255,.95);
}

.payrollSheet tbody tr.is-selected td{
  background:rgba(224,242,254,.92);
}

.payrollSheet tbody tr:hover td:first-child,
.payrollSheet tbody tr.is-selected td:first-child{
  box-shadow:inset 3px 0 0 rgba(37,99,235,.34);
}

/* employee */
.payrollEmpCell,
.payrollSheet thead th:first-child,
.payrollSheet tbody td:first-child{
  width:156px;
  min-width:156px;
  max-width:156px;
}

.payrollSheet thead th:first-child{
  position: sticky;
  left: 0;
  z-index: 9;
  background: linear-gradient(180deg, rgba(226,236,254,.99), rgba(216,230,252,.99));
  box-shadow: 10px 0 18px rgba(15,23,42,.08);
}

.payrollSheet tbody td:first-child{
  position: sticky;
  left: 0;
  z-index: 4;
  background: linear-gradient(180deg, rgba(247,250,255,.98), rgba(242,247,255,.98));
  box-shadow: 10px 0 18px rgba(15,23,42,.08);
}

.payrollSheet tbody tr:hover td:first-child{
  background: rgba(239,246,255,.98);
}

.payrollSheet tbody tr.is-selected td:first-child{
  background: rgba(224,242,254,.96);
}

.payrollEmpCell .emp{
  display:block;
  font-weight:800;
  line-height:1.2;
}

.payrollSheet .emp{
  display:block;
  width:100%;
  min-width:0;
  font-size:14px;
  font-weight:900;
  line-height:1.18;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
  color: rgba(15,23,42,.96);
}

.payrollSheet .empSub{
  display:block;
  margin-top:4px;
  font-size:12px;
  font-weight:700;
  color:rgba(71,85,105,.72);
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}

/* condensed day cells */
.payrollDayCell{
  width:92px;
  min-width:92px;
  max-width:92px;
  text-align:left;
}
.payrollDayStack{
  display:flex;
  flex-direction:column;
  gap:4px;
  min-height:74px;
  justify-content:flex-start;
  padding:0;
  border-radius:0;
  background:transparent;
  border:none;
  box-shadow:none;
}

.payrollDayLine{
  min-height:20px;
  display:flex;
  align-items:center;
}

.payrollDayLine + .payrollDayLine{
  padding-top:0;
  border-top:none;
}

.payrollDayHours{
  min-height:20px;
  display:flex;
  align-items:center;
  margin-top:auto;
  padding-top:4px;
  font-size:13px;
  font-weight:900;
  color:#0f766e;
}

.payrollDayEmpty{
  min-height:74px;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:20px;
  font-weight:700;
  color:rgba(100,116,139,.55);
  border-radius:0;
  border:none;
  background:transparent;
}

.payrollDayCellOT{
  background:rgba(255,247,237,.92) !important;
  box-shadow:inset 0 0 0 1px rgba(251,191,36,.20);
  border-radius:12px;
}

.payrollSheet tbody tr:hover td.payrollDayCellOT,
.payrollSheet tbody tr.is-selected td.payrollDayCellOT{
  background:rgba(245,158,11,.14) !important;
}

/* time inputs */
.payrollSheet input:disabled,
.payrollSheet select:disabled{
  background:transparent;
}

.payrollSheet input[type="time"]{
  font-weight:900;
  color:rgba(15,23,42,.98);
  letter-spacing:.01em;
}

.payrollSheet input[type="time"]:disabled{
  opacity:1;
  -webkit-text-fill-color:rgba(15,23,42,.98);
}

.payrollSheet input.payrollTimeInput,
.payrollTimeInput{
  width:100%;
  min-width:0;
  max-width:none;
  height:22px;
  line-height:22px;
  padding:0 2px 0 0;
  border:none;
  border-radius:8px;
  background:transparent;
  box-shadow:none;
  font-size:13px;
  font-weight:900;
  text-align:left;
  color:rgba(15,23,42,.94);
  outline:none;
  appearance:none;
  -webkit-appearance:none;
}

.payrollSheet input.payrollTimeInput::-webkit-calendar-picker-indicator,
.payrollSheet input.payrollTimeInput::-webkit-clear-button,
.payrollSheet input.payrollTimeInput::-webkit-inner-spin-button,
.payrollSheet input.payrollTimeInput::-webkit-outer-spin-button{
  display:none !important;
  -webkit-appearance:none !important;
  opacity:0 !important;
}

.payrollSheet input.payrollTimeInput[value=""]{
  color:transparent !important;
}

.payrollSheet input.payrollTimeInput[value=""]::-webkit-datetime-edit,
.payrollSheet input.payrollTimeInput[value=""]::-webkit-date-and-time-value{
  color:transparent !important;
}

.payrollSheet input.payrollTimeInput:focus{
  color:rgba(15,23,42,.94) !important;
  background:rgba(30,64,175,.06) !important;
  box-shadow:inset 0 0 0 1px rgba(30,64,175,.18) !important;
}

.payrollSheet input.payrollTimeInput:focus::-webkit-datetime-edit,
.payrollSheet input.payrollTimeInput:focus::-webkit-date-and-time-value{
  color:rgba(15,23,42,.94) !important;
}

/* summary columns */
.payrollSummaryTotal{
  width:72px;
  min-width:72px;
  max-width:72px;
  text-align:center !important;
}

.payrollSummaryMoney{
  width:106px;
  min-width:106px;
  max-width:106px;
  text-align:right !important;
}

.payrollSheet td.payrollSummaryTotal,
.payrollSheet td.payrollSummaryMoney{
  vertical-align:middle;
  font-weight:900;
}

.payrollSheet thead th.payrollSummaryTotal,
.payrollSheet thead th.payrollSummaryMoney,
.payrollSheet td.payrollSummaryTotal,
.payrollSheet td.payrollSummaryMoney{
  background-image: linear-gradient(180deg, rgba(240,247,255,.96), rgba(233,243,255,.96));
}

.payrollSheet td.payrollSummaryMoney{
  color: rgba(15,23,42,.98);
}

/* states */
.payrollSheet td.net{
  background:transparent;
  color:rgba(2,6,23,.92);
  font-weight:900;
}

.payrollSheet tbody tr:hover td.net,
.payrollSheet tbody tr.is-selected td.net{
  background:transparent;
}

.payrollSheet td.net.paidNetCell{
  background:transparent !important;
  color:rgba(21,128,61,.98) !important;
  font-weight:900;
  text-align:center !important;
}

.payrollSheet td.net.zeroNetCell{
  background:transparent !important;
  color:rgba(2,6,23,.72) !important;
  font-weight:800;
  text-align:right !important;
}
.paidNetBadge{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:6px;
  min-height:34px;
  padding:0 12px;
  border-radius:12px;
  background:linear-gradient(180deg, rgba(220,252,231,.96), rgba(209,250,229,.96));
  border:1px solid rgba(34,197,94,.18);
  color:rgba(21,128,61,.98);
  font-size:11px;
  font-weight:900;
  line-height:1;
  white-space:nowrap;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.78);
}
/* pay button */
.payCellForm{
  margin:0;
}

.payCellBtn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:8px;
  width:100%;
  min-height:38px;
  padding:7px 12px;
  border:1px solid rgba(251,191,36,.26);
  border-radius:12px;
  background:linear-gradient(180deg, rgba(255,247,237,.98), rgba(254,243,199,.96));
  color:rgba(15,23,42,.96);
  font-size:12px;
  font-weight:900;
  line-height:1;
  white-space:nowrap;
  cursor:pointer;
  transition:transform .12s ease, filter .12s ease, box-shadow .12s ease;
  box-shadow:
    0 8px 16px rgba(245,158,11,.10),
    inset 0 1px 0 rgba(255,255,255,.78);
}

.payCellBtn:hover{
  filter:brightness(.99);
  box-shadow:
    0 10px 18px rgba(245,158,11,.14),
    inset 0 0 0 1px rgba(180,83,9,.12);
}

.payCellBtn:active{
  transform:scale(.99);
}

.payCellBtn .payLabel{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  margin:0;
  min-height:20px;
  padding:0 8px;
  border-radius:999px;
  font-size:10px;
  font-weight:900;
  color:rgba(146,64,14,.95);
  background:rgba(251,191,36,.18);
}

/* mobile */
@media (max-width: 979px){
  .payrollSheet{
    min-width:1120px;
  }

  .payrollEmpCell,
  .payrollSheet thead th:first-child,
  .payrollSheet tbody td:first-child{
    width:112px;
    min-width:112px;
    max-width:112px;
  }

  .payrollDayCell{
    width:84px;
    min-width:84px;
    max-width:84px;
  }

  .payrollSummaryTotal{
    width:60px;
    min-width:60px;
    max-width:60px;
  }

  .payrollSummaryMoney{
    width:84px;
    min-width:84px;
    max-width:84px;
  }

  .payrollSheet thead th{
    font-size:12px;
    padding:10px 7px;
  }

  .payrollSheet tbody td{
    padding:10px 7px;
  }

  .payrollSheet .emp{
    font-size:12px;
  }

  .payrollSheet .empSub{
    font-size:10px;
  }

  .payrollSheet input.payrollTimeInput,
  .payrollTimeInput{
    font-size:12px;
  }

  .payrollDayHours{
    font-size:11px;
  }
}
/* Print tidy */
@media print{
  .sidebar, .bottomNav, button, input, select, .weekRow { display:none !important; }
  body{ padding:0 !important; background:#fff !important; }
  .shell{ width:100% !important; max-width:none !important; grid-template-columns: 1fr !important; }
  .card{ box-shadow:none !important; }
}

.kpiFancy{
  border: 1px solid rgba(56,189,248,.14);
  background:
    linear-gradient(180deg, #06142b 0%, #0a2342 55%, #0d2f52 100%);
  box-shadow:
    0 18px 40px rgba(2,6,23,.22),
    inset 0 1px 0 rgba(255,255,255,.04);
}

.kpiFancy .label{
  color: rgba(191,219,254,.78);
}

.kpiFancy .value{
  color: #f8fafc;
}

.kpiFancy .sub{
  color: rgba(191,219,254,.78);
}

.kpiFancy .chip{
  background: rgba(255,255,255,.08);
  border: 1px solid rgba(56,189,248,.18);
  color: #93c5fd;
}

/* Dashboard page menu card:
   keep on mobile, hide on desktop because sidebar already exists */
.dashboardMainMenu{
  display:block;
}

@media (min-width: 980px){
  .dashboardMainMenu{
    display:none;
  }
}
/* Payroll page docked sidebar */
@media (min-width: 980px){
  .payrollShell{
    grid-template-columns: 1fr !important;
    position: relative;
  }

  .payrollShell .sidebar{
    display: flex !important;
    position: fixed;
    left: 18px;
    top: 18px;
    bottom: 18px;
    width: 280px;
    z-index: 140;
    transform: translateX(-115%);
    opacity: 0;
    pointer-events: none;
    transition: transform .22s ease, opacity .22s ease;
  }

  .payrollShell.payrollMenuOpen .sidebar{
    transform: translateX(0);
    opacity: 1;
    pointer-events: auto;
  }

  .payrollShell .main{
    width: 100%;
    min-width: 0;
    transition: margin-left .22s ease, width .22s ease;
  }

  .payrollShell.payrollMenuOpen .main{
    margin-left: 298px;
    width: calc(100% - 298px);
  }

  /* no dark overlay for docked mode */
  .payrollMenuBackdrop{
    display: none !important;
  }

  .payrollMenuToggle{
  position: fixed;
  left: 5px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 160;
  width: 20px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(220,38,38,.22);
  border-radius: 0 12px 12px 0;
  background: linear-gradient(180deg, rgba(254,242,242,.98), rgba(252,231,243,.96));
  color: transparent;
  font-size: 0;
  cursor: pointer;
  box-shadow: 0 10px 22px rgba(220,38,38,.14);
  transition: left .22s ease, box-shadow .18s ease, background .18s ease;
}

.payrollMenuToggle::before{
  content: "❯";
  color: rgba(220,38,38,.95);
  font-size: 15px;
  font-weight: 900;
  line-height: 1;
}

.payrollShell.payrollMenuOpen .payrollMenuToggle{
  left: 308px;
}

.payrollShell.payrollMenuOpen .payrollMenuToggle::before{
  content: "❮";
}

.payrollMenuToggle:hover{
  box-shadow: 0 14px 26px rgba(220,38,38,.18);
  background: linear-gradient(180deg, rgba(254,226,226,.98), rgba(252,231,243,.98));
}
}
/* Admin payroll weekly employee cards - mobile compact table */
.payrollEmployeeCard .weeklyEditTable{
  table-layout: fixed;
  width: 100%;
  min-width: 0;
}

.payrollEmployeeCard .weeklyEditTable thead th,
.payrollEmployeeCard .weeklyEditTable tbody td{
  padding: 8px 4px;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.payrollEmployeeCard .weeklyEditTable thead th{
  letter-spacing: 0;
  font-size: 11px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(1),
.payrollEmployeeCard .weeklyEditTable td:nth-child(1){
  width: 38px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(2),
.payrollEmployeeCard .weeklyEditTable td:nth-child(2){
  width: 78px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(3),
.payrollEmployeeCard .weeklyEditTable td:nth-child(3),
.payrollEmployeeCard .weeklyEditTable th:nth-child(4),
.payrollEmployeeCard .weeklyEditTable td:nth-child(4){
  width: 56px;
  text-align: center;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(5),
.payrollEmployeeCard .weeklyEditTable td:nth-child(5){
  width: 46px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(6),
.payrollEmployeeCard .weeklyEditTable td:nth-child(6),
.payrollEmployeeCard .weeklyEditTable th:nth-child(7),
.payrollEmployeeCard .weeklyEditTable td:nth-child(7){
  width: 64px;
}

@media (max-width: 780px){
  .payrollEmployeeCard{
    padding: 10px !important;
  }

  .payrollEmployeeCard .weeklyEditTable thead th,
.payrollEmployeeCard .weeklyEditTable tbody td{
  padding: 6px 2px;
  font-size: 10px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(1),
.payrollEmployeeCard .weeklyEditTable td:nth-child(1){
  width: 30px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(2),
.payrollEmployeeCard .weeklyEditTable td:nth-child(2){
  width: 66px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(3),
.payrollEmployeeCard .weeklyEditTable td:nth-child(3),
.payrollEmployeeCard .weeklyEditTable th:nth-child(4),
.payrollEmployeeCard .weeklyEditTable td:nth-child(4){
  width: 46px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(5),
.payrollEmployeeCard .weeklyEditTable td:nth-child(5){
  width: 38px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(6),
.payrollEmployeeCard .weeklyEditTable td:nth-child(6),
.payrollEmployeeCard .weeklyEditTable th:nth-child(7),
.payrollEmployeeCard .weeklyEditTable td:nth-child(7){
  width: 52px;
}

  .payrollEmployeeCard .payrollSummaryBar{
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .payrollEmployeeCard .payrollSummaryItem{
  padding: 3px 5px;
  border-radius: 8px;
}

.payrollEmployeeCard .payrollSummaryItem .k{
  font-size: 8px;
}

.payrollEmployeeCard .payrollSummaryItem .v{
  font-size: 11px;
  line-height: 1;
}
}
/* ===== dark sidebar + blue payroll toggle ===== */

/* left menu panel */
.sidebar{
  background: linear-gradient(150deg, #0f172a 50%, #111827 20%) !important;
  border: 1px solid rgba(148,163,184,.16) !important;
  box-shadow: 0 18px 40px rgba(2,6,23,.28) !important;
}

.sideTitle{
  color: #e5e7eb !important;
}

.sideDivider{
  background: rgba(148,163,184,.18) !important;
}

/* menu cards inside dark panel */
.sideItem{
  background: rgba(255,255,255,.04) !important;
  border: 1px solid rgba(148,163,184,.14) !important;
  box-shadow: none !important;
}

.sideItem:hover{
  background: rgba(255,255,255,.07) !important;
  border-color: rgba(96,165,250,.26) !important;
  box-shadow: 0 10px 24px rgba(2,6,23,.18) !important;
}

.sideItem.active{
  background: linear-gradient(180deg, rgba(37,99,235,.22), rgba(59,130,246,.12)) !important;
  border-color: rgba(96,165,250,.34) !important;
  box-shadow: 0 12px 28px rgba(30,64,175,.22) !important;
}

.sideItem.active:before{
  content:none !important;
  display:none !important;
}

.shell:has(.sidebar) .sideItem.active::after{
  content:"";
  position:absolute;
  left:10px;
  right:10px;
  bottom:6px;
  height:4px;
  border-radius:999px;
  background:linear-gradient(90deg, #60a5fa, #2563eb);
  box-shadow:0 0 0 3px rgba(59,130,246,.12);
}

/* text + chevrons */
.sideText{
  color: #f8fafc !important;
}

.chev{
  color: #93c5fd !important;
  opacity: 1 !important;
}

/* icons - remove inner card look */
.sideIcon{
  background:transparent !important;
  border:0 !important;
  box-shadow:none !important;
  border-radius:0 !important;
  padding:0 !important;
  display:flex !important;
  align-items:center !important;
  justify-content:center !important;
  color:#cfe1ff !important;
}

.sideIcon svg{
  width:32px !important;
  height:32px !important;
  display:block !important;
}

.sideIcon img{
  width:32px !important;
  height:32px !important;
  object-fit:contain !important;
  display:block !important;
}

/* logout row */
.logoutBtn{
  background: rgba(239,68,68,.08) !important;
  border-color: rgba(248,113,113,.18) !important;
}

.logoutBtn .sideText,
.logoutBtn .chev{
  color: #f87171 !important;
}

/* payroll sliding button */
.payrollMenuToggle{
  left: 10px !important;
  top: 50% !important;
  transform: translateY(-50%) !important;
  width: 32px !important;
  height: 32px !important;
  padding: 0 !important;
  border-radius: 999px !important;
  border: 1px solid rgba(148,163,184,.34) !important;
  background: rgba(255,255,255,.96) !important;
  color: transparent !important;
  font-size: 0 !important;
  box-shadow: 0 6px 16px rgba(15,23,42,.08), inset 0 1px 0 rgba(255,255,255,.82) !important;
}

.payrollMenuToggle::before{
  content: "›";
  color: #64748b !important;
  font-size: 20px !important;
  font-weight: 800 !important;
  line-height: 1 !important;
  transform: translateX(1px);
}

.payrollMenuToggle:hover{
  background: rgba(255,255,255,.99) !important;
  border-color: rgba(99,102,241,.28) !important;
  box-shadow: 0 10px 20px rgba(15,23,42,.12), inset 0 1px 0 rgba(255,255,255,.9) !important;
}

/* when sidebar is open, keep toggle aligned just outside panel */
.payrollShell.payrollMenuOpen .payrollMenuToggle{
  left: 286px !important;
}
.payrollShell.payrollMenuOpen .payrollMenuToggle::before{
  content: "‹";
  transform: translateX(-1px);
}
@media (max-width: 979px){
  .payrollMenuToggle{
    display: none !important;
  }
}


.timeLogsTable{
  width: 100% !important;
  min-width: 0 !important;
  table-layout: fixed;
}

.timeLogsTable th,
.timeLogsTable td{
  padding: 12px 14px;
  font-size: 16px;
  line-height: 1.25;
  vertical-align: middle;
  white-space: nowrap;
}

.timeLogsTable th{
  font-size: 17px;
  font-weight: 800;
}

.timeLogsTable th:nth-child(1),
.timeLogsTable td:nth-child(1){
  width: 24%;
  text-align: left;
}

.timeLogsTable th:nth-child(2),
.timeLogsTable td:nth-child(2),
.timeLogsTable th:nth-child(3),
.timeLogsTable td:nth-child(3){
  width: 18%;
  text-align: center;
}

.timeLogsTable th:nth-child(4),
.timeLogsTable td:nth-child(4){
  width: 14%;
  text-align: center;
}

.timeLogsTable th:nth-child(5),
.timeLogsTable td:nth-child(5){
  width: 18%;
  text-align: right;
  padding-right: 18px;
}

@media (max-width: 700px){
  .timeLogsTable th,
  .timeLogsTable td{
    padding: 7px 6px;
    font-size: 12px;
  }

  .timeLogsTable th{
    font-size: 13px;
  }

  .timeLogsTable th:nth-child(1),
  .timeLogsTable td:nth-child(1){
    width: 30%;
  }

  .timeLogsTable th:nth-child(2),
  .timeLogsTable td:nth-child(2),
  .timeLogsTable th:nth-child(3),
  .timeLogsTable td:nth-child(3){
    width: 18%;
    text-align: center;
  }

  .timeLogsTable th:nth-child(4),
  .timeLogsTable td:nth-child(4){
    width: 14%;
    text-align: center;
  }

  .timeLogsTable th:nth-child(5),
  .timeLogsTable td:nth-child(5){
    width: 20%;
    text-align: right;
    padding-right: 10px;
  }
}

/* ===== LIGHT BRAND THEME (PURPLE / BLUE / GREEN) ===== */
:root{
  --bg:#f6f5fb !important;
  --card:#ffffff !important;
  --text:#26233a !important;
  --muted:#6f6c85 !important;
  --border:rgba(107,70,193,.12) !important;
  --shadow:0 12px 30px rgba(41,25,86,.08) !important;
  --shadow2:0 20px 42px rgba(41,25,86,.12) !important;
  --radius:18px !important;

  /* Re-map existing theme vars without touching app logic */
  --navy:#6d28d9 !important;
  --navy2:#2563eb !important;
  --navySoft:rgba(109,40,217,.10) !important;
  --green:#16a34a !important;
  --red:#dc2626 !important;
  --amber:#d97706 !important;
}

/* page background */
body{
  background:
    radial-gradient(980px 540px at 0% 0%, rgba(109,40,217,.08) 0%, rgba(109,40,217,0) 48%),
    radial-gradient(860px 520px at 100% 0%, rgba(37,99,235,.08) 0%, rgba(37,99,235,0) 48%),
    radial-gradient(880px 580px at 50% 100%, rgba(34,197,94,.05) 0%, rgba(34,197,94,0) 45%),
    linear-gradient(180deg, #fbfaff 0%, #f5f4fb 52%, #f1f5ff 100%) !important;
  color: var(--text) !important;
}

/* general cards / panels */
.card,
.kpiMini,
.kpi,
.payrollFiltersCard,
.payrollChartCard,
.adminToolCard,
.adminSectionCard,
.payrollSummaryItem,
.contractBox,
.tablewrap,
.payrollWrap,
.sectionIcon,
.adminToolIcon,
.adminSectionIcon,
.sideIcon,
.icoBox{
  background: linear-gradient(180deg, rgba(255,255,255,.99), rgba(250,248,255,.98)) !important;
  border: 1px solid rgba(109,40,217,.10) !important;
  border-radius: 18px !important;
  box-shadow: 0 12px 28px rgba(41,25,86,.08) !important;
  color: var(--text) !important;
}

/* module tinting */
.quickCard{
  background: linear-gradient(180deg, rgba(245,243,255,.98), rgba(255,255,255,.98)) !important;
  border: 1px solid rgba(109,40,217,.14) !important;
  color: var(--text) !important;
}
.activityCard{
  background: linear-gradient(180deg, rgba(239,246,255,.98), rgba(255,255,255,.98)) !important;
  border: 1px solid rgba(37,99,235,.14) !important;
  color: var(--text) !important;
}
.sideInfoCard{
  background: linear-gradient(180deg, rgba(240,253,244,.98), rgba(255,255,255,.98)) !important;
  border: 1px solid rgba(34,197,94,.16) !important;
  color: var(--text) !important;
}

/* corner radius */
.badge,
.badge.admin,
.chip,
.weekPill,
.btn,
.btnSoft,
.btnTiny,
.input,
.menuItem,
.sideItem,
.navIcon,
.payrollMenuToggle,
.adminPrimaryBtn,
.message,
.kpiMini,
.payrollSummaryItem,
.tablewrap,
.payrollWrap,
.contractBox{
  border-radius: 16px !important;
}

/* brand badges / pills */
.badge,
.badge.admin,
.weekPill{
  background: linear-gradient(180deg, rgba(109,40,217,.12), rgba(37,99,235,.10)) !important;
  color: #5b21b6 !important;
  border: 1px solid rgba(109,40,217,.16) !important;
  box-shadow: 0 4px 12px rgba(109,40,217,.08) !important;
}

/* brand button system */
.btn,
.btnSoft,
.adminPrimaryBtn,
.payrollMenuToggle{
  background: linear-gradient(135deg, #7c3aed 0%, #2563eb 100%) !important;
  color: #ffffff !important;
  border: 1px solid rgba(124,58,237,.14) !important;
  box-shadow: 0 12px 24px rgba(109,40,217,.18) !important;
}
.btnTiny{
  background: rgba(109,40,217,.08) !important;
  color: #5b21b6 !important;
  border: 1px solid rgba(109,40,217,.14) !important;
  box-shadow: none !important;
}
.btnTiny:hover,
.btnSoft:hover,
.btn:hover,
.adminPrimaryBtn:hover,
.payrollMenuToggle:hover{
  filter: brightness(1.03) !important;
  box-shadow: 0 16px 28px rgba(109,40,217,.20) !important;
}

/* top badges / company pill */
.topBrandBadge{
  color: #312e81 !important;
  border: 1px solid rgba(109,40,217,.12) !important;
  background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(245,243,255,.96)) !important;
  box-shadow: 0 10px 24px rgba(41,25,86,.08) !important;
}
.topBrandBadge:hover{
  border-color: rgba(109,40,217,.20) !important;
}

/* inputs */
.input,
select.input,
input.input,
textarea.input{
  background: rgba(255,255,255,.98) !important;
  color: #27253a !important;
  border: 1px solid rgba(148,163,184,.34) !important;
  border-radius: 14px !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.75) !important;
}
.input::placeholder,
textarea.input::placeholder{
  color: #8a86a3 !important;
}
.input:focus,
select.input:focus,
input.input:focus,
textarea.input:focus{
  border-color: rgba(124,58,237,.40) !important;
  box-shadow: 0 0 0 4px rgba(124,58,237,.10) !important;
}

/* labels + values */
.kpiMini .k,
.kpi .label,
.graphStat .k,
.payrollSummaryItem .k,
.sectionBadge,
.sub,
.timerSub,
.sideInfoLabel,
.adminToolSub,
.adminSectionSub,
.activityHead{
  color: #7a7592 !important;
}
.kpiMini .v,
.kpi .value,
.graphStat .v,
.payrollSummaryItem .v,
.sideInfoValue,
.adminToolTitle,
.adminSectionTitle,
.quickMini .miniText,
h1,
h2{
  color: #26233a !important;
}

/* graph / dashboard */
.graphCard{
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(245,243,255,.98)) !important;
  border: 1px solid rgba(109,40,217,.14) !important;
  box-shadow: 0 16px 36px rgba(41,25,86,.08) !important;
}
.graphTitle{
  color: #2f2851 !important;
}
.graphCard .sub{
  color: #7a7592 !important;
}
.graphRange{
  color: #5b21b6 !important;
}
.graphShell{
  background:
    linear-gradient(180deg, rgba(249,247,255,.98), rgba(240,247,255,.96)),
    radial-gradient(circle at top right, rgba(109,40,217,.08), transparent 40%),
    radial-gradient(circle at top left, rgba(37,99,235,.08), transparent 40%) !important;
  border: 1px solid rgba(109,40,217,.10) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.85), 0 10px 24px rgba(41,25,86,.06) !important;
}
.barValue{
  color: #6d28d9 !important;
  text-shadow: none !important;
}
.barTrack{
  background:
    linear-gradient(180deg, rgba(109,40,217,.04), rgba(109,40,217,.01)),
    linear-gradient(180deg, rgba(37,99,235,.03), rgba(37,99,235,0)) !important;
  box-shadow: inset 0 0 0 1px rgba(109,40,217,.06) !important;
}
.bar{
  background: linear-gradient(180deg, #7c3aed 0%, #38bdf8 100%) !important;
  box-shadow: 0 12px 24px rgba(109,40,217,.16), 0 0 16px rgba(56,189,248,.10) !important;
}
.barLabels{
  color: #6f6c85 !important;
}
.graphStat{
  background: rgba(255,255,255,.92) !important;
  border: 1px solid rgba(109,40,217,.08) !important;
}

/* tables */
.tablewrap table,
.weeklyEditTable,
.payrollSheet,
.timeLogsTable{
  background: rgba(255,255,255,.98) !important;
  color: #26233a !important;
}
.tablewrap th,
.weeklyEditTable thead th,
.payrollSheet thead th,
.timeLogsTable th{
  background: linear-gradient(180deg, rgba(244,241,255,.99), rgba(236,245,255,.99)) !important;
  color: rgba(38,35,58,.88) !important;
  border-bottom: 1px solid rgba(148,163,184,.18) !important;
}
.tablewrap td,
.weeklyEditTable tbody td,
.payrollSheet td,
.timeLogsTable td{
  background: rgba(255,255,255,.96) !important;
  color: rgba(38,35,58,.95) !important;
  border-bottom: 1px solid rgba(226,232,240,.90) !important;
}
.tablewrap table tbody tr:nth-child(even),
.weeklyEditTable tbody tr:nth-child(even) td,
.payrollSheet tbody tr:nth-child(even) td,
.timeLogsTable tbody tr:nth-child(even) td{
  background: rgba(249,247,255,.86) !important;
}
.tablewrap table tbody tr:hover,
.weeklyEditTable tbody tr:hover td,
.payrollSheet tbody tr:hover td,
.timeLogsTable tbody tr:hover td{
  background: rgba(241,245,255,.96) !important;
}
.weeklyEditTable tbody td:nth-child(2){
  color: #7a7592 !important;
}

/* payroll-specific light treatment */
.payrollWrap,
.tablewrap{
  background: linear-gradient(180deg, rgba(255,255,255,.99), rgba(247,249,255,.98)) !important;
  border-color: rgba(109,40,217,.10) !important;
}
.payrollSheet{
  background: transparent !important;
}
.payrollSheet tbody td:first-child,
.payrollSheet thead th:first-child{
  box-shadow: 10px 0 18px rgba(41,25,86,.06) !important;
}
.payrollSheet .emp{
  color: rgba(38,35,58,.98) !important;
}
.payrollSheet .empSub{
  color: rgba(111,108,133,.76) !important;
}
.payrollDayHours{
  color: #15803d !important;
}
.payrollDayEmpty{
  color: rgba(111,108,133,.54) !important;
}
.payrollSheet input[type="time"],
.payrollSheet input[type="time"]:disabled,
.payrollSheet input.payrollTimeInput,
.payrollTimeInput{
  color: rgba(38,35,58,.98) !important;
  -webkit-text-fill-color: rgba(38,35,58,.98) !important;
}
.payrollSummaryItem,
.payrollEmployeeCard .payrollSummaryItem:nth-child(1),
.payrollEmployeeCard .payrollSummaryItem:nth-child(2),
.payrollEmployeeCard .payrollSummaryItem:nth-child(3),
.payrollEmployeeCard .payrollSummaryItem:nth-child(4),
.payrollEmployeeCard .payrollSummaryItem:nth-child(5){
  background: linear-gradient(180deg, rgba(255,255,255,.99), rgba(248,246,255,.97)) !important;
  border: 1px solid rgba(109,40,217,.10) !important;
  box-shadow: 0 8px 18px rgba(41,25,86,.06), inset 0 1px 0 rgba(255,255,255,.90) !important;
}
.payrollSummaryItem .k,
.payrollEmployeeCard .payrollSummaryItem .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(1) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(2) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(3) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(4) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(5) .k{
  color: rgba(111,108,133,.82) !important;
}
.payrollSummaryItem .v,
.payrollSummaryItem.net .v,
.payrollEmployeeCard .payrollSummaryItem .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(1) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(2) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(3) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(4) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(5) .v{
  color: rgba(38,35,58,.96) !important;
}

/* employee detail cards */
.payrollEmployeeCard{
  background: linear-gradient(180deg, rgba(255,255,255,.99), rgba(245,243,255,.98)) !important;
  border: 1px solid rgba(109,40,217,.12) !important;
  box-shadow: 0 18px 34px rgba(41,25,86,.08), inset 0 1px 0 rgba(255,255,255,.90) !important;
  color: #26233a !important;
}
.payrollEmployeeHead{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  margin-bottom:14px;
  padding-bottom:10px;
  border-bottom:1px solid rgba(148,163,184,.18);
}
.payrollEmployeeName{
  font-size: clamp(28px, 3vw, 40px);
  line-height: 1.05;
  font-weight: 900;
  letter-spacing: -.03em;
  color: #26233a !important;
  text-shadow: none !important;
}

/* sidebar */
.sidebar{
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(244,241,255,.96)) !important;
  border: 1px solid rgba(109,40,217,.10) !important;
  border-radius: 20px !important;
  box-shadow: 0 18px 40px rgba(41,25,86,.08) !important;
}
.sideTitle,
.sideText,
.menuText{
  color: #26233a !important;
}
.sideItem,
.menuItem{
  background: rgba(255,255,255,.82) !important;
  border: 1px solid rgba(109,40,217,.08) !important;
  border-radius: 16px !important;
  box-shadow: none !important;
}
.sideItem:hover,
.menuItem:hover{
  background: rgba(124,58,237,.05) !important;
  border-color: rgba(124,58,237,.16) !important;
}
.sideItem.active,
.menuItem.active{
  background: linear-gradient(180deg, rgba(124,58,237,.10), rgba(37,99,235,.06)) !important;
  border-color: rgba(124,58,237,.20) !important;
  box-shadow: inset 0 -3px 0 rgba(37,99,235,.35) !important;
}
.chev{
  color: #5b21b6 !important;
}
.navIcon,
.sideIcon,
.icoBox,
.adminToolIcon,
.adminSectionIcon{
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(245,243,255,.98)) !important;
  color: #5b21b6 !important;
  border-color: rgba(109,40,217,.10) !important;
}

/* admin shells */
.adminToolsShell{
  background: linear-gradient(180deg, rgba(248,246,255,.98), rgba(255,255,255,.98)) !important;
  border: 1px solid rgba(109,40,217,.10) !important;
  box-shadow: 0 18px 40px rgba(41,25,86,.08) !important;
}
.adminToolCard:hover{
  transform: translateY(-2px);
  box-shadow: 0 18px 34px rgba(41,25,86,.12) !important;
}
.adminToolCard.payroll .adminToolIcon{
  background: linear-gradient(180deg, rgba(239,246,255,.98), rgba(219,234,254,.98)) !important;
  color: #2563eb !important;
  border-color: rgba(37,99,235,.16) !important;
}
.adminToolCard.company .adminToolIcon{
  background: linear-gradient(180deg, rgba(245,243,255,.98), rgba(237,233,254,.98)) !important;
  color: #6d28d9 !important;
  border-color: rgba(109,40,217,.16) !important;
}
.adminToolCard.onboarding .adminToolIcon,
.adminToolCard.employees .adminToolIcon{
  background: linear-gradient(180deg, rgba(240,253,244,.98), rgba(220,252,231,.98)) !important;
  color: #15803d !important;
  border-color: rgba(34,197,94,.16) !important;
}

/* dashboard mini cards / rows */
.quickMini,
.activityRow,
.activityEmpty,
.dashboardMainMenu .menuItem,
.adminStats .adminStatCard,
.adminSectionCard{
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,246,255,.96)) !important;
  border: 1px solid rgba(109,40,217,.10) !important;
  box-shadow: 0 10px 22px rgba(41,25,86,.06) !important;
  border-radius: 16px !important;
}
.quickMini .miniIcon{
  color: #000000 !important;
  background: rgba(0,0,0,.06) !important;
  border-color: rgba(0,0,0,.12) !important;
}
.activityRow{
  color: rgba(38,35,58,.88) !important;
}
.activityEmpty{
  color: #7a7592 !important;
  background: rgba(255,255,255,.82) !important;
  border: 1px dashed rgba(109,40,217,.16) !important;
}
.sideInfoRow{
  background: rgba(255,255,255,.84) !important;
  border: 1px solid rgba(34,197,94,.12) !important;
}
.sideInfoLabel{
  color: #5e7a66 !important;
}
.sideInfoValue{
  color: #1f3b2c !important;
}

/* messages */
.message{
  background: rgba(124,58,237,.08) !important;
  border: 1px solid rgba(124,58,237,.14) !important;
  color: #312e81 !important;
}
.message.error{
  background: rgba(220,38,38,.08) !important;
  border-color: rgba(220,38,38,.16) !important;
  color: #991b1b !important;
}

/* MY REPORTS / PLAIN SECTION cards become light too */
.myReportsWeekTable.plainSection,
.payrollEmployeeCard.plainSection{
  background: linear-gradient(180deg, rgba(255,255,255,.99), rgba(248,246,255,.98)) !important;
  border: 1px solid rgba(109,40,217,.12) !important;
  box-shadow: 0 16px 32px rgba(41,25,86,.08) !important;
}
.myReportsWeekTable.plainSection .sub,
.payrollEmployeeCard.plainSection .sub,
.myReportsWeekTable.plainSection .payrollSummaryItem .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem .k,
.myReportsWeekTable.plainSection .payrollSummaryItem:nth-child(1) .k,
.myReportsWeekTable.plainSection .payrollSummaryItem:nth-child(2) .k,
.myReportsWeekTable.plainSection .payrollSummaryItem:nth-child(3) .k,
.myReportsWeekTable.plainSection .payrollSummaryItem:nth-child(4) .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(1) .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(2) .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(3) .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(4) .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(5) .k{
  color: rgba(111,108,133,.82) !important;
  -webkit-text-fill-color: rgba(111,108,133,.82) !important;
}
.myReportsWeekTable.plainSection .payrollSummaryItem .v,
.myReportsWeekTable.plainSection .payrollSummaryItem.net .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(1) .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(2) .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(3) .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(4) .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(5) .v{
  color: #26233a !important;
  -webkit-text-fill-color: #26233a !important;
  text-shadow: none !important;
}

/* ===== FINAL TABLE READABILITY FIXES ===== */

/* 1) TIME LOGS: keep all rows bright and readable */
.timeLogsTable tbody tr,
.timeLogsTable tbody tr:nth-child(odd),
.timeLogsTable tbody tr:nth-child(even){
  background: transparent !important;
}

.timeLogsTable tbody tr td,
.timeLogsTable tbody tr:nth-child(odd) td,
.timeLogsTable tbody tr:nth-child(even) td{
  background: #ffffff !important;
  color: #26233a !important;
  -webkit-text-fill-color: #26233a !important;
  text-shadow: none !important;
  border-bottom: 1px solid rgba(226,232,240,.90) !important;
}

.timeLogsTable tbody tr:hover td{
  background: #f5f3ff !important;
  color: #26233a !important;
  -webkit-text-fill-color: #26233a !important;
}

/* 2) EMPLOYEE SITES + LOCATIONS: keep table form controls clean */
.tablewrap td form .input,
.tablewrap td form input,
.tablewrap td form input.input,
.tablewrap td form select,
.tablewrap td form select.input,
.tablewrap td form textarea,
.tablewrap td form textarea.input{
  background: #ffffff !important;
  color: #26233a !important;
  -webkit-text-fill-color: #26233a !important;
  caret-color: #26233a !important;
  border: 1px solid rgba(148,163,184,.36) !important;
  box-shadow: none !important;
  font-weight: 600 !important;
}

.tablewrap td form .input::placeholder,
.tablewrap td form input::placeholder,
.tablewrap td form textarea::placeholder{
  color: #7a7592 !important;
  -webkit-text-fill-color: #7a7592 !important;
}

.tablewrap td form select option,
.tablewrap td form select optgroup{
  background: #ffffff !important;
  color: #26233a !important;
}

/* keep plain numeric/location cells readable */
.tablewrap td.num{
  color: #26233a !important;
  -webkit-text-fill-color: #26233a !important;
}

/* 3) DISTINCT STATUS COLORS */
.chip.ok,
.tablewrap .chip.ok{
  background: #16a34a !important;
  color: #f0fdf4 !important;
  border: 1px solid #15803d !important;
  box-shadow: none !important;
}

.chip.warn,
.tablewrap .chip.warn{
  background: #dc2626 !important;
  color: #fff1f2 !important;
  border: 1px solid #b91c1c !important;
  box-shadow: none !important;
}

.chip.bad,
.tablewrap .chip.bad{
  background: #d97706 !important;
  color: #fffbeb !important;
  border: 1px solid #b45309 !important;
  box-shadow: none !important;
}

/* helper text inside white table sections */
.tablewrap td .sub,
.tablewrap td label.sub{
  color: #6f6c85 !important;
}

/* keep action links readable */
.tablewrap td a[href*="/admin/locations?site="]{
  color: #2563eb !important;
  font-weight: 700 !important;
}

/* reduce clipping on admin management tables */
.tablewrap > table[style*="min-width:980px"]{
  min-width: 860px !important;
  width: 100% !important;
  table-layout: auto !important;
}

.tablewrap > table[style*="min-width:980px"] th,
.tablewrap > table[style*="min-width:980px"] td{
  white-space: normal !important;
  vertical-align: top !important;
}

.tablewrap > table[style*="min-width:980px"] td:last-child,
.tablewrap > table[style*="min-width:980px"] th:last-child{
  min-width: 280px !important;
}



/* ===== softer typography v2 ===== */
body{
  font-size:13px !important;
  -webkit-font-smoothing:antialiased;
  text-rendering:optimizeLegibility;
}

h1,
.headerTop h1,
.dashboardTitle,
.timeLogsTitle,
.adminPageTitle,
.statementTitle{
  font-size:clamp(20px, 3.2vw, 28px) !important;
  font-weight:600 !important;
  line-height:1.08 !important;
  letter-spacing:-.02em !important;
}

h2,
.card h2,
.adminSectionTitle,
.adminToolTitle,
.timeLogsSectionTitle,
.graphTitle,
.sectionTitle{
  font-size:16px !important;
  font-weight:600 !important;
  line-height:1.18 !important;
  letter-spacing:-.01em !important;
}

h3,
.uploadTitle,
.contractTitle{
  font-size:14px !important;
  font-weight:600 !important;
}

strong,
b{
  font-weight:600 !important;
}

.sub,
.timerSub,
.sideInfoLabel,
.adminToolSub,
.adminSectionSub,
.activityHead,
label.sub,
.smallText,
.tableHint,
.muted,
.miniText{
  font-size:12.5px !important;
  font-weight:500 !important;
  line-height:1.45 !important;
  color:#7a7592 !important;
}

.badge,
.badge.admin,
.weekPill,
.chip,
.topBrandBadge,
.dashboardEyebrow,
.timeLogsEyebrow,
.sectionBadge,
.onboardMiniStat .k{
  font-size:11px !important;
  font-weight:600 !important;
  letter-spacing:.03em !important;
}

.sideText,
.menuText{
  font-size:13px !important;
  font-weight:600 !important;
}

.kpi .label,
.kpiFancy .label,
.kpiFancy .sub,
.kpiMini .k,
.graphStat .k,
.payrollSummaryItem .k,
.timeLogsSummaryCard .k,
.adminStatCard .k,
.statementSummaryRow .k,
.statementTotalCard .k{
  font-size:11.5px !important;
  font-weight:500 !important;
  letter-spacing:.01em !important;
  color:#7a7592 !important;
}

.kpi .value,
.kpiFancy .value,
.kpiMini .v,
.graphStat .v,
.payrollSummaryItem .v,
.timeLogsSummaryCard .v,
.adminStatCard .v,
.statementSummaryRow .v,
.statementTotalCard .v,
.netBadge,
.sideInfoValue{
  font-size:clamp(16px, 2.2vw, 22px) !important;
  font-weight:600 !important;
  line-height:1.08 !important;
  letter-spacing:-.02em !important;
}

.kpi .value,
.kpiFancy .value{
  margin-top:4px !important;
}

.tablewrap th,
.weeklyEditTable thead th,
.payrollSheet thead th,
table thead th{
  font-size:11.5px !important;
  font-weight:600 !important;
  letter-spacing:.01em !important;
  color:#6f6b87 !important;
}

.tablewrap td,
.weeklyEditTable tbody td,
.payrollSheet td,
table tbody td{
  font-size:12.5px !important;
  font-weight:500 !important;
  color:#302d43 !important;
}

.tablewrap input.input,
.weeklyEditTable input.input,
.payrollSheet input.input,
.input,
select.input,
input.input,
textarea.input{
  font-size:13px !important;
  font-weight:500 !important;
}

.btn,
.btnSoft,
.btnTiny,
.adminPrimaryBtn,
.payrollMenuToggle,
button{
  font-size:13px !important;
  font-weight:600 !important;
  letter-spacing:0 !important;
}

@media (min-width:980px){
  .kpi .value,
  .kpiFancy .value,
  .kpiMini .v,
  .graphStat .v,
  .payrollSummaryItem .v,
  .timeLogsSummaryCard .v,
  .adminStatCard .v,
  .statementSummaryRow .v,
  .statementTotalCard .v,
  .netBadge,
  .sideInfoValue{
    font-size:20px !important;
  }

  .tablewrap th,
  .weeklyEditTable thead th,
  .payrollSheet thead th,
  table thead th{
    font-size:11px !important;
  }

  .tablewrap td,
  .weeklyEditTable tbody td,
  .payrollSheet td,
  table tbody td{
    font-size:12px !important;
  }
}


/* ===== shared back buttons ===== */
.pageBackRow{
  display:flex;
  align-items:center;
  margin:0 0 12px;
}
.printToolbar .pageBackRow,
.toolbar .pageBackRow{
  margin:0;
}
.pageBackBtn,
.pageBackBtn:link,
.pageBackBtn:visited{
  width:32px;
  height:32px;
  min-width:32px;
  padding:0;
  border:1px solid rgba(148,163,184,.34);
  border-radius:999px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  background:rgba(255,255,255,.96);
  color:#64748b;
  text-decoration:none;
  box-shadow:0 6px 16px rgba(15,23,42,.08), inset 0 1px 0 rgba(255,255,255,.82);
  transition:transform .16s ease, box-shadow .16s ease, border-color .16s ease, background .16s ease;
  cursor:pointer;
}
.pageBackBtn:hover{
  transform:translateY(-1px);
  border-color:rgba(99,102,241,.28);
  box-shadow:0 10px 20px rgba(15,23,42,.12), inset 0 1px 0 rgba(255,255,255,.9);
  background:rgba(255,255,255,.99);
}
.pageBackBtn span{
  display:block;
  font-size:20px;
  font-weight:800;
  line-height:1;
  transform:translateX(-1px);
}

</style>
"""


# ================= ICONS =================
def _svg_clock():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="9"></circle><path d="M12 7v6l4 2"></path></svg>"""


def _svg_clipboard():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="8" y="2" width="8" height="4" rx="1"></rect>
      <path d="M9 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3"></path></svg>"""


def _svg_chart():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M4 19V5"></path><path d="M4 19h16"></path>
      <path d="M8 17V9"></path><path d="M12 17V7"></path><path d="M16 17v-4"></path></svg>"""


def _svg_doc():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path></svg>"""


def _svg_user():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M20 21a8 8 0 1 0-16 0"></path><circle cx="12" cy="7" r="4"></circle></svg>"""


def _svg_grid():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M4 4h7v7H4z"></path><path d="M13 4h7v7h-7z"></path>
      <path d="M4 13h7v7H4z"></path><path d="M13 13h7v7h-7z"></path></svg>"""


def _svg_logout():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M10 17l5-5-5-5"></path><path d="M15 12H3"></path>
      <path d="M21 3v18"></path></svg>"""


def _svg_shield():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M12 3l7 3v6c0 5-3.5 8-7 9-3.5-1-7-4-7-9V6l7-3z"></path>
    </svg>"""


# ================= CONTRACT TEXT =================

def _app_icon(file_name: str, size: int = 22, alt: str = ""):
    return (
        f'<img src="/static/modern_icons/{file_name}" '
        f'alt="{escape(alt)}" '
        f'width="{size}" height="{size}" '
        f'style="width:{size}px;height:{size}px;object-fit:contain;display:block;">'
    )


def _icon_dashboard(size=22): return _app_icon("dashboard.png", size, "Dashboard")


def _icon_clock(size=22): return _app_icon("clock.png", size, "Clock In & Out")


def _icon_timelogs(size=22): return _app_icon("timelogs.png", size, "Time Logs")


def _icon_timesheets(size=22): return _app_icon("timesheets.png", size, "Timesheets")

def _icon_payments(size=22):
    return f'''
    <div style="
      width:{size}px;
      height:{size}px;
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:{max(12, int(size * 0.82))}px;
      font-weight:900;
      line-height:1;
      color:currentColor;
    ">£</div>
    '''


def _icon_starter_form(size=22): return _app_icon("starter_form.png", size, "Starter Form")


def _icon_admin(size=22): return _app_icon("admin.png", size, "Admin")


def _icon_workplaces(size=22): return _app_icon("workplaces.png", size, "Workplaces")


def _icon_profile(size=22): return _app_icon("profile.png", size, "Profile")


def _icon_onboarding(size=22): return _app_icon("onboarding.png", size, "Onboarding")


def _icon_payroll_report(size=22): return _app_icon("payroll_report.png", size, "Payroll Report")


def _icon_company_settings(size=22): return _app_icon("company_settings.png", size, "Company Settings")


def _icon_employee_sites(size=22): return _app_icon("employee_sites.png", size, "Employee Sites")


def _icon_employees(size=22): return _app_icon("employees.png", size, "Employees")


def _icon_connect_drive(size=22): return _app_icon("connect_drive.png", size, "Connect Drive")


def _icon_locations(size=22): return _app_icon("locations.png", size, "Locations")


CONTRACT_TEXT = """Contract

By signing this agreement, you confirm that while carrying out bricklaying services (and related works) for us, you are acting as a self-employed subcontractor and not as an employee.

You agree to:

Behave professionally at all times while on site

Use reasonable efforts to complete all work within agreed timeframes

Comply with all Health & Safety requirements, including rules on working hours, site conduct, and site security

Be responsible for the standard of your work and rectify any defects at your own cost and in your own time

Maintain valid public liability insurance

Supply your own hand tools

Manage and pay your own Tax and National Insurance contributions (CIS tax will be deducted by us and submitted to HMRC)

You are not required to:

Transfer to another site unless you choose to do so and agree a revised rate

Submit written quotations or tenders; all rates will be agreed verbally

Supply major equipment or materials

Carry out work you do not wish to accept; there is no obligation to accept work offered

Work set or fixed hours

Submit invoices; all payments will be processed under the CIS scheme and a payment statement will be provided

You have the right to:

Decide how the work is performed

Leave the site without seeking permission (subject to notifying us for Health & Safety reasons)

Provide a substitute with similar skills and experience, provided you inform us in advance. You will remain responsible for paying them

Terminate this agreement at any time without notice

Seek independent legal advice before signing and retain a copy of this agreement

You do not have the right to:

Receive sick pay or payment for work cancelled due to adverse weather

Use our internal grievance procedure

Describe yourself as an employee of our company

By signing this agreement, you accept these terms and acknowledge that they define the working relationship between you and us.

You also agree that this document represents the entire agreement between both parties, excluding any verbal discussions relating solely to pricing or work location.

Contractor Relationship

For the purposes of this agreement, you are the subcontractor, and we are the contractor.

We agree to:

Confirm payment rates verbally, either as a fixed price or an hourly rate, before work begins

We are not required to:

Guarantee or offer work at any time

We have the right to:

End this agreement without notice

Obtain legal advice prior to signing

We do not have the right to:

Direct or control how you carry out your work

Expect immediate availability or require you to prioritise our work over other commitments

By signing this agreement, we confirm our acceptance of its terms and that they govern the relationship between both parties.

This document represents the full agreement between us, excluding verbal discussions relating only to pricing or work location.

General Terms

This agreement is governed by the laws of England and Wales

If any part of this agreement is breached or found unenforceable, the remaining clauses will continue to apply
""".strip()


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
            db.session.rollback()
        except Exception:
            pass

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
            try:
                db.session.rollback()
            except Exception:
                pass
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
            db.session.rollback()

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


from datetime import datetime, timedelta


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
    }

    current_wp = _session_workplace_id()

    allowed_wps = set(_workplace_ids_for_read(current_wp))

    try:
        records = WorkplaceSetting.query.all() if DB_MIGRATION_MODE else (get_settings() or [])

        for rec in records:
            if isinstance(rec, dict):
                row_wp = str(rec.get("Workplace_ID") or rec.get("workplace_id") or "default").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

                tax_raw = str(rec.get("Tax_Rate") or rec.get("tax_rate") or "").strip()
                cur = str(
                    rec.get("Currency_Symbol") or rec.get("currency_symbol") or defaults["Currency_Symbol"]).strip() or \
                      defaults["Currency_Symbol"]
                name = str(rec.get("Company_Name") or rec.get("company_name") or defaults["Company_Name"]).strip() or \
                       defaults["Company_Name"]
                logo = str(rec.get("Company_Logo_URL") or rec.get("company_logo_url") or "").strip()
            else:
                row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

                tax_val = getattr(rec, "tax_rate", None)
                tax_raw = "" if tax_val is None else str(tax_val).strip()
                cur = str(getattr(rec, "currency_symbol", defaults["Currency_Symbol"]) or defaults[
                    "Currency_Symbol"]).strip() or defaults["Currency_Symbol"]
                name = str(
                    getattr(rec, "company_name", defaults["Company_Name"]) or defaults["Company_Name"]).strip() or \
                       defaults["Company_Name"]
                logo = str(getattr(rec, "company_logo_url", "") or "").strip()

            try:
                tax = float(tax_raw) if tax_raw != "" else defaults["Tax_Rate"]
            except Exception:
                tax = defaults["Tax_Rate"]

            return {
                "Workplace_ID": current_wp,
                "Tax_Rate": tax,
                "Currency_Symbol": cur,
                "Company_Name": name,
                "Company_Logo_URL": logo,
            }

        return defaults
    except Exception:
        return defaults


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
# Employees sheet: optional column "Site" that assigns an employee to a site name in Locations sheet.
# Locations sheet headers (recommended):
#   SiteName | Lat | Lon | RadiusMeters | Active
#
# WorkHours sheet (optional extra columns):
#   InLat, InLon, InAcc, InSite, InDistM, InSelfieURL, OutLat, OutLon, OutAcc, OutSite, OutDistM, OutSelfieURL

WORKHOURS_GEO_HEADERS = [
    "InLat", "InLon", "InAcc", "InSite", "InDistM", "InSelfieURL",
    "OutLat", "OutLon", "OutAcc", "OutSite", "OutDistM", "OutSelfieURL",
]


def _ensure_workhours_geo_headers():
    try:
        vals = work_sheet.get_all_values()
        if not vals:
            return
        headers = vals[0]
        base_headers = ["Username", "Date", "ClockIn", "ClockOut", "Hours", "Pay", "Workplace_ID"]
        # If there is no header row, do nothing (your sheet should have one).
        if not headers:
            return
        # Extend header row safely
        if len(headers) < len(base_headers):
            headers = base_headers[:]
        missing = [h for h in (["Workplace_ID"] + WORKHOURS_GEO_HEADERS) if h not in headers]
        if missing:
            headers = headers + missing
            work_sheet.update(f"A1:{gspread.utils.rowcol_to_a1(1, len(headers)).replace('1', '')}1", [headers])
    except Exception:
        return


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    # distance in meters
    from math import radians, sin, cos, asin, sqrt
    R = 6371000.0
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dl / 2) ** 2
    c = 2 * asin(sqrt(a))
    return R * c


def _get_employee_sites(username: str) -> list[str]:
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    def _normalize_sites(raw_values):
        sites = []
        for raw in raw_values:
            raw = (raw or "").strip()
            if not raw:
                continue
            for part in re.split(r"[;,]", raw):
                p = (part or "").strip()
                if p:
                    sites.append(p)

        seen = set()
        out = []
        for s in sites:
            key = s.lower()
            if key not in seen:
                seen.add(key)
                out.append(s)
        return out

    if DB_MIGRATION_MODE:
        try:
            rec = Employee.query.filter_by(username=username, workplace_id=current_wp).first()
            if not rec:
                rec = Employee.query.filter_by(email=username, workplace_id=current_wp).first()
            if rec:
                raw1 = str(getattr(rec, "site", "") or "").strip()
                raw2 = str(getattr(rec, "site2", "") or "").strip() if hasattr(rec, "site2") else ""
                return _normalize_sites([raw1, raw2])
        except Exception:
            pass

    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return []
        headers = vals[0]
        if "Username" not in headers:
            return []
        ucol = headers.index("Username")
        wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
        scol = headers.index("Site") if "Site" in headers else None
        s2col = headers.index("Site2") if "Site2" in headers else None

        for i in range(1, len(vals)):
            row = vals[i]
            if len(row) > ucol and (row[ucol] or "").strip() == username:
                if wp_col is not None:
                    row_wp = (row[wp_col] if len(row) > wp_col else "").strip() or "default"
                    if row_wp not in allowed_wps:
                        continue

                raw1 = (row[scol] or "").strip() if scol is not None and scol < len(row) else ""
                raw2 = (row[s2col] or "").strip() if s2col is not None and s2col < len(row) else ""
                return _normalize_sites([raw1, raw2])
    except Exception:
        return []

    return []


def _get_employee_site(username: str) -> str:
    """Backwards-compatible: return primary site (first) or empty."""
    sites = _get_employee_sites(username)
    return sites[0] if sites else ""


def _get_active_locations() -> list[dict]:
    out = []
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    if DB_MIGRATION_MODE:
        try:
            for rec in Location.query.all():
                row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

                name = str(getattr(rec, "site_name", "") or "").strip()
                active = str(getattr(rec, "active", "TRUE") or "TRUE").strip().upper()
                lat = safe_float(getattr(rec, "lat", None), None)
                lon = safe_float(getattr(rec, "lon", None), None)
                rad = safe_float(getattr(rec, "radius_meters", None), 0.0)

                if not name:
                    continue
                if active not in ("TRUE", "YES", "1"):
                    continue
                if lat is None or lon is None or rad <= 0:
                    continue

                out.append({"name": name, "lat": float(lat), "lon": float(lon), "radius": float(rad)})
            return out
        except Exception:
            pass

    if not locations_sheet:
        return out

    try:
        vals = locations_sheet.get_all_values()
        if not vals:
            return out
        headers = vals[0]

        def idx(n):
            return headers.index(n) if n in headers else None

        i_name = idx("SiteName")
        i_lat = idx("Lat")
        i_lon = idx("Lon")
        i_rad = idx("RadiusMeters")
        i_act = idx("Active")
        i_wp = idx("Workplace_ID")

        for r in vals[1:]:
            if i_wp is not None:
                row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

            name = (r[i_name] if i_name is not None and i_name < len(r) else "").strip()
            if not name:
                continue

            active = (r[i_act] if i_act is not None and i_act < len(r) else "TRUE").strip().upper()
            if active not in ("TRUE", "YES", "1"):
                continue

            lat = safe_float(r[i_lat] if i_lat is not None and i_lat < len(r) else "", None)
            lon = safe_float(r[i_lon] if i_lon is not None and i_lon < len(r) else "", None)
            rad = safe_float(r[i_rad] if i_rad is not None and i_rad < len(r) else "", 0.0)

            if lat is None or lon is None or rad <= 0:
                continue

            out.append({"name": name, "lat": float(lat), "lon": float(lon), "radius": float(rad)})
    except Exception:
        return []

    return out


def _get_site_config(site_name: str) -> dict | None:
    sites = _get_active_locations()
    if not sites:
        return None
    # exact match first
    for s in sites:
        if s["name"].strip().lower() == (site_name or "").strip().lower():
            return s
    # fallback: first active site
    return sites[0] if sites else None


def _sanitize_clock_geo(lat_v, lon_v, acc_v):
    if lat_v is None or lon_v is None:
        return lat_v, lon_v, acc_v
    lat_v = float(lat_v)
    lon_v = float(lon_v)
    if not (-90.0 <= lat_v <= 90.0) or not (-180.0 <= lon_v <= 180.0):
        raise RuntimeError("Invalid location coordinates.")
    if acc_v is not None:
        acc_v = float(acc_v)
        if acc_v < 0:
            raise RuntimeError("Invalid location accuracy.")
        if acc_v > MAX_CLOCK_LOCATION_ACCURACY_M:
            raise RuntimeError(
                f"Location accuracy is too low ({int(acc_v)}m). Move to an open area and try again."
            )
        acc_v = round(acc_v, 2)
    return round(lat_v, 8), round(lon_v, 8), acc_v


def _validate_recent_clock_capture(captured_at_raw: str, now_dt: datetime):
    raw = (captured_at_raw or "").strip()
    if not raw:
        raise RuntimeError("Fresh location capture is required. Please try again.")
    try:
        ts = float(raw)
    except Exception as exc:
        raise RuntimeError("Invalid location capture timestamp.") from exc
    if ts > 1e12:
        ts = ts / 1000.0
    age = abs(now_dt.timestamp() - ts)
    if age > MAX_CLOCK_LOCATION_AGE_S:
        raise RuntimeError("Location capture expired. Please try again.")


def _validate_user_location(username: str, lat: float | None, lon: float | None, acc_m: float | None = None) -> tuple[
    bool, dict, float]:
    """Returns (ok, site_cfg, distance_m).

    Behavior:
      - If employee has assigned site(s): validate against those sites (passes if inside ANY assigned site radius).
      - If no assigned site exists: fail closed. Clocking requires an explicit site assignment.
    """
    sites = _get_employee_sites(username)
    active_sites = _get_active_locations()

    if lat is None or lon is None:
        # no coordinates -> always fail (UI message explains)
        # choose a sensible cfg for messaging
        if sites:
            cfg = _get_site_config(sites[0]) or {"name": sites[0], "lat": 0.0, "lon": 0.0, "radius": 0.0}
        else:
            cfg = active_sites[0] if active_sites else {"name": "Unknown", "lat": 0.0, "lon": 0.0, "radius": 0.0}
        return False, cfg, 0.0

    latf, lonf = float(lat), float(lon)
    if not (-90.0 <= latf <= 90.0 and -180.0 <= lonf <= 180.0):
        raise RuntimeError("Invalid location data received. Please refresh and try again.")

    # GPS accuracy can be noisy (especially desktop / Wi‑Fi positioning).
    # If provided, allow a small uncertainty buffer so users don't get falsely blocked.
    try:
        acc_buf = float(acc_m) if acc_m is not None else 0.0
        if acc_buf < 0:
            acc_buf = 0.0
        if acc_buf > MAX_CLOCK_LOCATION_ACCURACY_M:
            raise RuntimeError(
                "Location accuracy is too low to verify this clock action. Move closer to the site and try again.")
    except RuntimeError:
        raise
    except Exception:
        acc_buf = 0.0

    def _inside(dist_m: float, radius_m: float) -> bool:
        # Cap buffer to avoid accidental huge values
        buf = min(max(acc_buf, 0.0), 2000.0)
        return dist_m <= (float(radius_m) + buf)

    # If no active sites configured at all -> fail
    if not active_sites:
        pref = sites[0] if sites else "Unknown"
        return False, {"name": pref, "lat": 0.0, "lon": 0.0, "radius": 0.0}, 0.0

    # Build candidate list from explicitly assigned sites only.
    if not sites:
        cfg = active_sites[0] if active_sites else {"name": "Unknown", "lat": 0.0, "lon": 0.0, "radius": 0.0}
        return False, cfg, 0.0

    candidates = []
    for sname in sites:
        cfg = _get_site_config(sname)
        if cfg:
            candidates.append(cfg)

    if not candidates:
        pref = sites[0] if sites else "Unknown"
        return False, {"name": pref, "lat": 0.0, "lon": 0.0, "radius": 0.0}, 0.0

    best_cfg = candidates[0]
    best_dist = _haversine_m(latf, lonf, best_cfg["lat"], best_cfg["lon"])
    best_ok = _inside(best_dist, float(best_cfg["radius"]))

    for cfg in candidates[1:]:
        dist = _haversine_m(latf, lonf, cfg["lat"], cfg["lon"])
        ok = _inside(dist, float(cfg["radius"]))
        if ok and (not best_ok or dist < best_dist):
            best_cfg, best_dist, best_ok = cfg, dist, ok
        elif (not best_ok) and dist < best_dist:
            best_cfg, best_dist, best_ok = cfg, dist, ok

    return bool(best_ok), best_cfg, float(best_dist)


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
    # Find the most recent row for this user where ClockOut is still blank.
    # Workplace-safe: if WorkHours has Workplace_ID, require it to match session workplace.
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
    u = (username or "").strip()
    if not u:
        return ""

    current_wp = _session_workplace_id()

    allowed_wps = set(_workplace_ids_for_read(current_wp))
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    if DB_MIGRATION_MODE:
        try:
            rec = Employee.query.filter(
                Employee.username == u,
                Employee.workplace_id.in_(list(allowed_wps))
            ).first()
            if not rec:
                rec = Employee.query.filter(
                    Employee.email == u,
                    Employee.workplace_id.in_(list(allowed_wps))
                ).first()

            if rec:
                first_name = str(getattr(rec, "first_name", "") or "").strip()
                last_name = str(getattr(rec, "last_name", "") or "").strip()
                full_name = str(getattr(rec, "name", "") or "").strip()

                display = (" ".join([first_name, last_name])).strip()
                return display or full_name or u
        except Exception:
            pass

    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return u

        headers = vals[0]
        if "Username" not in headers:
            return u

        ucol = headers.index("Username")
        wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
        fn_col = headers.index("FirstName") if "FirstName" in headers else None
        ln_col = headers.index("LastName") if "LastName" in headers else None

        for i in range(1, len(vals)):
            row = vals[i]
            row_user = (row[ucol] if len(row) > ucol else "").strip()
            if row_user != u:
                continue

            if wp_col is not None:
                row_wp = ((row[wp_col] if len(row) > wp_col else "").strip() or "default")
                if row_wp not in allowed_wps:
                    continue

            fn = row[fn_col] if fn_col is not None and fn_col < len(row) else ""
            ln = row[ln_col] if ln_col is not None and ln_col < len(row) else ""
            full = (fn + " " + ln).strip()
            return full or u

        return u
    except Exception:
        return u


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


@app.post("/admin/employees/reset-password")
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


@app.post("/admin/employees/clear-history")
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


@app.post("/admin/employees/delete")
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


@app.route("/admin/migrate-workplace-id", methods=["GET", "POST"])
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
        sensitive_last4 = {"NationalInsurance", "UTR", "BankAccountNumber", "SortCode"}
        if key in sensitive_full:
            return "[Hidden]"
        if key in sensitive_last4:
            tail = val[-4:] if len(val) >= 4 else val
            return f"••••{tail}"
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
PAYROLL_HEADERS = ["WeekStart", "WeekEnd", "Username", "Gross", "Tax", "Net", "PaidAt", "PaidBy", "Paid",
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


def _is_paid_for_week(week_start: str, week_end: str, username: str) -> tuple[bool, str]:
    """Return (is_paid, paid_at)."""
    try:
        _ensure_payroll_headers()
        vals = get_payroll_rows()
        if not vals or len(vals) < 2:
            return (False, "")
        headers = vals[0]

        def idx(name):
            return headers.index(name) if name in headers else None

        i_ws = idx("WeekStart");
        i_we = idx("WeekEnd");
        i_u = idx("Username");
        i_pa = idx("PaidAt");
        i_wp = idx("Workplace_ID")
        paid_at = ""
        current_wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(current_wp))

        for r in vals[1:]:
            ws = (r[i_ws] if i_ws is not None and i_ws < len(r) else "").strip()
            we = (r[i_we] if i_we is not None and i_we < len(r) else "").strip()
            uu = (r[i_u] if i_u is not None and i_u < len(r) else "").strip()
            wp = ((r[i_wp] if i_wp is not None and i_wp < len(r) else "").strip() or "default")

            if ws == week_start and we == week_end and uu == username and wp == current_wp:
                paid_at = (r[i_pa] if i_pa is not None and i_pa < len(r) else "").strip()
                return (paid_at != "", paid_at)
        return (False, "")
    except Exception:
        return (False, "")


# ================= NAV / LAYOUT =================
def bottom_nav(active: str, role: str) -> str:
    return ""


def sidebar_html(active: str, role: str) -> str:
    items = [
        ("home", "/", "Dashboard", _icon_dashboard(45)),
        ("clock", "/clock", "Clock In & Out", _icon_clock(45)),
        ("times", "/my-times", "Time logs", _icon_timelogs(45)),
        ("reports", "/my-reports", "Timesheets", _icon_timesheets(45)),
        ("payments", "/payments", "Payments", _icon_payments(45)),
    ]

    if role in ("admin", "master_admin"):
        items.append(("admin", "/admin", "Admin", _icon_admin(45)))

    if role == "master_admin":
        items.append(("workplaces", "/admin/workplaces", "Workplaces", _icon_workplaces(45)))

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
        <div class="sideMenuTitle">Menu</div>
        {''.join(links)}
      </div>
    """


def page_back_button(href: str | None = None, label: str = "Back") -> str:
    icon = '<span aria-hidden="true">‹</span>'
    if href:
        return f'<div class="pageBackRow"><a class="pageBackBtn" href="{escape(href)}" aria-label="{escape(label)}" title="{escape(label)}">{icon}</a></div>'
    return f'<div class="pageBackRow"><button type="button" class="pageBackBtn" aria-label="{escape(label)}" title="{escape(label)}" onclick="window.history.back()">{icon}</button></div>'


def layout_shell(active: str, role: str, content_html: str, shell_class: str = "") -> str:
    extra = f" {shell_class}" if shell_class else ""

    try:
        company_name = (get_company_settings().get("Company_Name") or "").strip() or "Main"
    except Exception:
        company_name = "Main"

    company_bar = f"""
      <div class="topBarFixed">
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
      {bottom_nav(active if active in ('home', 'clock', 'times', 'reports', 'profile', 'admin', 'workplaces') else 'home', role)}
    """


# ================= ROUTES =================
@app.get("/ping")
def ping():
    return "pong", 200


# ----- OAUTH CONNECT (ADMIN ONLY) -----
@app.get("/connect-drive")
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


@app.get("/oauth2callback")
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
@app.route("/login", methods=["GET", "POST"])
def login():
    msg = session.pop("_login_notice", "") if request.method == "GET" else ""
    csrf = get_csrf()

    if request.method == "POST":
        require_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        workplace_id = (request.form.get("workplace_id", "") or "").strip()

        login_usernames = [username]
        if username.lower() == "masteradmin":
            login_usernames = ["masteradmin", "master_admin"]
        elif username.lower() == "master_admin":
            login_usernames = ["master_admin", "masteradmin"]

        if not workplace_id:
            msg = "Workplace ID is required."
            ip = _client_ip()
        else:
            ip = _client_ip()

        if workplace_id:
            allowed, retry_after = _login_rate_limit_check(ip)
            if not allowed:
                log_audit("LOGIN_LOCKED", actor=ip, username=username, date_str="",
                          details=f"RetryAfter={retry_after}s")
                mins = max(1, int(math.ceil(retry_after / 60)))
                msg = f"Too many login attempts. Try again in {mins} minute(s)."
            else:
                ok_user = None
                if not DB_MIGRATION_MODE:
                    try:
                        sid = getattr(spreadsheet, "id", None)
                        wid = getattr(employees_sheet, "id", None)
                        if sid and wid:
                            _cache_invalidate_prefix((sid, wid))
                    except Exception:
                        pass

                ok_user = None
                matched_username = username
                for candidate_username in login_usernames:
                    ok_user = _find_employee_record(candidate_username, workplace_id)
                    if ok_user:
                        matched_username = candidate_username
                        break

                if ok_user and is_password_valid(ok_user.get("Password", ""), password):
                    active_raw = str(ok_user.get("Active", "") or "").strip().lower()
                    is_active = active_raw not in ("false", "0", "no", "n", "off")

                    if not is_active:
                        _login_rate_limit_hit(ip)
                        log_audit("LOGIN_INACTIVE", actor=ip, username=username, date_str="",
                                  details="Inactive account login attempt")
                        msg = "Invalid login"
                    else:
                        _login_rate_limit_clear(ip)

                        migrate_password_if_plain(matched_username, ok_user.get("Password", ""), password,
                                                  workplace_id=workplace_id)
                        active_session_token = _issue_active_session_token(matched_username, workplace_id)
                        if not active_session_token:
                            log_audit("LOGIN_SESSION_FAIL", actor=ip, username=matched_username, date_str="",
                                      details=f"Could not start active session workplace={workplace_id}")
                            msg = "Could not start secure session. Please try again."
                        else:
                            session.clear()
                            session["csrf"] = csrf
                            session["username"] = matched_username
                            session["workplace_id"] = workplace_id
                            session["role"] = (ok_user.get("Role", "employee") or "employee").strip().lower()
                            session["rate"] = safe_float(ok_user.get("Rate", 0), 0.0)
                            session["early_access"] = parse_bool(ok_user.get("EarlyAccess", False))
                            session["active_session_token"] = active_session_token
                            return redirect(url_for("home"))
                else:
                    _login_rate_limit_hit(ip)
                    log_audit("LOGIN_FAIL", actor=ip, username=username, date_str="",
                              details="Invalid username or password")
                    msg = "Invalid login"

    try:
        company_name = (get_company_settings().get("Company_Name") or "").strip() or "Main"
    except Exception:
        company_name = "Main"

    entered_username = (request.form.get("username", "") or "").strip() if request.method == "POST" else ""
    entered_workplace_id = (request.form.get("workplace_id", "") or "").strip() if request.method == "POST" else ""

    login_page_style = """
    <style>
      .loginShellPro{
        max-width: 760px;
        margin: 0 auto;
        padding: 22px 0 30px;
      }

      .loginCardPro{
        overflow: hidden;
        border-radius: 28px !important;
        border: 1px solid rgba(109,40,217,.10) !important;
        background:
          radial-gradient(circle at top right, rgba(109,40,217,.05), transparent 32%),
          radial-gradient(circle at top left, rgba(37,99,235,.05), transparent 28%),
          linear-gradient(180deg, #ffffff 0%, #fbfaff 100%) !important;
        box-shadow: 0 24px 60px rgba(41,25,86,.10) !important;
      }

      .loginHeroPro{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 18px;
        padding: 26px 28px 20px 28px;
        border-bottom: 1px solid rgba(109,40,217,.08);
        background: linear-gradient(180deg, rgba(255,255,255,.82), rgba(248,247,255,.96));
      }

      .loginEyebrow{
        display: inline-flex;
        align-items: center;
        padding: 8px 14px;
        border-radius: 999px;
        border: 1px solid rgba(109,40,217,.12);
        background: rgba(109,40,217,.06);
        color: #7c3aed;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: .05em;
        text-transform: uppercase;
      }

      .loginHeroPro h1{
        margin: 16px 0 10px 0;
        font-size: clamp(52px, 7vw, 74px);
        line-height: .95;
        letter-spacing: -.04em;
        color: #1f2547;
        font-weight: 900;
      }

      .loginLead{
        margin: 0;
        color: #6f6c85 !important;
        font-size: 18px;
        line-height: 1.65;
        max-width: 560px;
      }

      .loginHeroBadge{
        flex: 0 0 auto;
        align-self: flex-start;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 48px;
        padding: 0 18px;
        border-radius: 18px;
        border: 1px solid rgba(37,99,235,.10);
        background: linear-gradient(180deg, #f3f7ff, #edf2ff);
        color: #4f46e5;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: .05em;
        text-transform: uppercase;
        box-shadow: 0 8px 20px rgba(41,25,86,.06);
      }

      .loginFormWrap{
        padding: 26px 28px 28px 28px;
      }

      .loginSectionTitle{
        margin: 0 0 14px 0;
        color: #1f2547;
        font-size: 28px;
        font-weight: 800;
        letter-spacing: -.02em;
      }

      .loginFormGrid{
        display: grid;
        gap: 14px;
      }

      .loginFieldLabel{
        display: block;
        margin: 0 0 8px 0;
        color: #6f6c85;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: .02em;
      }

      .loginInput{
        margin-top: 0 !important;
        height: 56px !important;
        padding: 0 16px !important;
        border-radius: 18px !important;
        border: 1px solid rgba(109,40,217,.12) !important;
        background: #ffffff !important;
        color: #1f2547 !important;
        box-shadow: 0 6px 18px rgba(41,25,86,.04);
      }

      .loginInput::placeholder{
        color: #9a96ad;
      }

      .loginInput:focus{
        border-color: rgba(79,70,229,.35) !important;
        box-shadow: 0 0 0 4px rgba(109,40,217,.08), 0 8px 24px rgba(41,25,86,.08) !important;
        outline: none;
      }

      .loginPrimaryBtn{
        margin-top: 4px;
        width: 100%;
        min-height: 58px;
        border: 0;
        border-radius: 18px;
        background: linear-gradient(90deg, #2563eb, #5b8cff);
        color: #ffffff;
        font-size: 17px;
        font-weight: 800;
        letter-spacing: .01em;
        box-shadow: 0 14px 30px rgba(37,99,235,.20);
        transition: transform .18s ease, box-shadow .18s ease, filter .18s ease;
      }

      .loginPrimaryBtn:hover{
        transform: translateY(-1px);
        box-shadow: 0 18px 34px rgba(37,99,235,.24);
        filter: brightness(1.02);
      }

      .loginMessageWrap{
        margin-top: 16px;
      }

      .loginMetaGrid{
        margin-top: 20px;
        display: grid;
        grid-template-columns: repeat(3, minmax(0,1fr));
        gap: 12px;
      }

      .loginMetaCard{
        padding: 14px 16px;
        border-radius: 20px;
        border: 1px solid rgba(109,40,217,.10);
        background: linear-gradient(180deg, #ffffff, #f8f7ff);
        box-shadow: 0 10px 24px rgba(41,25,86,.06);
      }

      .loginMetaLabel{
        display: block;
        margin: 0 0 6px 0;
        color: #8a84a3;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .08em;
        text-transform: uppercase;
      }

      .loginMetaValue{
        display: block;
        color: #1f2547;
        font-size: 15px;
        font-weight: 800;
        line-height: 1.45;
      }

      .loginFooterNote{
        margin-top: 16px;
        color: #8a84a3;
        font-size: 14px;
        line-height: 1.65;
      }

      @media (max-width: 760px){
        .loginShellPro{
          max-width: 100%;
          padding-top: 10px;
        }

        .loginHeroPro{
          padding: 22px 20px 18px 20px;
          flex-direction: column;
          align-items: flex-start;
        }

        .loginHeroPro h1{
          font-size: 48px;
        }

        .loginFormWrap{
          padding: 20px;
        }

        .loginMetaGrid{
          grid-template-columns: 1fr;
        }
      }

      @media (max-width: 560px){
        .loginHeroPro h1{
          font-size: 40px;
        }

        .loginLead{
          font-size: 15px;
          line-height: 1.6;
        }

        .loginSectionTitle{
          font-size: 22px;
        }

        .loginInput{
          height: 54px !important;
        }

        .loginPrimaryBtn{
          min-height: 54px;
          font-size: 16px;
        }
      }
    </style>
    """

    html = f"""
    <div class="shell loginShellPro" style="grid-template-columns:1fr;">
      <div class="main">

        <div class="card loginCardPro">
          <div class="loginHeroPro">
            <div>
              <div class="loginEyebrow">Secure workforce access</div>
              <h1>WorkHours</h1>
              <p class="sub loginLead">Payroll, attendance and site clock-in in one secure workspace.</p>
            </div>
            <div class="loginHeroBadge">Secure sign in</div>
          </div>

          <div class="loginFormWrap">
            <div class="loginSectionTitle">Sign in to continue</div>
            <form method="POST" class="loginFormGrid" onsubmit="var f=this,ae=document.activeElement;if(ae&&ae.blur)ae.blur();window.scrollTo(0,0);setTimeout(f.submit.bind(f),180);return false;">
              <input type="hidden" name="csrf" value="{escape(csrf)}">

              <div>
                <label class="loginFieldLabel" for="login-username">Username</label>
                <input id="login-username" class="input loginInput" name="username" value="{escape(entered_username)}" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="Enter your username" required>
              </div>

              <div>
                <label class="loginFieldLabel" for="login-workplace">Workplace ID</label>
                <input id="login-workplace" class="input loginInput" name="workplace_id" value="{escape(entered_workplace_id)}" autocomplete="organization" autocapitalize="none" spellcheck="false" placeholder="e.g. newera" required>
              </div>

              <div>
                <label class="loginFieldLabel" for="login-password">Password</label>
                <input id="login-password" class="input loginInput" type="password" name="password" autocomplete="current-password" placeholder="Enter your password" required>
              </div>

              <button class="loginPrimaryBtn" type="submit">Sign in</button>
            </form>

            {("<div class='message error loginMessageWrap'>" + escape(msg) + "</div>") if msg else ""}

            <div class="loginMetaGrid">
              <div class="loginMetaCard">
                <span class="loginMetaLabel">Platform</span>
                <span class="loginMetaValue">Payroll and attendance workspace</span>
              </div>
              <div class="loginMetaCard">
                <span class="loginMetaLabel">Access</span>
                <span class="loginMetaValue">Role-based secure session</span>
              </div>
              <div class="loginMetaCard">
                <span class="loginMetaLabel">Sign-in</span>
                <span class="loginMetaValue">Use your workplace ID and password</span>
              </div>
            </div>

            <div class="loginFooterNote">Use the same credentials provided by your administrator. After sign-in you can access clock-in, timesheets and payroll tools based on your role.</div>
          </div>
        </div>
      </div>
    </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}{login_page_style}{html}")


@app.get("/logout")
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


@app.post("/logout")
def logout():
    require_csrf()
    username = (session.get("username") or "").strip()
    workplace_id = _session_workplace_id()
    active_session_token = str(session.get("active_session_token") or "")
    if username and active_session_token:
        _clear_active_session_token(username, workplace_id, expected_token=active_session_token)
    session.clear()
    return redirect(url_for("login"))


# ---------- DASHBOARD ----------
@app.get("/")
def home():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")

    now = datetime.now(TZ)
    today = now.date()
    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    monday = today - timedelta(days=today.weekday())

    def week_key_for_n(n: int):
        d2 = monday - timedelta(days=7 * n)
        yy, ww, _ = d2.isocalendar()
        return yy, ww

    dashboard_weeks = 8
    week_keys = [week_key_for_n(i) for i in range(dashboard_weeks - 1, -1, -1)]
    week_labels = [str(k[1]) for k in week_keys]
    weekly_gross = [0.0] * dashboard_weeks

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if len(r) <= COL_USER:
            continue
        row_user = (r[COL_USER] or "").strip()

        # Employees should see ONLY their own totals (Admin can see whole workplace)
        if role not in ("admin", "master_admin") and row_user != username:
            continue

        # Workplace filter (prefer WorkHours row Workplace_ID)
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            # Backward compat if WorkHours has no Workplace_ID column
            if not user_in_same_workplace(row_user):
                continue
        if not r[COL_PAY]:
            continue
        try:
            d = datetime.strptime(r[COL_DATE], "%Y-%m-%d").date()
            yy, ww, _ = d.isocalendar()
        except Exception:
            continue
        for idx, (yy2, ww2) in enumerate(week_keys):
            if yy == yy2 and ww == ww2:
                weekly_gross[idx] += safe_float(r[COL_PAY], 0.0)

    max_g = max(weekly_gross) if weekly_gross else 0.0
    max_g = max(max_g, 1.0)

    prev_gross = round(weekly_gross[-2], 2) if len(weekly_gross) >= 2 else 0.0
    curr_gross = round(weekly_gross[-1], 2)

    admin_item = ""
    if role in ("admin", "master_admin"):
        admin_item = f"""
        <a class="menuItem nav-admin" href="/admin">
          <div class="menuLeft"><div class="icoBox">{_icon_admin(22)}</div><div class="menuText">Admin</div></div>
          <div class="chev">›</div>
        </a>
        """

    workplaces_item = ""
    if role == "master_admin":
        workplaces_item = f"""
        <a class="menuItem nav-home" href="/admin/workplaces">
          <div class="menuLeft"><div class="icoBox">{_icon_workplaces(22)}</div><div class="menuText">Workplaces</div></div>
          <div class="chev">›</div>
        </a>
        """
    recent_rows = []
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if len(r) <= COL_USER:
            continue

        row_user = (r[COL_USER] or "").strip()

        if role not in ("admin", "master_admin") and row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(row_user):
                continue

        recent_rows.append({
            "date": (r[COL_DATE] if len(r) > COL_DATE else "") or "",
            "cin": (r[COL_IN] if len(r) > COL_IN else "") or "",
            "cout": (r[COL_OUT] if len(r) > COL_OUT else "") or "",
            "hours": (r[COL_HOURS] if len(r) > COL_HOURS else "") or "",
            "pay": (r[COL_PAY] if len(r) > COL_PAY else "") or "",
        })

    recent_rows = sorted(recent_rows, key=lambda x: x["date"], reverse=True)[:5]

    if recent_rows:
        activity_html = """
          <div class="activityRow activityHead">
            <div>Date</div><div>In</div><div>Out</div><div>Hours</div><div>Pay</div>
          </div>
        """
        for rr in recent_rows:
            activity_html += f"""
              <div class="activityRow">
                <div>{escape(rr['date'])}</div>
                <div>{escape((rr['cin'] or '')[:5])}</div>
                <div>{escape((rr['cout'] or '')[:5])}</div>
                <div>{escape(fmt_hours(rr['hours']))}</div>
                <div>{escape(currency)}{escape(rr['pay'])}</div>
              </div>
            """
    else:
        activity_html = "<div class='activityEmpty'>No recent activity yet.</div>"
    today_hours = 0.0
    today_pay = 0.0
    week_hours = 0.0
    week_days = set()

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if len(r) <= COL_USER:
            continue

        row_user = (r[COL_USER] or "").strip()

        if role not in ("admin", "master_admin") and row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(row_user):
                continue

        d_str = (r[COL_DATE] if len(r) > COL_DATE else "") or ""
        h_val = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        p_val = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        if d_str == today.strftime("%Y-%m-%d"):
            today_hours += h_val
            today_pay += p_val

        try:
            d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
            if d_obj >= monday:
                week_hours += h_val
                if h_val > 0:
                    week_days.add(d_str)
        except Exception:
            pass

    latest_user_date = None
    latest_user_open = False

    for r in rows[1:]:
        if len(r) <= COL_OUT or len(r) <= COL_USER or len(r) <= COL_DATE:
            continue

        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(row_user):
                continue

        d_str = (r[COL_DATE] or "").strip()
        if not d_str:
            continue

        try:
            d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        row_has_in = bool((r[COL_IN] or "").strip())
        row_has_out = bool((r[COL_OUT] or "").strip())
        row_is_open = row_has_in and not row_has_out

        if latest_user_date is None or d_obj >= latest_user_date:
            latest_user_date = d_obj
            latest_user_open = row_is_open

    is_clocked_in = latest_user_open
    status_text = "Clocked In" if is_clocked_in else "Clocked Out"
    status_class = "ok" if is_clocked_in else "warn"
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
        for s in _get_open_shifts():
            clocked_in_count += 1
    except Exception:
        pass

    try:
        active_locations_count = len(_get_active_locations())
    except Exception:
        active_locations_count = 0

    best_week_gross = max(weekly_gross) if weekly_gross else 0.0
    avg_weekly_gross = (sum(weekly_gross) / len(weekly_gross)) if weekly_gross else 0.0
    week_target_hours = 42.5
    week_progress_pct = 0
    if week_target_hours > 0:
        week_progress_pct = int(round(max(0.0, min(1.0, week_hours / week_target_hours)) * 100))
    team_metric_label = "Clocked In Now" if role in ("admin", "master_admin") else "Active Locations"
    team_metric_value = clocked_in_count if role in ("admin", "master_admin") else active_locations_count
    if prev_gross > 0:
        week_delta_pct = ((curr_gross - prev_gross) / prev_gross) * 100.0
    elif curr_gross > 0:
        week_delta_pct = 100.0
    else:
        week_delta_pct = 0.0

    def _nice_chart_axis_max(value: float) -> float:
        try:
            value = float(value or 0.0)
        except Exception:
            value = 0.0
        if value <= 0:
            return 1000.0
        scaled = value * 1.15
        power = 10 ** math.floor(math.log10(scaled))
        normalized = scaled / power
        if normalized <= 1:
            nice = 1
        elif normalized <= 1.5:
            nice = 1.5
        elif normalized <= 2:
            nice = 2
        elif normalized <= 2.5:
            nice = 2.5
        elif normalized <= 5:
            nice = 5
        else:
            nice = 10
        return nice * power

    def _fmt_chart_tick(value: float) -> str:
        try:
            value = float(value or 0.0)
        except Exception:
            value = 0.0
        if abs(value) < 1e-9:
            return "0.0"
        if abs(value - round(value)) < 1e-9:
            return str(int(round(value)))
        return f"{value:.1f}".rstrip("0").rstrip(".")

    chart_week_labels = week_labels[-5:] if len(week_labels) >= 5 else list(week_labels)
    chart_weekly_gross = weekly_gross[-5:] if len(weekly_gross) >= 5 else list(weekly_gross)
    chart_y_max = _nice_chart_axis_max(max(chart_weekly_gross) if chart_weekly_gross else 0.0)
    chart_tick_values = [round(chart_y_max * (i / 5.0), 1) for i in range(5, -1, -1)]
    chart_ticks_html = "".join(
        f'<div class=\"grossChartTick\"><span>{escape(_fmt_chart_tick(v))}</span></div>'
        for v in chart_tick_values
    )
    chart_grid_html = "".join(
        f'<div class=\"grossChartGridLine\" style=\"bottom:{int((i / 5.0) * 100)}%;\"></div>'
        for i in range(6)
    )

    chart_bar_parts = []
    for lbl, gross in zip(chart_week_labels, chart_weekly_gross):
        try:
            gross_val = float(gross or 0.0)
        except Exception:
            gross_val = 0.0
        bar_pct = 0.0 if chart_y_max <= 0 else max(0.0, min(100.0, (gross_val / chart_y_max) * 100.0))
        if gross_val > 0 and bar_pct < 6.0:
            bar_pct = 6.0
        chart_bar_parts.append(
            f"<div class='grossChartBarCol'><div class='grossChartBarWrap'><div class='grossChartBar' style='height:{bar_pct:.2f}%;'></div></div><div class='grossChartBarLabel'>{escape(lbl)}</div></div>"
        )
    chart_bars_html = "".join(chart_bar_parts)

    chart_delta_text = ("+" if week_delta_pct > 0 else "") + f"{int(round(week_delta_pct))}%"
    chart_delta_class = "up" if week_delta_pct >= 0 else "down"
    chart_range_label = f"Weeks {chart_week_labels[0]} – {chart_week_labels[-1]}" if chart_week_labels else "Weeks"

    chart_section_html = f"""
      <div class=\"grossChartCard plainSection\">
        <div class=\"grossChartSummaryRow\">
          <div class=\"grossSummaryBox\">
            <div class=\"grossSummaryLabel\">Previous Gross</div>
            <div class=\"grossSummaryValue\">{escape(currency)}{money(prev_gross)}</div>
          </div>

          <div class=\"grossSummaryBox\">
            <div class=\"grossSummaryLabel\">Current Gross</div>
            <div class=\"grossSummaryValue\">{escape(currency)}{money(curr_gross)}</div>
            <div class=\"grossSummaryDelta {chart_delta_class}\">{chart_delta_text}</div>
          </div>
        </div>

        <div class=\"grossChartNav\">
          <div class=\"grossChartArrow\">‹</div>
          <div class=\"grossChartRangeTitle\">{escape(chart_range_label)}</div>
          <div class=\"grossChartArrow\" style=\"opacity:.55;\">›</div>
        </div>

        <div class=\"grossChartPlot\">
          <div class=\"grossChartYAxis\">
            {chart_ticks_html}
          </div>

          <div class=\"grossChartCanvas\">
            {chart_grid_html}
            <div class=\"grossChartBars\">
              {chart_bars_html}
            </div>
          </div>
        </div>
      </div>
    """

    snapshot_html = ""
    if role in ("admin", "master_admin"):
        snapshot_html = f"""
          <div class="sideInfoCard plainSection">
            <div class="sectionHead">
              <div class="sectionHeadLeft">
                <div class="sectionIcon">{_svg_grid()}</div>
                <div>
                  <h2 style="margin:0;">Business Snapshot</h2>
                  <p class="sub" style="margin:4px 0 0 0;">Live workforce and workplace setup overview.</p>
                </div>
              </div>
              <div class="sectionBadge">Live</div>
            </div>

            <div class="sideInfoList">
              <div class="sideInfoRow">
                <div class="sideInfoLabel">Employees</div>
                <div class="sideInfoValue">{employee_count}</div>
              </div>

              <div class="sideInfoRow">
                <div class="sideInfoLabel">Clocked In Now</div>
                <div class="sideInfoValue">{clocked_in_count}</div>
              </div>

              <div class="sideInfoRow">
                <div class="sideInfoLabel">Active Locations</div>
                <div class="sideInfoValue">{active_locations_count}</div>
              </div>

              <div class="sideInfoRow">
                <div class="sideInfoLabel">Onboarding Pending</div>
                <div class="sideInfoValue">{onboarding_pending_count}</div>
              </div>
            </div>

            <div class="snapshotFoot">Monitor staffing, access setup and onboarding completion from one place.</div>
          </div>
        """

    content = f"""
      <div class="dashboardHero">
  <div class="dashboardHeroMain">
    <h1>Dashboard</h1>
  </div>
  <div class="dashboardHeroMeta">
    <div class="badge {'admin' if role in ('admin', 'master_admin') else ''}">{escape(role_label(role))}</div>
    <div class="dashboardDateChip">{escape(now.strftime("%A • %d %b %Y"))}</div>
  </div>
</div>

      {chart_section_html}

      <div class="dashboardLower">
        <div class="quickCard plainSection">
          <div class="sectionHead">
            <div class="sectionHeadLeft">
              <div class="sectionIcon">{_svg_clock()}</div>
              <div>
                <h2 style="margin:0;">Today&apos;s Summary</h2>
                <p class="sub" style="margin:4px 0 0 0;">Live attendance and pay summary for this workplace.</p>
              </div>
            </div>
            <div class="sectionBadge">This week</div>
          </div>

          <div class="quickGrid">
            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_clock()}</div>
                <div class="miniText">Status</div>
              </div>
              <div class="chip {status_class}">{status_text}</div>
            </div>

            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_clipboard()}</div>
                <div class="miniText">Today Hours</div>
              </div>
              <div class="miniText">{fmt_hours(today_hours)}</div>
            </div>

            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_chart()}</div>
                <div class="miniText">Today Gross</div>
              </div>
              <div class="miniText">{escape(currency)}{money(today_pay)}</div>
            </div>

            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_grid()}</div>
                <div class="miniText">Week Hours</div>
              </div>
              <div class="miniText">{fmt_hours(week_hours)}</div>
            </div>

            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_doc()}</div>
                <div class="miniText">Days Logged</div>
              </div>
              <div class="miniText">{len(week_days)}</div>
            </div>

            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_grid()}</div>
                <div class="miniText">{team_metric_label}</div>
              </div>
              <div class="miniText">{team_metric_value}</div>
            </div>
          </div>

          <div class="dashboardProgressRow">
  <div class="dashboardProgressMeta">
    <span>Weekly hours progress • {fmt_hours(week_hours)} / {fmt_hours(week_target_hours)}</span>
    <strong>{week_progress_pct}%</strong>
  </div>
  <div class="dashboardProgressBar">
    <span style="width:{week_progress_pct}%;"></span>
  </div>
</div>
        </div>
      </div>

      <div class="dashboardBottom">
        <div class="activityCard plainSection">
          <div class="sectionHead">
            <div class="sectionHeadLeft">
              <div class="sectionIcon">{_svg_clipboard()}</div>
              <div>
                <h2 style="margin:0;">Recent Activity</h2>
                <p class="sub" style="margin:4px 0 0 0;">Latest logged work entries.</p>
              </div>
            </div>
            <div class="sectionBadge">Last 5 rows</div>
          </div>

          <div class="activityList">
            {activity_html}
          </div>
        </div>

        {snapshot_html}
      </div>

      <div class="card menu dashboardMainMenu">
  <div class="sectionHead dashboardMenuHead" style="display:none;"></div>

        <div class="dashboardShortcutGrid">
          <a class="menuItem nav-clock" href="/clock">
            <div class="menuLeft"><div class="icoBox">{_icon_clock(22)}</div><div class="menuText">Clock In & Out</div></div>
            <div class="chev">›</div>
          </a>
          <a class="menuItem nav-times" href="/my-times">
            <div class="menuLeft"><div class="icoBox">{_icon_timelogs(22)}</div><div class="menuText">Time logs</div></div>
            <div class="chev">›</div>
          </a>
          <a class="menuItem nav-reports" href="/my-reports">
  <div class="menuLeft"><div class="icoBox">{_icon_timesheets(22)}</div><div class="menuText">Timesheets</div></div>
  <div class="chev">›</div>
</a>
<a class="menuItem nav-payments" href="/payments">
  <div class="menuLeft"><div class="icoBox">{_icon_payments(22)}</div><div class="menuText">Payments</div></div>
  <div class="chev">›</div>
</a>
<a class="menuItem nav-agreements" href="/onboarding">
  <div class="menuLeft"><div class="icoBox">{_icon_starter_form(22)}</div><div class="menuText">Starter Form</div></div>
  <div class="chev">›</div>
</a>
          {admin_item}
          {workplaces_item}
          <a class="menuItem nav-profile" href="/password">
            <div class="menuLeft"><div class="icoBox">{_icon_profile(22)}</div><div class="menuText">Profile</div></div>
            <div class="chev">›</div>
          </a>
        </div>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("home", role, content))


# ---------- CLOCK PAGE ----------
@app.route("/clock", methods=["GET", "POST"])
def clock_page():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

    rate = _get_user_rate(username)
    early_access = bool(session.get("early_access", False))
    try:
        live_user = _find_employee_record(username, _session_workplace_id())
        if live_user:
            early_access = parse_bool(live_user.get("EarlyAccess", early_access))
            session["early_access"] = early_access
    except Exception:
        pass

    now = datetime.now(TZ)
    today_str = now.strftime("%Y-%m-%d")

    # Geo-fence config (employee assigned site -> Locations sheet)
    _ensure_workhours_geo_headers()
    site_pref = _get_employee_site(username)
    site_cfg = _get_site_config(site_pref)  # may be None

    msg = ""
    msg_class = "message"

    def _read_float(name):
        try:
            v = (request.form.get(name) or "").strip()
            return float(v) if v else None
        except Exception:
            return None

    if request.method == "POST":
        require_csrf()
        action = (request.form.get("action") or "").strip()
        selfie_data = (request.form.get("selfie_data") or "").strip()

        if CLOCK_SELFIE_REQUIRED and action in ("in", "out") and not selfie_data:
            msg = "Selfie is required before clocking in or out."
            msg_class = "message error"
        else:
            lat_v = _read_float("lat")
            lon_v = _read_float("lon")
            acc_v = _read_float("acc")

            try:
                if lat_v is not None and lon_v is not None:
                    _validate_recent_clock_capture(request.form.get("geo_ts"), now)
                    lat_v, lon_v, acc_v = _sanitize_clock_geo(lat_v, lon_v, acc_v)
                ok_loc, cfg, dist_m = _validate_user_location(username, lat_v, lon_v, acc_v)

                if not ok_loc:
                    if (not _get_employee_sites(username)) and _get_active_locations():
                        msg = "No site is assigned to your account. Ask Admin to assign your site first."
                    elif not site_cfg and not cfg.get("radius"):
                        msg = "Location system is not configured. Ask Admin to create Locations and set your site."
                    elif lat_v is None or lon_v is None:
                        msg = "Location is required. Please allow location access and try again."
                    else:
                        msg = f"Outside site radius. Distance: {int(dist_m)}m (limit {int(cfg['radius'])}m) • Site: {cfg['name']}"
                    msg_class = "message error"
                else:
                    rows = work_sheet.get_all_values()

                    if action == "in":
                        open_shift = find_open_shift(rows, username)

                        if open_shift:
                            msg = "You are already clocked in."
                            msg_class = "message error"

                        elif has_any_row_today(rows, username, today_str):
                            msg = "You already completed your shift for today."
                            msg_class = "message error"

                        else:
                            selfie_url = _store_clock_selfie(selfie_data, username, "clock_in",
                                                             now) if CLOCK_SELFIE_REQUIRED else ""
                            cin = normalized_clock_in_time(now, early_access)

                            headers_now = work_sheet.row_values(1)
                            new_row = [username, today_str, cin, "", "", ""]

                            if headers_now and "Workplace_ID" in headers_now:
                                wp_idx = headers_now.index("Workplace_ID")
                                if len(new_row) <= wp_idx:
                                    new_row += [""] * (wp_idx + 1 - len(new_row))
                                new_row[wp_idx] = _session_workplace_id()

                            if headers_now and len(new_row) < len(headers_now):
                                new_row += [""] * (len(headers_now) - len(new_row))

                            _gs_write_with_retry(
                                lambda: work_sheet.append_row(new_row, value_input_option="USER_ENTERED"))

                            vals = work_sheet.get_all_values()
                            rownum = _find_workhours_row_by_user_date(vals, username, today_str)
                            if rownum:
                                headers = vals[0] if vals else []

                                def _col(name):
                                    return headers.index(name) + 1 if name in headers else None

                                import copy

                                updates = []
                                for k, v in [
                                    ("InLat", lat_v), ("InLon", lon_v), ("InAcc", acc_v),
                                    ("InSite", cfg.get("name", "")), ("InDistM", int(dist_m)),
                                    ("InSelfieURL", selfie_url), ("Workplace_ID", _session_workplace_id()),
                                ]:
                                    c = _col(k)
                                    if c:
                                        updates.append({
                                            "range": gspread.utils.rowcol_to_a1(rownum, c),
                                            "values": [["" if v is None else v]],
                                        })

                                if updates:
                                    _gs_write_with_retry(lambda: work_sheet.batch_update(copy.deepcopy(updates)))

                                if DB_MIGRATION_MODE:
                                    try:
                                        shift_date = datetime.strptime(today_str, "%Y-%m-%d").date()
                                        clock_in_dt = datetime.strptime(f"{today_str} {cin}", "%Y-%m-%d %H:%M:%S")

                                        db_row = WorkHour.query.filter(
                                            WorkHour.employee_email == username,
                                            WorkHour.date == shift_date,
                                            or_(WorkHour.workplace_id == _session_workplace_id(),
                                                WorkHour.workplace == _session_workplace_id()),
                                        ).order_by(WorkHour.id.desc()).first()

                                        if db_row:
                                            db_row.clock_in = clock_in_dt
                                            db_row.clock_out = None
                                            db_row.in_selfie_url = selfie_url
                                        else:
                                            db.session.add(
                                                WorkHour(
                                                    employee_email=username,
                                                    date=shift_date,
                                                    clock_in=clock_in_dt,
                                                    clock_out=None,
                                                    workplace=_session_workplace_id(),
                                                    workplace_id=_session_workplace_id(),
                                                    in_selfie_url=selfie_url,
                                                )
                                            )

                                        db.session.commit()
                                    except Exception:
                                        db.session.rollback()

                            if (not early_access) and (now.time() < CLOCKIN_EARLIEST):
                                msg = f"Clocked in successfully (counted from 08:00) • {cfg['name']} ({int(dist_m)}m)"
                            else:
                                msg = f"Clocked in successfully • {cfg['name']} ({int(dist_m)}m)"

                    elif action == "out":
                        osf = find_open_shift(rows, username)

                        if not osf:
                            if has_any_row_today(rows, username, today_str):
                                msg = "You already clocked out today."
                            else:
                                msg = "No active shift found."
                            msg_class = "message error"

                        else:
                            selfie_url = _store_clock_selfie(selfie_data, username, "clock_out",
                                                             now) if CLOCK_SELFIE_REQUIRED else ""
                            i, d, t = osf
                            cin_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
                            raw_hours = max(0.0, (now - cin_dt).total_seconds() / 3600.0)
                            hours_rounded = _round_to_half_hour(_apply_unpaid_break(raw_hours))
                            pay = round(hours_rounded * float(rate), 2)

                            sheet_row = i + 1
                            cout = now.strftime("%H:%M:%S")

                            updates = [
                                {
                                    "range": f"{gspread.utils.rowcol_to_a1(sheet_row, COL_OUT + 1)}:{gspread.utils.rowcol_to_a1(sheet_row, COL_PAY + 1)}",
                                    "values": [[cout, hours_rounded, pay]],
                                }
                            ]

                            vals = work_sheet.get_all_values()
                            headers = vals[0] if vals else []

                            def _col(name):
                                return headers.index(name) + 1 if name in headers else None

                            for k, v in [
                                ("OutLat", lat_v), ("OutLon", lon_v), ("OutAcc", acc_v),
                                ("OutSite", cfg.get("name", "")), ("OutDistM", int(dist_m)),
                                ("OutSelfieURL", selfie_url),
                            ]:
                                c = _col(k)
                                if c:
                                    updates.append({
                                        "range": gspread.utils.rowcol_to_a1(sheet_row, c),
                                        "values": [["" if v is None else str(v)]],
                                    })

                            import copy
                            if updates:
                                _gs_write_with_retry(lambda: work_sheet.batch_update(copy.deepcopy(updates)))

                            if DB_MIGRATION_MODE:
                                try:
                                    shift_date = datetime.strptime(d, "%Y-%m-%d").date()
                                    clock_out_dt = datetime.strptime(f"{d} {cout}", "%Y-%m-%d %H:%M:%S")
                                    clock_in_dt_check = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")

                                    if clock_out_dt < clock_in_dt_check:
                                        clock_out_dt = clock_out_dt + timedelta(days=1)

                                    db_row = WorkHour.query.filter(
                                        WorkHour.employee_email == username,
                                        WorkHour.date == shift_date,
                                        or_(WorkHour.workplace_id == _session_workplace_id(),
                                            WorkHour.workplace == _session_workplace_id()),
                                    ).order_by(WorkHour.id.desc()).first()

                                    if db_row:
                                        db_row.clock_out = clock_out_dt
                                        db_row.out_selfie_url = selfie_url
                                    else:
                                        db.session.add(
                                            WorkHour(
                                                employee_email=username,
                                                date=shift_date,
                                                clock_in=None,
                                                clock_out=clock_out_dt,
                                                workplace=_session_workplace_id(),
                                                workplace_id=_session_workplace_id(),
                                                out_selfie_url=selfie_url,
                                            )
                                        )

                                    db.session.commit()
                                except Exception:
                                    db.session.rollback()

                            msg = f"Clocked out successfully • {cfg['name']} ({int(dist_m)}m) • Total today: {hours_rounded:.2f}h"

                    else:
                        msg = "Invalid action."
                        msg_class = "message error"
            except Exception as e:
                if isinstance(e, RuntimeError):
                    msg = str(e) or "Unable to process selfie."
                    msg_class = "message error"
                else:
                    app.logger.exception("Clock POST failed")
                    msg = "Internal error while saving. Please refresh and try again."
                    msg_class = "message error"

    # Active shift timer
    rows2 = get_workhours_rows()
    osf2 = find_open_shift(rows2, username)
    active_start_iso = ""
    active_start_label = ""
    if osf2:
        _, d, t = osf2
        try:
            start_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
            active_start_iso = start_dt.isoformat()
            active_start_label = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    if active_start_iso:
        timer_html = f"""
        <div class="clockStatus clockStatusLive">Clocked in</div>
        <div class="timerBig" id="timerDisplay">00:00:00</div>
        <div class="clockHint">Started at {escape(active_start_label)}</div>
        <div class="timerSub">
          <span class="chip ok" id="otChip">Normal</span>
        </div>
        <script>
          (function() {{
            const startIso = "{escape(active_start_iso)}";
            const start = new Date(startIso);
            const el = document.getElementById("timerDisplay");
            function pad(n) {{ return String(n).padStart(2, "0"); }}
            function tick() {{
              const now = new Date();
              let diff = Math.floor((now - start) / 1000);
              if (diff < 0) diff = 0;
              const h = Math.floor(diff / 3600);
              const m = Math.floor((diff % 3600) / 60);
              const s = diff % 60;
              el.textContent = pad(h) + ":" + pad(m) + ":" + pad(s);

              const otEl = document.getElementById("otChip");
              if (otEl) {{
                const startedAtEight = (start.getHours() === 8 && start.getMinutes() === 0);
                const overtime = startedAtEight && (diff >= 9 * 3600);
                if (overtime) {{
                  otEl.textContent = "Overtime";
                  otEl.className = "chip warn";
                }} else {{
                  otEl.textContent = "Normal";
                  otEl.className = "chip ok";
                }}
              }}
            }}
            tick(); setInterval(tick, 1000);
          }})();
        </script>
        """
    else:
        timer_html = f"""
        <div class="clockStatus clockStatusIdle">Not clocked in</div>
        <div class="timerBig">00:00:00</div>
        <div class="clockHint">Tap Clock In to start your shift.</div>
        """

    # Map config for front-end (if site configured)
    if site_cfg:
        site_json = json.dumps(
            {"name": site_cfg["name"], "lat": site_cfg["lat"], "lon": site_cfg["lon"], "radius": site_cfg["radius"]})
    else:
        site_json = json.dumps(None)

    leaflet_tags = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin=""/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
"""

    company_name = str(get_company_settings().get("Company_Name") or "Main").strip() or "Main"
    msg_html = ""
    if msg:
        msg_state = "ok" if msg_class != "message error" else ""
        msg_html = f'<div class="clockInlineMsg {msg_state}">{escape(msg)}</div>'

    content = f"""
      {leaflet_tags}
      <style>
        .clockFlowWrap {{
  position: relative;
  max-width: 860px;
  margin: 0 auto;
  padding: 18px 0 10px;
}}

.clockInlineMsg {{
  margin: 0 0 18px;
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid rgba(220,38,38,.16);
  background: linear-gradient(180deg, #fff5f5, #ffffff);
  color: #b91c1c;
  box-shadow: 0 10px 24px rgba(41,25,86,.08);
}}

.clockInlineMsg.ok {{
  border-color: rgba(22,163,74,.18);
  background: linear-gradient(180deg, #f0fdf4, #ffffff);
  color: #166534;
}}

.clockStep {{
  padding: 28px 22px 30px;
  border-radius: 30px;
  border: 1px solid rgba(109,40,217,.10);
  background:
    radial-gradient(circle at top right, rgba(109,40,217,.05), transparent 34%),
    radial-gradient(circle at top left, rgba(37,99,235,.05), transparent 30%),
    linear-gradient(180deg, #ffffff 0%, #fbfaff 100%);
  box-shadow: 0 18px 42px rgba(41,25,86,.10);
}}

.clockStepLabel {{
  text-align: center;
  color: #2563eb;
  font-size: 17px;
  font-weight: 800;
  letter-spacing: .02em;
  margin-bottom: 12px;
}}

.clockHeroTitle {{
  margin: 0 0 12px;
  text-align: center;
  color: #1f2547;
  font-size: clamp(32px, 5vw, 44px);
  line-height: 1.06;
  font-weight: 900;
}}

.clockStageCard {{
  border-radius: 24px;
  border: 1px solid rgba(109,40,217,.10);
  overflow: hidden;
  background: #ffffff;
  box-shadow: 0 14px 34px rgba(41,25,86,.08);
}}

.clockSelfieStage {{
  position: relative;
  min-height: 320px;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at center, rgba(37,99,235,.05), transparent 52%),
    linear-gradient(180deg, #fcfcff, #f4f7ff);
}}

.clockSelfiePlaceholder {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #4338ca;
  opacity: .96;
  text-align: center;
}}

.clockSelfiePlaceholderIcon {{
  font-size: 76px;
  line-height: 1;
}}

.clockSelfiePlaceholderText {{
  font-size: 15px;
  color: #6f6c85;
  max-width: 420px;
}}

.clockSelfieVideo {{
  display: none;
  width: 100%;
  min-height: 320px;
  border-radius: 18px;
  object-fit: cover;
  background: #e9eefb;
  border: 1px solid rgba(109,40,217,.10);
}}

.clockCaptureBar {{
  display: flex;
  gap: 12px;
  padding: 18px;
  align-items: center;
  background: linear-gradient(180deg, #ffffff, #f8f9ff);
  border-top: 1px solid rgba(109,40,217,.08);
}}

.clockPrimaryBtn,
.clockPrimaryAction,
.clockSecondaryAction,
.clockGhostBtn {{
  border: 0;
  border-radius: 18px;
  font-weight: 800;
  transition: transform .18s ease, box-shadow .18s ease, opacity .18s ease, filter .18s ease;
}}

.clockPrimaryBtn,
.clockPrimaryAction {{
  background: linear-gradient(90deg, #6d28d9, #2563eb);
  color: #ffffff;
  box-shadow: 0 12px 26px rgba(79,70,229,.22);
}}

.clockPrimaryBtn:hover,
.clockPrimaryAction:hover,
.clockSecondaryAction:hover,
.clockGhostBtn:hover {{
  transform: translateY(-1px);
  filter: brightness(1.03);
}}

.clockPrimaryBtn {{
  display: inline-flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 14px;
  min-height: 72px;
  font-size: 20px;
}}

.clockPrimaryBtnArrow {{
  font-size: 34px;
  line-height: 1;
  margin-top: -1px;
}}

.clockGhostBtn {{
  min-width: 128px;
  min-height: 72px;
  padding: 0 22px;
  background: #f8f7ff;
  color: #6d28d9;
  border: 1px solid rgba(109,40,217,.12);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.8);
}}

.clockDistanceAlert {{
  margin: 20px auto 16px;
  max-width: 520px;
  padding: 14px 18px;
  border-radius: 18px;
  text-align: center;
  border: 1px solid rgba(220,38,38,.14);
  background: linear-gradient(180deg, #fff7f7, #ffffff);
  box-shadow: 0 10px 24px rgba(41,25,86,.06);
}}

.clockDistanceAlertTitle {{
  font-size: 18px;
  font-weight: 800;
  color: #dc2626;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}}

.clockDistanceAlertMeta {{
  margin-top: 5px;
  font-size: 15px;
  color: #6f6c85;
}}

.clockDistanceAlert.is-ok {{
  border-color: rgba(22,163,74,.18);
  background: linear-gradient(180deg, #f0fdf4, #ffffff);
}}

.clockDistanceAlert.is-ok .clockDistanceAlertTitle {{
  color: #15803d;
}}

.clockDistanceAlert.is-ok .clockDistanceAlertMeta {{
  color: #166534;
}}

.clockMapShell {{
  border-radius: 24px;
  overflow: hidden;
  border: 1px solid rgba(109,40,217,.10);
  box-shadow: 0 14px 30px rgba(41,25,86,.08);
  background: #ffffff;
}}

.clockFooterNote {{
  margin: 18px 6px 0;
  text-align: center;
  color: #6f6c85;
  font-size: 15px;
}}

.clockFooterNote strong {{
  color: #26233a;
}}

.clockHidden {{
  display: none !important;
}}

.clockStepTwo {{
  display: none;
  text-align: center;
  padding-top: 10px;
}}

.clockCapturedRow {{
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: #26233a;
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 22px;
}}

.clockCapturedIcon {{
  width: 32px;
  height: 32px;
  display: inline-grid;
  place-items: center;
  border-radius: 999px;
  background: rgba(109,40,217,.10);
  color: #6d28d9;
  font-size: 18px;
  font-weight: 900;
}}

.clockFinalSelfie {{
  width: min(220px, 52vw);
  aspect-ratio: 1 / 1;
  margin: 0 auto 28px;
  border-radius: 22px;
  object-fit: cover;
  background: #ffffff;
  border: 1px solid rgba(109,40,217,.10);
  box-shadow: 0 14px 30px rgba(41,25,86,.10);
  display: none;
}}

.clockTimerStage {{
  margin: 0 auto 24px;
  max-width: 540px;
  padding: 8px 0 0;
}}

.clockTimerStage .clockStatusIdle,
.clockTimerStage .clockStatusLive {{
  background: transparent !important;
  color: #2563eb !important;
  font-size: 16px !important;
  font-weight: 700 !important;
  margin-bottom: 10px !important;
  padding: 0 !important;
  border: 0 !important;
  box-shadow: none !important;
}}

.clockTimerStage .timerBig {{
  font-size: clamp(54px, 11vw, 80px) !important;
  line-height: 1 !important;
  letter-spacing: 1.5px !important;
  color: #26233a !important;
  margin: 0 !important;
  font-weight: 800 !important;
}}

.clockTimerStage .clockHint {{
  margin-top: 12px !important;
  color: #6f6c85 !important;
  font-size: 14px !important;
}}

.clockTimerStage .timerSub {{
  margin-top: 12px !important;
}}

.clockActionStack {{
  max-width: 560px;
  margin: 0 auto;
  display: grid;
  gap: 14px;
}}

.clockPrimaryAction,
.clockSecondaryAction {{
  width: 100%;
  min-height: 82px;
  font-size: clamp(22px, 4vw, 28px);
  letter-spacing: .04em;
  text-transform: uppercase;
}}

.clockSecondaryAction {{
  background: #ffffff;
  color: #2563eb;
  border: 1px solid rgba(37,99,235,.14);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.78);
}}

.clockSecondaryAction[disabled],
.clockGhostBtn[disabled] {{
  opacity: .5;
  cursor: not-allowed;
  transform: none;
}}

.clockTextLink {{
  display: inline-block;
  margin-top: 18px;
  color: #6d28d9;
  font-weight: 700;
  text-decoration: none;
}}

.clockBackLink {{
  margin-top: 16px;
  background: transparent;
  border: 0;
  color: #6d28d9;
  font-weight: 700;
  cursor: pointer;
}}

.clockMetaText {{
  margin-top: 14px;
  color: #6f6c85;
  font-size: 14px;
  text-align: center;
}}

@media (max-width: 640px) {{
  .clockFlowWrap {{ padding-top: 10px; }}
  .clockStep {{
    padding: 22px 14px 24px;
    border-radius: 24px;
  }}
  .clockHeroTitle {{
    font-size: 28px;
    margin-bottom: 16px;
  }}
  .clockSelfieStage {{
    min-height: 240px;
    padding: 16px;
  }}
  .clockSelfieVideo {{
    min-height: 240px;
  }}
  .clockCaptureBar {{
    flex-direction: column;
  }}
  .clockGhostBtn {{
    width: 100%;
    min-height: 58px;
  }}
  .clockPrimaryBtn {{
    min-height: 62px;
    font-size: 18px;
  }}
  .clockPrimaryAction,
  .clockSecondaryAction {{
    min-height: 72px;
    font-size: 20px;
  }}
}} .clockFlowWrap {{ padding-top: 10px; }} .clockStep {{ padding: 22px 14px 24px; border-radius: 24px; }} .clockHeroTitle {{ font-size: 28px; margin-bottom: 20px; }} .clockSelfieStage {{ min-height: 240px; padding: 16px; }} .clockSelfieVideo {{ min-height: 240px; }} .clockCaptureBar {{ flex-direction: column; }} .clockGhostBtn {{ width: 100%; min-height: 58px; }} .clockPrimaryBtn {{ min-height: 62px; font-size: 18px; }} .clockPrimaryAction, .clockSecondaryAction {{ min-height: 72px; font-size: 20px; }} }}

      </style>

      {page_back_button("/", "Back to dashboard")}

      <div class="clockFlowWrap">
        {msg_html}

        <div class="clockStep" id="clockStepOne">
          <div class="clockStepLabel">Step 1 of 2</div>
          <h1 class="clockHeroTitle">Take a selfie to continue</h1>

          <div class="clockStageCard">
            <div class="clockSelfieStage">
              <div class="clockSelfiePlaceholder" id="clockSelfiePlaceholder">
                <div class="clockSelfiePlaceholderIcon">&#128247;</div>
                <div class="clockSelfiePlaceholderText">Open the camera and capture a clear front-facing selfie.</div>
              </div>
              <video id="selfieVideo" class="clockSelfieVideo" autoplay playsinline muted></video>
            </div>
            <div class="clockCaptureBar">
              <button class="clockPrimaryBtn" id="takeSelfieBtn" type="button">
                <span class="clockPrimaryBtnText">Take Selfie</span>
                <span class="clockPrimaryBtnArrow">&#8250;</span>
              </button>
              <button class="clockGhostBtn" id="retakeSelfieBtn" type="button" disabled>Retake</button>
            </div>
          </div>

          <div class="clockMetaText" id="selfieStatus">Tap Take Selfie to open the camera.</div>
          <div id="geoStatus" class="clockHidden" aria-live="polite"></div>

          <div class="clockDistanceAlert is-error" id="geoAlert">
            <div class="clockDistanceAlertTitle" id="geoAlertTitle">📍 You are too far from the site</div>
            <div class="clockDistanceAlertMeta" id="geoAlertMeta">Distance: --m (limit --m)</div>
          </div>

          <div class="clockMapShell">
            <div id="map" style="height:280px; min-height:280px;"></div>
          </div>

          <div class="clockFooterNote" id="clockFooterNote">You'll be able to <strong>clock in</strong> after taking a selfie.</div>
        </div>

        <div class="clockStep clockStepTwo" id="clockStepTwo">
          <div class="clockStepLabel">Step 2 of 2</div>
          <div class="clockCapturedRow">
            <span class="clockCapturedIcon">✓</span>
            <span>Selfie captured</span>
          </div>

          <img id="selfiePreviewFinal" class="clockFinalSelfie" alt="Selfie preview">
          <canvas id="selfieCanvas" class="clockHidden"></canvas>

          <div class="clockTimerStage">
            {timer_html}
          </div>

          <form method="POST" id="geoClockForm" class="clockActionStack">
            <input type="hidden" name="csrf" value="{escape(csrf)}">
            <input type="hidden" name="action" id="geoAction" value="">
            <input type="hidden" name="lat" id="geoLat" value="">
            <input type="hidden" name="lon" id="geoLon" value="">
            <input type="hidden" name="acc" id="geoAcc" value="">
            <input type="hidden" name="geo_ts" id="geoTs" value="">
            <input type="hidden" name="selfie_data" id="selfieData" value="">

            <button class="clockPrimaryAction" id="btnClockIn" type="button">Clock In</button>
            <button class="clockSecondaryAction" id="btnClockOut" type="button">Clock Out</button>
          </form>

          <a href="/my-times" class="clockTextLink">View time logs</a>
          <div><button class="clockBackLink" id="backToStepOne" type="button">Retake selfie</button></div>
        </div>
      </div>

      <script>
        (function() {{
          const SITE = {site_json};
          const statusEl = document.getElementById("geoStatus");
          const form = document.getElementById("geoClockForm");
          const act = document.getElementById("geoAction");
          const latEl = document.getElementById("geoLat");
          const lonEl = document.getElementById("geoLon");
          const accEl = document.getElementById("geoAcc");
          const geoTsEl = document.getElementById("geoTs");

          const btnIn = document.getElementById("btnClockIn");
          const btnOut = document.getElementById("btnClockOut");
          const selfieDataEl = document.getElementById("selfieData");
          const selfieVideo = document.getElementById("selfieVideo");
          const selfieCanvas = document.getElementById("selfieCanvas");
          const selfieStatus = document.getElementById("selfieStatus");
          const takeSelfieBtn = document.getElementById("takeSelfieBtn");
          const takeSelfieBtnText = takeSelfieBtn.querySelector(".clockPrimaryBtnText");
          const retakeSelfieBtn = document.getElementById("retakeSelfieBtn");
          const backToStepOneBtn = document.getElementById("backToStepOne");
          const stepOne = document.getElementById("clockStepOne");
          const stepTwo = document.getElementById("clockStepTwo");
          const selfiePlaceholder = document.getElementById("clockSelfiePlaceholder");
          const selfiePreviewFinal = document.getElementById("selfiePreviewFinal");
          const geoAlert = document.getElementById("geoAlert");
          const geoAlertTitle = document.getElementById("geoAlertTitle");
          const geoAlertMeta = document.getElementById("geoAlertMeta");
          const footerNote = document.getElementById("clockFooterNote");
          let selfieStream = null;

          function setDisabled(v) {{
            btnIn.disabled = v;
            btnOut.disabled = v;
          }}

          function syncSteps() {{
            const hasSelfie = !!selfieDataEl.value;
            stepOne.style.display = hasSelfie ? "none" : "block";
            stepTwo.style.display = hasSelfie ? "block" : "none";
            if (hasSelfie) {{
              selfiePreviewFinal.src = selfieDataEl.value;
              selfiePreviewFinal.style.display = "block";
            }} else {{
              selfiePreviewFinal.src = "";
              selfiePreviewFinal.style.display = "none";
            }}
          }}

          function updateCaptureUi(cameraLive) {{
            selfiePlaceholder.style.display = cameraLive ? "none" : "flex";
            selfieVideo.style.display = cameraLive ? "block" : "none";
            takeSelfieBtnText.textContent = cameraLive ? "Capture Selfie" : "Take Selfie";
          }}

          function stopSelfieCamera() {{
            if (selfieStream) {{
              selfieStream.getTracks().forEach(track => track.stop());
              selfieStream = null;
            }}
            selfieVideo.srcObject = null;
            updateCaptureUi(false);
          }}

          async function startSelfieCamera() {{
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{
              selfieStatus.textContent = "Camera preview is not supported on this device/browser.";
              return;
            }}
            try {{
              stopSelfieCamera();
              selfieStream = await navigator.mediaDevices.getUserMedia({{ video: {{ facingMode: "user", width: {{ ideal: 1280 }}, height: {{ ideal: 720 }} }}, audio: false }});
              selfieVideo.srcObject = selfieStream;
              if (selfieVideo.play) {{
                try {{ await selfieVideo.play(); }} catch (e) {{}}
              }}
              updateCaptureUi(true);
              selfieStatus.textContent = "Camera ready. Tap capture when you're centered.";
            }} catch (err) {{
              console.log(err);
              selfieStatus.textContent = "Could not open camera. Please allow camera permission and try again.";
            }}
          }}

          function setSelfieData(dataUrl) {{
            selfieDataEl.value = dataUrl || "";
            if (dataUrl) {{
              retakeSelfieBtn.disabled = false;
              selfieStatus.textContent = "Selfie captured.";
              footerNote.innerHTML = "Selfie captured. You can now <strong>clock in</strong>.";
            }} else {{
              retakeSelfieBtn.disabled = true;
              selfieStatus.textContent = "Tap Take Selfie to open the camera.";
              footerNote.innerHTML = "You'll be able to <strong>clock in</strong> after taking a selfie.";
            }}
            syncSteps();
          }}

          function captureSelfieFrame() {{
            if (!selfieVideo || !selfieVideo.videoWidth || !selfieVideo.videoHeight) {{
              selfieStatus.textContent = "Open the camera first, then capture your selfie.";
              return;
            }}
            const maxW = 960;
            const scale = Math.min(1, maxW / selfieVideo.videoWidth);
            const width = Math.max(320, Math.round(selfieVideo.videoWidth * scale));
            const height = Math.max(240, Math.round(selfieVideo.videoHeight * scale));
            selfieCanvas.width = width;
            selfieCanvas.height = height;
            const ctx = selfieCanvas.getContext("2d");
            ctx.drawImage(selfieVideo, 0, 0, width, height);
            const dataUrl = selfieCanvas.toDataURL("image/jpeg", 0.88);
            setSelfieData(dataUrl);
            stopSelfieCamera();
          }}

          let map = null;
          let youMarker = null;

          function initMap() {{
            const start = SITE ? [SITE.lat, SITE.lon] : [51.505, -0.09];
            map = L.map("map", {{ zoomControl: true }}).setView(start, SITE ? 16 : 5);
            L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
              maxZoom: 19,
              attribution: "&copy; OpenStreetMap"
            }}).addTo(map);

            if (SITE) {{
              L.marker([SITE.lat, SITE.lon]).addTo(map).bindPopup(SITE.name);
              L.circle([SITE.lat, SITE.lon], {{ radius: SITE.radius }}).addTo(map);
            }}
          }}

          function haversineMeters(lat1, lon1, lat2, lon2) {{
            const R = 6371000;
            const toRad = (x) => x * Math.PI / 180;
            const dLat = toRad(lat2 - lat1);
            const dLon = toRad(lon2 - lon1);
            const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                      Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
                      Math.sin(dLon / 2) * Math.sin(dLon / 2);
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
            return R * c;
          }}

          function updateStatus(lat, lon, acc) {{
            if (!SITE) {{
              statusEl.textContent = "Location captured (no site configured).";
              geoAlert.className = "clockDistanceAlert is-ok";
              geoAlertTitle.textContent = "📍 Location captured";
              geoAlertMeta.textContent = "No active site radius is configured for this account.";
              return;
            }}
            const dist = haversineMeters(lat, lon, SITE.lat, SITE.lon);
            const ok = dist <= SITE.radius;
            statusEl.textContent = ok
              ? `Location OK: ${{SITE.name}} (${{Math.round(dist)}}m)`
              : `Outside radius: ${{Math.round(dist)}}m (limit ${{Math.round(SITE.radius)}}m)`;
            geoAlert.className = `clockDistanceAlert ${{ok ? 'is-ok' : 'is-error'}}`;
            geoAlertTitle.textContent = ok ? "📍 You are at the correct site" : "📍 You are too far from the site";
            geoAlertMeta.textContent = `Distance: ${{Math.round(dist)}}m (limit ${{Math.round(SITE.radius)}}m)`;
          }}

          function updateYouMarker(lat, lon) {{
            if (!map) return;
            if (!youMarker) {{
              youMarker = L.marker([lat, lon]).addTo(map);
            }} else {{
              youMarker.setLatLng([lat, lon]);
            }}
          }}

          function requestLocationAndSubmit(actionValue) {{
            if (!selfieDataEl.value) {{
              syncSteps();
              selfieStatus.textContent = "Selfie required before clocking in or out.";
              return;
            }}

            stopSelfieCamera();

            if (!navigator.geolocation) {{
              alert("Geolocation is not supported on this device/browser.");
              return;
            }}

            setDisabled(true);
            statusEl.textContent = "Getting your location…";

            navigator.geolocation.getCurrentPosition((pos) => {{
              const lat = pos.coords.latitude;
              const lon = pos.coords.longitude;
              const acc = pos.coords.accuracy;

              latEl.value = lat;
              lonEl.value = lon;
              accEl.value = acc;
              geoTsEl.value = String(Date.now());

              updateStatus(lat, lon, acc);
              updateYouMarker(lat, lon);

              act.value = actionValue;
              form.submit();
            }}, (err) => {{
              console.log(err);
              alert("Location is required to clock in or out. Please allow location permission and try again.");
              statusEl.textContent = "Location required. Please allow permission.";
              setDisabled(false);
            }}, {{ enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }});
          }}

          initMap();

          if (navigator.geolocation) {{
            navigator.geolocation.getCurrentPosition((pos) => {{
              const lat = pos.coords.latitude;
              const lon = pos.coords.longitude;
              updateStatus(lat, lon, pos.coords.accuracy);
              updateYouMarker(lat, lon);
            }}, () => {{
              geoAlert.className = "clockDistanceAlert is-error";
              geoAlertTitle.textContent = "📍 Location permission needed";
              geoAlertMeta.textContent = "Allow location access so we can verify your site.";
            }}, {{ enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }});
          }}

          takeSelfieBtn.addEventListener("click", async () => {{
            const hasLiveCamera = !!(selfieStream || (selfieVideo && selfieVideo.srcObject));
            if (!hasLiveCamera) {{
              await startSelfieCamera();
              return;
            }}
            captureSelfieFrame();
          }});

          retakeSelfieBtn.addEventListener("click", async () => {{
            setSelfieData("");
            await startSelfieCamera();
          }});

          backToStepOneBtn.addEventListener("click", async () => {{
            setSelfieData("");
            await startSelfieCamera();
          }});

          window.addEventListener("pagehide", stopSelfieCamera);
          window.addEventListener("beforeunload", stopSelfieCamera);
          document.addEventListener("visibilitychange", () => {{
            if (document.hidden) stopSelfieCamera();
          }});

          btnIn.addEventListener("click", () => requestLocationAndSubmit("in"));
          btnOut.addEventListener("click", () => requestLocationAndSubmit("out"));

          updateCaptureUi(false);
          syncSteps();
        }})();
      </script>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("clock", role, content))


@app.get("/my-times")
def my_times():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")

    rows = work_sheet.get_all_values()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    records = []
    total_hours = 0.0
    total_pay = 0.0
    last_clock_date = "—"
    today_count = 0
    week_count = 0
    today = datetime.now(TZ).date()
    week_start = today - timedelta(days=today.weekday())

    for r in rows[1:]:
        if len(r) <= COL_PAY or len(r) <= COL_USER:
            continue
        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(row_user):
                continue

        d_raw = (r[COL_DATE] if len(r) > COL_DATE else "").strip()
        hours_val = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        pay_val = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)
        total_hours += hours_val
        total_pay += pay_val
        if d_raw:
            last_clock_date = d_raw
            try:
                row_date = datetime.strptime(d_raw, "%Y-%m-%d").date()
                if row_date == today:
                    today_count += 1
                if week_start <= row_date <= today:
                    week_count += 1
            except Exception:
                pass

        records.append({
            "date": d_raw,
            "clock_in": (r[COL_IN] if len(r) > COL_IN else "") or "",
            "clock_out": (r[COL_OUT] if len(r) > COL_OUT else "") or "",
            "hours": hours_val,
            "pay": pay_val,
        })

    table_rows = []
    for rec in records:
        table_rows.append(
            f"<tr><td>{escape(rec['date'])}</td><td>{escape(rec['clock_in'])}</td><td>{escape(rec['clock_out'])}</td><td class='num'>{escape(fmt_hours(rec['hours']))}</td><td class='num'>{escape(currency)}{escape(money(rec['pay']))}</td></tr>"
        )
    table = "".join(table_rows) if table_rows else "<tr><td colspan='5'>No records yet.</td></tr>"

    page_css = """
    <style>
      .timeLogsPageShell{ display:grid; gap:14px; }
      .timeLogsHero{
        padding:18px;
        border-radius:24px;
        border:1px solid rgba(96,165,250,.16);
        background:linear-gradient(180deg, rgba(245,243,255,.98), rgba(255,255,255,.98));
        box-shadow:0 18px 40px rgba(15,23,42,.08), inset 0 1px 0 rgba(255,255,255,.78);
      }
      .timeLogsSummaryCard,
      .timeLogsTableCard{
        border:1px solid rgba(15,23,42,.08);
        background:linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
        box-shadow:0 14px 30px rgba(15,23,42,.06);
      }
      .timeLogsHeroTop{ display:flex; justify-content:space-between; gap:14px; align-items:flex-start; flex-wrap:wrap; }
      .timeLogsEyebrow{ display:inline-flex; align-items:center; gap:8px; padding:7px 12px; border-radius:999px; font-size:12px; font-weight:800; letter-spacing:.05em; text-transform:uppercase; color:#6d28d9; background:rgba(139,92,246,.10); border:1px solid rgba(139,92,246,.16); }
      .timeLogsHero h1{ margin:12px 0 0; font-size:clamp(34px, 5vw, 46px); color:var(--text); }
      .timeLogsHero .sub{ color:var(--muted); }
      .timeLogsSummaryGrid{ display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; }
      .timeLogsSummaryCard{ padding:14px 16px; border-radius:20px; }
      .timeLogsSummaryCard .k{ font-size:12px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; color:#64748b; }
      .timeLogsSummaryCard .v{ margin-top:8px; font-size:clamp(24px, 3vw, 34px); font-weight:800; color:var(--text); }
      .timeLogsSummaryCard .sub{ margin-top:6px; color:var(--muted); }
      .timeLogsTableCard{ padding:12px; border-radius:24px; }
      .timeLogsTable{ width:100%; min-width:720px; border-collapse:separate; border-spacing:0; overflow:hidden; border:1px solid rgba(15,23,42,.08); border-radius:18px; background:rgba(255,255,255,.98); }
      .timeLogsTable thead th{ padding:14px 16px; font-size:12px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; color:#475569; background:linear-gradient(180deg, rgba(248,250,252,.98), rgba(241,245,249,.98)); border-bottom:1px solid rgba(15,23,42,.08); }
      .timeLogsTable tbody td{ padding:16px; color:var(--text); font-weight:700; font-variant-numeric:tabular-nums; border-bottom:1px solid rgba(15,23,42,.08); }
      .timeLogsTable tbody tr:nth-child(even) td{ background:rgba(248,250,252,.92); }
      .timeLogsTable tbody tr:hover td{ background:rgba(59,130,246,.06); }
      .timeLogsTable td.num, .timeLogsTable th.num{ text-align:right; }
      .timeLogsTable tbody tr:last-child td{ border-bottom:0; }
      @media (max-width: 960px){ .timeLogsSummaryGrid{ grid-template-columns:1fr 1fr; } }
      @media (max-width: 700px){ .timeLogsSummaryGrid{ grid-template-columns:1fr; } .timeLogsHero{ padding:16px; border-radius:20px; } .timeLogsTableCard{ padding:10px; border-radius:20px; } }
    </style>
    """

    content = f"""
      {page_css}
      {page_back_button("/", "Back to dashboard")}

      <div class="timeLogsPageShell">
        <div class="timeLogsHero plainSection">
          <div class="timeLogsHeroTop">
            <div>
              <div class="timeLogsEyebrow">Clock history</div>
              <h1>Time logs</h1>
              <p class="sub">{escape(display_name)} • Review every saved clock in and out entry.</p>
            </div>
            <div class="badge {'admin' if role == 'admin' else ''}">{escape(role.upper())}</div>
          </div>
        </div>

        <div class="timeLogsSummaryGrid">
          <div class="timeLogsSummaryCard plainMetric"><div class="k">Entries</div><div class="v">{len(records)}</div><div class="sub">Saved shifts</div></div>
          <div class="timeLogsSummaryCard plainMetric"><div class="k">Total Hours</div><div class="v">{escape(fmt_hours(total_hours))}</div><div class="sub">Across all records</div></div>
          <div class="timeLogsSummaryCard plainMetric"><div class="k">Total Pay</div><div class="v">{escape(currency)}{escape(money(total_pay))}</div><div class="sub">Recorded gross pay</div></div>
          <div class="timeLogsSummaryCard plainMetric"><div class="k">Recent Activity</div><div class="v">{escape(str(last_clock_date))}</div><div class="sub">Today: {today_count} • This week: {week_count}</div></div>
        </div>

        <div class="timeLogsTableCard plainSection">
          <div class="tablewrap">
            <table class="timeLogsTable">
              <thead><tr><th>Date</th><th>Clock In</th><th>Clock Out</th><th class='num'>Hours</th><th class='num'>Pay</th></tr></thead>
              <tbody>{table}</tbody>
            </table>
          </div>
        </div>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("times", role, content))


# ---------- MY REPORTS ----------
@app.get("/my-reports")
def my_reports():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    company_name = str(settings.get("Company_Name") or "Main").strip() or "Main"
    company_logo = str(settings.get("Company_Logo_URL") or "").strip()

    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    now = datetime.now(TZ)
    today = now.date()

    # week selector: 0=this week, 1=last week, etc.
    try:
        wk_offset = max(0, int((request.args.get("wk", "0") or "0").strip()))
    except Exception:
        wk_offset = 0

    this_monday = today - timedelta(days=today.weekday())
    selected_week_start = this_monday - timedelta(days=7 * wk_offset)
    selected_week_end = selected_week_start + timedelta(days=6)

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    daily_hours = 0.0
    daily_pay = 0.0
    month_hours = 0.0
    month_pay = 0.0
    selected_week_hours = 0.0
    selected_week_pay = 0.0

    # build selected week map
    week_map = {}
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        d_display = d.strftime("%y-%m-%d")
        week_map[d_str] = {
            "day": day_labels[i],
            "date": d_str,
            "display_date": d_display,
            "first_in": "",
            "last_out": "",
            "hours": 0.0,
            "gross": 0.0,
        }

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue

        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

        d_str = (r[COL_DATE] if len(r) > COL_DATE else "").strip()
        if not d_str:
            continue

        try:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        cin = ((r[COL_IN] if len(r) > COL_IN else "") or "").strip()
        cout = ((r[COL_OUT] if len(r) > COL_OUT else "") or "").strip()
        hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        pay = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        if d == today:
            daily_hours += hrs
            daily_pay += pay

        if d.year == today.year and d.month == today.month:
            month_hours += hrs
            month_pay += pay

        if selected_week_start <= d <= selected_week_end:
            selected_week_hours += hrs
            selected_week_pay += pay

            item = week_map.get(d_str)
            if item is not None:
                item["hours"] += hrs
                item["gross"] += pay

                cin_short = cin[:5] if cin else ""
                cout_short = cout[:5] if cout else ""

                if cin_short:
                    if not item["first_in"] or cin_short < item["first_in"]:
                        item["first_in"] = cin_short

                if cout_short:
                    if not item["last_out"] or cout_short > item["last_out"]:
                        item["last_out"] = cout_short

    def gross_tax_net(gross):
        gross = round(gross, 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)
        return gross, tax, net

    d_g, d_t, d_n = gross_tax_net(daily_pay)
    w_g, w_t, w_n = gross_tax_net(selected_week_pay)
    m_g, m_t, m_n = gross_tax_net(month_pay)

    # weekly summary list (all weeks with data)
    week_summaries = {}

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue

        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

        d_str = (r[COL_DATE] if len(r) > COL_DATE else "").strip()
        if not d_str:
            continue

        try:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        gross = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        if hrs <= 0 and gross <= 0:
            continue

        monday = d - timedelta(days=d.weekday())
        sunday = monday + timedelta(days=6)
        key = monday.strftime("%Y-%m-%d")

        rec = week_summaries.setdefault(key, {
            "monday": monday,
            "sunday": sunday,
            "hours": 0.0,
            "gross": 0.0,
            "payment_date": d,
        })

        rec["hours"] += hrs
        rec["gross"] += gross

        if d > rec["payment_date"]:
            rec["payment_date"] = d

    weekly_list = []
    for key in sorted(week_summaries.keys(), reverse=True):
        rec = week_summaries[key]
        monday = rec["monday"]
        sunday = rec["sunday"]
        gross = round(rec["gross"], 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)

        iso = monday.isocalendar()
        period_label = f"Week {iso[1]} • {monday.strftime('%d %b')} – {sunday.strftime('%d %b %Y')}"
        payment_date = rec["payment_date"].strftime("%d/%m/%y")
        wk_link_offset = max(0, (this_monday - monday).days // 7)

        weekly_list.append({
            "period": period_label,
            "payment_date": payment_date,
            "company": company_name,
            "hours": round(rec["hours"], 2),
            "gross": gross,
            "tax": tax,
            "net": net,
            "wk_offset": wk_link_offset,
        })

    list_rows_html = []
    for item in weekly_list:
        list_rows_html.append(f"""
          <tr>
            <td>{escape(item['period'])}</td>
            <td>{escape(item['payment_date'])}</td>
            <td>{escape(item['company'])}</td>
            <td class="num">{escape(fmt_hours(item['hours']))}</td>
            <td class="num">{escape(currency)}{money(item['gross'])}</td>
            <td class="num">{escape(currency)}{money(item['tax'])}</td>
            <td class="num">{escape(currency)}{money(item['net'])}</td>
            <td class="num">
  <a class="reportsListDownloadBtn"
     href="/my-reports-print?wk={item['wk_offset']}"
     target="_blank"
     rel="noopener"
     title="View slip">
    &#8250;
  </a>
</td>
          </tr>
        """)

    if not list_rows_html:
        list_rows_html = [
            "<tr><td colspan='8' style='text-align:center; color:#6f6c85; padding:24px;'>No weekly timesheet records found.</td></tr>"
        ]

    page_css = """
    <style>
      .reportsListShell{
        max-width: 1320px;
        margin: 0 auto;
        padding: 6px 0 18px;
      }

      .reportsListHeader{
        display:flex;
        align-items:flex-start;
        justify-content:space-between;
        gap:18px;
        margin-bottom:14px;
      }

      .reportsListEyebrow{
        display:inline-flex;
        align-items:center;
        padding:8px 14px;
        border-radius:999px;
        border:1px solid rgba(109,40,217,.12);
        background:rgba(109,40,217,.06);
        color:#6d28d9;
        font-size:12px;
        font-weight:800;
        text-transform:uppercase;
        letter-spacing:.06em;
      }

      .reportsListHeader h1{
        margin:10px 0 8px;
        font-size:clamp(34px,4vw,46px);
        line-height:1.02;
        letter-spacing:-.03em;
        color:#1f2547;
        font-weight:900;
      }

      .reportsListHeader .sub{
        color:#6f6c85;
        font-size:15px;
      }

      .reportsListTopActions{
        display:flex;
        align-items:center;
        gap:10px;
        flex-wrap:wrap;
      }

      .reportsListTopActions .btnSoft{
        text-decoration:none;
        display:inline-flex;
        align-items:center;
        justify-content:center;
        min-height:46px;
        padding:0 16px;
        border-radius:14px;
        font-weight:800;
        background:#ffffff;
        border:1px solid rgba(109,40,217,.12);
        color:#4338ca;
        box-shadow:0 8px 18px rgba(41,25,86,.06);
      }

      .reportsListTopActions .btnPrimary{
        text-decoration:none;
        display:inline-flex;
        align-items:center;
        justify-content:center;
        min-height:46px;
        padding:0 18px;
        border-radius:14px;
        font-weight:800;
        color:#ffffff;
        background:linear-gradient(90deg, #6d28d9, #2563eb);
        box-shadow:0 12px 24px rgba(79,70,229,.20);
      }

      .reportsListTableShell{
        border:1px solid rgba(109,40,217,.10);
        border-radius:24px;
        overflow:hidden;
        background:linear-gradient(180deg, #ffffff, #fbfaff);
        box-shadow:0 18px 36px rgba(41,25,86,.08);
      }

      .reportsListTableTop{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        padding:14px 18px;
        border-bottom:1px solid rgba(109,40,217,.08);
        background:linear-gradient(180deg, rgba(109,40,217,.04), rgba(255,255,255,.85));
      }

      .reportsListTableTitle{
        font-size:18px;
        font-weight:800;
        color:#1f2547;
      }

      .reportsListTableMeta{
        color:#6f6c85;
        font-size:14px;
        font-weight:600;
      }

      .reportsListTableWrap{
        overflow:auto;
        background:#ffffff;
      }

      .reportsListTable{
  width:100%;
  min-width:1120px;
  border-collapse:separate;
  border-spacing:0;
  table-layout:auto;
  background:#ffffff;
}

.reportsListTable th:nth-child(1),
.reportsListTable td:nth-child(1){
  white-space:nowrap;
  min-width:240px;
}

.reportsListTable th:nth-child(2),
.reportsListTable td:nth-child(2){
  white-space:nowrap;
  min-width:120px;
}

.reportsListTable th:nth-child(3),
.reportsListTable td:nth-child(3){
  white-space:nowrap;
  min-width:250px;
}

.reportsListTable th:nth-child(8),
.reportsListTable td:nth-child(8){
  width:72px;
  min-width:72px;
}

      .reportsListTable thead th{
        background:#f4f5fb;
        color:#6b7280;
        font-size:12px;
        font-weight:800;
        text-transform:uppercase;
        letter-spacing:.04em;
        padding:14px 14px;
        border-bottom:1px solid #e8eaf2;
        text-align:left;
        white-space:nowrap;
      }

      .reportsListTable tbody td{
        padding:15px 14px;
        color:#1f2547;
        font-size:14px;
        font-weight:700;
        border-bottom:1px solid #edf0f5;
        white-space:nowrap;
        background:#ffffff;
      }

      .reportsListTable tbody tr:nth-child(even) td{
        background:#fcfbff;
      }

      .reportsListTable tbody tr:hover td{
        background:#f7f4ff;
      }

      .reportsListTable td.num,
      .reportsListTable th.num{
        text-align:right;
        font-variant-numeric:tabular-nums;
      }

      .reportsListTable tbody tr:last-child td{
        border-bottom:0;
      }

      .reportsListDownloadBtn{
        display:inline-flex;
        align-items:center;
        justify-content:center;
        width:34px;
        height:34px;
        border-radius:999px;
        border:1px solid rgba(109,40,217,.14);
        background:rgba(109,40,217,.06);
        color:#6d28d9;
        font-size:18px;
        font-weight:900;
        text-decoration:none;
        box-shadow:0 6px 14px rgba(41,25,86,.06);
        transition:transform .16s ease, box-shadow .16s ease, background .16s ease;
      }

      .reportsListDownloadBtn:hover{
        transform:translateY(-1px);
        background:rgba(109,40,217,.10);
        box-shadow:0 10px 18px rgba(41,25,86,.10);
      }

      .reportsListFooter{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        padding:12px 18px 16px;
        border-top:1px solid rgba(109,40,217,.08);
        background:#ffffff;
        color:#8a84a3;
        font-size:13px;
      }

      @media (max-width: 820px){
        .reportsListHeader{
          flex-direction:column;
        }

        .reportsListTopActions{
          width:100%;
        }

        .reportsListTopActions .btnSoft,
        .reportsListTopActions .btnPrimary{
          width:100%;
        }
      }

      @media print{
        .sidebar,
        .topbar,
        .mobileNav,
        .bottomNav,
        .dashboardMainMenu,
        .payrollMenuBackdrop,
        .payrollMenuToggle,
        #payrollMenuBackdrop,
        #payrollMenuToggle,
        .noPrint,
        .badge{
          display:none !important;
          visibility:hidden !important;
        }

        .shell,
        .content,
        .page,
        .main,
        .reportsListShell{
          margin:0 !important;
          padding:0 !important;
          width:100% !important;
          max-width:none !important;
        }

        body{
          background:#fff !important;
          margin:0 !important;
          padding:0 !important;
        }

        .reportsListTableShell{
          box-shadow:none !important;
        }
      }
    </style>
    """
    week_label = f"Week {selected_week_start.isocalendar()[1]} ({selected_week_start.strftime('%d %b')} – {selected_week_end.strftime('%d %b %Y')})"

    rows_html = []
    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        item = week_map[d_str]

        hours_val = round(item["hours"], 2)
        gross_val = round(item["gross"], 2)

        row_class = "overtimeRow" if hours_val > OVERTIME_HOURS else ""

        cin_txt = item["first_in"] if item["first_in"] else ""
        cout_txt = item["last_out"] if item["last_out"] else ""
        hrs_txt = fmt_hours(hours_val) if hours_val > 0 else ""
        gross_txt = money(gross_val) if gross_val > 0 else ""

    content = f"""
      {page_css}

      {page_back_button("/", "Back to dashboard")}

      <div class="reportsListShell">
        <div class="reportsListHeader">
          <div>
            <div class="reportsListEyebrow">Timesheets</div>
            <h1>Timesheets</h1>
            <p class="sub">{escape(display_name)} • {escape(company_name)}</p>
          </div>

        </div>
        
        <div class="reportsListTableShell">
          <div class="reportsListTableTop">
            <div class="reportsListTableTitle">All weekly timesheets</div>
            <div class="reportsListTableMeta">{len(weekly_list)} week(s)</div>
          </div>

          <div class="reportsListTableWrap">
            <table class="reportsListTable">
            <colgroup>
  <col style="width:24%;">
  <col style="width:12%;">
  <col style="width:24%;">
  <col style="width:8%;">
  <col style="width:11%;">
  <col style="width:10%;">
  <col style="width:11%;">
  <col style="width:4%;">
</colgroup>
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Payment Date</th>
                  <th>Company</th>
                  <th class="num">Hours</th>
                  <th class="num">Gross Pay</th>
                  <th class="num">Tax</th>
                  <th class="num">Take Home</th>
                  <th class="num">View</th>
                </tr>
              </thead>
              <tbody>
                {''.join(list_rows_html)}
              </tbody>
            </table>
          </div>

        
        </div>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("reports", role, content))

@app.get("/payments")
def payments_page():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    company_name = str(settings.get("Company_Name") or "Main").strip() or "Main"

    now = datetime.now(TZ)
    today = now.date()
    this_monday = today - timedelta(days=today.weekday())

    vals = get_payroll_rows()
    headers = vals[0] if vals else []

    def idx(name):
        return headers.index(name) if name in headers else None

    i_ws = idx("WeekStart")
    i_we = idx("WeekEnd")
    i_u = idx("Username")
    i_g = idx("Gross")
    i_t = idx("Tax")
    i_n = idx("Net")
    i_pa = idx("PaidAt")
    i_pb = idx("PaidBy")
    i_paid = idx("Paid")
    i_wp = idx("Workplace_ID")

    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    def money_float(v):
        try:
            return round(float(str(v or "0").replace("£", "").replace(",", "").strip() or "0"), 2)
        except Exception:
            return 0.0

    def fmt_paid_at(raw):
        raw = str(raw or "").strip()
        if not raw:
            return ""
        try:
            return datetime.fromisoformat(raw).strftime("%d/%m/%y")
        except Exception:
            pass
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%y")
        except Exception:
            pass
        return raw[:10]

    paid_rows = []

    for r in vals[1:]:
        row_user = (r[i_u] if i_u is not None and i_u < len(r) else "").strip()
        if row_user != username:
            continue

        row_wp = ((r[i_wp] if i_wp is not None and i_wp < len(r) else "").strip() or "default")
        if row_wp not in allowed_wps:
            continue

        week_start = (r[i_ws] if i_ws is not None and i_ws < len(r) else "").strip()
        week_end = (r[i_we] if i_we is not None and i_we < len(r) else "").strip()
        paid_at = (r[i_pa] if i_pa is not None and i_pa < len(r) else "").strip()
        paid_by = (r[i_pb] if i_pb is not None and i_pb < len(r) else "").strip()
        paid_flag = (r[i_paid] if i_paid is not None and i_paid < len(r) else "").strip().lower()

        is_paid = bool(paid_at) or paid_flag in {"true", "yes", "1", "paid"}
        if not is_paid:
            continue

        try:
            monday = date.fromisoformat(week_start)
            sunday = date.fromisoformat(week_end)
        except Exception:
            continue

        gross = money_float(r[i_g] if i_g is not None and i_g < len(r) else "0")
        tax = money_float(r[i_t] if i_t is not None and i_t < len(r) else "0")
        net = money_float(r[i_n] if i_n is not None and i_n < len(r) else "0")

        wk_offset = max(0, (this_monday - monday).days // 7)
        iso = monday.isocalendar()
        period_label = f"Week {iso[1]} • {monday.strftime('%d %b')} – {sunday.strftime('%d %b %Y')}"

        paid_rows.append({
            "monday": monday,
            "period": period_label,
            "paid_at": fmt_paid_at(paid_at),
            "paid_by": paid_by or "-",
            "company": company_name,
            "gross": gross,
            "tax": tax,
            "net": net,
            "wk_offset": wk_offset,
        })

    paid_rows.sort(key=lambda x: x["monday"], reverse=True)

    row_html = []
    for item in paid_rows:
        row_html.append(f"""
          <tr>
            <td>{escape(item['period'])}</td>
            <td class="num">{escape(currency)}{money(item['gross'])}</td>
            <td class="num">{escape(currency)}{money(item['tax'])}</td>
            <td class="num">{escape(currency)}{money(item['net'])}</td>
            <td class="num">
              <a class="reportsListDownloadBtn" href="/my-reports-print?wk={item['wk_offset']}" target="_blank" rel="noopener" title="Download payslip">↓</a>
            </td>
          </tr>
        """)

    if not row_html:
        row_html = [
            "<tr><td colspan='5' style='text-align:center; color:#6f6c85; padding:24px;'>No paid weeks found yet.</td></tr>"
        ]

    page_css = """
    <style>
      .paymentsShell{
        max-width: 1320px;
        margin: 0 auto;
        padding: 6px 0 18px;
      }

      .paymentsHeader{
        display:flex;
        align-items:flex-start;
        justify-content:space-between;
        gap:18px;
        margin-bottom:14px;
      }

      .paymentsEyebrow{
        display:inline-flex;
        align-items:center;
        padding:8px 14px;
        border-radius:999px;
        border:1px solid rgba(109,40,217,.12);
        background:rgba(109,40,217,.06);
        color:#6d28d9;
        font-size:12px;
        font-weight:800;
        text-transform:uppercase;
        letter-spacing:.06em;
      }

      .paymentsHeader h1{
        margin:10px 0 8px;
        font-size:clamp(34px,4vw,46px);
        line-height:1.02;
        letter-spacing:-.03em;
        color:#1f2547;
        font-weight:900;
      }

      .paymentsHeader .sub{
        color:#6f6c85;
        font-size:15px;
      }

      .paymentsTableShell{
        overflow:hidden;
        border-radius:24px;
        border:1px solid rgba(109,40,217,.10);
        background:#ffffff;
        box-shadow:0 16px 32px rgba(41,25,86,.08);
      }

      .paymentsTableTop{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        padding:16px 18px;
        border-bottom:1px solid rgba(109,40,217,.08);
        background:linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,246,255,.98));
      }

      .paymentsTableTitle{
        font-size:18px;
        font-weight:900;
        color:#1f2547;
      }

      .paymentsTableMeta{
        font-size:13px;
        color:#8a84a3;
        font-weight:700;
      }

      .paymentsTableWrap{
  overflow-x:hidden;
  overflow-y:visible;
}

.paymentsTable{
  width:100%;
  min-width:0;
  border-collapse:separate;
  border-spacing:0;
  table-layout:fixed;
}

      .paymentsTable th,
      .paymentsTable td{
        padding:14px 16px;
        border-bottom:1px solid rgba(109,40,217,.08);
        text-align:left;
        background:#fff;
      }

      .paymentsTable th{
        font-size:12px;
        text-transform:uppercase;
        letter-spacing:.06em;
        color:#7b7693;
        font-weight:800;
      }

      .paymentsTable td{
        color:#1f2547;
        font-size:14px;
      }

      .paymentsTable td.num,
      .paymentsTable th.num{
        text-align:right;
      }
      
      .paymentsTable th,
.paymentsTable td{
  padding:12px 10px;
}

.paymentsTable th:nth-child(1),
.paymentsTable td:nth-child(1){
  width:44%;
  white-space:normal;
  line-height:1.25;
}

.paymentsTable th:nth-child(2),
.paymentsTable td:nth-child(2),
.paymentsTable th:nth-child(3),
.paymentsTable td:nth-child(3),
.paymentsTable th:nth-child(4),
.paymentsTable td:nth-child(4){
  width:16%;
}

.paymentsTable th:nth-child(5),
.paymentsTable td:nth-child(5){
  width:8%;
}

      .paymentsTable tbody tr:hover td{
        background:rgba(109,40,217,.03);
      }

      .reportsListDownloadBtn{
        width:34px;
        height:34px;
        display:inline-flex;
        align-items:center;
        justify-content:center;
        border-radius:999px;
        border:1px solid rgba(109,40,217,.14);
        background:rgba(109,40,217,.06);
        color:#6d28d9;
        font-size:18px;
        font-weight:900;
        text-decoration:none;
        box-shadow:0 6px 14px rgba(41,25,86,.06);
      }

      .paymentsFooter{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        padding:12px 18px 16px;
        border-top:1px solid rgba(109,40,217,.08);
        background:#ffffff;
        color:#8a84a3;
        font-size:13px;
      }

      @media (max-width: 820px){
        .paymentsHeader{
          flex-direction:column;
        }
      }
    </style>
    """

    content = f"""
      {page_css}
      {page_back_button("/", "Back to dashboard")}

      <div class="paymentsShell">
        <div class="paymentsHeader">
          <div>
            <div class="paymentsEyebrow">Payments</div>
            <h1>Payments</h1>
            <p class="sub">{escape(display_name)} • {escape(company_name)}</p>
          </div>
        </div>

        <div class="paymentsTableShell">
          <div class="paymentsTableTop">
            <div class="paymentsTableTitle">Paid weeks</div>
            <div class="paymentsTableMeta">{len(paid_rows)} paid week(s)</div>
          </div>

          <div class="paymentsTableWrap">
            <table class="paymentsTable">
              <thead>
  <tr>
    <th>Period</th>
    <th class="num">Gross</th>
    <th class="num">Tax</th>
    <th class="num">Net</th>
    <th class="num">Download</th>
  </tr>
</thead>
              <tbody>
                {''.join(row_html)}
              </tbody>
            </table>
          </div>

          
        </div>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("payments", role, content))


@app.get("/my-reports-print")
def my_reports_print():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    company_name = str(settings.get("Company_Name") or "Main").strip() or "Main"
    company_logo = str(settings.get("Company_Logo_URL") or "").strip()

    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    now = datetime.now(TZ)
    today = now.date()

    try:
        wk_offset = max(0, int((request.args.get("wk", "0") or "0").strip()))
    except Exception:
        wk_offset = 0

    this_monday = today - timedelta(days=today.weekday())
    selected_week_start = this_monday - timedelta(days=7 * wk_offset)
    selected_week_end = selected_week_start + timedelta(days=6)

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    selected_week_hours = 0.0
    selected_week_pay = 0.0

    week_map = {}
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        d_display = d.strftime("%y-%m-%d")
        week_map[d_str] = {
            "day": day_labels[i],
            "date": d_str,
            "display_date": d_display,
            "first_in": "",
            "last_out": "",
            "hours": 0.0,
            "gross": 0.0,
        }

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue

        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

        d_str = (r[COL_DATE] if len(r) > COL_DATE else "").strip()
        if not d_str:
            continue

        try:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        cin = ((r[COL_IN] if len(r) > COL_IN else "") or "").strip()
        cout = ((r[COL_OUT] if len(r) > COL_OUT else "") or "").strip()
        hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        pay = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        if selected_week_start <= d <= selected_week_end:
            selected_week_hours += hrs
            selected_week_pay += pay

            item = week_map.get(d_str)
            if item is not None:
                item["hours"] += hrs
                item["gross"] += pay

                cin_short = cin[:5] if cin else ""
                cout_short = cout[:5] if cout else ""

                if cin_short:
                    if not item["first_in"] or cin_short < item["first_in"]:
                        item["first_in"] = cin_short

                if cout_short:
                    if not item["last_out"] or cout_short > item["last_out"]:
                        item["last_out"] = cout_short

    def gross_tax_net(gross):
        gross = round(gross, 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)
        return gross, tax, net

    w_g, w_t, w_n = gross_tax_net(selected_week_pay)

    week_label = f"Week {selected_week_start.isocalendar()[1]} ({selected_week_start.strftime('%d %b')} – {selected_week_end.strftime('%d %b %Y')})"
    rows_html = []
    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        item = week_map[d_str]

        hours_val = round(item["hours"], 2)
        gross_val = round(item["gross"], 2)

        row_class = "overtimeRow" if hours_val > OVERTIME_HOURS else ""

        cin_txt = item["first_in"] if item["first_in"] else ""
        cout_txt = item["last_out"] if item["last_out"] else ""
        hrs_txt = fmt_hours(hours_val) if hours_val > 0 else ""
        gross_txt = money(gross_val) if gross_val > 0 else ""

        rows_html.append(f"""
          <tr class="{row_class}">
            <td><b>{escape(item['day'])}</b></td>
            <td>{escape(item['display_date'])}</td>
            <td style="font-weight:700; text-align:center;">{escape(cin_txt)}</td>
            <td style="font-weight:700; text-align:center;">{escape(cout_txt)}</td>
            <td class="num" style="font-weight:700;">{escape(hrs_txt)}</td>
            <td class="num" style="font-weight:700;">{escape(gross_txt)}</td>
          </tr>
        """)

    rows_html = []
    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        item = week_map[d_str]

        hours_val = round(item["hours"], 2)
        gross_val = round(item["gross"], 2)
        net_val = round(gross_val - (gross_val * tax_rate), 2)

        row_class = "overtimeRow" if hours_val > OVERTIME_HOURS else ""

        cin_txt = item["first_in"] if item["first_in"] else ""
        cout_txt = item["last_out"] if item["last_out"] else ""
        hrs_txt = fmt_hours(hours_val) if hours_val > 0 else ""
        gross_txt = money(gross_val) if gross_val > 0 else ""
        net_txt = money(net_val) if net_val > 0 else ""

        rows_html.append(f"""
          <tr class="{row_class}">
            <td><b>{escape(item['day'])}</b></td>
            <td>{escape(item['display_date'])}</td>
            <td style="font-weight:700; text-align:center;">{escape(cin_txt)}</td>
            <td style="font-weight:700; text-align:center;">{escape(cout_txt)}</td>
            <td class="num" style="font-weight:700;">{escape(hrs_txt)}</td>
            <td class="num" style="font-weight:700;">{escape(gross_txt)}</td>
            <td class="num" style="font-weight:800; color:rgba(15,23,42,.92);">{escape(net_txt)}</td>
          </tr>
        """)

    page_css = """
    <style>
      .printSheetWrap{
        max-width: 980px;
        margin: 0 auto;
      }

      .printCard{
        background: #ffffff;
        border: 1px solid #e6e8f0;
        border-radius: 0;
        box-shadow: 0 18px 40px rgba(15,23,42,.08);
        overflow: hidden;
      }

      .printToolbar{
        display:flex;
        justify-content:space-between;
        align-items:center;
        gap:12px;
        margin-bottom:14px;
      }

      .printToolbar .btnSoft{
        text-decoration:none;
      }

      .statementHead{
        padding: 26px 28px 18px;
        border-bottom: 1px solid #ececf4;
        background: #ffffff;
      }

      .statementHeadGrid{
        display:grid;
        grid-template-columns: 1.1fr 1fr .9fr;
        gap: 20px;
        align-items:start;
      }

      .statementCompany{
        min-width:0;
      }

      .statementLogo{
        max-height: 42px;
        max-width: 150px;
        object-fit: contain;
        display:block;
        margin-bottom: 10px;
      }

      .statementCompanyName{
        font-size: 20px;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.15;
      }

      .statementCompanySub{
        margin-top: 8px;
        color: #64748b;
        font-size: 12px;
        line-height: 1.5;
      }

      .statementTitleBlock{
        text-align:center;
        min-width:0;
      }

      .statementTitle{
        font-size: 22px;
        font-weight: 900;
        color: #111827;
        line-height: 1.15;
      }

      .statementPeriod{
        margin-top: 4px;
        font-size: 16px;
        font-weight: 800;
        color: #1f2937;
      }

      .statementMeta{
        justify-self:end;
        min-width: 220px;
        text-align:right;
      }

      .statementMetaRow{
        font-size: 11px;
        color: #6b7280;
        line-height: 1.55;
      }

      .statementMetaRow strong{
        color: #111827;
        font-weight: 800;
      }

      .statementBody{
        padding: 20px 28px 18px;
      }

      .statementTopGrid{
        display:grid;
        grid-template-columns: 1fr 1fr;
        gap: 26px;
        margin-bottom: 18px;
      }

      .statementSectionTitle{
        margin: 0 0 8px 0;
        font-size: 11px;
        font-weight: 900;
        letter-spacing: .08em;
        text-transform: uppercase;
        color: #6d28d9;
      }

      .statementInfoLines{
        color: #111827;
        font-size: 13px;
        line-height: 1.7;
      }

      .statementInfoLines .muted{
        color: #6b7280;
      }

      .statementSummary{
        display:grid;
        gap: 6px;
      }

      .statementSummaryRow{
        display:grid;
        grid-template-columns: 1fr auto;
        gap: 12px;
        align-items:end;
        padding: 2px 0;
        font-size: 13px;
        color: #111827;
      }

      .statementSummaryRow .label{
        color: #4b5563;
      }

      .statementSummaryRow .value{
        font-weight: 800;
        color: #111827;
        white-space: nowrap;
      }

      .statementSummaryRow.total{
        margin-top: 6px;
        padding-top: 8px;
        border-top: 1px solid #e5e7eb;
      }

      .statementSummaryRow.total .label,
      .statementSummaryRow.total .value{
        font-weight: 900;
        color: #111827;
      }

      .statementTableWrap{
        margin-top: 8px;
        border: 1px solid #e5e7eb;
        border-radius: 0;
        overflow: hidden;
      }

      .statementTable{
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
        background: #ffffff;
      }

      .statementTable th{
        background: #f5f6fa;
        color: #374151;
        font-size: 11px;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: .04em;
        padding: 10px 10px;
        border-bottom: 1px solid #e5e7eb;
        text-align: left;
      }

      .statementTable td{
        padding: 9px 10px;
        font-size: 13px;
        color: #111827;
        border-bottom: 1px solid #edf0f5;
        vertical-align: middle;
      }

      .statementTable tbody tr:last-child td{
        border-bottom: 0;
      }

      .statementTable td.num,
      .statementTable th.num{
        text-align: right;
        font-variant-numeric: tabular-nums;
      }

      .statementFooterTotals{
        margin-top: 16px;
        display:grid;
        grid-template-columns: repeat(4, minmax(0,1fr));
        gap: 12px;
      }

      .statementTotalCard{
        border: 1px solid #e5e7eb;
        border-radius: 0;
        background: #ffffff;
        padding: 10px 12px;
      }

      .statementTotalCard .k{
        font-size: 11px;
        font-weight: 900;
        letter-spacing: .06em;
        text-transform: uppercase;
        color: #6b7280;
      }

      .statementTotalCard .v{
        margin-top: 4px;
        font-size: 16px;
        font-weight: 900;
        color: #111827;
        line-height: 1.15;
      }

      .statementBottomBar{
        height: 14px;
        background: linear-gradient(90deg, #7c3aed 0%, #6d28d9 40%, #5b21b6 100%);
      }

      @media (max-width: 860px){
        .statementHeadGrid,
        .statementTopGrid,
        .statementFooterTotals{
          grid-template-columns: 1fr;
        }

        .statementMeta{
          justify-self:start;
          text-align:left;
          min-width:0;
        }

        .statementTitleBlock{
          text-align:left;
        }
      }

      @media print{
        .sidebar,
        .topbar,
        .mobileNav,
        .bottomNav,
        .dashboardMainMenu,
        .payrollMenuBackdrop,
        .payrollMenuToggle,
        #payrollMenuBackdrop,
        #payrollMenuToggle,
        .noPrint,
        .headerTop,
        .badge{
          display:none !important;
          visibility:hidden !important;
        }

        .shell,
        .content,
        .page,
        .main,
        .printSheetWrap{
          margin:0 !important;
          padding:0 !important;
          width:100% !important;
          max-width:none !important;
        }

        body{
          background:#ffffff !important;
          margin:0 !important;
          padding:0 !important;
          -webkit-print-color-adjust: exact;
          print-color-adjust: exact;
        }

        .printCard,
        .statementTableWrap,
        .statementTotalCard{
          box-shadow:none !important;
        }

        .printCard{
          border:none !important;
        }
      }
    </style>
    """
    content = f"""
      {page_css}

      <div class="printSheetWrap">
        <div class="printToolbar noPrint">
          {page_back_button(f"/my-reports?wk={wk_offset}", "Back to timesheets")}
          <button class="btnSoft" type="button" onclick="window.print()">Save / Print Payslip</button>
        </div>

        <div class="printCard">
          <div class="statementHead" style="padding:18px 24px 12px;">
            <div class="statementHeadGrid" style="grid-template-columns:1.2fr 1fr; gap:18px;">
              <div class="statementCompany">
                {f'<img src="{escape(company_logo)}" alt="Company logo" class="statementLogo">' if company_logo else ''}
                <div class="statementCompanyName">{escape(company_name)}</div>
                <div class="statementCompanySub">
                  Payroll / Timesheet statement<br>
                  Generated from weekly records
                </div>
              </div>

              <div class="statementTitleBlock" style="text-align:right;">
                <div class="statementTitle">CIS Pay Statement</div>
                <div class="statementPeriod">{escape(week_label)}</div>
                <div class="statementMetaRow" style="margin-top:10px;">
                  <strong>Employee:</strong> {escape(display_name)}
                </div>
                <div class="statementMetaRow">
                  <strong>Generated:</strong> {escape(datetime.now(TZ).strftime("%d/%m/%Y %H:%M"))}
                </div>
              </div>
            </div>
          </div>

          <div class="statementBody" style="padding:14px 24px 16px;">
            <div class="statementSectionTitle" style="margin-bottom:8px;">Pay summary</div>
            <div class="statementSummary" style="margin-bottom:14px;">
              <div class="statementSummaryRow">
                <div class="label">Hours worked</div>
                <div class="value">{escape(fmt_hours(selected_week_hours))}</div>
              </div>
              <div class="statementSummaryRow">
                <div class="label">Gross pay</div>
                <div class="value">{escape(currency)}{money(w_g)}</div>
              </div>
              <div class="statementSummaryRow">
                <div class="label">Tax</div>
                <div class="value">{escape(currency)}{money(w_t)}</div>
              </div>
              <div class="statementSummaryRow total">
                <div class="label">Total net pay</div>
                <div class="value">{escape(currency)}{money(w_n)}</div>
              </div>
            </div>

            <div class="statementSectionTitle" style="margin-bottom:8px;">Weekly breakdown</div>

            <div class="statementTableWrap">
              <table class="statementTable" style="table-layout:fixed;">
                <colgroup>
                  <col style="width:14%;">
                  <col style="width:18%;">
                  <col style="width:16%;">
                  <col style="width:16%;">
                  <col style="width:12%;">
                  <col style="width:12%;">
                  <col style="width:12%;">
                </colgroup>
                <thead>
                  <tr>
                    <th>Day</th>
                    <th>Date</th>
                    <th>Clock In</th>
                    <th>Clock Out</th>
                    <th class="num">Hours</th>
                    <th class="num">Gross</th>
                    <th class="num">Net</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(rows_html)}
                </tbody>
              </table>
            </div>
          </div>

          <div class="statementBottomBar"></div>
        </div>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("reports", role, content))


@app.get("/my-reports.pdf")
def my_reports_pdf():
    gate = require_login()
    if gate:
        return gate

    # local imports so the app still starts even if reportlab is missing
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception:
        return {"error": "PDF library missing. Install reportlab."}, 500

    username = session["username"]
    display_name = get_employee_display_name(username)

    settings = get_company_settings()
    company_name = (settings.get("Company_Name", "") or "").strip() or "Company"
    currency = (settings.get("Currency", "£") or "£").strip() or "£"

    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    now = datetime.now(TZ)
    today = now.date()

    try:
        wk_offset = max(0, int((request.args.get("wk", "0") or "0").strip()))
    except Exception:
        wk_offset = 0

    this_monday = today - timedelta(days=today.weekday())
    selected_week_start = this_monday - timedelta(days=7 * wk_offset)
    selected_week_end = selected_week_start + timedelta(days=6)

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    week_map = {}

    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        week_map[d_str] = {
            "day": day_labels[i],
            "date": d_str,
            "clock_in": "",
            "clock_out": "",
            "hours": 0.0,
            "gross": 0.0,
        }

    total_hours = 0.0
    total_gross = 0.0

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue

        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

        d_str = (r[COL_DATE] if len(r) > COL_DATE else "").strip()
        if not d_str or d_str not in week_map:
            continue

        try:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        if not (selected_week_start <= d <= selected_week_end):
            continue

        cin = ((r[COL_IN] if len(r) > COL_IN else "") or "").strip()
        cout = ((r[COL_OUT] if len(r) > COL_OUT else "") or "").strip()
        hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        gross = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        item = week_map[d_str]
        item["hours"] += hrs
        item["gross"] += gross

        cin_short = cin[:5] if cin else ""
        cout_short = cout[:5] if cout else ""

        if cin_short:
            if not item["clock_in"] or cin_short < item["clock_in"]:
                item["clock_in"] = cin_short

        if cout_short:
            if not item["clock_out"] or cout_short > item["clock_out"]:
                item["clock_out"] = cout_short

        total_hours += hrs
        total_gross += gross

    total_tax = round(total_gross * tax_rate, 2)
    total_net = round(total_gross - total_tax, 2)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_width, page_height = A4

    left = 40
    right = page_width - 40
    y = page_height - 40

    def line(text, size=10, bold=False, step=16):
        nonlocal y
        if y < 60:
            pdf.showPage()
            y = page_height - 40
        font_name = "Helvetica-Bold" if bold else "Helvetica"
        pdf.setFont(font_name, size)
        pdf.drawString(left, y, str(text))
        y -= step

    pdf.setTitle(f"Payslip {display_name} {selected_week_start.isoformat()}")

    line(company_name, size=16, bold=True, step=22)
    line("Payslip / Timesheet", size=12, bold=True, step=18)
    line(f"Employee: {display_name}", size=11, step=16)
    line(f"Week: {selected_week_start.isoformat()} to {selected_week_end.isoformat()}", size=11, step=20)

    line("Day | Date | In | Out | Hours | Gross | Net", size=10, bold=True, step=16)
    line("-" * 90, size=9, step=12)

    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        item = week_map[d_str]

        gross_val = round(item["gross"], 2)
        tax_val = round(gross_val * tax_rate, 2)
        net_val = round(gross_val - tax_val, 2)
        hours_val = round(item["hours"], 2)

        row_text = (
            f"{item['day']} | {item['date']} | "
            f"{item['clock_in'] or '-'} | {item['clock_out'] or '-'} | "
            f"{hours_val:.2f} | {currency}{gross_val:.2f} | {currency}{net_val:.2f}"
        )
        line(row_text, size=9, step=14)

    y -= 8
    line("Totals", size=11, bold=True, step=16)
    line(f"Total Hours: {round(total_hours, 2):.2f}", size=10, step=14)
    line(f"Gross Pay: {currency}{round(total_gross, 2):.2f}", size=10, step=14)
    line(f"Tax: {currency}{total_tax:.2f}", size=10, step=14)
    line(f"Net Pay: {currency}{total_net:.2f}", size=10, bold=True, step=16)

    pdf.save()
    buffer.seek(0)

    filename = (
        f"payslip_{secure_filename(username)}_"
        f"{selected_week_start.isoformat()}_to_{selected_week_end.isoformat()}.pdf"
    )

    response = send_file(
        buffer,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=filename,
        max_age=0,
        conditional=False,
    )

    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response


@app.get("/my-reports.csv")
def my_reports_csv():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    display_name = get_employee_display_name(username)

    settings = get_company_settings()
    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    now = datetime.now(TZ)
    today = now.date()

    try:
        wk_offset = max(0, int((request.args.get("wk", "0") or "0").strip()))
    except Exception:
        wk_offset = 0

    this_monday = today - timedelta(days=today.weekday())
    selected_week_start = this_monday - timedelta(days=7 * wk_offset)
    selected_week_end = selected_week_start + timedelta(days=6)

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    week_map = {}

    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        week_map[d_str] = {
            "day": day_labels[i],
            "date": d_str,
            "clock_in": "",
            "clock_out": "",
            "hours": 0.0,
            "gross": 0.0,
        }

    total_hours = 0.0
    total_gross = 0.0

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue

        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

        d_str = (r[COL_DATE] if len(r) > COL_DATE else "").strip()
        if not d_str or d_str not in week_map:
            continue

        try:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        if not (selected_week_start <= d <= selected_week_end):
            continue

        cin = ((r[COL_IN] if len(r) > COL_IN else "") or "").strip()
        cout = ((r[COL_OUT] if len(r) > COL_OUT else "") or "").strip()
        hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        gross = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        item = week_map[d_str]
        item["hours"] += hrs
        item["gross"] += gross

        cin_short = cin[:5] if cin else ""
        cout_short = cout[:5] if cout else ""

        if cin_short:
            if not item["clock_in"] or cin_short < item["clock_in"]:
                item["clock_in"] = cin_short

        if cout_short:
            if not item["clock_out"] or cout_short > item["clock_out"]:
                item["clock_out"] = cout_short

        total_hours += hrs
        total_gross += gross

    import csv
    from io import StringIO

    output = StringIO()
    output.write("sep=,\r\n")
    writer = csv.writer(output)
    writer.writerow([
        "Employee", "WeekStart", "WeekEnd", "Day", "Date",
        "ClockIn", "ClockOut", "Hours", "Gross", "Tax", "Net"
    ])

    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        item = week_map[d_str]

        gross_val = round(item["gross"], 2)
        tax_val = round(gross_val * tax_rate, 2)
        net_val = round(gross_val - tax_val, 2)
        hours_val = round(item["hours"], 2)

        writer.writerow([
            display_name,
            selected_week_start.isoformat(),
            selected_week_end.isoformat(),
            item["day"],
            item["date"],
            item["clock_in"],
            item["clock_out"],
            f"{hours_val:.2f}",
            f"{gross_val:.2f}",
            f"{tax_val:.2f}",
            f"{net_val:.2f}",
        ])

    total_tax = round(total_gross * tax_rate, 2)
    total_net = round(total_gross - total_tax, 2)

    writer.writerow([])
    writer.writerow([
        "TOTAL", "", "", "", "", "", "",
        f"{round(total_hours, 2):.2f}",
        f"{round(total_gross, 2):.2f}",
        f"{total_tax:.2f}",
        f"{total_net:.2f}",
    ])

    buf = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    buf.seek(0)

    filename = f"timesheet_{secure_filename(username)}_{selected_week_start.isoformat()}_to_{selected_week_end.isoformat()}.csv"

    return send_file(
        buf,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
        max_age=0
    )


# ---------- STARTER FORM / ONBOARDING ----------
@app.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)
    existing = get_onboarding_record(username)

    msg = ""
    msg_ok = False

    typed = None
    missing_fields = set()

    if request.method == "POST":
        require_csrf()
        typed = request.form.to_dict(flat=True)
        submit_type = request.form.get("submit_type", "draft")
        is_final = (submit_type == "final")

        def g(name):
            return (request.form.get(name, "") or "").strip()

        first = g("first");
        last = g("last");
        birth = g("birth")
        phone_cc = g("phone_cc") or "+44";
        phone_num = g("phone_num")
        street = g("street");
        city = g("city");
        postcode = g("postcode")
        email = g("email")
        ec_name = g("ec_name");
        ec_cc = g("ec_cc") or "+44";
        ec_phone = g("ec_phone")
        medical = g("medical");
        medical_details = g("medical_details")
        position = g("position");
        cscs_no = g("cscs_no");
        cscs_exp = g("cscs_exp")
        emp_type = g("emp_type");
        rtw = g("rtw")
        ni = g("ni");
        utr = g("utr");
        start_date = g("start_date")
        acc_no = g("acc_no");
        sort_code = g("sort_code");
        acc_name = g("acc_name")
        comp_trading = g("comp_trading");
        comp_reg = g("comp_reg")
        contract_date = g("contract_date");
        site_address = g("site_address")
        contract_accept = (request.form.get("contract_accept", "") == "yes")
        signature_name = g("signature_name")

        passport_file = request.files.get("passport_file")
        cscs_file = request.files.get("cscs_file")
        pli_file = request.files.get("pli_file")
        share_file = request.files.get("share_file")

        missing = []

        def req(value, input_name, label):
            if not value:
                missing.append(label)
                missing_fields.add(input_name)

        if is_final:
            req(first, "first", "First Name")
            req(last, "last", "Last Name")
            req(birth, "birth", "Birth Date")
            req(phone_num, "phone_num", "Phone Number")
            req(email, "email", "Email")
            req(ec_name, "ec_name", "Emergency Contact Name")
            req(ec_phone, "ec_phone", "Emergency Contact Phone")

            if medical not in ("yes", "no"):
                missing.append("Medical condition (Yes/No)")
                missing_fields.add("medical")

            req(position, "position", "Position")
            req(cscs_no, "cscs_no", "CSCS Number")
            req(cscs_exp, "cscs_exp", "CSCS Expiry Date")
            req(emp_type, "emp_type", "Employment Type")

            if rtw not in ("yes", "no"):
                missing.append("Right to work UK (Yes/No)")
                missing_fields.add("rtw")

            req(ni, "ni", "National Insurance")
            req(utr, "utr", "UTR")
            req(start_date, "start_date", "Start Date")
            req(acc_no, "acc_no", "Bank Account Number")
            req(sort_code, "sort_code", "Sort Code")
            req(acc_name, "acc_name", "Account Holder Name")
            req(contract_date, "contract_date", "Date of Contract")
            req(site_address, "site_address", "Site address")

            if not contract_accept:
                missing.append("Contract acceptance")
                missing_fields.add("contract_accept")

            req(signature_name, "signature_name", "Signature name")

            if not passport_file or not passport_file.filename:
                missing.append("Passport/Birth Certificate file")
                missing_fields.add("passport_file")
            if not cscs_file or not cscs_file.filename:
                missing.append("CSCS (front/back) file")
                missing_fields.add("cscs_file")
            if not pli_file or not pli_file.filename:
                missing.append("Public Liability file")
                missing_fields.add("pli_file")
            if not share_file or not share_file.filename:
                missing.append("Share code file")
                missing_fields.add("share_file")

        if missing:
            msg = "Missing required (final): " + ", ".join(missing)
            msg_ok = False
        else:
            def v(key: str) -> str:
                return (existing or {}).get(key, "")

            passport_link = v("PassportOrBirthCertLink")
            cscs_link = v("CSCSFrontBackLink")
            pli_link = v("PublicLiabilityLink")
            share_link = v("ShareCodeLink")

            try:
                if passport_file and passport_file.filename:
                    passport_link = upload_to_drive(passport_file, f"{username}_passport")
                if cscs_file and cscs_file.filename:
                    cscs_link = upload_to_drive(cscs_file, f"{username}_cscs")
                if pli_file and pli_file.filename:
                    pli_link = upload_to_drive(pli_file, f"{username}_pli")
                if share_file and share_file.filename:
                    share_link = upload_to_drive(share_file, f"{username}_share")
            except Exception as e:
                msg = f"Upload error: {e}"
                msg_ok = False
                existing = get_onboarding_record(username)
                return render_template_string(
                    f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell(
                        "agreements", role,
                        _render_onboarding_page(display_name, role, csrf, existing, msg, msg_ok, typed, set())
                    )
                )

            now_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

            data = {
                "FirstName": first,
                "LastName": last,
                "BirthDate": birth,
                "PhoneCountryCode": phone_cc,
                "PhoneNumber": phone_num,
                "StreetAddress": street,
                "City": city,
                "Postcode": postcode,
                "Email": email,
                "EmergencyContactName": ec_name,
                "EmergencyContactPhoneCountryCode": ec_cc,
                "EmergencyContactPhoneNumber": ec_phone,
                "MedicalCondition": medical,
                "MedicalDetails": medical_details,
                "Position": position,
                "CSCSNumber": cscs_no,
                "CSCSExpiryDate": cscs_exp,
                "EmploymentType": emp_type,
                "RightToWorkUK": rtw,
                "NationalInsurance": ni,
                "UTR": utr,
                "StartDate": start_date,
                "BankAccountNumber": acc_no,
                "SortCode": sort_code,
                "AccountHolderName": acc_name,
                "CompanyTradingName": comp_trading,
                "CompanyRegistrationNo": comp_reg,
                "DateOfContract": contract_date,
                "SiteAddress": site_address,
                "PassportOrBirthCertLink": passport_link,
                "CSCSFrontBackLink": cscs_link,
                "PublicLiabilityLink": pli_link,
                "ShareCodeLink": share_link,
                "ContractAccepted": "TRUE" if (is_final and contract_accept) else "FALSE",
                "SignatureName": signature_name,
                "SignatureDateTime": now_str if is_final else "",
                "SubmittedAt": now_str,
            }

            update_or_append_onboarding(username, data)
            if DB_MIGRATION_MODE:
                try:
                    phone_full = " ".join([x for x in [phone_cc, phone_num] if x]).strip()
                    emergency_phone_full = " ".join([x for x in [ec_cc, ec_phone] if x]).strip()
                    address_full = ", ".join([x for x in [street, city, postcode] if x]).strip()

                    db_row = OnboardingRecord.query.filter_by(username=username,
                                                              workplace_id=_session_workplace_id()).first()

                    if db_row:
                        db_row.first_name = first
                        db_row.last_name = last
                        db_row.birth_date = birth
                        db_row.phone = phone_full
                        db_row.email = email
                        db_row.address = address_full
                        db_row.emergency_contact_name = ec_name
                        db_row.emergency_contact_phone = emergency_phone_full
                        db_row.medical_condition = medical
                        db_row.position = position
                    else:
                        db.session.add(
                            OnboardingRecord(
                                username=username,
                                workplace_id=_session_workplace_id(),
                                first_name=first,
                                last_name=last,
                                birth_date=birth,
                                phone=phone_full,
                                email=email,
                                address=address_full,
                                emergency_contact_name=ec_name,
                                emergency_contact_phone=emergency_phone_full,
                                medical_condition=medical,
                                position=position,
                            )
                        )

                    db.session.commit()
                except Exception:
                    db.session.rollback()
            set_employee_first_last(username, first, last)
            if is_final:
                set_employee_field(username, "OnboardingCompleted", "TRUE")
                set_employee_field(username, "Workplace_ID", _session_workplace_id())

            existing = get_onboarding_record(username)
            msg = "Saved draft." if not is_final else "Submitted final successfully."
            msg_ok = True
            typed = None
            missing_fields = set()

    content = _render_onboarding_page(display_name, role, csrf, existing, msg, msg_ok, typed, missing_fields)
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("agreements", role, content))


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
        .onboardIntroCard{ padding:18px; border-radius:24px; margin-bottom:12px; }
        .onboardHeroTop{ display:flex; justify-content:space-between; gap:14px; align-items:flex-start; flex-wrap:wrap; }
        .onboardEyebrow{ display:inline-flex; align-items:center; gap:8px; padding:7px 12px; border-radius:999px; font-size:12px; font-weight:800; letter-spacing:.05em; text-transform:uppercase; color:#1d4ed8; background:rgba(59,130,246,.10); border:1px solid rgba(96,165,250,.18); margin-bottom:10px; }
        .onboardIntroCard h1{ color:var(--text); margin:0; }
        .onboardIntroCard .sub{ color:var(--muted); }
        .onboardMiniGrid{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-top:14px; }
        .onboardMiniStat{ padding:12px 14px; border-radius:18px; background:linear-gradient(180deg, rgba(248,250,252,.98), rgba(241,245,249,.98)); border:1px solid rgba(15,23,42,.08); }
        .onboardMiniStat .k{ font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.05em; color:#64748b; }
        .onboardMiniStat .v{ margin-top:6px; font-size:15px; font-weight:700; color:var(--text); }
        .onboardShell{ padding:16px; border-radius:24px; }
        .onboardShell form > h2{ margin:18px 0 10px; padding:10px 14px; border-radius:16px; background:linear-gradient(180deg, rgba(241,245,249,.98), rgba(226,232,240,.96)); border:1px solid rgba(148,163,184,.18); color:var(--text); font-size:18px; font-weight:800; }
        .onboardShell .sub, .onboardShell label{ color:#64748b; }
        .onboardShell .uploadTitle{ margin-top:12px; font-size:13px; font-weight:800; letter-spacing:.03em; color:var(--text); }
        .onboardShell .row2{ display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:12px; align-items:start; }
        .onboardShell .input{ background:rgba(255,255,255,.96); border:1px solid rgba(15,23,42,.10); color:var(--text); box-shadow:none; }
        .onboardShell .input::placeholder{ color:#94a3b8; }
        .onboardShell .input:focus{ border-color:rgba(96,165,250,.34); box-shadow:0 0 0 3px rgba(37,99,235,.10); }
        .onboardShell .contractBox{ background:rgba(248,250,252,.96); border:1px solid rgba(15,23,42,.08); color:var(--text); }
        .onboardActionRow{ position:sticky; bottom:10px; z-index:3; margin-top:18px !important; padding:12px; border-radius:18px; background:rgba(255,255,255,.92); border:1px solid rgba(15,23,42,.08); box-shadow:0 18px 36px rgba(15,23,42,.08); backdrop-filter:blur(10px); }
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


# ---------- PROFILE (DETAILS + CHANGE PASSWORD) ----------
@app.route("/password", methods=["GET", "POST"])
def change_password():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

    details_html = onboarding_details_block(username)

    msg = ""
    ok = False

    if request.method == "POST":
        require_csrf()
        current = request.form.get("current", "")
        new1 = request.form.get("new1", "")
        new2 = request.form.get("new2", "")

        stored_pw = None
        user_row = _find_employee_record(username)
        if user_row:
            stored_pw = user_row.get("Password", "")

        if stored_pw is None or not is_password_valid(stored_pw, current):
            msg = "Current password is incorrect."
            ok = False
        elif len(new1) < 8:
            msg = "New password too short (min 8)."
            ok = False
        elif new1 != new2:
            msg = "New passwords do not match."
            ok = False
        else:
            ok = update_employee_password(username, new1)
            msg = "Password updated successfully." if ok else "Could not update password."

        details_html = onboarding_details_block(username)

    content = f"""
      {page_back_button("/", "Back to dashboard")}

      <div class="headerTop">
        <div>
          <h1>Profile</h1>
          <p class="sub">{escape(display_name)}</p>
        </div>
        <div class="badge {'admin' if role == 'admin' else ''}">{escape(role.upper())}</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

      <div class="card" style="padding:14px;">
        <h2>My Details</h2>
        <p class="sub">Saved from Starter Form (files not shown).</p>
        {details_html}
      </div>

      <div class="card" style="padding:14px; margin-top:12px;">
        <h2>Change Password</h2>
        <form method="POST">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <label class="sub">Current password</label>
          <input class="input" type="password" name="current" required>

          <label class="sub" style="margin-top:10px; display:block;">New password</label>
          <input class="input" type="password" name="new1" required>

          <label class="sub" style="margin-top:10px; display:block;">Repeat new password</label>
          <input class="input" type="password" name="new2" required>

          <button class="btnSoft" type="submit" style="margin-top:12px;">Save</button>
        </form>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("profile", role, content))


def _get_user_rate(username: str) -> float:
    """Fetch hourly rate for a username; prefer DB in migration mode, then fall back to sheet/session."""
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))
    u = (username or "").strip()

    if DB_MIGRATION_MODE:
        try:
            rec = Employee.query.filter_by(username=u, workplace_id=current_wp).first()
            if not rec:
                rec = Employee.query.filter_by(email=u, workplace_id=current_wp).first()

            if rec is not None:
                rate_val = getattr(rec, "rate", None)
                if rate_val not in (None, ""):
                    return safe_float(rate_val, 0.0)
        except Exception:
            pass

    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return safe_float(session.get("rate", 0), 0.0)

        headers = vals[0]
        if "Username" not in headers:
            return safe_float(session.get("rate", 0), 0.0)

        ucol = headers.index("Username")
        rcol = headers.index("Rate") if "Rate" in headers else None
        wpcol = headers.index("Workplace_ID") if "Workplace_ID" in headers else None

        for r in vals[1:]:
            if len(r) <= ucol:
                continue
            if (r[ucol] or "").strip() != u:
                continue

            if wpcol is not None:
                row_wp = (r[wpcol] if len(r) > wpcol else "").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

            if rcol is not None and rcol < len(r):
                return safe_float(r[rcol], default=0.0)

        return safe_float(session.get("rate", 0), 0.0)
    except Exception:
        return safe_float(session.get("rate", 0), 0.0)


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
@app.get("/admin")
def admin():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()

    # NEW: currency from Settings
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    currency_html = escape(currency)
    currency_js = currency.replace("\\", "\\\\").replace('"', '\\"')

    open_shifts = _get_open_shifts()
    employees_total = 0
    onboarding_total = 0
    locations_total = len(_get_active_locations())
    open_total = len(open_shifts)

    try:
        employees_total = len(_list_employee_records_for_workplace())
    except Exception:
        employees_total = 0

    try:
        current_wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(current_wp))
        if DB_MIGRATION_MODE:
            onboarding_total = sum(
                1
                for rec in OnboardingRecord.query.all()
                if (str(getattr(rec, "workplace_id", "default") or "default").strip() or "default") == current_wp
                and str(getattr(rec, "username", "") or "").strip()
            )
        else:
            vals_onb = onboarding_sheet.get_all_values()
            headers_onb = vals_onb[0] if vals_onb else []
            ucol_onb = headers_onb.index("Username") if "Username" in headers_onb else None
            wp_col_onb = headers_onb.index("Workplace_ID") if "Workplace_ID" in headers_onb else None

            if ucol_onb is not None:
                for r in vals_onb[1:]:
                    u = (r[ucol_onb] if ucol_onb < len(r) else "").strip()
                    if not u:
                        continue
                    if wp_col_onb is not None:
                        row_wp = (r[wp_col_onb] if wp_col_onb < len(r) else "").strip() or "default"
                        if row_wp not in allowed_wps:
                            continue
                    onboarding_total += 1
    except Exception:
        onboarding_total = 0

    if open_shifts:
        rows = []
        for s in open_shifts:
            rate = _get_user_rate(s["user"])
            rows.append(f"""
              <tr>
                <td>
                  <div>
                    <div>
                      <div style="font-weight:600;">{escape(s['name'])}</div>
                      <div class="sub" style="margin:2px 0 0 0;">{escape(s['user'])}</div>
                    </div>
                  </div>
                </td>
                <td>{escape(s['start_label'])}</td>
                <td class="num"><span class="netBadge" data-live-start="{escape(s['start_iso'])}">00:00:00</span></td>
                <td class="num" data-est-hours="{escape(s['start_iso'])}">0.00</td>
                <td class="num" data-est-pay="{escape(s['start_iso'])}" data-rate="{rate}">{currency_html}0.00</td>
                <td style="min-width:240px;">
                  <form method="POST" action="/admin/force-clockout" style="margin:0; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                    <input type="hidden" name="csrf" value="{escape(csrf)}">
                    <input type="hidden" name="user" value="{escape(s['user'])}">
                    <input class="input" type="time" step="1" name="out_time" value="" style="margin-top:0; max-width:150px;">
                    <button class="btnTiny" type="submit">Force Clock-Out</button>
                  </form>
                  <div class="sub" style="margin-top:6px;">Set the correct end time and force close the open shift.</div>
                </td>
              </tr>
            """)

        open_html = f"""
                    <div class="adminSectionCard plainSection" style="margin-top:12px;">
            <div class="adminSectionHead">
              <div class="adminSectionHeadLeft">
                <div class="adminSectionIcon live">{_svg_user()}</div>
                <div>
                  <h2 class="adminSectionTitle">Live Clocked-In</h2>
                  <p class="adminSectionSub">Employees currently clocked in. Live time updates every second.</p>
                </div>
              </div>
              <div class="adminHintChip">{len(open_shifts)} active</div>
            </div>
            <div class="tablewrap adminLiveTableWrap" style="margin-top:12px;">
              <table class="adminLiveTable">
                <thead><tr>
                  <th>Employee</th>
                  <th>Started</th>
                  <th class="num">Live Time</th>
                  <th class="num">Est Hours</th>
                  <th class="num">Est Pay</th>
                  <th>Actions</th>
                </tr></thead>
                <tbody>{''.join(rows)}</tbody>
              </table>
            </div>
            <script>
              (function(){{
                const CURRENCY = "{currency_js}";
                function pad(n){{ return String(n).padStart(2,"0"); }}
                function tick(){{
                  const now = new Date();
                  document.querySelectorAll("[data-live-start]").forEach(el=>{{
                    const startIso = el.getAttribute("data-live-start");
                    const start = new Date(startIso);
                    let diff = Math.floor((now - start)/1000);
                    if(diff < 0) diff = 0;
                    const h = Math.floor(diff/3600);
                    const m = Math.floor((diff%3600)/60);
                    const s = diff%60;
                    el.textContent = pad(h)+":"+pad(m)+":"+pad(s);
                  }});

                  document.querySelectorAll("[data-est-hours]").forEach(el=>{{
                    const startIso = el.getAttribute("data-est-hours");
                    const start = new Date(startIso);
                    let hrs = (now - start) / 3600000.0;
                    if(hrs < 0) hrs = 0;
                    if(hrs >= {BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS}) hrs = Math.max(0, hrs - {UNPAID_BREAK_HOURS});
                    hrs = Math.min(hrs, 16);
                    el.textContent = (Math.round(hrs*100)/100).toFixed(2);
                  }});

                  document.querySelectorAll("[data-est-pay]").forEach(el=>{{
                    const startIso = el.getAttribute("data-est-pay");
                    const rate = parseFloat(el.getAttribute("data-rate") || "0") || 0;
                    const start = new Date(startIso);
                    let hrs = (now - start) / 3600000.0;
                    if(hrs < 0) hrs = 0;
                    if(hrs >= {BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS}) hrs = Math.max(0, hrs - {UNPAID_BREAK_HOURS});
                    hrs = Math.min(hrs, 16);
                    const pay = hrs * rate;
                    el.textContent = CURRENCY + pay.toFixed(2);
                  }});
                }}
                tick(); setInterval(tick, 1000);
              }})();
            </script>
          </div>
        """
    else:
        open_html = f"""
          <div class="adminSectionCard plainSection" style="margin-top:12px;">
            <div class="adminSectionHead">
              <div class="adminSectionHeadLeft">
                <div class="adminSectionIcon live">{_svg_user()}</div>
                <div>
                  <h2 class="adminSectionTitle">Live Clocked-In</h2>
                  <p class="adminSectionSub">See who is currently active on site in real time.</p>
                </div>
              </div>
              <div class="adminHintChip">Live</div>
            </div>
            <p class="sub" style="margin:0;">No one is currently clocked in.</p>
          </div>
        """
    employee_options = ""
    try:
        current_wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(current_wp))

        for rec in get_employees_compat():
            u = str(rec.get("Username") or "").strip()
            if not u:
                continue

            row_wp = str(rec.get("Workplace_ID") or "default").strip() or "default"
            if row_wp not in allowed_wps:
                continue

            fn = str(rec.get("FirstName") or "").strip()
            ln = str(rec.get("LastName") or "").strip()
            disp = (fn + " " + ln).strip() or u

            employee_options += f"<option value='{escape(u)}'>{escape(disp)} ({escape(u)})</option>"
    except Exception:
        employee_options = ""

    content = f"""
      <style>
        .adminHeroCard,
        .adminSectionCard,
        .adminForceCard{{
          border:1px solid rgba(15,23,42,.08);
          background:linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
          box-shadow:0 18px 40px rgba(15,23,42,.08), inset 0 1px 0 rgba(255,255,255,.78);
        }}
        .adminHeroCard{{padding:18px; border-radius:24px; margin-bottom:12px;}}
        .adminHeroTop{{display:flex; justify-content:space-between; gap:16px; align-items:flex-start; flex-wrap:wrap;}}
        .adminHeroEyebrow{{display:inline-flex; align-items:center; gap:8px; padding:7px 12px; border-radius:999px; font-size:12px; font-weight:800; letter-spacing:.05em; text-transform:uppercase; color:#1d4ed8; background:rgba(59,130,246,.10); border:1px solid rgba(96,165,250,.18); margin-bottom:10px;}}
        .adminHeroCard h1{{color:var(--text); margin:0;}}
        .adminHeroCard .sub{{color:var(--muted);}}
        .adminForceCard{{margin-top:12px; padding:16px; border-radius:24px;}}
        .adminActionBar{{background:rgba(248,250,252,.96); border:1px solid rgba(15,23,42,.08);}}
        .adminActionBar .input{{background:rgba(255,255,255,.96); border:1px solid rgba(15,23,42,.10); color:var(--text); box-shadow:none;}}
        .adminActionBar .input:focus{{border-color:rgba(96,165,250,.34); box-shadow:0 0 0 3px rgba(37,99,235,.10);}}
        .adminPrimaryBtn{{box-shadow:0 14px 28px rgba(37,99,235,.20);}}
      </style>
      
      {admin_back_link("/")}

      <div class="adminHeroCard plainSection">
        <div class="adminHeroTop">
          <div>
            <div class="adminHeroEyebrow">Admin workspace</div>
            <h1>Admin</h1>
            <p class="sub">Payroll, onboarding, employees and workplace controls.</p>
          </div>
          <div class="badge admin">{escape(role_label(session.get('role', 'admin')))}</div>
        </div>
      </div>

                  <div class="kpiStrip adminStats" style="margin-bottom:12px;">
        <div class="kpiMini adminStatCard employees">
          <div class="k">Employees</div>
          <div class="v">{employees_total}</div>
        </div>
        <div class="kpiMini adminStatCard clocked">
          <div class="k">Clocked In</div>
          <div class="v">{open_total}</div>
        </div>
        <div class="kpiMini adminStatCard locations">
          <div class="k">Active Locations</div>
          <div class="v">{locations_total}</div>
        </div>
        <div class="kpiMini adminStatCard onboarding">
          <div class="k">Onboarding Records</div>
          <div class="v">{onboarding_total}</div>
        </div>
      </div>

            <div class="card menu adminToolsShell" style="padding:14px;">
             <div class="adminGrid">

          <a class="adminToolCard payroll" href="/admin/payroll">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_payroll_report(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Payroll Report</div>
            <div class="adminToolSub">Weekly payroll, tax, net pay and paid status.</div>
          </a>

          <a class="adminToolCard company" href="/admin/company">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_company_settings(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Company Settings</div>
            <div class="adminToolSub">Change workplace name and company-level settings.</div>
          </a>

          <a class="adminToolCard onboarding" href="/admin/onboarding">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_onboarding(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Onboarding</div>
            <div class="adminToolSub">Review starter forms, documents and contract details.</div>
          </a>

          <a class="adminToolCard locations" href="/admin/locations">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_locations(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Locations</div>
            <div class="adminToolSub">Manage geo-fence sites and allowed clock-in zones.</div>
          </a>

          <a class="adminToolCard sites" href="/admin/employee-sites">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_employee_sites(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Employee Sites</div>
            <div class="adminToolSub">Assign employees to site locations for clock-in access.</div>
          </a>

          <a class="adminToolCard employees" href="/admin/employees">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_employees(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Employees</div>
            <div class="adminToolSub">Create employees, update rates and manage access.</div>
          </a>

                    {
    f'''
              <a class="adminToolCard drive" href="/connect-drive">
                <div class="adminToolTop">
                <div class="adminToolIcon">{_icon_connect_drive(45)}</div>
                <div class="chev">›</div>
                </div>
                <div class="adminToolTitle">Connect Drive</div>
                <div class="adminToolSub">Reconnect Google Drive for onboarding uploads.</div>
              </a>
            '''
    if session.get("role") == "master_admin"
    else ""
    }
        </div>
      </div>
            <div class="card adminForceCard">
        <div class="adminSectionHead">
          <div class="adminSectionHeadLeft">
            <div class="adminSectionIcon clockin">{_svg_clock()}</div>
            <div>
              <h2 class="adminSectionTitle">Force Clock-In</h2>
              <p class="adminSectionSub">Use this if someone forgot to clock in. It creates or updates today’s row.</p>
            </div>
          </div>
          <div class="adminHintChip">Admin action</div>
        </div>

                <form method="POST" action="/admin/force-clockin" class="adminFormRow">
          <input type="hidden" name="csrf" value="{escape(csrf)}">

          <div class="adminActionBar">
            <input class="input" type="date" name="date" value="{escape(datetime.now(TZ).strftime('%Y-%m-%d'))}" style="max-width:190px;" required>

            <select class="input" name="user" style="max-width:260px;">
              {employee_options}
            </select>

            <input class="input" type="time" step="1" name="in_time" style="max-width:170px;" required>

            <button class="adminPrimaryBtn" type="submit">Force Clock-In</button>
          </div>
        </form>
      </div>
      {open_html}
    """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell(
            active="admin",
            role=session.get("role", "admin"),
            content_html=content
        )
    )


def admin_back_link(href: str = "/admin") -> str:
    return f"""
      <div style="margin:8px 0 14px;">
        <a href="{href}"
           aria-label="Back"
           title="Back"
           style="
             display:inline-flex;
             align-items:center;
             justify-content:center;
             width:32px;
             height:32px;
             border-radius:999px;
             background:#ffffff;
             border:1px solid #cbd5e1;
             color:#64748b;
             text-decoration:none;
             box-shadow:0 1px 2px rgba(15,23,42,.06);
             font-size:18px;
             font-weight:700;
             line-height:1;
           ">
          &#8249;
        </a>
      </div>
    """


@app.route("/admin/company", methods=["GET", "POST"])
def admin_company():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    role = session.get("role", "admin")
    wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(wp))

    settings = get_company_settings()
    current_name = (settings.get("Company_Name") or "").strip() or "Main"
    current_logo = (settings.get("Company_Logo_URL") or "").strip()

    msg = ""
    ok = False

    if request.method == "POST":
        require_csrf()
        new_name = (request.form.get("company_name") or "").strip()
        new_logo = (request.form.get("company_logo_url") or "").strip()

        if not new_name:
            msg = "Company name required."
        elif not settings_sheet:
            msg = "Settings sheet not configured."
        else:
            vals = settings_sheet.get_all_values()
            if not vals:
                settings_sheet.append_row(
                    ["Workplace_ID", "Tax_Rate", "Currency_Symbol", "Company_Name", "Company_Logo_URL"])
                vals = settings_sheet.get_all_values()

            hdr = vals[0] if vals else []
            if "Company_Logo_URL" not in hdr:
                settings_sheet.update_cell(1, len(hdr) + 1, "Company_Logo_URL")
                vals = settings_sheet.get_all_values()
                hdr = vals[0] if vals else []

            def idx(n):
                return hdr.index(n) if n in hdr else None

            i_wp = idx("Workplace_ID")
            i_name = idx("Company_Name")
            i_logo = idx("Company_Logo_URL")
            i_tax = idx("Tax_Rate")
            i_cur = idx("Currency_Symbol")

            if i_wp is None or i_name is None:
                msg = "Settings headers missing Workplace_ID or Company_Name."
            else:
                rownum = None
                for i in range(1, len(vals)):
                    r = vals[i]
                    row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                    if row_wp == wp:
                        rownum = i + 1
                        break

                if rownum:
                    settings_sheet.update_cell(rownum, i_name + 1, new_name)
                    if i_logo is not None:
                        settings_sheet.update_cell(rownum, i_logo + 1, new_logo)
                        if DB_MIGRATION_MODE:
                            try:
                                tax_value = settings.get("Tax_Rate", 20.0)
                                try:
                                    tax_value = float(tax_value)
                                except Exception:
                                    tax_value = 20.0

                                currency_value = str(settings.get("Currency_Symbol", "£") or "£")

                                db_row = WorkplaceSetting.query.filter_by(workplace_id=wp).first()
                                if db_row:
                                    db_row.company_name = new_name
                                    db_row.company_logo_url = new_logo
                                    db_row.tax_rate = tax_value
                                    db_row.currency_symbol = currency_value
                                    db.session.commit()
                            except Exception:
                                db.session.rollback()
                else:
                    row = [""] * len(hdr)
                    row[i_wp] = wp
                    row[i_name] = new_name
                    if i_logo is not None:
                        row[i_logo] = new_logo
                    if i_tax is not None:
                        row[i_tax] = str(settings.get("Tax_Rate", 20.0))
                    if i_cur is not None:
                        row[i_cur] = str(settings.get("Currency_Symbol", "£"))
                    settings_sheet.append_row(row)
                    if DB_MIGRATION_MODE:
                        try:
                            tax_value = settings.get("Tax_Rate", 20.0)
                            try:
                                tax_value = float(tax_value)
                            except Exception:
                                tax_value = 20.0

                            currency_value = str(settings.get("Currency_Symbol", "£") or "£")

                            db_row = WorkplaceSetting.query.filter_by(workplace_id=wp).first()
                            if db_row:
                                db_row.company_name = new_name
                                db_row.company_logo_url = new_logo
                                db_row.tax_rate = tax_value
                                db_row.currency_symbol = currency_value
                            else:
                                db.session.add(
                                    WorkplaceSetting(
                                        workplace_id=wp,
                                        tax_rate=tax_value,
                                        currency_symbol=currency_value,
                                        company_name=new_name,
                                        company_logo_url=new_logo,
                                    )
                                )

                            db.session.commit()
                        except Exception:
                            db.session.rollback()

                log_audit("SET_COMPANY_NAME", actor=session.get("username", "admin"), details=f"{wp} -> {new_name}")
                ok = True
                msg = "Saved."
                current_name = new_name
                current_logo = new_logo

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Company Settings</h1>
          <p class="sub">Workplace: <b>{escape(wp)}</b></p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {admin_back_link()}

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

      <div class="payrollEmployeeCard plainSection" style="padding:12px; margin-top:12px;">
        <form method="POST">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <label class="sub">Company name</label>
          <input class="input" name="company_name" value="{escape(current_name)}" required>

          <label class="sub" style="margin-top:10px;">Company logo URL</label>
          <input class="input" name="company_logo_url" value="{escape(current_logo)}" placeholder="https://.../logo.png">

          <button class="btnSoft" type="submit" style="margin-top:12px;">Save</button>
        </form>
      </div>
    """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )


@app.post("/admin/save-shift")
def admin_save_shift():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or request.form.get("username") or "").strip()
    date_str = (request.form.get("date") or "").strip()
    cin = (request.form.get("cin") or request.form.get("clock_in") or "").strip()
    cout = (request.form.get("cout") or request.form.get("clock_out") or "").strip()
    hours_in = (request.form.get("hours") or "").strip()
    pay_in = (request.form.get("pay") or "").strip()
    recalc = (request.form.get("recalc") == "yes")

    if not username or not date_str:
        return redirect(request.referrer or "/admin/payroll")

    # If the admin clears all fields for a day, treat that as "delete this shift".
    delete_shift = (cin == "" and cout == "" and hours_in == "" and pay_in == "")

    if delete_shift:
        if DB_MIGRATION_MODE:
            try:
                shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                deleted = WorkHour.query.filter(
                    WorkHour.employee_email == username,
                    WorkHour.date == shift_date,
                    WorkHour.workplace_id == _session_workplace_id(),
                ).delete(synchronize_session=False)

                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return make_response(f"Could not delete shift: {e}", 500)

            return redirect(request.referrer or "/admin/payroll")

        try:
            vals = work_sheet.get_all_values()
            rownum = _find_workhours_row_by_user_date(vals, username, date_str)
            if rownum:
                work_sheet.delete_rows(rownum)
        except Exception as e:
            return make_response(f"Could not delete shift: {e}", 500)

        return redirect(request.referrer or "/admin/payroll")

    rate = _get_user_rate(username)
    hours_val = None if hours_in == "" else safe_float(hours_in, 0.0)
    pay_val = None if pay_in == "" else safe_float(pay_in, 0.0)

    auto_calc = recalc or (cin and cout and hours_in == "" and pay_in == "")
    if cin and cout and auto_calc:
        computed = _compute_hours_from_times(date_str, cin, cout)
        if computed is not None:
            hours_val = computed
            pay_val = round(computed * rate, 2)

    if hours_in != "" and pay_in == "":
        pay_val = round(safe_float(hours_in, 0.0) * rate, 2)

    hours_cell = "" if hours_val is None else str(hours_val)
    pay_cell = "" if pay_val is None else str(pay_val)

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            db_row = _workhour_query_for_user(username, _session_workplace_id()).filter(
                WorkHour.date == shift_date
            ).order_by(WorkHour.id.desc()).first()

            if not db_row:
                db_row = WorkHour(
                    employee_email=username,
                    date=shift_date,
                    workplace=_session_workplace_id(),
                    workplace_id=_session_workplace_id(),
                )
                db.session.add(db_row)

            clock_in_dt = None
            clock_out_dt = None
            cin_db = cin
            cout_db = cout

            if cin_db:
                if len(cin_db.split(":")) == 2:
                    cin_db = cin_db + ":00"
                clock_in_dt = datetime.strptime(f"{date_str} {cin_db}", "%Y-%m-%d %H:%M:%S")

            if cout_db:
                if len(cout_db.split(":")) == 2:
                    cout_db = cout_db + ":00"
                clock_out_dt = datetime.strptime(f"{date_str} {cout_db}", "%Y-%m-%d %H:%M:%S")
                if clock_in_dt and clock_out_dt < clock_in_dt:
                    clock_out_dt = clock_out_dt + timedelta(days=1)

            db_row.clock_in = clock_in_dt
            db_row.clock_out = clock_out_dt
            db_row.hours = float(hours_cell) if hours_cell != "" else None
            db_row.pay = float(pay_cell) if pay_cell != "" else None
            db_row.workplace = _session_workplace_id()
            db_row.workplace_id = _session_workplace_id()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not save shift: {e}", 500)
        return redirect(request.referrer or "/admin/payroll")

    try:
        vals = work_sheet.get_all_values()
        headers = vals[0] if vals else []
        rownum = _find_workhours_row_by_user_date(vals, username, date_str)

        if not rownum:
            new_row = [username, date_str, cin, cout, hours_cell, pay_cell]
            if headers and "Workplace_ID" in headers:
                wp_idx = headers.index("Workplace_ID")
                if len(new_row) <= wp_idx:
                    new_row += [""] * (wp_idx + 1 - len(new_row))
                new_row[wp_idx] = _session_workplace_id()
            if headers and len(new_row) < len(headers):
                new_row += [""] * (len(headers) - len(new_row))
            work_sheet.append_row(new_row)
        else:
            updates = [
                {"range": gspread.utils.rowcol_to_a1(rownum, COL_IN + 1), "values": [[cin]]},
                {"range": gspread.utils.rowcol_to_a1(rownum, COL_OUT + 1), "values": [[cout]]},
                {"range": gspread.utils.rowcol_to_a1(rownum, COL_HOURS + 1), "values": [[hours_cell]]},
                {"range": gspread.utils.rowcol_to_a1(rownum, COL_PAY + 1), "values": [[pay_cell]]},
            ]
            if headers and "Workplace_ID" in headers:
                wp_col = headers.index("Workplace_ID") + 1
                updates.append(
                    {"range": gspread.utils.rowcol_to_a1(rownum, wp_col), "values": [[_session_workplace_id()]]})
            _gs_write_with_retry(lambda: work_sheet.batch_update(updates))
    except Exception as e:
        return make_response(f"Could not save shift: {e}", 500)

    return redirect(request.referrer or "/admin/payroll")


@app.post("/admin/force-clockin")
def admin_force_clockin():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or "").strip()
    in_time = (request.form.get("in_time") or "").strip()
    date_str = (request.form.get("date") or "").strip()

    if not username or not in_time or not date_str:
        return redirect(request.referrer or "/admin")

    if len(in_time.split(":")) == 2:
        in_time = in_time + ":00"

    rows = get_workhours_rows()
    if find_open_shift(rows, username):
        return redirect(request.referrer or "/admin")

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            clock_in_dt = datetime.strptime(f"{date_str} {in_time}", "%Y-%m-%d %H:%M:%S")
            db_row = _workhour_query_for_user(username, _session_workplace_id()).filter(
                WorkHour.date == shift_date
            ).order_by(WorkHour.id.desc()).first()

            if db_row:
                db_row.clock_in = clock_in_dt
                db_row.clock_out = None
                db_row.hours = None
                db_row.pay = None
                db_row.workplace = _session_workplace_id()
                db_row.workplace_id = _session_workplace_id()
            else:
                db.session.add(
                    WorkHour(
                        employee_email=username,
                        date=shift_date,
                        clock_in=clock_in_dt,
                        clock_out=None,
                        hours=None,
                        pay=None,
                        workplace=_session_workplace_id(),
                        workplace_id=_session_workplace_id(),
                    )
                )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not force clock in: {e}", 500)
    else:
        try:
            vals = work_sheet.get_all_values()
            headers = vals[0] if vals else []
            rownum = _find_workhours_row_by_user_date(vals, username, date_str)
            wp_col = (headers.index("Workplace_ID") + 1) if ("Workplace_ID" in headers) else None

            if rownum:
                work_sheet.update_cell(rownum, COL_IN + 1, in_time)
                work_sheet.update_cell(rownum, COL_OUT + 1, "")
                work_sheet.update_cell(rownum, COL_HOURS + 1, "")
                work_sheet.update_cell(rownum, COL_PAY + 1, "")
                if wp_col:
                    work_sheet.update_cell(rownum, wp_col, _session_workplace_id())
            else:
                new_row = [username, date_str, in_time, "", "", ""]
                if headers and "Workplace_ID" in headers:
                    wp_idx = headers.index("Workplace_ID")
                    if len(new_row) <= wp_idx:
                        new_row += [""] * (wp_idx + 1 - len(new_row))
                    new_row[wp_idx] = _session_workplace_id()
                if headers and len(new_row) < len(headers):
                    new_row += [""] * (len(headers) - len(new_row))
                work_sheet.append_row(new_row)
        except Exception as e:
            return make_response(f"Could not force clock in: {e}", 500)

    actor = session.get("username", "admin")
    log_audit("FORCE_CLOCK_IN", actor=actor, username=username, date_str=date_str, details=f"in={in_time}")
    return redirect(request.referrer or "/admin")


@app.post("/admin/force-clockout")
def admin_force_clockout():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or "").strip()
    out_time = (request.form.get("out_time") or "").strip()

    if not username or not out_time:
        return redirect(request.referrer or "/admin")

    rows = get_workhours_rows()
    osf = find_open_shift(rows, username)
    if not osf:
        return redirect(request.referrer or "/admin")

    idx, d, cin = osf
    rate = _get_user_rate(username)

    if len(out_time.split(":")) == 2:
        out_time = out_time + ":00"

    computed_hours = _compute_hours_from_times(d, cin, out_time)
    if computed_hours is None:
        return redirect(request.referrer or "/admin")

    pay = round(computed_hours * rate, 2)

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(d, "%Y-%m-%d").date()
            clock_out_dt = datetime.strptime(f"{d} {out_time}", "%Y-%m-%d %H:%M:%S")
            clock_in_dt_check = datetime.strptime(f"{d} {cin}", "%Y-%m-%d %H:%M:%S")
            if clock_out_dt < clock_in_dt_check:
                clock_out_dt = clock_out_dt + timedelta(days=1)

            db_row = _workhour_query_for_user(username, _session_workplace_id()).filter(
                WorkHour.date == shift_date
            ).order_by(WorkHour.id.desc()).first()

            if db_row:
                if not getattr(db_row, "clock_in", None):
                    db_row.clock_in = clock_in_dt_check
                db_row.clock_out = clock_out_dt
                db_row.hours = computed_hours
                db_row.pay = pay
                db_row.workplace = _session_workplace_id()
                db_row.workplace_id = _session_workplace_id()
            else:
                db.session.add(
                    WorkHour(
                        employee_email=username,
                        date=shift_date,
                        clock_in=clock_in_dt_check,
                        clock_out=clock_out_dt,
                        hours=computed_hours,
                        pay=pay,
                        workplace=_session_workplace_id(),
                        workplace_id=_session_workplace_id(),
                    )
                )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not force clock out: {e}", 500)
    else:
        sheet_row = idx + 1
        try:
            vals = work_sheet.get_all_values()
            headers = vals[0] if vals else []
            updates = [
                {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_OUT + 1), "values": [[out_time]]},
                {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_HOURS + 1), "values": [[str(computed_hours)]]},
                {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_PAY + 1), "values": [[str(pay)]]},
            ]
            if headers and "Workplace_ID" in headers:
                wp_col = headers.index("Workplace_ID") + 1
                updates.append(
                    {"range": gspread.utils.rowcol_to_a1(sheet_row, wp_col), "values": [[_session_workplace_id()]]})
            _gs_write_with_retry(lambda: work_sheet.batch_update(updates))
        except Exception as e:
            return make_response(f"Could not force clock out: {e}", 500)

    actor = session.get("username", "admin")
    log_audit("FORCE_CLOCK_OUT", actor=actor, username=username, date_str=d,
              details=f"out={out_time} hours={computed_hours} pay={pay}")
    return redirect(request.referrer or "/admin")


@app.post("/admin/mark-paid")
def admin_mark_paid():
    gate = require_admin()
    if gate:
        return gate

    try:
        require_csrf()
    except Exception:
        return redirect(request.referrer or "/admin/payroll")

    try:
        week_start = (request.form.get("week_start") or "").strip()
        week_end = (request.form.get("week_end") or "").strip()
        username = (request.form.get("user") or request.form.get("username") or "").strip()

        gross = safe_float(request.form.get("gross", "0") or "0", 0.0)
        tax = safe_float(request.form.get("tax", "0") or "0", 0.0)
        net = safe_float(request.form.get("net", "0") or "0", 0.0)

        paid_by = session.get("username", "admin")

        if week_start and week_end and username:
            _append_paid_record_safe(week_start, week_end, username, gross, tax, net, paid_by)
    except Exception:
        pass

    return redirect(request.referrer or "/admin/payroll")


@app.get("/admin/payroll")
def admin_payroll():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    _ensure_workhours_geo_headers()
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    company_name = str(settings.get("Company_Name") or "Main").strip() or "Main"
    company_logo = str(settings.get("Company_Logo_URL") or "").strip()
    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    q = (request.args.get("q", "") or "").strip().lower()
    date_from = (request.args.get("from", "") or "").strip()
    date_to = (request.args.get("to", "") or "").strip()

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    employee_records = []
    try:
        employee_records = _list_employee_records_for_workplace(include_inactive=True)
    except Exception:
        employee_records = []
    current_users = [
        (rec.get("Username") or "").strip()
        for rec in employee_records
        if (rec.get("Username") or "").strip()
    ]
    current_usernames = set(current_users)

    today = datetime.now(TZ).date()
    wk_offset_raw = (request.args.get("wk", "0") or "0").strip()
    try:
        wk_offset = max(0, int(wk_offset_raw))
    except Exception:
        wk_offset = 0

    this_monday = today - timedelta(days=today.weekday())
    week_start = this_monday - timedelta(days=7 * wk_offset)
    week_end = week_start + timedelta(days=6)
    week_start_str = week_start.strftime("%Y-%m-%d")
    week_end_str = week_end.strftime("%Y-%m-%d")

    def week_label(d0):
        iso = d0.isocalendar()
        return f"Week {iso[1]} ({d0.strftime('%d %b')} – {(d0 + timedelta(days=6)).strftime('%d %b %Y')})"

    def in_range(d: str) -> bool:
        if not d:
            return False
        if date_from and d < date_from:
            return False
        if date_to and d > date_to:
            return False
        return True

    filtered = []
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        user = (r[COL_USER] or "").strip()
        if not user or user not in current_usernames:
            continue

        # Workplace filter: prefer WorkHours row Workplace_ID (tenant-safe)
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            # Backward compat if WorkHours has no Workplace_ID column
            if not user_in_same_workplace(user):
                continue
        d = (r[COL_DATE] or "").strip()
        if not in_range(d):
            continue
        if q and q not in user.lower():
            continue
        filtered.append({
            "user": user,
            "date": d,
            "cin": (r[COL_IN] if len(r) > COL_IN else "") or "",
            "cout": (r[COL_OUT] if len(r) > COL_OUT else "") or "",
            "hours": (r[COL_HOURS] if len(r) > COL_HOURS else "") or "",
            "pay": (r[COL_PAY] if len(r) > COL_PAY else "") or "",
        })

    by_user = {}
    overall_hours = 0.0
    overall_gross = 0.0

    for row in filtered:
        u = row["user"] or "Unknown"
        by_user.setdefault(u, {"hours": 0.0, "gross": 0.0})
        if row["hours"] != "":
            h = _round_to_half_hour(safe_float(row["hours"], 0.0))
            g = safe_float(row["pay"], 0.0)
            by_user[u]["hours"] += h
            by_user[u]["gross"] += g
            overall_hours += h
            overall_gross += g

    overall_tax = round(overall_gross * tax_rate, 2)
    overall_net = round(overall_gross - overall_tax, 2)

    # Week lookup for editable tables
    week_lookup = {}
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        user = (r[COL_USER] or "").strip()
        d = (r[COL_DATE] or "").strip()
        if not user or not d:
            continue
        # Workplace filter for weekly tables (tenant-safe)
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(user):
                continue
        if d < week_start_str or d > week_end_str:
            continue
        week_lookup.setdefault(user, {})
        week_lookup[user][d] = {
            "cin": (r[COL_IN] if len(r) > COL_IN else "") or "",
            "cout": (r[COL_OUT] if len(r) > COL_OUT else "") or "",
            "hours": (r[COL_HOURS] if len(r) > COL_HOURS else "") or "",
            "pay": (r[COL_PAY] if len(r) > COL_PAY else "") or "",
        }

    # Include both current employee records and any users that have week rows
    all_users = sorted(set(current_users) | set(week_lookup.keys()), key=lambda s: s.lower())

    if q:
        all_users = [u for u in all_users if q in u.lower() or q in (get_employee_display_name(u) or "").lower()]

    employee_options = ["<option value=''>All employees</option>"]
    for u in sorted(all_users, key=lambda s: get_employee_display_name(s).lower()):
        display = get_employee_display_name(u)
        selected = "selected" if q == u.lower() else ""
        employee_options.append(
            f"<option value='{escape(u)}' {selected}>{escape(display)}</option>"
        )

    # Week dropdown
    week_options = []
    for i in range(0, 52):
        d0 = this_monday - timedelta(days=7 * i)
        selected = "selected" if i == wk_offset else ""
        week_options.append(
            f"<option value='{i}' {selected}>{escape(week_label(d0))}</option>"
        )

    week_nav_html = f"""
      <form method="GET"
            style="margin-top:14px; display:flex; flex-wrap:wrap; gap:16px; align-items:end; justify-content:space-between; padding:18px 20px; border-radius:24px; border:1px solid rgba(109,40,217,.10); background:linear-gradient(180deg,#ffffff,#f8f7ff); box-shadow:0 14px 30px rgba(41,25,86,.08);">
        <input type="hidden" name="q" value="{escape(q)}">
        <input type="hidden" name="from" value="{escape(date_from)}">
        <input type="hidden" name="to" value="{escape(date_to)}">

        <div style="flex:1 1 320px; min-width:260px;">
          <div style="display:inline-flex; align-items:center; padding:8px 14px; border-radius:999px; border:1px solid rgba(109,40,217,.12); background:rgba(109,40,217,.06); color:#4338ca; font-size:13px; font-weight:800; text-transform:uppercase; letter-spacing:.05em;">
            Employee detail tables
          </div>
          <div style="margin-top:10px; color:#6f6c85; font-size:15px;">
            Choose the week shown in the individual employee tables below.
          </div>
        </div>

        <div style="flex:0 1 360px; min-width:260px; display:flex; flex-direction:column; gap:8px;">
          <label for="payroll-week-select"
                 style="font-size:12px; font-weight:800; letter-spacing:.06em; text-transform:uppercase; color:#6f6c85;">
            Week
          </label>
          <select id="payroll-week-select" class="input" name="wk" onchange="this.form.submit()"
                  style="margin-top:0; height:56px; border-radius:18px; border:1px solid rgba(109,40,217,.14); background:#ffffff; color:#1f2547; font-weight:800; box-shadow:0 8px 20px rgba(41,25,86,.06);">
            {''.join(week_options)}
          </select>
        </div>
      </form>
    """
    # Payroll donut chart data (gross by employee for current filtered view)
    chart_palette = [
        "#2563eb", "#7c3aed", "#16a34a", "#f59e0b", "#ef4444",
        "#06b6d4", "#84cc16", "#ec4899", "#14b8a6", "#8b5cf6"
    ]

    chart_rows = []
    for u in current_users:
        display_name = get_employee_display_name(u)

        if q and q not in u.lower() and q not in display_name.lower():
            continue

        gross_u = 0.0
        for rec in (week_lookup.get(u, {}) or {}).values():
            gross_u += safe_float(rec.get("pay", "0"), 0.0)

        gross_u = round(gross_u, 2)
        if gross_u <= 0:
            continue

        chart_rows.append({
            "user": u,
            "name": display_name,
            "gross": gross_u,
        })

    chart_rows = sorted(chart_rows, key=lambda x: x["gross"], reverse=True)
    chart_top = chart_rows[:15]
    other_total = round(sum(x["gross"] for x in chart_rows[15:]), 2)

    chart_segments = []
    for i, item in enumerate(chart_top):
        chart_segments.append({
            "label": item["name"],
            "value": item["gross"],
            "color": chart_palette[i % len(chart_palette)],
        })

    if other_total > 0:
        chart_segments.append({
            "label": "Other",
            "value": other_total,
            "color": "#94a3b8",
        })

    total_chart_value = round(sum(x["value"] for x in chart_segments), 2)

    donut_css = "#e5e7eb"
    pie_html = "<div class='activityEmpty'>No payroll data for current filters.</div>"

    if total_chart_value > 0:
        angle_acc = 0.0
        stops = []
        label_parts = []

        for seg in chart_segments:
            pct = (seg["value"] / total_chart_value) * 100.0
            start = angle_acc
            end = angle_acc + pct
            mid = (start + end) / 2.0

            stops.append(f"{seg['color']} {start:.2f}% {end:.2f}%")
            angle_acc = end

            theta = math.radians((mid * 3.6) - 90.0)
            x = 50.0 + math.cos(theta) * 28.0
            y = 50.0 + math.sin(theta) * 28.0

            label_parts.append(f'''
                  <div class="payrollPieLabel" style="left:{x:.2f}%; top:{y:.2f}%;">
                    <div class="pct">{pct:.0f}%</div>
                    <div class="amt">{escape(currency)}{money(seg['value'])}</div>
                    <div class="name">{escape(seg['label'])}</div>
                  </div>
                ''')

        donut_css = f"conic-gradient({', '.join(stops)})"

        pie_html = f'''
              <div class="payrollPieWrap">
                <div class="payrollPie" style="background:{donut_css};"></div>
                {''.join(label_parts)}
              </div>
            '''

    # KPI strip (PRO)
    kpi_strip = f"""
      <div class="kpiStrip">
        <div class="kpiMini"><div class="k">Hours</div><div class="v">{round(overall_hours, 2)}</div></div>
        <div class="kpiMini"><div class="k">Gross</div><div class="v">{escape(currency)}{money(overall_gross)}</div></div>
        <div class="kpiMini"><div class="k">Tax</div><div class="v">{escape(currency)}{money(overall_tax)}</div></div>
        <div class="kpiMini"><div class="k">Net</div><div class="v">{escape(currency)}{money(overall_net)}</div></div>
      </div>
    """

    # Summary table (polished + paid under name)
    summary_rows = []
    for u in sorted(all_users, key=lambda s: s.lower()):
        gross = round(by_user.get(u, {}).get("gross", 0.0), 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)
        hours = round(by_user.get(u, {}).get("hours", 0.0), 2)

        display = get_employee_display_name(u)
        paid, paid_at = _is_paid_for_week(week_start_str, week_end_str, u)

        paid_line = ""
        if paid:
            paid_line = f"<div class='sub' style='margin:2px 0 0 0;'><span class='chip ok'>Paid</span></div>"
            if paid_at:
                paid_line += f"<div class='sub' style='margin:2px 0 0 0;'>Paid at: {escape(paid_at)}</div>"
        else:
            paid_line = "<div class='sub' style='margin:2px 0 0 0;'><span class='chip warn'>Not paid</span></div>"

        mark_paid_btn = ""
        if (not paid) and gross > 0:
            mark_paid_btn = f"""
              <form method="POST" action="/admin/mark-paid" style="margin:0;">
                <input type="hidden" name="csrf" value="{escape(csrf)}">
                <input type="hidden" name="week_start" value="{escape(week_start_str)}">
                <input type="hidden" name="week_end" value="{escape(week_end_str)}">
                <input type="hidden" name="user" value="{escape(u)}">
                <input type="hidden" name="gross" value="{gross}">
                <input type="hidden" name="tax" value="{tax}">
                <input type="hidden" name="net" value="{net}">
                <button class="btnTiny dark" type="submit">Paid</button>
              </form>
            """

        row_class = "rowHasValue" if gross > 0 else ""

        name_cell = f"""
          <div>
            <div>
              <div style="font-weight:600;">{escape(display)}</div>
              <div class="sub" style="margin:2px 0 0 0;">{escape(u)}</div>
              {paid_line}
            </div>
          </div>
        """

        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    sheet_rows = []

    for u in sorted(all_users, key=lambda s: get_employee_display_name(s).lower()):
        display = get_employee_display_name(u)
        user_days = week_lookup.get(u, {})

        total_hours = 0.0
        gross = 0.0

        def show_num(v):
            try:
                vv = float(v)
                return "" if abs(vv) < 0.005 else fmt_hours(vv)
            except Exception:
                return ""

        cells = [f"""
          <td class="payrollEmpCell">
            <span class="emp">{escape(display)}</span>
          </td>
        """]

        for di in range(7):
            d_str = (week_start + timedelta(days=di)).strftime("%Y-%m-%d")
            rec = user_days.get(d_str, {}) if isinstance(user_days, dict) else {}

            cin = ((rec.get("cin", "") if isinstance(rec, dict) else "") or "").strip()
            cout = ((rec.get("cout", "") if isinstance(rec, dict) else "") or "").strip()
            hrs = _round_to_half_hour(
                safe_float((rec.get("hours", "0") if isinstance(rec, dict) else "0"), default=0.0))
            pay = safe_float((rec.get("pay", "0") if isinstance(rec, dict) else "0"), default=0.0)

            total_hours += hrs
            gross += pay

            form_id = f"payroll_{re.sub(r'[^a-zA-Z0-9]+', '_', u)}_{d_str.replace('-', '_')}"
            has_day_value = bool(cin or cout or hrs > 0 or pay > 0)
            day_cls = "payrollDayCellOT" if hrs > OVERTIME_HOURS else ""

            if has_day_value:
                hrs_txt = f"{show_num(hrs)}h" if hrs > 0 else "—"
                day_inner = f"""
                     <div class="payrollDayStack">
                       <div class="payrollDayLine">
                         <input
                           class="payrollTimeInput"
                           type="time"
                           step="60"
                           name="cin"
                           value="{escape(cin[:5])}"
                           form="{form_id}"
                           data-autosave="1">
                       </div>
                       <div class="payrollDayLine">
                         <input
                           class="payrollTimeInput"
                           type="time"
                           step="60"
                           name="cout"
                           value="{escape(cout[:5])}"
                           form="{form_id}"
                           data-autosave="1">
                       </div>
                       <div class="payrollDayHours">{escape(hrs_txt)}</div>
                     </div>
                   """
            else:
                day_inner = '<div class="payrollDayEmpty">—</div>'

            cells.append(f"""
                 <td class="payrollDayCell {day_cls}">
                   {day_inner}
                   <form id="{form_id}" method="POST" action="/admin/save-shift" style="display:none;">
                     <input type="hidden" name="csrf" value="{escape(csrf)}">
                     <input type="hidden" name="user" value="{escape(u)}">
                     <input type="hidden" name="date" value="{escape(d_str)}">
                   </form>
                 </td>
               """)

        gross = round(gross, 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)

        paid, _paid_at = _is_paid_for_week(week_start_str, week_end_str, u)

        cells.append(
            f"<td class='num payrollSummaryTotal' style='color:#1d4ed8 !important; font-weight:900;'>{show_num(total_hours)}</td>")
        cells.append(
            f"<td class='num payrollSummaryMoney'>{(escape(currency) + money(gross)) if gross > 0 else ''}</td>")
        cells.append(f"<td class='num payrollSummaryMoney'>{(escape(currency) + money(tax)) if tax > 0 else ''}</td>")

        if paid:
            cells.append(
                f"<td class='num payrollSummaryMoney net paidNetCell'><span class='paidNetBadge'>{escape(currency)}{money(net)} · Paid</span></td>")
        elif gross > 0:
            cells.append(f"""
                 <td class='num payrollSummaryMoney net'>
                   <form method="POST" action="/admin/mark-paid" class="payCellForm">
                     <input type="hidden" name="csrf" value="{escape(csrf)}">
                     <input type="hidden" name="week_start" value="{escape(week_start_str)}">
                     <input type="hidden" name="week_end" value="{escape(week_end_str)}">
                     <input type="hidden" name="user" value="{escape(u)}">
                     <input type="hidden" name="gross" value="{gross}">
                     <input type="hidden" name="tax" value="{tax}">
                     <input type="hidden" name="net" value="{net}">
                     <button class="payCellBtn" type="submit">
                       {escape(currency)}{money(net)} <span class="payLabel">Pay</span>
                     </button>
                   </form>
                 </td>
               """)
        else:
            cells.append("<td class='num payrollSummaryMoney'></td>")

        sheet_rows.append("<tr>" + "".join(cells) + "</tr>")

    sheet_html = "".join(sheet_rows)

    # Per-user weekly editable tables
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    blocks = []
    for u in sorted(all_users, key=lambda s: s.lower()):
        display = get_employee_display_name(u)
        user_days = week_lookup.get(u, {})

        # Show the editable weekly table only if the employee has at least 1 REAL record in this week
        has_any = False
        for rec in user_days.values():
            if isinstance(rec, dict) and (
                    rec.get("cin") or
                    rec.get("cout") or
                    safe_float(rec.get("hours", "0"), 0.0) > 0 or
                    safe_float(rec.get("pay", "0"), 0.0) > 0
            ):
                has_any = True
                break

        if not has_any:
            continue

        wk_hours = 0.0
        wk_gross = 0.0
        wk_overtime_days = 0

        for di in range(7):
            d_str = (week_start + timedelta(days=di)).strftime("%Y-%m-%d")
            rec = user_days.get(d_str)
            if rec and rec.get("hours"):
                h = _round_to_half_hour(safe_float(rec.get("hours", "0"), 0.0))
                wk_hours += h
                if h > OVERTIME_HOURS:
                    wk_overtime_days += 1
            if rec and rec.get("pay"):
                wk_gross += safe_float(rec.get("pay", "0"), 0.0)

        wk_hours = round(wk_hours, 2)
        wk_gross = round(wk_gross, 2)
        wk_tax = round(wk_gross * tax_rate, 2)
        wk_net = round(wk_gross - wk_tax, 2)

        paid, paid_at = _is_paid_for_week(week_start_str, week_end_str, u)

        rows_html = []
        for di in range(7):
            d_dt = week_start + timedelta(days=di)
            d_str = d_dt.strftime("%Y-%m-%d")
            d_display = d_dt.strftime("%y-%m-%d")
            rec = user_days.get(d_str)

            cin = rec["cin"] if rec else ""
            cout = rec["cout"] if rec else ""
            hrs = rec["hours"] if rec else ""
            pay = rec["pay"] if rec else ""

            h_val = _round_to_half_hour(safe_float(hrs, 0.0)) if str(hrs).strip() != "" else 0.0
            overtime_row_class = "overtimeRow" if (str(hrs).strip() != "" and h_val > OVERTIME_HOURS) else ""

            if rec:
                if cout.strip() == "" and cin.strip() != "":
                    status_html = "<span class='chip bad'>Open</span>"
                elif cin.strip() and cout.strip():
                    status_html = "<span class='chip ok'>Complete</span>"
                else:
                    status_html = "<span class='chip warn'>Partial</span>"
            else:
                status_html = "<span class='chip'>Missing</span>"

            ot_badge = ""
            if overtime_row_class:
                ot_badge = "<span class='overtimeChip'>Overtime</span>"

            has_row = bool(
                rec and (
                        str(cin).strip() or
                        str(cout).strip() or
                        str(hrs).strip() or
                        str(pay).strip()
                )
            )

            cin_txt = ""
            if has_row and str(cin).strip() not in ("", "--:--", "--:--:--"):
                cin_txt = str(cin).strip()[:5]

            cout_txt = ""
            if has_row and str(cout).strip() not in ("", "--:--", "--:--:--"):
                cout_txt = str(cout).strip()[:5]

            hrs_txt = ""
            if has_row:
                hrs_txt = fmt_hours(hrs)

            pay_txt = ""
            if has_row:
                pay_txt = money(safe_float(pay, 0.0))

            rows_html.append(f"""
              <tr class="{overtime_row_class}">
                <td><b>{day_names[di]}</b></td>
                <td style="text-align:center;">{escape(d_display)}</td>
                <td style="font-weight:700; text-align:center;">{escape(cin_txt)}</td>
                <td style="font-weight:700; text-align:center;">{escape(cout_txt)}</td>
                <td class="num" style="font-weight:700;">{escape(hrs_txt)}</td>
<td class="num" style="font-weight:700;">{escape(pay_txt)}</td>
<td class="num" style="font-weight:800; color:rgba(15,23,42,.92);">{escape(money(round(safe_float(pay, 0.0) * (1 - tax_rate), 2))) if has_row else ""}</td>
              </tr>
            """)

        blocks.append(f"""
          <div class="payrollEmployeeCard plainSection" style="padding:12px; margin-top:12px;">
            <div class="payrollEmployeeHead">
              <div class="payrollEmployeeName">{escape(display)}</div>
            </div>

            <div class="tablewrap" style="margin-top:12px;">
              <table class="weeklyEditTable">
                <colgroup>
  <col style="width:38px;">
  <col style="width:78px;">
  <col style="width:56px;">
  <col style="width:56px;">
  <col style="width:46px;">
  <col style="width:64px;">
  <col style="width:64px;">
</colgroup>
                <thead>
                  <tr>
                    <th>Day</th>
                    <th>Date</th>
                    <th>Clock In</th>
                    <th>Clock Out</th>
                    <th class="num">Hours</th>
                    <th class="num">Gross</th>
                    <th class="num">Net</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(rows_html)}
                </tbody>
              </table>
            </div>
            <div class="payrollSummaryBar">
    <div class="payrollSummaryItem">
        <div class="k">Hours</div>
        <div class="v">{wk_hours:.2f}</div>
    </div>

    <div class="payrollSummaryItem">
        <div class="k">Gross</div>
        <div class="v">{escape(currency)}{money(wk_gross)}</div>
    </div>

    <div class="payrollSummaryItem">
        <div class="k">Tax</div>
        <div class="v">{escape(currency)}{money(wk_tax)}</div>
    </div>

    <div class="payrollSummaryItem net">
        <div class="k">Net</div>
        <div class="v">{escape(currency)}{money(wk_net)}</div>
    </div>

        <div class="payrollSummaryItem paidat">
        <div class="k">Paid at</div>
        <div class="v">{escape(paid_at) if paid and paid_at else "—"}</div>
    </div>
</div>
          </div>
        """)

    last_updated = datetime.now(TZ).strftime("%d %b %Y • %H:%M")
    csv_url = "/admin/payroll-report.csv"
    if request.query_string:
        csv_url += "?" + request.query_string.decode("utf-8", "ignore")

    content = f"""
      <div class="payrollMenuBackdrop" id="payrollMenuBackdrop"></div>

      <div class="headerTop">
        <div>
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <button type="button" class="payrollMenuToggle" id="payrollMenuToggle" aria-label="Toggle menu"></button>
            <div>
              <h1>Payroll Report</h1>
              <p class="sub">Printable • Updated {escape(last_updated)} • Weekly tables auto-update every week</p>
            </div>
          </div>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {admin_back_link()}

            <div class="payrollTopGrid">
        <div class="card payrollFiltersCard">
          <form method="GET">
            <div>
              <label class="sub">Employee</label>
              <select class="input" name="q">
                {''.join(employee_options)}
              </select>
            </div>

            <div style="margin-top:10px;">
              <label class="sub">Date range (summary table only)</label>
              <div class="row2 payrollDateRow">
  <div>
    <input class="input" type="date" name="from" value="{escape(date_from)}">
  </div>
  <div>
    <input class="input" type="date" name="to" value="{escape(date_to)}">
  </div>
</div>
            </div>

            <input type="hidden" name="wk" value="{wk_offset}">
            <button class="btnSoft" type="submit" style="margin-top:12px;">Apply</button>
          </form>

          {kpi_strip}

          <div style="margin-top:10px;">
            <a href="{csv_url}">
              <button class="btnTiny csvDownload" type="button">Download CSV</button>
            </a>
          </div>
        </div>

        <div class="payrollChartCard plainSection">
          <div class="sectionHead">
            <div class="sectionHeadLeft">
              <div class="sectionIcon">{_svg_chart()}</div>
              <div>
                <h2 style="margin:0;">Payroll Split</h2>
                <p class="sub" style="margin:4px 0 0 0;">Gross by employee for current filters.</p>
              </div>
            </div>
          </div>

          <div class="payrollPieSection">
            {pie_html}
          </div>
        </div>
      </div>

              <div class="payrollWrap" style="margin-top:12px;">
        <table class="payrollSheet">
          <thead>
            <tr class="cols">
              <th>Employee</th>
              <th>Mon</th>
              <th>Tue</th>
              <th>Wed</th>
              <th>Thu</th>
              <th>Fri</th>
              <th>Sat</th>
              <th>Sun</th>
              <th class="payrollSummaryTotal">Total</th>
              <th class="payrollSummaryMoney">Gross</th>
              <th class="payrollSummaryMoney">Tax</th>
              <th class="payrollSummaryMoney">Net</th>
            </tr>
          </thead>
          <tbody>
            {sheet_html}
          </tbody>
        </table>
      </div>

      {week_nav_html}

      {''.join(blocks)}



<script>
(function(){{
  const tbody = document.querySelector(".payrollWrap .payrollSheet tbody");
  if(!tbody) return;

  let selected = null;

  tbody.querySelectorAll("tr").forEach((tr) => {{
    tr.style.cursor = "pointer";

    tr.addEventListener("click", (e) => {{
      if (e.target.closest("input, button, form, a, select")) return;

      if (selected === tr) {{
        tr.classList.remove("is-selected");
        selected = null;
        return;
      }}

      if (selected) selected.classList.remove("is-selected");
      tr.classList.add("is-selected");
      selected = tr;
    }});
  }});
}})();
</script>

<script>
(function(){{
  const timers = new WeakMap();

  function clearTimer(input){{
    if (timers.has(input)) {{
      clearTimeout(timers.get(input));
      timers.delete(input);
    }}
  }}

  function submitLater(input, delay){{
    const formId = input.getAttribute("form");
    if (!formId) return;
    const form = document.getElementById(formId);
    if (!form) return;

    clearTimer(input);

    const t = setTimeout(function(){{
      if (!document.body.contains(input)) return;
      if (document.activeElement === input) return;
      form.submit();
    }}, delay);

    timers.set(input, t);
  }}

  document.querySelectorAll('.payrollTimeInput[data-autosave="1"]').forEach(function(input){{
    input.addEventListener("focus", function(){{
      clearTimer(input);
    }});

    input.addEventListener("input", function(){{
      clearTimer(input);
    }});

    input.addEventListener("change", function(){{
      clearTimer(input);
    }});

    input.addEventListener("keydown", function(e){{
      if (e.key === "Enter") {{
        e.preventDefault();
        submitLater(input, 80);
      }}
    }});

    input.addEventListener("blur", function(){{
      const v = (input.value || "").trim();
      if (v === "" || v.length >= 4) {{
        submitLater(input, 120);
      }}
    }});
  }});
}})();
</script>

<script>
(function(){{
  const shell = document.querySelector(".shell.payrollShell");
  const btn = document.getElementById("payrollMenuToggle");
  const backdrop = document.getElementById("payrollMenuBackdrop");

  if (!shell || !btn) return;

  function closeMenu(){{
    shell.classList.remove("payrollMenuOpen");
  }}

  btn.addEventListener("click", function(e){{
    e.preventDefault();
    e.stopPropagation();
    shell.classList.toggle("payrollMenuOpen");
  }});

  if (backdrop) {{
    backdrop.addEventListener("click", closeMenu);
  }}

  document.addEventListener("keydown", function(e){{
    if (e.key === "Escape") closeMenu();
  }});
}})();
</script>
    """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell(
            active="admin",
            role=session.get("role", "admin"),
            content_html=content,
            shell_class="payrollShell"
        )
    )


def _get_week_range(wk_offset: int):
    """
    Returns (week_start_str, week_end_str) for a Monday->Sunday week,
    offset by wk_offset weeks (0=this week, 1=previous week, etc).
    """
    today = datetime.now(TZ).date()
    monday = today - timedelta(days=today.weekday())  # Monday
    week_start = monday - timedelta(days=7 * int(wk_offset))
    week_end = week_start + timedelta(days=6)  # Sunday
    return week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d")


@app.get("/admin/payroll-report.csv")
def admin_payroll_report_csv():
    gate = require_admin()
    if gate:
        return gate

    username_q = (request.args.get("q") or "").strip().lower()
    date_from = (request.args.get("from") or "").strip()
    date_to = (request.args.get("to") or "").strip()

    try:
        wk_offset = int((request.args.get("wk") or "0").strip())
    except Exception:
        wk_offset = 0

    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    wp = _session_workplace_id()

    allowed_wps = set(_workplace_ids_for_read(wp))
    allowed_wps = set(_workplace_ids_for_read(wp))
    week_start, week_end = _get_week_range(wk_offset)

    use_range = False
    range_start = range_end = None

    if date_from and date_to:
        try:
            range_start = date.fromisoformat(date_from)
            range_end = date.fromisoformat(date_to)
            use_range = True
            week_start, week_end = date_from, date_to
        except ValueError:
            use_range = False

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    employee_records = []
    try:
        employee_records = _list_employee_records_for_workplace(include_inactive=True)
    except Exception:
        employee_records = []
    current_usernames = {
        (rec.get("Username") or "").strip()
        for rec in employee_records
        if (rec.get("Username") or "").strip()
    }

    totals_by_user = {}

    for r in rows[1:]:
        if len(r) <= COL_PAY or len(r) <= COL_USER or len(r) <= COL_DATE:
            continue

        user = (r[COL_USER] or "").strip()
        d_str = (r[COL_DATE] or "").strip()

        if not user or not d_str or user not in current_usernames:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(user):
                continue

        if username_q and username_q not in user.lower() and username_q not in get_employee_display_name(user).lower():
            continue

        try:
            d_obj = date.fromisoformat(d_str)
        except Exception:
            continue

        if use_range:
            if d_obj < range_start or d_obj > range_end:
                continue
        else:
            if d_str < str(week_start)[:10] or d_str > str(week_end)[:10]:
                continue

        hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        gross = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        totals_by_user.setdefault(user, {"hours": 0.0, "gross": 0.0})
        totals_by_user[user]["hours"] += hrs
        totals_by_user[user]["gross"] += gross

    export_rows = []
    for user, vals in totals_by_user.items():
        gross = round(vals["gross"], 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)
        hours = round(vals["hours"], 2)

        export_rows.append({
            "Employee": get_employee_display_name(user),
            "Username": user,
            "Hours": f"{hours:.2f}",
            "Gross": f"{gross:.2f}",
            "Tax": f"{tax:.2f}",
            "Net": f"{net:.2f}",
        })

    export_rows.sort(key=lambda x: (x.get("Employee") or "").lower())

    import csv
    from io import StringIO

    output = StringIO()
    output.write("sep=,\r\n")
    w = csv.writer(output)
    w.writerow(["WeekStart", "WeekEnd", "Employee", "Hours", "Gross", "Tax", "Net"])

    for r in export_rows:
        w.writerow([
            str(week_start),
            str(week_end),
            r["Employee"],
            r["Hours"],
            r["Gross"],
            r["Tax"],
            r["Net"],
        ])

    buf = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    buf.seek(0)

    filename = f"payroll_{week_start}_to_{week_end}.csv"

    return send_file(
        buf,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
        max_age=0
    )


# ---------- ADMIN ONBOARDING LIST / DETAIL ----------
@app.get("/admin/onboarding")
def admin_onboarding_list():
    gate = require_admin()
    if gate:
        return gate

    q = (request.args.get("q", "") or "").strip().lower()
    vals = onboarding_sheet.get_all_values() if not DB_MIGRATION_MODE else [
                                                                               ["Username", "FirstName", "LastName",
                                                                                "SubmittedAt", "Workplace_ID"]
                                                                           ] + [
                                                                               [
                                                                                   str(getattr(rec, "username",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "first_name",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "last_name",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "submitted_at",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "workplace_id",
                                                                                               "default") or "default").strip(),
                                                                               ]
                                                                               for rec in OnboardingRecord.query.all()
                                                                           ]
    if not vals:
        body = "<tr><td colspan='4'>No onboarding data.</td></tr>"
    else:
        headers = vals[0]

        def idx(name):
            return headers.index(name) if name in headers else None

        i_user = idx("Username")
        i_fn = idx("FirstName")
        i_ln = idx("LastName")
        i_sub = idx("SubmittedAt")
        i_wp = idx("Workplace_ID")
        current_wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(current_wp))

        rows_html = []
        for r in vals[1:]:
            u = r[i_user] if i_user is not None and i_user < len(r) else ""
            if not u:
                continue
            # Tenant-safe: filter by Onboarding row Workplace_ID (if column exists)
            if i_wp is not None:
                row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                if row_wp not in allowed_wps:
                    continue
            else:
                # Backward compat if Onboarding has no Workplace_ID column
                if not user_in_same_workplace(u):
                    continue
            fn = r[i_fn] if i_fn is not None and i_fn < len(r) else ""
            ln = r[i_ln] if i_ln is not None and i_ln < len(r) else ""
            sub = r[i_sub] if i_sub is not None and i_sub < len(r) else ""
            name = (fn + " " + ln).strip() or u
            if q and (q not in u.lower() and q not in name.lower()):
                continue
            rows_html.append(
                f"<tr>"
                f"<td><a href='/admin/onboarding/{escape(u)}' style='color:var(--navy);font-weight:600;'>{escape(name)}</a></td>"
                f"<td>{escape(u)}</td>"
                f"<td>{escape(sub)}</td>"
                f"<td style='text-align:center; white-space:nowrap;'><a href='/admin/onboarding/{escape(u)}/download' target='_blank' rel='noopener' style='display:inline-block; text-decoration:none; font-size:12px; font-weight:700; color:#6d28d9; line-height:1;'>PDF</a></td>"
                f"<a href='/admin/onboarding/{escape(u)}/download' target='_blank' rel='noopener' "
                f"style='display:inline; margin:0; padding:0; border:0; background:none; box-shadow:none; text-decoration:none; font-size:12px; font-weight:700; color:#6d28d9; line-height:1;'>PDF</a>"
                f"</td>"
                f"</tr>"
            )
        body = "".join(rows_html) if rows_html else "<tr><td colspan='4'>No matches.</td></tr>"

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Onboarding</h1>
          <p class="sub">Click a name to view details</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {admin_back_link()}

      <div class="card" style="padding:12px;">
        <form method="GET">
          <label class="sub">Search</label>
          <div class="row2">
            <input class="input" name="q" value="{escape(q)}" placeholder="name or username">
            <button class="btnSoft" type="submit" style="margin-top:8px;">Search</button>
          </div>
        </form>

        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width: 720px;">
            <thead><tr><th>Name</th><th>Username</th><th>Last saved</th><th style="text-align:center; width:70px;">PDF</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </div>
    """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )


@app.get("/admin/onboarding/<username>")
def admin_onboarding_detail(username):
    gate = require_admin()
    if gate:
        return gate
    rec = get_onboarding_record(username)
    if not rec:
        abort(404)
    # Tenant-safe: ensure the record is for the current workplace (if field exists)
    rec_wp = (rec.get("Workplace_ID") or "").strip() or "default"
    if rec_wp != _session_workplace_id():
        abort(404)

    def row(label, key, link=False):
        v_ = rec.get(key, "")
        vv = linkify(v_) if link else escape(v_)
        return f"<tr><th style='width:260px;'>{escape(label)}</th><td>{vv}</td></tr>"

    details = ""
    for label, key in [
        ("Username", "Username"), ("First name", "FirstName"), ("Last name", "LastName"),
        ("Birth date", "BirthDate"), ("Phone CC", "PhoneCountryCode"), ("Phone", "PhoneNumber"),
        ("Email", "Email"), ("Street", "StreetAddress"), ("City", "City"), ("Postcode", "Postcode"),
        ("Emergency contact", "EmergencyContactName"), ("Emergency CC", "EmergencyContactPhoneCountryCode"),
        ("Emergency phone", "EmergencyContactPhoneNumber"),
        ("Medical", "MedicalCondition"), ("Medical details", "MedicalDetails"),
        ("Position", "Position"), ("CSCS number", "CSCSNumber"), ("CSCS expiry", "CSCSExpiryDate"),
        ("Employment type", "EmploymentType"), ("Right to work UK", "RightToWorkUK"),
        ("NI", "NationalInsurance"), ("UTR", "UTR"), ("Start date", "StartDate"),
        ("Bank account", "BankAccountNumber"), ("Sort code", "SortCode"), ("Account holder", "AccountHolderName"),
        ("Company trading", "CompanyTradingName"), ("Company reg", "CompanyRegistrationNo"),
        ("Date of contract", "DateOfContract"), ("Site address", "SiteAddress"),
    ]:
        details += row(label, key)

    details += row("Passport/Birth cert", "PassportOrBirthCertLink", link=True)
    details += row("CSCS front/back", "CSCSFrontBackLink", link=True)
    details += row("Public liability", "PublicLiabilityLink", link=True)
    details += row("Share code", "ShareCodeLink", link=True)
    details += row("Contract accepted", "ContractAccepted")
    details += row("Signature name", "SignatureName")
    details += row("Signature time", "SignatureDateTime")
    details += row("Last saved", "SubmittedAt")

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Onboarding Details</h1>
          <p class="sub">{escape(username)}</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {admin_back_link()}

      <div class="card" style="padding:12px;">
        <div class="actionRow" style="margin-bottom:12px; grid-template-columns:1fr auto;">
  <div class="sub">Share or save this form as PDF even if no images were uploaded.</div>
  <a href="/admin/onboarding/{escape(username)}/download" target="_blank" rel="noopener" style="text-decoration:none; font-size:12px; font-weight:700; color:#6d28d9; white-space:nowrap;">PDF</a>
</div>

        <div class="tablewrap">
          <table style="min-width: 720px;"><tbody>{details}</tbody></table>
        </div>
      </div>
    """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )


@app.get("/admin/onboarding/<username>/download")
def admin_onboarding_download(username):
    gate = require_admin()
    if gate:
        return gate

    rec = get_onboarding_record(username)
    if not rec:
        abort(404)

    rec_wp = (rec.get("Workplace_ID") or "").strip() or "default"
    if rec_wp != _session_workplace_id():
        abort(404)

    settings = get_company_settings()
    company_name = str(settings.get("Company_Name", "WorkHours") or "WorkHours")
    currency = str(settings.get("Currency_Symbol", "£") or "£")

    display_name = (
            ((rec.get("FirstName") or "").strip() + " " + (rec.get("LastName") or "").strip()).strip()
            or (rec.get("Username") or "").strip()
            or username
    )

    def show(key):
        return escape((rec.get(key, "") or "").strip() or "—")

    def doc_status(label, key):
        link = (rec.get(key, "") or "").strip()
        if link:
            return f"<tr><th>{escape(label)}</th><td>Uploaded</td></tr>"
        return f"<tr><th>{escape(label)}</th><td>Not uploaded</td></tr>"

    personal_rows = "".join([
        f"<tr><th>First name</th><td>{show('FirstName')}</td></tr>",
        f"<tr><th>Last name</th><td>{show('LastName')}</td></tr>",
        f"<tr><th>Birth date</th><td>{show('BirthDate')}</td></tr>",
        f"<tr><th>Phone</th><td>{show('PhoneCountryCode')} {show('PhoneNumber')}</td></tr>",
        f"<tr><th>Email</th><td>{show('Email')}</td></tr>",
        f"<tr><th>Street</th><td>{show('StreetAddress')}</td></tr>",
        f"<tr><th>City</th><td>{show('City')}</td></tr>",
        f"<tr><th>Postcode</th><td>{show('Postcode')}</td></tr>",
    ])

    work_rows = "".join([
        f"<tr><th>Emergency contact</th><td>{show('EmergencyContactName')}</td></tr>",
        f"<tr><th>Emergency phone</th><td>{show('EmergencyContactPhoneCountryCode')} {show('EmergencyContactPhoneNumber')}</td></tr>",
        f"<tr><th>Medical condition</th><td>{show('MedicalCondition')}</td></tr>",
        f"<tr><th>Medical details</th><td>{show('MedicalDetails')}</td></tr>",
        f"<tr><th>Position</th><td>{show('Position')}</td></tr>",
        f"<tr><th>CSCS number</th><td>{show('CSCSNumber')}</td></tr>",
        f"<tr><th>CSCS expiry</th><td>{show('CSCSExpiryDate')}</td></tr>",
        f"<tr><th>Employment type</th><td>{show('EmploymentType')}</td></tr>",
        f"<tr><th>Right to work UK</th><td>{show('RightToWorkUK')}</td></tr>",
        f"<tr><th>NI</th><td>{show('NationalInsurance')}</td></tr>",
        f"<tr><th>UTR</th><td>{show('UTR')}</td></tr>",
        f"<tr><th>Start date</th><td>{show('StartDate')}</td></tr>",
    ])

    company_rows = "".join([
        f"<tr><th>Bank account</th><td>{show('BankAccountNumber')}</td></tr>",
        f"<tr><th>Sort code</th><td>{show('SortCode')}</td></tr>",
        f"<tr><th>Account holder</th><td>{show('AccountHolderName')}</td></tr>",
        f"<tr><th>Company trading</th><td>{show('CompanyTradingName')}</td></tr>",
        f"<tr><th>Company reg no</th><td>{show('CompanyRegistrationNo')}</td></tr>",
        f"<tr><th>Date of contract</th><td>{show('DateOfContract')}</td></tr>",
        f"<tr><th>Site address</th><td>{show('SiteAddress')}</td></tr>",
        f"<tr><th>Contract accepted</th><td>{show('ContractAccepted')}</td></tr>",
        f"<tr><th>Signature name</th><td>{show('SignatureName')}</td></tr>",
        f"<tr><th>Signature time</th><td>{show('SignatureDateTime')}</td></tr>",
        f"<tr><th>Last saved</th><td>{show('SubmittedAt')}</td></tr>",
    ])

    doc_rows = "".join([
        doc_status("Passport / Birth cert", "PassportOrBirthCertLink"),
        doc_status("CSCS front / back", "CSCSFrontBackLink"),
        doc_status("Public liability", "PublicLiabilityLink"),
        doc_status("Share code", "ShareCodeLink"),
    ])

    page = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Onboarding Form - {escape(display_name)}</title>
      <style>
        body {{
          margin: 0;
          background: #f5f6fb;
          color: #1f2547;
          font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}

        .printWrap {{
          max-width: 980px;
          margin: 24px auto;
          padding: 0 16px;
        }}

        .toolbar {{
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          margin-bottom: 14px;
        }}

        .btn {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 44px;
          padding: 0 16px;
          border-radius: 14px;
          text-decoration: none;
          font-weight: 800;
          border: 1px solid rgba(109,40,217,.12);
          background: #fff;
          color: #4338ca;
          box-shadow: 0 8px 18px rgba(41,25,86,.06);
        }}

        .btnPrimary {{
          color: #fff;
          border: 0;
          background: linear-gradient(90deg, #6d28d9, #2563eb);
          box-shadow: 0 12px 24px rgba(79,70,229,.20);
        }}

        .sheet {{
          background: #fff;
          border: 1px solid #e7e8f0;
          box-shadow: 0 20px 40px rgba(15,23,42,.08);
        }}

        .sheetHead {{
          padding: 22px 24px 14px;
          border-bottom: 1px solid #ececf4;
        }}

        .sheetTop {{
          display: grid;
          grid-template-columns: 1.2fr 1fr;
          gap: 18px;
          align-items: start;
        }}

        .eyebrow {{
          display: inline-flex;
          align-items: center;
          padding: 8px 12px;
          border-radius: 999px;
          border: 1px solid rgba(109,40,217,.12);
          background: rgba(109,40,217,.06);
          color: #6d28d9;
          font-size: 12px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: .05em;
        }}

        .sheetTitle {{
          margin: 14px 0 8px;
          font-size: 34px;
          line-height: 1.02;
          letter-spacing: -.03em;
          font-weight: 900;
          color: #111827;
        }}

        .sheetSub {{
          color: #6f6c85;
          font-size: 14px;
          line-height: 1.6;
        }}

        .meta {{
          text-align: right;
          font-size: 12px;
          line-height: 1.7;
          color: #6b7280;
        }}

        .meta strong {{
          color: #111827;
        }}

        .section {{
          padding: 16px 24px 0;
        }}

        .sectionTitle {{
          margin: 0 0 10px 0;
          color: #6d28d9;
          font-size: 12px;
          font-weight: 900;
          letter-spacing: .07em;
          text-transform: uppercase;
        }}

        table {{
          width: 100%;
          border-collapse: collapse;
          table-layout: fixed;
          background: #fff;
          border: 1px solid #e7e8f0;
        }}

        th, td {{
          border-bottom: 1px solid #edf0f5;
          padding: 10px 12px;
          text-align: left;
          vertical-align: top;
          font-size: 13px;
        }}

        th {{
          width: 240px;
          color: #4b5563;
          background: #f7f8fc;
          font-weight: 800;
        }}

        td {{
          color: #111827;
          word-break: break-word;
        }}

        .bottomSpace {{
          height: 18px;
        }}

        .bar {{
          height: 12px;
          background: linear-gradient(90deg, #7c3aed 0%, #6d28d9 40%, #2563eb 100%);
        }}

        @media (max-width: 760px) {{
          .sheetTop {{
            grid-template-columns: 1fr;
          }}
          .meta {{
            text-align: left;
          }}
          th {{
            width: 42%;
          }}
        }}

        @media print {{
          body {{
            background: #fff;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }}
          .toolbar {{
            display: none !important;
          }}
          .printWrap {{
            max-width: none;
            margin: 0;
            padding: 0;
          }}
          .sheet {{
            box-shadow: none;
            border: none;
          }}
        }}
      </style>
    </head>
    <body>
      <div class="printWrap">
        <div class="toolbar">
          {page_back_button(f"/admin/onboarding/{escape(username)}", "Back to details")}
          <button class="btn btnPrimary" onclick="window.print()">Save / Print Form</button>
        </div>

        <div class="sheet">
          <div class="sheetHead">
            <div class="sheetTop">
              <div>
                <div class="eyebrow">Onboarding Form</div>
                <div class="sheetTitle">{escape(display_name)}</div>
                <div class="sheetSub">{escape(company_name)}<br>Starter form / onboarding record</div>
              </div>
              <div class="meta">
                <div><strong>Workplace:</strong> {escape(rec_wp)}</div>
                <div><strong>Generated:</strong> {escape(datetime.now(TZ).strftime("%d/%m/%Y %H:%M"))}</div>
                <div><strong>Last saved:</strong> {show('SubmittedAt')}</div>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="sectionTitle">Personal details</div>
            <table><tbody>{personal_rows}</tbody></table>
          </div>

          <div class="section">
            <div class="sectionTitle">Employment & emergency details</div>
            <table><tbody>{work_rows}</tbody></table>
          </div>

          <div class="section">
            <div class="sectionTitle">Company / contract details</div>
            <table><tbody>{company_rows}</tbody></table>
          </div>

          <div class="section">
            <div class="sectionTitle">Uploaded documents</div>
            <table><tbody>{doc_rows}</tbody></table>
          </div>

          <div class="bottomSpace"></div>
          <div class="bar"></div>
        </div>
      </div>
    </body>
    </html>
    """
    return render_template_string(page)


# ---------- ADMIN LOCATIONS (Geofencing) ----------
@app.get("/admin/locations")
def admin_locations():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    _ensure_locations_headers()

    all_rows = []
    try:
        current_wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(current_wp))

        records = Location.query.all() if DB_MIGRATION_MODE else (get_locations() or [])
        for rec in records:
            if isinstance(rec, dict):
                row_wp = (rec.get("Workplace_ID") or rec.get("workplace_id") or "default").strip()
                if row_wp not in allowed_wps:
                    continue

                name = str(rec.get("SiteName") or rec.get("site_name") or rec.get("Site") or "").strip()
                lat = str(rec.get("Lat") or rec.get("lat") or "").strip()
                lon = str(rec.get("Lon") or rec.get("lon") or "").strip()
                rad = str(rec.get("RadiusMeters") or rec.get("radius_meters") or rec.get("Radius") or "").strip()
                act = str(rec.get("Active") or rec.get("active") or "TRUE").strip()
            else:
                row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip()
                if row_wp not in allowed_wps:
                    continue

                name = str(getattr(rec, "site_name", "") or "").strip()
                lat = str(getattr(rec, "lat", "") or "").strip()
                lon = str(getattr(rec, "lon", "") or "").strip()
                rad = str(getattr(rec, "radius_meters", "") or "").strip()
                act = str(getattr(rec, "active", "TRUE") or "TRUE").strip()

            if name:
                all_rows.append({
                    "name": name,
                    "lat": lat,
                    "lon": lon,
                    "rad": rad,
                    "act": act
                })
    except Exception:
        all_rows = []

    def _is_active(v):
        return str(v or "").strip().lower() not in ("false", "0", "no", "n", "off")

    def row_html(s):
        act_on = _is_active(s.get("act", "TRUE"))
        badge = "<span class='chip ok'>Active</span>" if act_on else "<span class='chip warn'>Inactive</span>"
        return f"""
          <tr>
            <td><b>{escape(s.get('name', ''))}</b><div class='sub' style='margin:2px 0 0 0;'>{badge}<div class='sub' style='margin:6px 0 0 0;'><a href='/admin/locations?site={escape(s.get('name', ''))}' style='color:var(--navy);font-weight:600;'>View map</a></div></td>
            <td class='num'>{escape(s.get('lat', ''))}</td>
            <td class='num'>{escape(s.get('lon', ''))}</td>
            <td class='num'>{escape(s.get('rad', ''))}</td>
            <td style='min-width:340px;'>
              <form method="POST" action="/admin/locations/save" style="margin:0; display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                <input type="hidden" name="csrf" value="{escape(csrf)}">
                <input type="hidden" name="orig_name" value="{escape(s.get('name', ''))}">
                <input class="input" name="name" value="{escape(s.get('name', ''))}" placeholder="Site name" style="margin-top:0; max-width:160px; color:#f8fafc; -webkit-text-fill-color:#f8fafc; caret-color:#f8fafc;">
                <input class="input" name="lat" value="{escape(s.get('lat', ''))}" placeholder="Lat" style="margin-top:0; max-width:120px; color:#f8fafc; -webkit-text-fill-color:#f8fafc; caret-color:#f8fafc;">
                <input class="input" name="lon" value="{escape(s.get('lon', ''))}" placeholder="Lon" style="margin-top:0; max-width:120px; color:#f8fafc; -webkit-text-fill-color:#f8fafc; caret-color:#f8fafc;">
                <input class="input" name="rad" value="{escape(s.get('rad', ''))}" placeholder="Radius m" style="margin-top:0; max-width:110px; color:#f8fafc; -webkit-text-fill-color:#f8fafc; caret-color:#f8fafc;">
                <label class="sub" style="display:flex; align-items:center; gap:8px; margin:0;">
                  <input type="checkbox" name="active" value="yes" {"checked" if act_on else ""}>
                  Active
                </label>
                <button class="btnTiny" type="submit">Save</button>
              </form>
              <form method="POST" action="/admin/locations/deactivate" style="margin-top:8px;">
                <input type="hidden" name="csrf" value="{escape(csrf)}">
                <input type="hidden" name="name" value="{escape(s.get('name', ''))}">
                <button class="btnTiny dark" type="submit">Deactivate</button>
              </form>
            </td>
          </tr>
        """

    table_body = "".join(
        [row_html(r) for r in all_rows]) if all_rows else "<tr><td colspan='5'>No locations yet.</td></tr>"

    # Map preview (no API key): OpenStreetMap embed for selected site
    selected = (request.args.get("site") or "").strip()
    chosen = None
    for rr in all_rows:
        if selected and rr.get("name", "").strip().lower() == selected.lower():
            chosen = rr
            break
    if not chosen and all_rows:
        chosen = all_rows[0]

    map_card = ""
    if chosen:
        try:
            latf = float((chosen.get("lat") or "0").strip())
            lonf = float((chosen.get("lon") or "0").strip())
            delta = 0.006
            left = lonf - delta
            right = lonf + delta
            top = latf + delta
            bottom = latf - delta
            # OSM embed URL
            osm = f"https://www.openstreetmap.org/export/embed.html?bbox={left}%2C{bottom}%2C{right}%2C{top}&layer=mapnik&marker={latf}%2C{lonf}"
            map_card = f"""
              <div class="card" style="padding:12px; margin-top:12px;">
                <h2>Map preview</h2>
                <div class="sub" style="margin-top:6px;">{escape(chosen.get('name', ''))} • {escape(chosen.get('lat', ''))}, {escape(chosen.get('lon', ''))}</div>
                <div style="margin-top:12px; border-radius:18px; overflow:hidden; border:1px solid rgba(11,18,32,.10);">
                  <iframe title="map" src="{osm}" style="width:100%; height:320px; border:0;" loading="lazy"></iframe>
                </div>
                <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
                  <a href="https://www.google.com/maps?q={latf},{lonf}" target="_blank" rel="noopener noreferrer" style="color:var(--navy); font-weight:600;">Open in Google Maps</a>
                  <a href="https://www.openstreetmap.org/?mlat={latf}&mlon={lonf}#map=18/{latf}/{lonf}" target="_blank" rel="noopener noreferrer" style="color:var(--navy); font-weight:600;">Open in OSM</a>
                </div>
              </div>
            """
        except Exception:
            map_card = ""

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Locations</h1>
          <p class="sub">Clock in/out will only work inside an allowed location radius.</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {admin_back_link()}

      {map_card}

      <div class="card" style="padding:12px;">
        <h2>Add location</h2>
        <form method="POST" action="/admin/locations/save">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <input type="hidden" name="orig_name" value="">
          <div class="row2">
            <div>
              <label class="sub">Site name</label>
              <input class="input" name="name" placeholder="e.g. Site A" required>
            </div>
            <div>
              <label class="sub">Radius (meters)</label>
              <input class="input" name="rad" placeholder="e.g. 150" required>
            </div>
          </div>
          <div class="row2">
            <div>
              <label class="sub">Latitude</label>
              <input class="input" name="lat" placeholder="e.g. 51.5074" required>
            </div>
            <div>
              <label class="sub">Longitude</label>
              <input class="input" name="lon" placeholder="e.g. -0.1278" required>
            </div>
          </div>
          <label class="sub" style="display:flex; align-items:center; gap:8px; margin-top:10px;">
            <input type="checkbox" name="active" value="yes" checked> Active
          </label>
          <button class="btnSoft" type="submit" style="margin-top:12px;">Add</button>
        </form>
      </div>

      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>All locations</h2>
        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:980px;">
            <thead><tr><th>Site</th><th class="num">Lat</th><th class="num">Lon</th><th class="num">Radius (m)</th><th>Manage</th></tr></thead>
            <tbody>{table_body}</tbody>
          </table>
        </div>
        <p class="sub" style="margin-top:10px;">
          Tip: Use your phone’s Google Maps to read the site latitude/longitude (drop a pin → share → coordinates).
        </p>
      </div>
    """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )


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

            # If Workplace_ID exists, require it to match current workplace
            if wp_idx is not None:
                row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

            return i + 1
    except Exception:
        return None
    return None


@app.post("/admin/locations/save")
def admin_locations_save():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    name = (request.form.get("name") or "").strip()
    orig = (request.form.get("orig_name") or "").strip()
    lat = (request.form.get("lat") or "").strip()
    lon = (request.form.get("lon") or "").strip()
    rad = (request.form.get("rad") or "").strip()
    active = "TRUE" if (request.form.get("active") == "yes") else "FALSE"

    if not locations_sheet or not name:
        return redirect("/admin/locations")

    try:
        float(lat);
        float(lon);
        float(rad)
    except Exception:
        return redirect("/admin/locations")

    _ensure_locations_headers()

    rownum = _find_location_row_by_name(orig or name)
    row = [name, lat, lon, rad, active, _session_workplace_id()]
    try:
        if rownum:
            locations_sheet.update(f"A{rownum}:F{rownum}", [row])
        else:
            locations_sheet.append_row(row)
    except Exception:
        pass

    if DB_MIGRATION_MODE:
        try:
            wp = _session_workplace_id()
            allowed_wps = set(_workplace_ids_for_read(wp))

            db_row = Location.query.filter_by(
                workplace_id=wp,
                site_name=(orig or name)
            ).first()

            if not db_row:
                db_row = Location.query.filter_by(
                    workplace_id=wp,
                    site_name=name
                ).first()

            if db_row:
                db_row.site_name = name
                db_row.lat = float(lat)
                db_row.lon = float(lon)
                db_row.radius_meters = int(float(rad))
                db_row.active = active
            else:
                db.session.add(
                    Location(
                        site_name=name,
                        lat=float(lat),
                        lon=float(lon),
                        radius_meters=int(float(rad)),
                        active=active,
                        workplace_id=wp,
                    )
                )

            db.session.commit()
        except Exception:
            db.session.rollback()

    actor = session.get("username", "admin")
    log_audit("LOCATIONS_SAVE", actor=actor, username="", date_str="",
              details=f"{name} {lat},{lon} r={rad} active={active}")
    return redirect("/admin/locations")


@app.post("/admin/locations/deactivate")
def admin_locations_deactivate():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    name = (request.form.get("name") or "").strip()
    if not locations_sheet or not name:
        return redirect("/admin/locations")

    rownum = _find_location_row_by_name(name)
    if rownum:
        try:
            locations_sheet.update_cell(rownum, 5, "FALSE")

            if DB_MIGRATION_MODE:
                try:
                    wp = _session_workplace_id()
                    allowed_wps = set(_workplace_ids_for_read(wp))
                    db_row = Location.query.filter_by(workplace_id=wp, site_name=name).first()
                    if db_row:
                        db_row.active = "FALSE"
                        db.session.commit()
                except Exception:
                    db.session.rollback()
        except Exception:
            pass

    actor = session.get("username", "admin")
    log_audit("LOCATIONS_DEACTIVATE", actor=actor, username="", date_str="", details=name)
    return redirect("/admin/locations")


# ---------- ADMIN: EMPLOYEE SITE ASSIGNMENTS ----------
@app.get("/admin/employee-sites")
def admin_employee_sites():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()

    sites = _get_active_locations()
    site_names = [s["name"] for s in sites] if sites else []

    rows_html = []
    employee_rows = get_employees_compat()

    def build_opts(current: str):
        opts = []
        cur = (current or "").strip()
        cur_l = cur.lower()

        if cur and (cur not in site_names):
            opts.append(f"<option value='{escape(cur)}' selected>{escape(cur)} (inactive/unknown)</option>")

        if not site_names:
            opts.append("<option value='' selected>(No active locations)</option>")
        else:
            opts.append("<option value=''>— None —</option>")
            for n in site_names:
                sel = "selected" if (n.strip().lower() == cur_l and cur) else ""
                opts.append(f"<option value='{escape(n)}' {sel}>{escape(n)}</option>")

        return "".join(opts)

    current_wp = _session_workplace_id()

    allowed_wps = set(_workplace_ids_for_read(current_wp))

    for user in employee_rows:
        u = (user.get("Username") or "").strip()
        if not u:
            continue

        row_wp = (user.get("Workplace_ID") or "default").strip() or "default"
        if row_wp not in allowed_wps:
            continue

        fn = (user.get("FirstName") or "").strip()
        ln = (user.get("LastName") or "").strip()
        raw_site = (user.get("Site") or "").strip()
        disp = (fn + " " + ln).strip() or u

        assigned = _get_employee_sites(u)
        s1 = assigned[0] if len(assigned) > 0 else ""
        s2 = assigned[1] if len(assigned) > 1 else ""

        chips = []
        if not assigned:
            chips.append("<span class='chip warn'>No site assigned (clock-in blocked)</span>")
        else:
            for s in assigned[:2]:
                if s and s in site_names:
                    chips.append(f"<span class='chip ok'>{escape(s)}</span>")
                elif s:
                    chips.append(f"<span class='chip bad'>{escape(s)}?</span>")

        rows_html.append(f"""
          <tr>
            <td>
              <div style='display:flex; align-items:center; gap:10px;'>
                <div class='avatar'>{escape(initials(disp))}</div>
                <div>
                  <div style='font-weight:600;'>{escape(disp)}</div>
                  <div class='sub' style='margin:2px 0 0 0;'>{escape(u)}</div>
                  <div style='margin-top:6px; display:flex; gap:6px; flex-wrap:wrap;'>{''.join(chips)}</div>
                </div>
              </div>
            </td>
            <td style='min-width:420px;'>
              <form method='POST' action='/admin/employee-sites/save' style='margin:0; display:flex; gap:8px; align-items:center; flex-wrap:wrap;'>
                <input type='hidden' name='csrf' value='{escape(csrf)}'>
                <input type='hidden' name='user' value='{escape(u)}'>
                <select class='input' name='site1' style='margin-top:0; max-width:200px;'>
                  {build_opts(s1)}
                </select>
                <select class='input' name='site2' style='margin-top:0; max-width:200px;'>
                  {build_opts(s2)}
                </select>
                <button class='btnTiny' type='submit'>Save</button>
              </form>
              <div class='sub' style='margin-top:6px;'>Tip: leaving both blank blocks employee clock-in until a site is assigned.</div>
            </td>
            <td class='sub'>{escape(raw_site) if raw_site else ''}</td>
          </tr>
        """)

    body = "".join(rows_html) if rows_html else "<tr><td colspan='3'>No employees found.</td></tr>"

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Employee Sites</h1>
          <p class="sub">Assign each employee to up to 2 sites (used for geo-fence clock in/out).</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {admin_back_link()}

      <div class="card" style="padding:12px;">
        <p class="sub" style="margin-top:0;">
          This updates the <b>Employees → Site</b> column. You can save <b>two sites</b>; they will be stored as <b>Site1,Site2</b>.
          If no site is set for an employee, clock-in is <b>blocked</b> until a site is assigned.
        </p>
        <a href="/admin/locations" style="display:inline-block; margin-top:8px;">
          <button class="btnSoft" type="button">Manage Locations</button>
        </a>
      </div>

      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>Employees</h2>
        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:980px;">
            <thead><tr><th>Employee</th><th>Assign site(s)</th><th>Raw</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </div>
    """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )


@app.post("/admin/employee-sites/save")
def admin_employee_sites_save():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    u = (request.form.get("user") or "").strip()
    s1 = (request.form.get("site1") or "").strip()
    s2 = (request.form.get("site2") or "").strip()

    if s1 and s2 and s1.strip().lower() == s2.strip().lower():
        s2 = ""

    site_val = f"{s1},{s2}" if (s1 and s2) else (s1 or s2 or "")

    if u:
        if not _find_employee_record(u):
            return redirect("/admin/employee-sites")

        try:
            headers = get_sheet_headers(employees_sheet)
            if headers and "Site" not in headers:
                headers2 = headers + ["Site"]
                end_col = gspread.utils.rowcol_to_a1(1, len(headers2)).replace("1", "")
                employees_sheet.update(f"A1:{end_col}1", [headers2])
        except Exception:
            pass

        try:
            set_employee_field(u, "Site", site_val)
        except Exception:
            pass

        if DB_MIGRATION_MODE:
            try:
                wp = _session_workplace_id()
                allowed_wps = set(_workplace_ids_for_read(wp))
                db_row = Employee.query.filter_by(username=u, workplace_id=wp).first()
                if not db_row:
                    db_row = Employee.query.filter_by(email=u, workplace_id=wp).first()
                if db_row:
                    db_row.site = site_val
                    db_row.workplace = wp
                    db_row.workplace_id = wp
                    db.session.commit()
            except Exception:
                db.session.rollback()

        actor = session.get("username", "admin")
        log_audit("EMPLOYEE_SITE_SET", actor=actor, username=u, date_str="", details=f"site={site_val}")

    return redirect("/admin/employee-sites")


@app.route("/admin/employees", methods=["GET", "POST"])
def admin_employees():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    msg = ""
    ok = False
    created = None

    if request.method == "POST":
        require_csrf()
        action = (request.form.get("action") or "create").strip().lower()

        if action == "update":
            edit_username = (request.form.get("edit_username") or "").strip()
            raw_edit_role = (request.form.get("edit_role") or "").strip()
            edit_role = raw_edit_role
            edit_rate_raw = (request.form.get("edit_rate") or "").strip()
            edit_early_access = (request.form.get("edit_early_access") or "").strip()
            actor_role = (session.get("role") or "employee").strip().lower()
            if raw_edit_role:
                sanitized_role = _sanitize_requested_role(raw_edit_role, actor_role)
                if not sanitized_role:
                    ok = False
                    msg = "You are not allowed to assign that role."
                else:
                    edit_role = sanitized_role

            if not edit_username:
                ok = False
                msg = "Enter a username to update."
            else:
                _ensure_employees_columns()
                headers = get_sheet_headers(employees_sheet)

                rownum = find_row_by_username(employees_sheet, edit_username)  # tenant-safe
                if not rownum and DB_MIGRATION_MODE:
                    new_rate_str = None
                    if edit_rate_raw != "":
                        try:
                            new_rate_str = str(float(edit_rate_raw))
                        except Exception:
                            ok = False
                            msg = "Hourly rate must be a number."

                    changed = []
                    if not msg:
                        try:
                            db_row = _employee_query_for_write(edit_username, _session_workplace_id()).first()
                            if not db_row:
                                ok = False
                                msg = "Employee not found in this workplace."
                            else:
                                if edit_role != "" and hasattr(db_row, "role"):
                                    db_row.role = edit_role
                                    changed.append(f"role={edit_role}")

                                if new_rate_str is not None and hasattr(db_row, "rate"):
                                    db_row.rate = Decimal(new_rate_str)
                                    changed.append(f"rate={new_rate_str}")

                                if edit_early_access in ("TRUE", "FALSE") and hasattr(db_row, "early_access"):
                                    db_row.early_access = edit_early_access
                                    changed.append(f"early_access={edit_early_access}")

                                if not changed:
                                    ok = False
                                    msg = "Nothing to update (enter a new role, rate, and/or early access change)."
                                else:
                                    db.session.commit()
                                    actor = session.get("username", "admin")
                                    log_audit("EMPLOYEE_UPDATE", actor=actor, username=edit_username, date_str="",
                                              details=" ".join(changed))
                                    ok = True
                                    msg = "Employee updated."
                        except Exception:
                            db.session.rollback()
                            ok = False
                            msg = "Could not update employee."
                elif not rownum:
                    ok = False
                    msg = "Employee not found in this workplace."
                else:
                    new_rate_str = None
                    if edit_rate_raw != "":
                        try:
                            new_rate_str = str(float(edit_rate_raw))
                        except Exception:
                            ok = False
                            msg = "Hourly rate must be a number."

                    if not msg:
                        existing = employees_sheet.row_values(rownum)
                        row = (existing + [""] * max(0, len(headers) - len(existing)))[:len(headers)]

                        changed = []

                        if edit_role != "" and "Role" in headers:
                            row[headers.index("Role")] = edit_role
                            changed.append(f"role={edit_role}")

                        if new_rate_str is not None and "Rate" in headers:
                            row[headers.index("Rate")] = new_rate_str
                            changed.append(f"rate={new_rate_str}")

                        if edit_early_access in ("TRUE", "FALSE") and "EarlyAccess" in headers:
                            row[headers.index("EarlyAccess")] = edit_early_access
                            changed.append(f"early_access={edit_early_access}")

                        if not changed:
                            ok = False
                            msg = "Nothing to update (enter a new role, rate, and/or early access change)."
                        else:
                            end_col = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
                            try:
                                employees_sheet.update(f"A{rownum}:{end_col}{rownum}", [row])
                                actor = session.get("username", "admin")
                                log_audit("EMPLOYEE_UPDATE", actor=actor, username=edit_username, date_str="",
                                          details=" ".join(changed))

                                if DB_MIGRATION_MODE:
                                    try:
                                        def _row_str(col_name, default=""):
                                            if headers and col_name in headers:
                                                idx = headers.index(col_name)
                                                if idx < len(row):
                                                    return str(row[idx] or "").strip()
                                            return default

                                        username_db = _row_str("Username", edit_username) or edit_username
                                        first_name_db = _row_str("FirstName")
                                        last_name_db = _row_str("LastName")
                                        full_name_db = (" ".join([first_name_db, last_name_db])).strip()
                                        role_db = _row_str("Role")
                                        password_db = _normalize_password_hash_value(_row_str("Password"))
                                        early_access_db = _row_str("EarlyAccess")
                                        active_db = _row_str("Active", "TRUE") or "TRUE"
                                        workplace_id_db = _row_str("Workplace_ID",
                                                                   _session_workplace_id()) or _session_workplace_id()
                                        site_db = _row_str("Site")

                                        rate_db = None
                                        rate_raw_db = _row_str("Rate")
                                        if rate_raw_db != "":
                                            try:
                                                rate_db = Decimal(rate_raw_db)
                                            except Exception:
                                                rate_db = None

                                        db_row = _employee_query_for_write(username_db, workplace_id_db).first()

                                        if db_row:
                                            db_row.email = username_db
                                            db_row.name = full_name_db or username_db
                                            db_row.role = role_db
                                            db_row.username = username_db
                                            db_row.first_name = first_name_db
                                            db_row.last_name = last_name_db
                                            db_row.password = password_db or db_row.password
                                            db_row.rate = rate_db
                                            db_row.early_access = early_access_db
                                            db_row.active = active_db
                                            if hasattr(db_row, "site"):
                                                db_row.site = site_db
                                        else:
                                            db.session.add(
                                                Employee(
                                                    email=username_db,
                                                    name=full_name_db or username_db,
                                                    role=role_db,
                                                    workplace=workplace_id_db,
                                                    created_at=None,
                                                    username=username_db,
                                                    first_name=first_name_db,
                                                    last_name=last_name_db,
                                                    password=password_db,
                                                    rate=rate_db,
                                                    early_access=early_access_db,
                                                    active=active_db,
                                                    workplace_id=workplace_id_db,
                                                    site=site_db,
                                                )
                                            )

                                        db.session.commit()
                                    except Exception:
                                        db.session.rollback()

                                ok = True
                                msg = "Employee updated."
                            except Exception:
                                ok = False
                                msg = "Could not update employee (sheet write failed)."

        elif action in ("deactivate", "reactivate"):
            edit_username = (request.form.get("edit_username") or "").strip()
            if not edit_username:
                ok = False
                msg = "Choose an employee."
            else:
                _ensure_employees_columns()
                headers = get_sheet_headers(employees_sheet)

                # Ensure Active column exists
                if headers and "Active" not in headers:
                    headers2 = headers + ["Active"]
                    end_col_h = gspread.utils.rowcol_to_a1(1, len(headers2)).replace("1", "")
                    employees_sheet.update(f"A1:{end_col_h}1", [headers2])
                    headers = headers2

                rownum = find_row_by_username(employees_sheet, edit_username)  # tenant-safe
                if not rownum and DB_MIGRATION_MODE:
                    val = "FALSE" if action == "deactivate" else "TRUE"
                    try:
                        db_row = _employee_query_for_write(edit_username, _session_workplace_id()).first()
                        if not db_row:
                            ok = False
                            msg = "Employee not found in this workplace."
                        else:
                            db_row.active = val
                            if action == "deactivate" and hasattr(db_row, "active_session_token"):
                                db_row.active_session_token = None
                            db.session.commit()
                            actor = session.get("username", "admin")
                            if action == "deactivate":
                                log_audit("EMPLOYEE_DEACTIVATE", actor=actor, username=edit_username, date_str="",
                                          details="active=FALSE")
                                msg = "Employee deactivated."
                            else:
                                log_audit("EMPLOYEE_REACTIVATE", actor=actor, username=edit_username, date_str="",
                                          details="active=TRUE")
                                msg = "Employee reactivated."
                            ok = True
                    except Exception:
                        db.session.rollback()
                        ok = False
                        msg = "Could not update employee."
                elif not rownum:
                    ok = False
                    msg = "Employee not found in this workplace."
                else:
                    existing = employees_sheet.row_values(rownum)
                    row = (existing + [""] * max(0, len(headers) - len(existing)))[:len(headers)]

                    val = "FALSE" if action == "deactivate" else "TRUE"
                    if "Active" in headers:
                        row[headers.index("Active")] = val

                    end_col = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
                    try:
                        employees_sheet.update(f"A{rownum}:{end_col}{rownum}", [row])
                        actor = session.get("username", "admin")
                        if action == "deactivate":
                            log_audit("EMPLOYEE_DEACTIVATE", actor=actor, username=edit_username, date_str="",
                                      details="active=FALSE")
                            msg = "Employee deactivated."
                        else:
                            log_audit("EMPLOYEE_REACTIVATE", actor=actor, username=edit_username, date_str="",
                                      details="active=TRUE")
                            msg = "Employee reactivated."

                        if DB_MIGRATION_MODE:
                            try:
                                db_row = _employee_query_for_write(edit_username, _session_workplace_id()).first()
                                if db_row:
                                    db_row.active = val
                                    if action == "deactivate" and hasattr(db_row, "active_session_token"):
                                        db_row.active_session_token = None
                                    db.session.commit()
                            except Exception:
                                db.session.rollback()

                        ok = True
                    except Exception:
                        ok = False
                        msg = "Could not update employee (sheet write failed)."

        elif action == "reset_password":
            if session.get("role") != "master_admin":
                ok = False
                msg = "Only master admin can reset passwords."
            else:
                packed_target = (request.form.get("reset_target") or "").strip()
                legacy_username = (request.form.get("reset_username") or "").strip()
                new_password = (request.form.get("new_password") or "").strip()

                target_wp = (_session_workplace_id() or "default").strip() or "default"
                reset_username = legacy_username
                if packed_target and "||" in packed_target:
                    target_wp, reset_username = packed_target.split("||", 1)
                    target_wp = (target_wp or "").strip() or "default"
                    reset_username = (reset_username or "").strip()

                if not reset_username:
                    ok = False
                    msg = "Choose a user to reset."
                elif len(new_password) < 8:
                    ok = False
                    msg = "New password must be at least 8 characters."
                else:
                    changed = update_employee_password(reset_username, new_password, workplace_id=target_wp)
                    if changed:
                        actor = session.get("username", "master_admin")
                        log_audit(
                            "EMPLOYEE_PASSWORD_RESET",
                            actor=actor,
                            username=reset_username,
                            date_str="",
                            details=f"manual reset workplace={target_wp}",
                        )
                        ok = True
                        msg = f"Password reset for {reset_username} ({target_wp})."
                    else:
                        ok = False
                        msg = "Could not reset password for that user."

        elif action == "create":
            first = (request.form.get("first") or "").strip()
            last = (request.form.get("last") or "").strip()
            actor_role = (session.get("role") or "employee").strip().lower()
            raw_role_new = (request.form.get("role") or "employee").strip() or "employee"
            role_new = _sanitize_requested_role(raw_role_new, actor_role)
            rate_raw = (request.form.get("rate") or "").strip()

            if not role_new:
                return make_response("You are not allowed to create a user with that role.", 403)

            try:
                rate_val = float(rate_raw) if rate_raw != "" else 0.0
            except Exception:
                rate_val = 0.0

            wp = _session_workplace_id()

            allowed_wps = set(_workplace_ids_for_read(wp))

            _ensure_employees_columns()
            headers = get_sheet_headers(employees_sheet)

            new_username = _generate_unique_username(first, last, wp)
            temp_pw = _generate_temp_password(10)
            hashed = generate_password_hash(temp_pw)

            row = [""] * (len(headers) if headers else 0)

            def set_col(col_name: str, value: str):
                if headers and col_name in headers:
                    row[headers.index(col_name)] = value

            set_col("Username", new_username)
            set_col("Password", hashed)
            set_col("Role", role_new)
            set_col("Rate", str(rate_val))
            set_col("EarlyAccess", "TRUE")
            set_col("OnboardingCompleted", "")
            set_col("FirstName", first)
            set_col("LastName", last)
            set_col("Workplace_ID", wp)

            try:
                employees_sheet.append_row(row)
                actor = session.get("username", "admin")
                log_audit("EMPLOYEE_CREATE", actor=actor, username=new_username, date_str="",
                          details=f"role={role_new} rate={rate_val}")

                if DB_MIGRATION_MODE:
                    try:
                        full_name = (" ".join([first, last])).strip()

                        db_row = Employee.query.filter_by(username=new_username, workplace_id=wp).first()
                        if not db_row:
                            db_row = Employee.query.filter_by(email=new_username, workplace_id=wp).first()

                        if db_row:
                            db_row.email = new_username
                            db_row.name = full_name or new_username
                            db_row.role = role_new
                            db_row.workplace = wp
                            db_row.username = new_username
                            db_row.first_name = first
                            db_row.last_name = last
                            db_row.password = hashed
                            db_row.rate = Decimal(str(rate_val))
                            db_row.early_access = "TRUE"
                            db_row.active = "TRUE"
                            db_row.workplace_id = wp
                            db_row.site = ""
                        else:
                            db.session.add(
                                Employee(
                                    email=new_username,
                                    name=full_name or new_username,
                                    role=role_new,
                                    workplace=wp,
                                    created_at=None,
                                    username=new_username,
                                    first_name=first,
                                    last_name=last,
                                    password=hashed,
                                    rate=Decimal(str(rate_val)),
                                    early_access="TRUE",
                                    active="TRUE",
                                    workplace_id=wp,
                                    site="",
                                )
                            )

                        db.session.commit()
                    except Exception:
                        db.session.rollback()

                ok = True
                msg = "Employee created."
                created = {"u": new_username, "p": temp_pw, "wp": wp}
            except Exception:
                ok = False
                msg = "Could not create employee (sheet write failed)."

        else:
            ok = False
            msg = "Unknown action."

    # List employees in this workplace
    wp = _session_workplace_id()
    rows_html = []
    try:
        table_records = _list_employee_records_for_workplace(wp, include_inactive=True)

        for rec in table_records:
            u = (rec.get("Username") or "").strip()
            if not u:
                continue

            fn = (rec.get("FirstName") or "").strip()
            ln = (rec.get("LastName") or "").strip()
            rr = (rec.get("Role") or "").strip()
            rate = str(rec.get("Rate") or "").strip()
            early = str(rec.get("EarlyAccess") or "").strip()
            active = str(rec.get("Active") or "TRUE").strip().lower()

            early_label = "Yes" if early in ("true", "1", "yes") else "No"
            inactive_tag = " (inactive)" if active in ("false", "0", "no", "n", "off") else ""
            disp = ((fn + " " + ln).strip() or u) + inactive_tag

            rows_html.append(
                f"<tr><td>{escape(disp)}</td><td>{escape(u)}</td><td>{escape(rr)}</td><td>{escape(early_label)}</td><td class='num'>{escape(rate)}</td></tr>"
            )
    except Exception:
        rows_html = []

    # Roles allowed for the logged-in actor
    actor_role_page = (session.get("role") or "employee").strip().lower()

    role_suggestions = set(_allowed_assignable_roles_for_actor(actor_role_page))

    try:
        for rec in get_employees_compat():
            row_wp = (rec.get("Workplace_ID") or "default").strip() or "default"
            if row_wp not in allowed_wps:
                continue

            rr = (rec.get("Role") or "").strip()
            if not rr:
                continue

            # Do not suggest master_admin in the create form
            if rr.lower() == "master_admin":
                continue

            # Normal admins should not get "admin" suggested
            if rr.lower() == "admin" and actor_role_page != "master_admin":
                continue

            role_suggestions.add(rr)
    except Exception:
        pass

    role_suggestions = sorted(role_suggestions, key=lambda x: x.lower())

    role_options_html = "".join(
        f"<option value='{escape(r)}'></option>"
        for r in role_suggestions
    )
    table = "".join(rows_html) if rows_html else "<tr><td colspan='4'>No employees found.</td></tr>"

    created_card = ""
    if created:
        created_card = f"""
        <div class="card" style="padding:12px; margin-top:12px;">
          <h2>Employee created</h2>
          <p class="sub">Give these login details to the employee (they can change password in Profile).</p>
          <div class="card" style="padding:12px; background:rgba(56,189,248,.18); border:1px solid rgba(56,189,248,.35); color:rgba(2,6,23,.95);">
            <div><b>Username:</b> {escape(created["u"])}</div>
            <div><b>Workplace ID:</b> {escape(created["wp"])}</div>
            <div><b>Temp password:</b> {escape(created["p"])}</div>
          </div>
        </div>
        """

    employee_options_html = "<option value='' selected disabled>Select employee</option>"
    delete_employee_options_html = "<option value='' selected disabled>Select employee</option>"
    try:
        wp_now = _session_workplace_id()
        allowed_wps_for_dropdown = set(_workplace_ids_for_read(wp_now))
        records = _list_employee_records_for_workplace(wp_now, include_inactive=True)
        seen_usernames = set()

        def _record_sort_key(rec):
            rec_wp = str(rec.get("Workplace_ID") or "default").strip() or "default"
            return (0 if rec_wp == wp_now else 1, str(rec.get("Username") or "").strip().lower())

        for rec in sorted(records, key=_record_sort_key):
            u = str(rec.get("Username") or "").strip()
            if not u or u in seen_usernames:
                continue

            r_wp = str(rec.get("Workplace_ID") or "default").strip() or "default"
            if r_wp not in allowed_wps_for_dropdown:
                continue

            a = str(rec.get("Active") or "TRUE").strip().lower()
            inactive_tag = " (inactive)" if a in ("false", "0", "no", "n", "off") else ""

            fn = str(rec.get("FirstName") or "").strip()
            ln = str(rec.get("LastName") or "").strip()
            disp = (fn + " " + ln).strip() or u

            role_raw = str(rec.get("Role") or "").strip().lower()
            label = f"{disp}{inactive_tag} ({u})"

            employee_options_html += f"<option value='{escape(u)}'>{escape(label)}</option>"
            seen_usernames.add(u)

            if role_raw != "master_admin":
                delete_employee_options_html += f"<option value='{escape(u)}'>{escape(label)}</option>"
    except Exception:
        pass

    reset_user = session.pop("_pwreset_user", "")
    session.pop("_pwreset_password", None)
    reset_msg = session.pop("_pwreset_msg", "")
    reset_ok = session.pop("_pwreset_ok", None)
    emp_msg = session.pop("_emp_msg", "")
    emp_ok = session.pop("_emp_ok", None)

    if reset_ok is not None:
        msg = reset_msg
        ok = bool(reset_ok)

    if emp_ok is not None:
        msg = emp_msg
        ok = bool(emp_ok)

    reset_card = ""
    if session.get("role") == "master_admin":
        reset_card = f"""
          <div class="card" style="padding:12px; margin-top:12px;">
            <h2>Reset Password</h2>
            <p class="sub">Master admin can reset passwords only for users in the current workplace.</p>

            <form method="POST" action="/admin/employees/reset-password" style="margin-top:12px;">
              <input type="hidden" name="csrf" value="{escape(csrf)}">

              <label class="sub">Username</label>
              <select class="input" name="username" required>
                {employee_options_html}
              </select>

              <label class="sub" style="margin-top:10px;">New password</label>
              <input class="input" type="password" name="new_password" minlength="8" required>

              <button class="btnSoft" type="submit" style="margin-top:12px;">Reset password</button>
            </form>
          </div>
       """
    reset_result_card = ""
    if reset_ok and reset_user:
        reset_result_card = f"""
          <div class="card" style="padding:12px; margin-top:12px; background:rgba(56,189,248,.12); border:1px solid rgba(56,189,248,.35);">
            <h2>Password Updated</h2>
            <p class="sub">Password was updated successfully for this user.</p>
            <div style="font-weight:700; margin-top:8px;">User: {escape(reset_user)}</div>
          </div>
        """
    danger_card = ""
    if session.get("role") == "master_admin":
        danger_card = f"""
      <div class="card" style="padding:12px; margin-top:12px; border:1px solid rgba(239,68,68,.25);">
        <h2>Clear / Delete Employee</h2>
        <p class="sub">Clear timesheet + payroll history, or delete the employee completely.</p>

        <form method="POST" action="/admin/employees/clear-history" style="margin-top:12px;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">

          <label class="sub">Employee</label>
          <select class="input" name="username" required>
            {employee_options_html}
          </select>

          <button class="btnSoft" type="submit" style="margin-top:12px;"
                  onclick="return confirm('Clear all clock and payroll history for this employee?');">
            Clear history
          </button>
        </form>

        <form method="POST" action="/admin/employees/delete" style="margin-top:12px;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">

          <label class="sub">Delete employee</label>
          <select class="input" name="username" required>
            {delete_employee_options_html}
          </select>

          <button class="btnSoft" type="submit" style="margin-top:12px; background:#7f1d1d; border-color:#7f1d1d;"
                  onclick="return confirm('Delete this employee completely? This cannot be undone.');">
            Delete account
          </button>
        </form>
      </div>
    """

    content = f"""

      <div class="headerTop">
        <div>
          <h1>Create Employee</h1>
          <p class="sub">Create a new employee login (auto username + temp password)</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {admin_back_link()}

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
{("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

{reset_result_card}
{danger_card}

      <div class="card" style="padding:12px;">
        <form method="POST">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <div class="row2">
            <div>
              <label class="sub">First name</label>
              <input class="input" name="first" placeholder="e.g. John" required>
            </div>
            <div>
              <label class="sub">Last name</label>
              <input class="input" name="last" placeholder="e.g. Smith" required>
            </div>
          </div>

          <div class="row2">
            <div>
              <label class="sub">Role</label>
<input class="input" name="role" list="role_list" value="employee">
<datalist id="role_list">
  {role_options_html}
</datalist>
            </div>
            <div>
              <label class="sub">Hourly rate</label>
              <input class="input" name="rate" placeholder="e.g. 25">
            </div>
          </div>

          <button class="btnSoft" type="submit" style="margin-top:12px;">Create</button>
        </form>
        <p class="sub" style="margin-top:10px;">Note: this creates the user inside Workplace_ID <b>{escape(wp)}</b>.</p>
      </div>

      {created_card}
      <div class="card" style="padding:12px; margin-top:12px;">
  <h2>Update Employee</h2>
  <p class="sub">Update role and/or hourly rate for an existing username in this workplace.</p>

  <form method="POST" style="margin-top:12px;">
    <input type="hidden" name="csrf" value="{escape(csrf)}">
   <div style="margin-top:12px; display:flex; gap:10px;">
  <button class="btnSoft" type="submit" name="action" value="update">Save changes</button>

  <button class="btnSoft" type="submit" name="action" value="deactivate"
          onclick="return confirm('Deactivate this employee?')">
    Deactivate
  </button>

  <button class="btnSoft" type="submit" name="action" value="reactivate"
          onclick="return confirm('Reactivate this employee?')">
    Reactivate
  </button>
</div>

    <label class="sub">Username</label>
    <select class="input" name="edit_username" required>
     {employee_options_html}
    </select>   

    <div class="row2" style="margin-top:10px;">
  <div>
    <label class="sub">New role (optional)</label>
    <input class="input" name="edit_role" list="role_list" placeholder="Leave blank to keep existing">
  </div>
  <div>
    <label class="sub">New hourly rate (optional)</label>
    <input class="input" name="edit_rate" placeholder="Leave blank to keep existing">
  </div>
</div>

<div style="margin-top:10px;">
  <label class="sub">Early Access</label>
  <select class="input" name="edit_early_access">
    <option value="">Keep current</option>
    <option value="TRUE">Enabled</option>
    <option value="FALSE">Disabled</option>
  </select>
</div>
  </form>
</div>
      {reset_card}
      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>Employees (this workplace)</h2>
        <div class="tablewrap" style="margin-top:12px;">
          <table class="employeesTable">
            <thead>
              <tr>
                <th>Name</th>
                <th>Username</th>
                <th>Role</th>
                <th>Early Access</th>
                <th class="num">Rate</th>
              </tr>
            </thead>
            <tbody>{table}</tbody>
          </table>
        </div>
      </div>
    """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )


# ================= LOCAL RUN =================


@app.route("/admin/workplaces", methods=["GET", "POST"])
def admin_workplaces():
    gate = require_master_admin()
    if gate:
        return gate

    csrf = get_csrf()
    msg = ""
    ok = False
    created_info = None

    if request.method == "POST":
        require_csrf()
        action = (request.form.get("action") or "").strip().lower()

        if action == "switch":
            target_wp = (request.form.get("target_workplace") or "").strip()

            found = False
            try:
                vals = settings_sheet.get_all_values() if settings_sheet else []
                headers = vals[0] if vals else []
                i_wp = headers.index("Workplace_ID") if headers and "Workplace_ID" in headers else None

                if i_wp is not None:
                    for r in (vals[1:] if len(vals) > 1 else []):
                        row_wp = (r[i_wp] if i_wp < len(r) else "").strip()
                        if row_wp == target_wp:
                            found = True
                            break
            except Exception:
                found = False

            if not target_wp:
                msg = "No workplace selected."
            elif not found:
                msg = "Workplace not found."
            else:
                session["workplace_id"] = target_wp
                ok = True
                msg = f"Opened workplace: {target_wp}"

        elif action == "create":
            workplace_id_raw = (request.form.get("workplace_id") or "").strip()
            company_name = (request.form.get("company_name") or "").strip()
            tax_rate = (request.form.get("tax_rate") or "20").strip()
            currency_symbol = (request.form.get("currency_symbol") or "£").strip() or "£"

            admin_first = (request.form.get("admin_first") or "").strip()
            admin_last = (request.form.get("admin_last") or "").strip()
            admin_username = (request.form.get("admin_username") or "").strip()
            admin_password = (request.form.get("admin_password") or "").strip()

            workplace_id = re.sub(r"[^a-zA-Z0-9_-]", "", workplace_id_raw).strip().lower()

            if not workplace_id:
                msg = "Workplace ID is required."
            elif not company_name:
                msg = "Company name is required."
            elif not admin_first:
                msg = "Admin first name is required."
            elif not admin_last:
                msg = "Admin last name is required."
            elif not admin_username:
                msg = "Admin username is required."
            elif len(admin_password) < 8:
                msg = "Admin password must be at least 8 characters."
            else:
                exists = False
                try:
                    vals = settings_sheet.get_all_values() if settings_sheet else []
                    headers = vals[0] if vals else []

                    if not vals:
                        settings_sheet.append_row(["Workplace_ID", "Tax_Rate", "Currency_Symbol", "Company_Name"])
                        vals = settings_sheet.get_all_values()
                        headers = vals[0] if vals else []

                    i_wp = headers.index("Workplace_ID") if headers and "Workplace_ID" in headers else None

                    if i_wp is not None:
                        for r in (vals[1:] if len(vals) > 1 else []):
                            row_wp = (r[i_wp] if i_wp < len(r) else "").strip().lower()
                            if row_wp == workplace_id:
                                exists = True
                                break

                    if exists:
                        msg = "That workplace already exists."
                    else:
                        existing_users = _employees_usernames_for_workplace(workplace_id)
                        if admin_username.lower() in existing_users:
                            msg = "That admin username already exists in this workplace."
                        else:
                            settings_row = [""] * len(headers)

                            if "Workplace_ID" in headers:
                                settings_row[headers.index("Workplace_ID")] = workplace_id
                            if "Tax_Rate" in headers:
                                settings_row[headers.index("Tax_Rate")] = tax_rate
                            if "Currency_Symbol" in headers:
                                settings_row[headers.index("Currency_Symbol")] = currency_symbol
                            if "Company_Name" in headers:
                                settings_row[headers.index("Company_Name")] = company_name

                            settings_sheet.append_row(settings_row)

                            _ensure_employees_columns()
                            emp_headers = get_sheet_headers(employees_sheet)
                            emp_row = [""] * len(emp_headers)

                            def set_emp(col_name, value):
                                if col_name in emp_headers:
                                    emp_row[emp_headers.index(col_name)] = value

                            set_emp("Username", admin_username)
                            set_emp("Password", generate_password_hash(admin_password))
                            set_emp("Role", "admin")
                            set_emp("Rate", "0")
                            set_emp("EarlyAccess", "TRUE")
                            set_emp("OnboardingCompleted", "")
                            set_emp("FirstName", admin_first)
                            set_emp("LastName", admin_last)
                            set_emp("Site", "")
                            set_emp("Workplace_ID", workplace_id)
                            if "Active" in emp_headers:
                                set_emp("Active", "TRUE")

                            employees_sheet.append_row(emp_row)
                            if DB_MIGRATION_MODE:
                                try:
                                    db_setting = WorkplaceSetting.query.filter_by(workplace_id=workplace_id).first()
                                    if not db_setting:
                                        db_setting = WorkplaceSetting(workplace_id=workplace_id)
                                        db.session.add(db_setting)

                                    db_setting.tax_rate = Decimal(str(tax_rate or "20"))
                                    db_setting.currency_symbol = currency_symbol
                                    db_setting.company_name = company_name

                                    db_admin = Employee.query.filter_by(username=admin_username,
                                                                        workplace_id=workplace_id).first()
                                    if not db_admin:
                                        db_admin = Employee.query.filter_by(email=admin_username,
                                                                            workplace_id=workplace_id).first()

                                    admin_hash = generate_password_hash(admin_password)

                                    if db_admin:
                                        db_admin.email = admin_username
                                        db_admin.username = admin_username
                                        db_admin.first_name = admin_first
                                        db_admin.last_name = admin_last
                                        db_admin.name = (" ".join([admin_first, admin_last])).strip() or admin_username
                                        db_admin.password = admin_hash
                                        db_admin.role = "admin"
                                        db_admin.rate = Decimal("0")
                                        db_admin.early_access = "TRUE"
                                        db_admin.active = "TRUE"
                                        db_admin.site = ""
                                        db_admin.workplace = workplace_id
                                        db_admin.workplace_id = workplace_id
                                    else:
                                        db.session.add(
                                            Employee(
                                                email=admin_username,
                                                username=admin_username,
                                                first_name=admin_first,
                                                last_name=admin_last,
                                                name=(" ".join([admin_first, admin_last])).strip() or admin_username,
                                                password=admin_hash,
                                                role="admin",
                                                rate=Decimal("0"),
                                                early_access="TRUE",
                                                active="TRUE",
                                                site="",
                                                workplace=workplace_id,
                                                workplace_id=workplace_id,
                                                created_at=None,
                                            )
                                        )

                                    db.session.commit()
                                except Exception:
                                    db.session.rollback()

                            if DB_MIGRATION_MODE:
                                try:
                                    db_setting = WorkplaceSetting.query.filter_by(workplace_id=workplace_id).first()
                                    if not db_setting:
                                        db_setting = WorkplaceSetting(workplace_id=workplace_id)
                                        db.session.add(db_setting)

                                    db_setting.tax_rate = Decimal(str(tax_rate or "20"))
                                    db_setting.currency_symbol = currency_symbol
                                    db_setting.company_name = company_name

                                    db_admin = Employee.query.filter_by(username=admin_username,
                                                                        workplace_id=workplace_id).first()
                                    if not db_admin:
                                        db_admin = Employee.query.filter_by(email=admin_username,
                                                                            workplace_id=workplace_id).first()

                                    admin_hash = generate_password_hash(admin_password)

                                    if db_admin:
                                        db_admin.email = admin_username
                                        db_admin.username = admin_username
                                        db_admin.first_name = admin_first
                                        db_admin.last_name = admin_last
                                        db_admin.name = (" ".join([admin_first, admin_last])).strip() or admin_username
                                        db_admin.password = admin_hash
                                        db_admin.role = "admin"
                                        db_admin.rate = Decimal("0")
                                        db_admin.early_access = "TRUE"
                                        db_admin.active = "TRUE"
                                        db_admin.site = ""
                                        db_admin.workplace = workplace_id
                                        db_admin.workplace_id = workplace_id
                                    else:
                                        db.session.add(
                                            Employee(
                                                email=admin_username,
                                                username=admin_username,
                                                first_name=admin_first,
                                                last_name=admin_last,
                                                name=(" ".join([admin_first, admin_last])).strip() or admin_username,
                                                password=admin_hash,
                                                role="admin",
                                                rate=Decimal("0"),
                                                early_access="TRUE",
                                                active="TRUE",
                                                site="",
                                                workplace=workplace_id,
                                                workplace_id=workplace_id,
                                                created_at=None,
                                            )
                                        )

                                    db.session.commit()
                                except Exception:
                                    db.session.rollback()

                            session["workplace_id"] = workplace_id
                            ok = True
                            msg = f"Created workplace: {workplace_id}"
                            created_info = {
                                "workplace_id": workplace_id,
                                "company_name": company_name,
                                "admin_username": admin_username,
                                "admin_password": admin_password,
                            }
                except Exception:
                    msg = "Could not create workplace."

    rows_html = []

    try:
        vals = settings_sheet.get_all_values() if settings_sheet else []
        headers = vals[0] if vals else []

        def idx(name):
            return headers.index(name) if headers and name in headers else None

        i_wp = idx("Workplace_ID")
        i_tax = idx("Tax_Rate")
        i_cur = idx("Currency_Symbol")
        i_name = idx("Company_Name")

        current_wp = _session_workplace_id()

        allowed_wps = set(_workplace_ids_for_read(current_wp))

        for r in (vals[1:] if len(vals) > 1 else []):
            wp = (r[i_wp] if i_wp is not None and i_wp < len(r) else "").strip()
            if not wp:
                continue

            tax = (r[i_tax] if i_tax is not None and i_tax < len(r) else "").strip()
            cur = (r[i_cur] if i_cur is not None and i_cur < len(r) else "").strip()
            name = (r[i_name] if i_name is not None and i_name < len(r) else "").strip() or wp
            status_text = "Current" if wp == current_wp else ""

            if wp == current_wp:
                open_btn = "<span style='font-weight:600; color: rgba(15,23,42,.55);'>Opened</span>"
            else:
                open_btn = f"""
                  <form method="POST" style="margin:0;">
                    <input type="hidden" name="csrf" value="{escape(csrf)}">
                    <input type="hidden" name="action" value="switch">
                    <input type="hidden" name="target_workplace" value="{escape(wp)}">
                    <button class="btnTiny" type="submit">Open</button>
                  </form>
                """

            rows_html.append(f"""
              <tr>
                <td style="width:36%;">
                  <div style="font-weight:700;">{escape(name)}</div>
                  <div class="sub" style="margin:2px 0 0 0;">{escape(wp)}</div>
                </td>
                <td class="num" style="width:12%; text-align:right;">{escape(tax)}</td>
                <td style="width:12%; text-align:center;">{escape(cur)}</td>
                <td style="width:16%; text-align:left; font-weight:600; color: rgba(15,23,42,.72);">{escape(status_text)}</td>
                <td style="width:14%; text-align:center;">{open_btn}</td>
              </tr>
            """)
    except Exception:
        rows_html = []

    table_html = "".join(rows_html) if rows_html else "<tr><td colspan='5'>No workplaces found.</td></tr>"

    created_card = ""
    if created_info:
        created_card = f"""
          <div class="card" style="padding:12px; margin-top:12px;">
            <h2>First admin created</h2>
            <div class="sub">Save these details now.</div>
            <div class="card" style="padding:12px; margin-top:10px; background:rgba(56,189,248,.18); border:1px solid rgba(56,189,248,.35); color:rgba(2,6,23,.95);">
              <div><b>Company:</b> {escape(created_info["company_name"])}</div>
              <div><b>Workplace ID:</b> {escape(created_info["workplace_id"])}</div>
              <div><b>Admin username:</b> {escape(created_info["admin_username"])}</div>
              <div><b>Admin password:</b> {escape(created_info["admin_password"])}</div>
            </div>
          </div>
        """

    content = f"""
      {page_back_button("/admin", "Back to Admin")}

      <div class="headerTop">
        <div>
          <h1>Workplaces</h1>
          <p class="sub">Master admin only.</p>
        </div>
        <div class="badge admin">{escape(role_label(session.get('role', 'master_admin')))}</div>
      </div>


      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

      <div class="card" style="padding:12px;">
        <h2>Create workplace</h2>
        <form method="POST">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <input type="hidden" name="action" value="create">

          <div class="row2">
            <div>
              <label class="sub">Workplace ID</label>
              <input class="input" name="workplace_id" placeholder="e.g. nw01" required>
            </div>
            <div>
              <label class="sub">Company name</label>
              <input class="input" name="company_name" placeholder="e.g. Newera North" required>
            </div>
          </div>

          <div class="row2">
            <div>
              <label class="sub">Tax rate</label>
              <input class="input" name="tax_rate" value="20" required>
            </div>
            <div>
              <label class="sub">Currency symbol</label>
              <input class="input" name="currency_symbol" value="£" required>
            </div>
          </div>

          <h2 style="margin-top:14px;">First admin</h2>

          <div class="row2">
            <div>
              <label class="sub">First name</label>
              <input class="input" name="admin_first" required>
            </div>
            <div>
              <label class="sub">Last name</label>
              <input class="input" name="admin_last" required>
            </div>
          </div>

          <div class="row2">
            <div>
              <label class="sub">Username</label>
              <input class="input" name="admin_username" required>
            </div>
            <div>
              <label class="sub">Password</label>
              <input class="input" name="admin_password" required>
            </div>
          </div>

          <button class="btnSoft" type="submit" style="margin-top:12px;">Create workplace</button>
        </form>
      </div>

      {created_card}

      <div class="card" style="padding:12px; margin-top:12px;">
  <h2>Existing workplaces</h2>
  <div class="tablewrap workplacesTableWrap" style="margin-top:12px;">
    <table class="workplacesTable" style="table-layout:fixed;">
      <thead>
        <tr>
          <th style="width:36%; text-align:left;">Company</th>
          <th class="num" style="width:12%; text-align:right;">Tax</th>
          <th style="width:12%; text-align:center;">Currency</th>
          <th style="width:16%; text-align:left;">Status</th>
          <th style="width:14%; text-align:center;">Open</th>
        </tr>
      </thead>
      <tbody>{table_html}</tbody>
    </table>
  </div>
</div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("workplaces", "master_admin", content))


# ================= DATABASE TABLES =================

class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    name = db.Column(db.String(255))
    role = db.Column(db.String(50))
    workplace = db.Column(db.String(255), index=True)
    created_at = db.Column(db.DateTime)

    username = db.Column(db.String(255), index=True)
    first_name = db.Column(db.String(255))
    last_name = db.Column(db.String(255))
    password = db.Column(db.Text)
    rate = db.Column(db.Numeric(10, 2))
    early_access = db.Column(db.String(10))
    active = db.Column(db.String(10))
    workplace_id = db.Column(db.String(255), index=True)
    active_session_token = db.Column(db.String(255), index=True)
    site = db.Column(db.String(255))
    site2 = db.Column(db.String(255))
    onboarding_completed = db.Column(db.String(20))


class WorkHour(db.Model):
    __tablename__ = "workhours"
    id = db.Column(db.Integer, primary_key=True)
    employee_email = db.Column(db.String(255), index=True)
    date = db.Column(db.Date, index=True)
    clock_in = db.Column(db.DateTime)
    clock_out = db.Column(db.DateTime)
    workplace = db.Column(db.String(255), index=True)
    hours = db.Column(db.Numeric(10, 2))
    pay = db.Column(db.Numeric(10, 2))
    in_lat = db.Column(db.Numeric(12, 8))
    in_lon = db.Column(db.Numeric(12, 8))
    in_acc = db.Column(db.Numeric(10, 2))
    in_site = db.Column(db.String(255))
    in_dist_m = db.Column(db.Integer)
    out_lat = db.Column(db.Numeric(12, 8))
    out_lon = db.Column(db.Numeric(12, 8))
    out_acc = db.Column(db.Numeric(10, 2))
    out_site = db.Column(db.String(255))
    out_dist_m = db.Column(db.Integer)
    in_selfie_url = db.Column(db.Text)
    out_selfie_url = db.Column(db.Text)
    workplace_id = db.Column(db.String(255), index=True)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(255))
    user_email = db.Column(db.String(255))
    actor = db.Column(db.String(255))
    username = db.Column(db.String(255))
    date_text = db.Column(db.String(50))
    details = db.Column(db.Text)
    workplace_id = db.Column(db.String(255), index=True)
    created_at = db.Column(db.DateTime)


class PayrollReport(db.Model):
    __tablename__ = "payroll_reports"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), index=True)
    week_start = db.Column(db.Date)
    week_end = db.Column(db.Date)
    gross = db.Column(db.Numeric(10, 2))
    tax = db.Column(db.Numeric(10, 2))
    net = db.Column(db.Numeric(10, 2))
    paid_at = db.Column(db.DateTime)
    paid_by = db.Column(db.String(255))
    paid = db.Column(db.String(50))
    workplace_id = db.Column(db.String(255), index=True)


class OnboardingRecord(db.Model):
    __tablename__ = "onboarding_records"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), index=True)
    workplace_id = db.Column(db.String(255), index=True)

    first_name = db.Column(db.String(255))
    last_name = db.Column(db.String(255))
    birth_date = db.Column(db.String(50))

    phone_country_code = db.Column(db.String(20))
    phone_number = db.Column(db.String(100))
    phone = db.Column(db.String(100))

    email = db.Column(db.String(255))

    street_address = db.Column(db.Text)
    city = db.Column(db.String(255))
    postcode = db.Column(db.String(50))
    address = db.Column(db.Text)

    emergency_contact_name = db.Column(db.String(255))
    emergency_contact_phone_country_code = db.Column(db.String(20))
    emergency_contact_phone_number = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(100))

    medical_condition = db.Column(db.Text)
    medical_details = db.Column(db.Text)

    position = db.Column(db.String(255))
    cscs_number = db.Column(db.String(255))
    cscs_expiry_date = db.Column(db.String(50))
    employment_type = db.Column(db.String(100))
    right_to_work_uk = db.Column(db.String(20))
    national_insurance = db.Column(db.String(100))
    utr = db.Column(db.String(100))
    start_date = db.Column(db.String(50))

    bank_account_number = db.Column(db.String(100))
    sort_code = db.Column(db.String(100))
    account_holder_name = db.Column(db.String(255))

    company_trading_name = db.Column(db.String(255))
    company_registration_no = db.Column(db.String(255))

    date_of_contract = db.Column(db.String(50))
    site_address = db.Column(db.Text)

    passport_or_birth_cert_link = db.Column(db.Text)
    cscs_front_back_link = db.Column(db.Text)
    public_liability_link = db.Column(db.Text)
    share_code_link = db.Column(db.Text)

    contract_accepted = db.Column(db.String(20))
    signature_name = db.Column(db.String(255))
    signature_datetime = db.Column(db.String(100))
    submitted_at = db.Column(db.String(100))


class Location(db.Model):
    __tablename__ = "locations"
    id = db.Column(db.Integer, primary_key=True)
    site_name = db.Column(db.String(255))
    lat = db.Column(db.Numeric(12, 8))
    lon = db.Column(db.Numeric(12, 8))
    radius_meters = db.Column(db.Integer)
    active = db.Column(db.String(50))
    workplace_id = db.Column(db.String(255), index=True)


class WorkplaceSetting(db.Model):
    __tablename__ = "workplace_settings"
    id = db.Column(db.Integer, primary_key=True)
    workplace_id = db.Column(db.String(255), unique=True)
    tax_rate = db.Column(db.Numeric(10, 2))
    currency_symbol = db.Column(db.String(20))
    company_name = db.Column(db.String(255))
    company_logo_url = db.Column(db.Text)


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
            if pay_txt == "":
                pay_txt = str(round(computed_hours * float(_get_user_rate(rec.employee_email or "")), 2))
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
    headers = ["Workplace_ID", "Tax_Rate", "Currency_Symbol", "Company_Name"]
    model = WorkplaceSetting

    def _records(self):
        return sorted(WorkplaceSetting.query.all(),
                      key=lambda r: (str(getattr(r, "workplace_id", "") or ""), getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            str(getattr(rec, "workplace_id", "") or ""),
            _db_format_decimal(getattr(rec, "tax_rate", None)),
            str(getattr(rec, "currency_symbol", "") or ""),
            str(getattr(rec, "company_name", "") or ""),
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
            data.get("Workplace_ID") or getattr(rec, "workplace_id", "default") or "default").strip() or "default"
        tax_txt = str(data.get("Tax_Rate") or "").strip()
        rec.tax_rate = Decimal(tax_txt) if tax_txt else Decimal("20")
        rec.currency_symbol = str(data.get("Currency_Symbol") or getattr(rec, "currency_symbol", "£") or "£")
        rec.company_name = str(data.get("Company_Name") or getattr(rec, "company_name", "Main") or "Main")

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


def _append_paid_record_safe(week_start: str, week_end: str, username: str, gross: float, tax: float, net: float,
                             paid_by: str):
    try:
        _ensure_payroll_headers()
        paid, _ = _is_paid_for_week(week_start, week_end, username)
        if paid:
            return
        paid_at = datetime.now(TZ)
        if DATABASE_ENABLED:
            db.session.add(
                PayrollReport(
                    username=username,
                    week_start=datetime.strptime(week_start, "%Y-%m-%d").date(),
                    week_end=datetime.strptime(week_end, "%Y-%m-%d").date(),
                    gross=Decimal(str(round(gross, 2))),
                    tax=Decimal(str(round(tax, 2))),
                    net=Decimal(str(round(net, 2))),
                    paid_at=paid_at,
                    paid_by=paid_by,
                    paid="",
                    workplace_id=_session_workplace_id(),
                )
            )
            db.session.commit()
            return
        payroll_sheet.append_row([week_start, week_end, username, money(gross), money(tax), money(net),
                                  paid_at.strftime("%Y-%m-%d %H:%M:%S"), paid_by, "", _session_workplace_id()])
    except Exception:
        if DATABASE_ENABLED:
            db.session.rollback()


def _patch_admin_only_endpoints():
    protected = [
        "db_view_employees", "db_view_workhours", "db_view_audit", "db_view_payroll", "db_view_onboarding",
        "db_view_locations", "db_view_settings",
        "db_upgrade_employees_table", "db_upgrade_onboarding_table",
        "import_employees", "import_locations", "import_settings", "import_audit", "import_payroll",
        "import_onboarding", "import_workhours",
    ]
    import_endpoints = {"import_employees", "import_locations", "import_settings", "import_audit", "import_payroll",
                        "import_onboarding", "import_workhours"}
    for endpoint in protected:
        original = app.view_functions.get(endpoint)
        if not original:
            continue

        def wrapped(*args, _original=original, _endpoint=endpoint, **kwargs):
            gate = require_admin()
            if gate:
                return gate
            if _endpoint in import_endpoints and not ENABLE_GOOGLE_SHEETS:
                return {"status": "error",
                        "message": "Google Sheets import is disabled. Set ENABLE_SHEETS_IMPORT=1 for one-time import."}, 400
            return _original(*args, **kwargs)

        app.view_functions[endpoint] = wrapped


_ensure_database_schema()
_patch_admin_only_endpoints()

if DATABASE_ENABLED:
    employees_sheet = _EmployeesProxy("Employees")
    work_sheet = _WorkHoursProxy("WorkHours")
    payroll_sheet = _PayrollProxy("PayrollReports")
    onboarding_sheet = _OnboardingProxy("Onboarding")
    settings_sheet = _SettingsProxy("Settings")
    audit_sheet = _AuditProxy("AuditLog")
    locations_sheet = _LocationsProxy("Locations")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=DEBUG_MODE)








