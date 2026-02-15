# ===================== app.py (FULL - Premium UI + Dashboard Graph + Desktop Sidebar + Logout bottom separated) =====================
# Notes:
# - NO reportlab / NO PDF exports (so Render won't fail).
# - Admin Payroll page is printable in browser (Ctrl+P / Save as PDF).
# - Logout is ONLY in sidebar bottom on desktop (separated) and also available on mobile bottom bar as an icon.

import os
import json
import io
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
)
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
:root{
  --bg:#f6f8fb;
  --card:#ffffff;
  --text:#0f172a;
  --muted:#64748b;
  --border:rgba(15,23,42,.10);
  --shadow: 0 12px 34px rgba(15,23,42,.08);
  --shadow2: 0 18px 50px rgba(15,23,42,.10);
  --radius: 22px;

  --purple:#6d28d9;
  --purpleSoft:#efe9ff;
  --green:#16a34a;
  --red:#dc2626;

  --h1: clamp(26px, 5vw, 40px);
  --h2: clamp(16px, 3vw, 22px);
  --small: clamp(12px, 2vw, 14px);
}

*{box-sizing:border-box;}
html,body{height:100%;}
body{
  margin:0;
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  background:
    radial-gradient(1000px 550px at 20% 0%, rgba(109,40,217,.10) 0%, rgba(109,40,217,0) 60%),
    radial-gradient(900px 500px at 80% 10%, rgba(37,99,235,.08) 0%, rgba(37,99,235,0) 60%),
    var(--bg);
  color: var(--text);
  padding: 16px 14px calc(130px + env(safe-area-inset-bottom)) 14px;
}
a{color:inherit;text-decoration:none;}
h1{font-size:var(--h1); margin:0;}
h2{font-size:var(--h2); margin: 0 0 8px 0;}
.sub{color:var(--muted); margin:6px 0 0 0; font-size:var(--small); line-height:1.35;}

.card{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

.badge{
  font-size: 12px;
  padding: 7px 10px;
  border-radius: 999px;
  border: 1px solid rgba(15,23,42,.10);
  background: rgba(255,255,255,.75);
  color: rgba(15,23,42,.70);
  font-weight: 900;
  white-space: nowrap;
}

.card, .menuItem, .btnSoft, .navIcon, .sideItem, .input{
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
.kpi .label{font-size:var(--small); color:var(--muted); margin:0;}
.kpi .value{font-size: 28px; font-weight: 950; margin: 6px 0 0 0; letter-spacing:.2px;}

.graphCard{ margin-top: 12px; padding: 14px; }
.graphTop{ display:flex; align-items:center; justify-content:space-between; gap:12px; }
.graphTitle{ font-weight: 950; font-size: 18px; }
.graphRange{ color: var(--muted); font-size: 13px; font-weight: 800; }
.bars{
  margin-top: 12px;
  height: 180px;
  display:flex;
  align-items:flex-end;
  justify-content:space-around;
  gap: 12px;
  padding: 10px 6px 0 6px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(109,40,217,.04) 0%, rgba(109,40,217,0) 60%);
  border: 1px solid rgba(109,40,217,.10);
}
.bar{
  width: 16%;
  border-radius: 14px 14px 10px 10px;
  background: #0b0b0b;
}
.barLabels{
  display:flex; justify-content:space-around; gap:12px;
  margin-top: 10px;
  color: var(--muted);
  font-weight: 900;
  font-size: 13px;
}

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
  border-color: rgba(109,40,217,.12);
}
.menuLeft{display:flex; align-items:center; gap:12px;}
.icoBox{
  width: 44px; height: 44px;
  border-radius: 14px;
  background: rgba(255,255,255,.92);
  border: 1px solid rgba(15,23,42,.06);
  display:grid; place-items:center;
  color: rgba(109,40,217,.92);
}
.icoBox svg{ width: 22px; height: 22px; }
.menuText{
  font-weight: 950;
  font-size: 20px;
  letter-spacing:.1px;
  color: rgba(109,40,217,.95);
}
.chev{
  font-size: 26px;
  color: rgba(109,40,217,.90);
  font-weight: 900;
}

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
  font-weight: 950;
  text-align:center;
  background: rgba(22,163,74,.10);
  border: 1px solid rgba(22,163,74,.18);
}
.message.error{ background: rgba(220,38,38,.10); border-color: rgba(220,38,38,.20); }

