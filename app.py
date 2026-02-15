# ===================== app.py (FULL - PROFESSIONAL MOBILE UI) =====================
# - Dashboard home (like your screenshots: KPI cards + weekly bars + menu list + bottom nav)
# - Separate Clock In/Out page with live session timer + professional buttons
# - Admin Payroll Report (grouped + print + CSV)
# - Onboarding upload titles bigger/clearer
# - Removes "Starter Form is optional"
# - Keeps your Google Sheets + Drive OAuth upload working (no new software)
# - Adds CSRF + password hashing (auto-migrates from plaintext on next login)

import os
import json
import io
import csv
import secrets
from urllib.parse import urlparse

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    session,
    url_for,
    abort,
    Response,
)
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# OAuth (Drive as real user) - fixes: "Service Accounts do not have storage quota"
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials as UserCredentials
from google.auth.transport.requests import Request

# Built-in with Flask/Werkzeug (no extra install)
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


# ================= GOOGLE DRIVE UPLOAD (OAUTH USER) =================
OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive"]

UPLOAD_FOLDER_ID = os.environ.get("ONBOARDING_DRIVE_FOLDER_ID", "").strip()
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "").strip()
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "").strip()
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "").strip()

DRIVE_TOKEN_PATH = os.path.join(BASE_DIR, "drive_token.json")
DRIVE_TOKEN_ENV = os.environ.get("DRIVE_TOKEN_JSON", "").strip()  # optional backup

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

TAX_RATE = 0.20
CLOCKIN_EARLIEST = dtime(8, 0, 0)


