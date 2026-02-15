import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, render_template_string, request, redirect, session, url_for, abort
from datetime import datetime, timedelta, time

# ================= APP =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static",
)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

# ================= GOOGLE SHEETS =================
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

spreadsheet = client.open("WorkHours")
employees_sheet = spreadsheet.worksheet("Employees")
work_sheet = spreadsheet.worksheet("WorkHours")
payroll_sheet = spreadsheet.worksheet("PayrollReports")
onboarding_sheet = spreadsheet.worksheet("Onboarding")  # MUST EXIST

# WorkHours columns (0-based)
COL_USER = 0
COL_DATE = 1
COL_IN = 2
COL_OUT = 3
COL_HOURS = 4
COL_PAY = 5

TAX_RATE = 0.20
CLOCKIN_EARLIEST = time(8, 0, 0)  # 08:00


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
  --bg:#0b1220;
  --card:#111c33;
  --card2:#0b1328;
  --text:#e5e7eb;
  --muted:#a7b0c0;
  --border:rgba(255,255,255,.08);
  --shadow: 0 18px 50px rgba(0,0,0,.45);
  --radius: 22px;

  --h1: clamp(22px, 4vw, 34px);
  --h2: clamp(18px, 3vw, 24px);
  --p:  clamp(15px, 2.4vw, 19px);
  --small: clamp(13px, 2vw, 15px);
  --btn: clamp(14px, 2.2vw, 16px);
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

.header{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap: 14px;
  margin-bottom: 14px;
}
.title{ display:flex; flex-direction:column; gap: 6px; }

h1{ font-size: var(--h1); margin:0; letter-spacing: .2px; }
h2{ font-size: var(--h2); margin: 0; color: var(--text); }
.sub{ font-size: var(--small); color: var(--muted); margin: 0; }

.appIcon{
  width: 64px;
  height: 64px;
  border-radius: 18px;
  background:
    radial-gradient(22px 22px at 30% 30%, rgba(255,255,255,.22) 0%, rgba(255,255,255,0) 70%),
    linear-gradient(135deg, rgba(96,165,250,.95) 0%, rgba(167,139,250,.95) 55%, rgba(34,197,94,.95) 120%);
  border: 1px solid rgba(255,255,255,.14);
  box-shadow: 0 16px 26px rgba(0,0,0,.35);
  display:grid;
  place-items:center;
  flex: 0 0 auto;
}
.appIcon .glyph{ width: 30px; height: 30px; position: relative; }
.appIcon .glyph:before,
.appIcon .glyph:after{
  content:"";
  position:absolute;
  inset:0;
  border-radius: 12px;
  border: 3px solid rgba(10,15,30,.82);
}
.appIcon .glyph:after{ inset: 7px; border-radius: 9px; }
.appIcon .dot{
  position:absolute;
  width: 7px; height: 7px;
  border-radius: 50%;
  background: rgba(10,15,30,.82);
  left: 50%; top: 50%;
  transform: translate(-50%,-50%);
}

.message{
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 16px;
  background: rgba(34,197,94,.12);
  border: 1px solid rgba(34,197,94,.22);
  font-size: var(--p);
  font-weight: 700;
  text-align:center;
}
.message.error{
  background: rgba(239,68,68,.12);
  border: 1px solid rgba(239,68,68,.22);
}

