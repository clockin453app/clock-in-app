# ===================== app.py (FULL - FINAL REWRITE) =====================
# White/light professional theme
# Admin "Payroll Report" (All Times) grouped by employee + print view + CSV
# Mobile buttons fill the screen (2-column grid on phones)
# Same Google Sheets + Drive OAuth flow as your working version
# CSRF protection + password hashing with auto-migrate from plaintext

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

# Built into Flask/Werkzeug (no new packages)
from werkzeug.security import generate_password_hash, check_password_hash


# ================= APP =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static",
)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

# Upload size cap (adjust as needed)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "15")) * 1024 * 1024

# Cookie hardening
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
    # local fallback (DO NOT COMMIT credentials.json)
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
    token_data = session.get("drive_token")
    if not token_data:
        token_data = _load_drive_token()
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
            raise RuntimeError(
                "Upload folder not found. Fix ONBOARDING_DRIVE_FOLDER_ID (use a FOLDER id from your Drive)."
            ) from e

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
        "background_color": "#f6f7fb",
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


# ================= UI (LIGHT / WHITE PROFESSIONAL THEME) =================
STYLE = """
<style>
:root{
  --bg:#f6f7fb;
  --card:#ffffff;
  --text:#0f172a;
  --muted:#475569;
  --border:rgba(15,23,42,.10);
  --shadow: 0 18px 48px rgba(15,23,42,.10);
  --radius: 18px;

  --h1: clamp(22px, 4vw, 32px);
  --h2: clamp(18px, 3vw, 22px);
  --p:  clamp(15px, 2.4vw, 18px);
  --small: clamp(13px, 2vw, 15px);
  --btn: clamp(13px, 2.2vw, 15px);
  --input: clamp(15px, 2.4vw, 17px);

  --primary:#2563eb;
  --success:#16a34a;
  --danger:#dc2626;
  --purple:#7c3aed;
}

*{ box-sizing:border-box; }
html, body { height:100%; }
body{
  margin:0;
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  background:
    radial-gradient(1200px 700px at 10% 0%, rgba(37,99,235,.08) 0%, rgba(37,99,235,0) 60%),
    radial-gradient(900px 650px at 90% 15%, rgba(124,58,237,.06) 0%, rgba(124,58,237,0) 55%),
    var(--bg);
  color: var(--text);
  padding: clamp(12px, 3vw, 22px);
  -webkit-text-size-adjust: 100%;
}
.app{ width:100%; max-width: 1120px; margin: 0 auto; }

.card{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: clamp(16px, 3vw, 24px);
  box-shadow: var(--shadow);
}

.header{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:14px;}
.title{display:flex;flex-direction:column;gap:6px;}
h1{font-size:var(--h1);margin:0;letter-spacing:.1px;}
h2{font-size:var(--h2);margin: 18px 0 10px 0;}
.sub{font-size:var(--small);color:var(--muted);margin:0;line-height:1.35;}

.badge{
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: rgba(15,23,42,.03);
  color: var(--muted);
  white-space: nowrap;
}

.appIcon{
  width: 54px;height: 54px;border-radius: 16px;
  background:
    radial-gradient(22px 22px at 30% 30%, rgba(255,255,255,.9) 0%, rgba(255,255,255,0) 70%),
    linear-gradient(135deg, rgba(37,99,235,.95) 0%, rgba(124,58,237,.70) 55%, rgba(22,163,74,.75) 120%);
  border: 1px solid rgba(15,23,42,.10);
  box-shadow: 0 14px 24px rgba(15,23,42,.10);
  display:grid;place-items:center;flex: 0 0 auto;
}
.appIcon .glyph{ width: 26px; height: 26px; position: relative; }
.appIcon .glyph:before,.appIcon .glyph:after{
  content:""; position:absolute; inset:0; border-radius: 12px;
  border: 3px solid rgba(15,23,42,.80);
}
.appIcon .glyph:after{ inset: 7px; border-radius: 9px; }
.appIcon .dot{
  position:absolute; width: 7px; height: 7px; border-radius: 50%;
  background: rgba(15,23,42,.80); left: 50%; top: 50%;
  transform: translate(-50%,-50%);
}

.message{
  margin-top: 12px; padding: 10px 12px; border-radius: 14px;
  background: rgba(22,163,74,.08); border: 1px solid rgba(22,163,74,.18);
  font-size: var(--p); font-weight: 800; text-align:center;
}
.message.error{ background: rgba(220,38,38,.08); border: 1px solid rgba(220,38,38,.18); }

a{color:var(--primary);text-decoration:none;}
a:hover{text-decoration:underline;}

.input{
  width:100%;
  padding:12px 12px;
  border-radius:12px;
  border:1px solid rgba(15,23,42,.14);
  background:#fff;
  color: var(--text);
  font-size: var(--input);
  outline:none;
  margin-top:10px;
}
.input:focus{ border-color: rgba(37,99,235,.45); box-shadow: 0 0 0 3px rgba(37,99,235,.12); }

.row2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
@media (max-width: 640px){.row2{grid-template-columns:1fr;}}

.btnrow{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px; justify-content:center;}
button{
  border: 1px solid rgba(15,23,42,.12);
  border-radius:12px;
  padding:10px 10px;
  font-weight:900;
  cursor:pointer;
  font-size: var(--btn);
  min-height: 40px;
  flex: 1 1 130px;
  box-shadow: 0 10px 18px rgba(15,23,42,.08);
  transition: transform .06s ease, filter .06s ease;
}
button:active{ transform: translateY(1px); filter: brightness(.99); }

.btnSmall{min-height: 34px !important;padding: 8px 10px !important;flex:0 0 auto !important;}

.green{background:rgba(22,163,74,1);color:white;border-color: rgba(22,163,74,.35);}
.red{background:rgba(220,38,38,1);color:white;border-color: rgba(220,38,38,.35);}
.blue{background:rgba(37,99,235,1);color:white;border-color: rgba(37,99,235,.35);}
.purple{background:rgba(124,58,237,1);color:white;border-color: rgba(124,58,237,.35);}
.gray{background:#ffffff;color: var(--text); border:1px solid rgba(15,23,42,.16);}

.actionbar{
  position: sticky; bottom: 10px; margin-top: 14px; padding: 10px;
  border-radius: 16px;
  background: rgba(255,255,255,.85);
  border: 1px solid rgba(15,23,42,.10);
  backdrop-filter: blur(10px);
}

.navgrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:10px;}
@media (min-width: 720px){.navgrid{grid-template-columns:repeat(6,minmax(0,1fr));}}
.navgrid a{text-decoration:none;}
.navgrid button{width:100%;min-height:34px;padding:8px 10px;flex:none;}

.tablewrap{margin-top:14px;overflow:auto;border-radius:16px;border:1px solid rgba(15,23,42,.10);}
table{width:100%;border-collapse:collapse;min-width:780px;background:#fff;}
th,td{padding:10px 10px;border-bottom:1px solid rgba(15,23,42,.08);text-align:left;font-size: clamp(13px,2vw,15px);}
th{position:sticky;top:0;background: rgba(248,250,252,.95);backdrop-filter: blur(8px);color: rgba(15,23,42,.85);}

.kpi{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px;}
@media (min-width: 720px){.kpi{grid-template-columns:repeat(4,minmax(0,1fr));}}
.kpi .box{border:1px solid rgba(15,23,42,.10);background: rgba(248,250,252,.75);border-radius:14px;padding:12px;}
.kpi .big{font-size: clamp(16px,2.6vw,20px);font-weight:950;}

.timerBox{
  margin-top: 12px; padding: 12px; border-radius: 14px;
  background: rgba(37,99,235,.06);
  border: 1px solid rgba(37,99,235,.16);
}
.timerBig{font-weight: 950; font-size: clamp(18px, 3vw, 26px);}

.contract{
  margin-top:12px;padding:12px;border-radius:14px;border:1px solid rgba(15,23,42,.10);
  background: rgba(248,250,252,.75);
  max-height:320px;overflow:auto;font-size: var(--small);
  color: var(--text); line-height:1.35;
}

/* Upload headers */
.uploadLabel{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  margin-top: 14px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid rgba(37,99,235,.18);
  background: rgba(37,99,235,.06);
}
.uploadLabel .text{ font-weight: 950; font-size: clamp(15px, 2.6vw, 18px); color: rgba(15,23,42,.95); }
.uploadLabel .hint{ font-size: var(--small); color: rgba(71,85,105,.9); }

.bad{
  border: 1px solid rgba(220,38,38,.75) !important;
  box-shadow: 0 0 0 3px rgba(220,38,38,.10) !important;
}
.badLabel{ color: rgba(220,38,38,.9) !important; font-weight: 900; }

/* Payroll report blocks */
.reportHeader{
  display:flex; align-items:flex-end; justify-content:space-between; gap:12px;
  padding: 12px; border-radius: 14px; border: 1px solid rgba(15,23,42,.10);
  background: rgba(248,250,252,.75);
  margin-top: 10px;
}
.reportTitle{ font-weight: 950; font-size: 18px; }
.reportMeta{ color: var(--muted); font-size: var(--small); line-height: 1.4; }
.reportStamp{
  text-align:right;
  color: rgba(15,23,42,.75);
  font-size: var(--small);
}

/* Print view */
.noPrint{ display:block; }
.onlyPrint{ display:none; }
@media print{
  body{ background:#fff; padding:0; }
  .app{ max-width:none; }
  .card{ border:none; box-shadow:none; border-radius:0; padding: 18px; }
  .actionbar, .navgrid, .noPrint{ display:none !important; }
  .onlyPrint{ display:block !important; }
  .tablewrap{ border:1px solid rgba(0,0,0,.15); }
  th{ background:#f3f4f6 !important; }
}

/* ---- Mobile: make buttons fill the phone width nicely ---- */
@media (max-width: 640px){

  .btnrow{
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
    gap: 10px;
  }

  .btnrow button{
    width: 100%;
    flex: none !important;
  }

  .navgrid{
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    width: 100%;
  }

  .navgrid button{
    width: 100%;
  }
}
</style>
"""

