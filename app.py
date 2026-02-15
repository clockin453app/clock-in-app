import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, render_template_string, request, redirect, session, url_for
from datetime import datetime, timedelta

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
    # Local fallback (DO NOT commit)
    with open("credentials.json", "r", encoding="utf-8") as f:
        return json.load(f)

creds_dict = load_google_creds_dict()
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(creds)

spreadsheet = client.open("WorkHours")
employees_sheet = spreadsheet.worksheet("Employees")
work_sheet = spreadsheet.worksheet("WorkHours")
payroll_sheet = spreadsheet.worksheet("PayrollReports")

# WorkHours columns (0-based)
COL_USER = 0
COL_DATE = 1
COL_IN = 2
COL_OUT = 3
COL_HOURS = 4
COL_PAY = 5

# ================= APP-LIKE UI (BIGGER + MOBILE FIRST) =================
STYLE = """
<style>
:root{
  --bg:#0b1220;
  --panel:#0f172a;
  --card:#111c33;
  --card2:#0b1328;
  --text:#e5e7eb;
  --muted:#a7b0c0;
  --border:rgba(255,255,255,.08);
  --shadow: 0 18px 50px rgba(0,0,0,.45);
  --radius: 22px;

  --h1: clamp(30px, 4.5vw, 46px);
  --h2: clamp(22px, 3.2vw, 30px);
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

.icon{
  width: 74px;
  height: 74px;
  border-radius: 22px;
  background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 55%, #22c55e 120%);
  box-shadow: 0 18px 30px rgba(0,0,0,.35);
  display:grid;
  place-items:center;
  flex: 0 0 auto;
}
.icon span{
  font-size: 34px;
  font-weight: 1000;
  color: rgba(10,15,30,.92);
}

/* Admin table */
.tablewrap{
  margin-top: 16px;
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

.smallbtn{
  padding: 10px 12px;
  min-height: 44px;
  border-radius: 14px;
  font-size: clamp(14px, 2.1vw, 16px);
  flex: 0 0 auto;
}
@media (max-width: 520px){
  .kpis{ grid-template-columns: 1fr; }
}
</style>
"""

VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'

# ================= HELPERS =================
def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

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

def hours_to_hm(decimal_hours: float) -> str:
    total_minutes = int(round(decimal_hours * 60))
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h}h {m:02d}m"

def has_any_row_today(rows, username: str, today_str: str) -> bool:
    for row in rows[1:]:
        if len(row) > COL_DATE and row[COL_USER] == username and row[COL_DATE] == today_str:
            return True
    return False

def find_open_shift(rows, username: str):
    for i in range(len(rows) - 1, 0, -1):
        r = rows[i]
        if len(r) > COL_OUT and r[COL_USER] == username and r[COL_OUT] == "":
            return i, r[COL_DATE], r[COL_IN]
    return None

def find_employee_row_by_username(username: str):
    """
    Returns (row_number, headers) where row_number is 1-based in the sheet.
    If not found, returns (None, headers).
    """
    values = employees_sheet.get_all_values()
    if not values:
        return None, []
    headers = values[0]
    for idx in range(1, len(values)):
        row = values[idx]
        if len(row) > 0 and row[0] == username:  # assumes Username is first column OR we handle headers below
            pass
    # Better: locate Username column by header
    try:
        user_col = headers.index("Username")
    except ValueError:
        return None, headers

    for i in range(1, len(values)):
        row = values[i]
        if len(row) > user_col and row[user_col] == username:
            return i + 1, headers  # sheet row number
    return None, headers

# ================= ROUTES =================
@app.get("/ping")
def ping():
    return "pong", 200

