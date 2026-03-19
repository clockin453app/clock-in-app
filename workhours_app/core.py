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
from flask import Flask, request, session, redirect, url_for, abort, make_response, send_file
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
from workhours_app.extensions import db

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
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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

db.init_app(app)
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
                if (row.get("Workplace_ID", "") or "default").strip() != target_wp:
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
            if row_user == target_user and row_wp == target_wp:
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
    out = []

    if DB_MIGRATION_MODE:
        try:
            for rec in Employee.query.all():
                row = _employee_record_from_model(rec)
                if not row:
                    continue
                if (row.get("Workplace_ID", "") or "default").strip() != target_wp:
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
            if row_wp != target_wp:
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
    current_wp = _session_workplace_id()

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
        if row_wp != current_wp:
            continue

        d = getattr(rec, "date", None)
        cin = getattr(rec, "clock_in", None)
        cout = getattr(rec, "clock_out", None)

        hours_val = ""
        pay_val = ""

        if cin and cout:
            try:
                raw_hours = max(0.0, (cout - cin).total_seconds() / 3600.0)
                hours_num = round(_apply_unpaid_break(raw_hours), 2)
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
    current_wp = _session_workplace_id()

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
        if row_wp != current_wp:
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


def _get_import_sheet(sheet_name: str):
    """Return the sheet-like adapter used for one-time import operations.

    In database mode this still resolves to the proxy-backed objects created
    during ``initialize_runtime()``, which preserves compatibility with the old
    import/debug endpoints without depending on Google Sheets at runtime.
    """
    mapping = {
        "employees": employees_sheet,
        "workhours": work_sheet,
        "payroll": payroll_sheet,
        "onboarding": onboarding_sheet,
        "settings": settings_sheet,
        "audit": audit_sheet,
        "locations": locations_sheet,
    }
    key = str(sheet_name or "").strip().lower()
    sheet = mapping.get(key)
    if sheet is None:
        raise KeyError(f"Unknown import sheet: {sheet_name}")
    return sheet

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
        raise RuntimeError("Encrypted Drive token storage is unavailable. Install cryptography and configure token encryption.")
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

# Clock selfie settings
CLOCK_SELFIE_REQUIRED = str(os.environ.get("CLOCK_SELFIE_REQUIRED", "true") or "true").strip().lower() in ("1", "true", "yes", "on")
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


# ================= PWA / UI ASSETS =================

from flask import render_template

VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'
PWA_TAGS = """
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#ffffff">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<link rel="apple-touch-icon" href="/static/icon-192.png">
"""


def render_standalone_page(body_html: str, title: str = "WorkHours"):
    return render_template(
        "layouts/standalone_page.html",
        title=title,
        body_html=body_html,
    )


def render_app_page(active: str, role: str, content_html: str, title: str = "WorkHours", shell_class: str = ""):
    try:
        company_name = (get_company_settings().get("Company_Name") or "").strip() or "Main"
    except Exception:
        company_name = "Main"
    return render_template(
        "layouts/shell_page.html",
        title=title,
        body_html=content_html,
        active=active,
        role=role,
        shell_class=shell_class,
        company_name=company_name,
        sidebar_html=sidebar_html(active, role),
        bottom_nav_html=bottom_nav(active if active in ("home", "clock", "times", "reports", "profile", "admin", "workplaces") else "home", role),
    )


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
    """Return lowercase set of usernames in Employees for this workplace (if column exists)."""
    out = set()
    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return out
        headers = vals[0] or []
        if "Username" not in headers:
            return out
        ucol = headers.index("Username")
        wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
        target_wp = (wp or "").strip() or "default"

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
    return (session.get("workplace_id") or "").strip() or "default"


def _row_workplace_id(row):
    return (row.get("Workplace_ID") or "").strip() or "default"


def _same_workplace(row):
    return _row_workplace_id(row) == _session_workplace_id()


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