a { color: #93c5fd; text-decoration:none; }
a:hover { text-decoration:underline; }

.input{
  width: 100%;
  padding: 12px 12px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: rgba(255,255,255,.04);
  color: var(--text);
  font-size: var(--input);
  outline:none;
  margin-top: 10px;
}
.input::placeholder{ color: rgba(229,231,235,.55); }

.row2{
  display:grid;
  grid-template-columns: repeat(2, minmax(0,1fr));
  gap: 10px;
}
@media (max-width: 640px){
  .row2{ grid-template-columns: 1fr; }
}

.btnrow{
  display:flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 12px;
}

button{
  border: none;
  border-radius: 14px;
  padding: 11px 11px;
  font-weight: 900;
  cursor: pointer;
  font-size: var(--btn);
  min-height: 42px;
  flex: 1 1 140px;
  box-shadow: 0 10px 18px rgba(0,0,0,.22);
}
.btnSmall{
  min-height: 38px !important;
  padding: 9px 10px !important;
  font-size: clamp(13px, 2vw, 14px) !important;
  flex: 0 0 auto !important;
}

.green{ background: #22c55e; color:#06230f; }
.red{ background: #ef4444; color:#2a0606; }
.blue{ background: #60a5fa; color:#071527; }
.purple{ background: #a78bfa; color:#140726; }
.gray{ background: rgba(255,255,255,.10); color: var(--text); border: 1px solid var(--border); }

.actionbar{
  position: sticky;
  bottom: 10px;
  margin-top: 14px;
  padding: 10px;
  border-radius: 18px;
  background: rgba(15,23,42,.65);
  border: 1px solid var(--border);
  backdrop-filter: blur(10px);
}

.navgrid{
  display:grid;
  grid-template-columns: repeat(3, minmax(0,1fr));
  gap: 10px;
  margin-top: 10px;
}
@media (min-width: 720px){
  .navgrid{ grid-template-columns: repeat(6, minmax(0,1fr)); }
}
.navgrid a{ text-decoration:none; }
.navgrid button{
  width: 100%;
  min-height: 40px;
  padding: 9px 10px;
  font-size: clamp(13px, 2vw, 14px);
  flex: none;
}

.tablewrap{
  margin-top: 14px;
  overflow:auto;
  border-radius: 18px;
  border: 1px solid var(--border);
}
table{
  width: 100%;
  border-collapse: collapse;
  min-width: 720px;
  background: rgba(255,255,255,.03);
}
th, td{
  padding: 10px 10px;
  border-bottom: 1px solid var(--border);
  text-align:left;
  font-size: clamp(13px, 2vw, 15px);
}
th{
  position: sticky;
  top: 0;
  background: rgba(0,0,0,.25);
  backdrop-filter: blur(8px);
}

.contract{
  margin-top: 12px;
  padding: 12px;
  border-radius: 16px;
  border: 1px solid var(--border);
  background: rgba(0,0,0,.20);
  max-height: 260px;
  overflow:auto;
  font-size: var(--small);
  color: var(--text);
  line-height: 1.35;
}

.installBanner{
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 18px;
  background: rgba(255,255,255,.06);
  border: 1px solid var(--border);
}
.installBanner h3{ margin: 0 0 6px 0; font-size: clamp(16px, 2.4vw, 18px); }
.installBanner p{ margin: 0; color: var(--muted); font-size: clamp(14px, 2.2vw, 16px); line-height: 1.35; }
.installSteps{ margin-top: 10px; display:flex; flex-direction:column; gap: 8px; }
.step{ display:flex; gap: 10px; padding: 10px 12px; border-radius: 16px; background: rgba(0,0,0,.20); border: 1px solid var(--border); }
.step .num{ width: 26px; height: 26px; border-radius: 10px; display:grid; place-items:center; background: rgba(96,165,250,.25); border: 1px solid rgba(96,165,250,.35); font-weight: 900; }
.step .txt{ color: var(--text); font-size: clamp(14px, 2.2vw, 16px); }
</style>
"""

HEADER_ICON = """
<div class="appIcon" aria-hidden="true">
  <div class="glyph"><div class="dot"></div></div>
</div>
"""

# ================= HELPERS =================
def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def parse_bool(v) -> bool:
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "on")

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

def find_open_shift(rows, username: str):
    for i in range(len(rows) - 1, 0, -1):
        r = rows[i]
        if len(r) > COL_OUT and r[COL_USER] == username and r[COL_OUT] == "":
            return i, r[COL_DATE], r[COL_IN]
    return None

def has_any_row_today(rows, username: str, today_str: str) -> bool:
    for r in rows[1:]:
        if len(r) > COL_DATE and r[COL_USER] == username and r[COL_DATE] == today_str:
            return True
    return False

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

    end_a1 = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")  # like "AG"
    if rownum:
        onboarding_sheet.update(f"A{rownum}:{end_a1}{rownum}", [row_values])
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

def get_employee_record(username: str):
    for rec in employees_sheet.get_all_records():
        if rec.get("Username") == username:
            return rec
    return None

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

def escape(s: str) -> str:
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def linkify(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    uesc = escape(u)
    return f"<a href='{uesc}' target='_blank' rel='noopener noreferrer'>{uesc}</a>"

# ================= CONTRACT =================
CONTRACT_TEXT = """
Contract

By signing this agreement, you confirm that while carrying out bricklaying services (and related works) for us, you are acting as a self-employed subcontractor and not as an employee.

You agree to:
• Behave professionally at all times while on site
• Use reasonable efforts to complete all work within agreed timeframes
• Comply with all Health & Safety requirements
• Be responsible for the standard of your work and rectify any defects at your own cost
• Maintain valid public liability insurance
• Supply your own hand tools
• Manage and pay your own Tax and National Insurance contributions (CIS tax will be deducted by us and submitted to HMRC)

You do not have the right to:
• Receive sick pay or payment for work cancelled due to adverse weather
• Use our internal grievance procedure
• Describe yourself as an employee of our company

General Terms
This agreement is governed by the laws of England and Wales.
""".strip()

# ================= ROUTES =================
@app.get("/ping")
def ping():
    return "pong", 200

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
                session["onboarding_completed"] = parse_bool(user.get("OnboardingCompleted", False))
                if not session["onboarding_completed"]:
                    return redirect(url_for("onboarding"))
                return redirect(url_for("home"))
        msg = "Invalid login"

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}<div class="title"><h1>WorkHours</h1><p class="sub">Sign in</p></div></div>
      <h2>Login</h2>
      <form method="POST">
        <input class="input" name="username" placeholder="Username" required>
        <input class="input" type="password" name="password" placeholder="Password" required>
        <div class="btnrow actionbar"><button class="blue" type="submit">Login</button></div>
      </form>

      <div id="iosInstall" class="installBanner" style="display:none;">
        <h3>Install on iPhone</h3>
        <p>Add this app to your Home Screen and open it like a normal app.</p>
        <div class="installSteps">
          <div class="step"><div class="num">1</div><div class="txt">Open this page in <b>Safari</b>.</div></div>
          <div class="step"><div class="num">2</div><div class="txt">Tap <b>Share</b> (square with arrow).</div></div>
          <div class="step"><div class="num">3</div><div class="txt">Tap <b>Add to Home Screen</b>.</div></div>
        </div>
      </div>
      <script>
      (function(){{
        const isIOS = /iPhone|iPad|iPod/i.test(navigator.userAgent);
        const isStandalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) || (window.navigator.standalone === true);
        if (isIOS && !isStandalone) document.getElementById('iosInstall').style.display = 'block';
      }})();
      </script>

      {("<div class='message error'>" + msg + "</div>") if msg else ""}
    </div></div>
    """)

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- EMPLOYEE HOME (minimal, with link to onboarding if needed) ----------
@app.route("/", methods=["GET", "POST"])
def home():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    early_access = bool(session.get("early_access", False))
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    msg = ""
    msg_class = "message"

    rows = work_sheet.get_all_values()
    open_shift = find_open_shift(rows, username)
    active_clock_in_iso = ""
    if open_shift:
        _, d, t = open_shift
        try:
            active_clock_in_iso = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S").isoformat()
        except Exception:
            active_clock_in_iso = ""

    if request.method == "POST":
        action = request.form.get("action")
        if action == "in":
            if has_any_row_today(rows, username, today_str):
                msg = "Already clocked in today (1 per day)."
                msg_class = "message error"
            elif find_open_shift(rows, username):
                msg = "Already clocked in."
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
                msg = "No active shift."
                msg_class = "message error"
            else:
                i, d, t = osf
                cin_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")
                hours = max(0.0, (now - cin_dt).total_seconds() / 3600.0)
                hours_rounded = round(hours, 2)
                pay = round(hours_rounded * float(session.get("rate", 0.0)), 2)
                sheet_row = i + 1
                work_sheet.update_cell(sheet_row, COL_OUT + 1, now.strftime("%H:%M:%S"))
                work_sheet.update_cell(sheet_row, COL_HOURS + 1, hours_rounded)
                work_sheet.update_cell(sheet_row, COL_PAY + 1, pay)
                msg = "Clocked Out"

    admin_btn = "<a href='/admin'><button class='purple btnSmall' type='button'>Admin</button></a>" if role == "admin" else ""

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title"><h1>Hi, {escape(username)}</h1><p class="sub">Clock in/out</p></div>
      </div>

      {("<div class='" + msg_class + "'>" + escape(msg) + "</div>") if msg else ""}

      <div class="actionbar">
        <form method="POST" class="btnrow" style="margin:0;">
          <button class="green" name="action" value="in">Clock In</button>
          <button class="red" name="action" value="out">Clock Out</button>
        </form>

        <div class="navgrid">
          {admin_btn if admin_btn else ""}
          <a href="/onboarding"><button class="blue btnSmall" type="button">My Starter Form</button></a>
          <a href="/logout"><button class="gray btnSmall" type="button">Logout</button></a>
        </div>
      </div>
    </div></div>
    """)

# ---------- ONBOARDING (employee can view/edit; option 1 updates same row) ----------
@app.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    existing = get_onboarding_record(username)

    msg = ""

    if request.method == "POST":
        def g(name): return request.form.get(name, "").strip()

        first = g("first")
        last = g("last")
        birth = g("birth")  # YYYY-MM-DD
        phone_cc = g("phone_cc") or "+44"
        phone_num = g("phone_num")
        street = g("street")
        city = g("city")
        postcode = g("postcode")
        email = g("email")
        ec_name = g("ec_name")
        ec_cc = g("ec_cc") or "+44"
        ec_phone = g("ec_phone")

        medical = g("medical")  # yes/no
        medical_details = g("medical_details")

        position = g("position")
        cscs_no = g("cscs_no")
        cscs_exp = g("cscs_exp")
        emp_type = g("emp_type")
        rtw = g("rtw")  # yes/no
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
        docs_folder = g("docs_folder")

        contract_accept = request.form.get("contract_accept", "") == "yes"
        signature_name = g("signature_name")

        missing = []
        def req(v, label):
            if not v:
                missing.append(label)

        req(first, "First Name")
        req(last, "Last Name")
        req(birth, "Birth Date")
        req(phone_num, "Phone Number")
        req(email, "Email")
        req(ec_name, "Emergency Contact Name")
        req(ec_phone, "Emergency Contact Phone")
        if medical not in ("yes", "no"):
            missing.append("Medical (Yes/No)")
        req(position, "Position")
        req(cscs_no, "CSCS Number")
        req(cscs_exp, "CSCS Expiry Date")
        req(emp_type, "Employment Type")
        if rtw not in ("yes", "no"):
            missing.append("Right to work UK (Yes/No)")
        req(ni, "National Insurance")
        req(utr, "UTR")
        req(start_date, "Start Date")
        req(acc_no, "Bank Account Number")
        req(sort_code, "Sort Code")
        req(acc_name, "Account Holder Name")
        req(contract_date, "Date of Contract")
        req(site_address, "Site address")
        req(docs_folder, "DocsFolderLink (Drive folder)")
        if not contract_accept:
            missing.append("Contract acceptance")
        req(signature_name, "Signature name")

        if missing:
            msg = "Missing required: " + ", ".join(missing)
        else:
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
                "DocsFolderLink": docs_folder,
                "ContractAccepted": "TRUE",
                "SignatureName": signature_name,
                "SignatureDateTime": now_str,
                "SubmittedAt": now_str,
            }
            update_or_append_onboarding(username, data)
            set_employee_field(username, "OnboardingCompleted", "TRUE")
            session["onboarding_completed"] = True
            existing = get_onboarding_record(username)
            msg = "Saved successfully."

    # Prefill
    def val(key):
        return (existing or {}).get(key, "")

    def checked_radio(key, v):
        return "checked" if val(key) == v else ""

    def selected(key, v):
        return "selected" if val(key) == v else ""

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title"><h1>Starter Form</h1><p class="sub">Your details (admin can view)</p></div>
      </div>

      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and "Missing" in msg) else ""}
      {("<div class='message'>" + escape(msg) + "</div>") if (msg and "Saved" in msg) else ""}

      <form method="POST">
        <h2>Personal details</h2>
        <div class="row2">
          <div><label class="sub">First Name *</label><input class="input" name="first" value="{escape(val('FirstName'))}" required></div>
          <div><label class="sub">Last Name *</label><input class="input" name="last" value="{escape(val('LastName'))}" required></div>
        </div>

        <label class="sub" style="margin-top:10px; display:block;">Birth Date *</label>
        <input class="input" type="date" name="birth" value="{escape(val('BirthDate'))}" required>

        <label class="sub" style="margin-top:10px; display:block;">Phone Number *</label>
        <div class="row2">
          <input class="input" name="phone_cc" value="{escape(val('PhoneCountryCode') or '+44')}" required>
          <input class="input" name="phone_num" value="{escape(val('PhoneNumber'))}" required>
        </div>

        <h2 style="margin-top:18px;">Address</h2>
        <input class="input" name="street" placeholder="Street Address" value="{escape(val('StreetAddress'))}">
        <div class="row2">
          <input class="input" name="city" placeholder="City" value="{escape(val('City'))}">
          <input class="input" name="postcode" placeholder="Postcode" value="{escape(val('Postcode'))}">
        </div>

        <div class="row2">
          <div><label class="sub">E-mail *</label><input class="input" name="email" type="email" value="{escape(val('Email'))}" required></div>
          <div><label class="sub">Emergency Contact Name *</label><input class="input" name="ec_name" value="{escape(val('EmergencyContactName'))}" required></div>
        </div>

        <label class="sub" style="margin-top:10px; display:block;">Emergency Contact Phone Number *</label>
        <div class="row2">
          <input class="input" name="ec_cc" value="{escape(val('EmergencyContactPhoneCountryCode') or '+44')}" required>
          <input class="input" name="ec_phone" value="{escape(val('EmergencyContactPhoneNumber'))}" required>
        </div>

        <h2 style="margin-top:18px;">Medical *</h2>
        <div class="row2">
          <label class="sub" style="display:flex; gap:10px; align-items:center;"><input type="radio" name="medical" value="no" {checked_radio('MedicalCondition','no')} required> No</label>
          <label class="sub" style="display:flex; gap:10px; align-items:center;"><input type="radio" name="medical" value="yes" {checked_radio('MedicalCondition','yes')} required> Yes</label>
        </div>
        <label class="sub" style="margin-top:10px; display:block;">Details (optional)</label>
        <input class="input" name="medical_details" value="{escape(val('MedicalDetails'))}">

        <h2 style="margin-top:18px;">Position *</h2>
        <div class="row2">
          <label class="sub" style="display:flex; gap:10px; align-items:center;"><input type="radio" name="position" value="Bricklayer" {"checked" if val('Position')=='Bricklayer' else ""} required> Bricklayer</label>
          <label class="sub" style="display:flex; gap:10px; align-items:center;"><input type="radio" name="position" value="Labourer" {"checked" if val('Position')=='Labourer' else ""} required> Labourer</label>
          <label class="sub" style="display:flex; gap:10px; align-items:center;"><input type="radio" name="position" value="Fixer" {"checked" if val('Position')=='Fixer' else ""} required> Fixer</label>
          <label class="sub" style="display:flex; gap:10px; align-items:center;"><input type="radio" name="position" value="Supervisor/Foreman" {"checked" if val('Position')=='Supervisor/Foreman' else ""} required> Supervisor/Foreman</label>
        </div>

        <div class="row2">
          <div><label class="sub">CSCS Number *</label><input class="input" name="cscs_no" value="{escape(val('CSCSNumber'))}" required></div>
          <div><label class="sub">CSCS Expiry (YYYY-MM-DD) *</label><input class="input" name="cscs_exp" value="{escape(val('CSCSExpiryDate'))}" required></div>
        </div>

        <label class="sub" style="margin-top:10px; display:block;">Employment Type *</label>
        <select class="input" name="emp_type" required>
          <option value="">Please Select</option>
          <option value="Self-employed" {selected('EmploymentType','Self-employed')}>Self-employed</option>
          <option value="Ltd Company" {selected('EmploymentType','Ltd Company')}>Ltd Company</option>
          <option value="Agency" {selected('EmploymentType','Agency')}>Agency</option>
          <option value="PAYE" {selected('EmploymentType','PAYE')}>PAYE</option>
        </select>

        <label class="sub" style="margin-top:10px; display:block;">Right to work in UK? *</label>
        <div class="row2">
          <label class="sub" style="display:flex; gap:10px; align-items:center;"><input type="radio" name="rtw" value="yes" {checked_radio('RightToWorkUK','yes')} required> Yes</label>
          <label class="sub" style="display:flex; gap:10px; align-items:center;"><input type="radio" name="rtw" value="no" {checked_radio('RightToWorkUK','no')} required> No</label>
        </div>

        <div class="row2">
          <div><label class="sub">National Insurance *</label><input class="input" name="ni" value="{escape(val('NationalInsurance'))}" required></div>
          <div><label class="sub">UTR *</label><input class="input" name="utr" value="{escape(val('UTR'))}" required></div>
        </div>

        <label class="sub" style="margin-top:10px; display:block;">Start Date *</label>
        <input class="input" type="date" name="start_date" value="{escape(val('StartDate'))}" required>

        <h2 style="margin-top:18px;">Bank details *</h2>
        <div class="row2">
          <div><label class="sub">Account Number *</label><input class="input" name="acc_no" value="{escape(val('BankAccountNumber'))}" required></div>
          <div><label class="sub">Sort Code *</label><input class="input" name="sort_code" value="{escape(val('SortCode'))}" required></div>
        </div>
        <label class="sub" style="margin-top:10px; display:block;">Account Holder Name *</label>
        <input class="input" name="acc_name" value="{escape(val('AccountHolderName'))}" required>

        <h2 style="margin-top:18px;">Company details</h2>
        <input class="input" name="comp_trading" placeholder="Trading name" value="{escape(val('CompanyTradingName'))}">
        <input class="input" name="comp_reg" placeholder="Company reg no." value="{escape(val('CompanyRegistrationNo'))}">

        <h2 style="margin-top:18px;">Subcontractor details *</h2>
        <div class="row2">
          <div><label class="sub">Date of Contract *</label><input class="input" type="date" name="contract_date" value="{escape(val('DateOfContract'))}" required></div>
          <div><label class="sub">Site address *</label><input class="input" name="site_address" value="{escape(val('SiteAddress'))}" required></div>
        </div>

        <h2 style="margin-top:18px;">Documents folder (Drive link) *</h2>
        <p class="sub">Create a Drive folder, upload all documents, share “Anyone with link can view”, paste link.</p>
        <input class="input" name="docs_folder" placeholder="https://drive.google.com/..." value="{escape(val('DocsFolderLink'))}" required>

        <h2 style="margin-top:18px;">Contract acceptance *</h2>
        <div class="contract"><pre style="white-space:pre-wrap; margin:0;">{CONTRACT_TEXT}</pre></div>

        <label class="sub" style="display:flex; gap:10px; align-items:center; margin-top:10px;">
          <input type="checkbox" name="contract_accept" value="yes" required>
          I have read and accept the contract terms *
        </label>

        <label class="sub" style="margin-top:10px; display:block;">Signature (type your full name) *</label>
        <input class="input" name="signature_name" value="{escape(val('SignatureName'))}" required>

        <div class="btnrow actionbar">
          <button class="green" type="submit">Save</button>
          <a href="/"><button class="gray" type="button">Back</button></a>
        </div>
      </form>
    </div></div>
    """)

# ---------- ADMIN: list onboarding records ----------
@app.get("/admin")
def admin():
    gate = require_admin()
    if gate:
        return gate
    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app"><div class="card">
      <div class="header">{HEADER_ICON}
        <div class="title"><h1>Admin</h1><p class="sub">Onboarding list</p></div>
      </div>
      <div class="navgrid actionbar">
        <a href="/admin/onboarding"><button class="purple btnSmall" type="button">Onboarding</button></a>
        <a href="/"><button class="gray btnSmall" type="button">Back</button></a>
      </div>
    </div></div>
    """)

@app.get("/admin/onboarding")
def admin_onboarding_list():
    gate = require_admin()
    if gate:
        return gate

    q = (request.args.get("q", "") or "").strip().lower()
    vals = onboarding_sheet.get_all_values()
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

        body_rows = []
        for r in vals[1:]:
            u = r[i_user] if i_user is not None and i_user < len(r) else ""
            fn = r[i_fn] if i_fn is not None and i_fn < len(r) else ""
            ln = r[i_ln] if i_ln is not None and i_ln < len(r) else ""
            sub = r[i_sub] if i_sub is not None and i_sub < len(r) else ""
            name = (fn + " " + ln).strip() or u
            if q and (q not in u.lower() and q not in name.lower()):
                continue
            body_rows.append(
                f"<tr><td><a href='/admin/onboarding/{escape(u)}'>{escape(name)}</a></td><td>{escape(u)}</td><td>{escape(sub)}</td><td>{linkify(get_onboarding_record(u).get('DocsFolderLink','') if get_onboarding_record(u) else '')}</td></tr>"
            )
        body = "".join(body_rows) if body_rows else "<tr><td colspan='4'>No matches.</td></tr>"

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
          <thead><tr><th>Name</th><th>Username</th><th>Submitted</th><th>Docs folder</th></tr></thead>
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

    # Show important groups
    def row(label, key, link=False):
        v = rec.get(key, "")
        vv = linkify(v) if link else escape(v)
        return f"<tr><th>{escape(label)}</th><td>{vv}</td></tr>"

    details = ""
    details += row("Username", "Username")
    details += row("First name", "FirstName")
    details += row("Last name", "LastName")
    details += row("Birth date", "BirthDate")
    details += row("Phone", "PhoneCountryCode")  # show cc + num below
    details += f"<tr><th>Phone number</th><td>{escape(rec.get('PhoneNumber',''))}</td></tr>"
    details += row("Email", "Email")
    details += row("Address", "StreetAddress")
    details += row("City", "City")
    details += row("Postcode", "Postcode")
    details += row("Emergency contact", "EmergencyContactName")
    details += f"<tr><th>Emergency phone</th><td>{escape(rec.get('EmergencyContactPhoneCountryCode',''))} {escape(rec.get('EmergencyContactPhoneNumber',''))}</td></tr>"
    details += row("Medical", "MedicalCondition")
    details += row("Medical details", "MedicalDetails")
    details += row("Position", "Position")
    details += row("CSCS number", "CSCSNumber")
    details += row("CSCS expiry", "CSCSExpiryDate")
    details += row("Employment type", "EmploymentType")
    details += row("Right to work UK", "RightToWorkUK")
    details += row("NI", "NationalInsurance")
    details += row("UTR", "UTR")
    details += row("Start date", "StartDate")
    details += row("Bank account", "BankAccountNumber")
    details += row("Sort code", "SortCode")
    details += row("Account holder", "AccountHolderName")
    details += row("Company trading", "CompanyTradingName")
    details += row("Company reg", "CompanyRegistrationNo")
    details += row("Date of contract", "DateOfContract")
    details += row("Site address", "SiteAddress")
    details += row("Docs folder", "DocsFolderLink", link=True)
    details += row("Contract accepted", "ContractAccepted")
    details += row("Signature name", "SignatureName")
    details += row("Signature time", "SignatureDateTime")
    details += row("Submitted at", "SubmittedAt")

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
        <table style="min-width: 640px;">
          <tbody>{details}</tbody>
        </table>
      </div>
    </div></div>
    """)

# ================= LOCAL RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

