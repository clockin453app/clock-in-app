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
# - Dark mode toggle (localStorage).
# - Admin dashboard: live timers for currently clocked-in employees.
# - Unpaid break deduction: subtract 0.5h on shifts >= 6h (so 8am–5pm => 8.5h recorded).
#
# ✅ Fix:
# - Escaped JS curly braces inside f-strings to avoid Render SyntaxError.

import os
import json
import io
import secrets
import math
from urllib.parse import urlparse

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, render_template_string, request, redirect, session, url_for, abort
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials as UserCredentials
from google.auth.transport.requests import Request

from werkzeug.security import generate_password_hash, check_password_hash


# ================= APP =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static",
)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "15")) * 1024 * 1024
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"),
)

TZ = ZoneInfo(os.environ.get("APP_TZ", "Europe/London"))


# ================= GOOGLE SHEETS (SERVICE ACCOUNT) =================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

def load_google_creds_dict():
    raw = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
    if raw:
        return json.loads(raw)
    with open("credentials.json", "r", encoding="utf-8") as f:
        return json.load(f)

creds_dict = load_google_creds_dict()
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
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
# Optional (recommended): Admin audit log
try:
    audit_sheet = spreadsheet.worksheet("AuditLog")
except Exception:
    audit_sheet = None

# Optional: Locations sheet for geo-fencing
try:
    locations_sheet = spreadsheet.worksheet("Locations")
except Exception:
    locations_sheet = None





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

DRIVE_TOKEN_PATH = os.path.join(BASE_DIR, "drive_token.json")
DRIVE_TOKEN_ENV = os.environ.get("DRIVE_TOKEN_JSON", "").strip()

def _make_oauth_flow():
    if not (OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and OAUTH_REDIRECT_URI):
        raise RuntimeError("Missing OAuth env vars: OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET / OAUTH_REDIRECT_URI")
    client_config = {
        "web": {
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [OAUTH_REDIRECT_URI],
        }
    }
    return Flow.from_client_config(client_config, scopes=OAUTH_SCOPES, redirect_uri=OAUTH_REDIRECT_URI)

def _save_drive_token(token_dict: dict):
    try:
        with open(DRIVE_TOKEN_PATH, "w", encoding="utf-8") as f:
            json.dump(token_dict, f)
    except Exception:
        pass

def _load_drive_token() -> dict | None:
    try:
        if os.path.exists(DRIVE_TOKEN_PATH):
            with open(DRIVE_TOKEN_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    if DRIVE_TOKEN_ENV:
        try:
            return json.loads(DRIVE_TOKEN_ENV)
        except Exception:
            return None
    return None

def get_user_drive_service():
    token_data = session.get("drive_token") or _load_drive_token()
    if not token_data:
        return None

    creds_user = UserCredentials(**token_data)
    if creds_user.expired and creds_user.refresh_token:
        creds_user.refresh(Request())
        token_data["token"] = creds_user.token
        if creds_user.refresh_token:
            token_data["refresh_token"] = creds_user.refresh_token
        session["drive_token"] = token_data
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


# ================= PREMIUM UI =================
STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root{
  --bg:#f4f7fb;
  --card:#ffffff;
  --text:#0b1220;
  --muted:#5b667a;
  --border:rgba(11,18,32,.10);
  --shadow: 0 10px 28px rgba(11,18,32,.08);
  --shadow2: 0 16px 46px rgba(11,18,32,.12);
  --radius: 20px;

  /* Brand: Navy + Green */
  --navy:#0a2a5e;
  --navy2:#0b3a7a;
  --navySoft:rgba(10,42,94,.10);
  --green:#16a34a;
  --red:#dc2626;
  --amber:#f59e0b;

  --h1: clamp(26px, 5vw, 38px);
  --h2: clamp(16px, 3vw, 20px);
  --small: clamp(12px, 2vw, 14px);
}

*{box-sizing:border-box;}
html,body{height:100%;}
body{
  margin:0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  background:
    radial-gradient(950px 520px at 18% 0%, rgba(10,42,94,.12) 0%, rgba(10,42,94,0) 62%),
    radial-gradient(900px 520px at 82% 10%, rgba(22,163,74,.10) 0%, rgba(22,163,74,0) 62%),
    linear-gradient(180deg, rgba(255,255,255,.70), rgba(255,255,255,0) 40%),
    var(--bg);
  color: var(--text);
  padding: 16px 14px calc(90px + env(safe-area-inset-bottom)) 14px;
}
a{color:inherit;text-decoration:none;}
h1{font-size:var(--h1); margin:0; font-weight:700; letter-spacing:.2px;}
h2{font-size:var(--h2); margin: 0 0 8px 0; font-weight:600;}
.sub{color:var(--muted); margin:6px 0 0 0; font-size:var(--small); line-height:1.35; font-weight:400;}

.card{
  background: color-mix(in srgb, var(--card) 88%, rgba(255,255,255,.0));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  backdrop-filter: blur(10px);
  transition: transform .16s ease, box-shadow .16s ease, background .16s ease, border-color .16s ease;
}

.badge{
  font-size: 12px;
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid rgba(11,18,32,.12);
  background: rgba(255,255,255,.75);
  color: rgba(11,18,32,.72);
  font-weight:600;
  white-space: nowrap;
}
.badge.admin{
  background: var(--navy);
  color:#ffffff;
  border: 1px solid rgba(255,255,255,.12);
}

.menuItem, .btnSoft, .navIcon, .sideItem, .input{
  transition: transform .16s ease, box-shadow .16s ease, background .16s ease, border-color .16s ease;
}
.menuItem:hover, .sideItem:hover{ transform: translateY(-1px); box-shadow: var(--shadow2); }
.btnSoft:hover{ transform: translateY(-1px); box-shadow: var(--shadow2); }

.shell{ max-width: 560px; margin: 0 auto; }
.sidebar{ display:none; }
.main{ width:100%; }

.headerTop{
  display:flex; align-items:flex-start; justify-content:space-between; gap:12px;
  margin-bottom: 14px;
}

.kpiRow{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 12px;
}
.kpi{ padding:14px; }
.kpi .label{font-size:var(--small); color:var(--muted); margin:0; font-weight:400;}
.kpi .value{font-size: 28px; font-weight:700; margin: 6px 0 0 0; font-variant-numeric: tabular-nums;}

.graphCard{ margin-top: 12px; padding: 14px; }
.graphTop{ display:flex; align-items:center; justify-content:space-between; gap:12px; }
.graphTitle{ font-weight:600; font-size: 16px; }
.graphRange{ color: var(--muted); font-size: 13px; font-weight:500; }
.bars{
  margin-top: 12px;
  height: 180px;
  display:flex;
  align-items:flex-end;
  justify-content:space-around;
  gap: 12px;
  padding: 10px 6px 0 6px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(10,42,94,.06) 0%, rgba(10,42,94,0) 65%);
  border: 1px solid rgba(10,42,94,.12);
}
.bar{
  width: 16%;
  border-radius: 14px 14px 10px 10px;
  background: linear-gradient(180deg, rgba(10,42,94,.92), rgba(10,42,94,.55));
  box-shadow: 0 8px 18px rgba(10,42,94,.18);
}
.barLabels{
  display:flex; justify-content:space-around; gap:12px;
  margin-top: 10px;
  color: var(--muted);
  font-weight:500;
  font-size: 13px;
}