.clockCard{ margin-top: 12px; padding: 14px; }
.timerBig{
  font-weight: 950;
  font-size: clamp(26px, 6vw, 36px);
  margin-top: 6px;
}
.timerSub{ color: var(--muted); font-weight: 900; font-size: 13px; margin-top: 6px; }
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
  color: rgba(109,40,217,.98);
}

.tablewrap{ margin-top:14px; overflow:auto; border-radius: 18px; border:1px solid rgba(15,23,42,.08); }
table{ width:100%; border-collapse: collapse; min-width: 720px; background:#fff; }
th,td{ padding: 10px 10px; border-bottom: 1px solid rgba(15,23,42,.08); text-align:left; font-size: 14px; }
th{ position: sticky; top:0; background: rgba(248,250,252,.96); }

.bottomNav{
  position: fixed;
  left: 0; right: 0; bottom: 0;
  background: rgba(255,255,255,.92);
  border-top: 1px solid rgba(15,23,42,.08);
  backdrop-filter: blur(10px);
  padding: 10px 14px calc(14px + env(safe-area-inset-bottom)) 14px;
  z-index: 99;
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

.safeBottom{ height: calc(180px + env(safe-area-inset-bottom)); }

/* Desktop “gmail-style” left menu with logout separated at bottom */
@media (min-width: 980px){
  body{ padding: 18px 18px 22px 18px; }
  .shell{
    max-width: 1320px;
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
    font-weight: 950;
    font-size: 16px;
    color: rgba(15,23,42,.85);
    margin: 0 0 10px 2px;
  }
  .sideItem{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:12px;
    padding: 12px 12px;
    border-radius: 16px;
    background: #f7f8ff;
    border: 1px solid rgba(15,23,42,.06);
    margin-top: 10px;
  }
  .sideItem.active{
    background: var(--purpleSoft);
    border-color: rgba(109,40,217,.14);
  }
  .sideLeft{ display:flex; align-items:center; gap:12px; }
  .sideText{ font-weight: 950; font-size: 16px; letter-spacing:.1px; }
  .sideIcon{
    width: 40px; height: 40px;
    border-radius: 14px;
    background: rgba(255,255,255,.92);
    border: 1px solid rgba(15,23,42,.06);
    display:grid; place-items:center;
    color: rgba(109,40,217,.92);
  }
  .sideIcon svg{ width:20px; height:20px; }

  .sideDivider{
    height: 1px;
    background: rgba(15,23,42,.10);
    margin: 10px 0 6px 0;
  }
  .logoutBtn{
    margin-top: 2px;
    background: rgba(220,38,38,.08);
    border-color: rgba(220,38,38,.12);
  }
  .logoutBtn .sideIcon, .logoutBtn .chev{
    color: rgba(220,38,38,.95);
  }
  .logoutBtn .sideText{
    color: rgba(220,38,38,.95);
  }
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
    return f"<a href='{uesc}' target='_blank' rel='noopener noreferrer' style='color:var(--purple);font-weight:950;'>Open</a>"

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
    # Mobile bottom nav includes logout as last icon (users asked logout only at bottom of sidebar separated on desktop;
    # mobile still needs a way to log out, so we keep a small logout icon here.)
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
        ("agreements", "/onboarding", "Agreements", _svg_doc()),
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

    # Logout ONLY at bottom, separated
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
    return f"""
      <div class="shell">
        {sidebar_html(active, role)}
        <div class="main">
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
          <div class="menuLeft"><div class="icoBox">{_svg_doc()}</div><div class="menuText">Agreements</div></div>
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

    msg = ""
    msg_class = "message"

    if request.method == "POST":
        require_csrf()
        action = request.form.get("action")
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
                work_sheet.append_row([username, today_str, cin, "", "", ""])
                msg = "Clocked In"
                if (not early_access) and (now.time() < CLOCKIN_EARLIEST):
                    msg = "Clocked In (counted from 08:00)"

        elif action == "out":
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
            tick(); setInterval(tick, 1000);
          }})();
        </script>
        """
    else:
        timer_html = """
        <div class="timerSub">No active session</div>
        <div class="timerBig">00:00:00</div>
        <div class="timerSub">Clock in to start the live timer.</div>
        """

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Clock In & Out</h1>
          <p class="sub">{escape(display_name)} • Live session timer</p>
        </div>
        <div class="badge">{escape(role.upper())}</div>
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
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("clock", role, content))


# ---------- MY TIMES ----------
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
            f"<td>{escape(r[COL_OUT])}</td><td>{escape(r[COL_HOURS])}</td><td>{escape(r[COL_PAY])}</td></tr>"
        )
    table = "".join(body) if body else "<tr><td colspan='5'>No records yet.</td></tr>"

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Time logs</h1>
          <p class="sub">{escape(display_name)} • Clock history</p>
        </div>
        <div class="badge">{escape(role.upper())}</div>
      </div>

      <div class="card" style="padding:12px;">
        <div class="tablewrap">
          <table style="min-width:640px;">
            <thead><tr><th>Date</th><th>Clock In</th><th>Clock Out</th><th>Hours</th><th>Pay</th></tr></thead>
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
        <div class="badge">{escape(role.upper())}</div>
      </div>

      <div class="kpiRow">
        <div class="card kpi">
          <p class="label">Today Gross</p>
          <p class="value">£{d_g}</p>
          <p class="sub">Hours: {round(daily_hours,2)} • Tax: £{d_t} • Net: £{d_n}</p>
        </div>
        <div class="card kpi">
          <p class="label">This Week Gross</p>
          <p class="value">£{w_g}</p>
          <p class="sub">Hours: {round(weekly_hours,2)} • Tax: £{w_t} • Net: £{w_n}</p>
        </div>
      </div>

      <div class="card kpi" style="margin-top:12px;">
        <p class="label">This Month Gross</p>
        <p class="value">£{m_g}</p>
        <p class="sub">Hours: {round(monthly_hours,2)} • Tax: £{m_t} • Net: £{m_n}</p>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("reports", role, content))


