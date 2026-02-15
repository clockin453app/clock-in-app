# ===================== app.py (FULL) =====================
import os
import json
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, render_template_string, request, redirect, session, url_for, abort
from datetime import datetime, timedelta, time as dtime

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# OAuth (Drive as real user) - fixes: "Service Accounts do not have storage quota"
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials as UserCredentials
from google.auth.transport.requests import Request


# ================= APP =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static",
)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

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
# We store the OAuth token in a small server-side file so employees can upload too.
# (Otherwise, the token would exist only in the admin's browser session.)
OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

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
        # If disk is read-only or fails, uploads may still work in this process via session,
        # but employees in other sessions may not.
        pass

def _load_drive_token() -> dict | None:
    # 1) try file
    try:
        if os.path.exists(DRIVE_TOKEN_PATH):
            with open(DRIVE_TOKEN_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass

    # 2) try env (optional)
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
        # refresh_token can be None sometimes on refresh, so keep existing if missing
        if creds_user.refresh_token:
            token_data["refresh_token"] = creds_user.refresh_token
        session["drive_token"] = token_data
        _save_drive_token(token_data)

    return build("drive", "v3", credentials=creds_user, cache_discovery=False)

def upload_to_drive(file_storage, filename_prefix: str) -> str:
    """
    Upload using OAuth user (Drive quota exists).
    Works without Shared Drives.
    """
    drive_service = get_user_drive_service()
    if not drive_service:
        raise RuntimeError("Drive not connected. Admin must visit /connect-drive once.")

    # If user configured a folder id, validate it exists (gives clearer error than create())
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
    # Important: passports/IDs should NOT be made public
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
        "background_color": "#0b1220",
        "theme_color": "#0b1220",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }, 200, {"Content-Type": "application/manifest+json"}

VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'
PWA_TAGS = """
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#0b1220">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="apple-touch-icon" href="/static/icon-192.png">
"""


