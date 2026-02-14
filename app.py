import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, render_template_string, request, redirect, session
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ================= GOOGLE SHEETS CONNECTION =================

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

spreadsheet = client.open("WorkHours")
employees_sheet = spreadsheet.worksheet("Employees")
work_sheet = spreadsheet.worksheet("WorkHours")

# ================= LOGIN PAGE =================

LOGIN_HTML = """
<h2>Login</h2>
<form method="POST">
<input name="username" placeholder="Username" required><br><br>
<input type="password" name="password" placeholder="Password" required><br><br>
<button>Login</button>
</form>
<p style="color:red;">{{ message }}</p>
"""

# ================= CLOCK PAGE =================

CLOCK_HTML = """
<h2>Clock In System</h2>
<p>Welcome {{ username }}</p>

<form method="POST">
<button name="action" value="in">Clock In</button>
<button name="action" value="out">Clock Out</button>
</form>

<h3>Hours Today: {{ daily_hours }}</h3>
<h3>Total This Week: {{ weekly_hours }}</h3>

<p style="color:green;">{{ message }}</p>
<a href="/logout">Logout</a>
"""

# ================= LOGIN =================

@app.route("/login", methods=["GET", "POST"])
def login():
    message = ""

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        users = employees_sheet.get_all_records()

        for user in users:
            if user["Username"] == username and user["Password"] == password:
                session["username"] = username
                return redirect("/")

        message = "Invalid login"

    return render_template_string(LOGIN_HTML, message=message)

# ================= LOGOUT =================

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ================= HOME =================

@app.route("/", methods=["GET", "POST"])
def home():

    if "username" not in session:
        return redirect("/login")

    username = session["username"]
    message = ""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    rows = work_sheet.get_all_values()

    # ================= CLOCK ACTIONS =================

    if request.method == "POST":
        action = request.form["action"]

        # -------- CLOCK IN --------
        if action == "in":

            # Prevent double clock in same day
            for row in rows[1:]:
                if row[0] == username and row[1] == today_str:
                    message = "You already clocked in today"
                    break
            else:
                work_sheet.append_row([
                    username,
                    today_str,
                    now.strftime("%H:%M:%S"),
                    "",   # Clock Out
                    ""    # Hours
                ])
                message = "Clocked In"

        # -------- CLOCK OUT --------
        elif action == "out":

            for i in range(len(rows) - 1, 0, -1):
                if rows[i][0] == username and rows[i][3] == "":
                    clock_in_time = datetime.strptime(
                        rows[i][1] + " " + rows[i][2],
                        "%Y-%m-%d %H:%M:%S"
                    )

                    seconds = (now - clock_in_time).total_seconds()
                    hours = round(seconds / 3600, 2)

                    work_sheet.update_cell(i + 1, 4, now.strftime("%H:%M:%S"))
                    work_sheet.update_cell(i + 1, 5, hours)

                    message = f"Shift Hours: {hours}"
                    break
            else:
                message = "No active shift"

    # ================= CALCULATE TOTALS =================

    daily_hours = 0
    weekly_hours = 0

    today = now.date()
    week_start = today - timedelta(days=today.weekday())

    rows = work_sheet.get_all_values()

    for row in rows[1:]:
        if row[0] == username and row[4] != "":
            row_date = datetime.strptime(row[1], "%Y-%m-%d").date()
            hours = float(row[4])

            if row_date == today:
                daily_hours += hours

            if row_date >= week_start:
                weekly_hours += hours

    return render_template_string(
        CLOCK_HTML,
        username=username,
        message=message,
        daily_hours=round(daily_hours, 2),
        weekly_hours=round(weekly_hours, 2)
    )

# ================= RUN =================

if __name__ == "__main__":
    app.run()