HEADER_ICON = """<div class="appIcon"><div class="glyph"><div class="dot"></div></div></div>"""


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
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
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
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title"><h1>WorkHours</h1><p class="sub">Sign in</p></div>
        <div class="badge">Secure access</div>
      </div>
      <form method="POST">
        <input type="hidden" name="csrf" value="{escape(csrf)}">
        <input class="input" name="username" placeholder="Username" required>
        <input class="input" type="password" name="password" placeholder="Password" required>
        <div class="btnrow actionbar">
          <button class="blue" type="submit">Login</button>
        </div>
      </form>
      {("<div class='message error'>" + escape(msg) + "</div>") if msg else ""}
    </div></div>
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
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title"><h1>Change Password</h1><p class="sub">Update your login password</p></div>
      </div>

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

        <div class="btnrow actionbar">
          <button class="blue" type="submit">Save</button>
          <a href="/"><button class="gray" type="button">Back</button></a>
        </div>
      </form>
    </div></div>
    """)


# ---------- HOME (LIVE SESSION TIMER) ----------
@app.route("/", methods=["GET", "POST"])
def home():
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

    # Determine active session start for live timer
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
        <div class="timerBox">
          <div class="sub">Active session</div>
          <div class="timerBig" id="timerDisplay">00:00:00</div>
          <div class="sub" style="margin-top:6px;">Start: {escape(active_start_label)}</div>
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
            }}
            tick();
            setInterval(tick, 1000);
          }})();
        </script>
        """

    admin_btn = "<a href='/admin'><button class='purple btnSmall' type='button'>Admin</button></a>" if role == "admin" else ""
    drive_btn = "<a href='/connect-drive'><button class='blue btnSmall' type='button'>Connect Drive</button></a>" if role == "admin" else ""

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title">
          <h1>Hi, {escape(username)}</h1>
          <p class="sub">Clock in/out • view your times & pay • starter form</p>
        </div>
        <div class="badge">{escape(role.upper())}</div>
      </div>

      {("<div class='" + msg_class + "'>" + escape(msg) + "</div>") if msg else ""}

      {timer_html}

      <div class="actionbar">
        <form method="POST" class="btnrow" style="margin:0;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <button class="green" name="action" value="in">Clock In</button>
          <button class="red" name="action" value="out">Clock Out</button>
        </form>

        <div class="navgrid">
          {admin_btn if admin_btn else ""}
          {drive_btn if drive_btn else ""}
          <a href="/my-times"><button class="blue btnSmall" type="button">My Times</button></a>
          <a href="/my-reports"><button class="blue btnSmall" type="button">My Reports</button></a>
          <a href="/onboarding"><button class="blue btnSmall" type="button">Starter Form</button></a>
          <a href="/password"><button class="blue btnSmall" type="button">Password</button></a>
          <a href="/logout"><button class="gray btnSmall" type="button">Logout</button></a>
        </div>
      </div>
    </div></div>
    """)


# ---------- MY TIMES ----------
@app.get("/my-times")
def my_times():
    gate = require_login()
    if gate:
        return gate
    username = session["username"]

    rows = work_sheet.get_all_values()
    body = []
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if r[COL_USER] != username:
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
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title"><h1>My Times</h1><p class="sub">Clock-in/out history</p></div>
      </div>
      <div class="btnrow">
        <a href="/"><button class="gray btnSmall" type="button">Back</button></a>
      </div>
      <div class="tablewrap">
        <table style="min-width:640px;">
          <thead><tr><th>Date</th><th>Clock In</th><th>Clock Out</th><th>Hours</th><th>Pay</th></tr></thead>
          <tbody>{table}</tbody>
        </table>
      </div>
    </div></div>
    """)


