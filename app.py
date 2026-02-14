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
    """
    Render: GOOGLE_CREDENTIALS env var contains service-account JSON.
    Local: optional credentials.json file (DO NOT commit).
    """
    raw = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
    if raw:
        return json.loads(raw)

    # Local fallback
    with open("credentials.json", "r", encoding="utf-8") as f:
        return json.load(f)

creds_dict = load_google_creds_dict()
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(creds)

# Names must match your Google Sheet
spreadsheet = client.open("WorkHours")
employees_sheet = spreadsheet.worksheet("Employees")
work_sheet = spreadsheet.worksheet("WorkHours")
payroll_sheet = spreadsheet.worksheet("PayrollReports")

# WorkHours columns (0-based in python list)
# Username | Date | ClockIn | ClockOut | Hours | Pay | Notes(optional)
COL_USER = 0
COL_DATE = 1
COL_IN = 2
COL_OUT = 3
COL_HOURS = 4
COL_PAY = 5

# ================= STYLE =================

STYLE = """
<style>
body {font-family: Arial; background:#f4f6f9; padding:40px;}
.container {max-width:900px; margin:auto; background:white; padding:30px; border-radius:12px; box-shadow:0 5px 20px rgba(0,0,0,0.08);}
h2,h3{text-align:center;}
.buttons{display:flex; justify-content:center; gap:15px; margin:20px 0; flex-wrap:wrap;}
button{padding:10px 20px; border:none; border-radius:6px; font-weight:bold; cursor:pointer;}
.clockin{background:#28a745;color:white;}
.clockout{background:#dc3545;color:white;}
.adminbtn{background:#007bff;color:white;}
.reportbtn{background:#6f42c1;color:white;}
button:hover{opacity:0.9;}
.link{text-align:center; margin-top:20px;}
.message{text-align:center; font-weight:bold; color:green;}
.message.error{color:#dc3545;}
</style>
"""

# ================= HELPERS =================

def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def require_login():
    if "username" not in session:
        return redirect(url_for("login"))
    # If session is broken/expired, force re-login
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

# ================= ROUTES =================

@app.get("/ping")
def ping():
    return "pong", 200

# -------- LOGIN --------

@app.route("/login", methods=["GET", "POST"])
def login():
    message = ""
    message_class = "message error"

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        users = employees_sheet.get_all_records()  # headers: Username, Password, Role, Rate
        for user in users:
            if user.get("Username") == username and user.get("Password") == password:
                session.clear()
                session["username"] = username
                session["role"] = user.get("Role", "employee")
                session["rate"] = safe_float(user.get("Rate", 0), 0.0)
                return redirect(url_for("home"))

        message = "Invalid login"

    return render_template_string(f"""
    {STYLE}
    <div class="container">
      <h2>Login</h2>
      <form method="POST">
        <input name="username" placeholder="Username" required><br>
        <input type="password" name="password" placeholder="Password" required><br><br>
        <button class="adminbtn" type="submit">Login</button>
      </form>
      <p class="{message_class}">{message}</p>
    </div>
    """)

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------- HOME (NO PAY SHOWN) --------

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
    message_class = "message"

    rows = work_sheet.get_all_values()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "in":
            # prevent double clock-in if last shift not closed
            for i in range(len(rows) - 1, 0, -1):
                if rows[i][COL_USER] == username and rows[i][COL_OUT] == "":
                    message = "You are already clocked in."
                    message_class = "message error"
                    break
            else:
                work_sheet.append_row([username, today_str, now.strftime("%H:%M:%S"), "", "", "", ""])
                message = "Clocked In"

        elif action == "out":
            for i in range(len(rows) - 1, 0, -1):
                if rows[i][COL_USER] == username and rows[i][COL_OUT] == "":
                    clock_in = datetime.strptime(
                        rows[i][COL_DATE] + " " + rows[i][COL_IN],
                        "%Y-%m-%d %H:%M:%S"
                    )
                    hours = round((now - clock_in).total_seconds() / 3600, 2)

                    # Pay is calculated + stored, but NEVER displayed on home UI
                    pay = round(hours * rate, 2)

                    sheet_row = i + 1  # gspread rows are 1-based
                    work_sheet.update_cell(sheet_row, COL_OUT + 1, now.strftime("%H:%M:%S"))
                    work_sheet.update_cell(sheet_row, COL_HOURS + 1, hours)
                    work_sheet.update_cell(sheet_row, COL_PAY + 1, pay)

                    message = f"Shift: {hours}h"
                    break
            else:
                message = "No active shift found to clock out."
                message_class = "message error"

    # Compute totals (hours only for UI)
    daily_hours = 0.0
    weekly_hours = 0.0

    rows = work_sheet.get_all_values()
    for row in rows[1:]:
        if len(row) <= COL_HOURS:
            continue
        if row[COL_USER] != username:
            continue
        if row[COL_HOURS] == "":
            continue

        try:
            row_date = datetime.strptime(row[COL_DATE], "%Y-%m-%d").date()
        except Exception:
            continue

        h = safe_float(row[COL_HOURS], 0.0)

        if row_date == today:
            daily_hours += h
        if row_date >= week_start:
            weekly_hours += h

    admin_link = (
        "<a href='/admin'><button class='adminbtn'>Admin Dashboard</button></a>"
        if role == "admin" else ""
    )

    return render_template_string(f"""
    {STYLE}
    <div class="container">
      <h2>Welcome {username}</h2>

      <form method="POST" class="buttons">
        <button name="action" value="in" class="clockin">Clock In</button>
        <button name="action" value="out" class="clockout">Clock Out</button>
      </form>

      <p>Today Hours: {round(daily_hours, 2)}</p>
      <p>Week Hours: {round(weekly_hours, 2)}</p>

      <p class="{message_class}">{message}</p>

      <div class="buttons">{admin_link}</div>
      <div class="link"><a href="/logout">Logout</a></div>
    </div>
    """)

