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
import secrets
import string
import math
import re
import time
import random
from urllib.parse import urlparse
from google.oauth2.service_account import Credentials as SACredentials
import gspread
from flask import Flask, request, session, redirect, url_for, render_template_string, abort, make_response, send_file
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from datetime import date, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials as UserCredentials
from google.auth.transport.requests import Request

from werkzeug.security import generate_password_hash, check_password_hash

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

    for _m in ("update", "update_cell", "update_cells", "append_row", "append_rows", "batch_update", "delete_rows", "insert_row", "insert_rows", "clear"):
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

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static",
)
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable must be set (do not use a default in production).")
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "15")) * 1024 * 1024
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"),
)

TZ = ZoneInfo(os.environ.get("APP_TZ", "Europe/London"))

# ================= GOOGLE SHEETS (SERVICE ACCOUNT) =================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds_json = os.environ.get("GOOGLE_CREDENTIALS", "").strip()

if creds_json:
    # Running on Render (env variable set)
    service_account_info = json.loads(creds_json)
    creds = SACredentials.from_service_account_info(service_account_info, scopes=SCOPES)
else:
    # Running locally (use credentials.json file)
    CREDENTIALS_FILE = "credentials.json"
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            "credentials.json not found locally and GOOGLE_CREDENTIALS not set."
        )
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
# Optional (recommended): Admin audit log
try:
    audit_sheet = spreadsheet.worksheet("AuditLog")
except Exception:
    audit_sheet = None

# Optional: geofenced clocking locations (Admin-managed)
try:
    locations_sheet = spreadsheet.worksheet("Locations")
except Exception:
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
    if not DRIVE_TOKEN_ENCRYPTION_KEY or not Fernet:
        return None
    try:
        return Fernet(DRIVE_TOKEN_ENCRYPTION_KEY.encode("utf-8"))
    except Exception:
        return None

def _save_drive_token(token_dict: dict):
    _ensure_instance_dir()
    payload = json.dumps(token_dict).encode("utf-8")
    f = _fernet()
    try:
        if f:
            payload = f.encrypt(payload)
        with open(DRIVE_TOKEN_STORE_PATH, "wb") as fp:
            fp.write(payload)
    except Exception:
        # Don't crash app on token write failure; uploads will fail until fixed.
        pass

def _load_drive_token() -> dict | None:
    # 1) Encrypted/plain file
    try:
        if os.path.exists(DRIVE_TOKEN_STORE_PATH):
            blob = open(DRIVE_TOKEN_STORE_PATH, "rb").read()
            f = _fernet()
            if f:
                try:
                    blob = f.decrypt(blob)
                except InvalidToken:
                    # Wrong key / corrupted file
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

def upload_to_drive(file_storage, filename_prefix: str) -> str:
    drive_service = get_user_drive_service()
    if not drive_service:
        raise RuntimeError("Drive not connected. Admin must visit /connect-drive once.")

    if UPLOAD_FOLDER_ID:
        try:
            drive_service.files().get(fileId=UPLOAD_FOLDER_ID, fields="id,name").execute()
        except Exception as e:
            raise RuntimeError("Upload folder not found. Fix ONBOARDING_DRIVE_FOLDER_ID (use a FOLDER id).") from e

    file_bytes = file_storage.read()
    file_storage.stream.seek(0)

    original = file_storage.filename or "upload"
    name = f"{filename_prefix}_{original}"

    media = MediaIoBaseUpload(
        io.BytesIO(file_bytes),
        mimetype=file_storage.mimetype or "application/octet-stream",
        resumable=False,
    )

    metadata = {"name": name}
    if UPLOAD_FOLDER_ID:
        metadata["parents"] = [UPLOAD_FOLDER_ID]

    created = drive_service.files().create(
        body=metadata,
        media_body=media,
        fields="id, webViewLink",
    ).execute()

    file_id = created["id"]
    return created.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"


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
UNPAID_BREAK_HOURS = 0.5     # deduct 30 minutes
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

VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'
PWA_TAGS = """
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#ffffff">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<link rel="apple-touch-icon" href="/static/icon-192.png">
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
  padding: 16px;
  border-radius: 22px;
}
.graphTop{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:12px;
}

.graphTitle{
  font-weight:800;
  font-size: 18px;
  color: rgba(15,23,42,.96);
}

.graphRange{
  color: var(--muted);
  font-size: 13px;
  font-weight:600;
}

.graphShell{
  margin-top: 14px;
  padding: 14px 14px 10px 14px;
  border-radius: 22px;
  border: 1px solid rgba(10,42,94,.10);
  background:
    linear-gradient(180deg, rgba(255,255,255,.96), rgba(248,250,252,.92)),
    radial-gradient(circle at top left, rgba(59,130,246,.10), transparent 45%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.6);
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
  color: rgba(30,64,175,.92);
  min-height: 16px;
  white-space: nowrap;
}

.barTrack{
  width: 100%;
  height: 180px;
  display:flex;
  align-items:flex-end;
  justify-content:center;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(30,64,175,.03), rgba(30,64,175,0));
  position: relative;
}

.bar{
  width: 72%;
  min-width: 24px;
  border-radius: 18px 18px 12px 12px;
  background: linear-gradient(180deg, #1e3a8a 0%, #3b82f6 100%);
  box-shadow: 0 14px 26px rgba(30,64,175,.22);
}

.barLabels{
  display:flex;
  justify-content:space-between;
  gap:14px;
  margin-top: 8px;
  color: var(--muted);
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
  background: rgba(255,255,255,.88);
  border:1px solid rgba(11,18,32,.08);
}
.payrollEmployeeCard{
  width:100%;
  box-sizing:border-box;
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
.weeklyEditTable thead th{
  background: linear-gradient(180deg, #dc2626, #b91c1c);
  color: white;
  font-size:13px;
  font-weight:800;
  padding:12px 10px;
  border-bottom:1px solid rgba(127,29,29,.35);
}

.weeklyEditTable tbody td{
  padding:14px 10px;
  border-bottom:1px solid rgba(11,18,32,.06);
  color: rgba(15,23,42,.92);
  font-size:14px;
  background: rgba(255,255,255,.82);
  vertical-align:middle;
}

.weeklyEditTable tbody tr:nth-child(even) td{
  background: rgba(248,250,252,.78);
}

.weeklyEditTable tbody tr:hover td{
  background: rgba(239,246,255,.72);
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
.graphCard{
  margin-top: 12px;
  padding: 16px;
  border-radius: 22px;
}

.graphTop{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:12px;
}

.graphTitle{
  font-weight:800;
  font-size: 18px;
  color: rgba(15,23,42,.96);
}

.graphRange{
  color: var(--muted);
  font-size: 13px;
  font-weight:600;
}

.graphShell{
  margin-top: 14px;
  padding: 14px 14px 10px 14px;
  border-radius: 22px;
  border: 1px solid rgba(10,42,94,.10);
  background:
    linear-gradient(180deg, rgba(255,255,255,.96), rgba(248,250,252,.92)),
    radial-gradient(circle at top left, rgba(59,130,246,.10), transparent 45%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.6);
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
  color: rgba(30,64,175,.92);
  min-height: 16px;
  white-space: nowrap;
}

.barTrack{
  width: 100%;
  height: 180px;
  display:flex;
  align-items:flex-end;
  justify-content:center;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(30,64,175,.03), rgba(30,64,175,0));
  position: relative;
}

.bar{
  width: 72%;
  min-width: 24px;
  border-radius: 18px 18px 12px 12px;
  background: linear-gradient(180deg, #1e3a8a 0%, #3b82f6 100%);
  box-shadow: 0 14px 26px rgba(30,64,175,.22);
}

.barLabels{
  display:flex;
  justify-content:space-between;
  gap:14px;
  margin-top: 8px;
  color: var(--muted);
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

/* Menu */
.menu{ margin-top: 14px; padding: 12px; }

.adminGrid{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 6px;
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
  width: 46px;
  height: 46px;
  border-radius: 14px;
  display:grid;
  place-items:center;
  border: 1px solid rgba(15,23,42,.08);
}
.adminToolIcon svg{
  width: 22px;
  height: 22px;
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
/* Download CSV button styled like week pills (btnTiny) */
.btnTiny.csvDownload{
  background: #217346;
  border-color: #1a5c37;
  color: #fff;
}
.btnTiny.csvDownload:hover{
  background: #1b5f38;
  border-color: #144a2b;
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

/* Clock */
.clockCard{ margin-top: 12px; padding: 14px; }
.timerBig{
  font-weight:800;
  font-size: clamp(26px, 6vw, 36px);
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
.tablewrap td:last-child button,
.tablewrap td:last-child a{
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
  padding: 14px;
}

.payrollChartCard{
  background:
    linear-gradient(180deg, rgba(239,246,255,.96), rgba(255,255,255,.96));
  border: 1px solid rgba(59,130,246,.14);
}

.payrollDonutWrap{
  margin-top: 8px;
  display:flex;
  align-items:center;
  justify-content:center;
  min-height: 250px;
}

.payrollDonut{
  width: 230px;
  height: 230px;
  border-radius: 999px;
  position: relative;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.6), 0 12px 26px rgba(15,23,42,.08);
}

.payrollDonut::after{
  content:"";
  position:absolute;
  inset: 38px;
  border-radius: 999px;
  background: white;
  box-shadow: inset 0 1px 0 rgba(15,23,42,.04);
}

.payrollDonutCenter{
  position:absolute;
  inset:0;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  z-index:2;
  text-align:center;
  pointer-events:none;
}

.payrollDonutCenter .k{
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
}

.payrollDonutCenter .v{
  margin-top: 4px;
  font-size: 20px;
  font-weight: 800;
  color: rgba(15,23,42,.96);
}

.payrollLegend{
  margin-top: 12px;
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap:8px;
  align-items:start;
}

@media (max-width: 1100px){
  .payrollLegend{
    grid-template-columns: 1fr;
  }
}

.payrollLegendRow{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:8px;
  padding:7px 9px;
  border-radius: 12px;
  border:1px solid rgba(11,18,32,.08);
  background: rgba(255,255,255,.84);
  min-width:0;
}

.payrollLegendLeft{
  display:flex;
  align-items:center;
  gap:8px;
  min-width:0;
}

.payrollLegendDot{
  width:12px;
  height:12px;
  border-radius:999px;
  flex:0 0 auto;
}

.payrollLegendName{
  font-size:12px;
  font-weight:700;
  color: rgba(15,23,42,.88);
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}

.payrollLegendVal{
  font-size:12px;
  font-weight:800;
  color: rgba(30,64,175,.95);
  white-space:nowrap;
}
@media (max-width: 800px){
  .kpiStrip{ grid-template-columns: 1fr 1fr; }
}
.kpiMini{
  padding: 12px;
  border-radius: 18px;
  border: 1px solid rgba(11,18,32,.10);
  background: rgba(255,255,255,.80);
}
.kpiMini .k{ font-size: 12px; color: var(--muted); font-weight:600; }
.kpiMini .v{ margin-top:6px; font-size: 18px; font-weight:800; font-variant-numeric: tabular-nums; }
/* Admin summary cards */
.adminStats .adminStatCard{
  border-radius: 18px;
  border: 1px solid rgba(15,23,42,.10);
  box-shadow: 0 8px 22px rgba(15,23,42,.06);
}

.adminStats .adminStatCard .k{
  font-size: 12px;
  font-weight: 700;
}

.adminStats .adminStatCard .v{
  font-size: 18px;
  font-weight: 900;
}

/* Individual colors */
.adminStats .adminStatCard.employees{
  background: linear-gradient(180deg, rgba(219,234,254,.55), rgba(255,255,255,.96));
  border-color: rgba(37,99,235,.16);
}
.adminStats .adminStatCard.employees .k,
.adminStats .adminStatCard.employees .v{
  color: #1d4ed8;
}

.adminStats .adminStatCard.clocked{
  background: linear-gradient(180deg, rgba(220,252,231,.55), rgba(255,255,255,.96));
  border-color: rgba(22,163,74,.16);
}
.adminStats .adminStatCard.clocked .k,
.adminStats .adminStatCard.clocked .v{
  color: #15803d;
}

.adminStats .adminStatCard.locations{
  background: linear-gradient(180deg, rgba(207,250,254,.55), rgba(255,255,255,.96));
  border-color: rgba(8,145,178,.16);
}
.adminStats .adminStatCard.locations .k,
.adminStats .adminStatCard.locations .v{
  color: #0e7490;
}

.adminStats .adminStatCard.onboarding{
  background: linear-gradient(180deg, rgba(224,231,255,.55), rgba(255,255,255,.96));
  border-color: rgba(79,70,229,.16);
}
.adminStats .adminStatCard.onboarding .k,
.adminStats .adminStatCard.onboarding .v{
  color: #4338ca;
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

/* Bottom nav (mobile) */
.bottomNav{
  position: fixed;
  left: 0; right: 0; bottom: 0;
  background: rgba(255,255,255,.92);
  border-top: 1px solid rgba(11,18,32,.10);
  backdrop-filter: blur(10px);
  padding: 10px 14px calc(14px + env(safe-area-inset-bottom)) 14px;
  z-index: 99;
  border-radius: 20px 20px 0 0;
  box-shadow: 0 -8px 30px rgba(11,18,32,.12);
}
.navInner{
  max-width:560px;
  margin: 0 auto;
  display:flex;
  align-items:center;
  justify-content:space-around;
}
.navIcon{
  width: 46px; height: 46px;
  border-radius: 16px;
  display:grid; place-items:center;
  color: var(--navy);
  transition: transform .16s ease, background .16s ease, box-shadow .16s ease;
}
.navIcon.active{ background: rgba(30,64,175,.10); }
.navIcon svg{ width: 22px; height: 22px; }
.safeBottom{ height: calc(120px + env(safe-area-inset-bottom)); }

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
    width: 36px; height: 36px;
    border-radius: 12px;
    background: linear-gradient(180deg, rgba(239,246,255,.95), rgba(219,234,254,.90));
    border: 1px solid rgba(30,64,175,.12);
    display:grid; place-items:center;
    color: var(--navy);
  }
  .sideIcon svg{ width:18px; height:18px; }
  
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

/* ================= PAYROLL SHEET (Spreadsheet style) ================= */
.payrollWrap{
  margin-top:14px;
  width: 100%;
  max-width: 100%;
  min-width: 0;                 /* IMPORTANT */
  background:#fff;
  border:1px solid rgba(15,23,42,.12);
  border-radius: 14px;
  overflow-x: auto;             /* horizontal scroll */
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  box-shadow: var(--shadow);
}

.payrollTitleRow{
  display:flex;
  align-items:flex-end;
  justify-content:space-between;
  gap:12px;
  padding: 14px 14px 10px 14px;
  border-bottom:1px solid rgba(15,23,42,.08);
}
.payrollTitleRow .title{
  font-weight:800;
  font-size: 18px;
  margin:0;
}
.payrollTitleRow .sub{
  margin:4px 0 0 0;
  color: rgba(15,23,42,.62);
  font-size: 13px;
}

.payrollSheet{
  width: max-content;
  border-collapse: collapse;
  table-layout: fixed;
  min-width: 2200px;
  background:#fff;
}

.payrollSheet tbody tr:hover td{
  background: rgba(30,64,175,.14);
}
.payrollSheet tbody tr:hover td:first-child{
  box-shadow: inset 3px 0 0 rgba(30,64,175,.45);
}
/* Let zebra show through disabled inputs in the weekly grid */
.payrollSheet input:disabled,
.payrollSheet select:disabled{
  background: transparent;
}
.payrollSheet input:disabled,
.payrollSheet select:disabled{
  background: transparent;
}

/* PASTE THIS RIGHT HERE */
.payrollSheet input[type="time"]{
  font-weight: 800;
  color: rgba(2,6,23,.98);
}
.payrollSheet input[type="time"]:disabled{
  opacity: 1;
  -webkit-text-fill-color: rgba(2,6,23,.98);
}
/* END PASTE */
.payrollSheet th{
  border:1px solid rgba(15,23,42,.10);
  padding: 7px 8px;
  font-size: 13px;
  line-height: 1.2;
  vertical-align: middle;
  background:#fff;               /* header stays white */
  color: rgba(11,18,32,.88);
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}

.payrollSheet td{
  border:1px solid rgba(15,23,42,.10);
  padding: 7px 8px;
  font-size: 15px;
  line-height: 1.35;
  vertical-align: middle;
  background: transparent;       /* allow zebra to show */
  color: rgba(11,18,32,.88);
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
  font-weight: 750;
  color: rgba(2,6,23,.92);
}
/* Net column: yellow CELL, normal text */
.payrollSheet td.net{
  background: rgba(250,204,21,.22);   /* soft yellow */
  color: rgba(2,6,23,.92);            /* normal/dark text */
  font-weight: 800;
}
.payrollSheet thead th{
  position: sticky;
  top: 0;
  z-index: 5;
  background: #f8fafc;
  font-weight: 1100;
  color: rgba(15,23,42,.86);
    font-size: 13px;
  letter-spacing: .3px;
  text-transform: none;
}

.payrollSheet thead tr.group th{
  background: #eef2ff;
  color: rgba(30,64,175,1);
  font-weight: 900;
  text-transform: uppercase;
  letter-spacing: .6px;
  font-size: 11px;
}

.payrollSheet thead tr.cols th{
  background: #f8fafc;
  font-weight: 800;
  font-size: 12px;
}
/* Make the big payroll day columns tighter */
.payrollSheet thead tr.cols th{
  padding: 6px 4px;
}

.payrollSheet thead tr.cols th:nth-child(3n+1),
.payrollSheet thead tr.cols th:nth-child(3n+2){
  width: 52px;
  min-width: 52px;
  max-width: 52px;
}

.payrollSheet thead tr.cols th:nth-child(3n+3){
  width: 42px;
  min-width: 42px;
  max-width: 42px;
}

/* Body cells for the 7 day columns only (cols 2 to 22 in each row) */
.payrollSheet tbody td:nth-child(3n+2):nth-child(-n+22),
.payrollSheet tbody td:nth-child(3n+3):nth-child(-n+22){
  width: 52px;
  min-width: 52px;
  max-width: 52px;
  padding-left: 4px;
  padding-right: 4px;
}

.payrollSheet tbody td:nth-child(3n+4):nth-child(-n+22){
  width: 42px;
  min-width: 42px;
  max-width: 42px;
  padding-left: 4px;
  padding-right: 4px;
}
.payrollSheet .num{ text-align:right; white-space:nowrap; }
.payrollSheet .emp{ font-weight:900; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.payrollSheet .empSub{
  display:block;
  font-weight:600;
  color: rgba(15,23,42,.55);
  margin-top: 2px;
  font-size: 12px;
}

.payrollSheet input,
.payrollSheet select{
  width: 100%;
  height: 30px;
  padding: 4px 8px;
  border-radius: 8px;
  border: 1px solid rgba(15,23,42,.14);
  background: #fff;
  font-size: 13px;
  outline: none;
}
.payrollSheet input.payrollTimeInput{
  width: 48px !important;
  height: 18px !important;
  padding: 0 !important;
  border: none !important;
  border-radius: 0 !important;
  background: transparent !important;
  box-shadow: none !important;
  font-size: 10px !important;
  font-weight: 800 !important;
  text-align: center !important;
  color: rgba(15,23,42,.92) !important;
  outline: none !important;
  appearance: none;
  -webkit-appearance: none;
}

/* Hide the browser's empty time placeholder like --:-- or dots */
.payrollSheet input.payrollTimeInput[value=""]{
  color: transparent !important;
}

.payrollSheet input.payrollTimeInput[value=""]::-webkit-datetime-edit{
  color: transparent !important;
}

.payrollSheet input.payrollTimeInput[value=""]::-webkit-date-and-time-value{
  color: transparent !important;
}

.payrollSheet input.payrollTimeInput:focus{
  color: rgba(15,23,42,.92) !important;
  background: rgba(30,64,175,.06) !important;
  border-radius: 6px !important;
  box-shadow: inset 0 0 0 1px rgba(30,64,175,.18) !important;
}

.payrollSheet input.payrollTimeInput:focus::-webkit-datetime-edit,
.payrollSheet input.payrollTimeInput:focus::-webkit-date-and-time-value{
  color: rgba(15,23,42,.92) !important;
}
.payrollSheet input:focus,
.payrollSheet select:focus{
  border-color: rgba(30,64,175,.45);
  box-shadow: 0 0 0 3px rgba(30,64,175,.10);
}
.payrollTimeInput{
  width: 72px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  font-size: 12px;
  font-weight: 800;
  text-align: center;
  color: rgba(15,23,42,.92);
  appearance: none;
  -webkit-appearance: none;
}

.payrollTimeInput:focus{
  outline: none;
  background: rgba(30,64,175,.06);
  border-radius: 6px;
  box-shadow: inset 0 0 0 1px rgba(30,64,175,.18);
}
.payrollSheet tfoot td{
  background:#f8fafc;
  font-weight: 900;
}

.payrollSheet .net{
  background: rgba(34,197,94,.08);
  font-weight: 900;
}

/* Mark Paid button inside payroll sheet */
.payrollWrap button,
.payrollWrap a{
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
  font-weight: 900;
  cursor: pointer;
  transition: all .15s ease;
  white-space: nowrap;
}
.payrollWrap button:hover,
.payrollWrap a:hover{
  background: rgba(30,64,175,.14);
  border-color: rgba(30,64,175,.35);
}
/* Keep Net cell yellow even on row hover */
.payrollSheet tbody tr:hover td.net{
  background: rgba(250,204,21,.30);
}
/* Responsive payroll sizing */
.payrollEmpCell{
  min-width: 135px;
  max-width: 135px;
}

/* Wide desktop */
@media (max-width: 1700px) and (min-width: 980px){
  .payrollSheet{
    min-width: 2050px;
  }

  .payrollEmpCell{
    min-width: 120px;
    max-width: 120px;
  }

  .payrollSheet th{
    padding: 6px 6px;
    font-size: 12px;
  }

  .payrollSheet td{
    padding: 6px 6px;
    font-size: 13px;
  }

  .payrollSheet input.payrollTimeInput{
    width: 44px !important;
    font-size: 10px !important;
  }

  .payCellBtn{
    min-height: 30px;
    padding: 4px 6px;
    font-size: 11px;
  }

  .payCellBtn .payLabel{
    font-size: 10px;
  }
}

/* Smaller laptop desktop */
@media (max-width: 1450px) and (min-width: 980px){
  .payrollSheet{
    min-width: 1880px;
  }

  .payrollEmpCell{
    min-width: 108px;
    max-width: 108px;
  }

  .payrollSheet th{
    padding: 5px 4px;
    font-size: 11px;
  }

  .payrollSheet td{
    padding: 5px 4px;
    font-size: 12px;
  }

  .payrollSheet input.payrollTimeInput{
    width: 38px !important;
    font-size: 9px !important;
  }

  .payCellBtn{
    min-height: 28px;
    padding: 3px 5px;
    font-size: 10px;
  }

  .payCellBtn .payLabel{
    font-size: 9px;
  }

  .payrollSheet tbody td:nth-child(2),
  .payrollSheet tbody td:nth-child(3),
  .payrollSheet tbody td:nth-child(5),
  .payrollSheet tbody td:nth-child(6),
  .payrollSheet tbody td:nth-child(8),
  .payrollSheet tbody td:nth-child(9),
  .payrollSheet tbody td:nth-child(11),
  .payrollSheet tbody td:nth-child(12),
  .payrollSheet tbody td:nth-child(14),
  .payrollSheet tbody td:nth-child(15),
  .payrollSheet tbody td:nth-child(17),
  .payrollSheet tbody td:nth-child(18),
  .payrollSheet tbody td:nth-child(20),
  .payrollSheet tbody td:nth-child(21){
    width: 42px;
    min-width: 42px;
    max-width: 42px;
  }

  .payrollSheet tbody td:nth-child(4),
  .payrollSheet tbody td:nth-child(7),
  .payrollSheet tbody td:nth-child(10),
  .payrollSheet tbody td:nth-child(13),
  .payrollSheet tbody td:nth-child(16),
  .payrollSheet tbody td:nth-child(19),
  .payrollSheet tbody td:nth-child(22){
    width: 34px;
    min-width: 34px;
    max-width: 34px;
  }
}
/* Tighten the last 4 payroll columns */
.payrollSheet thead tr.group th:nth-last-child(4){
  width: 72px;
  min-width: 72px;
  max-width: 72px;
}

.payrollSheet thead tr.group th:nth-last-child(3){
  width: 92px;
  min-width: 92px;
  max-width: 92px;
}

.payrollSheet thead tr.group th:nth-last-child(2){
  width: 82px;
  min-width: 82px;
  max-width: 82px;
}

.payrollSheet thead tr.group th:nth-last-child(1){
  width: 120px;
  min-width: 120px;
  max-width: 120px;
}

.payrollSheet tbody td:nth-child(23){
  width: 72px;
  min-width: 72px;
  max-width: 72px;
}

.payrollSheet tbody td:nth-child(24){
  width: 92px;
  min-width: 92px;
  max-width: 92px;
}

.payrollSheet tbody td:nth-child(25){
  width: 82px;
  min-width: 82px;
  max-width: 82px;
}

.payrollSheet tbody td:nth-child(26){
  width: 120px;
  min-width: 120px;
  max-width: 120px;
}

/* Smaller pay button inside Net / Pay */
.payCellBtn{
  min-height: 28px;
  padding: 4px 6px;
  font-size: 11px;
}

.payCellBtn .payLabel{
  font-size: 10px;
}
/* Net cell as payment action */
.payCellForm{
  margin: 0;
}

.payCellBtn{
  width: 100%;
  min-height: 34px;
  border: none;
  border-radius: 10px;
  padding: 6px 8px;
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
  background: rgba(250,204,21,.22);
  color: rgba(2,6,23,.92);
  transition: transform .12s ease, filter .12s ease, box-shadow .12s ease;
}

.payCellBtn:hover{
  filter: brightness(0.98);
  box-shadow: inset 0 0 0 1px rgba(146,64,14,.18);
}

.payCellBtn:active{
  transform: scale(.99);
}

.payCellBtn .payLabel{
  display:block;
  font-size: 11px;
  font-weight: 800;
  color: rgba(146,64,14,.95);
  margin-top: 2px;
}

.payrollSheet td.net.paidNetCell{
  background: rgba(22,163,74,.18) !important;
  color: rgba(21,128,61,.98) !important;
  font-weight: 900;
  text-align: center;
}

.payrollSheet td.net.zeroNetCell{
  background: rgba(250,204,21,.16) !important;
  color: rgba(2,6,23,.92) !important;
  font-weight: 800;
  text-align: right;
}

/* Print tidy */
@media print{
  .sidebar, .bottomNav, button, input, select, .weekRow { display:none !important; }
  body{ padding:0 !important; background:#fff !important; }
  .shell{ width:100% !important; max-width:none !important; grid-template-columns: 1fr !important; }
  .card{ box-shadow:none !important; }
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
from datetime import datetime, timedelta
def user_in_same_workplace(username: str) -> bool:
    target = (username or "").strip()
    if not target:
        return False

    current_wp = _session_workplace_id()

    # IMPORTANT: do NOT return on the first match.
    # If usernames exist in multiple workplaces, check ALL matches.
    try:
        for rec in employees_sheet.get_all_records():
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

    if not settings_sheet:
        return defaults

    try:
        vals = settings_sheet.get_all_values()
        if not vals or len(vals) < 2:
            return defaults

        headers = vals[0]

        def idx(name):
            return headers.index(name) if name in headers else None

        i_wp = idx("Workplace_ID")
        i_tax = idx("Tax_Rate")
        i_cur = idx("Currency_Symbol")
        i_name = idx("Company_Name")

        current_wp = _session_workplace_id()

        for row in vals[1:]:
            row_wp = ((row[i_wp] if i_wp is not None and i_wp < len(row) else "").strip() or "default")
            if row_wp != current_wp:
                continue

            tax_raw = (row[i_tax] if i_tax is not None and i_tax < len(row) else "").strip()
            cur = (row[i_cur] if i_cur is not None and i_cur < len(row) else "").strip() or defaults["Currency_Symbol"]
            name = (row[i_name] if i_name is not None and i_name < len(row) else "").strip() or defaults["Company_Name"]

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
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def linkify(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    p = urlparse(u)
    if p.scheme not in ("http", "https"):
        return ""
    uesc = escape(u)
    return f"<a href='{uesc}' target='_blank' rel='noopener noreferrer' style='color:var(--navy);font-weight:600;'>Open</a>"



# ================= GEOLOCATION (GEOFENCE) =================
# Employees sheet: optional column "Site" that assigns an employee to a site name in Locations sheet.
# Locations sheet headers (recommended):
#   SiteName | Lat | Lon | RadiusMeters | Active
#
# WorkHours sheet (optional extra columns):
#   InLat, InLon, InAcc, InSite, InDistM, OutLat, OutLon, OutAcc, OutSite, OutDistM

WORKHOURS_GEO_HEADERS = [
    "InLat","InLon","InAcc","InSite","InDistM",
    "OutLat","OutLon","OutAcc","OutSite","OutDistM",
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
            work_sheet.update(f"A1:{gspread.utils.rowcol_to_a1(1, len(headers)).replace('1','')}1", [headers])
    except Exception:
        return

def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    # distance in meters
    from math import radians, sin, cos, asin, sqrt
    R = 6371000.0
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(phi1)*cos(phi2)*sin(dl/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def _get_employee_sites(username: str) -> list[str]:
    """Return list of site names assigned to employee.
    Supports:
      - Employees sheet column 'Site' with comma/semicolon-separated sites
      - Optional column 'Site2' (if present)
    """
    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return []
        headers = vals[0]
        if "Username" not in headers:
            return []
        ucol = headers.index("Username")
        wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
        current_wp = _session_workplace_id()
        scol = headers.index("Site") if "Site" in headers else None
        s2col = headers.index("Site2") if "Site2" in headers else None

        for i in range(1, len(vals)):
            row = vals[i]
            if len(row) > ucol and (row[ucol] or "").strip() == username:
                if wp_col is not None:
                    row_wp = (row[wp_col] if len(row) > wp_col else "").strip() or "default"
                    if row_wp != current_wp:
                        continue
                sites: list[str] = []
                if scol is not None and scol < len(row):
                    raw = (row[scol] or "").strip()
                    if raw:
                        # allow comma/semicolon separated
                        for part in re.split(r"[;,]", raw):
                            p = (part or "").strip()
                            if p:
                                sites.append(p)
                if s2col is not None and s2col < len(row):
                    raw2 = (row[s2col] or "").strip()
                    if raw2:
                        for part in re.split(r"[;,]", raw2):
                            p = (part or "").strip()
                            if p:
                                sites.append(p)
                # unique preserve order
                seen = set()
                out = []
                for s in sites:
                    key = s.lower()
                    if key not in seen:
                        seen.add(key)
                        out.append(s)
                return out
    except Exception:
        return []
    return []

def _get_employee_site(username: str) -> str:
    """Backwards-compatible: return primary site (first) or empty."""
    sites = _get_employee_sites(username)
    return sites[0] if sites else ""

def _get_active_locations() -> list[dict]:
    out = []
    if not locations_sheet:
        return out
    try:
        vals = locations_sheet.get_all_values()
        if not vals:
            return out
        headers = vals[0]
        def idx(n): return headers.index(n) if n in headers else None

        i_name = idx("SiteName");
        i_lat = idx("Lat");
        i_lon = idx("Lon");
        i_rad = idx("RadiusMeters");
        i_act = idx("Active")
        i_wp = idx("Workplace_ID");
        current_wp = _session_workplace_id()
        for r in vals[1:]:
            # Workplace filter (only if Locations sheet has Workplace_ID column)
            if i_wp is not None:
                row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                if row_wp != current_wp:
                    continue
            name = (r[i_name] if i_name is not None and i_name < len(r) else "").strip()
            if not name:
                continue
            active = (r[i_act] if i_act is not None and i_act < len(r) else "TRUE").strip().upper()
            if active not in ("TRUE","YES","1"):
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

def _validate_user_location(username: str, lat: float | None, lon: float | None, acc_m: float | None = None) -> tuple[bool, dict, float]:
    """Returns (ok, site_cfg, distance_m).

    Behavior:
      - If employee has assigned site(s): validate against those sites (passes if inside ANY site radius).
      - Fallback (no assigned site): validate against ANY active site (passes if inside ANY active site radius),
        choosing the nearest site as the 'matched' one.
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

    # GPS accuracy can be noisy (especially desktop / Wi‑Fi positioning).
    # If provided, allow a small uncertainty buffer so users don't get falsely blocked.
    try:
        acc_buf = float(acc_m) if acc_m is not None else 0.0
        if acc_buf < 0:
            acc_buf = 0.0
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

    # Build candidate list
    candidates = []
    if sites:
        # only those sites (if found/active)
        for sname in sites:
            cfg = _get_site_config(sname)
            if cfg:
                candidates.append(cfg)
        # If assigned sites exist but none are active/found, fall back to all active
        if not candidates:
            candidates = active_sites[:]
    else:
        # fallback: any active site
        candidates = active_sites[:]

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

def require_login():
    if "username" not in session:
        return redirect(url_for("login"))
    return None

def require_admin():
    gate = require_login()
    if gate:
        return gate
    if session.get("role") != "admin":
        return redirect(url_for("home"))
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
    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return username

        headers = vals[0]
        if "Username" not in headers:
            return username

        ucol = headers.index("Username")
        wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
        fn_col = headers.index("FirstName") if "FirstName" in headers else None
        ln_col = headers.index("LastName") if "LastName" in headers else None

        current_wp = _session_workplace_id()
        u = (username or "").strip()

        for i in range(1, len(vals)):
            row = vals[i]
            row_user = (row[ucol] if len(row) > ucol else "").strip()
            if row_user != u:
                continue

            # If Workplace_ID exists, require it to match session workplace
            if wp_col is not None:
                row_wp = ((row[wp_col] if len(row) > wp_col else "").strip() or "default")
                if row_wp != current_wp:
                    continue

            fn = row[fn_col] if fn_col is not None and fn_col < len(row) else ""
            ln = row[ln_col] if ln_col is not None and ln_col < len(row) else ""
            full = (fn + " " + ln).strip()
            return full or username

        return username
    except Exception:
        return username