# ================= UI =================
STYLE = """
<style>
:root{
  --bg:#0b1220; --card:#111c33; --card2:#0b1328;
  --text:#e5e7eb; --muted:#a7b0c0; --border:rgba(255,255,255,.08);
  --shadow: 0 18px 50px rgba(0,0,0,.45);
  --radius: 22px;

  --h1: clamp(22px, 4vw, 34px);
  --h2: clamp(18px, 3vw, 24px);
  --p:  clamp(15px, 2.4vw, 19px);
  --small: clamp(13px, 2vw, 15px);
  --btn: clamp(13px, 2.2vw, 15px);
  --input: clamp(16px, 2.4vw, 19px);
}
*{ box-sizing:border-box; }
html, body { height:100%; }
body{
  margin:0;
  font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  background: radial-gradient(1200px 800px at 20% 0%, #1b2b5a 0%, rgba(27,43,90,0) 65%),
              radial-gradient(900px 700px at 80% 10%, #2a1b5a 0%, rgba(42,27,90,0) 60%),
              var(--bg);
  color: var(--text);
  padding: clamp(12px, 3vw, 22px);
  -webkit-text-size-adjust: 100%;
}
.app{ width:100%; max-width: 980px; margin: 0 auto; }
.card{
  background: linear-gradient(180deg, var(--card) 0%, var(--card2) 100%);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: clamp(16px, 3vw, 24px);
  box-shadow: var(--shadow);
}
.header{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:14px;}
.title{display:flex;flex-direction:column;gap:6px;}
h1{font-size:var(--h1);margin:0;letter-spacing:.2px;}
h2{font-size:var(--h2);margin: 14px 0 8px 0;}
.sub{font-size:var(--small);color:var(--muted);margin:0;line-height:1.35;}
.appIcon{
  width: 58px;height: 58px;border-radius: 18px;
  background:
    radial-gradient(22px 22px at 30% 30%, rgba(255,255,255,.22) 0%, rgba(255,255,255,0) 70%),
    linear-gradient(135deg, rgba(96,165,250,.95) 0%, rgba(167,139,250,.95) 55%, rgba(34,197,94,.95) 120%);
  border: 1px solid rgba(255,255,255,.14);
  box-shadow: 0 16px 26px rgba(0,0,0,.35);
  display:grid;place-items:center;flex: 0 0 auto;
}
.appIcon .glyph{ width: 28px; height: 28px; position: relative; }
.appIcon .glyph:before,.appIcon .glyph:after{
  content:""; position:absolute; inset:0; border-radius: 12px;
  border: 3px solid rgba(10,15,30,.82);
}
.appIcon .glyph:after{ inset: 7px; border-radius: 9px; }
.appIcon .dot{
  position:absolute; width: 7px; height: 7px; border-radius: 50%;
  background: rgba(10,15,30,.82); left: 50%; top: 50%;
  transform: translate(-50%,-50%);
}
.message{
  margin-top: 12px; padding: 10px 12px; border-radius: 16px;
  background: rgba(34,197,94,.12); border: 1px solid rgba(34,197,94,.22);
  font-size: var(--p); font-weight: 800; text-align:center;
}
.message.error{background: rgba(239,68,68,.12);border: 1px solid rgba(239,68,68,.22);}
a{color:#93c5fd;text-decoration:none;}
a:hover{text-decoration:underline;}
.input{
  width:100%;padding:12px 12px;border-radius:14px;border:1px solid var(--border);
  background: rgba(255,255,255,.04);color: var(--text);font-size: var(--input);
  outline:none;margin-top:10px;
}
.row2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
@media (max-width: 640px){.row2{grid-template-columns:1fr;}}
.btnrow{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;}
button{
  border:none;border-radius:14px;padding:10px 10px;font-weight:900;cursor:pointer;
  font-size: var(--btn); min-height: 40px; flex: 1 1 130px;
  box-shadow: 0 10px 18px rgba(0,0,0,.22);
}
.btnSmall{min-height: 34px !important;padding: 8px 10px !important;flex:0 0 auto !important;}
.green{background:#22c55e;color:#06230f;}
.red{background:#ef4444;color:#2a0606;}
.blue{background:#60a5fa;color:#071527;}
.purple{background:#a78bfa;color:#140726;}
.gray{background:rgba(255,255,255,.10);color: var(--text); border:1px solid var(--border);}
.actionbar{
  position: sticky; bottom: 10px; margin-top: 14px; padding: 10px;
  border-radius: 18px; background: rgba(15,23,42,.65); border: 1px solid var(--border);
  backdrop-filter: blur(10px);
}
.navgrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:10px;}
@media (min-width: 720px){.navgrid{grid-template-columns:repeat(6,minmax(0,1fr));}}
.navgrid a{text-decoration:none;}
.navgrid button{width:100%;min-height:34px;padding:8px 10px;flex:none;}
.tablewrap{margin-top:14px;overflow:auto;border-radius:18px;border:1px solid var(--border);}
table{width:100%;border-collapse:collapse;min-width:720px;background:rgba(255,255,255,.03);}
th,td{padding:10px 10px;border-bottom:1px solid var(--border);text-align:left;font-size: clamp(13px,2vw,15px);}
th{position:sticky;top:0;background:rgba(0,0,0,.25);backdrop-filter: blur(8px);}
.contract{
  margin-top:12px;padding:12px;border-radius:16px;border:1px solid var(--border);
  background:rgba(0,0,0,.20);max-height:280px;overflow:auto;font-size: var(--small);
  color: var(--text); line-height:1.35;
}
.kpi{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:12px;}
@media (min-width: 720px){.kpi{grid-template-columns:repeat(4,minmax(0,1fr));}}
.kpi .box{border:1px solid var(--border);background:rgba(255,255,255,.04);border-radius:16px;padding:10px;}
.kpi .big{font-size: clamp(16px,2.6vw,20px);font-weight:900;}

.timerBox{
  margin-top: 12px; padding: 12px; border-radius: 16px;
  background: rgba(96,165,250,.10); border: 1px solid rgba(96,165,250,.22);
}
.timerBig{font-weight: 950; font-size: clamp(18px, 3vw, 26px);}

.bad{
  border: 1px solid rgba(239,68,68,.85) !important;
  box-shadow: 0 0 0 3px rgba(239,68,68,.12) !important;
}
.badLabel{ color: #fca5a5 !important; font-weight: 900; }
</style>
"""