# ---------- MY REPORTS ----------
@app.get("/my-reports")
def my_reports():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
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
        if r[COL_USER] != username:
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
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title"><h1>My Reports</h1><p class="sub">Totals + tax (20%) + net</p></div>
      </div>

      <div class="kpi">
        <div class="box"><div class="sub">Today Hours</div><div class="big">{round(daily_hours,2)}</div></div>
        <div class="box"><div class="sub">Today Gross</div><div class="big">{d_g}</div></div>
        <div class="box"><div class="sub">Today Tax</div><div class="big">{d_t}</div></div>
        <div class="box"><div class="sub">Today Net</div><div class="big">{d_n}</div></div>

        <div class="box"><div class="sub">Week Hours</div><div class="big">{round(weekly_hours,2)}</div></div>
        <div class="box"><div class="sub">Week Gross</div><div class="big">{w_g}</div></div>
        <div class="box"><div class="sub">Week Tax</div><div class="big">{w_t}</div></div>
        <div class="box"><div class="sub">Week Net</div><div class="big">{w_n}</div></div>

        <div class="box"><div class="sub">Month Hours</div><div class="big">{round(monthly_hours,2)}</div></div>
        <div class="box"><div class="sub">Month Gross</div><div class="big">{m_g}</div></div>
        <div class="box"><div class="sub">Month Tax</div><div class="big">{m_t}</div></div>
        <div class="box"><div class="sub">Month Net</div><div class="big">{m_n}</div></div>
      </div>

      <div class="btnrow actionbar">
        <a href="/"><button class="gray btnSmall" type="button">Back</button></a>
      </div>
    </div></div>
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

        # typed fields
        first = g("first")
        last = g("last")
        birth = g("birth")
        phone_cc = g("phone_cc") or "+44"
        phone_num = g("phone_num")
        street = g("street")
        city = g("city")
        postcode = g("postcode")
        email = g("email")
        ec_name = g("ec_name")
        ec_cc = g("ec_cc") or "+44"
        ec_phone = g("ec_phone")

        medical = g("medical")
        medical_details = g("medical_details")

        position = g("position")
        cscs_no = g("cscs_no")
        cscs_exp = g("cscs_exp")
        emp_type = g("emp_type")
        rtw = g("rtw")
        ni = g("ni")
        utr = g("utr")
        start_date = g("start_date")

        acc_no = g("acc_no")
        sort_code = g("sort_code")
        acc_name = g("acc_name")
        comp_trading = g("comp_trading")
        comp_reg = g("comp_reg")

        contract_date = g("contract_date")
        site_address = g("site_address")

        contract_accept = (request.form.get("contract_accept", "") == "yes")
        signature_name = g("signature_name")

        # files
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
                missing.append("Passport or Birth Certificate file")
                missing_fields.add("passport_file")
            if not cscs_file or not cscs_file.filename:
                missing.append("CSCS Card (front & back) file")
                missing_fields.add("cscs_file")
            if not pli_file or not pli_file.filename:
                missing.append("Public Liability file")
                missing_fields.add("pli_file")
            if not share_file or not share_file.filename:
                missing.append("Share Code / Confirmation file")
                missing_fields.add("share_file")

        typed = dict(request.form)

        if missing:
            msg = "Missing required (final): " + ", ".join(missing)
            msg_ok = False
            return render_template_string(_render_onboarding(username, role, existing, msg, msg_ok, typed, missing_fields, csrf))

        # Keep existing links if draft/partial
        passport_link = v("PassportOrBirthCertLink")
        cscs_link = v("CSCSFrontBackLink")
        pli_link = v("PublicLiabilityLink")
        share_link = v("ShareCodeLink")

        # Upload files if provided
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

        if is_final:
            set_employee_field(username, "OnboardingCompleted", "TRUE")

        existing = get_onboarding_record(username)
        msg = "Saved draft." if not is_final else "Submitted final successfully."
        msg_ok = True

        return render_template_string(_render_onboarding(username, role, existing, msg, msg_ok, {}, set(), csrf))

    # GET
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

    admin_btn = "<a href='/admin'><button class='purple btnSmall' type='button'>Admin</button></a>" if role == "admin" else ""
    drive_hint = ""
    if role == "admin":
        drive_hint = "<p class='sub'>Admin: if uploads fail, click <a href='/connect-drive'>Connect Drive</a> once.</p>"

    return f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title">
          <h1>Starter Form</h1>
          <p class="sub">Save Draft anytime. Submit Final when complete (required + contract + uploads).</p>
          {drive_hint}
        </div>
        <div class="badge">{escape(username)}</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and msg_ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not msg_ok) else ""}

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

        <h2>Address</h2>
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

        <h2>Medical</h2>
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

        <h2>Position</h2>
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

        <h2>Bank details</h2>
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

        <h2>Company details</h2>
        <input class="input" name="comp_trading" placeholder="Trading name" value="{escape(val('comp_trading','CompanyTradingName'))}">
        <input class="input" name="comp_reg" placeholder="Company reg no." value="{escape(val('comp_reg','CompanyRegistrationNo'))}">

        <h2>Contract & site</h2>
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

        <h2>Upload documents</h2>
        <p class="sub">Draft: optional uploads. Final: all 4 required. (Files must be re-selected if a Final submit fails.)</p>

        <div class="uploadLabel {bad('passport_file')}">
          <div class="text">Passport or Birth Certificate</div>
          <div class="hint">Required for Final</div>
        </div>
        <input class="input {bad('passport_file')}" type="file" name="passport_file" accept="image/*,.pdf">
        <p class="sub">Saved: {linkify((existing or {}).get('PassportOrBirthCertLink',''))}</p>

        <div class="uploadLabel {bad('cscs_file')}">
          <div class="text">CSCS Card (front & back)</div>
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

        <h2>Contract</h2>
        <div class="contract"><pre style="white-space:pre-wrap; margin:0;">{escape(CONTRACT_TEXT)}</pre></div>

        <label class="sub {bad_label('contract_accept')}" style="display:flex; gap:10px; align-items:center; margin-top:10px;">
          <input type="checkbox" name="contract_accept" value="yes" {"checked" if typed.get('contract_accept')=='yes' else ""}>
          I have read and accept the contract terms (required for Final)
        </label>

        <label class="sub {bad_label('signature_name')}" style="margin-top:10px; display:block;">Signature (type your full name)</label>
        <input class="input {bad('signature_name')}" name="signature_name" value="{escape(val('signature_name','SignatureName'))}">

        <div class="btnrow actionbar">
          <button class="green" name="submit_type" value="draft" type="submit">Save Draft</button>
          <button class="purple" name="submit_type" value="final" type="submit">Submit Final</button>
          <a href="/"><button class="gray" type="button">Back</button></a>
        </div>

        <div class="navgrid">
          {admin_btn if admin_btn else ""}
        </div>
      </form>
    </div></div>
    """


# ---------- ADMIN DASHBOARD ----------
@app.get("/admin")
def admin():
    gate = require_admin()
    if gate:
        return gate
    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title"><h1>Admin</h1><p class="sub">Payroll + onboarding + reports</p></div>
        <div class="badge">ADMIN</div>
      </div>
      <div class="navgrid actionbar">
        <a href="/connect-drive"><button class="blue btnSmall" type="button">Connect Drive</button></a>
        <a href="/admin/onboarding"><button class="purple btnSmall" type="button">Onboarding</button></a>
        <a href="/admin/times"><button class="blue btnSmall" type="button">Payroll Report</button></a>
        <a href="/weekly"><button class="blue btnSmall" type="button">Weekly Payroll</button></a>
        <a href="/monthly"><button class="blue btnSmall" type="button">Monthly Payroll</button></a>
        <a href="/"><button class="gray btnSmall" type="button">Back</button></a>
      </div>
    </div></div>
    """)