def set_employee_field(username: str, field: str, value: str):
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
    current_wp = _session_workplace_id()

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

    current_wp = _session_workplace_id()

    rownum = None
    for i in range(1, len(vals)):
        row = vals[i]

        row_user = row[ucol].strip() if len(row) > ucol else ""
        row_wp = (row[wp_col].strip() if (wp_col is not None and len(row) > wp_col) else "") or "default"

        if row_user == username and row_wp == current_wp:
            rownum = i + 1
            break

    if not rownum:
        return

    if fn_col:
        employees_sheet.update_cell(rownum, fn_col, first or "")
    if ln_col:
        employees_sheet.update_cell(rownum, ln_col, last or "")

def update_employee_password(username: str, new_password: str) -> bool:
    vals = employees_sheet.get_all_values()
    if not vals:
        return False
    headers = vals[0]
    if "Username" not in headers or "Password" not in headers:
        return False
    ucol = headers.index("Username")
    wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
    pcol = headers.index("Password") + 1
    hashed = generate_password_hash(new_password)
    current_wp = _session_workplace_id()

    for i in range(1, len(vals)):
        row = vals[i]

        row_user = row[ucol].strip() if len(row) > ucol else ""
        row_wp = (row[wp_col].strip() if (wp_col is not None and len(row) > wp_col) else "") or "default"

        if row_user == username and row_wp == current_wp:
            employees_sheet.update_cell(i + 1, pcol, hashed)
            return True
    return False

def is_password_valid(stored: str, provided: str) -> bool:
    stored = stored or ""
    if stored.startswith("pbkdf2:") or stored.startswith("scrypt:"):
        return check_password_hash(stored, provided)
    return stored == provided

def migrate_password_if_plain(username: str, stored: str, provided: str):
    stored = stored or ""
    if stored and not (stored.startswith("pbkdf2:") or stored.startswith("scrypt:")):
        update_employee_password(username, provided)
def _ensure_onboarding_workplace_header():
    """Ensure Onboarding sheet has Workplace_ID column (append only; keep existing headers)."""
    if not onboarding_sheet:
        return
    try:
        vals = onboarding_sheet.get_all_values()
        if not vals:
            return
        headers = vals[0] or []
        if not headers or "Username" not in headers:
            return
        if "Workplace_ID" in headers:
            return

        new_headers = headers + ["Workplace_ID"]
        end_a1 = gspread.utils.rowcol_to_a1(1, len(new_headers))  # e.g. "K1"
        onboarding_sheet.update(f"A1:{end_a1}", [new_headers])  # e.g. "A1:K1"
    except Exception:
        return
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

    # Find row by (Username + Workplace_ID) if Workplace_ID exists
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

def get_onboarding_record(username: str):
    headers = get_sheet_headers(onboarding_sheet)
    vals = onboarding_sheet.get_all_values()
    if not vals or "Username" not in headers:
        return None

    ucol = headers.index("Username")
    wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
    current_wp = _session_workplace_id()

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
        ("Birth date", "BirthDate"),
        ("Phone", "PhoneNumber"),
        ("Email", "Email"),
        ("Street address", "StreetAddress"),
        ("City", "City"),
        ("Postcode", "Postcode"),
        ("Emergency contact", "EmergencyContactName"),
        ("Emergency phone", "EmergencyContactPhoneNumber"),
        ("Medical condition", "MedicalCondition"),
        ("Medical details", "MedicalDetails"),
        ("Position", "Position"),
        ("CSCS number", "CSCSNumber"),
        ("CSCS expiry", "CSCSExpiryDate"),
        ("Employment type", "EmploymentType"),
        ("Right to work UK", "RightToWorkUK"),
        ("National Insurance", "NationalInsurance"),
        ("UTR", "UTR"),
        ("Start date", "StartDate"),
        ("Bank account", "BankAccountNumber"),
        ("Sort code", "SortCode"),
        ("Account holder", "AccountHolderName"),
        ("Company trading name", "CompanyTradingName"),
        ("Company reg no.", "CompanyRegistrationNo"),
        ("Date of contract", "DateOfContract"),
        ("Site address", "SiteAddress"),
        ("Last saved", "SubmittedAt"),
    ]

    rows = []
    for label, key in fields:
        val = (rec.get(key, "") or "").strip()
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
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        return xff.split(",")[0].strip() or "unknown"
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
AUDIT_HEADERS = ["Timestamp","Actor","Action","Username","Date","Details","Workplace_ID"]
PAYROLL_HEADERS = ["WeekStart","WeekEnd","Username","Gross","Tax","Net","PaidAt","PaidBy","Paid","Workplace_ID"]

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

def log_audit(action: str, actor: str = "", username: str = "", date_str: str = "", details: str = ""):
    """Best-effort audit logging (never raises)."""
    if not audit_sheet:
        return
    try:
        _ensure_audit_headers()
        ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        audit_sheet.append_row(
            [ts, actor or "", action or "", username or "", date_str or "", details or "", _session_workplace_id()])
    except Exception:
        return

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
            end_col = gspread.utils.rowcol_to_a1(1, len(new_headers)).replace("1","")
            locations_sheet.update(f"A1:{end_col}1", [new_headers])
    except Exception:
        return

def _ensure_payroll_headers():
    try:
        vals = payroll_sheet.get_all_values()
        if not vals:
            payroll_sheet.append_row(PAYROLL_HEADERS)
            return
        headers = vals[0]
        if "WeekStart" not in headers:
            payroll_sheet.insert_row(PAYROLL_HEADERS, 1)
            return
        if headers[:len(PAYROLL_HEADERS)] != PAYROLL_HEADERS:
            new_headers = PAYROLL_HEADERS + [h for h in headers if h not in PAYROLL_HEADERS]
            end_col = gspread.utils.rowcol_to_a1(1, len(new_headers)).replace("1","")
            payroll_sheet.update(f"A1:{end_col}1", [new_headers])
    except Exception:
        return

def _append_paid_record_safe(week_start: str, week_end: str, username: str, gross: float, tax: float, net: float, paid_by: str):
    """Append a paid record for the week/user if not already paid."""
    try:
        _ensure_payroll_headers()
        paid, _ = _is_paid_for_week(week_start, week_end, username)
        if paid:
            return
        paid_at = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        payroll_sheet.append_row(
            [week_start, week_end, username, money(gross), money(tax), money(net), paid_at, paid_by, "",
             _session_workplace_id()])
        log_audit("MARK_PAID", actor=paid_by, username=username, date_str=f"{week_start}..{week_end}", details=f"gross={gross} tax={tax} net={net}")
    except Exception:
        return

def _is_paid_for_week(week_start: str, week_end: str, username: str) -> tuple[bool, str]:
    """Return (is_paid, paid_at)."""
    try:
        _ensure_payroll_headers()
        vals = payroll_sheet.get_all_values()
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
    return f"""
    <div class="bottomNav">
      <div class="navInner">
        <a class="navIcon {'active' if active=='home' else ''}" href="/" title="Dashboard">{_svg_grid()}</a>
        <a class="navIcon {'active' if active=='clock' else ''}" href="/clock" title="Clock">{_svg_clock()}</a>
        <a class="navIcon {'active' if active=='times' else ''}" href="/my-times" title="Time logs">{_svg_clipboard()}</a>
        <a class="navIcon {'active' if active=='reports' else ''}" href="/my-reports" title="Reports">{_svg_chart()}</a>
        <a class="navIcon" href="/logout" title="Logout" style="color: rgba(220,38,38,.92);">{_svg_logout()}</a>
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
    if role == "admin":
        items.insert(5, ("admin", "/admin", "Admin", _svg_grid()))

    links = []
    for key, href, label, icon in items:
        links.append(f"""
          <a class="sideItem nav-{key} {'active' if active==key else ''}" href="{href}">
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
      {bottom_nav(active if active in ('home','clock','times','reports','profile') else 'home', role)}
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
    if session.get("role") != "admin":
        return redirect(url_for("home"))

    flow = _make_oauth_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["oauth_state"] = state
    return redirect(auth_url)

@app.get("/oauth2callback")
def oauth2callback():
    gate = require_login()
    if gate:
        return gate
    if session.get("role") != "admin":
        return redirect(url_for("home"))

    returned_state = request.args.get("state")
    expected_state = session.get("oauth_state")
    if not expected_state or returned_state != expected_state:
        abort(400)
    session.pop("oauth_state", None)

    flow = _make_oauth_flow()
    flow.fetch_token(authorization_response=request.url)
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
    msg = ""
    csrf = get_csrf()

    if request.method == "POST":
        require_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        workplace_id = (request.form.get("workplace_id", "") or "").strip() or "default"
        # Allow entering Company_Name instead of Workplace_ID
        try:
            if settings_sheet and workplace_id:
                svals = settings_sheet.get_all_values()
                if svals and len(svals) > 1:
                    sh = svals[0]
                    i_wp = sh.index("Workplace_ID") if "Workplace_ID" in sh else None
                    i_name = sh.index("Company_Name") if "Company_Name" in sh else None
                    if i_wp is not None and i_name is not None:
                        typed = workplace_id.strip().lower()
                        for rr in svals[1:]:
                            nm = (rr[i_name] if i_name < len(rr) else "").strip().lower()
                            if nm and nm == typed:
                                workplace_id = ((rr[i_wp] if i_wp < len(rr) else "").strip() or workplace_id)
                                break
        except Exception:
            pass

        ip = _client_ip()

        allowed, retry_after = _login_rate_limit_check(ip)
        if not allowed:
            log_audit("LOGIN_LOCKED", actor=ip, username=username, date_str="", details=f"RetryAfter={retry_after}s")
            mins = max(1, int(math.ceil(retry_after / 60)))
            msg = f"Too many login attempts. Try again in {mins} minute(s)."
        else:
            ok_user = None
            # Force fresh read of Employees on login (avoid cached empty sheet after manual edits)
            try:
                sid = getattr(spreadsheet, "id", None)
                wid = getattr(employees_sheet, "id", None)
                if sid and wid:
                    _cache_invalidate_prefix((sid, wid))
            except Exception:
                pass
            for user in employees_sheet.get_all_records():
                row_user = (user.get("Username") or "").strip()
                row_wp = (user.get("Workplace_ID") or "").strip() or "default"  # backward-compatible
                if row_user == username and row_wp == workplace_id:
                    ok_user = user
                    break

            if ok_user and is_password_valid(ok_user.get("Password", ""), password):
                _login_rate_limit_clear(ip)

                migrate_password_if_plain(username, ok_user.get("Password", ""), password)
                session.clear()
                session["csrf"] = csrf
                session["username"] = username
                session["workplace_id"] = workplace_id
                session["role"] = (ok_user.get("Role", "employee") or "employee").strip().lower()
                session["rate"] = safe_float(ok_user.get("Rate", 0), 0.0)
                session["early_access"] = parse_bool(ok_user.get("EarlyAccess", False))
                return redirect(url_for("home"))

            _login_rate_limit_hit(ip)
            log_audit("LOGIN_FAIL", actor=ip, username=username, date_str="", details="Invalid username or password")
            msg = "Invalid login"

    html = f"""
    <div class="shell" style="grid-template-columns:1fr; max-width:560px;">
      <div class="main">
        <div class="headerTop">
          <div>
            <h1>WorkHours</h1>
            <p class="sub">Sign in</p>
          </div>
          <div class="badge">Secure</div>
        </div>

        <div class="card" style="padding:14px;">
          <form method="POST">
            <input type="hidden" name="csrf" value="{escape(csrf)}">
            <label class="sub">Username</label>
            <input class="input" name="username" required>
            <label class="sub" style="margin-top:10px; display:block;">Workplace ID</label>
            <input class="input" name="workplace_id" value="" placeholder="e.g. default" required>
            <label class="sub" style="margin-top:10px; display:block;">Password</label>
            <input class="input" type="password" name="password" required>
            <button class="btnSoft" type="submit" style="margin-top:12px;">Login</button>
          </form>
          {("<div class='message error'>" + escape(msg) + "</div>") if msg else ""}
        </div>
      </div>
    </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}{html}")

@app.get("/logout")
def logout_confirm():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    role = session.get("role", "employee")

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Logout</h1>
          <p class="sub">Are you sure you want to log out?</p>
        </div>
        <div class="badge {'admin' if role=='admin' else ''}">{escape(role.upper())}</div>
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
    rows = work_sheet.get_all_values()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()

    monday = today - timedelta(days=today.weekday())

    def week_key_for_n(n: int):
        d2 = monday - timedelta(days=7*n)
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
        if role != "admin" and row_user != username:
            continue

        # Workplace filter (prefer WorkHours row Workplace_ID)
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != current_wp:
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

    bars_html = "".join([f"<div class='bar' style='height:{int((g/max_g)*165)}px;'></div>" for g in weekly_gross])
    labels_html = "".join([f"<div style='width:16%;text-align:center;'>{escape(x)}</div>" for x in week_labels])

    prev_gross = round(sum(weekly_gross[:-1]), 2)
    curr_gross = round(weekly_gross[-1], 2)

    admin_item = ""
    if role == "admin":
        admin_item = f"""
        <a class="menuItem" href="/admin">
          <div class="menuLeft"><div class="icoBox">{_svg_grid()}</div><div class="menuText">Admin</div></div>
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

        if role != "admin" and row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != current_wp:
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
                <div>{escape(rr['hours'])}</div>
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

        if role != "admin" and row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != current_wp:
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

    is_clocked_in = bool(find_open_shift(rows, username))
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
                    if row_wp != current_wp:
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
    content = f"""
      <div class="headerTop">
        <div>
          <h1>Dashboard</h1>
          <p class="sub">Welcome, {escape(display_name)}</p>
        </div>
        <div class="badge {'admin' if role=='admin' else ''}">{escape(role.upper())}</div>
      </div>
<div class="kpiRow">
  <div class="card kpi kpiFancy">
    <div class="kpiTop">
      <p class="label">Previous Gross</p>
      <span class="chip">Week total</span>
    </div>
    <p class="value">{escape(currency)}{money(prev_gross)}</p>
    <p class="sub">Sum of prior 4 weeks</p>
  </div>

  <div class="card kpi kpiFancy kpiPrimary">
    <div class="kpiTop">
      <p class="label">Current Gross</p>
      <span class="chip {'ok' if curr_gross >= prev_gross else 'warn'}">
        {'▲' if curr_gross >= prev_gross else '▼'}
        {money(((curr_gross - prev_gross) / (prev_gross if prev_gross > 0 else 1.0)) * 100.0)}%
      </span>
    </div>
    <p class="value">{escape(currency)}{money(curr_gross)}</p>
    <p class="sub">This week (so far)</p>
  </div>
</div>

                  <div class="card graphCard">
        <div class="graphTop">
          <div>
            <div class="graphTitle">Weekly Gross</div>
            <div class="sub">Last 5 weeks performance</div>
          </div>
          <div class="graphRange">Weeks {escape(week_labels[0])} – {escape(week_labels[-1])}</div>
        </div>

        <div class="graphShell">
          <div class="bars">
            {''.join([
              f"""
              <div class="barCol">
                <div class="barValue">{escape(currency)}{money(g)}</div>
                <div class="barTrack">
                  <div class="bar" style="height:{int((g/max_g)*165)}px;"></div>
                </div>
              </div>
              """
              for g in weekly_gross
            ])}
          </div>

          <div class="barLabels">
            {''.join([f"<div>{escape(x)}</div>" for x in week_labels])}
          </div>

          <div class="graphMeta">
            <div class="graphStat">
              <div class="k">Previous 4 Weeks</div>
              <div class="v">{escape(currency)}{money(prev_gross)}</div>
            </div>
            <div class="graphStat">
              <div class="k">Current Week</div>
              <div class="v">{escape(currency)}{money(curr_gross)}</div>
            </div>
            <div class="graphStat">
              <div class="k">Best Week</div>
              <div class="v">{escape(currency)}{money(max(weekly_gross) if weekly_gross else 0)}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="dashboardLower">
                <div class="card quickCard">
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
              <div class="miniText">{round(today_hours, 2)}</div>
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
              <div class="miniText">{round(week_hours, 2)}</div>
            </div>

            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_doc()}</div>
                <div class="miniText">Days Logged</div>
              </div>
              <div class="miniText">{len(week_days)}</div>
            </div>
          </div>

                <div class="dashboardBottom">
                    <div class="card activityCard">
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

          <div class="card sideInfoCard">
            <div class="sectionHead">
              <div class="sectionHeadLeft">
                <div class="sectionIcon">{_svg_grid()}</div>
                <div>
                  <h2 style="margin:0;">Business Snapshot</h2>
                  <p class="sub" style="margin:4px 0 0 0;">Current workplace overview.</p>
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
          </div>
        </div>

      <div class="card menu dashboardMainMenu">
        <a class="menuItem active" href="/clock">
          <div class="menuLeft"><div class="icoBox">{_svg_clock()}</div><div class="menuText">Clock In & Out</div></div>
          <div class="chev">›</div>
        </a>
        <a class="menuItem" href="/my-times">
          <div class="menuLeft"><div class="icoBox">{_svg_clipboard()}</div><div class="menuText">Time logs</div></div>
          <div class="chev">›</div>
        </a>
        <a class="menuItem" href="/my-reports">
          <div class="menuLeft"><div class="icoBox">{_svg_chart()}</div><div class="menuText">Timesheets</div></div>
          <div class="chev">›</div>
        </a>
        <a class="menuItem" href="/onboarding">
          <div class="menuLeft"><div class="icoBox">{_svg_doc()}</div><div class="menuText">Starter Form</div></div>
          <div class="chev">›</div>
        </a>
        {admin_item}
        <a class="menuItem" href="/password">
          <div class="menuLeft"><div class="icoBox">{_svg_user()}</div><div class="menuText">Profile</div></div>
          <div class="chev">›</div>
        </a>
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

    rate = safe_float(session.get("rate", 0), 0.0)
    early_access = bool(session.get("early_access", False))

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

        # require geolocation for BOTH clock in and clock out
        lat_v = _read_float("lat")
        lon_v = _read_float("lon")
        acc_v = _read_float("acc")

        try:
            ok_loc, cfg, dist_m = _validate_user_location(username, lat_v, lon_v, acc_v)

            if not ok_loc:
                # Build a clean error message
                if not site_cfg and not cfg.get("radius"):
                    msg = "Location system is not configured. Ask Admin to create Locations sheet and set your Site."
                elif lat_v is None or lon_v is None:
                    msg = "Location is required. Please allow location access and try again."
                else:
                    msg = f"Outside site radius. Distance: {int(dist_m)}m (limit {int(cfg['radius'])}m) • Site: {cfg['name']}"
                msg_class = "message error"
            else:
                rows = work_sheet.get_all_values()

                if action == "in":
                    if has_any_row_today(rows, username, today_str):
                        msg = "You already clocked in today (1 per day)."
                        msg_class = "message error"
                    elif find_open_shift(rows, username):
                        msg = "You are already clocked in."
                        msg_class = "message error"
                    else:
                        cin = normalized_clock_in_time(now, early_access)

                        # ✅ Append row INCLUDING Workplace_ID so _find_workhours_row_by_user_date can find it
                        headers_now = work_sheet.row_values(1)  # fresh header row

                        new_row = [username, today_str, cin, "", "",
                                   ""]  # Username, Date, ClockIn, ClockOut, Hours, Pay

                        if headers_now and "Workplace_ID" in headers_now:
                            wp_idx = headers_now.index("Workplace_ID")
                            if len(new_row) <= wp_idx:
                                new_row += [""] * (wp_idx + 1 - len(new_row))
                            new_row[wp_idx] = _session_workplace_id()

                        # Pad to header width (prevents misalignment if sheet has extra columns)
                        if headers_now and len(new_row) < len(headers_now):
                            new_row += [""] * (len(headers_now) - len(new_row))

                        _gs_write_with_retry(lambda: work_sheet.append_row(new_row, value_input_option="USER_ENTERED"))

                        # Find the row we just added and store geo fields
                        vals = work_sheet.get_all_values()
                        rownum = _find_workhours_row_by_user_date(vals, username, today_str)
                        if rownum:
                            headers = vals[0] if vals else []
                            def _col(name):
                                return headers.index(name) + 1 if name in headers else None

                            import copy  # put this at the TOP of the file with your other imports

                            updates = []
                            for k, v in [
                                ("InLat", lat_v), ("InLon", lon_v), ("InAcc", acc_v),
                                ("InSite", cfg.get("name", "")), ("InDistM", int(dist_m)),
                                ("Workplace_ID", _session_workplace_id()),
                            ]:
                                c = _col(k)
                                if c:
                                    updates.append({
                                        "range": gspread.utils.rowcol_to_a1(rownum, c),
                                        "values": [["" if v is None else v]],
                                    })

                            # ✅ IMPORTANT: batch_update must be OUTSIDE the loop
                            if updates:
                                _gs_write_with_retry(lambda: work_sheet.batch_update(copy.deepcopy(updates)))
                    msg = f"Clocked In • {cfg['name']} ({int(dist_m)}m)"
                    if (not early_access) and (now.time() < CLOCKIN_EARLIEST):
                        msg = f"Clocked In (counted from 08:00) • {cfg['name']} ({int(dist_m)}m)"

                elif action == "out":
                    osf = find_open_shift(rows, username)
                    if not osf:
                        msg = "No active shift found."
                        msg_class = "message error"
                    else:
                        i, d, t = osf
                        cin_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
                        raw_hours = max(0.0, (now - cin_dt).total_seconds() / 3600.0)
                        hours_rounded = round(_apply_unpaid_break(raw_hours), 2)
                        pay = round(hours_rounded * float(rate), 2)

                        sheet_row = i + 1  # find_open_shift returns index in rows list
                        cout = now.strftime("%H:%M:%S")

                        updates = [
                            {
                                "range": f"{gspread.utils.rowcol_to_a1(sheet_row, COL_OUT + 1)}:{gspread.utils.rowcol_to_a1(sheet_row, COL_PAY + 1)}",
                                "values": [[cout, hours_rounded, pay]],
                            }
                        ]

                        # Store geo fields (clock-out) in the same batch update (if headers exist)
                        vals = work_sheet.get_all_values()
                        headers = vals[0] if vals else []
                        def _col(name):
                            return headers.index(name) + 1 if name in headers else None

                        for k, v in [
                            ("OutLat", lat_v), ("OutLon", lon_v), ("OutAcc", acc_v),
                            ("OutSite", cfg.get("name", "")), ("OutDistM", int(dist_m)),
                        ]:
                            c = _col(k)
                            if c:
                                updates.append({"range": gspread.utils.rowcol_to_a1(sheet_row, c), "values": [["" if v is None else str(v)]]})

                        import copy
                        if updates:
                            _gs_write_with_retry(lambda: work_sheet.batch_update(copy.deepcopy(updates)))
                    msg = f"Clocked Out • {cfg['name']} ({int(dist_m)}m)"

                else:
                    msg = "Invalid action."
                    msg_class = "message error"
        except Exception as e:
            app.logger.exception('Clock POST failed')
            msg = 'Internal error while saving. Please refresh and try again.'
            msg_class = 'message error'


    # Active shift timer
    rows2 = work_sheet.get_all_values()
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
        <div class="timerSub">Active session started</div>
        <div class="timerBig" id="timerDisplay">00:00:00</div>
        <div style="margin-top:8px;">
          <span class="chip ok" id="otChip">Normal</span>
        </div>
        <div class="timerSub">Start: {escape(active_start_label)} </div>
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
        <div class="timerSub">No active session</div>
        <div class="timerBig">00:00:00</div>
        <div class="timerSub">Clock in to start the live timer.</div>
        """

    # Map config for front-end (if site configured)
    if site_cfg:
        site_json = json.dumps({"name": site_cfg["name"], "lat": site_cfg["lat"], "lon": site_cfg["lon"], "radius": site_cfg["radius"]})
    else:
        site_json = json.dumps(None)

    leaflet_tags = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin=""/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