# ================= PWA =================
@app.get("/manifest.webmanifest")
def manifest():
    return {
        "name": "WorkHours",
        "short_name": "WorkHours",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f4f6ff",
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


# ================= UI (Dashboard style like your screenshots) =================
STYLE = """
<style>
:root{
  --bg:#f4f6ff;
  --card:#ffffff;
  --text:#0f172a;
  --muted:#64748b;
  --border:rgba(15,23,42,.08);
  --shadow: 0 10px 30px rgba(15,23,42,.08);
  --radius: 22px;

  --purple:#6d28d9;
  --purpleSoft:#efe9ff;
  --blue:#2563eb;
  --green:#16a34a;
  --red:#ef4444;

  --h1: clamp(26px, 5vw, 36px);
  --h2: clamp(16px, 3vw, 20px);
  --p:  clamp(14px, 2.4vw, 17px);
  --small: clamp(12px, 2vw, 14px);
}
*{box-sizing:border-box;}
html,body{height:100%;}
body{
  margin:0;
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  padding: 16px 14px 90px 14px; /* space for bottom nav */
}
a{color:inherit;text-decoration:none;}

.app{max-width: 560px; margin: 0 auto;}

.headerTop{
  display:flex; align-items:flex-start; justify-content:space-between; gap:12px;
  margin-bottom: 14px;
}
h1{font-size:var(--h1); margin:0; letter-spacing:.2px;}
.sub{color:var(--muted); margin:6px 0 0 0; font-size:var(--small);}

.badge{
  font-size: 12px;
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: rgba(255,255,255,.7);
  color: rgba(15,23,42,.70);
  font-weight: 900;
  white-space: nowrap;
}

.card{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

.kpiRow{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap:12px;
  margin-top: 12px;
}
.kpi{
  padding:14px;
}
.kpi .label{font-size:var(--small); color:var(--muted); margin:0;}
.kpi .value{font-size: 26px; font-weight: 950; margin: 6px 0 0 0;}

.chartCard{ margin-top: 12px; padding: 14px;}
.chartHead{
  display:flex; justify-content:center; align-items:center; gap:14px;
  font-weight: 950; font-size: 18px;
}
.chartBars{
  margin-top: 12px;
  height: 170px;
  display:flex;
  align-items:flex-end;
  justify-content:space-around;
  gap: 12px;
  padding: 10px 6px 0 6px;
}
.bar{
  width: 16%;
  border-radius: 12px 12px 6px 6px;
  background: #0b0b0b;
}
.barLabelRow{
  display:flex; justify-content:space-around; gap:12px;
  margin-top: 10px;
  color: var(--muted);
  font-weight: 800;
  font-size: 13px;
}

/* Menu list */
.menu{ margin-top: 14px; padding: 12px; }
.menuItem{
  display:flex; align-items:center; justify-content:space-between; gap:12px;
  padding: 14px 14px;
  border-radius: 18px;
  background: #f7f8ff;
  border: 1px solid rgba(15,23,42,.06);
  margin-top: 10px;
}
.menuItem.active{
  background: var(--purpleSoft);
  border-color: rgba(109,40,217,.10);
}
.menuLeft{display:flex; align-items:center; gap:12px;}
.icoBox{
  width: 44px; height: 44px;
  border-radius: 14px;
  background: rgba(255,255,255,.92);
  border: 1px solid rgba(15,23,42,.06);
  display:grid; place-items:center;
}
.icoBox svg{ width: 22px; height: 22px; }
.menuText{
  font-weight: 950;
  font-size: 20px;
  letter-spacing:.1px;
}
.chev{
  font-size: 26px;
  color: rgba(109,40,217,.90);
  font-weight: 900;
}

/* Forms */
.input{
  width:100%;
  padding: 12px 12px;
  border-radius: 16px;
  border: 1px solid rgba(15,23,42,.10);
  background: #fff;
  font-size: 16px;
  outline:none;
  margin-top: 8px;
}
.input:focus{ border-color: rgba(109,40,217,.35); box-shadow: 0 0 0 3px rgba(109,40,217,.10); }

.row2{ display:grid; grid-template-columns: 1fr 1fr; gap:10px; }
@media (max-width: 520px){ .row2{ grid-template-columns: 1fr; } }

.message{
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 18px;
  font-weight: 900;
  text-align:center;
  background: rgba(22,163,74,.10);
  border: 1px solid rgba(22,163,74,.18);
}
.message.error{ background: rgba(239,68,68,.10); border-color: rgba(239,68,68,.18); }

/* Clock page */
.clockCard{ margin-top: 12px; padding: 14px; }
.timerBig{
  font-weight: 950;
  font-size: clamp(26px, 6vw, 34px);
  margin-top: 6px;
}
.timerSub{ color: var(--muted); font-weight: 800; font-size: 13px; margin-top: 6px; }
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
  font-weight: 950;
  font-size: 16px;
  cursor:pointer;
  box-shadow: 0 10px 18px rgba(15,23,42,.08);
}
.btnIn{ background: var(--green); color: white;}
.btnOut{ background: var(--red); color: white;}
.btnSoft{
  width:100%;
  border:none;
  border-radius: 18px;
  padding: 12px 12px;
  font-weight: 950;
  font-size: 15px;
  cursor:pointer;
  background: rgba(109,40,217,.10);
  color: rgba(109,40,217,.95);
}

/* Tables */
.tablewrap{ margin-top:14px; overflow:auto; border-radius: 18px; border:1px solid rgba(15,23,42,.08); }
table{ width:100%; border-collapse: collapse; min-width: 720px; background:#fff; }
th,td{ padding: 10px 10px; border-bottom: 1px solid rgba(15,23,42,.08); text-align:left; font-size: 14px; }
th{ position: sticky; top:0; background: rgba(248,250,252,.96); }

/* Upload titles */
.uploadLabel{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 18px;
  border: 1px solid rgba(109,40,217,.12);
  background: rgba(109,40,217,.08);
}
.uploadLabel .text{ font-weight: 950; font-size: 18px; color: rgba(15,23,42,.95); }
.uploadLabel .hint{ font-size: 12px; color: rgba(100,116,139,.95); font-weight: 800; }

.bad{
  border: 1px solid rgba(239,68,68,.70) !important;
  box-shadow: 0 0 0 3px rgba(239,68,68,.10) !important;
}
.badLabel{ color: rgba(239,68,68,.95) !important; font-weight: 900; }

/* Bottom nav bar */
.bottomNav{
  position: fixed;
  left: 0; right: 0; bottom: 0;
  background: rgba(255,255,255,.92);
  border-top: 1px solid rgba(15,23,42,.08);
  backdrop-filter: blur(10px);
  padding: 10px 14px 14px 14px;
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
  color: rgba(109,40,217,.92);
}
.navIcon.active{ background: rgba(109,40,217,.10); }
.navIcon svg{ width: 22px; height: 22px; }

/* Print view for payroll report */
.noPrint{ display:block; }
.onlyPrint{ display:none; }
@media print{
  body{ background:#fff; padding:0; }
  .bottomNav, .noPrint{ display:none !important; }
  .onlyPrint{ display:block !important; }
  .app{ max-width:none; }
  .card{ box-shadow:none; }
}
</style>
"""

def _svg_clock():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="9"></circle>
      <path d="M12 7v6l4 2"></path>
    </svg>"""

def _svg_clipboard():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="8" y="2" width="8" height="4" rx="1"></rect>
      <path d="M9 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3"></path>
    </svg>"""

def _svg_chart():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M4 19V5"></path>
      <path d="M4 19h16"></path>
      <path d="M8 17V9"></path>
      <path d="M12 17V7"></path>
      <path d="M16 17v-4"></path>
    </svg>"""

def _svg_doc():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
      <path d="M14 2v6h6"></path>
    </svg>"""

def _svg_user():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M20 21a8 8 0 1 0-16 0"></path>
      <circle cx="12" cy="7" r="4"></circle>
    </svg>"""

def _svg_grid():
    return """<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M4 4h7v7H4z"></path><path d="M13 4h7v7h-7z"></path>
      <path d="M4 13h7v7H4z"></path><path d="M13 13h7v7h-7z"></path>
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
def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def safe_int(x, default=0):
    try:
        return int(str(x).strip())
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
    return f"<a href='{uesc}' target='_blank' rel='noopener noreferrer'>Open</a>"

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

def bottom_nav(active: str, role: str) -> str:
    # active: "home" / "clock" / "times" / "reports" / "profile"
    admin_link = ""
    if role == "admin":
        admin_link = """
        <a class="navIcon" href="/admin" title="Admin">""" + _svg_grid() + """</a>
        """
    return f"""
    <div class="bottomNav">
      <div class="navInner">
        <a class="navIcon {'active' if active=='home' else ''}" href="/" title="Dashboard">{_svg_grid()}</a>
        <a class="navIcon {'active' if active=='clock' else ''}" href="/clock" title="Clock">{_svg_clock()}</a>
        <a class="navIcon {'active' if active=='times' else ''}" href="/my-times" title="Time logs">{_svg_clipboard()}</a>
        <a class="navIcon {'active' if active=='reports' else ''}" href="/my-reports" title="Reports">{_svg_chart()}</a>
        <a class="navIcon {'active' if active=='profile' else ''}" href="/password" title="Profile">{_svg_user()}</a>
        {admin_link}
      </div>
    </div>
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

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
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
          <input class="input" name="username" placeholder="Username" required>
          <label class="sub" style="margin-top:10px; display:block;">Password</label>
          <input class="input" type="password" name="password" placeholder="Password" required>

          <button class="btnSoft" type="submit" style="margin-top:12px;">Login</button>
        </form>

        {("<div class='message error'>" + escape(msg) + "</div>") if msg else ""}
      </div>
    </div>
    """)

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- CHANGE PASSWORD ----------
@app.route("/password", methods=["GET", "POST"])
def change_password():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")

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
            if update_employee_password(username, new1):
                msg = "Password updated successfully."
                ok = True
            else:
                msg = "Could not update password (check Employees sheet headers)."
                ok = False

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="headerTop">
        <div>
          <h1>Profile</h1>
          <p class="sub">Change password</p>
        </div>
        <div class="badge">{escape(username)}</div>
      </div>

      <div class="card" style="padding:14px;">
        {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
        {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

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

        <a href="/logout" style="display:block;margin-top:12px;">
          <button class="btnSoft" type="button" style="background: rgba(239,68,68,.10); color: rgba(239,68,68,.95);">Logout</button>
        </a>
      </div>

      {bottom_nav("profile", role)}
    </div>
    """)


# ---------- DASHBOARD HOME ----------
@app.get("/")
def home():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    now = datetime.now(TZ)
    today = now.date()

    # build last 5 ISO weeks gross for this user
    rows = work_sheet.get_all_values()

    y, w, _ = today.isocalendar()
    monday = today - timedelta(days=today.weekday())

    def week_key_for_n(n: int):
        d2 = monday - timedelta(days=7*n)
        yy, ww, _ = d2.isocalendar()
        return yy, ww

    # oldest -> newest
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

    bars_html = ""
    for g in weekly_gross:
        h = int((g / max_g) * 160)  # px
        bars_html += f"<div class='bar' style='height:{h}px;'></div>"

    labels_html = "".join([f"<div style='width:16%;text-align:center;'>{escape(x)}</div>" for x in week_labels])

    prev_gross = round(sum(weekly_gross[:-1]), 2)
    curr_gross = round(weekly_gross[-1], 2)

    admin_item = ""
    if role == "admin":
        admin_item = f"""
        <a class="menuItem" href="/admin">
          <div class="menuLeft">
            <div class="icoBox" style="color: var(--purple);">{_svg_grid()}</div>
            <div class="menuText" style="color:var(--purple);">Admin</div>
          </div>
          <div class="chev">›</div>
        </a>
        """

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">

      <div class="headerTop">
        <div>
          <h1>Dashboard</h1>
          <p class="sub">Welcome, {escape(username)}</p>
        </div>
        <div class="badge">{escape(role.upper())}</div>
      </div>

      <div class="kpiRow">
        <div class="card kpi">
          <p class="label">Previous Gross</p>
          <p class="value">£{prev_gross}</p>
        </div>
        <div class="card kpi">
          <p class="label">Current Gross</p>
          <p class="value">£{curr_gross}</p>
        </div>
      </div>

      <div class="card chartCard">
        <div class="chartHead">Weeks {escape(week_labels[0])} – {escape(week_labels[-1])}</div>
        <div class="chartBars">{bars_html}</div>
        <div class="barLabelRow">{labels_html}</div>
      </div>

      <div class="card menu">
        <a class="menuItem active" href="/clock">
          <div class="menuLeft">
            <div class="icoBox" style="color: var(--purple);">{_svg_clock()}</div>
            <div class="menuText" style="color:var(--purple);">Clock In & Out</div>
          </div>
          <div class="chev">›</div>
        </a>

        <a class="menuItem" href="/my-times">
          <div class="menuLeft">
            <div class="icoBox" style="color: var(--purple);">{_svg_clipboard()}</div>
            <div class="menuText" style="color:var(--purple);">Time logs</div>
          </div>
          <div class="chev">›</div>
        </a>

        <a class="menuItem" href="/my-reports">
          <div class="menuLeft">
            <div class="icoBox" style="color: var(--blue);">{_svg_chart()}</div>
            <div class="menuText" style="color:var(--blue);">Timesheets</div>
          </div>
          <div class="chev">›</div>
        </a>

        <a class="menuItem" href="/onboarding">
          <div class="menuLeft">
            <div class="icoBox" style="color: var(--purple);">{_svg_doc()}</div>
            <div class="menuText" style="color:var(--purple);">Agreements</div>
          </div>
          <div class="chev">›</div>
        </a>

        {admin_item}

        <a class="menuItem" href="/password">
          <div class="menuLeft">
            <div class="icoBox" style="color: var(--purple);">{_svg_user()}</div>
            <div class="menuText" style="color:var(--purple);">Profile</div>
          </div>
          <div class="chev">›</div>
        </a>
      </div>

      {bottom_nav("home", role)}
    </div>
    """)


# ---------- CLOCK IN / OUT PAGE (LIVE SESSION) ----------
@app.route("/clock", methods=["GET", "POST"])
def clock_page():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")
    rate = safe_float(session.get("rate", 0), 0.0)
    early_access = bool(session.get("early_access", False))

    now = datetime.now(TZ)
    today_str = now.strftime("%Y-%m-%d")

    msg = ""
    msg_class = "message"

    if request.method == "POST":
        require_csrf()
        action = request.form.get("action")

        if action == "in":
            rows = work_sheet.get_all_values()
            if has_any_row_today(rows, username, today_str):
                msg = "You already clocked in today (1 per day)."
                msg_class = "message error"
            elif find_open_shift(rows, username):
                msg = "You are already clocked in."
                msg_class = "message error"
            else:
                cin = normalized_clock_in_time(now, early_access)
                work_sheet.append_row([username, today_str, cin, "", "", ""])
                msg = "Clocked In"
                if (not early_access) and (now.time() < CLOCKIN_EARLIEST):
                    msg = "Clocked In (counted from 08:00)"

        elif action == "out":
            rows = work_sheet.get_all_values()
            osf = find_open_shift(rows, username)
            if not osf:
                msg = "No active shift found."
                msg_class = "message error"
            else:
                i, d, t = osf
                cin_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
                hours = max(0.0, (now - cin_dt).total_seconds() / 3600.0)
                hours_rounded = round(hours, 2)
                pay = round(hours_rounded * rate, 2)

                sheet_row = i + 1
                work_sheet.update_cell(sheet_row, COL_OUT + 1, now.strftime("%H:%M:%S"))
                work_sheet.update_cell(sheet_row, COL_HOURS + 1, hours_rounded)
                work_sheet.update_cell(sheet_row, COL_PAY + 1, pay)
                msg = "Clocked Out"

    # live session timer
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

    timer_html = ""
    if active_start_iso:
        timer_html = f"""
        <div class="timerSub">Active session started</div>
        <div class="timerBig" id="timerDisplay">00:00:00</div>
        <div class="timerSub">Start: {escape(active_start_label)}</div>
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
            tick();
            setInterval(tick, 1000);
          }})();
        </script>
        """
    else:
        timer_html = """
        <div class="timerSub">No active session</div>
        <div class="timerBig">00:00:00</div>
        <div class="timerSub">Clock in to start the live timer.</div>
        """

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">

      <div class="headerTop">
        <div>
          <h1>Clock In & Out</h1>
          <p class="sub">Live session timer</p>
        </div>
        <div class="badge">{escape(username)}</div>
      </div>

      {("<div class='" + msg_class + "'>" + escape(msg) + "</div>") if msg else ""}

      <div class="card clockCard">
        {timer_html}

        <form method="POST" class="actionRow">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <button class="btn btnIn" name="action" value="in">Clock In</button>
          <button class="btn btnOut" name="action" value="out">Clock Out</button>
        </form>

        <a href="/my-times" style="display:block;margin-top:12px;">
          <button class="btnSoft" type="button">View my time logs</button>
        </a>
      </div>

      {bottom_nav("clock", role)}
    </div>
    """)


# ---------- MY TIMES ----------
@app.get("/my-times")
def my_times():
    gate = require_login()
    if gate:
        return gate
    username = session["username"]
    role = session.get("role", "employee")

    rows = work_sheet.get_all_values()
    body = []
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if (r[COL_USER] or "").strip() != username:
            continue
        date = r[COL_DATE]
        cin = r[COL_IN]
        cout = r[COL_OUT]
        hrs = r[COL_HOURS]
        pay = r[COL_PAY]
        body.append(
            f"<tr><td>{escape(date)}</td><td>{escape(cin)}</td>"
            f"<td>{escape(cout)}</td><td>{escape(hrs)}</td><td>{escape(pay)}</td></tr>"
        )

    table = "".join(body) if body else "<tr><td colspan='5'>No records yet.</td></tr>"

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="headerTop">
        <div>
          <h1>Time logs</h1>
          <p class="sub">Your clock history</p>
        </div>
        <div class="badge">{escape(username)}</div>
      </div>

      <div class="card" style="padding:12px;">
        <div class="tablewrap">
          <table style="min-width:640px;">
            <thead><tr><th>Date</th><th>Clock In</th><th>Clock Out</th><th>Hours</th><th>Pay</th></tr></thead>
            <tbody>{table}</tbody>
          </table>
        </div>
      </div>

      {bottom_nav("times", role)}
    </div>
    """)


