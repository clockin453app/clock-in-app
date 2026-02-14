import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, render_template_string, request, redirect, session, url_for
from datetime import datetime, timedelta

app = Flask(__name__)

# Render: set SECRET_KEY in environment
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

# ================= GOOGLE SHEETS =================

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

def load_google_creds_dict():
    """
    Production (Render): GOOGLE_CREDENTIALS env var (JSON string).
    Local: optional credentials.json file in same folder as app.py.
    """
    if "GOOGLE_CREDENTIALS" in os.environ and os.environ["GOOGLE_CREDENTIALS"].strip():
        return json.loads(os.environ["GOOGLE_CREDENTIALS"])
    # Local fallback (DO NOT commit credentials.json)
    with open("credentials.json", "r", encoding="utf-8") as f:
        return json.load(f)

creds_dict = load_google_creds_dict()
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(creds)

# Spreadsheet + worksheet names (must match your Google Sheets)
spreadsheet = client.open("WorkHours")
employees_sheet = spreadsheet.worksheet("Employees")
work_sheet = spreadsheet.worksheet("WorkHours")
payroll_sheet = spreadsheet.worksheet("PayrollReports")

# ================= GLOBAL STYLE =================

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
table{width:100%; border-collapse:collapse; margin-top:20px;}
th,td{padding:8px; border-bottom:1px solid #ddd; text-align:center;}
th{background:#f1f1f1;}
form input, form select{padding:6px; margin:5px;}
.link{text-align:center; margin-top:20px;}
.message{text-align:center; font-weight:bold; color:green;}
.message.error{color:#dc3545;}
</style>
"""

# ================= HELPERS =================

# WorkHours columns (0-based in Python list)
# Username | Date | ClockIn | ClockOut | Hours | Pay | (optional notes)
COL_USER = 0
COL_DATE = 1
COL_IN = 2
COL_OUT = 3
COL_HOURS = 4
COL_PAY = 5

def require_login():
    if "username" not in session:
        return redirect(url_for("login"))
    # if session got invalidated, force fresh login
    if "role" not in session or "rate" not in session:
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

def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

# ================= LOGIN =================

@app.route("/login", methods=["GET", "POST"])
def login():
    message = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        users = employees_sheet.get_all_records()  # expects headers in row 1
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
        <input type="password" name="password" placeholder="Password" required><br>
        <button class="adminbtn" type="submit">Login</button>
      </form>
      <p class="message error">{message}</p>
    </div>
    """)

# ================= LOGOUT =================

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ================= HOME =================

@app.route("/", methods=["GET", "POST"])
def home():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    rate = safe_float(session.get("rate", 0), 0.0)

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    message = ""
    message_class = "message"

    rows = work_sheet.get_all_values()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "in":
            # prevent double clock-in if last shift has no clock_out
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
                    pay = round(hours * rate, 2)

                    sheet_row = i + 1  # gspread is 1-based
                    work_sheet.update_cell(sheet_row, COL_OUT + 1, now.strftime("%H:%M:%S"))
                    work_sheet.update_cell(sheet_row, COL_HOURS + 1, hours)
                    work_sheet.update_cell(sheet_row, COL_PAY + 1, pay)

                    message = f"Shift: {hours}h | Pay: {pay}"
                    break
            else:
                message = "No active shift found to clock out."
                message_class = "message error"

    # totals
    daily_hours = weekly_hours = daily_pay = weekly_pay = 0.0
    today = now.date()
    week_start = today - timedelta(days=today.weekday())

    rows = work_sheet.get_all_values()
    for row in rows[1:]:
        if len(row) <= COL_PAY:
            continue
        if row[COL_USER] == username and row[COL_HOURS] != "":
            row_date = None
            try:
                row_date = datetime.strptime(row[COL_DATE], "%Y-%m-%d").date()
            except Exception:
                continue

            hours = safe_float(row[COL_HOURS], 0.0)
            pay = safe_float(row[COL_PAY], 0.0)

            if row_date == today:
                daily_hours += hours
                daily_pay += pay
            if row_date >= week_start:
                weekly_hours += hours
                weekly_pay += pay

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
      <p>Today Pay: {round(daily_pay, 2)}</p>
      <p>Week Hours: {round(weekly_hours, 2)}</p>
      <p>Week Pay: {round(weekly_pay, 2)}</p>

      <p class="{message_class}">{message}</p>

      <div class="buttons">{admin_link}</div>
      <div class="link"><a href="/logout">Logout</a></div>
    </div>
    """)

# ================= ADMIN DASHBOARD =================

@app.route("/admin")
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

# ================= WEEKLY REPORT =================

@app.route("/weekly")
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

# ================= MONTHLY REPORT =================

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
            # Keeping your structure: using "Week" column to store the month number for Monthly rows
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
# On Render you use Gunicorn, so this block is only for local runs.

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)