"""

    content = f"""
      {leaflet_tags}
      <div class="headerTop">
        <div>
          <h1>Clock In & Out</h1>
          <p class="sub">{escape(display_name)} • Location required</p>
        </div>
        <div class="badge {'admin' if role=='admin' else ''}">{escape(role.upper())}</div>
      </div>

      {("<div class='" + msg_class + "'>" + escape(msg) + "</div>") if msg else ""}
<div class="card clockCard">
  {timer_html}


  <div class="sub" id="geoStatus" style="margin-top:10px;">📍 Waiting for location…</div>

        <div id="map" style="margin-top:10px; height:240px; border-radius:18px; overflow:hidden; border:1px solid rgba(11,18,32,.10);"></div>

        <form method="POST" class="actionRow" id="geoClockForm" style="margin-top:12px;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <input type="hidden" name="action" id="geoAction" value="">
          <input type="hidden" name="lat" id="geoLat" value="">
          <input type="hidden" name="lon" id="geoLon" value="">
          <input type="hidden" name="acc" id="geoAcc" value="">
          <button class="btn btnIn" type="button" id="btnClockIn">Clock In</button>
          <button class="btn btnOut" type="button" id="btnClockOut">Clock Out</button>
        </form>

        <a href="/my-times" style="display:block;margin-top:12px;">
          <button class="btnSoft" type="button">View my time logs</button>
        </a>
      </div>

      <script>
        (function(){{
          const SITE = {site_json};
          const statusEl = document.getElementById("geoStatus");
          const form = document.getElementById("geoClockForm");
          const act = document.getElementById("geoAction");
          const latEl = document.getElementById("geoLat");
          const lonEl = document.getElementById("geoLon");
          const accEl = document.getElementById("geoAcc");

          const btnIn = document.getElementById("btnClockIn");
          const btnOut = document.getElementById("btnClockOut");

          function setDisabled(v){{
            btnIn.disabled = v;
            btnOut.disabled = v;
            btnIn.style.opacity = v ? "0.6" : "1";
            btnOut.style.opacity = v ? "0.6" : "1";
          }}

          // Map
          let map = null;
          let siteMarker = null;
          let radiusCircle = null;
          let youMarker = null;

          function initMap(){{
            const start = SITE ? [SITE.lat, SITE.lon] : [51.505, -0.09];
            map = L.map("map", {{ zoomControl: true }}).setView(start, SITE ? 16 : 5);
            L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
              maxZoom: 19,
              attribution: "&copy; OpenStreetMap"
            }}).addTo(map);

            if(SITE){{
              siteMarker = L.marker([SITE.lat, SITE.lon]).addTo(map).bindPopup(SITE.name);
              radiusCircle = L.circle([SITE.lat, SITE.lon], {{
                radius: SITE.radius
              }}).addTo(map);
            }}
          }}

          function haversineMeters(lat1, lon1, lat2, lon2){{
            const R = 6371000;
            const toRad = (x)=> x * Math.PI / 180;
            const dLat = toRad(lat2-lat1);
            const dLon = toRad(lon2-lon1);
            const a = Math.sin(dLat/2)*Math.sin(dLat/2) +
                      Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*
                      Math.sin(dLon/2)*Math.sin(dLon/2);
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            return R * c;
          }}

          function updateStatus(lat, lon, acc){{
            if(!SITE){{
              statusEl.textContent = "📍 Location captured (no site configured)";
              return;
            }}
            const dist = haversineMeters(lat, lon, SITE.lat, SITE.lon);
            const ok = dist <= SITE.radius;
            statusEl.textContent = ok
              ? `📍 Location OK: ${{SITE.name}} (${{Math.round(dist)}}m)`
              : `📍 Outside radius: ${{Math.round(dist)}}m (limit ${{Math.round(SITE.radius)}}m)`;
            statusEl.style.color = ok ? "var(--green)" : "var(--red)";
          }}

          function updateYouMarker(lat, lon){{
            if(!map) return;
            if(!youMarker){{
              youMarker = L.marker([lat, lon]).addTo(map);
            }} else {{
              youMarker.setLatLng([lat, lon]);
            }}
          }}

          function requestLocationAndSubmit(actionValue){{
            if(!navigator.geolocation){{
              alert("Geolocation is not supported on this device/browser.");
              return;
            }}
            setDisabled(true);
            statusEl.style.color = "var(--muted)";
            statusEl.textContent = "📍 Getting your location…";

            navigator.geolocation.getCurrentPosition((pos)=>{{
              const lat = pos.coords.latitude;
              const lon = pos.coords.longitude;
              const acc = pos.coords.accuracy;

              latEl.value = lat;
              lonEl.value = lon;
              accEl.value = acc;

              updateStatus(lat, lon, acc);
              updateYouMarker(lat, lon);

              act.value = actionValue;
              form.submit();
            }}, (err)=>{{
              console.log(err);
              alert("Location is required to clock in/out. Please allow location permission and try again.");
              statusEl.textContent = "📍 Location required. Please allow permission.";
              statusEl.style.color = "var(--red)";
              setDisabled(false);
            }}, {{
              enableHighAccuracy: true,
              timeout: 12000,
              maximumAge: 0
            }});
          }}

          initMap();

          // Try to show status + marker before pressing buttons
          if(navigator.geolocation){{
            navigator.geolocation.getCurrentPosition((pos)=>{{
              const lat = pos.coords.latitude;
              const lon = pos.coords.longitude;
              const acc = pos.coords.accuracy;
              updateStatus(lat, lon, acc);
              updateYouMarker(lat, lon);
            }}, ()=>{{
              statusEl.textContent = "📍 Location required. Please allow permission.";
              statusEl.style.color = "var(--red)";
            }}, {{ enableHighAccuracy:true, timeout: 8000, maximumAge: 0 }});
          }}

          btnIn.addEventListener("click", ()=> requestLocationAndSubmit("in"));
          btnOut.addEventListener("click", ()=> requestLocationAndSubmit("out"));
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
    body = []
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if len(r) <= COL_USER:
            continue
        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        # Workplace filter (only if WorkHours has Workplace_ID column)
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != current_wp:
                continue
        else:
            # Backward compat if sheet has no Workplace_ID column
            if not user_in_same_workplace(row_user):
                continue


        body.append(
            f"<tr><td>{escape(r[COL_DATE])}</td><td>{escape(r[COL_IN])}</td>"
            f"<td>{escape(r[COL_OUT])}</td><td class='num'>{escape(r[COL_HOURS])}</td><td class='num'>{escape(currency)}{escape(r[COL_PAY])}</td></tr>"
        )
    table = "".join(body) if body else "<tr><td colspan='5'>No records yet.</td></tr>"

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Time logs</h1>
          <p class="sub">{escape(display_name)} • Clock history</p>
        </div>
        <div class="badge {'admin' if role=='admin' else ''}">{escape(role.upper())}</div>
      </div>

      <div class="card payrollShell" style="padding:12px;">
        <div class="tablewrap">
          <table style="min-width:640px;">
            <thead><tr><th>Date</th><th>Clock In</th><th>Clock Out</th><th class="num" style="text-align:center;">Hours</th>