.menu{ margin-top: 14px; padding: 12px; }
.menuItem{
  display:flex; align-items:center; justify-content:space-between; gap:12px;
  padding: 14px 14px;
  border-radius: 18px;
  background: rgba(255,255,255,.85);
  border: 1px solid rgba(11,18,32,.08);
  margin-top: 10px;
}
.menuItem.active{
  background: var(--navySoft);
  border-color: rgba(10,42,94,.18);
}
.menuLeft{display:flex; align-items:center; gap:12px;}
.icoBox{
  width: 44px; height: 44px;
  border-radius: 14px;
  background: rgba(255,255,255,.92);
  border: 1px solid rgba(11,18,32,.08);
  display:grid; place-items:center;
  color: var(--navy);
}
.icoBox svg{ width: 22px; height: 22px; }
.menuText{
  font-weight:600;
  font-size: 18px;
  letter-spacing:.1px;
  color: var(--navy);
}
.chev{
  font-size: 26px;
  color: color-mix(in srgb, var(--navy) 88%, #000);
  font-weight:600;
}

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
.input:focus{ border-color: rgba(10,42,94,.35); box-shadow: 0 0 0 3px rgba(10,42,94,.10); }

.row2{ display:grid; grid-template-columns: 1fr 1fr; gap:10px; }
@media (max-width: 520px){ .row2{ grid-template-columns: 1fr; } }

.message{
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 18px;
  font-weight:600;
  text-align:center;
  background: rgba(22,163,74,.10);
  border: 1px solid rgba(22,163,74,.18);
}
.message.error{ background: rgba(220,38,38,.10); border-color: rgba(220,38,38,.20); }

.clockCard{ margin-top: 12px; padding: 14px; }
.timerBig{
  font-weight:700;
  font-size: clamp(26px, 6vw, 36px);
  margin-top: 6px;
  font-variant-numeric: tabular-nums;
}
.timerSub{ color: var(--muted); font-weight:400; font-size: 13px; margin-top: 6px; }
.actionRow{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 14px;
}
.btn{
  border:none;
  border-radius: 18px;
  padding: 14px 12px;
  font-weight:600;
  font-size: 15px;
  cursor:pointer;
  box-shadow: 0 10px 18px rgba(11,18,32,.08);
  transition: transform .16s ease, box-shadow .16s ease, filter .16s ease;
}
.btn:hover{ transform: translateY(-1px); filter: brightness(1.02); }
.btn:active{ transform: translateY(0px); filter: brightness(.98); }
.btnIn{ background: var(--green); color: white;}
.btnOut{ background: var(--red); color: white;}

.btnSoft{
  width:100%;
  border:none;
  border-radius: 18px;
  padding: 12px 12px;
  font-weight:600;
  font-size: 14px;
  cursor:pointer;
  background: rgba(10,42,94,.10);
  color: var(--navy);
}

.btnTiny{
  border:none;
  border-radius: 14px;
  padding: 10px 10px;
  font-weight:600;
  font-size: 13px;
  cursor:pointer;
  background: rgba(10,42,94,.10);
  color: var(--navy);
  white-space: nowrap;
}
.btnTiny.dark{
  background: rgba(11,18,32,.10);
  color: rgba(11,18,32,.90);
}

.tablewrap{ margin-top:14px; overflow:auto; border-radius: 18px; border:1px solid rgba(11,18,32,.10); }
table{ width:100%; border-collapse: collapse; min-width: 720px; background: rgba(255,255,255,.92); }
th,td{ padding: 10px 10px; border-bottom: 1px solid rgba(11,18,32,.08); text-align:left; font-size: 14px; vertical-align: top;}
th{ position: sticky; top:0; background: rgba(248,250,252,.96); font-weight:500; }
table tbody tr:nth-child(even){ background: rgba(11,18,32,.02); }
table tbody tr:hover{ background: rgba(10,42,94,.04); }

/* Pro numeric formatting */
.num{ text-align:right; font-variant-numeric: tabular-nums; }

/* Row emphasis if gross > 0 */
.rowHasValue{ background: rgba(10,42,94,.035) !important; }

/* Overtime highlight */
.overtimeRow{ outline: 2px solid rgba(245,158,11,.30); background: rgba(245,158,11,.06) !important; }
.overtimeChip{
  display:inline-flex; align-items:center;
  padding: 4px 10px; border-radius:999px;
  font-size:12px; font-weight:600;
  background: rgba(245,158,11,.14);
  border: 1px solid rgba(245,158,11,.22);
  color: rgba(146,64,14,.95);
}

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
.badLabel{ color: rgba(220,38,38,.92) !important; font-weight:600 !important; }
.uploadTitle{
  margin-top: 12px;
  font-weight:600;
  font-size: 14px;
  color: var(--navy);
}

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
}
.navIcon.active{ background: rgba(10,42,94,.10); }
.navIcon svg{ width: 22px; height: 22px; }