def user_in_same_workplace(username: str) -> bool:
    target = (username or "").strip()
    if not target:
        return False

    current_wp = _session_workplace_id()

    # IMPORTANT: do NOT return on the first match.
    # If usernames exist in multiple workplaces, check ALL matches.
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
    }

    current_wp = _session_workplace_id()

    try:
        records = WorkplaceSetting.query.all() if DB_MIGRATION_MODE else (get_settings() or [])

        for rec in records:
            if isinstance(rec, dict):
                row_wp = str(rec.get("Workplace_ID") or rec.get("workplace_id") or "default").strip() or "default"
                if row_wp != current_wp:
                    continue

                tax_raw = str(rec.get("Tax_Rate") or rec.get("tax_rate") or "").strip()
                cur = str(
                    rec.get("Currency_Symbol") or rec.get("currency_symbol") or defaults["Currency_Symbol"]).strip() or \
                      defaults["Currency_Symbol"]
                name = str(rec.get("Company_Name") or rec.get("company_name") or defaults["Company_Name"]).strip() or \
                       defaults["Company_Name"]
            else:
                row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip() or "default"
                if row_wp != current_wp:
                    continue

                tax_val = getattr(rec, "tax_rate", None)
                tax_raw = "" if tax_val is None else str(tax_val).strip()
                cur = str(getattr(rec, "currency_symbol", defaults["Currency_Symbol"]) or defaults[
                    "Currency_Symbol"]).strip() or defaults["Currency_Symbol"]
                name = str(
                    getattr(rec, "company_name", defaults["Company_Name"]) or defaults["Company_Name"]).strip() or \
                       defaults["Company_Name"]

            try:
                tax = float(tax_raw) if tax_raw != "" else defaults["Tax_Rate"]
            except Exception:
                tax = defaults["Tax_Rate"]

            return {
                "Workplace_ID": current_wp,
                "Tax_Rate": tax,
                "Currency_Symbol": cur,
                "Company_Name": name,
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

        return round(payable, 2)
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
                    if row_wp != current_wp:
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

    if DB_MIGRATION_MODE:
        try:
            for rec in Location.query.all():
                row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip() or "default"
                if row_wp != current_wp:
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
                if row_wp != current_wp:
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
            raise RuntimeError("Location accuracy is too low to verify this clock action. Move closer to the site and try again.")
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
        n = round(float(x or 0), 1)
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
    rec = Employee.query.filter_by(username=target_user, workplace_id=target_wp).first()
    if not rec:
        rec = Employee.query.filter_by(email=target_user, workplace_id=target_wp).first()
    return rec


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

    workplace_id = (session.get("workplace_id") or "default").strip() or "default"
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
    active_raw = ((row[active_col] if active_col is not None and len(row) > active_col else "TRUE") or "TRUE").strip().lower()
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

    for r in rows[1:]:
        if len(r) <= COL_DATE or len(r) <= COL_USER:
            continue

        row_user = (r[COL_USER] or "").strip()
        if row_user != u:
            continue

        # Prefer WorkHours row workplace if the column exists
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != current_wp:
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
            if row_wp != current_wp:
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
    target = (username or "").strip()

    for i in range(1, len(vals)):
        row = vals[i]
        row_user = (row[ucol] if len(row) > ucol else "").strip()
        if row_user != target:
            continue

        # If the sheet has Workplace_ID, require it to match the session workplace
        if wp_col is not None:
            row_wp = (row[wp_col] if len(row) > wp_col else "").strip() or "default"
            if row_wp != current_wp:
                continue

        return i + 1  # gspread row number (1-based)

    return None


def get_employee_display_name(username: str) -> str:
    u = (username or "").strip()
    if not u:
        return ""

    current_wp = _session_workplace_id()

    if DB_MIGRATION_MODE:
        try:
            rec = Employee.query.filter_by(username=u, workplace_id=current_wp).first()
            if not rec:
                rec = Employee.query.filter_by(email=u, workplace_id=current_wp).first()

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
                if row_wp != current_wp:
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

    if DB_MIGRATION_MODE:
        try:
            db_row = Employee.query.filter_by(username=username, workplace_id=current_wp).first()
            if not db_row:
                db_row = Employee.query.filter_by(email=username, workplace_id=current_wp).first()
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
    if actor == "master_admin":
        return {"employee", "admin"}
    if actor == "admin":
        return {"employee"}
    return {"employee"}


def _sanitize_requested_role(raw_role: str, actor_role: str) -> str | None:
    role = (raw_role or "").strip().lower()
    if not role:
        return None
    allowed = _allowed_assignable_roles_for_actor(actor_role)
    return role if role in allowed else None


def update_employee_password(username: str, new_password: str, workplace_id: str | None = None) -> bool:
    hashed = generate_password_hash(new_password)
    current_wp = (workplace_id or _session_workplace_id() or "default").strip() or "default"
    target_user = (username or "").strip()

    if not target_user:
        return False

    if DB_MIGRATION_MODE:
        try:
            db_row = Employee.query.filter_by(username=target_user, workplace_id=current_wp).first()
            if not db_row:
                db_row = Employee.query.filter_by(email=target_user, workplace_id=current_wp).first()
            if not db_row:
                return False
            db_row.password = hashed
            db_row.active_session_token = None
            db_row.workplace = current_wp
            db_row.workplace_id = current_wp
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


from sqlalchemy import or_, and_




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
    _ensure_onboarding_workplace_header()
    headers = get_sheet_headers(onboarding_sheet)
    if not headers or "Username" not in headers:
        raise RuntimeError("Onboarding sheet must have header row with 'Username'.")

    vals = onboarding_sheet.get_all_values()
    if not vals:
        raise RuntimeError("Onboarding sheet is empty (missing headers).")

    ucol = headers.index("Username")
    wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
    current_wp = _session_workplace_id()

    rownum = None
    for i in range(1, len(vals)):
        row = vals[i]
        row_u = (row[ucol] if ucol < len(row) else "").strip()
        if row_u != (username or "").strip():
            continue

        if wp_col is not None:
            row_wp = (row[wp_col] if wp_col < len(row) else "").strip() or "default"
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

    if DB_MIGRATION_MODE:
        try:
            rec = OnboardingRecord.query.filter_by(username=username, workplace_id=current_wp).first()
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
        except Exception:
            db.session.rollback()


def get_onboarding_record(username: str):
    current_wp = _session_workplace_id()

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
            if row_wp != current_wp:
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
        sensitive_full = {"BirthDate", "StreetAddress", "City", "Postcode", "MedicalCondition", "MedicalDetails", "SiteAddress"}
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


def _legacy_log_audit_before_db_patch(action: str, actor: str = "", username: str = "", date_str: str = "", details: str = ""):
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


def _legacy_append_paid_record_safe_before_db_patch(week_start: str, week_end: str, username: str, gross: float, tax: float, net: float,
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
    extra_admin = ""
    extra_workplaces = ""

    if role in ("admin", "master_admin"):
        extra_admin = f"""
        <a class="navIcon nav-admin {'active' if active == 'admin' else ''}" href="/admin" title="Admin">{_svg_shield()}</a>
        """

    if role == "master_admin":
        extra_workplaces = f"""
        <a class="navIcon nav-workplaces {'active' if active == 'workplaces' else ''}" href="/admin/workplaces" title="Workplaces">{_svg_doc()}</a>
        """

    return f"""
    <div class="bottomNav">
      <div class="navInner">
        <a class="navIcon nav-home {'active' if active == 'home' else ''}" href="/" title="Dashboard">{_svg_grid()}</a>
        <a class="navIcon nav-clock {'active' if active == 'clock' else ''}" href="/clock" title="Clock">{_svg_clock()}</a>
        <a class="navIcon nav-times {'active' if active == 'times' else ''}" href="/my-times" title="Time logs">{_svg_clipboard()}</a>
        <a class="navIcon nav-reports {'active' if active == 'reports' else ''}" href="/my-reports" title="Reports">{_svg_chart()}</a>
        {extra_admin}
        {extra_workplaces}
        <a class="navIcon nav-logout" href="/logout" title="Logout">{_svg_logout()}</a>
      </div>
    </div>
    """


def sidebar_html(active: str, role: str) -> str:
    items = [
        ("home", "/", "Dashboard", _svg_grid()),
        ("clock", "/clock", "Clock In & Out", _svg_clock()),
        ("times", "/my-times", "Time logs", _svg_clipboard()),
        ("reports", "/my-reports", "Timesheets", _svg_chart()),
        ("agreements", "/onboarding", "Starter Form", _svg_doc()),
        ("profile", "/password", "Profile", _svg_user()),
    ]
    if role in ("admin", "master_admin"):
        items.insert(5, ("admin", "/admin", "Admin", _svg_grid()))

    if role == "master_admin":
        items.insert(6, ("workplaces", "/admin/workplaces", "Workplaces", _svg_grid()))

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

    logout_html = f"""
      <div class="sideDivider"></div>
      <a class="sideItem logoutBtn" href="/logout">
        <div class="sideLeft">
          <div class="sideIcon">{_svg_logout()}</div>
          <div class="sideText">Logout</div>
        </div>
        <div class="chev">›</div>
      </a>
    """

    return f"""
      <div class="card sidebar">
        <div class="sideTitle">Menu</div>
        <div class="sideScroll">
          {''.join(links)}
        </div>
        {logout_html}
      </div>
    """


def layout_shell(active: str, role: str, content_html: str, shell_class: str = "") -> str:
    extra = f" {shell_class}" if shell_class else ""

    try:
        company_name = (get_company_settings().get("Company_Name") or "").strip() or "Main"
    except Exception:
        company_name = "Main"

    company_bar = f"""
      <div style="display:flex; justify-content:flex-end; margin-bottom:10px;">
        <span class="badge" style="background: var(--navy); color:#fff; border-color: rgba(255,255,255,.12);">
  {escape(company_name)}
</span>
      </div>
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


# ----- OAUTH CONNECT (ADMIN ONLY) -----




# ---------- LOGIN ----------






# ---------- DASHBOARD ----------


# ---------- CLOCK PAGE ----------




# ---------- MY REPORTS ----------


# ---------- STARTER FORM / ONBOARDING ----------


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
        drive_hint = "<p class='sub'>Master admin: if uploads fail, click <a href='/connect-drive' style='color:var(--navy);font-weight:600;'>Connect Drive</a> once.</p>"
    return f"""
      <div class="headerTop">
        <div>
          <h1>Starter Form</h1>
          <p class="sub">{escape(display_name)} • Save Draft anytime • Submit Final when complete</p>
          {drive_hint}
        </div>
        <div class="badge {'admin' if role == 'admin' else ''}">{escape(role.upper())}</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and msg_ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not msg_ok) else ""}

      <div class="card" style="padding:14px;">
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
          <div class="row2">
            <input class="input" name="phone_cc" value="{escape(val('phone_cc', 'PhoneCountryCode') or '+44')}">
            <input class="input {bad('phone_num')}" name="phone_num" value="{escape(val('phone_num', 'PhoneNumber'))}">
          </div>

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
          <div class="row2">
            <input class="input" name="ec_cc" value="{escape(val('ec_cc', 'EmergencyContactPhoneCountryCode') or '+44')}">
            <input class="input {bad('ec_phone')}" name="ec_phone" value="{escape(val('ec_phone', 'EmergencyContactPhoneNumber'))}">
          </div>

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

          <div class="row2" style="margin-top:14px;">
            <button class="btnSoft" name="submit_type" value="draft" type="submit">Save Draft</button>
            <button class="btnSoft" name="submit_type" value="final" type="submit" style="background:rgba(10,42,94,.14);">Submit Final</button>
          </div>
        </form>
      </div>
    """


# ---------- PROFILE (DETAILS + CHANGE PASSWORD) ----------


def _get_user_rate(username: str) -> float:
    """Fetch hourly rate for a username; prefer DB in migration mode, then fall back to sheet/session."""
    current_wp = _session_workplace_id()
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
                if row_wp != current_wp:
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

        for r in rows[1:]:
            if len(r) <= max(i_user, i_date, i_in, i_out):
                continue
            u = (r[i_user] or "").strip()
            # Tenant-safe: only show open shifts for this workplace
            if i_wp is not None:
                row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                if row_wp != current_wp:
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




# ---------- ADMIN ONBOARDING LIST / DETAIL ----------




# ---------- ADMIN LOCATIONS (Geofencing) ----------


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
                if row_wp != current_wp:
                    continue

            return i + 1
    except Exception:
        return None
    return None






# ---------- ADMIN: EMPLOYEE SITE ASSIGNMENTS ----------






# ================= LOCAL RUN =================




# ================= DATABASE TABLES =================

from workhours_app.models import (
    AuditLog,
    Employee,
    Location,
    OnboardingRecord,
    PayrollReport,
    WorkHour,
    WorkplaceSetting,
)


from workhours_app.legacy.proxies import (
    _AuditProxy,
    _EmployeesProxy,
    _LocationsProxy,
    _OnboardingProxy,
    _PayrollProxy,
    _ProxySheetBase,
    _SettingsProxy,
    _WorkHoursProxy,
    _db_bool_text,
    _db_format_decimal,
    _db_parse_date,
    _db_parse_datetime,
    _db_workhour_metrics,
    _db_workhour_order_key,
)


from workhours_app.legacy.migration_helpers import _ensure_database_schema


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






_RUNTIME_INITIALIZED = False


def initialize_runtime():
    global _RUNTIME_INITIALIZED, employees_sheet, work_sheet, payroll_sheet, onboarding_sheet, settings_sheet, audit_sheet, locations_sheet
    if _RUNTIME_INITIALIZED:
        return
    if _env_flag("AUTO_CREATE_DB_SCHEMA", default=False):
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
    _RUNTIME_INITIALIZED = True
