import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, render_template_string, request, redirect, session, url_for
from datetime import datetime, timedelta, date

# ================= APP =================
app = Flask(__name__)
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
    # Local fallback (DO NOT COMMIT credentials.json)
    with open("credentials.json", "r", encoding="utf-8") as f:
        return json.load(f)

creds_dict = load_google_creds_dict()
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(creds)

spreadsheet = client.open("WorkHours")
employees_sheet = spreadsheet.worksheet("Employees")
work_sheet = spreadsheet.worksheet("WorkHours")
payroll_sheet = spreadsheet.worksheet("PayrollReports")

# WorkHours columns (0-based indices)
COL_USER = 0
COL_DATE = 1
COL_IN = 2
COL_OUT = 3
COL_HOURS = 4
COL_PAY = 5

TAX_RATE = 0.20

# ================= PWA =================
# Put these in: static/icon-192.png and static/icon-512.png
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

# ================= UI =================
VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'
PWA_TAGS = """
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#0b1220">
<link rel="apple-touch-icon" href="/static/icon-192.png">
"""

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

  --h1: clamp(28px, 4.2vw, 44px);
  --h2: clamp(20px, 3.0vw, 28px);
  --p:  clamp(18px, 2.4vw, 22px);
  --small: clamp(14px, 2vw, 16px);
  --btn: clamp(18px, 2.5vw, 22px);
  --input: clamp(18px, 2.5vw, 22px);
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
  padding: clamp(14px, 3vw, 34px);
  -webkit-text-size-adjust: 100%;
}

.app{ width:100%; max-width: 980px; margin: 0 auto; }
.card{
  background: linear-gradient(180deg, var(--card) 0%, var(--card2) 100%);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: clamp(18px, 3vw, 34px);
  box-shadow: var(--shadow);
}