<th class="num" style="text-align:center;">Pay</th>
</tr></thead>
            <tbody>{table}</tbody>
          </table>
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

    now = datetime.now(TZ)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())

    rows = work_sheet.get_all_values()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    daily_hours = daily_pay = 0.0
    weekly_hours = weekly_pay = 0.0
    monthly_hours = monthly_pay = 0.0

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if (r[COL_USER] or "").strip() != username:
            continue
        # Workplace filter (only if WorkHours has Workplace_ID column)
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != current_wp:
                continue
        if not r[COL_HOURS]:
            continue
        try:
            d = datetime.strptime(r[COL_DATE], "%Y-%m-%d").date()
        except Exception:
            continue

        hrs = safe_float(r[COL_HOURS], 0.0)
        pay = safe_float(r[COL_PAY], 0.0)

        if d == today:
            daily_hours += hrs
            daily_pay += pay
        if d >= week_start:
            weekly_hours += hrs
            weekly_pay += pay
        if d.year == today.year and d.month == today.month:
            monthly_hours += hrs
            monthly_pay += pay

    def gross_tax_net(gross):
        settings = get_company_settings()
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)
        return round(gross, 2), tax, net

    d_g, d_t, d_n = gross_tax_net(daily_pay)
    w_g, w_t, w_n = gross_tax_net(weekly_pay)
    m_g, m_t, m_n = gross_tax_net(monthly_pay)
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    content = f"""
      <div class="headerTop">
        <div>
          <h1>Timesheets</h1>
          <p class="sub">{escape(display_name)} • Totals + tax + net</p>
        </div>
        <div class="badge {'admin' if role=='admin' else ''}">{escape(role.upper())}</div>
      </div>

      <div class="kpiRow">
        <div class="card kpi">
          <p class="label">Today Gross</p>
          <p class="value">{escape(currency)}{money(d_g)}</p>
          <p class="sub">Hours: {round(daily_hours,2)} • Tax: {escape(currency)}{money(d_t)} • Net: {escape(currency)}{money(d_n)}</p>
        </div>
        <div class="card kpi">
          <p class="label">This Week Gross</p>
          <p class="value">{escape(currency)}{money(w_g)}</p>
          <p class="sub">Hours: {round(weekly_hours,2)} • Tax: {escape(currency)}{money(w_t)} • Net: {escape(currency)}{money(w_n)}</p>
        </div>
      </div>

      <div class="card kpi" style="margin-top:12px;">
        <p class="label">This Month Gross</p>
        <p class="value">{escape(currency)}{money(m_g)}</p>
<p class="sub">Hours: {round(monthly_hours,2)} • Tax: {escape(currency)}{money(m_t)} • Net: {escape(currency)}{money(m_n)}</p>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("reports", role, content))


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
        typed = dict(request.form)
        submit_type = request.form.get("submit_type", "draft")
        is_final = (submit_type == "final")

        def g(name): return (request.form.get(name, "") or "").strip()

        first = g("first"); last = g("last"); birth = g("birth")
        phone_cc = g("phone_cc") or "+44"; phone_num = g("phone_num")
        street = g("street"); city = g("city"); postcode = g("postcode")
        email = g("email")
        ec_name = g("ec_name"); ec_cc = g("ec_cc") or "+44"; ec_phone = g("ec_phone")
        medical = g("medical"); medical_details = g("medical_details")
        position = g("position"); cscs_no = g("cscs_no"); cscs_exp = g("cscs_exp")
        emp_type = g("emp_type"); rtw = g("rtw")
        ni = g("ni"); utr = g("utr"); start_date = g("start_date")
        acc_no = g("acc_no"); sort_code = g("sort_code"); acc_name = g("acc_name")
        comp_trading = g("comp_trading"); comp_reg = g("comp_reg")
        contract_date = g("contract_date"); site_address = g("site_address")
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

            if not _load_drive_token():
                missing.append("Upload system not connected (admin must click Connect Drive)")

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
    if role == "admin":
        drive_hint = "<p class='sub'>Admin: if uploads fail, click <a href='/connect-drive' style='color:var(--navy);font-weight:600;'>Connect Drive</a> once.</p>"

    return f"""
      <div class="headerTop">
        <div>
          <h1>Starter Form</h1>
          <p class="sub">{escape(display_name)} • Save Draft anytime • Submit Final when complete</p>
          {drive_hint}
        </div>
        <div class="badge {'admin' if role=='admin' else ''}">{escape(role.upper())}</div>
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
              <input class="input {bad('first')}" name="first" value="{escape(val('first','FirstName'))}">
            </div>
            <div>
              <label class="sub {bad_label('last')}">Last Name</label>
              <input class="input {bad('last')}" name="last" value="{escape(val('last','LastName'))}">
            </div>
          </div>

          <label class="sub {bad_label('birth')}" style="margin-top:10px; display:block;">Birth Date</label>
          <input class="input {bad('birth')}" type="date" name="birth" value="{escape(val('birth','BirthDate'))}">

          <label class="sub {bad_label('phone_num')}" style="margin-top:10px; display:block;">Phone Number</label>
          <div class="row2">
            <input class="input" name="phone_cc" value="{escape(val('phone_cc','PhoneCountryCode') or '+44')}">
            <input class="input {bad('phone_num')}" name="phone_num" value="{escape(val('phone_num','PhoneNumber'))}">
          </div>

          <h2 style="margin-top:14px;">Address</h2>
          <input class="input" name="street" placeholder="Street Address" value="{escape(val('street','StreetAddress'))}">
          <div class="row2">
            <input class="input" name="city" placeholder="City" value="{escape(val('city','City'))}">
            <input class="input" name="postcode" placeholder="Postcode" value="{escape(val('postcode','Postcode'))}">
          </div>

          <div class="row2">
            <div>
              <label class="sub {bad_label('email')}">Email</label>
              <input class="input {bad('email')}" name="email" type="email" value="{escape(val('email','Email'))}">
            </div>
            <div>
              <label class="sub {bad_label('ec_name')}">Emergency Contact Name</label>
              <input class="input {bad('ec_name')}" name="ec_name" value="{escape(val('ec_name','EmergencyContactName'))}">
            </div>
          </div>

          <label class="sub {bad_label('ec_phone')}" style="margin-top:10px; display:block;">Emergency Contact Phone</label>
          <div class="row2">
            <input class="input" name="ec_cc" value="{escape(val('ec_cc','EmergencyContactPhoneCountryCode') or '+44')}">
            <input class="input {bad('ec_phone')}" name="ec_phone" value="{escape(val('ec_phone','EmergencyContactPhoneNumber'))}">
          </div>

          <h2 style="margin-top:14px;">Medical</h2>
          <label class="sub {bad_label('medical')}">Do you have any medical condition that may affect you at work?</label>
          <div class="row2">
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="medical" value="no" {checked_radio('medical','MedicalCondition','no')}> No
            </label>
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="medical" value="yes" {checked_radio('medical','MedicalCondition','yes')}> Yes
            </label>
          </div>
          <label class="sub" style="margin-top:10px; display:block;">Details</label>
          <input class="input" name="medical_details" value="{escape(val('medical_details','MedicalDetails'))}">

          <h2 style="margin-top:14px;">Position</h2>
          <div class="row2">
            <label class="sub {bad_label('position')}" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Bricklayer" {"checked" if val('position','Position')=='Bricklayer' else ""}> Bricklayer
            </label>
            <label class="sub {bad_label('position')}" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Labourer" {"checked" if val('position','Position')=='Labourer' else ""}> Labourer
            </label>
            <label class="sub {bad_label('position')}" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Fixer" {"checked" if val('position','Position')=='Fixer' else ""}> Fixer
            </label>
            <label class="sub {bad_label('position')}" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Supervisor/Foreman" {"checked" if val('position','Position')=='Supervisor/Foreman' else ""}> Supervisor/Foreman
            </label>
          </div>

          <div class="row2">
            <div>
              <label class="sub {bad_label('cscs_no')}">CSCS Number</label>
              <input class="input {bad('cscs_no')}" name="cscs_no" value="{escape(val('cscs_no','CSCSNumber'))}">
            </div>
            <div>
              <label class="sub {bad_label('cscs_exp')}">CSCS Expiry</label>
              <input class="input {bad('cscs_exp')}" type="date" name="cscs_exp" value="{escape(val('cscs_exp','CSCSExpiryDate'))}">
            </div>
          </div>

          <label class="sub {bad_label('emp_type')}" style="margin-top:10px; display:block;">Employment Type</label>
          <select class="input {bad('emp_type')}" name="emp_type">
            <option value="">Please Select</option>
            <option value="Self-employed" {selected('emp_type','EmploymentType','Self-employed')}>Self-employed</option>
            <option value="Ltd Company" {selected('emp_type','EmploymentType','Ltd Company')}>Ltd Company</option>
            <option value="Agency" {selected('emp_type','EmploymentType','Agency')}>Agency</option>
            <option value="PAYE" {selected('emp_type','EmploymentType','PAYE')}>PAYE</option>
          </select>

          <label class="sub {bad_label('rtw')}" style="margin-top:10px; display:block;">Right to work in UK?</label>
          <div class="row2">
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="rtw" value="yes" {checked_radio('rtw','RightToWorkUK','yes')}> Yes
            </label>
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="rtw" value="no" {checked_radio('rtw','RightToWorkUK','no')}> No
            </label>
          </div>

          <div class="row2">
            <div>
              <label class="sub {bad_label('ni')}">National Insurance</label>
              <input class="input {bad('ni')}" name="ni" value="{escape(val('ni','NationalInsurance'))}">
            </div>
            <div>
              <label class="sub {bad_label('utr')}">UTR</label>
              <input class="input {bad('utr')}" name="utr" value="{escape(val('utr','UTR'))}">
            </div>
          </div>

          <label class="sub {bad_label('start_date')}" style="margin-top:10px; display:block;">Start Date</label>
          <input class="input {bad('start_date')}" type="date" name="start_date" value="{escape(val('start_date','StartDate'))}">

          <h2 style="margin-top:14px;">Bank details</h2>
          <div class="row2">
            <div>
              <label class="sub {bad_label('acc_no')}">Account Number</label>
              <input class="input {bad('acc_no')}" name="acc_no" value="{escape(val('acc_no','BankAccountNumber'))}">
            </div>
            <div>
              <label class="sub {bad_label('sort_code')}">Sort Code</label>
              <input class="input {bad('sort_code')}" name="sort_code" value="{escape(val('sort_code','SortCode'))}">
            </div>
          </div>
          <label class="sub {bad_label('acc_name')}" style="margin-top:10px; display:block;">Account Holder Name</label>
          <input class="input {bad('acc_name')}" name="acc_name" value="{escape(val('acc_name','AccountHolderName'))}">

          <h2 style="margin-top:14px;">Company details</h2>
          <input class="input" name="comp_trading" placeholder="Trading name" value="{escape(val('comp_trading','CompanyTradingName'))}">
          <input class="input" name="comp_reg" placeholder="Company reg no." value="{escape(val('comp_reg','CompanyRegistrationNo'))}">

          <h2 style="margin-top:14px;">Contract & site</h2>
          <div class="row2">
            <div>
              <label class="sub {bad_label('contract_date')}">Date of Contract</label>
              <input class="input {bad('contract_date')}" type="date" name="contract_date" value="{escape(val('contract_date','DateOfContract'))}">
            </div>
            <div>
              <label class="sub {bad_label('site_address')}">Site address</label>
              <input class="input {bad('site_address')}" name="site_address" value="{escape(val('site_address','SiteAddress'))}">
            </div>
          </div>

          <h2 style="margin-top:14px;">Upload documents</h2>
          <p class="sub">Draft: optional uploads. Final: all 4 required. (If Final fails, re-select files.)</p>

          <div class="uploadTitle {bad_label('passport_file')}">Passport or Birth Certificate</div>
          <input class="input {bad('passport_file')}" type="file" name="passport_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('PassportOrBirthCertLink',''))}</p>

          <div class="uploadTitle {bad_label('cscs_file')}">CSCS Card (front & back)</div>
          <input class="input {bad('cscs_file')}" type="file" name="cscs_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('CSCSFrontBackLink',''))}</p>

          <div class="uploadTitle {bad_label('pli_file')}">Public Liability Insurance</div>
          <input class="input {bad('pli_file')}" type="file" name="pli_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('PublicLiabilityLink',''))}</p>

          <div class="uploadTitle {bad_label('share_file')}">Share Code / Confirmation</div>
          <input class="input {bad('share_file')}" type="file" name="share_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('ShareCodeLink',''))}</p>

          <h2 style="margin-top:14px;">Contract</h2>
          <div class="contractBox">{escape(CONTRACT_TEXT)}</div>

          <label class="sub {bad_label('contract_accept')}" style="display:flex; gap:10px; align-items:center; margin-top:10px;">
            <input type="checkbox" name="contract_accept" value="yes" {"checked" if typed.get('contract_accept')=='yes' else ""}>
            I have read and accept the contract terms (required for Final)
          </label>

          <label class="sub {bad_label('signature_name')}" style="margin-top:10px; display:block;">Signature (type your full name)</label>
          <input class="input {bad('signature_name')}" name="signature_name" value="{escape(val('signature_name','SignatureName'))}">

          <div class="row2" style="margin-top:14px;">
            <button class="btnSoft" name="submit_type" value="draft" type="submit">Save Draft</button>
            <button class="btnSoft" name="submit_type" value="final" type="submit" style="background:rgba(10,42,94,.14);">Submit Final</button>
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
        for user in employees_sheet.get_all_records():
            if not _same_workplace(user):
                continue
            if user.get("Username") == username:
                stored_pw = user.get("Password", "")
                break

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
      <div class="headerTop">
        <div>
          <h1>Profile</h1>
          <p class="sub">{escape(display_name)}</p>
        </div>
        <div class="badge {'admin' if role=='admin' else ''}">{escape(role.upper())}</div>
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
    """Fetch hourly rate for a username from Employees sheet; fall back to session rate or 0."""
    try:
        # Prefer Employees sheet (source of truth)
        vals = employees_sheet.get_all_values()
        if not vals:
            return safe_float(session.get("rate", 0), 0.0)
        headers = vals[0]
        if "Username" not in headers:
            return safe_float(session.get("rate", 0), 0.0)
        ucol = headers.index("Username")
        rcol = headers.index("Rate") if "Rate" in headers else None
        wpcol = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
        current_wp = _session_workplace_id()
        for r in vals[1:]:
            if len(r) <= ucol:
                continue
            if (r[ucol] or "").strip() != (username or "").strip():
                continue

            # Enforce workplace match ONLY if Employees sheet has Workplace_ID
            if wpcol is not None:
                row_wp = (r[wpcol] if len(r) > wpcol else "").strip() or "default"
                if row_wp != current_wp:
                    continue

            if rcol is not None and rcol < len(r):
                return safe_float(r[rcol], default=0.0)
            break
    except Exception:
        pass
    return safe_float(session.get("rate", 0), 0.0)

def _get_open_shifts() -> list[dict]:
    """Return currently open shifts (ClockOut empty) with display metadata for Admin dashboard."""
    out = []
    try:
        rows = work_sheet.get_all_values()
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
        vals_emp = employees_sheet.get_all_values()
        headers_emp = vals_emp[0] if vals_emp else []
        ucol = headers_emp.index("Username") if "Username" in headers_emp else None
        wp_col = headers_emp.index("Workplace_ID") if "Workplace_ID" in headers_emp else None
        current_wp = _session_workplace_id()

        if ucol is not None:
            for r in vals_emp[1:]:
                u = (r[ucol] if ucol < len(r) else "").strip()
                if not u:
                    continue
                if wp_col is not None:
                    row_wp = (r[wp_col] if wp_col < len(r) else "").strip() or "default"
                    if row_wp != current_wp:
                        continue
                employees_total += 1
    except Exception:
        employees_total = 0

    try:
        vals_onb = onboarding_sheet.get_all_values()
        headers_onb = vals_onb[0] if vals_onb else []
        ucol_onb = headers_onb.index("Username") if "Username" in headers_onb else None
        wp_col_onb = headers_onb.index("Workplace_ID") if "Workplace_ID" in headers_onb else None
        current_wp = _session_workplace_id()

        if ucol_onb is not None:
            for r in vals_onb[1:]:
                u = (r[ucol_onb] if ucol_onb < len(r) else "").strip()
                if not u:
                    continue
                if wp_col_onb is not None:
                    row_wp = (r[wp_col_onb] if wp_col_onb < len(r) else "").strip() or "default"
                    if row_wp != current_wp:
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
                    <div class="card adminSectionCard" style="margin-top:12px;">
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
            <div class="tablewrap" style="margin-top:12px;">
              <table style="min-width:1100px;">
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
          <div class="card adminSectionCard" style="margin-top:12px;">
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
        vals_emp = employees_sheet.get_all_values()
        headers_emp = vals_emp[0] if vals_emp else []
        ucol = headers_emp.index("Username") if "Username" in headers_emp else 0
        wp_col = headers_emp.index("Workplace_ID") if "Workplace_ID" in headers_emp else None
        current_wp = _session_workplace_id()

        for r in vals_emp[1:]:
            u = (r[ucol] if ucol < len(r) else "").strip()
            if not u:
                continue

            # Tenant-safe: filter by Employees row Workplace_ID
            if wp_col is not None:
                row_wp = (r[wp_col] if wp_col < len(r) else "").strip() or "default"
                if row_wp != current_wp:
                    continue

            employee_options += f"<option value='{escape(u)}'>{escape(u)}</option>"
    except Exception:
        employee_options = ""

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Admin</h1>
          <p class="sub">Payroll + onboarding</p>
        </div>
        <div class="badge admin">ADMIN</div>
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

            <div class="card menu" style="padding:14px;">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap;">
          <div>
            <h2>Admin tools</h2>
            <p class="sub">Manage payroll, people, sites, onboarding and drive access.</p>
          </div>
          <div class="badge admin">Control Centre</div>
        </div>

        <div class="adminGrid" style="margin-top:12px;">
          <a class="adminToolCard payroll" href="/admin/payroll">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_chart()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Payroll Report</div>
            <div class="adminToolSub">Weekly payroll, tax, net pay and paid status.</div>
          </a>

          <a class="adminToolCard company" href="/admin/company">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_doc()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Company Settings</div>
            <div class="adminToolSub">Change workplace name and company-level settings.</div>
          </a>

          <a class="adminToolCard onboarding" href="/admin/onboarding">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_doc()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Onboarding</div>
            <div class="adminToolSub">Review starter forms, documents and contract details.</div>
          </a>

          <a class="adminToolCard locations" href="/admin/locations">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_grid()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Locations</div>
            <div class="adminToolSub">Manage geo-fence sites and allowed clock-in zones.</div>
          </a>

          <a class="adminToolCard sites" href="/admin/employee-sites">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_user()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Employee Sites</div>
            <div class="adminToolSub">Assign employees to site locations for clock-in access.</div>
          </a>

          <a class="adminToolCard employees" href="/admin/employees">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_user()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Employees</div>
            <div class="adminToolSub">Create employees, update rates and manage access.</div>
          </a>

          <a class="adminToolCard drive" href="/connect-drive">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_grid()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Connect Drive</div>
            <div class="adminToolSub">Reconnect Google Drive for onboarding uploads.</div>
          </a>
        </div>
      </div>
            <div class="card adminSectionCard" style="margin-top:12px;">
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
            role="admin",
            content_html=content
        )
    )