# -------- ADMIN --------

@app.get("/admin")
def admin():
    gate = require_admin()
    if gate:
        return gate

    return render_template_string(f"""
    {STYLE}
    <div class="container">
      <h2>Admin Dashboard</h2>
      <div class="buttons">
        <a href="/weekly"><button class="reportbtn">Generate Weekly Payroll</button></a>
        <a href="/monthly"><button class="reportbtn">Generate Monthly Payroll</button></a>
      </div>
      <div class="link"><a href="/">Back</a></div>
    </div>
    """)

# -------- WEEKLY REPORT (STORES PAY IN SHEET, NOT HOME UI) --------

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

    for row in rows[1:]:
        if len(row) <= COL_PAY or row[COL_HOURS] == "":
            continue
        try:
            row_date = datetime.strptime(row[COL_DATE], "%Y-%m-%d")
        except Exception:
            continue

        y, w, _ = row_date.isocalendar()
        if y == year and w == week_number:
            emp = row[COL_USER]
            payroll.setdefault(emp, {"hours": 0.0, "pay": 0.0})
            payroll[emp]["hours"] += safe_float(row[COL_HOURS], 0.0)
            payroll[emp]["pay"] += safe_float(row[COL_PAY], 0.0)

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
        selected = request.form["month"]  # YYYY-MM
        year = int(selected.split("-")[0])
        month = int(selected.split("-")[1])
        generated_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        existing = payroll_sheet.get_all_records()
        for row in existing:
            # Uses "Week" column to store month number for Monthly rows (keeps your structure)
            if row.get("Type") == "Monthly" and int(row.get("Year", 0)) == year and int(row.get("Week", 0)) == month:
                return "Monthly payroll already generated."

        rows = work_sheet.get_all_values()
        payroll = {}

        for row in rows[1:]:
            if len(row) <= COL_PAY or row[COL_HOURS] == "":
                continue
            try:
                row_date = datetime.strptime(row[COL_DATE], "%Y-%m-%d")
            except Exception:
                continue

            if row_date.year == year and row_date.month == month:
                emp = row[COL_USER]
                payroll.setdefault(emp, {"hours": 0.0, "pay": 0.0})
                payroll[emp]["hours"] += safe_float(row[COL_HOURS], 0.0)
                payroll[emp]["pay"] += safe_float(row[COL_PAY], 0.0)

        for employee, data in payroll.items():
            payroll_sheet.append_row([
                "Monthly", year, month, employee,
                round(data["hours"], 2),
                round(data["pay"], 2),
                generated_on
            ])

        return "Monthly payroll stored successfully."

    return render_template_string(f"""
    {STYLE}
    <div class="container">
      <h2>Select Month</h2>
      <form method="POST">
        <input type="month" name="month" required>
        <button class="adminbtn" type="submit">Generate Monthly Payroll</button>
      </form>
      <div class="link"><a href="/admin">Back</a></div>
    </div>
    """)

# ================= LOCAL RUN =================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