# -------- LOGIN --------
@app.route("/login", methods=["GET", "POST"])
def login():
    message = ""
    msg_class = "message error"

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        users = employees_sheet.get_all_records()  # Username, Password, Role, Rate
        for user in users:
            if user.get("Username") == username and user.get("Password") == password:
                session.clear()
                session["username"] = username
                session["role"] = user.get("Role", "employee")
                session["rate"] = safe_float(user.get("Rate", 0), 0.0)
                return redirect(url_for("home"))

        message = "Invalid login"

    return render_template_string(f"""
    {STYLE}{VIEWPORT}
    <div class="app">
      <div class="card">
        <div class="header">
          <div class="icon"><span>⏱</span></div>
          <div class="title">
            <h1>Clock In</h1>
            <p class="sub">Sign in to continue</p>
          </div>
        </div>

        <h2>Sign in</h2>

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

# -------- CHANGE PASSWORD (EMPLOYEE SELF-SERVICE) --------
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
            # Verify current password from sheet
            records = employees_sheet.get_all_records()
            user_row = None
            for u in records:
                if u.get("Username") == username:
                    user_row = u
                    break

            if not user_row:
                message = "User not found."
                msg_class = "message error"
            elif user_row.get("Password") != current_pw:
                message = "Current password is incorrect."
                msg_class = "message error"
            else:
                rownum, headers = find_employee_row_by_username(username)
                if not rownum:
                    message = "Could not locate your row in Employees sheet."
                    msg_class = "message error"
                else:
                    try:
                        pw_col = headers.index("Password") + 1
                    except ValueError:
                        message = "Employees sheet is missing a 'Password' column header."
                        msg_class = "message error"
                    else:
                        employees_sheet.update_cell(rownum, pw_col, new_pw)
                        message = "Password changed successfully."
                        msg_class = "message"
                        # keep them logged in; nothing else needed

    return render_template_string(f"""
    {STYLE}{VIEWPORT}
    <div class="app">
      <div class="card">
        <div class="header">
          <div class="icon"><span>🔒</span></div>
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
            <a href="/"><button class="gray" type="button" onclick="window.location='/'">Back</button></a>
          </div>
        </form>

        {"<div class='" + msg_class + "'>" + message + "</div>" if message else ""}
      </div>
    </div>
    """)

# -------- HOME (NO PAY SHOWN, LIVE TIMER) --------
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

    # PERFORMANCE: one read
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
                message = "You already clocked in today. Only 1 clock-in per day is allowed."
                msg_class = "message error"
            else:
                work_sheet.append_row([username, today_str, now.strftime("%H:%M:%S"), "", "", "", ""])
                message = "Clocked In"
                msg_class = "message"
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
                hours = round((now - clock_in_dt).total_seconds() / 3600, 4)
                pay = round(hours * rate, 2)  # stored only

                sheet_row = i + 1
                work_sheet.update_cell(sheet_row, COL_OUT + 1, now.strftime("%H:%M:%S"))
                work_sheet.update_cell(sheet_row, COL_HOURS + 1, round(hours, 2))
                work_sheet.update_cell(sheet_row, COL_PAY + 1, pay)

                message = f"Shift time: {hours_to_hm(hours)}"
                msg_class = "message"
                active_clock_in_iso = ""

    # Totals (completed shifts)
    daily_hours = 0.0
    weekly_hours = 0.0
    for r in rows[1:]:
        if len(r) <= COL_HOURS:
            continue
        if r[COL_USER] != username:
            continue
        if r[COL_HOURS] == "":
            continue
        try:
            row_date = datetime.strptime(r[COL_DATE], "%Y-%m-%d").date()
        except Exception:
            continue
        h = safe_float(r[COL_HOURS], 0.0)
        if row_date == today:
            daily_hours += h
        if row_date >= week_start:
            weekly_hours += h

    today_display = hours_to_hm(daily_hours)
    week_display = hours_to_hm(weekly_hours)

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
    {STYLE}{VIEWPORT}
    <div class="app">
      <div class="card">
        <div class="header">
          <div class="icon"><span>⏱</span></div>
          <div class="title">
            <h1>Hi, {username}</h1>
            <p class="sub">Clock in / out</p>
          </div>
        </div>

        <div class="kpis">
          <div class="kpi">
            <div class="label">Today</div>
            <div class="value">{today_display}</div>
            <div class="sub">Completed shift time</div>
          </div>
          <div class="kpi">
            <div class="label">This week</div>
            <div class="value">{week_display}</div>
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
            <a href="/change-password"><button class="blue" type="button" onclick="window.location='/change-password'">Change Password</button></a>
            <a href="/logout"><button class="gray" type="button" onclick="window.location='/logout'">Logout</button></a>
          </div>
        </div>
      </div>
    </div>
    """)