# ---------- MY REPORTS ----------
@app.get("/my-reports")
def my_reports():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
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

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="headerTop">
        <div>
          <h1>Timesheets</h1>
          <p class="sub">Totals + 20% tax + net</p>
        </div>
        <div class="badge">{escape(username)}</div>
      </div>

      <div class="kpiRow">
        <div class="card kpi">
          <p class="label">Today</p>
          <p class="value">£{d_g}</p>
          <p class="sub">Hours: {round(daily_hours,2)} • Tax: £{d_t} • Net: £{d_n}</p>
        </div>
        <div class="card kpi">
          <p class="label">This Week</p>
          <p class="value">£{w_g}</p>
          <p class="sub">Hours: {round(weekly_hours,2)} • Tax: £{w_t} • Net: £{w_n}</p>
        </div>
      </div>

      <div class="card kpi" style="margin-top:12px;">
        <p class="label">This Month</p>
        <p class="value">£{m_g}</p>
        <p class="sub">Hours: {round(monthly_hours,2)} • Tax: £{m_t} • Net: £{m_n}</p>
      </div>

      {bottom_nav("reports", role)}
    </div>
    """)


# ---------- ONBOARDING ----------
@app.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")
    existing = get_onboarding_record(username)

    msg = ""
    msg_ok = False

    def v(key: str) -> str:
        return (existing or {}).get(key, "")

    if request.method == "POST":
        require_csrf()
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
        emp_type = g("emp_type"); rtw = g("rtw"); ni = g("ni"); utr = g("utr"); start_date = g("start_date")

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
        missing_fields = set()

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

            if not position:
                missing.append("Position")
                missing_fields.add("position")

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
                missing.append("Passport or Birth Certificate file"); missing_fields.add("passport_file")
            if not cscs_file or not cscs_file.filename:
                missing.append("CSCS Card (front & back) file"); missing_fields.add("cscs_file")
            if not pli_file or not pli_file.filename:
                missing.append("Public Liability file"); missing_fields.add("pli_file")
            if not share_file or not share_file.filename:
                missing.append("Share Code / Confirmation file"); missing_fields.add("share_file")

        typed = dict(request.form)

        if missing:
            msg = "Missing required (final): " + ", ".join(missing)
            msg_ok = False
            return render_template_string(_render_onboarding(username, role, existing, msg, msg_ok, typed, missing_fields, csrf))

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
            typed = dict(request.form)
            return render_template_string(_render_onboarding(username, role, existing, msg, msg_ok, typed, set(), csrf))

        now_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

        data = {
            "FirstName": first, "LastName": last, "BirthDate": birth,
            "PhoneCountryCode": phone_cc, "PhoneNumber": phone_num,
            "StreetAddress": street, "City": city, "Postcode": postcode, "Email": email,
            "EmergencyContactName": ec_name,
            "EmergencyContactPhoneCountryCode": ec_cc,
            "EmergencyContactPhoneNumber": ec_phone,
            "MedicalCondition": medical, "MedicalDetails": medical_details,
            "Position": position,
            "CSCSNumber": cscs_no, "CSCSExpiryDate": cscs_exp,
            "EmploymentType": emp_type,
            "RightToWorkUK": rtw,
            "NationalInsurance": ni, "UTR": utr, "StartDate": start_date,

            "BankAccountNumber": acc_no, "SortCode": sort_code, "AccountHolderName": acc_name,
            "CompanyTradingName": comp_trading, "CompanyRegistrationNo": comp_reg,

            "DateOfContract": contract_date, "SiteAddress": site_address,

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

        if is_final:
            set_employee_field(username, "OnboardingCompleted", "TRUE")

        existing = get_onboarding_record(username)
        msg = "Saved draft." if not is_final else "Submitted final successfully."
        msg_ok = True

        return render_template_string(_render_onboarding(username, role, existing, msg, msg_ok, {}, set(), csrf))

    return render_template_string(_render_onboarding(username, role, existing, msg, msg_ok, None, None, csrf))


def _render_onboarding(username, role, existing, msg, msg_ok, typed=None, missing_fields=None, csrf=""):
    typed = typed or {}
    missing_fields = missing_fields or set()

    def val(input_name, existing_key):
        if input_name in typed and typed[input_name] is not None:
            return typed[input_name]
        return (existing or {}).get(existing_key, "")

    def bad(input_name):
        return "bad" if input_name in missing_fields else ""

    def bad_label(input_name):
        return "badLabel" if input_name in missing_fields else ""

    def checked_radio(input_name, existing_key, value):
        return "checked" if val(input_name, existing_key) == value else ""

    def selected(input_name, existing_key, value):
        return "selected" if val(input_name, existing_key) == value else ""

    drive_hint = ""
    if role == "admin":
        drive_hint = "<p class='sub'>Admin: if uploads fail, click <a href='/connect-drive' style='color:var(--purple);font-weight:900;'>Connect Drive</a> once.</p>"

    return f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="headerTop">
        <div>
          <h1>Agreements</h1>
          <p class="sub">Starter form • contract • document uploads</p>
          {drive_hint}
        </div>
        <div class="badge">{escape(username)}</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and msg_ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not msg_ok) else ""}

      <div class="card" style="padding:14px;">
        <form method="POST" enctype="multipart/form-data">
          <input type="hidden" name="csrf" value="{escape(csrf)}">

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

          <div class="row2" style="margin-top:10px;">
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

          <label class="sub {bad_label('medical')}" style="margin-top:12px; display:block;">Medical condition that may affect work?</label>
          <div class="row2">
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="medical" value="no" {checked_radio('medical','MedicalCondition','no')}> No
            </label>
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="medical" value="yes" {checked_radio('medical','MedicalCondition','yes')}> Yes
            </label>
          </div>
          <label class="sub" style="margin-top:8px; display:block;">Details</label>
          <input class="input" name="medical_details" value="{escape(val('medical_details','MedicalDetails'))}">

          <label class="sub {bad_label('position')}" style="margin-top:12px; display:block;">Position</label>
          <div class="row2">
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Bricklayer" {"checked" if val('position','Position')=='Bricklayer' else ""}> Bricklayer
            </label>
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Labourer" {"checked" if val('position','Position')=='Labourer' else ""}> Labourer
            </label>
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Fixer" {"checked" if val('position','Position')=='Fixer' else ""}> Fixer
            </label>
            <label class="sub" style="display:flex; gap:10px; align-items:center;">
              <input type="radio" name="position" value="Supervisor/Foreman" {"checked" if val('position','Position')=='Supervisor/Foreman' else ""}> Supervisor/Foreman
            </label>
          </div>

          <div class="row2" style="margin-top:10px;">
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

          <div class="row2" style="margin-top:10px;">
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

          <div class="row2" style="margin-top:10px;">
            <div>
              <label class="sub {bad_label('acc_no')}">Bank Account Number</label>
              <input class="input {bad('acc_no')}" name="acc_no" value="{escape(val('acc_no','BankAccountNumber'))}">
            </div>
            <div>
              <label class="sub {bad_label('sort_code')}">Sort Code</label>
              <input class="input {bad('sort_code')}" name="sort_code" value="{escape(val('sort_code','SortCode'))}">
            </div>
          </div>
          <label class="sub {bad_label('acc_name')}" style="margin-top:10px; display:block;">Account Holder Name</label>
          <input class="input {bad('acc_name')}" name="acc_name" value="{escape(val('acc_name','AccountHolderName'))}">

          <label class="sub" style="margin-top:12px; display:block;">Company details (optional)</label>
          <input class="input" name="comp_trading" placeholder="Trading name" value="{escape(val('comp_trading','CompanyTradingName'))}">
          <input class="input" name="comp_reg" placeholder="Company reg no." value="{escape(val('comp_reg','CompanyRegistrationNo'))}">

          <div class="row2" style="margin-top:10px;">
            <div>
              <label class="sub {bad_label('contract_date')}">Date of Contract</label>
              <input class="input {bad('contract_date')}" type="date" name="contract_date" value="{escape(val('contract_date','DateOfContract'))}">
            </div>
            <div>
              <label class="sub {bad_label('site_address')}">Site address</label>
              <input class="input {bad('site_address')}" name="site_address" value="{escape(val('site_address','SiteAddress'))}">
            </div>
          </div>

          <label class="sub" style="margin-top:14px; display:block; font-weight:900;">Upload documents</label>
          <p class="sub">Draft: optional uploads. Final: all 4 required. (Files must be re-selected if a Final submit fails.)</p>

          <div class="uploadLabel {bad('passport_file')}">
            <div class="text">Passport or Birth Certificate</div>
            <div class="hint">Required for Final</div>
          </div>
          <input class="input {bad('passport_file')}" type="file" name="passport_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('PassportOrBirthCertLink',''))}</p>

          <div class="uploadLabel {bad('cscs_file')}">
            <div class="text">CSCS Card (front &amp; back)</div>
            <div class="hint">Required for Final</div>
          </div>
          <input class="input {bad('cscs_file')}" type="file" name="cscs_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('CSCSFrontBackLink',''))}</p>

          <div class="uploadLabel {bad('pli_file')}">
            <div class="text">Public Liability</div>
            <div class="hint">Required for Final</div>
          </div>
          <input class="input {bad('pli_file')}" type="file" name="pli_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('PublicLiabilityLink',''))}</p>

          <div class="uploadLabel {bad('share_file')}">
            <div class="text">Share Code / Confirmation</div>
            <div class="hint">Required for Final</div>
          </div>
          <input class="input {bad('share_file')}" type="file" name="share_file" accept="image/*,.pdf">
          <p class="sub">Saved: {linkify((existing or {}).get('ShareCodeLink',''))}</p>

          <label class="sub" style="margin-top:14px; display:block; font-weight:900;">Contract</label>
          <div class="card" style="padding:12px; background:#f7f8ff; border:1px solid rgba(15,23,42,.06); box-shadow:none;">
            <pre style="white-space:pre-wrap; margin:0; font-size:13px; color:rgba(15,23,42,.92);">{escape(CONTRACT_TEXT)}</pre>
          </div>

          <label class="sub {bad_label('contract_accept')}" style="display:flex; gap:10px; align-items:center; margin-top:10px;">
            <input type="checkbox" name="contract_accept" value="yes" {"checked" if typed.get('contract_accept')=='yes' else ""}>
            I have read and accept the contract terms (required for Final)
          </label>

          <label class="sub {bad_label('signature_name')}" style="margin-top:10px; display:block;">Signature (type your full name)</label>
          <input class="input {bad('signature_name')}" name="signature_name" value="{escape(val('signature_name','SignatureName'))}">

          <div class="row2" style="margin-top:14px;">
            <button class="btnSoft" name="submit_type" value="draft" type="submit">Save Draft</button>
            <button class="btnSoft" name="submit_type" value="final" type="submit" style="background: rgba(109,40,217,.14); color: rgba(109,40,217,.98);">Submit Final</button>
          </div>
        </form>
      </div>

      {bottom_nav("home", role)}
    </div>
    """