@app.route("/admin/company", methods=["GET", "POST"])
def admin_company():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    role = session.get("role", "admin")
    wp = _session_workplace_id()

    settings = get_company_settings()
    current_name = (settings.get("Company_Name") or "").strip() or "Main"

    msg = ""
    ok = False

    if request.method == "POST":
        require_csrf()
        new_name = (request.form.get("company_name") or "").strip()

        if not new_name:
            msg = "Company name required."
        elif not settings_sheet:
            msg = "Settings sheet not configured."
        else:
            vals = settings_sheet.get_all_values()
            if not vals:
                settings_sheet.append_row(["Workplace_ID", "Tax_Rate", "Currency_Symbol", "Company_Name"])
                vals = settings_sheet.get_all_values()

            hdr = vals[0] if vals else []
            def idx(n): return hdr.index(n) if n in hdr else None

            i_wp = idx("Workplace_ID")
            i_name = idx("Company_Name")
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
                else:
                    row = [""] * len(hdr)
                    row[i_wp] = wp
                    row[i_name] = new_name
                    if i_tax is not None:
                        row[i_tax] = str(settings.get("Tax_Rate", 20.0))
                    if i_cur is not None:
                        row[i_cur] = str(settings.get("Currency_Symbol", "£"))
                    settings_sheet.append_row(row)

                log_audit("SET_COMPANY_NAME", actor=session.get("username", "admin"), details=f"{wp} -> {new_name}")
                ok = True
                msg = "Saved."
                current_name = new_name

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Company Settings</h1>
          <p class="sub">Workplace: <b>{escape(wp)}</b></p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

      <div class="card payrollEmployeeCard" style="padding:12px; margin-top:12px;">
        <form method="POST">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <label class="sub">Company name</label>
          <input class="input" name="company_name" value="{escape(current_name)}" required>
          <button class="btnSoft" type="submit" style="margin-top:12px;">Save</button>
        </form>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", role, content))

@app.post("/admin/save-shift")
def admin_save_shift():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or "").strip()
    date_str = (request.form.get("date") or "").strip()
    cin = (request.form.get("cin") or "").strip()
    cout = (request.form.get("cout") or "").strip()
    hours_in = (request.form.get("hours") or "").strip()
    pay_in = (request.form.get("pay") or "").strip()
    recalc = (request.form.get("recalc") == "yes")

    if not username or not date_str:
        return redirect(request.referrer or "/admin/payroll")

    rate = _get_user_rate(username)

    hours_val = None if hours_in == "" else safe_float(hours_in, 0.0)
    pay_val = None if pay_in == "" else safe_float(pay_in, 0.0)

    # Auto-calc when:
    # - admin ticks "Recalculate", OR
    # - admin enters Clock In/Out and leaves Hours+Pay blank
    auto_calc = recalc or (cin and cout and hours_in == "" and pay_in == "")

    if cin and cout and auto_calc:
        computed = _compute_hours_from_times(date_str, cin, cout)
        if computed is not None:
            hours_val = computed
            pay_val = round(computed * rate, 2)

    # Manual hours edit: if Hours is entered but Pay is blank,
    # automatically refresh Pay from the employee rate.
    if hours_in != "" and pay_in == "":
        pay_val = round(safe_float(hours_in, 0.0) * rate, 2)

    hours_cell = "" if hours_val is None else str(hours_val)
    pay_cell = "" if pay_val is None else str(pay_val)

    try:
        vals = work_sheet.get_all_values()
        rownum = _find_workhours_row_by_user_date(vals, username, date_str)
        if rownum:
            work_sheet.update_cell(rownum, COL_IN + 1, cin)
            work_sheet.update_cell(rownum, COL_OUT + 1, cout)
            work_sheet.update_cell(rownum, COL_HOURS + 1, hours_cell)
            work_sheet.update_cell(rownum, COL_PAY + 1, pay_cell)
        else:
            headers = vals[0] if vals else []
            new_row = [username, date_str, cin, cout, hours_cell, pay_cell]

            if headers and "Workplace_ID" in headers:
                wp_idx = headers.index("Workplace_ID")
                if len(new_row) <= wp_idx:
                    new_row += [""] * (wp_idx + 1 - len(new_row))
                new_row[wp_idx] = _session_workplace_id()

            # Pad to header width (prevents misaligned rows if sheet has extra columns)
            if headers and len(new_row) < len(headers):
                new_row += [""] * (len(headers) - len(new_row))

            work_sheet.append_row(new_row)
    except Exception:
        pass

    return redirect(request.referrer or "/admin/payroll")