.safeBottom{ height: calc(120px + env(safe-area-inset-bottom)); }

/* Status chips */
.chip{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight:500;
  border: 1px solid rgba(11,18,32,.12);
  background: rgba(255,255,255,.80);
  color: rgba(11,18,32,.76);
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

/* Avatar bubble */
.avatar{
  width: 34px;
  height: 34px;
  border-radius: 999px;
  display:grid;
  place-items:center;
  font-weight:600;
  color: var(--navy);
  background: rgba(10,42,94,.08);
  border: 1px solid rgba(10,42,94,.14);
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
  font-weight:500;
  border: 1px solid rgba(11,18,32,.12);
  background: rgba(255,255,255,.75);
  color: rgba(11,18,32,.72);
}
.weekPill.active{
  background: var(--navySoft);
  border-color: rgba(10,42,94,.18);
  color: var(--navy);
}

/* KPI strip */
.kpiStrip{
  margin-top: 12px;
  display:grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
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
.kpiMini .k{ font-size: 12px; color: var(--muted); font-weight:400; }
.kpiMini .v{ margin-top:6px; font-size: 18px; font-weight:600; font-variant-numeric: tabular-nums; }

/* Weekly net badge */
.netBadge{
  display:inline-flex;
  align-items:center;
  gap:8px;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid rgba(10,42,94,.18);
  background: rgba(10,42,94,.10);
  color: var(--navy);
  font-weight:600;
  font-variant-numeric: tabular-nums;
}

/* Dark mode toggle */
body.dark{
  --bg:#081225;
  --card:#0b1730;
  --text:#e7edf7;
  --muted:#a6b0c4;
  --border:rgba(255,255,255,.10);
  --shadow: 0 10px 28px rgba(0,0,0,.35);
  --shadow2: 0 16px 46px rgba(0,0,0,.45);
}
body.dark .menuItem,
body.dark .sideItem,
body.dark table,
body.dark .input,
body.dark .kpiMini{
  background: rgba(255,255,255,.04) !important;
}
body.dark th{
  background: rgba(255,255,255,.06) !important;
}
.themeToggle{
  position: fixed;
  top: 14px;
  right: 14px;
  z-index: 999;
  width: 44px; height: 44px;
  border-radius: 16px;
  border: 1px solid var(--border);
  background: rgba(255,255,255,.85);
  backdrop-filter: blur(10px);
  display:grid;
  place-items:center;
  cursor:pointer;
  box-shadow: var(--shadow);
  font-weight:600;
}
body.dark .themeToggle{ background: rgba(255,255,255,.06); }

/* ===== Desktop wide layout (FULL WIDTH) ===== */
@media (min-width: 980px){
  body{ padding: 18px 18px 22px 18px; }
  .shell{
    max-width: none;
    width: calc(100vw - 36px);
    margin: 0 auto;
    display: grid;
    grid-template-columns: 320px 1fr;
    gap: 18px;
    align-items: start;
  }
  .bottomNav{ display:none; }
  .sidebar{
    display:flex;
    flex-direction:column;
    gap: 10px;
    position: sticky;
    top: 18px;
    height: calc(100vh - 36px);
    overflow: hidden;
    padding: 14px;
  }
  .sideScroll{
    overflow:auto;
    padding-right: 4px;
    flex: 1 1 auto;
  }
  .sideTitle{
    font-weight:600;
    font-size: 14px;
    color: rgba(11,18,32,.80);
    margin: 0 0 10px 2px;
  }
  .sideItem{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:12px;
    padding: 12px 12px;
    border-radius: 16px;
    background: rgba(255,255,255,.85);
    border: 1px solid rgba(11,18,32,.08);
    margin-top: 10px;
  }
  .sideItem.active{
    background: var(--navySoft);
    border-color: rgba(10,42,94,.16);
  }
  .sideLeft{ display:flex; align-items:center; gap:12px; }
  .sideText{ font-weight:600; font-size: 15px; letter-spacing:.1px; }
  .sideIcon{
    width: 40px; height: 40px;
    border-radius: 14px;
    background: rgba(255,255,255,.92);
    border: 1px solid rgba(11,18,32,.08);
    display:grid; place-items:center;
    color: var(--navy);
  }
  .sideIcon svg{ width:20px; height:20px; }

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

/* Print tidy */
@media print{
  .sidebar, .bottomNav, .themeToggle, button, input, select, .weekRow { display:none !important; }
  body{ padding:0 !important; background:#fff !important; }
  .shell{ width:100% !important; max-width:none !important; grid-template-columns: 1fr !important; }
  .card{ box-shadow:none !important; }
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
        base_headers = ["Username","Date","ClockIn","ClockOut","Hours","Pay"]
        # If there is no header row, do nothing (your sheet should have one).
        if not headers:
            return
        # Extend header row safely
        if len(headers) < len(base_headers):
            headers = base_headers[:]
        missing = [h for h in WORKHOURS_GEO_HEADERS if h not in headers]
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

def _get_employee_site(username: str) -> str:
    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return ""
        headers = vals[0]
        if "Username" not in headers or "Site" not in headers:
            return ""
        ucol = headers.index("Username")
        scol = headers.index("Site")
        for i in range(1, len(vals)):
            row = vals[i]
            if len(row) > ucol and (row[ucol] or "").strip() == username:
                return (row[scol] if scol < len(row) else "").strip()
    except Exception:
        return ""
    return ""

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
        i_name = idx("SiteName"); i_lat = idx("Lat"); i_lon = idx("Lon"); i_rad = idx("RadiusMeters"); i_act = idx("Active")
        for r in vals[1:]:
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

def _validate_user_location(username: str, lat: float | None, lon: float | None) -> tuple[bool, dict, float]:
    """Returns (ok, site_cfg, distance_m). ok=False if outside radius or missing config."""
    site_pref = _get_employee_site(username)
    cfg = _get_site_config(site_pref)
    if not cfg:
        return False, {"name": site_pref or "Unknown", "lat": 0.0, "lon": 0.0, "radius": 0.0}, 0.0
    if lat is None or lon is None:
        return False, cfg, 0.0
    dist = _haversine_m(float(lat), float(lon), cfg["lat"], cfg["lon"])
    ok = dist <= float(cfg["radius"])
    return ok, cfg, dist
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
    for r in rows[1:]:
        if len(r) > COL_DATE and r[COL_USER] == username and r[COL_DATE] == today_str:
            return True
    return False

def find_open_shift(rows, username: str):
    for i in range(len(rows) - 1, 0, -1):
        r = rows[i]
        if len(r) > COL_OUT and r[COL_USER] == username and r[COL_OUT] == "":
            return i, r[COL_DATE], r[COL_IN]
    return None

def get_sheet_headers(sheet):
    vals = sheet.get_all_values()
    return vals[0] if vals else []

def find_row_by_username(sheet, username: str):
    vals = sheet.get_all_values()
    if not vals:
        return None
    headers = vals[0]
    if "Username" not in headers:
        return None
    ucol = headers.index("Username")
    for i in range(1, len(vals)):
        row = vals[i]
        if len(row) > ucol and row[ucol] == username:
            return i + 1
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
        fn_col = headers.index("FirstName") if "FirstName" in headers else None
        ln_col = headers.index("LastName") if "LastName" in headers else None
        for i in range(1, len(vals)):
            row = vals[i]
            if len(row) > ucol and row[ucol] == username:
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
    fcol = headers.index(field) + 1
    rownum = None
    for i in range(1, len(vals)):
        row = vals[i]
        if len(row) > ucol and row[ucol] == username:
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
    fn_col = headers.index("FirstName") + 1 if "FirstName" in headers else None
    ln_col = headers.index("LastName") + 1 if "LastName" in headers else None
    if not fn_col and not ln_col:
        return
    rownum = None
    for i in range(1, len(vals)):
        row = vals[i]
        if len(row) > ucol and row[ucol] == username:
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
    pcol = headers.index("Password") + 1
    hashed = generate_password_hash(new_password)
    for i in range(1, len(vals)):
        row = vals[i]
        if len(row) > ucol and row[ucol] == username:
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

def update_or_append_onboarding(username: str, data: dict):
    headers = get_sheet_headers(onboarding_sheet)
    if not headers or "Username" not in headers:
        raise RuntimeError("Onboarding sheet must have header row with 'Username'.")
    rownum = find_row_by_username(onboarding_sheet, username)

    row_values = []
    for h in headers:
        if h == "Username":
            row_values.append(username)
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
    for i in range(1, len(vals)):
        row = vals[i]
        if len(row) > ucol and row[ucol] == username:
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
          <a class="sideItem {'active' if active==key else ''}" href="{href}">
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

def layout_shell(active: str, role: str, content_html: str) -> str:
    theme_toggle = """
    <button class="themeToggle" id="themeToggle" title="Toggle dark mode">☾</button>
    <script>
    (function(){
      const key="wh_theme";
      const btn=document.getElementById("themeToggle");
      const set=(v)=>{ document.body.classList.toggle("dark", v==="dark"); btn.textContent = (v==="dark") ? "☀" : "☾"; };
      const saved=localStorage.getItem(key) || "light";
      set(saved);
      btn.addEventListener("click", ()=>{
        const now = document.body.classList.contains("dark") ? "light" : "dark";
        localStorage.setItem(key, now);
        set(now);
      });
    })();
    </script>
    """
    return f"""
      <div class="shell">
        {sidebar_html(active, role)}
        <div class="main">
          {content_html}
          <div class="safeBottom"></div>
        </div>
      </div>
      {theme_toggle}
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
    session["drive_token"] = token_dict
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

        for user in employees_sheet.get_all_records():
            if user.get("Username") == username and is_password_valid(user.get("Password", ""), password):
                migrate_password_if_plain(username, user.get("Password", ""), password)
                session.clear()
                session["csrf"] = csrf
                session["username"] = username
                session["role"] = user.get("Role", "employee")
                session["rate"] = safe_float(user.get("Rate", 0), 0.0)
                session["early_access"] = parse_bool(user.get("EarlyAccess", False))
                return redirect(url_for("home"))

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
def logout():
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

    now = datetime.now(TZ)
    today = now.date()
    rows = work_sheet.get_all_values()

    monday = today - timedelta(days=today.weekday())

    def week_key_for_n(n: int):
        d2 = monday - timedelta(days=7*n)
        yy, ww, _ = d2.isocalendar()
        return yy, ww

    week_keys = [week_key_for_n(i) for i in range(4, -1, -1)]
    week_labels = [str(k[1]) for k in week_keys]
    weekly_gross = [0.0] * 5

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if (r[COL_USER] or "").strip() != username:
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

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Dashboard</h1>
          <p class="sub">Welcome, {escape(display_name)}</p>
        </div>
        <div class="badge {'admin' if role=='admin' else ''}">{escape(role.upper())}</div>
      </div>

      <div class="kpiRow">
        <div class="card kpi">
          <p class="label">Previous Gross</p>
          <p class="value">£{money(prev_gross)}</p>
        </div>
        <div class="card kpi">
          <p class="label">Current Gross</p>
          <p class="value">£{money(curr_gross)}</p>
        </div>
      </div>

      <div class="card graphCard">
        <div class="graphTop">
          <div class="graphTitle">Weekly Gross</div>
          <div class="graphRange">Weeks {escape(week_labels[0])} – {escape(week_labels[-1])}</div>
        </div>
        <div class="bars">{bars_html}</div>
        <div class="barLabels">{labels_html}</div>
      </div>

      <div class="card menu">
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

        ok_loc, cfg, dist_m = _validate_user_location(username, lat_v, lon_v)

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
                    # Append base columns
                    work_sheet.append_row([username, today_str, cin, "", "", ""])
                    # Find the row we just added and store geo fields
                    vals = work_sheet.get_all_values()
                    rownum = _find_workhours_row_by_user_date(vals, username, today_str)
                    if rownum:
                        headers = vals[0]
                        def col(name):
                            return headers.index(name) + 1 if name in headers else None
                        for k, v in [
                            ("InLat", lat_v), ("InLon", lon_v), ("InAcc", acc_v),
                            ("InSite", cfg["name"]), ("InDistM", int(dist_m)),
                        ]:
                            c = col(k)
                            if c:
                                work_sheet.update_cell(rownum, c, "" if v is None else str(v))
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
                    hours_rounded = _apply_unpaid_break(raw_hours)
                    pay = round(hours_rounded * rate, 2)

                    sheet_row = i + 1  # find_open_shift returns index in rows list
                    work_sheet.update_cell(sheet_row, COL_OUT + 1, now.strftime("%H:%M:%S"))
                    work_sheet.update_cell(sheet_row, COL_HOURS + 1, hours_rounded)
                    work_sheet.update_cell(sheet_row, COL_PAY + 1, pay)

                    # store geo fields (clock-out)
                    vals = work_sheet.get_all_values()
                    headers = vals[0] if vals else []
                    def col(name):
                        return headers.index(name) + 1 if name in headers else None
                    for k, v in [
                        ("OutLat", lat_v), ("OutLon", lon_v), ("OutAcc", acc_v),
                        ("OutSite", cfg["name"]), ("OutDistM", int(dist_m)),
                    ]:
                        c = col(k)
                        if c:
                            work_sheet.update_cell(sheet_row, c, "" if v is None else str(v))

                    msg = f"Clocked Out • {cfg['name']} ({int(dist_m)}m) • Break deducted: {UNPAID_BREAK_HOURS}h"
            else:
                msg = "Invalid action."
                msg_class = "message error"

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
        <div class="timerSub">Start: {escape(active_start_label)} • Break: {UNPAID_BREAK_HOURS}h (deducted on Clock Out)</div>
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
            }}
            tick(); setInterval(tick, 1000);
          }})();
        </script>
        """
    else:
        timer_html = f"""
        <div class="timerSub">No active session</div>
        <div class="timerBig">00:00:00</div>
        <div class="timerSub">Clock in to start the live timer. Break deducted on Clock Out: {UNPAID_BREAK_HOURS}h</div>
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
        <div class="badge {{'admin' if role=='admin' else ''}}">{escape(role.upper())}</div>
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

    rows = work_sheet.get_all_values()
    body = []
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if (r[COL_USER] or "").strip() != username:
            continue
        body.append(
            f"<tr><td>{escape(r[COL_DATE])}</td><td>{escape(r[COL_IN])}</td>"
            f"<td>{escape(r[COL_OUT])}</td><td class='num'>{escape(r[COL_HOURS])}</td><td class='num'>£{escape(r[COL_PAY])}</td></tr>"
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

      <div class="card" style="padding:12px;">
        <div class="tablewrap">
          <table style="min-width:640px;">
            <thead><tr><th>Date</th><th>Clock In</th><th>Clock Out</th><th class='num'>Hours</th><th class='num'>Pay</th></tr></thead>
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
    daily_hours = daily_pay = 0.0
    weekly_hours = weekly_pay = 0.0
    monthly_hours = monthly_pay = 0.0

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if (r[COL_USER] or "").strip() != username:
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
        tax = round(gross * TAX_RATE, 2)
        net = round(gross - tax, 2)
        return round(gross, 2), tax, net

    d_g, d_t, d_n = gross_tax_net(daily_pay)
    w_g, w_t, w_n = gross_tax_net(weekly_pay)
    m_g, m_t, m_n = gross_tax_net(monthly_pay)

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
          <p class="value">£{money(d_g)}</p>
          <p class="sub">Hours: {round(daily_hours,2)} • Tax: £{money(d_t)} • Net: £{money(d_n)}</p>
        </div>
        <div class="card kpi">
          <p class="label">This Week Gross</p>
          <p class="value">£{money(w_g)}</p>
          <p class="sub">Hours: {round(weekly_hours,2)} • Tax: £{money(w_t)} • Net: £{money(w_n)}</p>
        </div>
      </div>

      <div class="card kpi" style="margin-top:12px;">
        <p class="label">This Month Gross</p>
        <p class="value">£{money(m_g)}</p>
        <p class="sub">Hours: {round(monthly_hours,2)} • Tax: £{money(m_t)} • Net: £{money(m_n)}</p>
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

            if not _load_drive_token() and not session.get("drive_token"):
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
            if user.get("Username") == username:
                stored_pw = user.get("Password", "")
                break

        if stored_pw is None or not is_password_valid(stored_pw, current):
            msg = "Current password is incorrect."
            ok = False
        elif len(new1) < 4:
            msg = "New password too short (min 4)."
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
        for r in vals[1:]:
            if len(r) > ucol and r[ucol] == username:
                if rcol is not None and rcol < len(r):
                    return safe_float(r[rcol], 0.0)
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

        for r in rows[1:]:
            if len(r) <= max(i_user, i_date, i_in, i_out):
                continue
            u = (r[i_user] or "").strip()
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

    open_shifts = _get_open_shifts()
    if open_shifts:
        rows = []
        for s in open_shifts:
            rate = _get_user_rate(s["user"])
            rows.append(f"""
              <tr>
                <td>
                  <div style="display:flex; align-items:center; gap:10px;">
                    <div class="avatar">{escape(initials(s['name']))}</div>
                    <div>
                      <div style="font-weight:600;">{escape(s['name'])}</div>
                      <div class="sub" style="margin:2px 0 0 0;">{escape(s['user'])}</div>
                    </div>
                  </div>
                </td>
                <td>{escape(s['start_label'])}</td>
                <td class="num"><span class="netBadge" data-live-start="{escape(s['start_iso'])}">00:00:00</span></td>
                <td class="num" data-est-hours="{escape(s['start_iso'])}">0.00</td>
                <td class="num" data-est-pay="{escape(s['start_iso'])}" data-rate="{rate}">£0.00</td>
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
          <div class="card" style="padding:12px; margin-top:12px;">
            <h2>Live Clocked-In</h2>
            <p class="sub">Employees currently clocked in. Live time updates every second.</p>
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
                    el.textContent = (Math.round(hrs*100)/100).toFixed(2);
                  }});

                  document.querySelectorAll("[data-est-pay]").forEach(el=>{{
                    const startIso = el.getAttribute("data-est-pay");
                    const rate = parseFloat(el.getAttribute("data-rate") || "0") || 0;
                    const start = new Date(startIso);
                    let hrs = (now - start) / 3600000.0;
                    if(hrs < 0) hrs = 0;
                    if(hrs >= {BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS}) hrs = Math.max(0, hrs - {UNPAID_BREAK_HOURS});
                    const pay = hrs * rate;
                    el.textContent = "£" + pay.toFixed(2);
                  }});
                }}
                tick(); setInterval(tick, 1000);
              }})();
            </script>
          </div>
        """
    else:
        open_html = f"""
          <div class="card" style="padding:12px; margin-top:12px;">
            <h2>Live Clocked-In</h2>
            <p class="sub">No one is currently clocked in.</p>
          </div>
        """

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Admin</h1>
          <p class="sub">Payroll + onboarding</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      <div class="card menu">
        <a class="menuItem active" href="/admin/payroll">
          <div class="menuLeft"><div class="icoBox">{_svg_chart()}</div><div class="menuText">Payroll Report</div></div>
          <div class="chev">›</div>
        </a>
        <a class="menuItem" href="/admin/onboarding">
          <div class="menuLeft"><div class="icoBox">{_svg_doc()}</div><div class="menuText">Onboarding</div></div>
          <div class="chev">›</div>
        </a>
        <a class="menuItem" href="/admin/locations">
          <div class="menuLeft"><div class="icoBox">{_svg_grid()}</div><div class="menuText">Locations</div></div>
          <div class="chev">›</div>
        </a>
        <a class="menuItem" href="/admin/employee-sites">
          <div class="menuLeft"><div class="icoBox">{_svg_user()}</div><div class="menuText">Employee Sites</div></div>
          <div class="chev">›</div>
        </a>
        <a class="menuItem" href="/connect-drive">
          <div class="menuLeft"><div class="icoBox">{_svg_grid()}</div><div class="menuText">Connect Drive</div></div>
          <div class="chev">›</div>
        </a>
      </div>

      {open_html}
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", "admin", content))


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

    if recalc:
        computed = _compute_hours_from_times(date_str, cin, cout)
        if computed is not None:
            hours_val = computed
            pay_val = round(computed * rate, 2)

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
            work_sheet.append_row([username, date_str, cin, cout, hours_cell, pay_cell])
    except Exception:
        pass

    return redirect(request.referrer or "/admin/payroll")



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

    try:
        work_sheet.update_cell(sheet_row, COL_OUT + 1, out_time)
        work_sheet.update_cell(sheet_row, COL_HOURS + 1, str(computed_hours))
        work_sheet.update_cell(sheet_row, COL_PAY + 1, str(pay))
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
        username = (request.form.get("user") or "").strip()

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

    q = (request.args.get("q", "") or "").strip().lower()
    date_from = (request.args.get("from", "") or "").strip()
    date_to = (request.args.get("to", "") or "").strip()

    rows = work_sheet.get_all_values()

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

    overall_tax = round(overall_gross * TAX_RATE, 2)
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
            un = (rec.get("Username") or "").strip()
            if un:
                all_users.append(un)
    except Exception:
        all_users = list(by_user.keys())

    if q:
        all_users = [u for u in all_users if q in u.lower() or q in (get_employee_display_name(u) or "").lower()]

    # Week pills
    pills = []
    for i in range(0, 13):
        d0 = this_monday - timedelta(days=7*i)
        active = "active" if i == wk_offset else ""
        pills.append(
            f"<a class='weekPill {active}' href='/admin/payroll?wk={i}&q={escape(q)}&from={escape(date_from)}&to={escape(date_to)}'>"
            f"{escape(week_label(d0))}</a>"
        )
    week_nav_html = "<div class='weekRow'>" + "".join(pills) + "</div>"

    # KPI strip (PRO)
    kpi_strip = f"""
      <div class="kpiStrip">
        <div class="kpiMini"><div class="k">Hours</div><div class="v">{round(overall_hours,2)}</div></div>
        <div class="kpiMini"><div class="k">Gross</div><div class="v">£{money(overall_gross)}</div></div>
        <div class="kpiMini"><div class="k">Tax</div><div class="v">£{money(overall_tax)}</div></div>
        <div class="kpiMini"><div class="k">Net</div><div class="v">£{money(overall_net)}</div></div>
      </div>
    """

    # Summary table (polished + paid under name)
    summary_rows = []
    for u in sorted(all_users, key=lambda s: s.lower()):
        gross = round(by_user.get(u, {}).get("gross", 0.0), 2)
        tax = round(gross * TAX_RATE, 2)
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
                <button class="btnTiny dark" type="submit">Mark Paid</button>
              </form>
            """

        row_class = "rowHasValue" if gross > 0 else ""

        name_cell = f"""
          <div style="display:flex; align-items:center; gap:10px;">
            <div class="avatar">{escape(initials(display))}</div>
            <div>
              <div style="font-weight:600;">{escape(display)}</div>
              <div class="sub" style="margin:2px 0 0 0;">{escape(u)}</div>
              {paid_line}
            </div>
          </div>
        """

        summary_rows.append(
            f"<tr class='{row_class}'>"
            f"<td>{name_cell}</td>"
            f"<td class='num'>{hours:.2f}</td><td class='num'>£{money(gross)}</td><td class='num'>£{money(tax)}</td><td class='num'>£{money(net)}</td>"
            f"<td style='text-align:right;'>{mark_paid_btn}</td>"
            f"</tr>"
        )

    summary_html = "".join(summary_rows) if summary_rows else "<tr><td colspan='6'>No employees.</td></tr>"

    # Per-user weekly editable tables
    day_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    blocks = []
    for u in sorted(all_users, key=lambda s: s.lower()):
        display = get_employee_display_name(u)
        user_days = week_lookup.get(u, {})

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
        wk_tax = round(wk_gross * TAX_RATE, 2)
        wk_net = round(wk_gross - wk_tax, 2)

        paid, paid_at = _is_paid_for_week(week_start_str, week_end_str, u)
        header_chip = "<span class='chip ok'>Paid</span>" if paid else "<span class='chip warn'>Not paid</span>"
        header_sub = f"<span class='sub' style='margin-left:10px;'>Paid at: {escape(paid_at)}</span>" if paid and paid_at else ""

        pay_btn = ""
        if (not paid) and wk_gross > 0:
            pay_btn = f"""
              <form method="POST" action="/admin/mark-paid" style="margin:0;">
                <input type="hidden" name="csrf" value="{escape(csrf)}">
                <input type="hidden" name="week_start" value="{escape(week_start_str)}">
                <input type="hidden" name="week_end" value="{escape(week_end_str)}">
                <input type="hidden" name="user" value="{escape(u)}">
                <input type="hidden" name="gross" value="{wk_gross}">
                <input type="hidden" name="tax" value="{wk_tax}">
                <input type="hidden" name="net" value="{wk_net}">
                <button class="btnTiny dark" type="submit">Mark Paid</button>
              </form>
            """

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

            rows_html.append(f"""
              <tr class="{overtime_row_class}">
                <td><b>{day_names[di]}</b></td>
                <td>{escape(d_str)}</td>
                <td>
                  <form method="POST" action="/admin/save-shift" style="margin:0;">
                    <input type="hidden" name="csrf" value="{escape(csrf)}">
                    <input type="hidden" name="user" value="{escape(u)}">
                    <input type="hidden" name="date" value="{escape(d_str)}">
                    <input class="input" type="time" step="1" name="cin" value="{escape(cin)}" style="margin-top:0; max-width:150px;">
                </td>
                <td>
                    <input class="input" type="time" step="1" name="cout" value="{escape(cout)}" style="margin-top:0; max-width:150px;">
                </td>
                <td>
                    <input class="input" name="hours" value="{escape(str(hrs))}" placeholder="e.g. 8.5" style="margin-top:0; max-width:110px;">
                </td>
                <td>
                    <input class="input" name="pay" value="{escape(str(pay))}" placeholder="e.g. 200" style="margin-top:0; max-width:110px;">
                </td>
                <td style="min-width:260px;">
                    <label class="sub" style="display:flex; align-items:center; gap:8px; margin:0;">
                      <input type="checkbox" name="recalc" value="yes">
                      Recalculate (break deducted)
                    </label>
                    <div style="display:flex; gap:8px; align-items:center; margin-top:8px; flex-wrap:wrap;">
                      <button class="btnTiny" type="submit">Save</button>
                      {status_html}
                      {ot_badge}
                    </div>
                  </form>
                </td>
              </tr>
            """)

        blocks.append(f"""
          <div class="card" style="padding:12px; margin-top:12px;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap;">
              <div style="display:flex; align-items:center; gap:10px;">
                <div class="avatar">{escape(initials(display))}</div>
                <div>
                  <div style="font-weight:600; font-size:16px;">{escape(display)} <span class="sub">({escape(u)})</span></div>
                  <div class="sub" style="margin:4px 0 0 0;">
                    {header_chip}{header_sub}
                    <span class="sub" style="margin-left:10px;">Week totals: Hours {wk_hours:.2f} • Gross £{money(wk_gross)} • Tax £{money(wk_tax)}</span>
                  </div>
                </div>
              </div>

              <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                <span class="netBadge">Weekly Net: £{money(wk_net)}</span>
                {overtime_note}
                {pay_btn}
              </div>
            </div>

            <div class="tablewrap" style="margin-top:12px;">
              <table style="min-width:1100px;">
                <thead>
                  <tr>
                    <th>Day</th><th>Date</th><th>Clock In</th><th>Clock Out</th><th class="num">Hours</th><th class="num">Pay</th><th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(rows_html)}
                </tbody>
              </table>
            </div>
            <p class="sub" style="margin-top:10px;">
              Rule: if shift is ≥ {BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS}h then {UNPAID_BREAK_HOURS}h break is deducted. Overtime highlight: > {OVERTIME_HOURS}h/day.
            </p>
          </div>
        """)

    last_updated = datetime.now(TZ).strftime("%d %b %Y • %H:%M")

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Payroll Report</h1>
          <p class="sub">Printable • Updated {escape(last_updated)} • Weekly tables auto-update every week</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      <div class="card" style="padding:12px;">
        <form method="GET">
          <div class="row2">
            <div>
              <label class="sub">Username contains</label>
              <input class="input" name="q" value="{escape(q)}" placeholder="e.g. john">
            </div>
            <div>
              <label class="sub">Date range (summary table only)</label>
              <div class="row2">
                <input class="input" type="date" name="from" value="{escape(date_from)}">
                <input class="input" type="date" name="to" value="{escape(date_to)}">
              </div>
            </div>
          </div>
          <input type="hidden" name="wk" value="{wk_offset}">
          <button class="btnSoft" type="submit" style="margin-top:12px;">Apply</button>
        </form>

        {week_nav_html}

        {kpi_strip}

        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:980px;">
            <thead><tr><th>Employee</th><th class="num">Hours</th><th class="num">Gross</th><th class="num">Tax</th><th class="num">Net</th><th style="text-align:right;">Paid</th></tr></thead>
            <tbody>{summary_html}</tbody>
          </table>
        </div>
      </div>

      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>Weekly History (Editable)</h2>
        <p class="sub">Week: <b>{escape(week_start_str)}</b> to <b>{escape(week_end_str)}</b>. Edit and save per day.</p>
      </div>

      {''.join(blocks)}
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", "admin", content))


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

        rows_html = []
        for r in vals[1:]:
            u = r[i_user] if i_user is not None and i_user < len(r) else ""
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
                rows = vals[1:] if "SiteName" in headers else vals
                for r in rows:
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
            <td><b>{escape(s.get('name',''))}</b><div class='sub' style='margin:2px 0 0 0;'>{badge}</div></td>
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

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Locations</h1>
          <p class="sub">Clock in/out will only work inside an allowed location radius.</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

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
        for i in range(start_idx, len(vals)):
            r = vals[i]
            n = (r[0] if len(r) > 0 else "").strip()
            if n.lower() == name.strip().lower():
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
    row = [name, lat, lon, rad, active]
    try:
        if rownum:
            locations_sheet.update(f"A{rownum}:E{rownum}", [row])
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
    site_opts = "".join([f"<option value='{escape(n)}'>{escape(n)}</option>" for n in site_names])

    # Employees list
    vals = employees_sheet.get_all_values()
    if not vals:
        body = "<tr><td colspan='4'>No employees found.</td></tr>"
    else:
        headers = vals[0]
        def idx(n): return headers.index(n) if n in headers else None
        i_user = idx("Username")
        i_fn = idx("FirstName")
        i_ln = idx("LastName")
        i_site = idx("Site")

        rows_html = []
        for r in vals[1:]:
            if i_user is None or i_user >= len(r):
                continue
            u = (r[i_user] or "").strip()
            if not u:
                continue
            fn = (r[i_fn] or "").strip() if i_fn is not None and i_fn < len(r) else ""
            ln = (r[i_ln] or "").strip() if i_ln is not None and i_ln < len(r) else ""
            cur_site = (r[i_site] or "").strip() if i_site is not None and i_site < len(r) else ""
            disp = (fn + " " + ln).strip() or u

            # Build dropdown with current selected (if present)
            opts = []
            if cur_site and cur_site not in site_names:
                opts.append(f"<option value='{escape(cur_site)}' selected>{escape(cur_site)} (inactive)</option>")
            if site_names:
                for n in site_names:
                    sel = "selected" if (n.strip().lower() == cur_site.strip().lower() and cur_site) else ""
                    opts.append(f"<option value='{escape(n)}' {sel}>{escape(n)}</option>")
            else:
                opts.append("<option value='' selected>(No active locations)</option>")

            rows_html.append(f"""
              <tr>
                <td>
                  <div style='display:flex; align-items:center; gap:10px;'>
                    <div class='avatar'>{escape(initials(disp))}</div>
                    <div>
                      <div style='font-weight:600;'>{escape(disp)}</div>
                      <div class='sub' style='margin:2px 0 0 0;'>{escape(u)}</div>
                    </div>
                  </div>
                </td>
                <td style='min-width:220px;'>
                  <form method='POST' action='/admin/employee-sites/save' style='margin:0; display:flex; gap:8px; align-items:center; flex-wrap:wrap;'>
                    <input type='hidden' name='csrf' value='{escape(csrf)}'>
                    <input type='hidden' name='user' value='{escape(u)}'>
                    <select class='input' name='site' style='margin-top:0; max-width:220px;'>
                      {''.join(opts)}
                    </select>
                    <button class='btnTiny' type='submit'>Save</button>
                  </form>
                </td>
                <td class='sub'>{escape(cur_site) if cur_site else ''}</td>
              </tr>
            """)

        body = "".join(rows_html) if rows_html else "<tr><td colspan='4'>No employees found.</td></tr>"

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Employee Sites</h1>
          <p class="sub">Assign each employee to a site (used for geo-fence clock in/out).</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      <div class="card" style="padding:12px;">
        <p class="sub" style="margin-top:0;">
          This updates the <b>Employees → Site</b> column. Each employee will be validated against their assigned site in <b>Locations</b>.
        </p>
        <a href="/admin/locations" style="display:inline-block; margin-top:8px;">
          <button class="btnSoft" type="button">Manage Locations</button>
        </a>
      </div>

      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>Employees</h2>
        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:980px;">
            <thead><tr><th>Employee</th><th>Assign site</th><th>Current</th></tr></thead>
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
    site = (request.form.get("site") or "").strip()

    if u:
        # Ensure "Site" column exists
        try:
            headers = get_sheet_headers(employees_sheet)
            if headers and "Site" not in headers:
                # append header (minimal and safe)
                headers2 = headers + ["Site"]
                end_col = gspread.utils.rowcol_to_a1(1, len(headers2)).replace("1", "")
                employees_sheet.update(f"A1:{end_col}1", [headers2])
        except Exception:
            pass

        set_employee_field(u, "Site", site)

        actor = session.get("username", "admin")
        log_audit("EMPLOYEE_SITE_SET", actor=actor, username=u, date_str="", details=f"site={site}")

    return redirect("/admin/employee-sites")




# ================= LOCAL RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