# ---------- ADMIN DASHBOARD ----------
@app.get("/admin")
def admin():
    gate = require_admin()
    if gate:
        return gate
    role = session.get("role", "employee")
    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="headerTop">
        <div>
          <h1>Admin</h1>
          <p class="sub">Payroll • onboarding • reports</p>
        </div>
        <div class="badge">ADMIN</div>
      </div>

      <div class="card menu">
        <a class="menuItem active" href="/admin/times">
          <div class="menuLeft">
            <div class="icoBox" style="color:var(--purple);">{_svg_chart()}</div>
            <div class="menuText" style="color:var(--purple);">Payroll Report</div>
          </div>
          <div class="chev">›</div>
        </a>

        <a class="menuItem" href="/admin/onboarding">
          <div class="menuLeft">
            <div class="icoBox" style="color:var(--purple);">{_svg_doc()}</div>
            <div class="menuText" style="color:var(--purple);">Onboarding</div>
          </div>
          <div class="chev">›</div>
        </a>

        <a class="menuItem" href="/weekly">
          <div class="menuLeft">
            <div class="icoBox" style="color:var(--blue);">{_svg_clipboard()}</div>
            <div class="menuText" style="color:var(--blue);">Generate Weekly Payroll</div>
          </div>
          <div class="chev">›</div>
        </a>

        <a class="menuItem" href="/monthly">
          <div class="menuLeft">
            <div class="icoBox" style="color:var(--blue);">{_svg_clipboard()}</div>
            <div class="menuText" style="color:var(--blue);">Generate Monthly Payroll</div>
          </div>
          <div class="chev">›</div>
        </a>

        <a class="menuItem" href="/connect-drive">
          <div class="menuLeft">
            <div class="icoBox" style="color:var(--purple);">{_svg_grid()}</div>
            <div class="menuText" style="color:var(--purple);">Connect Drive</div>
          </div>
          <div class="chev">›</div>
        </a>

        <a class="menuItem" href="/">
          <div class="menuLeft">
            <div class="icoBox" style="color:var(--purple);">{_svg_grid()}</div>
            <div class="menuText" style="color:var(--purple);">Back to Dashboard</div>
          </div>
          <div class="chev">›</div>
        </a>
      </div>

      {bottom_nav("home", role)}
    </div>
    """)


# ---------- ADMIN: PAYROLL REPORT (GROUPED + PRINT + CSV) ----------
@app.get("/admin/times")
def admin_times():
    gate = require_admin()
    if gate:
        return gate

    role = session.get("role", "employee")
    q = (request.args.get("q", "") or "").strip().lower()
    date_from = (request.args.get("from", "") or "").strip()
    date_to = (request.args.get("to", "") or "").strip()
    group_mode = (request.args.get("group", "employee") or "").strip().lower()
    download = (request.args.get("download", "") or "").strip()

    now = datetime.now(TZ)
    generated_on = now.strftime("%Y-%m-%d %H:%M:%S")

    rows = work_sheet.get_all_values()

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

    if download == "1":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Username", "Date", "Clock In", "Clock Out", "Hours", "Pay"])
        for row in filtered:
            w.writerow([row["user"], row["date"], row["cin"], row["cout"], row["hours"], row["pay"]])
        return Response(
            out.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=payroll_report.csv"},
        )

    by_user = {}
    overall_hours = 0.0
    overall_gross = 0.0

    for row in filtered:
        u = row["user"] or "Unknown"
        by_user.setdefault(u, {"rows": [], "hours": 0.0, "gross": 0.0})
        by_user[u]["rows"].append(row)
        if row["hours"] != "":
            h = safe_float(row["hours"], 0.0)
            g = safe_float(row["pay"], 0.0)
            by_user[u]["hours"] += h
            by_user[u]["gross"] += g
            overall_hours += h
            overall_gross += g

    overall_tax = round(overall_gross * TAX_RATE, 2)
    overall_net = round(overall_gross - overall_tax, 2)

    summary_rows = []
    for u in sorted(by_user.keys(), key=lambda s: s.lower()):
        gross = round(by_user[u]["gross"], 2)
        tax = round(gross * TAX_RATE, 2)
        net = round(gross - tax, 2)
        summary_rows.append(
            f"<tr><td>{escape(u)}</td><td>{round(by_user[u]['hours'],2)}</td><td>{gross}</td><td>{tax}</td><td>{net}</td></tr>"
        )
    summary_html = "".join(summary_rows) if summary_rows else "<tr><td colspan='5'>No data for this range.</td></tr>"

    grouped_html_parts = []
    if group_mode != "none":
        for u in sorted(by_user.keys(), key=lambda s: s.lower()):
            block = by_user[u]
            gross = round(block["gross"], 2)
            tax = round(gross * TAX_RATE, 2)
            net = round(gross - tax, 2)

            detail_rows = []
            rows_sorted = sorted(block["rows"], key=lambda rr: (rr["date"], rr["cin"]))
            for rr in rows_sorted:
                detail_rows.append(
                    "<tr>"
                    f"<td>{escape(rr['date'])}</td>"
                    f"<td>{escape(rr['cin'])}</td>"
                    f"<td>{escape(rr['cout'])}</td>"
                    f"<td>{escape(rr['hours'])}</td>"
                    f"<td>{escape(rr['pay'])}</td>"
                    "</tr>"
                )
            detail_html = "".join(detail_rows) if detail_rows else "<tr><td colspan='5'>No rows.</td></tr>"

            grouped_html_parts.append(f"""
              <div class="card" style="padding:12px; margin-top:12px;">
                <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-end;">
                  <div>
                    <div style="font-weight:950;font-size:18px;color:var(--purple);">{escape(u)}</div>
                    <div class="sub" style="margin-top:4px;">
                      Hours: <b>{round(block["hours"],2)}</b> • Gross: <b>{gross}</b> • Tax: <b>{tax}</b> • Net: <b>{net}</b>
                    </div>
                  </div>
                  <div class="sub" style="text-align:right;">Generated: {escape(generated_on)}</div>
                </div>

                <div class="tablewrap" style="margin-top:10px;">
                  <table style="min-width:760px;">
                    <thead><tr><th>Date</th><th>Clock In</th><th>Clock Out</th><th>Hours</th><th>Pay</th></tr></thead>
                    <tbody>{detail_html}</tbody>
                  </table>
                </div>
              </div>
            """)
        grouped_html = "".join(grouped_html_parts)
    else:
        flat_rows = []
        for rr in sorted(filtered, key=lambda x: (x["user"], x["date"], x["cin"])):
            flat_rows.append(
                "<tr>"
                f"<td>{escape(rr['user'])}</td>"
                f"<td>{escape(rr['date'])}</td>"
                f"<td>{escape(rr['cin'])}</td>"
                f"<td>{escape(rr['cout'])}</td>"
                f"<td>{escape(rr['hours'])}</td>"
                f"<td>{escape(rr['pay'])}</td>"
                "</tr>"
            )
        grouped_html = f"""
          <div class="card" style="padding:12px;margin-top:12px;">
            <div class="tablewrap">
              <table>
                <thead><tr><th>Username</th><th>Date</th><th>Clock In</th><th>Clock Out</th><th>Hours</th><th>Pay</th></tr></thead>
                <tbody>{''.join(flat_rows) if flat_rows else "<tr><td colspan='6'>No rows.</td></tr>"}</tbody>
              </table>
            </div>
          </div>
        """

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">

      <div class="headerTop">
        <div>
          <h1>Payroll Report</h1>
          <p class="sub">Grouped report • print-ready • CSV export</p>
        </div>
        <div class="badge">ADMIN</div>
      </div>

      <div class="card" style="padding:12px;">
        <div class="noPrint">
          <form method="GET">
            <div class="row2">
              <div>
                <label class="sub">Username contains</label>
                <input class="input" name="q" value="{escape(q)}" placeholder="e.g. john">
              </div>
              <div>
                <label class="sub">Date range</label>
                <div class="row2">
                  <input class="input" type="date" name="from" value="{escape(date_from)}">
                  <input class="input" type="date" name="to" value="{escape(date_to)}">
                </div>
              </div>
            </div>

            <label class="sub" style="margin-top:10px;display:block;">Grouping</label>
            <select class="input" name="group">
              <option value="employee" {"selected" if group_mode=="employee" else ""}>Group by employee</option>
              <option value="none" {"selected" if group_mode=="none" else ""}>No grouping</option>
            </select>

            <div class="row2" style="margin-top:12px;">
              <button class="btnSoft" type="submit">Apply</button>
              <a href="/admin/times?q={escape(q)}&from={escape(date_from)}&to={escape(date_to)}&group={escape(group_mode)}&download=1">
                <button class="btnSoft" type="button" style="background: rgba(109,40,217,.14); color: rgba(109,40,217,.98);">Download CSV</button>
              </a>
            </div>

            <div class="row2" style="margin-top:10px;">
              <button class="btnSoft" type="button" onclick="window.print()">Print</button>
              <a href="/admin"><button class="btnSoft" type="button">Back</button></a>
            </div>
          </form>
        </div>

        <div style="margin-top:12px;">
          <div class="sub"><b>Totals:</b> Hours {round(overall_hours,2)} • Gross £{round(overall_gross,2)} • Tax £{overall_tax} • Net £{overall_net}</div>
        </div>

        <div class="tablewrap">
          <table style="min-width:720px;">
            <thead><tr><th>Username</th><th>Hours</th><th>Gross</th><th>Tax</th><th>Net</th></tr></thead>
            <tbody>{summary_html}</tbody>
          </table>
        </div>
      </div>

      {grouped_html}

      {bottom_nav("home", role)}
    </div>
    """)