@app.post("/admin/force-clockin")
def admin_force_clockin():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or "").strip()
    in_time = (request.form.get("in_time") or "").strip()  # HH:MM or HH:MM:SS
    dates = [(d or "").strip() for d in request.form.getlist("date")]
    dates = [d for d in dates if d]
    date_str = dates[-1] if dates else datetime.now(TZ).strftime("%Y-%m-%d")
    if not username or not in_time:
        return redirect(request.referrer or "/admin")

    # normalize to HH:MM:SS
    if len(in_time.split(":")) == 2:
        in_time = in_time + ":00"

    try:
        vals = work_sheet.get_all_values()
        headers = vals[0] if vals else []

        # If an open shift already exists, do nothing (avoid duplicates)
        if find_open_shift(vals, username):
            return redirect(request.referrer or "/admin")

        rownum = _find_workhours_row_by_user_date(vals, username, date_str)

        wp_col = (headers.index("Workplace_ID") + 1) if ("Workplace_ID" in headers) else None

        if rownum:
            # Update today's row
            work_sheet.update_cell(rownum, COL_IN + 1, in_time)
            if wp_col:
                work_sheet.update_cell(rownum, wp_col, _session_workplace_id())
        else:
            # Create a new row for today
            new_row = [username, date_str, in_time, "", "", ""]

            if "Workplace_ID" in headers:
                wp_idx = headers.index("Workplace_ID")
                if len(new_row) <= wp_idx:
                    new_row += [""] * (wp_idx + 1 - len(new_row))
                new_row[wp_idx] = _session_workplace_id()

            # Pad to header width (prevents misaligned rows if sheet has extra columns)
            if headers and len(new_row) < len(headers):
                new_row += [""] * (len(headers) - len(new_row))

            work_sheet.append_row(new_row)

    except Exception:
        pass

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
    out_time = (request.form.get("out_time") or "").strip()  # HH:MM or HH:MM:SS

    if not username or not out_time:
        return redirect(request.referrer or "/admin")

    rows = work_sheet.get_all_values()
    osf = find_open_shift(rows, username)
    if not osf:
        return redirect(request.referrer or "/admin")

    idx, d, cin = osf  # idx is 0-based data index (within rows list)
    rate = _get_user_rate(username)

    # normalize to HH:MM:SS
    if len(out_time.split(":")) == 2:
        out_time = out_time + ":00"

    computed_hours = _compute_hours_from_times(d, cin, out_time)
    if computed_hours is None:
        return redirect(request.referrer or "/admin")

    pay = round(computed_hours * rate, 2)

    sheet_row = idx + 1  # idx already is row index in sheet values? find_open_shift returns i as index in rows list
    # In this codebase: find_open_shift returns i, date, in_time where i is index in rows list.
    sheet_row = idx + 1

    sheet_row = idx + 1

    try:
        vals = work_sheet.get_all_values()
        headers = vals[0] if vals else []

        updates = [
            {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_OUT + 1), "values": [[out_time]]},
            {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_HOURS + 1), "values": [[str(computed_hours)]]},
            {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_PAY + 1), "values": [[str(pay)]]},
        ]

        # Ensure Workplace_ID is set (if column exists)
        if headers and "Workplace_ID" in headers:
            wp_col = headers.index("Workplace_ID") + 1
            updates.append(
                {"range": gspread.utils.rowcol_to_a1(sheet_row, wp_col), "values": [[_session_workplace_id()]]})

        import copy
        _gs_write_with_retry(lambda: work_sheet.batch_update(copy.deepcopy(updates)))
    except Exception:
        pass

    actor = session.get("username", "admin")
    log_audit("FORCE_CLOCK_OUT", actor=actor, username=username, date_str=d, details=f"out={out_time} hours={computed_hours} pay={pay}")
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
    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    q = (request.args.get("q", "") or "").strip().lower()
    date_from = (request.args.get("from", "") or "").strip()
    date_to = (request.args.get("to", "") or "").strip()

    rows = work_sheet.get_all_values()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()

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
        return f"Week {iso[1]} ({d0.strftime('%d %b')} – {(d0+timedelta(days=6)).strftime('%d %b %Y')})"

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

        # Workplace filter: prefer WorkHours row Workplace_ID (tenant-safe)
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != current_wp:
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
            h = safe_float(row["hours"], 0.0)
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
            if row_wp != current_wp:
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

    # All users from Employees sheet
    all_users = []
    try:
        for rec in employees_sheet.get_all_records():
            if not _same_workplace(rec):
                continue
            un = (rec.get("Username") or "").strip()
            if un:
                all_users.append(un)
    except Exception:
        all_users = list(by_user.keys())

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
        d0 = this_monday - timedelta(days=7*i)
        selected = "selected" if i == wk_offset else ""
        week_options.append(
            f"<option value='{i}' {selected}>{escape(week_label(d0))}</option>"
        )

    week_nav_html = f"""
      <form method="GET" style="margin-top:10px; display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
        <input type="hidden" name="q" value="{escape(q)}">
        <input type="hidden" name="from" value="{escape(date_from)}">
        <input type="hidden" name="to" value="{escape(date_to)}">

        <label class="sub" style="margin:0; font-weight:700;">Week</label>
        <select class="input" name="wk" style="max-width:320px; margin-top:0;" onchange="this.form.submit()">
          {''.join(week_options)}
        </select>
      </form>
    """
    # Payroll donut chart data (gross by employee for current filtered view)
    chart_palette = [
        "#2563eb", "#7c3aed", "#16a34a", "#f59e0b", "#ef4444",
        "#06b6d4", "#84cc16", "#ec4899", "#14b8a6", "#8b5cf6"
    ]

    chart_rows = []
    for u, vals_u in by_user.items():
        gross_u = round(vals_u.get("gross", 0.0), 2)
        if gross_u <= 0:
            continue
        chart_rows.append({
            "user": u,
            "name": get_employee_display_name(u),
            "gross": gross_u,
        })

    chart_rows = sorted(chart_rows, key=lambda x: x["gross"], reverse=True)
    chart_top = chart_rows[:15]
    other_total = round(sum(x["gross"] for x in chart_rows[6:]), 2)

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
    legend_html = "<div class='activityEmpty'>No payroll data for current filters.</div>"

    if total_chart_value > 0:
        angle_acc = 0.0
        stops = []
        for seg in chart_segments:
            pct = (seg["value"] / total_chart_value) * 100.0
            start = angle_acc
            end = angle_acc + pct
            stops.append(f"{seg['color']} {start:.2f}% {end:.2f}%")
            angle_acc = end
        donut_css = f"conic-gradient({', '.join(stops)})"

        legend_parts = []
        for seg in chart_segments:
            legend_parts.append(f"""
              <div class="payrollLegendRow">
                <div class="payrollLegendLeft">
                  <span class="payrollLegendDot" style="background:{seg['color']};"></span>
                  <span class="payrollLegendName">{escape(seg['label'])}</span>
                </div>
                <div class="payrollLegendVal">{escape(currency)}{money(seg['value'])}</div>
              </div>
            """)
        legend_html = "".join(legend_parts)
    # KPI strip (PRO)
    kpi_strip = f"""
      <div class="kpiStrip">
        <div class="kpiMini"><div class="k">Hours</div><div class="v">{round(overall_hours,2)}</div></div>
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

        for u in sorted(all_users, key=lambda s: s.lower()):
            display = get_employee_display_name(u)
            user_days = week_lookup.get(u, {})

            total_hours = 0.0
            gross = 0.0
            tax = 0.0
            net = 0.0

            cells = []

            # Employee cell
            cells.append(f"""
                
                 <td class="payrollEmpCell">
                    <span class="emp">{escape(display)}</span>
                    <span class="empSub">ID: {escape(u)}</span>
                </td>
            """)

            # 7 days
            # 7 days (week_lookup is keyed by YYYY-MM-DD, and uses cin/cout keys)
            gross = 0.0
            total_hours = 0.0

            for di in range(7):
                d_str = (week_start + timedelta(days=di)).strftime("%Y-%m-%d")
                rec = user_days.get(d_str, {}) if isinstance(user_days, dict) else {}

                cin = (rec.get("cin", "") if isinstance(rec, dict) else "") or ""
                cout = (rec.get("cout", "") if isinstance(rec, dict) else "") or ""
                hrs = safe_float((rec.get("hours", "0") if isinstance(rec, dict) else "0"), default=0.0)
                pay = safe_float((rec.get("pay", "0") if isinstance(rec, dict) else "0"), default=0.0)

                total_hours += hrs
                gross += pay

                form_id = f"payroll_{re.sub(r'[^a-zA-Z0-9]+', '_', u)}_{d_str.replace('-', '_')}"

                cells.append(f"""
                  <td style='text-align:center;'>
                    <input
                      class="payrollTimeInput"
                      type="time"
                      step="60"
                      name="cin"
                      value="{escape((cin or '')[:5])}"
                      form="{form_id}"
                      onchange="document.getElementById('{form_id}').submit()">
                  </td>
                """)

                cells.append(f"""
                  <td style='text-align:center;'>
                    <input
                      class="payrollTimeInput"
                      type="time"
                      step="60"
                      name="cout"
                      value="{escape((cout or '')[:5])}"
                      form="{form_id}"
                      onchange="document.getElementById('{form_id}').submit()">
                  </td>
                """)

                cells.append(f"""
                  <td class='num' style='color: var(--navy); font-weight:900;'>
                    {hrs:.2f}
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

            if paid:
                mark_paid_btn = "<button class='btnTiny paidDone' type='button' disabled>Paid</button>"
            elif gross > 0:
                mark_paid_btn = f"""
                <form method="POST" action="/admin/mark-paid" style="margin:0;">
                    <input type="hidden" name="csrf" value="{escape(csrf)}">
                    <input type="hidden" name="week_start" value="{escape(week_start_str)}">
                    <input type="hidden" name="week_end" value="{escape(week_end_str)}">
                    <input type="hidden" name="user" value="{escape(u)}">
                    <input type="hidden" name="gross" value="{gross}">
                    <input type="hidden" name="tax" value="{tax}">
                    <input type="hidden" name="net" value="{net}">
                    <button class="btnTiny" type="submit">Paid</button>
                </form>
                """
            else:
                mark_paid_btn = ""

            cells.append(f"<td class='num'>{total_hours:.2f}</td>")
            cells.append(f"<td class='num'>{escape(currency)}{money(gross)}</td>")
            cells.append(f"<td class='num'>{escape(currency)}{money(tax)}</td>")

            if paid:
                cells.append(f"<td class='num net paidNetCell'>{escape(currency)}{money(net)}<br>Paid</td>")
            elif gross > 0:
                cells.append(f"""
                  <td class='num net'>
                    <form method="POST" action="/admin/mark-paid" class="payCellForm">
                      <input type="hidden" name="csrf" value="{escape(csrf)}">
                      <input type="hidden" name="week_start" value="{escape(week_start_str)}">
                      <input type="hidden" name="week_end" value="{escape(week_end_str)}">
                      <input type="hidden" name="user" value="{escape(u)}">
                      <input type="hidden" name="gross" value="{gross}">
                      <input type="hidden" name="tax" value="{tax}">
                      <input type="hidden" name="net" value="{net}">
                      <button class="payCellBtn" type="submit">
                        {escape(currency)}{money(net)}
                        <span class="payLabel">Pay</span>
                      </button>
                    </form>
                  </td>
                """)
            else:
                cells.append(f"<td class='num net zeroNetCell'>{escape(currency)}{money(net)}</td>")


            sheet_rows.append("<tr>" + "".join(cells) + "</tr>")

        sheet_html = "".join(sheet_rows)

    # Per-user weekly editable tables
    day_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    blocks = []
    for u in sorted(all_users, key=lambda s: s.lower()):
        display = get_employee_display_name(u)
        user_days = week_lookup.get(u, {})

        # Show the editable weekly table only if the employee has at least 1 REAL record in this week
        has_any = False
        for rec in user_days.values():
            if isinstance(rec, dict) and (
                    rec.get("clock_in") or
                    rec.get("clock_out") or
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
                h = safe_float(rec.get("hours","0"), 0.0)
                wk_hours += h
                if h > OVERTIME_HOURS:
                    wk_overtime_days += 1
            if rec and rec.get("pay"):
                wk_gross += safe_float(rec.get("pay","0"), 0.0)

        wk_hours = round(wk_hours, 2)
        wk_gross = round(wk_gross, 2)
        wk_tax = round(wk_gross * tax_rate, 2)
        wk_net = round(wk_gross - wk_tax, 2)

        paid, paid_at = _is_paid_for_week(week_start_str, week_end_str, u)

        summary_line = (
            f"Week totals: <b>{wk_hours:.2f}</b> hours &nbsp;•&nbsp; "
            f"Gross <b>{escape(currency)}{money(wk_gross)}</b> &nbsp;•&nbsp; "
            f"Tax <b>{escape(currency)}{money(wk_tax)}</b> &nbsp;•&nbsp; "
            f"Net <b>{escape(currency)}{money(wk_net)}</b>"
        )

        if paid and paid_at:
            summary_line += f" &nbsp;•&nbsp; Paid at <b>{escape(paid_at)}</b>"

        overtime_note = ""
        if wk_overtime_days > 0:
            overtime_note = f"<span class='overtimeChip'>Overtime days: {wk_overtime_days}</span>"

        rows_html = []
        for di in range(7):
            d_dt = week_start + timedelta(days=di)
            d_str = d_dt.strftime("%Y-%m-%d")
            rec = user_days.get(d_str)

            cin = rec["cin"] if rec else ""
            cout = rec["cout"] if rec else ""
            hrs = rec["hours"] if rec else ""
            pay = rec["pay"] if rec else ""

            h_val = safe_float(hrs, 0.0) if str(hrs).strip() != "" else 0.0
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
                hrs_txt = f"{safe_float(hrs, 0.0):.2f}".rstrip("0").rstrip(".")

            pay_txt = ""
            if has_row:
                pay_txt = money(safe_float(pay, 0.0))

            rows_html.append(f"""
              <tr class="{overtime_row_class}">
                <td><b>{day_names[di]}</b></td>
                <td>{escape(d_str)}</td>
                <td style="font-weight:700; text-align:center;">{escape(cin_txt)}</td>
                <td style="font-weight:700; text-align:center;">{escape(cout_txt)}</td>
                <td class="num" style="font-weight:700;">{escape(hrs_txt)}</td>
<td class="num" style="font-weight:700;">{escape(pay_txt)}</td>
<td class="num" style="font-weight:800; color:rgba(15,23,42,.92);">{escape(money(round(safe_float(pay, 0.0) * (1 - tax_rate), 2))) if has_row else ""}</td>
              </tr>
            """)

        blocks.append(f"""
          <div class="card payrollEmployeeCard" style="padding:12px; margin-top:12px;">
            <div style="margin-bottom:12px;">
              <div style="font-size:30px; font-weight:800; line-height:1.1; color:rgba(15,23,42,.96);">
                {escape(display)}
              </div>
            </div>

            <div class="tablewrap" style="margin-top:12px;">
              <table class="weeklyEditTable">
                <colgroup>
                  <col style="width:70px;">
                  <col style="width:130px;">
                  <col style="width:140px;">
                  <col style="width:140px;">
                  <col style="width:140px;">
                  <col style="width:150px;">
                  <col style="width:150px;">
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
            <button type="button" class="payrollMenuToggle" id="payrollMenuToggle">☰ Menu</button>
            <div>
              <h1>Payroll Report</h1>
              <p class="sub">Printable • Updated {escape(last_updated)} • Weekly tables auto-update every week</p>
            </div>
          </div>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

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
              <div class="row2">
                <input class="input" type="date" name="from" value="{escape(date_from)}">
                <input class="input" type="date" name="to" value="{escape(date_to)}">
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

        <div class="card payrollChartCard">
          <div class="sectionHead">
            <div class="sectionHeadLeft">
              <div class="sectionIcon">{_svg_chart()}</div>
              <div>
                <h2 style="margin:0;">Payroll Split</h2>
                <p class="sub" style="margin:4px 0 0 0;">Gross by employee for current filters.</p>
              </div>
            </div>
            <div class="sectionBadge">{len(chart_segments)} segments</div>
          </div>

          <div class="payrollDonutWrap">
            <div class="payrollDonut" style="background:{donut_css};">
              <div class="payrollDonutCenter">
                <div class="k">Total Gross</div>
                <div class="v">{escape(currency)}{money(total_chart_value)}</div>
              </div>
            </div>
          </div>

          <div class="payrollLegend">
            {legend_html}
          </div>
        </div>
      </div>

      {week_nav_html}

        <div class="payrollWrap" style="margin-top:12px;">
<table class="payrollSheet">
  <thead>
    <tr class="group">
      <th rowspan="2" style="width:110px;">Employee</th>
      <th colspan="3">Monday</th>
      <th colspan="3">Tuesday</th>
      <th colspan="3">Wednesday</th>
      <th colspan="3">Thursday</th>
      <th colspan="3">Friday</th>
      <th colspan="3">Saturday</th>
      <th colspan="3">Sunday</th>
      <th rowspan="2">Total</th>
      <th rowspan="2">Gross</th>
      <th rowspan="2">Tax</th>
      <th rowspan="2">Net / Pay</th>
    </tr>
    <tr class="cols">
      <th>In</th><th>Out</th><th>Hrs</th>
      <th>In</th><th>Out</th><th>Hrs</th>
      <th>In</th><th>Out</th><th>Hrs</th>
      <th>In</th><th>Out</th><th>Hrs</th>
      <th>In</th><th>Out</th><th>Hrs</th>
      <th>In</th><th>Out</th><th>Hrs</th>
      <th>In</th><th>Out</th><th>Hrs</th>
    </tr>
  </thead>
  <tbody>
    {sheet_html}
  </tbody>
</table>
</div>

<script>
(function(){{
  const table = document.querySelector(".payrollWrap .payrollSheet");
  if(!table) return;
  const tbody = table.querySelector("tbody");
  if(!tbody) return;

  let selected = null;

  function clearRow(tr){{
    if(!tr) return;
    tr.querySelectorAll("td").forEach(td => {{
      td.style.background = "";
      td.style.boxShadow = "";
    }});
  }}

  function applyRow(tr){{
    tr.querySelectorAll("td").forEach((td, idx) => {{
      td.style.background = "rgba(30,64,175,.14)";
      if(idx === 0){{
        td.style.boxShadow = "inset 3px 0 0 rgba(30,64,175,.45)";
      }}
    }});
  }}

  tbody.querySelectorAll("tr").forEach(tr => {{
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => {{
      if(selected === tr){{
        clearRow(tr);
        selected = null;
        return;
      }}
      clearRow(selected);
      selected = tr;
      applyRow(tr);
    }});
  }});
}})();
</script>
    {''.join(blocks)}
            <script>
        (function(){{
          const shell = document.querySelector(".shell.payrollShell");
          const btn = document.getElementById("payrollMenuToggle");
          const backdrop = document.getElementById("payrollMenuBackdrop");

          if (!shell || !btn || !backdrop) return;

          function closeMenu(){{
            shell.classList.remove("payrollMenuOpen");
          }}

          btn.addEventListener("click", function(){{
            shell.classList.toggle("payrollMenuOpen");
          }});

          backdrop.addEventListener("click", closeMenu);

          document.addEventListener("keydown", function(e){{
            if (e.key === "Escape") closeMenu();
          }});
        }})();
      </script>
    """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell(active="admin", role="admin", content_html=content, shell_class="payrollShell")
    )
def _get_week_range(wk_offset: int):
    """
    Returns (week_start_str, week_end_str) for a Monday->Sunday week,
    offset by wk_offset weeks (0=this week, 1=previous week, etc).
    """
    today = date.today()
    monday = today - timedelta(days=today.weekday())  # Monday
    week_start = monday - timedelta(days=7 * int(wk_offset))
    week_end = week_start + timedelta(days=6)  # Sunday
    return week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d")

@app.get("/admin/payroll-report.csv")
def admin_payroll_report_csv():
    gate = require_admin()
    if gate:
        return gate

    # Same filters as payroll report page
    username_q = (request.args.get("q") or "").strip().lower()
    date_from = (request.args.get("from") or "").strip()
    date_to = (request.args.get("to") or "").strip()
    wk_offset = int(request.args.get("wk") or "0")

    wp = _session_workplace_id()
    wp = ((wp or "default").strip() or "default")

    # Build the same weekly window you use in the Payroll Report page
    # (Assumes you already compute week_start/week_end similarly in the page)
    week_start, week_end = _get_week_range(wk_offset)  # <-- this helper should already exist in your code
    week_start = str(week_start)
    week_end = str(week_end)
    use_range = False
    range_start = range_end = None

    if date_from and date_to:
        try:
            range_start = date.fromisoformat(date_from)
            range_end = date.fromisoformat(date_to)
            use_range = True
            # also make filename/CSV columns show the selected range
            week_start = date_from
            week_end = date_to
        except ValueError:
            use_range = False
    debug_lines = [
        f"# DEBUG week_start={week_start} week_end={week_end} wk={wk_offset} wp={wp}",
    ]
    try:
        payroll_reports_sheet = spreadsheet.worksheet("PayrollReports")
        pv = payroll_reports_sheet.get_all_values()
        ph = pv[0] if pv else []
        debug_lines.append(f"# DEBUG payroll_headers={ph}")
        for rr in (pv[1:4] if len(pv) > 1 else []):
            debug_lines.append(f"# DEBUG row_weekstart={rr[0] if len(rr)>0 else ''} row_weekend={rr[1] if len(rr)>1 else ''} row_user={rr[2] if len(rr)>2 else ''}")
    except Exception as e:
        debug_lines.append(f"# DEBUG payroll_read_error={e}")
    # Summarise from PayrollReports (preferred) or WorkHours if your page does so.
    # We'll reuse your existing helper if present:
    # Build rows directly from PayrollReports sheet
        rows = []
        totals = {}

        def _f(x):
            try:
                return float((x or "").strip() or 0)
            except Exception:
                return 0.0

        try:
            payroll_reports_sheet = spreadsheet.worksheet("PayrollReports")
            vals = payroll_reports_sheet.get_all_values()
            hdr = vals[0] if vals else []

            def hidx(name):
                if not hdr:
                    return None
                target = (name or "").strip().lower()
                for i, h in enumerate(hdr):
                    if (h or "").strip().lower() == target:
                        return i
                return None

            i_ws = hidx("WeekStart")
            i_we = hidx("WeekEnd")
            i_user = hidx("Username")
            i_g = hidx("Gross")
            i_t = hidx("Tax")
            i_n = hidx("Net")
            i_paid = hidx("Paid")
            i_wp = hidx("Workplace_ID")

            for r in (vals[1:] if len(vals) > 1 else []):
                ws = (r[i_ws] if i_ws is not None and len(r) > i_ws else "").strip()
                we = (r[i_we] if i_we is not None and len(r) > i_we else "").strip()
                u = (r[i_user] if i_user is not None and len(r) > i_user else "").strip()

                if use_range:
                    try:
                        ws_d = date.fromisoformat(ws)
                        we_d = date.fromisoformat(we)
                    except ValueError:
                        continue
                    if we_d < range_start or ws_d > range_end:
                        continue
                else:
                    if ws != week_start or we != week_end:
                        continue

                if i_wp is not None:
                    rwp = ((r[i_wp] if len(r) > i_wp else "").strip() or "default")
                    if rwp != wp:
                        continue

                if username_q and username_q not in u.lower():
                    continue

                if use_range:
                    t = totals.setdefault(u, {"Gross": 0.0, "Tax": 0.0, "Net": 0.0})
                    t["Gross"] += _f(r[i_g] if i_g is not None and len(r) > i_g else "")
                    t["Tax"] += _f(r[i_t] if i_t is not None and len(r) > i_t else "")
                    t["Net"] += _f(r[i_n] if i_n is not None and len(r) > i_n else "")
                else:
                    rows.append({
                        "Employee": get_employee_display_name(u),
                        "Username": u,
                        "Hours": (r[i_h] if i_h is not None and len(r) > i_h else "").strip(),
                        "Gross": (r[i_g] if i_g is not None and len(r) > i_g else "").strip(),
                        "Tax": (r[i_t] if i_t is not None and len(r) > i_t else "").strip(),
                        "Net": (r[i_n] if i_n is not None and len(r) > i_n else "").strip(),
                        "Paid": (r[i_paid] if i_paid is not None and len(r) > i_paid else "").strip(),
                    })

            if use_range:
                rows = []
                for u, t in totals.items():
                    rows.append({
                        "Employee": get_employee_display_name(u),
                        "Username": u,
                        "Hours": "",
                        "Gross": f'{t["Gross"]:.2f}',
                        "Tax": f'{t["Tax"]:.2f}',
                        "Net": f'{t["Net"]:.2f}',
                        "Paid": "",
                    })

        except Exception as e:
            rows = []
            vals = []
            hdr = [f"BUILD_ERROR: {e}"]
            i_ws = i_we = i_user = i_wp = i_g = i_t = i_n = i_paid = None

        def _f(x):
            try:
                return float((x or "").strip() or 0)
            except Exception:
                return 0.0
    # rows should be list of dicts:
    # [{"Employee":..., "Username":..., "Hours":..., "Gross":..., "Tax":..., "Net":..., "Paid":...}, ...]

    # --- BUILD ROWS FOR CSV EXPORT (guaranteed in function scope) ---
    rows = []
    totals = {}
    vals = []
    hdr = []

    def _f(x):
        try:
            return float((x or "").strip() or 0)
        except Exception:
            return 0.0

    try:
        payroll_reports_sheet = spreadsheet.worksheet("PayrollReports")
        vals = payroll_reports_sheet.get_all_values()
        hdr = vals[0] if vals else []

        def hidx(name):
            target = (name or "").strip().lower()
            for i, h in enumerate(hdr):
                if (h or "").strip().lower() == target:
                    return i
            return None

        i_ws = hidx("WeekStart")
        i_we = hidx("WeekEnd")
        i_user = hidx("Username")
        i_h = hidx("Hours") or hidx("Hrs")
        i_g = hidx("Gross")
        i_t = hidx("Tax")
        i_n = hidx("Net")
        i_paid = hidx("Paid")
        i_wp = hidx("Workplace_ID")

        if i_ws is None or i_we is None or i_user is None:
            raise RuntimeError(f"Missing headers: WeekStart/WeekEnd/Username in {hdr}")

        for r in (vals[1:] if len(vals) > 1 else []):
            ws = ((r[i_ws] if len(r) > i_ws else "") or "").strip()[:10]
            we = ((r[i_we] if len(r) > i_we else "") or "").strip()[:10]
            u = ((r[i_user] if len(r) > i_user else "") or "").strip()

            if use_range:
                try:
                    ws_d = date.fromisoformat(ws)
                    we_d = date.fromisoformat(we)
                except ValueError:
                    continue
                if we_d < range_start or ws_d > range_end:
                    continue
            else:
                if ws != str(week_start)[:10] or we != str(week_end)[:10]:
                    continue

            if i_wp is not None:
                rwp = (((r[i_wp] if len(r) > i_wp else "") or "").strip() or "default")
                if rwp != wp:
                    continue

            if username_q and username_q not in u.lower():
                continue

            if use_range:
                t = totals.setdefault(u, {"Gross": 0.0, "Tax": 0.0, "Net": 0.0})
                t["Gross"] += _f(r[i_g] if i_g is not None and len(r) > i_g else "")
                t["Tax"] += _f(r[i_t] if i_t is not None and len(r) > i_t else "")
                t["Net"] += _f(r[i_n] if i_n is not None and len(r) > i_n else "")
            else:
                rows.append({
                    "Employee": get_employee_display_name(u),
                    "Username": u,
                    "Hours": "",
                    "Gross": (r[i_g] if i_g is not None and len(r) > i_g else "").strip(),
                    "Tax": (r[i_t] if i_t is not None and len(r) > i_t else "").strip(),
                    "Net": (r[i_n] if i_n is not None and len(r) > i_n else "").strip(),
                    "Paid": (r[i_paid] if i_paid is not None and len(r) > i_paid else "").strip(),
                })

        if use_range:
            rows = []
            for u, t in totals.items():
                rows.append({
                    "Employee": get_employee_display_name(u),
                    "Username": u,
                    "Hours": "",
                    "Gross": f'{t["Gross"]:.2f}',
                    "Tax": f'{t["Tax"]:.2f}',
                    "Net": f'{t["Net"]:.2f}',
                    "Paid": "",
                })

    except Exception as e:
        # keep debug visible
        hdr = [f"BUILD_ERROR: {e}"]
        rows = []
        totals = {}
    # --- END BUILD ---
        msg = []
        msg.append(f"wp={wp!r}")
        msg.append(f"wk_offset={wk_offset} week_start={week_start!r} week_end={week_end!r}")
        msg.append(f"use_range={use_range} from={date_from!r} to={date_to!r} q={username_q!r}")
        try:
            hdr_ = locals().get("hdr", None)
            vals_ = locals().get("vals", None)
            rows_ = locals().get("rows", None)
            totals_ = locals().get("totals", None)

            msg.append(f"hdr={hdr_!r}")
            msg.append(f"vals_exists={vals_ is not None} rows_exists={rows_ is not None} totals_exists={totals_ is not None}")

            if vals_:
                msg.append(f"total_rows={len(vals_) - 1}")
                msg.append(f"sample_rows={vals_[1:6]!r}")
            if rows_ is not None:
                msg.append(f"built_rows={len(rows_)}")
            if totals_ is not None:
                msg.append(f"totals_count={len(totals_)}")
        except Exception as e:
            msg.append(f"debug_error={e}")
        return make_response("\n".join(msg), 200, {"Content-Type": "text/plain"})
    import csv
    from io import StringIO
    output = StringIO()
    output.write("sep=,\r\n")  # Excel: force comma delimiter
    if use_range:
        output.write("# Note: totals include any payroll weeks that overlap the selected date range.\r\n")
    w = csv.writer(output)
    w.writerow(["WeekStart", "WeekEnd", "Employee", "Gross", "Tax", "Net"])
    rows = locals().get("rows", [])
    for r in rows:
        w.writerow([
            str(week_start),
            str(week_end),
            r.get("Employee", ""),
            r.get("Gross", ""),
            r.get("Tax", ""),
            r.get("Net", ""),
        ])

    csv_text = output.getvalue()
    buf = io.BytesIO(csv_text.encode("utf-8-sig"))  # Excel-friendly
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
    vals = onboarding_sheet.get_all_values()
    if not vals:
        body = "<tr><td colspan='3'>No onboarding data.</td></tr>"
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

        rows_html = []
        for r in vals[1:]:
            u = r[i_user] if i_user is not None and i_user < len(r) else ""
            if not u:
                continue
            # Tenant-safe: filter by Onboarding row Workplace_ID (if column exists)
            if i_wp is not None:
                row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                if row_wp != current_wp:
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
                f"<tr><td><a href='/admin/onboarding/{escape(u)}' style='color:var(--navy);font-weight:600;'>{escape(name)}</a></td>"
                f"<td>{escape(u)}</td><td>{escape(sub)}</td></tr>"
            )
        body = "".join(rows_html) if rows_html else "<tr><td colspan='3'>No matches.</td></tr>"

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Onboarding</h1>
          <p class="sub">Click a name to view details</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      <div class="card" style="padding:12px;">
        <form method="GET">
          <label class="sub">Search</label>
          <div class="row2">
            <input class="input" name="q" value="{escape(q)}" placeholder="name or username">
            <button class="btnSoft" type="submit" style="margin-top:8px;">Search</button>
          </div>
        </form>

        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width: 640px;">
            <thead><tr><th>Name</th><th>Username</th><th>Last saved</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", "admin", content))

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
        ("Username","Username"),("First name","FirstName"),("Last name","LastName"),
        ("Birth date","BirthDate"),("Phone CC","PhoneCountryCode"),("Phone","PhoneNumber"),
        ("Email","Email"),("Street","StreetAddress"),("City","City"),("Postcode","Postcode"),
        ("Emergency contact","EmergencyContactName"),("Emergency CC","EmergencyContactPhoneCountryCode"),
        ("Emergency phone","EmergencyContactPhoneNumber"),
        ("Medical","MedicalCondition"),("Medical details","MedicalDetails"),
        ("Position","Position"),("CSCS number","CSCSNumber"),("CSCS expiry","CSCSExpiryDate"),
        ("Employment type","EmploymentType"),("Right to work UK","RightToWorkUK"),
        ("NI","NationalInsurance"),("UTR","UTR"),("Start date","StartDate"),
        ("Bank account","BankAccountNumber"),("Sort code","SortCode"),("Account holder","AccountHolderName"),
        ("Company trading","CompanyTradingName"),("Company reg","CompanyRegistrationNo"),
        ("Date of contract","DateOfContract"),("Site address","SiteAddress"),
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

      <div class="card" style="padding:12px;">
        <div class="tablewrap">
          <table style="min-width: 720px;"><tbody>{details}</tbody></table>
        </div>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", "admin", content))



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
        if locations_sheet:
            vals = locations_sheet.get_all_values()
            if vals:
                headers = vals[0]
                i_wp = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
                current_wp = _session_workplace_id()
                rows = vals[1:] if "SiteName" in headers else vals
                for r in rows:
                    # Workplace filter (only if Locations has Workplace_ID column)
                    if i_wp is not None:
                        row_wp = (r[i_wp] if len(r) > i_wp else "").strip() or "default"
                        if row_wp != current_wp:
                            continue
                    if len(r) < 4:
                        continue
                    name = (r[0] or "").strip()
                    lat = (r[1] or "").strip() if len(r) > 1 else ""
                    lon = (r[2] or "").strip() if len(r) > 2 else ""
                    rad = (r[3] or "").strip() if len(r) > 3 else ""
                    act = (r[4] or "").strip() if len(r) > 4 else "TRUE"
                    if name:
                        all_rows.append({"name": name, "lat": lat, "lon": lon, "rad": rad, "act": act})
    except Exception:
        all_rows = []

    def _is_active(v):
        return str(v or "").strip().lower() not in ("false", "0", "no", "n", "off")

    def row_html(s):
        act_on = _is_active(s.get("act", "TRUE"))
        badge = "<span class='chip ok'>Active</span>" if act_on else "<span class='chip warn'>Inactive</span>"
        return f"""
          <tr>
            <td><b>{escape(s.get('name',''))}</b><div class='sub' style='margin:2px 0 0 0;'>{badge}<div class='sub' style='margin:6px 0 0 0;'><a href='/admin/locations?site={escape(s.get('name',''))}' style='color:var(--navy);font-weight:600;'>View map</a></div></td>
            <td class='num'>{escape(s.get('lat',''))}</td>
            <td class='num'>{escape(s.get('lon',''))}</td>
            <td class='num'>{escape(s.get('rad',''))}</td>
            <td style='min-width:340px;'>
              <form method="POST" action="/admin/locations/save" style="margin:0; display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                <input type="hidden" name="csrf" value="{escape(csrf)}">
                <input type="hidden" name="orig_name" value="{escape(s.get('name',''))}">
                <input class="input" name="name" value="{escape(s.get('name',''))}" placeholder="Site name" style="margin-top:0; max-width:160px;">
                <input class="input" name="lat" value="{escape(s.get('lat',''))}" placeholder="Lat" style="margin-top:0; max-width:120px;">
                <input class="input" name="lon" value="{escape(s.get('lon',''))}" placeholder="Lon" style="margin-top:0; max-width:120px;">
                <input class="input" name="rad" value="{escape(s.get('rad',''))}" placeholder="Radius m" style="margin-top:0; max-width:110px;">
                <label class="sub" style="display:flex; align-items:center; gap:8px; margin:0;">
                  <input type="checkbox" name="active" value="yes" {"checked" if act_on else ""}>
                  Active
                </label>
                <button class="btnTiny" type="submit">Save</button>
              </form>
              <form method="POST" action="/admin/locations/deactivate" style="margin-top:8px;">
                <input type="hidden" name="csrf" value="{escape(csrf)}">
                <input type="hidden" name="name" value="{escape(s.get('name',''))}">
                <button class="btnTiny dark" type="submit">Deactivate</button>
              </form>
            </td>
          </tr>
        """

    table_body = "".join([row_html(r) for r in all_rows]) if all_rows else "<tr><td colspan='5'>No locations yet.</td></tr>"



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
                <div class="sub" style="margin-top:6px;">{escape(chosen.get('name',''))} • {escape(chosen.get('lat',''))}, {escape(chosen.get('lon',''))}</div>
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
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", "admin", content))



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
        float(lat); float(lon); float(rad)
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

    actor = session.get("username", "admin")
    log_audit("LOCATIONS_SAVE", actor=actor, username="", date_str="", details=f"{name} {lat},{lon} r={rad} active={active}")
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

    # Active location names for dropdowns
    sites = _get_active_locations()
    site_names = [s["name"] for s in sites] if sites else []

    # Employees list
    vals = employees_sheet.get_all_values()
    rows_html = []

    if vals:
        headers = vals[0]
        def idx(n): return headers.index(n) if n in headers else None
        i_user = idx("Username")
        i_fn = idx("FirstName")
        i_ln = idx("LastName")
        i_site = idx("Site")
        i_wp = idx("Workplace_ID")
        current_wp = _session_workplace_id()

        for r in vals[1:]:
            if i_user is None or i_user >= len(r):
                continue
            u = (r[i_user] or "").strip()
            if not u:
                continue
            # Workplace filter: prefer row Workplace_ID (tenant-safe)
            if i_wp is not None:
                row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                if row_wp != current_wp:
                    continue
            else:
                # Backward compat if Employees has no Workplace_ID column
                if not user_in_same_workplace(u):
                    continue
            fn = (r[i_fn] or "").strip() if i_fn is not None and i_fn < len(r) else ""
            ln = (r[i_ln] or "").strip() if i_ln is not None and i_ln < len(r) else ""
            raw_site = (r[i_site] or "").strip() if i_site is not None and i_site < len(r) else ""
            disp = (fn + " " + ln).strip() or u

            assigned = _get_employee_sites(u)  # supports comma/semicolon
            s1 = assigned[0] if len(assigned) > 0 else ""
            s2 = assigned[1] if len(assigned) > 1 else ""

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

            # Validation chips
            chips = []
            if not assigned:
                chips.append("<span class='chip warn'>No site (fallback to any active)</span>")
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
                  <div class='sub' style='margin-top:6px;'>Tip: leave both blank to allow clock-in at any active site.</div>
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

      <div class="card" style="padding:12px;">
        <p class="sub" style="margin-top:0;">
          This updates the <b>Employees → Site</b> column. You can save <b>two sites</b>; they will be stored as <b>Site1,Site2</b>.
          If no site is set for an employee, the app falls back to <b>any active</b> location.
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
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", "admin", content))