.header{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.title{ display:flex; flex-direction:column; gap: 6px; }
h1{ font-size: var(--h1); margin:0; letter-spacing: .2px; }
h2{ font-size: var(--h2); margin: 0; color: var(--text); }
.sub{ font-size: var(--small); color: var(--muted); margin: 0; }

/* Professional generic app icon (no initials) */
.appIcon{
  width: 86px;
  height: 86px;
  border-radius: 24px;
  background:
    radial-gradient(26px 26px at 30% 30%, rgba(255,255,255,.22) 0%, rgba(255,255,255,0) 70%),
    linear-gradient(135deg, rgba(96,165,250,.95) 0%, rgba(167,139,250,.95) 55%, rgba(34,197,94,.95) 120%);
  border: 1px solid rgba(255,255,255,.14);
  box-shadow: 0 18px 30px rgba(0,0,0,.35);
  display:grid;
  place-items:center;
  flex: 0 0 auto;
}
.appIcon .glyph{
  width: 40px;
  height: 40px;
  position: relative;
}
.appIcon .glyph:before,
.appIcon .glyph:after{
  content:"";
  position:absolute;
  inset:0;
  border-radius: 14px;
  border: 3px solid rgba(10,15,30,.82);
}
.appIcon .glyph:after{
  inset: 8px;
  border-radius: 10px;
}
.appIcon .dot{
  position:absolute;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(10,15,30,.82);
  left: 50%;
  top: 50%;
  transform: translate(-50%,-50%);
}

.kpis{
  display:grid;
  grid-template-columns: repeat(2, minmax(0,1fr));
  gap: 14px;
  margin-top: 18px;
}
.kpi{
  background: rgba(255,255,255,.04);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 14px 14px;
}
.kpi .label{ font-size: var(--small); color: var(--muted); margin-bottom: 6px; }
.kpi .value{ font-size: clamp(22px, 3vw, 30px); font-weight: 900; }

.message{
  margin-top: 14px;
  padding: 12px 14px;
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
  padding: 16px 16px;
  border-radius: 18px;
  border: 1px solid var(--border);
  background: rgba(255,255,255,.04);
  color: var(--text);
  font-size: var(--input);
  outline:none;
}
.input::placeholder{ color: rgba(229,231,235,.55); }

.btnrow{
  display:flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-top: 16px;
}

button{
  border: none;
  border-radius: 18px;
  padding: 18px 18px;
  font-weight: 900;
  cursor: pointer;
  font-size: var(--btn);
  min-height: 60px;
  flex: 1 1 220px;
  box-shadow: 0 14px 26px rgba(0,0,0,.28);
  transition: transform .05s ease, opacity .12s ease;
}
button:active{ transform: translateY(1px); }
button:hover{ opacity:.95; }

.green{ background: #22c55e; color:#06230f; }
.red{ background: #ef4444; color:#2a0606; }
.blue{ background: #60a5fa; color:#071527; }
.purple{ background: #a78bfa; color:#140726; }
.gray{ background: rgba(255,255,255,.10); color: var(--text); border: 1px solid var(--border); }

.actionbar{
  position: sticky;
  bottom: 12px;
  margin-top: 18px;
  padding: 12px;
  border-radius: 22px;
  background: rgba(15,23,42,.65);
  border: 1px solid var(--border);
  backdrop-filter: blur(10px);
}

/* Tables */
.tablewrap{
  margin-top: 16px;
  overflow:auto;
  border-radius: 18px;
  border: 1px solid var(--border);
}
table{
  width: 100%;
  border-collapse: collapse;
  min-width: 860px;
  background: rgba(255,255,255,.03);
}
th, td{
  padding: 12px 12px;
  border-bottom: 1px solid var(--border);
  text-align:left;
  font-size: clamp(14px, 2.1vw, 16px);
}
th{
  position: sticky;
  top: 0;
  background: rgba(0,0,0,.25);
  backdrop-filter: blur(8px);
}
tfoot td{
  font-weight: 900;
  background: rgba(0,0,0,.18);
}

@media (max-width: 520px){
  .kpis{ grid-template-columns: 1fr; }
  table{ min-width: 760px; }
}
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

def hours_to_hm(decimal_hours: float) -> str:
    total_minutes = int(round(decimal_hours * 60))
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h}h {m:02d}m"

def parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def require_login():
    if "username" not in session:
        return redirect(url_for("login"))
    if session.get("role") is None or session.get("rate") is None:
        session.clear()
        return redirect(url_for("login"))
    return None

def require_admin():
    gate = require_login()
    if gate:
        return gate
    if session.get("role") != "admin":
        return redirect(url_for("home"))
    return None

def compute_money(gross: float):
    gross = round(gross, 2)
    tax = round(gross * TAX_RATE, 2)
    net = round(gross - tax, 2)
    return gross, tax, net

def has_any_row_today(rows, username: str, today_str: str) -> bool:
    # max 1 clock-in record per day
    for r in rows[1:]:
        if len(r) > COL_DATE and r[COL_USER] == username and r[COL_DATE] == today_str:
            return True
    return False

def find_open_shift(rows, username: str):
    # Find latest row for user where ClockOut is empty
    for i in range(len(rows) - 1, 0, -1):
        r = rows[i]
        if len(r) > COL_OUT and r[COL_USER] == username and r[COL_OUT] == "":
            return i, r[COL_DATE], r[COL_IN]
    return None

def get_rates_map():
    rates = {}
    for rec in employees_sheet.get_all_records():
        u = rec.get("Username")
        if u:
            rates[u] = safe_float(rec.get("Rate", 0), 0.0)
    return rates

def get_employees_headers():
    values = employees_sheet.get_all_values()
    if not values:
        return [], []
    return values[0], values

# ================= ROUTES =================
@app.get("/ping")
def ping():
    return "pong", 200

# ---------- LOGIN ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    message = ""
    msg_class = "message error"

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        for user in employees_sheet.get_all_records():
            if user.get("Username") == username and user.get("Password") == password:
                session.clear()
                session["username"] = username
                session["role"] = user.get("Role", "employee")
                session["rate"] = safe_float(user.get("Rate", 0), 0.0)
                return redirect(url_for("home"))

        message = "Invalid login"

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="card">
        <div class="header">
          {HEADER_ICON}
          <div class="title">
            <h1>WorkHours</h1>
            <p class="sub">Sign in</p>
          </div>
        </div>

        <h2>Login</h2>
        <form method="POST" style="margin-top:14px;">
          <input class="input" name="username" placeholder="Username" required>
          <input class="input" type="password" name="password" placeholder="Password" required>
          <div class="btnrow actionbar">
            <button class="blue" type="submit">Login</button>
          </div>
        </form>

        {"<div class='" + msg_class + "'>" + message + "</div>" if message else ""}
      </div>
    </div>
    """)

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- CHANGE PASSWORD ----------
@app.route("/change-password", methods=["GET", "POST"])
def change_password():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    message = ""
    msg_class = "message"

    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")

        if not current_pw or not new_pw or not confirm_pw:
            message = "All fields are required."
            msg_class = "message error"
        elif new_pw != confirm_pw:
            message = "New passwords do not match."
            msg_class = "message error"
        elif len(new_pw) < 4:
            message = "Password is too short."
            msg_class = "message error"
        else:
            records = employees_sheet.get_all_records()
            found = None
            for u in records:
                if u.get("Username") == username:
                    found = u
                    break

            if not found:
                message = "User not found."
                msg_class = "message error"
            elif found.get("Password") != current_pw:
                message = "Current password is incorrect."
                msg_class = "message error"
            else:
                headers, values = get_employees_headers()
                try:
                    ucol = headers.index("Username")
                    pcol = headers.index("Password") + 1  # gspread 1-based
                except ValueError:
                    message = "Employees sheet must have headers: Username, Password, Role, Rate"
                    msg_class = "message error"
                else:
                    rownum = None
                    for i in range(1, len(values)):
                        row = values[i]
                        if len(row) > ucol and row[ucol] == username:
                            rownum = i + 1
                            break
                    if not rownum:
                        message = "Could not locate your row in Employees sheet."
                        msg_class = "message error"
                    else:
                        employees_sheet.update_cell(rownum, pcol, new_pw)
                        message = "Password changed successfully."
                        msg_class = "message"

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="card">
        <div class="header">
          {HEADER_ICON}
          <div class="title">
            <h1>Change Password</h1>
            <p class="sub">Account: {username}</p>
          </div>
        </div>

        <form method="POST">
          <input class="input" type="password" name="current_password" placeholder="Current password" required>
          <input class="input" type="password" name="new_password" placeholder="New password" required>
          <input class="input" type="password" name="confirm_password" placeholder="Confirm new password" required>

          <div class="btnrow actionbar">
            <button class="green" type="submit">Save</button>
            <a href="/"><button class="gray" type="button">Back</button></a>
          </div>
        </form>

        {"<div class='" + msg_class + "'>" + message + "</div>" if message else ""}
      </div>
    </div>
    """)

# ---------- HOME (NO MONEY SHOWN) ----------
@app.route("/", methods=["GET", "POST"])
def home():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    rate = safe_float(session.get("rate", 0), 0.0)

    now = datetime.now()
    today = now.date()
    today_str = now.strftime("%Y-%m-%d")
    week_start = today - timedelta(days=today.weekday())

    message = ""
    msg_class = "message"

    rows = work_sheet.get_all_values()

    # Determine active shift start for live timer
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
            # block: only 1 clock-in row per day
            if has_any_row_today(rows, username, today_str):
                message = "You already clocked in today. Only 1 clock-in per day is allowed."
                msg_class = "message error"
            # block: if somehow already has open shift
            elif find_open_shift(rows, username) is not None:
                message = "You are already clocked in."
                msg_class = "message error"
            else:
                work_sheet.append_row([username, today_str, now.strftime("%H:%M:%S"), "", "", ""])
                message = "Clocked In"
                active_clock_in_iso = now.replace(microsecond=0).isoformat()

        elif action == "out":
            rows = work_sheet.get_all_values()
            open_shift = find_open_shift(rows, username)
            if not open_shift:
                message = "No active shift found to clock out."
                msg_class = "message error"
            else:
                i, d, t = open_shift
                clock_in_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")
                hours = (now - clock_in_dt).total_seconds() / 3600.0
                hours_rounded = round(hours, 2)
                pay = round(hours * rate, 2)  # stored in sheet only

                sheet_row = i + 1
                work_sheet.update_cell(sheet_row, COL_OUT + 1, now.strftime("%H:%M:%S"))
                work_sheet.update_cell(sheet_row, COL_HOURS + 1, hours_rounded)
                work_sheet.update_cell(sheet_row, COL_PAY + 1, pay)

                message = f"Shift time: {hours_to_hm(hours)}"
                active_clock_in_iso = ""

    # totals from completed shifts (Hours column)
    daily_hours = 0.0
    weekly_hours = 0.0

    rows = work_sheet.get_all_values()
    for r in rows[1:]:
        if len(r) <= COL_HOURS:
            continue
        if r[COL_USER] != username:
            continue
        if r[COL_HOURS] == "":
            continue

        rd = parse_date(r[COL_DATE])
        if not rd:
            continue

        h = safe_float(r[COL_HOURS], 0.0)
        if rd == today:
            daily_hours += h
        if rd >= week_start:
            weekly_hours += h

    admin_button = ""
    if role == "admin":
        admin_button = "<a href='/admin'><button class='purple'>Admin</button></a>"

    live_timer_block = f"""
    <div class="kpi">
      <div class="label">Live shift timer</div>
      <div class="value" id="liveTimer">—</div>
      <div class="sub" id="liveSince" style="margin-top:6px;">Since: —</div>
    </div>

    <script>
      const startIso = "{active_clock_in_iso}";
      const liveTimer = document.getElementById("liveTimer");
      const liveSince = document.getElementById("liveSince");

      function pad(n){{ return String(n).padStart(2,"0"); }}

      function tick(){{
        if(!startIso) return;
        const start = new Date(startIso);
        const now = new Date();
        let sec = Math.max(0, Math.floor((now - start) / 1000));
        const h = Math.floor(sec / 3600);
        sec = sec % 3600;
        const m = Math.floor(sec / 60);
        const s = sec % 60;

        liveTimer.textContent = `${{h}}h ${{pad(m)}}m ${{pad(s)}}s`;
        liveSince.textContent = "Since: " + start.toLocaleTimeString();
      }}

      tick();
      setInterval(tick, 1000);
    </script>
    """ if active_clock_in_iso else """
    <div class="kpi">
      <div class="label">Live shift timer</div>
      <div class="value">Not clocked in</div>
      <div class="sub" style="margin-top:6px;">Clock in to start timer</div>
    </div>
    """

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="card">
        <div class="header">
          {HEADER_ICON}
          <div class="title">
            <h1>Hi, {username}</h1>
            <p class="sub">Clock in / out</p>
          </div>
        </div>

        <div class="kpis">
          <div class="kpi">
            <div class="label">Today</div>
            <div class="value">{hours_to_hm(daily_hours)}</div>
            <div class="sub">Completed shift time</div>
          </div>
          <div class="kpi">
            <div class="label">This week</div>
            <div class="value">{hours_to_hm(weekly_hours)}</div>
            <div class="sub">From Monday to today</div>
          </div>
          {live_timer_block}
          <div class="kpi">
            <div class="label">Status</div>
            <div class="value">{'Clocked in' if active_clock_in_iso else 'Clocked out'}</div>
            <div class="sub">{'Timer running' if active_clock_in_iso else 'No active shift'}</div>
          </div>
        </div>

        {"<div class='" + msg_class + "'>" + message + "</div>" if message else ""}

        <div class="actionbar">
          <form method="POST" class="btnrow" style="margin:0;">
            <button class="green" name="action" value="in">Clock In</button>
            <button class="red" name="action" value="out">Clock Out</button>
          </form>

          <div class="btnrow" style="margin-top:12px;">
            {admin_button}
            <a href="/my-times"><button class="blue" type="button">My Times</button></a>
            <a href="/my-reports"><button class="blue" type="button">My Reports</button></a>
            <a href="/change-password"><button class="gray" type="button">Password</button></a>
            <a href="/logout"><button class="gray" type="button">Logout</button></a>
          </div>
        </div>
      </div>
    </div>
    """)

# ---------- EMPLOYEE: MY TIMES ----------
@app.get("/my-times")
def my_times():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    days = int(request.args.get("days", "14") or "14")
    days = max(1, min(days, 90))

    rows = work_sheet.get_all_values()
    today = datetime.now().date()
    start_date = today - timedelta(days=days - 1)

    items = []
    for r in rows[1:]:
        if len(r) <= COL_OUT:
            continue
        if r[COL_USER] != username:
            continue
        rd = parse_date(r[COL_DATE])
        if not rd or rd < start_date:
            continue

        cin = r[COL_IN] if len(r) > COL_IN else ""
        cout = r[COL_OUT] if len(r) > COL_OUT else ""
        hours = safe_float(r[COL_HOURS], 0.0) if len(r) > COL_HOURS and r[COL_HOURS] != "" else None
        items.append((rd, cin, cout, hours))

    items.sort(key=lambda x: x[0], reverse=True)

    rows_html = ""
    for rd, cin, cout, hours in items:
        htxt = hours_to_hm(hours) if hours is not None else "—"
        rows_html += f"<tr><td>{rd.isoformat()}</td><td>{cin}</td><td>{cout or '—'}</td><td>{htxt}</td></tr>"

    if not rows_html:
        rows_html = "<tr><td colspan='4'>No entries found.</td></tr>"

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="card">
        <div class="header">
          {HEADER_ICON}
          <div class="title">
            <h1>My Times</h1>
            <p class="sub">Last {days} days</p>
          </div>
        </div>

        <div class="btnrow">
          <a href="/my-times?days=7"><button class="gray" type="button">7 days</button></a>
          <a href="/my-times?days=14"><button class="gray" type="button">14 days</button></a>
          <a href="/my-times?days=30"><button class="gray" type="button">30 days</button></a>
          <a href="/"><button class="blue" type="button">Back</button></a>
        </div>

        <div class="tablewrap">
          <table>
            <thead><tr><th>Date</th><th>Clock In</th><th>Clock Out</th><th>Hours</th></tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
      </div>
    </div>
    """)

# ---------- EMPLOYEE: MY REPORTS ----------
@app.get("/my-reports")
def my_reports():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    rate = safe_float(session.get("rate", 0), 0.0)

    now = datetime.now()
    y_now, w_now, _ = now.isocalendar()

    mode = request.args.get("mode", "weekly")
    if mode not in ("weekly", "monthly"):
        mode = "weekly"

    year = int(request.args.get("year", str(y_now)) or y_now)
    week = int(request.args.get("week", str(w_now)) or w_now)
    month = int(request.args.get("month", str(now.month)) or now.month)

    rows = work_sheet.get_all_values()
    total_hours = 0.0
    gross_sum = 0.0

    if mode == "weekly":
        for r in rows[1:]:
            if len(r) <= COL_DATE:
                continue
            if r[COL_USER] != username or len(r) <= COL_HOURS or r[COL_HOURS] == "":
                continue
            rd = parse_date(r[COL_DATE])
            if not rd:
                continue
            yy, ww, _ = rd.isocalendar()
            if yy == year and ww == week:
                h = safe_float(r[COL_HOURS], 0.0)
                total_hours += h
                if len(r) > COL_PAY and r[COL_PAY] != "":
                    gross_sum += safe_float(r[COL_PAY], 0.0)
                else:
                    gross_sum += h * rate
        title = f"My Weekly Report • {year}-W{week}"
    else:
        for r in rows[1:]:
            if len(r) <= COL_DATE:
                continue
            if r[COL_USER] != username or len(r) <= COL_HOURS or r[COL_HOURS] == "":
                continue
            rd = parse_date(r[COL_DATE])
            if not rd:
                continue
            if rd.year == year and rd.month == month:
                h = safe_float(r[COL_HOURS], 0.0)
                total_hours += h
                if len(r) > COL_PAY and r[COL_PAY] != "":
                    gross_sum += safe_float(r[COL_PAY], 0.0)
                else:
                    gross_sum += h * rate
        title = f"My Monthly Report • {year}-{month:02d}"

    gross, tax, net = compute_money(gross_sum)

    week_input = f"<input class='input' name='week' value='{week}' placeholder='Week (1-53)'>" if mode == "weekly" else ""
    month_input = f"<input class='input' name='month' value='{month}' placeholder='Month (1-12)'>" if mode == "monthly" else ""

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="card">
        <div class="header">
          {HEADER_ICON}
          <div class="title">
            <h1>My Reports</h1>
            <p class="sub">{title}</p>
          </div>
        </div>

        <div class="btnrow">
          <a href="/my-reports?mode=weekly"><button class="blue" type="button">Weekly</button></a>
          <a href="/my-reports?mode=monthly"><button class="blue" type="button">Monthly</button></a>
          <a href="/"><button class="gray" type="button">Back</button></a>
        </div>

        <form method="GET" class="btnrow" style="margin-top:10px;">
          <input type="hidden" name="mode" value="{mode}">
          <input class="input" name="year" value="{year}" placeholder="Year (e.g. 2026)">
          {week_input}
          {month_input}
          <button class="purple" type="submit">View</button>
        </form>

        <div class="kpis">
          <div class="kpi"><div class="label">Hours</div><div class="value">{hours_to_hm(total_hours)}</div><div class="sub">Total hours</div></div>
          <div class="kpi"><div class="label">Gross</div><div class="value">{gross:.2f}</div><div class="sub">Before tax</div></div>
          <div class="kpi"><div class="label">Tax (20%)</div><div class="value">{tax:.2f}</div><div class="sub">Deducted</div></div>
          <div class="kpi"><div class="label">Net</div><div class="value">{net:.2f}</div><div class="sub">After tax</div></div>
        </div>

        <div class="btnrow actionbar">
          <a href="/my-times"><button class="gray" type="button">My Times</button></a>
          <a href="/change-password"><button class="gray" type="button">Password</button></a>
        </div>
      </div>
    </div>
    """)

# ---------- ADMIN DASHBOARD ----------
@app.get("/admin")
def admin():
    gate = require_admin()
    if gate:
        return gate

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="card">
        <div class="header">
          {HEADER_ICON}
          <div class="title">
            <h1>Admin</h1>
            <p class="sub">Reports + employee management</p>
          </div>
        </div>

        <div class="btnrow actionbar">
          <a href="/admin/weekly-report"><button class="purple">Weekly Report</button></a>
          <a href="/admin/monthly-report"><button class="purple">Monthly Report</button></a>
          <a href="/employees"><button class="blue">Employees</button></a>
          <a href="/"><button class="gray" type="button">Back</button></a>
        </div>
      </div>
    </div>
    """)

# ---------- ADMIN WEEKLY REPORT ----------
@app.get("/admin/weekly-report")
def admin_weekly_report():
    gate = require_admin()
    if gate:
        return gate

    nowd = datetime.now().date()
    y_now, w_now, _ = nowd.isocalendar()

    year = int(request.args.get("year", str(y_now)) or y_now)
    week = int(request.args.get("week", str(w_now)) or w_now)

    rows = work_sheet.get_all_values()
    rates = get_rates_map()

    agg = {}
    for r in rows[1:]:
        if len(r) <= COL_DATE:
            continue
        rd = parse_date(r[COL_DATE])
        if not rd:
            continue
        y, w, _ = rd.isocalendar()
        if y != year or w != week:
            continue
        if len(r) <= COL_HOURS or r[COL_HOURS] == "":
            continue

        user = r[COL_USER]
        h = safe_float(r[COL_HOURS], 0.0)
        if len(r) > COL_PAY and r[COL_PAY] != "":
            g = safe_float(r[COL_PAY], 0.0)
        else:
            g = h * rates.get(user, 0.0)

        agg.setdefault(user, {"hours": 0.0, "gross": 0.0})
        agg[user]["hours"] += h
        agg[user]["gross"] += g

    total_hours = total_gross = total_tax = total_net = 0.0
    body_html = ""

    for user in sorted(agg.keys()):
        h = agg[user]["hours"]
        gross, tax, net = compute_money(agg[user]["gross"])
        total_hours += h
        total_gross += gross
        total_tax += tax
        total_net += net
        body_html += f"<tr><td>{user}</td><td>{hours_to_hm(h)}</td><td>{gross:.2f}</td><td>{tax:.2f}</td><td>{net:.2f}</td></tr>"

    if not body_html:
        body_html = "<tr><td colspan='5'>No data for this week.</td></tr>"

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="card">
        <div class="header">
          {HEADER_ICON}
          <div class="title">
            <h1>Weekly Report</h1>
            <p class="sub">{year}-W{week} • Gross / Tax / Net</p>
          </div>
        </div>

        <form method="GET" class="btnrow">
          <input class="input" name="year" value="{year}" placeholder="Year">
          <input class="input" name="week" value="{week}" placeholder="Week">
          <button class="purple" type="submit">View</button>
          <a href="/admin"><button class="gray" type="button">Back</button></a>
        </form>

        <div class="tablewrap">
          <table>
            <thead><tr><th>Employee</th><th>Hours</th><th>Gross</th><th>Tax (20%)</th><th>Net</th></tr></thead>
            <tbody>{body_html}</tbody>
            <tfoot>
              <tr>
                <td>Totals</td>
                <td>{hours_to_hm(total_hours)}</td>
                <td>{total_gross:.2f}</td>
                <td>{total_tax:.2f}</td>
                <td>{total_net:.2f}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>
    """)

# ---------- ADMIN MONTHLY REPORT ----------
@app.get("/admin/monthly-report")
def admin_monthly_report():
    gate = require_admin()
    if gate:
        return gate

    nowd = datetime.now().date()
    year = int(request.args.get("year", str(nowd.year)) or nowd.year)
    month = int(request.args.get("month", str(nowd.month)) or nowd.month)

    rows = work_sheet.get_all_values()
    rates = get_rates_map()

    agg = {}
    for r in rows[1:]:
        if len(r) <= COL_DATE:
            continue
        rd = parse_date(r[COL_DATE])
        if not rd:
            continue
        if rd.year != year or rd.month != month:
            continue
        if len(r) <= COL_HOURS or r[COL_HOURS] == "":
            continue

        user = r[COL_USER]
        h = safe_float(r[COL_HOURS], 0.0)
        if len(r) > COL_PAY and r[COL_PAY] != "":
            g = safe_float(r[COL_PAY], 0.0)
        else:
            g = h * rates.get(user, 0.0)

        agg.setdefault(user, {"hours": 0.0, "gross": 0.0})
        agg[user]["hours"] += h
        agg[user]["gross"] += g

    total_hours = total_gross = total_tax = total_net = 0.0
    body_html = ""

    for user in sorted(agg.keys()):
        h = agg[user]["hours"]
        gross, tax, net = compute_money(agg[user]["gross"])
        total_hours += h
        total_gross += gross
        total_tax += tax
        total_net += net
        body_html += f"<tr><td>{user}</td><td>{hours_to_hm(h)}</td><td>{gross:.2f}</td><td>{tax:.2f}</td><td>{net:.2f}</td></tr>"

    if not body_html:
        body_html = "<tr><td colspan='5'>No data for this month.</td></tr>"

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="card">
        <div class="header">
          {HEADER_ICON}
          <div class="title">
            <h1>Monthly Report</h1>
            <p class="sub">{year}-{month:02d} • Gross / Tax / Net</p>
          </div>
        </div>

        <form method="GET" class="btnrow">
          <input class="input" name="year" value="{year}" placeholder="Year">
          <input class="input" name="month" value="{month}" placeholder="Month (1-12)">
          <button class="purple" type="submit">View</button>
          <a href="/admin"><button class="gray" type="button">Back</button></a>
        </form>

        <div class="tablewrap">
          <table>
            <thead><tr><th>Employee</th><th>Hours</th><th>Gross</th><th>Tax (20%)</th><th>Net</th></tr></thead>
            <tbody>{body_html}</tbody>
            <tfoot>
              <tr>
                <td>Totals</td>
                <td>{hours_to_hm(total_hours)}</td>
                <td>{total_gross:.2f}</td>
                <td>{total_tax:.2f}</td>
                <td>{total_net:.2f}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>
    """)