# ---------- ADMIN ONBOARDING ----------
@app.get("/admin/onboarding")
def admin_onboarding_list():
    gate = require_admin()
    if gate:
        return gate

    role = session.get("role", "employee")
    q = (request.args.get("q", "") or "").strip().lower()
    vals = onboarding_sheet.get_all_values()
    if not vals:
        body = "<tr><td colspan='3'>No onboarding data.</td></tr>"
    else:
        headers = vals[0]
        def idx(name): return headers.index(name) if name in headers else None
        i_user = idx("Username"); i_fn = idx("FirstName"); i_ln = idx("LastName"); i_sub = idx("SubmittedAt")

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
                f"<tr><td><a href='/admin/onboarding/{escape(u)}' style='color:var(--purple);font-weight:900;'>{escape(name)}</a></td>"
                f"<td>{escape(u)}</td><td>{escape(sub)}</td></tr>"
            )
        body = "".join(rows_html) if rows_html else "<tr><td colspan='3'>No matches.</td></tr>"

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="headerTop">
        <div>
          <h1>Onboarding</h1>
          <p class="sub">Click a name to view full details</p>
        </div>
        <div class="badge">ADMIN</div>
      </div>

      <div class="card" style="padding:12px;">
        <form method="GET">
          <label class="sub">Search name or username</label>
          <div class="row2">
            <input class="input" name="q" value="{escape(q)}" placeholder="Search...">
            <button class="btnSoft" type="submit">Search</button>
          </div>
        </form>

        <div class="tablewrap" style="margin-top:12px;">
          <table>
            <thead><tr><th>Name</th><th>Username</th><th>Last saved</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </div>

      {bottom_nav("home", role)}
    </div>
    """)

@app.get("/admin/onboarding/<username>")
def admin_onboarding_detail(username):
    gate = require_admin()
    if gate:
        return gate

    role = session.get("role", "employee")
    rec = get_onboarding_record(username)
    if not rec:
        abort(404)

    def row(label, key, link=False):
        v_ = rec.get(key, "")
        vv = linkify(v_) if link else escape(v_)
        return f"<tr><th>{escape(label)}</th><td>{vv}</td></tr>"

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

    details += row("Passport or Birth Certificate", "PassportOrBirthCertLink", link=True)
    details += row("CSCS Card (front & back)", "CSCSFrontBackLink", link=True)
    details += row("Public Liability", "PublicLiabilityLink", link=True)
    details += row("Share Code / Confirmation", "ShareCodeLink", link=True)

    details += row("Contract accepted", "ContractAccepted")
    details += row("Signature name", "SignatureName")
    details += row("Signature time", "SignatureDateTime")
    details += row("Last saved", "SubmittedAt")

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="headerTop">
        <div>
          <h1>Onboarding</h1>
          <p class="sub">{escape(username)}</p>
        </div>
        <div class="badge">ADMIN</div>
      </div>

      <div class="card" style="padding:12px;">
        <div class="tablewrap">
          <table style="min-width: 680px;"><tbody>{details}</tbody></table>
        </div>
        <a href="/admin/onboarding" style="display:block;margin-top:12px;">
          <button class="btnSoft" type="button">Back</button>
        </a>
      </div>

      {bottom_nav("home", role)}
    </div>
    """)