@app.post("/admin/employee-sites/save")
def admin_employee_sites_save():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    u = (request.form.get("user") or "").strip()
    s1 = (request.form.get("site1") or "").strip()
    s2 = (request.form.get("site2") or "").strip()

    # normalize duplicates
    if s1 and s2 and s1.strip().lower() == s2.strip().lower():
        s2 = ""

    # store in Employees -> Site as "Site1,Site2" (no sheet schema changes needed)
    site_val = ""
    if s1 and s2:
        site_val = f"{s1},{s2}"
    else:
        site_val = s1 or s2 or ""

    if u:
        # Ensure "Site" column exists
        try:
            headers = get_sheet_headers(employees_sheet)
            if headers and "Site" not in headers:
                headers2 = headers + ["Site"]
                end_col = gspread.utils.rowcol_to_a1(1, len(headers2)).replace("1", "")
                employees_sheet.update(f"A1:{end_col}1", [headers2])
        except Exception:
            pass
        if not user_in_same_workplace(u):
            return redirect("/admin/employee-sites")
        set_employee_field(u, "Site", site_val)

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
            edit_role = (request.form.get("edit_role") or "").strip()
            edit_rate_raw = (request.form.get("edit_rate") or "").strip()

            if not edit_username:
                ok = False
                msg = "Enter a username to update."
            else:
                _ensure_employees_columns()
                headers = get_sheet_headers(employees_sheet)

                rownum = find_row_by_username(employees_sheet, edit_username)  # tenant-safe
                if not rownum:
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

                        if not changed:
                            ok = False
                            msg = "Nothing to update (enter a new role and/or rate)."
                        else:
                            end_col = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
                            try:
                                employees_sheet.update(f"A{rownum}:{end_col}{rownum}", [row])
                                actor = session.get("username", "admin")
                                log_audit("EMPLOYEE_UPDATE", actor=actor, username=edit_username, date_str="", details=" ".join(changed))
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
                if not rownum:
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
                            log_audit("EMPLOYEE_DEACTIVATE", actor=actor, username=edit_username, date_str="", details="active=FALSE")
                            msg = "Employee deactivated."
                        else:
                            log_audit("EMPLOYEE_REACTIVATE", actor=actor, username=edit_username, date_str="", details="active=TRUE")
                            msg = "Employee reactivated."
                        ok = True
                    except Exception:
                        ok = False
                        msg = "Could not update employee (sheet write failed)."

        elif action == "create":
            first = (request.form.get("first") or "").strip()
            last = (request.form.get("last") or "").strip()
            role_new = (request.form.get("role") or "employee").strip() or "employee"
            rate_raw = (request.form.get("rate") or "").strip()

            try:
                rate_val = float(rate_raw) if rate_raw != "" else 0.0
            except Exception:
                rate_val = 0.0

            wp = _session_workplace_id()

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
                log_audit("EMPLOYEE_CREATE", actor=actor, username=new_username, date_str="", details=f"role={role_new} rate={rate_val}")
                ok = True
                msg = "Employee created."
                created = {"u": new_username, "p": temp_pw, "wp": wp}
            except Exception:
                ok = False
                msg = "Could not create employee (sheet write failed)."

        else:
            ok = False
            msg = "Unknown action."

            try:
                rate_val = float(rate_raw) if rate_raw != "" else 0.0
            except Exception:
                rate_val = 0.0

            wp = _session_workplace_id()

            _ensure_employees_columns()
            headers = get_sheet_headers(employees_sheet)

            # Generate credentials
            new_username = _generate_unique_username(first, last, wp)
            temp_pw = _generate_temp_password(10)
            hashed = generate_password_hash(temp_pw)

            # Build row aligned to header length
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
                log_audit("EMPLOYEE_CREATE", actor=actor, username=new_username, date_str="", details=f"role={role_new} rate={rate_val}")
                ok = True
                msg = "Employee created."
                created = {"u": new_username, "p": temp_pw, "wp": wp}
            except Exception:
                ok = False
                msg = "Could not create employee (sheet write failed)."

    # List employees in this workplace
    wp = _session_workplace_id()
    rows_html = []
    try:
        vals = employees_sheet.get_all_values()
        headers = vals[0] if vals else []
        def idx(n): return headers.index(n) if headers and n in headers else None
        i_u = idx("Username")
        i_fn = idx("FirstName")
        i_ln = idx("LastName")
        i_role = idx("Role")
        i_rate = idx("Rate")
        i_wp = idx("Workplace_ID")

        for r in (vals[1:] if len(vals) > 1 else []):
            u = (r[i_u] if i_u is not None and i_u < len(r) else "").strip()
            if not u:
                continue
            if i_wp is not None:
                row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                if row_wp != wp:
                    continue
            fn = (r[i_fn] if i_fn is not None and i_fn < len(r) else "").strip()
            ln = (r[i_ln] if i_ln is not None and i_ln < len(r) else "").strip()
            rr = (r[i_role] if i_role is not None and i_role < len(r) else "").strip()
            rate = (r[i_rate] if i_rate is not None and i_rate < len(r) else "").strip()
            disp = (fn + " " + ln).strip() or u

            rows_html.append(
                f"<tr><td>{escape(disp)}</td><td>{escape(u)}</td><td>{escape(rr)}</td><td class='num'>{escape(rate)}</td></tr>"
            )
    except Exception:
        rows_html = []
    # Role suggestions from Employees sheet (this workplace)
    role_suggestions = ["employee", "manager", "admin"]
    try:
        found = set()
        # reuse vals/headers from above if they exist
        if "vals" in locals() and "headers" in locals() and headers and "Role" in headers:
            i_role2 = headers.index("Role")
            i_wp2 = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
            for r in (vals[1:] if len(vals) > 1 else []):
                if i_wp2 is not None:
                    row_wp = (r[i_wp2] if i_wp2 < len(r) else "").strip() or "default"
                    if row_wp != wp:
                        continue
                rr = (r[i_role2] if i_role2 < len(r) else "").strip()
                if rr:
                    found.add(rr)
        role_suggestions = sorted(set(role_suggestions) | found, key=lambda x: x.lower())
    except Exception:
        pass

    role_options_html = "".join(f"<option value='{escape(r)}'></option>" for r in role_suggestions)
    table = "".join(rows_html) if rows_html else "<tr><td colspan='4'>No employees found.</td></tr>"

    created_card = ""
    if created:
        created_card = f"""
        <div class="card" style="padding:12px; margin-top:12px;">
          <h2>Employee created</h2>
          <p class="sub">Give these login details to the employee (they can change password in Profile).</p>
          <div class="card" style="padding:12px; background:rgba(56,189,248,.18); border:1px solid rgba(56,189,248,.35); color:rgba(2,6,23,.95);">
            <div><b>Username:</b> {escape(created["u"])}</div>
            <div><b>Company:</b> {escape(get_company_settings().get("Company_Name") or created["wp"])}</div>
            <div><b>Temp password:</b> {escape(created["p"])}</div>
          </div>
        </div>
        """
        # Build employee dropdown options (this workplace)
    employee_options_html = "<option value='' selected disabled>Select employee</option>"
    try:
        wp_now = _session_workplace_id()
        vals2 = employees_sheet.get_all_values()
        headers2 = vals2[0] if vals2 else []

        def idx2(name):
            if not headers2:
                return None
            target = (name or "").strip().lower()
            for i, h in enumerate(headers2):
                if (h or "").strip().lower() == target:
                    return i
            return None

        i_user = idx2("Username")
        i_fn = idx2("FirstName")
        i_ln = idx2("LastName")
        i_wp = idx2("Workplace_ID")
        i_active = idx2("Active")

        if i_user is not None:
            for r in (vals2[1:] if len(vals2) > 1 else []):
                u = (r[i_user] if len(r) > i_user else "").strip()
                if not u:
                    continue
                if i_wp is not None:
                    r_wp = (r[i_wp] if len(r) > i_wp else "").strip()
                    if r_wp != wp_now:
                        continue
                if i_active is not None:
                    a = (r[i_active] if len(r) > i_active else "").strip().lower()
                    inactive_tag = ""
                    if a in ("false", "0", "no"):
                        inactive_tag = " (inactive)"

                fn = (r[i_fn] if i_fn is not None and len(r) > i_fn else "").strip()
                ln = (r[i_ln] if i_ln is not None and len(r) > i_ln else "").strip()
                disp = (fn + " " + ln).strip() or u

                employee_options_html += f"<option value='{escape(u)}'>{escape(disp)}{inactive_tag} ({escape(u)})</option>"
    except Exception:
        pass
    content = f"""

      <div class="headerTop">
        <div>
          <h1>Create Employee</h1>
          <p class="sub">Create a new employee login (auto username + temp password)</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

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
  </form>
</div>
      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>Employees (this workplace)</h2>
        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:760px;">
            <thead><tr><th>Name</th><th>Username</th><th>Role</th><th class="num">Rate</th></tr></thead>
            <tbody>{table}</tbody>
          </table>
        </div>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", "admin", content))



# ================= LOCAL RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)