HEADER_ICON = """
<div class="appIcon"><div class="glyph"><div class="dot"></div></div></div>
"""


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

    for i in range(1, len(vals)):
        row = vals[i]
        if len(row) > ucol and row[ucol] == username:
            employees_sheet.update_cell(i + 1, pcol, new_password)
            return True
    return False

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
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        for user in employees_sheet.get_all_records():
            if user.get("Username") == username and user.get("Password") == password:
                session.clear()
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
      </div>
      <form method="POST">
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

    username = session["username"]
    msg = ""
    ok = False

    if request.method == "POST":
        current = request.form.get("current", "")
        new1 = request.form.get("new1", "")
        new2 = request.form.get("new2", "")

        user_ok = False
        for user in employees_sheet.get_all_records():
            if user.get("Username") == username and user.get("Password") == current:
                user_ok = True
                break

        if not user_ok:
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

    username = session["username"]
    role = session.get("role", "employee")
    rate = safe_float(session.get("rate", 0), 0.0)
    early_access = bool(session.get("early_access", False))

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    msg = ""
    msg_class = "message"

    rows = work_sheet.get_all_values()

    if request.method == "POST":
        action = request.form.get("action")

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
            rows = work_sheet.get_all_values()
            osf = find_open_shift(rows, username)
            if not osf:
                msg = "No active shift found."
                msg_class = "message error"
            else:
                i, d, t = osf
                cin_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")
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
            start_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")
            active_start_iso = start_dt.isoformat()
            active_start_label = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            active_start_iso = ""
            active_start_label = ""

    timer_html = ""
    if active_start_iso:
        timer_html = f"""
        <div class="timerBox">
          <div class="sub">Active session started</div>
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
          <p class="sub">Clock in/out + view your times & pay. Starter Form is optional.</p>
        </div>
      </div>

      {("<div class='" + msg_class + "'>" + escape(msg) + "</div>") if msg else ""}

      {timer_html}

      <div class="actionbar">
        <form method="POST" class="btnrow" style="margin:0;">
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
        <div class="title"><h1>My Times</h1><p class="sub">Your clock-in/out history</p></div>
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
    now = datetime.now()
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

    username = session["username"]
    role = session.get("role", "employee")
    existing = get_onboarding_record(username)

    msg = ""
    msg_ok = False

    def v(key: str) -> str:
        return (existing or {}).get(key, "")

    if request.method == "POST":
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

        missing = []                # labels for user message
        missing_fields = set()      # form field names to highlight

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

            # Drive config checks
            if not _load_drive_token() and not session.get("drive_token"):
                missing.append("Upload system not connected (admin must click Connect Drive)")

            if UPLOAD_FOLDER_ID == "":
                # still ok (uploads go to My Drive root), but typically you want a folder
                pass

            # file requirements for final
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

        typed = dict(request.form)

        if missing:
            msg = "Missing required (final): " + ", ".join(missing)
            msg_ok = False
            return render_template_string(_render_onboarding(username, role, existing, msg, msg_ok, typed, missing_fields))

        # Keep existing links if draft/partial
        passport_link = v("PassportOrBirthCertLink")
        cscs_link = v("CSCSFrontBackLink")
        pli_link = v("PublicLiabilityLink")
        share_link = v("ShareCodeLink")

        # Upload files if provided
        try:
            # NOTE: Browser security means file inputs CANNOT be preserved after submit.
            # Users must re-select files if validation fails.
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
            return render_template_string(_render_onboarding(username, role, existing, msg, msg_ok, typed, set()))

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

        return render_template_string(_render_onboarding(username, role, existing, msg, msg_ok, {}, set()))

    # GET
    return render_template_string(_render_onboarding(username, role, existing, msg, msg_ok, None, None))


def _render_onboarding(username, role, existing, msg, msg_ok, typed=None, missing_fields=None):
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
          <p class="sub">Optional. Save Draft anytime. Submit Final when complete (required + contract + uploads).</p>
          {drive_hint}
        </div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and msg_ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not msg_ok) else ""}

      <form method="POST" enctype="multipart/form-data">
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

        <label class="sub {bad_label('passport_file')}">Passport or Birth Certificate</label>
        <input class="input {bad('passport_file')}" type="file" name="passport_file" accept="image/*,.pdf">
        <p class="sub">Saved: {linkify((existing or {}).get('PassportOrBirthCertLink',''))}</p>

        <label class="sub {bad_label('cscs_file')}" style="margin-top:10px; display:block;">CSCS Card (front & back)</label>
        <input class="input {bad('cscs_file')}" type="file" name="cscs_file" accept="image/*,.pdf">
        <p class="sub">Saved: {linkify((existing or {}).get('CSCSFrontBackLink',''))}</p>

        <label class="sub {bad_label('pli_file')}" style="margin-top:10px; display:block;">Public Liability Insurance</label>
        <input class="input {bad('pli_file')}" type="file" name="pli_file" accept="image/*,.pdf">
        <p class="sub">Saved: {linkify((existing or {}).get('PublicLiabilityLink',''))}</p>

        <label class="sub {bad_label('share_file')}" style="margin-top:10px; display:block;">Share Code / Confirmation</label>
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
        <div class="title"><h1>Admin</h1><p class="sub">Payroll + onboarding</p></div>
      </div>
      <div class="navgrid actionbar">
        <a href="/connect-drive"><button class="blue btnSmall" type="button">Connect Drive</button></a>
        <a href="/admin/onboarding"><button class="purple btnSmall" type="button">Onboarding</button></a>
        <a href="/weekly"><button class="blue btnSmall" type="button">Weekly Payroll</button></a>
        <a href="/monthly"><button class="blue btnSmall" type="button">Monthly Payroll</button></a>
        <a href="/"><button class="gray btnSmall" type="button">Back</button></a>
      </div>
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

    details += row("Passport/Birth cert", "PassportOrBirthCertLink", link=True)
    details += row("CSCS front/back", "CSCSFrontBackLink", link=True)
    details += row("Public liability", "PublicLiabilityLink", link=True)
    details += row("Share code", "ShareCodeLink", link=True)

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

    now = datetime.now()
    year, week_number, _ = now.isocalendar()
    generated_on = now.strftime("%Y-%m-%d %H:%M:%S")

    existing = payroll_sheet.get_all_records()
    for row in existing:
        if row.get("Type") == "Weekly" and int(row.get("Year", 0)) == year and int(row.get("Week", 0)) == week_number:
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
        generated_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        existing = payroll_sheet.get_all_records()
        for row in existing:
            if row.get("Type") == "Monthly" and int(row.get("Year", 0)) == year and int(row.get("Week", 0)) == month:
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