# ---------- WEEKLY PAYROLL ----------
@app.get("/weekly")
def weekly_report():
    gate = require_admin()
    if gate:
        return gate

    now = datetime.now(TZ)
    year, week_number, _ = now.isocalendar()
    generated_on = now.strftime("%Y-%m-%d %H:%M:%S")

    existing = payroll_sheet.get_all_records()
    for row in existing:
        if row.get("Type") == "Weekly" and safe_int(row.get("Year", 0)) == year and safe_int(row.get("Week", 0)) == week_number:
            return "Weekly payroll already generated."

    rows = work_sheet.get_all_values()
    payroll = {}

    for r in rows[1:]:
        if len(r) <= COL_PAY or r[COL_HOURS] == "":
            continue
        try:
            row_date = datetime.strptime(r[COL_DATE], "%Y-%m-%d")
        except Exception:
            continue
        y, w, _ = row_date.isocalendar()
        if y == year and w == week_number:
            emp = r[COL_USER]
            payroll.setdefault(emp, {"hours": 0.0, "pay": 0.0})
            payroll[emp]["hours"] += safe_float(r[COL_HOURS], 0.0)
            payroll[emp]["pay"] += safe_float(r[COL_PAY], 0.0)

    for employee, data in payroll.items():
        gross = round(data["pay"], 2)
        tax = round(gross * TAX_RATE, 2)
        net = round(gross - tax, 2)

        payroll_sheet.append_row([
            "Weekly", year, week_number, employee,
            round(data["hours"], 2),
            gross,
            tax,
            net,
            generated_on
        ])

    return "Weekly payroll stored successfully."