# ---------- ADMIN: REAL PAYROLL REPORT (GROUPED + PRINT VIEW) ----------
@app.get("/admin/times")
def admin_times():
    gate = require_admin()
    if gate:
        return gate

    q = (request.args.get("q", "") or "").strip().lower()              # username contains
    date_from = (request.args.get("from", "") or "").strip()           # YYYY-MM-DD
    date_to = (request.args.get("to", "") or "").strip()               # YYYY-MM-DD
    group_mode = (request.args.get("group", "employee") or "").strip().lower()  # employee / none
    download = (request.args.get("download", "") or "").strip()        # "1" => CSV

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

    # CSV export
    if download == "1":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Username", "Date", "Clock In", "Clock Out", "Hours", "Pay"])
        for row in filtered:
            w.writerow([row["user"], row["date"], row["cin"], row["cout"], row["hours"], row["pay"]])

        total_hours = 0.0
        total_gross = 0.0
        for row in filtered:
            if row["hours"] != "":
                total_hours += safe_float(row["hours"], 0.0)
                total_gross += safe_float(row["pay"], 0.0)

        total_tax = round(total_gross * TAX_RATE, 2)
        total_net = round(total_gross - total_tax, 2)
        w.writerow([])
        w.writerow(["TOTAL HOURS", round(total_hours, 2)])
        w.writerow(["TOTAL GROSS", round(total_gross, 2)])
        w.writerow(["TOTAL TAX (20%)", total_tax])
        w.writerow(["TOTAL NET", total_net])

        return Response(
            out.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=payroll_report.csv"},
        )

    # Grouping + totals
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

    # Summary table
    summary_rows = []
    for u in sorted(by_user.keys(), key=lambda s: s.lower()):
        gross = round(by_user[u]["gross"], 2)
        tax = round(gross * TAX_RATE, 2)
        net = round(gross - tax, 2)
        summary_rows.append(
            f"<tr><td>{escape(u)}</td><td>{round(by_user[u]['hours'],2)}</td><td>{gross}</td><td>{tax}</td><td>{net}</td></tr>"
        )
    summary_html = "".join(summary_rows) if summary_rows else "<tr><td colspan='5'>No data for this range.</td></tr>"

    # Grouped detail sections
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
              <div style="margin-top:16px;">
                <div class="reportHeader">
                  <div>
                    <div class="reportTitle">{escape(u)}</div>
                    <div class="reportMeta">
                      Hours: <b>{round(block["hours"],2)}</b> • Gross: <b>{gross}</b> • Tax: <b>{tax}</b> • Net: <b>{net}</b>
                    </div>
                  </div>
                  <div class="reportStamp">Generated: {escape(generated_on)}</div>
                </div>

                <div class="tablewrap">
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
          <div class="tablewrap" style="margin-top:16px;">
            <table>
              <thead><tr><th>Username</th><th>Date</th><th>Clock In</th><th>Clock Out</th><th>Hours</th><th>Pay</th></tr></thead>
              <tbody>{''.join(flat_rows) if flat_rows else "<tr><td colspan='6'>No rows.</td></tr>"}</tbody>
            </table>
          </div>
        """

    # Safe query pieces for CSV link
    q_q = escape(q)
    q_from = escape(date_from)
    q_to = escape(date_to)
    q_group = escape(group_mode)

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app"><div class="card">

      <div class="header">
        {HEADER_ICON}
        <div class="title">
          <h1>Payroll Report</h1>
          <p class="sub">Grouped payroll view with print-ready layout (and CSV export)</p>
        </div>
        <div class="badge">ADMIN</div>
      </div>

      <div class="reportHeader onlyPrint">
        <div>
          <div class="reportTitle">Payroll Report</div>
          <div class="reportMeta">
            Range: <b>{escape(date_from or "All")}</b> to <b>{escape(date_to or "All")}</b><br>
            Filter: <b>{escape(q or "None")}</b> • Grouping: <b>{escape(group_mode)}</b>
          </div>
        </div>
        <div class="reportStamp">
          Generated: {escape(generated_on)}<br>
          Totals — Hours: <b>{round(overall_hours,2)}</b> • Gross: <b>{round(overall_gross,2)}</b> • Tax: <b>{overall_tax}</b> • Net: <b>{overall_net}</b>
        </div>
      </div>

      <div class="noPrint">
        <form method="GET" style="margin-top:10px;">
          <div class="row2">
            <div>
              <label class="sub">Username contains</label>
              <input class="input" name="q" placeholder="e.g. john" value="{escape(q)}">
            </div>
            <div>
              <label class="sub">Date range</label>
              <div class="row2">
                <input class="input" type="date" name="from" value="{escape(date_from)}">
                <input class="input" type="date" name="to" value="{escape(date_to)}">
              </div>
            </div>
          </div>

          <label class="sub" style="margin-top:10px; display:block;">Grouping</label>
          <select class="input" name="group">
            <option value="employee" {"selected" if group_mode=="employee" else ""}>Group by employee (recommended)</option>
            <option value="none" {"selected" if group_mode=="none" else ""}>No grouping (flat)</option>
          </select>

          <div class="btnrow" style="margin-top:10px;">
            <button class="blue btnSmall" type="submit">Apply</button>

            <a href="/admin/times?q={q_q}&from={q_from}&to={q_to}&group={q_group}&download=1">
              <button class="purple btnSmall" type="button">Download CSV</button>
            </a>

            <button class="gray btnSmall" type="button" onclick="window.print()">Print</button>

            <a href="/admin"><button class="gray btnSmall" type="button">Back</button></a>
          </div>
        </form>

        <div class="kpi">
          <div class="box"><div class="sub">Total Hours</div><div class="big">{round(overall_hours,2)}</div></div>
          <div class="box"><div class="sub">Total Gross</div><div class="big">{round(overall_gross,2)}</div></div>
          <div class="box"><div class="sub">Total Tax (20%)</div><div class="big">{overall_tax}</div></div>
          <div class="box"><div class="sub">Total Net</div><div class="big">{overall_net}</div></div>
        </div>

        <h2>Summary by employee</h2>
        <div class="tablewrap">
          <table style="min-width:720px;">
            <thead><tr><th>Username</th><th>Hours</th><th>Gross</th><th>Tax</th><th>Net</th></tr></thead>
            <tbody>{summary_html}</tbody>
          </table>
        </div>

        <h2>Detailed report</h2>
      </div>

      {grouped_html}

    </div></div>
    """)