# ---------- EMPLOYEE MANAGEMENT (ADMIN) ----------
@app.route("/employees", methods=["GET", "POST"])
def employees():
    gate = require_admin()
    if gate:
        return gate

    msg = ""
    msg_class = "message"

    headers, values = get_employees_headers()
    required = ["Username", "Password", "Role", "Rate"]
    missing = [c for c in required if c not in headers]
    if missing:
        return f"Employees sheet missing headers: {missing} (Row 1 must have Username, Password, Role, Rate)", 500

    def col_index(name: str) -> int:
        return headers.index(name) + 1  # 1-based for gspread

    records = employees_sheet.get_all_records()

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add":
            u = request.form.get("new_username", "").strip()
            p = request.form.get("new_password", "").strip()
            r = request.form.get("new_role", "employee").strip()
            rate = request.form.get("new_rate", "0").strip()

            if not u or not p:
                msg = "Username and password are required."
                msg_class = "message error"
            elif any(rec.get("Username") == u for rec in records):
                msg = "Username already exists."
                msg_class = "message error"
            else:
                employees_sheet.append_row([u, p, r, rate])
                msg = "Employee added."

        elif action == "update":
            rownum = int(request.form.get("rownum", "0"))
            new_pass = request.form.get("password", "").strip()
            new_role = request.form.get("role", "employee").strip()
            new_rate = request.form.get("rate", "0").strip()

            if rownum <= 1:
                msg = "Invalid row."
                msg_class = "message error"
            else:
                if new_pass:
                    employees_sheet.update_cell(rownum, col_index("Password"), new_pass)
                employees_sheet.update_cell(rownum, col_index("Role"), new_role)
                employees_sheet.update_cell(rownum, col_index("Rate"), new_rate)
                msg = "Employee updated."

        elif action == "delete":
            rownum = int(request.form.get("rownum", "0"))
            if rownum <= 1:
                msg = "Invalid row."
                msg_class = "message error"
            else:
                employees_sheet.delete_rows(rownum)
                msg = "Employee deleted."

        headers, values = get_employees_headers()
        records = employees_sheet.get_all_records()

    table_rows_html = ""
    for idx, rec in enumerate(records, start=2):
        u = rec.get("Username", "")
        role = rec.get("Role", "employee")
        rate = rec.get("Rate", "")

        table_rows_html += f"""
        <tr>
          <td>{idx}</td>
          <td>{u}</td>
          <td>
            <form method="POST" style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
              <input type="hidden" name="action" value="update">
              <input type="hidden" name="rownum" value="{idx}">
              <input class="input" name="password" placeholder="New password (optional)" style="max-width:260px;">
              <select class="input" name="role" style="max-width:180px;">
                <option value="employee" {"selected" if role=="employee" else ""}>employee</option>
                <option value="admin" {"selected" if role=="admin" else ""}>admin</option>
              </select>
              <input class="input" name="rate" value="{rate}" placeholder="Rate" style="max-width:160px;">
              <button class="blue" type="submit" style="min-height:44px;">Save</button>
            </form>
          </td>
          <td>
            <form method="POST" onsubmit="return confirm('Delete {u}?');">
              <input type="hidden" name="action" value="delete">
              <input type="hidden" name="rownum" value="{idx}">
              <button class="red" type="submit" style="min-height:44px;">Delete</button>
            </form>
          </td>
        </tr>
        """

    return render_template_string(f"""
    {STYLE}{VIEWPORT}{PWA_TAGS}
    <div class="app">
      <div class="card">
        <div class="header">
          {HEADER_ICON}
          <div class="title">
            <h1>Employees</h1>
            <p class="sub">Add / edit / delete employees</p>
          </div>
        </div>

        {"<div class='" + msg_class + "'>" + msg + "</div>" if msg else ""}

        <h2 style="margin-top:10px;">Add employee</h2>
        <form method="POST">
          <input type="hidden" name="action" value="add">
          <input class="input" name="new_username" placeholder="Username" required>
          <input class="input" name="new_password" placeholder="Password" required>
          <select class="input" name="new_role">
            <option value="employee">employee</option>
            <option value="admin">admin</option>
          </select>
          <input class="input" name="new_rate" placeholder="Rate (e.g. 12.5)" required>

          <div class="btnrow actionbar">
            <button class="green" type="submit">Add</button>
            <a href="/admin"><button class="gray" type="button">Back</button></a>
          </div>
        </form>

        <h2 style="margin-top:22px;">Manage</h2>
        <div class="tablewrap">
          <table>
            <thead>
              <tr>
                <th>Row</th>
                <th>Username</th>
                <th>Edit</th>
                <th>Delete</th>
              </tr>
            </thead>
            <tbody>
              {table_rows_html if table_rows_html else "<tr><td colspan='4'>No employees found.</td></tr>"}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    """)

# ================= LOCAL RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)