# ---------- MONTHLY PAYROLL ----------
@app.route("/monthly", methods=["GET", "POST"])
def monthly_report():
    gate = require_admin()
    if gate:
        return gate

    if request.method == "POST":
        selected = request.form["month"]  # YYYY-MM
        year = int(selected.split("-")[0])
        month = int(selected.split("-")[1])
        generated_on = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

        existing = payroll_sheet.get_all_records()
        for row in existing:
            if row.get("Type") == "Monthly" and safe_int(row.get("Year", 0)) == year and safe_int(row.get("Week", 0)) == month:
                return "Monthly payroll already generated."

        rows = work_sheet.get_all_values()
        payroll = {}

        for r in rows[1:]:
            if len(r) <= COL_PAY or r[COL_HOURS] == "":
                continue
            try:
                row_date = datetime.strptime(r[COL_DATE], "%Y-%m-%d")
            except Exception:
                continue
            if row_date.year == year and row_date.month == month:
                emp = r[COL_USER]
                payroll.setdefault(emp, {"hours": 0.0, "pay": 0.0})
                payroll[emp]["hours"] += safe_float(r[COL_HOURS], 0.0)
                payroll[emp]["pay"] += safe_float(r[COL_PAY], 0.0)

        for employee, data in payroll.items():
            gross = round(data["pay"], 2)
            tax = round(gross * TAX_RATE, 2)
            net = round(gross - tax, 2)

            payroll_sheet.append_row([
                "Monthly", year, month, employee,
                round(data["hours"], 2),
                gross,
                tax,
                net,
                generated_on
            ])

        return "Monthly payroll stored successfully."

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="headerTop">
        <div>
          <h1>Monthly Payroll</h1>
          <p class="sub">Generate payroll for a month</p>
        </div>
        <div class="badge">ADMIN</div>
      </div>

      <div class="card" style="padding:12px;">
        <form method="POST">
          <label class="sub">Select month</label>
          <input class="input" type="month" name="month" required>
          <button class="btnSoft" type="submit" style="margin-top:12px;">Generate</button>
          <a href="/admin" style="display:block;margin-top:10px;">
            <button class="btnSoft" type="button">Back</button>
          </a>
        </form>
      </div>

      {bottom_nav("home", "admin")}
    </div>
    """)


# ================= LOCAL RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