# ---------- ADMIN ONBOARDING ----------
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
                f"<tr><td><a href='/admin/onboarding/{escape(u)}'>{escape(name)}</a></td>"
                f"<td>{escape(u)}</td><td>{escape(sub)}</td></tr>"
            )
        body = "".join(rows_html) if rows_html else "<tr><td colspan='3'>No matches.</td></tr>"

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title"><h1>Onboarding</h1><p class="sub">Click a name to view full details</p></div>
      </div>

      <form method="GET" class="btnrow">
        <input class="input" name="q" placeholder="Search name or username" value="{escape(q)}">
        <button class="blue btnSmall" type="submit">Search</button>
        <a href="/admin"><button class="gray btnSmall" type="button">Back</button></a>
      </form>

      <div class="tablewrap">
        <table>
          <thead><tr><th>Name</th><th>Username</th><th>Last saved</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </div></div>
    """)

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
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title"><h1>Onboarding Details</h1><p class="sub">{escape(username)}</p></div>
      </div>
      <div class="btnrow">
        <a href="/admin/onboarding"><button class="gray btnSmall" type="button">Back</button></a>
      </div>
      <div class="tablewrap">
        <table style="min-width: 640px;"><tbody>{details}</tbody></table>
      </div>
    </div></div>
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
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title"><h1>Monthly Payroll</h1><p class="sub">Generate payroll for a month</p></div>
      </div>
      <form method="POST" class="btnrow">
        <input class="input" type="month" name="month" required>
        <button class="blue btnSmall" type="submit">Generate</button>
        <a href="/admin"><button class="gray btnSmall" type="button">Back</button></a>
      </form>
    </div></div>
    """)


# ================= LOCAL RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