# ---------- PROFILE (CHANGE PASSWORD) ----------
@app.route("/password", methods=["GET", "POST"])
def change_password():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

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

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Profile</h1>
          <p class="sub">{escape(display_name)}</p>
        </div>
        <div class="badge">{escape(role.upper())}</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

      <div class="card" style="padding:14px;">
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


# ---------- ADMIN ----------
@app.get("/admin")
def admin():
    gate = require_admin()
    if gate:
        return gate

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Admin</h1>
          <p class="sub">Payroll report (printable)</p>
        </div>
        <div class="badge">ADMIN</div>
      </div>

      <div class="card menu">
        <a class="menuItem active" href="/admin/payroll">
          <div class="menuLeft"><div class="icoBox">{_svg_chart()}</div><div class="menuText">Payroll Report</div></div>
          <div class="chev">›</div>
        </a>
        <a class="menuItem" href="/connect-drive">
          <div class="menuLeft"><div class="icoBox">{_svg_grid()}</div><div class="menuText">Connect Drive</div></div>
          <div class="chev">›</div>
        </a>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", "admin", content))


@app.get("/admin/payroll")
def admin_payroll():
    gate = require_admin()
    if gate:
        return gate

    q = (request.args.get("q", "") or "").strip().lower()
    date_from = (request.args.get("from", "") or "").strip()
    date_to = (request.args.get("to", "") or "").strip()

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

    summary_rows = []
    for u in sorted(by_user.keys(), key=lambda s: s.lower()):
        gross = round(by_user[u]["gross"], 2)
        tax = round(gross * TAX_RATE, 2)
        net = round(gross - tax, 2)
        display = get_employee_display_name(u)
        summary_rows.append(
            f"<tr><td>{escape(display)}</td><td>{escape(u)}</td>"
            f"<td>{round(by_user[u]['hours'],2)}</td><td>£{gross}</td><td>£{tax}</td><td>£{net}</td></tr>"
        )
    summary_html = "".join(summary_rows) if summary_rows else "<tr><td colspan='6'>No data for this range.</td></tr>"

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Payroll Report</h1>
          <p class="sub">Tip: use your browser Print → Save as PDF</p>
        </div>
        <div class="badge">ADMIN</div>
      </div>

      <div class="card" style="padding:12px;">
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
          <button class="btnSoft" type="submit" style="margin-top:12px;">Apply</button>
        </form>

        <div style="margin-top:12px;" class="sub">
          <b>Totals:</b> Hours {round(overall_hours,2)} • Gross £{round(overall_gross,2)} • Tax £{overall_tax} • Net £{overall_net}
        </div>

        <div class="tablewrap">
          <table style="min-width:900px;">
            <thead><tr><th>Name</th><th>Username</th><th>Hours</th><th>Gross</th><th>Tax</th><th>Net</th></tr></thead>
            <tbody>{summary_html}</tbody>
          </table>
        </div>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", "admin", content))


# ================= LOCAL RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