# -------- ADMIN DASHBOARD --------
@app.get("/admin")
def admin():
    gate = require_admin()
    if gate:
        return gate

    return render_template_string(f"""
    {STYLE}{VIEWPORT}
    <div class="app">
      <div class="card">
        <div class="header">
          <div class="icon"><span>🛠</span></div>
          <div class="title">
            <h1>Admin</h1>
            <p class="sub">Reports + Employee management</p>
          </div>
        </div>

        <div class="btnrow actionbar">
          <a href="/weekly"><button class="purple">Generate Weekly Payroll</button></a>
          <a href="/monthly"><button class="purple">Generate Monthly Payroll</button></a>
          <a href="/employees"><button class="blue">Employees</button></a>
          <a href="/"><button class="gray" type="button" onclick="window.location='/'">Back</button></a>
        </div>
      </div>
    </div>
    """)

# -------- EMPLOYEE MANAGEMENT (ADMIN) --------
@app.route("/employees", methods=["GET", "POST"])
def employees():
    gate = require_admin()
    if gate:
        return gate

    msg = ""
    msg_class = "message"

    headers = employees_sheet.row_values(1)
    records = employees_sheet.get_all_records()

    def col_index(name: str) -> int:
        try:
            return headers.index(name) + 1
        except ValueError:
            return -1

    required = ["Username", "Password", "Role", "Rate"]
    missing = [c for c in required if c not in headers]
    if missing:
        return f"Employees sheet missing columns: {missing}. Add them as headers in row 1.", 500

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

        headers = employees_sheet.row_values(1)
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
              <button class="smallbtn blue" type="submit">Save</button>
            </form>
          </td>
          <td>
            <form method="POST" onsubmit="return confirm('Delete {u}?');">
              <input type="hidden" name="action" value="delete">
              <input type="hidden" name="rownum" value="{idx}">
              <button class="smallbtn red" type="submit">Delete</button>
            </form>
          </td>
        </tr>
        """

    return render_template_string(f"""
    {STYLE}{VIEWPORT}
    <div class="app">
      <div class="card">
        <div class="header">
          <div class="icon"><span>👥</span></div>
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
          <div class="btnrow actionbar" style="margin-top:14px;">
            <button class="green" type="submit">Add</button>
            <a href="/admin"><button class="gray" type="button" onclick="window.location='/admin'">Back</button></a>
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

# -------- WEEKLY REPORT --------
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
        payroll_sheet.append_row([
            "Weekly", year, week_number, employee,
            round(data["hours"], 2),
            round(data["pay"], 2),
            generated_on
        ])

    return "Weekly payroll stored successfully."

# -------- MONTHLY REPORT --------
@app.route("/monthly", methods=["GET", "POST"])
def monthly_report():
    gate = require_admin()
    if gate:
        return gate

    if request.method == "POST":
        selected = request.form["month"]
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
            payroll_sheet.append_row([
                "Monthly", year, month, employee,
                round(data["hours"], 2),
                round(data["pay"], 2),
                generated_on
            ])

        return "Monthly payroll stored successfully."

    return render_template_string(f"""
    {STYLE}{VIEWPORT}
    <div class="app">
      <div class="card">
        <div class="header">
          <div class="icon"><span>📅</span></div>
          <div class="title">
            <h1>Monthly report</h1>
            <p class="sub">Pick a month</p>
          </div>
        </div>

        <form method="POST">
          <input class="input" type="month" name="month" required>
          <div class="btnrow actionbar">
            <button class="purple" type="submit">Generate</button>
            <a href="/admin"><button class="gray" type="button" onclick="window.location='/admin'">Back</button></a>
          </div>
        </form>
      </div>
    </div>
    """)

# ================= LOCAL RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
