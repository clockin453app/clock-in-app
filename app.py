import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, render_template_string, request, redirect, session
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ================= GOOGLE SHEETS =================

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
</style>
"""

# ================= LOGIN =================

@app.route("/login", methods=["GET","POST"])
def login():
    message=""
    if request.method=="POST":
        username=request.form["username"]
        password=request.form["password"]
        users=employees_sheet.get_all_records()
        for user in users:
            if user["Username"]==username and user["Password"]==password:
                session["username"]=username
                session["role"]=user["Role"]
                session["rate"]=float(user["Rate"])
                return redirect("/")
        message="Invalid login"

    return render_template_string(f"""
    {STYLE}
    <div class="container">
    <h2>Login</h2>
    <form method="POST">
    <input name="username" placeholder="Username" required><br>
    <input type="password" name="password" placeholder="Password" required><br>
    <button class="adminbtn">Login</button>
    </form>
    <p style="color:red;text-align:center;">{message}</p>
    </div>
    """)

# ================= LOGOUT =================

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ================= HOME =================

@app.route("/", methods=["GET","POST"])
def home():
    if "username" not in session:
        return redirect("/login")

    username=session["username"]
    role=session["role"]
    rate=session["rate"]
    now=datetime.now()
    today_str=now.strftime("%Y-%m-%d")
    message=""

    rows=work_sheet.get_all_values()

    if request.method=="POST":
        action=request.form["action"]

        if action=="in":
            work_sheet.append_row([username,today_str,now.strftime("%H:%M:%S"),"","",""])
            message="Clocked In"

        elif action=="out":
            for i in range(len(rows)-1,0,-1):
                if rows[i][0]==username and rows[i][3]=="":
                    clock_in=datetime.strptime(rows[i][1]+" "+rows[i][2],"%Y-%m-%d %H:%M:%S")
                    hours=round((now-clock_in).total_seconds()/3600,2)
                    pay=round(hours*rate,2)
                    work_sheet.update_cell(i+1,4,now.strftime("%H:%M:%S"))
                    work_sheet.update_cell(i+1,5,hours)
                    work_sheet.update_cell(i+1,6,pay)
                    message=f"Shift: {hours}h | Pay: {pay}"
                    break

    daily_hours=weekly_hours=daily_pay=weekly_pay=0
    today=now.date()
    week_start=today-timedelta(days=today.weekday())

    rows=work_sheet.get_all_values()
    for row in rows[1:]:
        if row[0]==username and row[4]!="":
            row_date=datetime.strptime(row[1],"%Y-%m-%d").date()
            hours=float(row[4]); pay=float(row[5])
            if row_date==today:
                daily_hours+=hours; daily_pay+=pay
            if row_date>=week_start:
                weekly_hours+=hours; weekly_pay+=pay

    admin_link=f"<a href='/admin'><button class='adminbtn'>Admin Dashboard</button></a>" if role=="admin" else ""

    return render_template_string(f"""
    {STYLE}
    <div class="container">
    <h2>Welcome {username}</h2>
    <form method="POST" class="buttons">
        <button name="action" value="in" class="clockin">Clock In</button>
        <button name="action" value="out" class="clockout">Clock Out</button>
    </form>

    <p>Today Hours: {round(daily_hours,2)}</p>
    <p>Today Pay: {round(daily_pay,2)}</p>
    <p>Week Hours: {round(weekly_hours,2)}</p>
    <p>Week Pay: {round(weekly_pay,2)}</p>

    <p class="message">{message}</p>

    <div class="buttons">{admin_link}</div>
    <div class="link"><a href="/logout">Logout</a></div>
    </div>
    """)

# ================= ADMIN DASHBOARD =================

@app.route("/admin")
def admin():
    if "username" not in session or session["role"]!="admin":
        return redirect("/")

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
    if "username" not in session or session["role"]!="admin":
        return redirect("/")

    now=datetime.now()
    year, week_number, _=now.isocalendar()
    generated_on=now.strftime("%Y-%m-%d %H:%M:%S")

    existing=payroll_sheet.get_all_records()

    for row in existing:
        if row["Type"]=="Weekly" and int(row["Year"])==year and int(row["Week"])==week_number:
            return "Weekly payroll already generated."

    rows=work_sheet.get_all_values()
    payroll={}

    for row in rows[1:]:
        if row[4]!="":
            row_date=datetime.strptime(row[1],"%Y-%m-%d")
            y,w,_=row_date.isocalendar()
            if y==year and w==week_number:
                payroll.setdefault(row[0],{"hours":0,"pay":0})
                payroll[row[0]]["hours"]+=float(row[4])
                payroll[row[0]]["pay"]+=float(row[5])

    for employee,data in payroll.items():
        payroll_sheet.append_row([
            "Weekly",year,week_number,employee,
            round(data["hours"],2),
            round(data["pay"],2),
            generated_on
        ])

    return "Weekly payroll stored successfully."

# ================= MONTHLY REPORT =================

@app.route("/monthly", methods=["GET","POST"])
def monthly_report():
    if "username" not in session or session["role"]!="admin":
        return redirect("/")

    if request.method=="POST":
        selected=request.form["month"]
        year=int(selected.split("-")[0])
        month=int(selected.split("-")[1])
        generated_on=datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        existing=payroll_sheet.get_all_records()

        for row in existing:
            if row["Type"]=="Monthly" and int(row["Year"])==year and int(row["Week"])==month:
                return "Monthly payroll already generated."

        rows=work_sheet.get_all_values()
        payroll={}

        for row in rows[1:]:
            if row[4]!="":
                row_date=datetime.strptime(row[1],"%Y-%m-%d")
                if row_date.year==year and row_date.month==month:
                    payroll.setdefault(row[0],{"hours":0,"pay":0})
                    payroll[row[0]]["hours"]+=float(row[4])
                    payroll[row[0]]["pay"]+=float(row[5])

        for employee,data in payroll.items():
            payroll_sheet.append_row([
                "Monthly",year,month,employee,
                round(data["hours"],2),
                round(data["pay"],2),
                generated_on
            ])

        return "Monthly payroll stored successfully."

    return render_template_string(f"""
    {STYLE}
    <div class="container">
    <h2>Select Month</h2>
    <form method="POST">
        <input type="month" name="month" required>
        <button class="adminbtn">Generate Monthly Payroll</button>
    </form>
    <div class="link"><a href="/admin">Back</a></div>
    </div>
    """)

# ================= RUN =================

if __name__=="__main__":
    app.run()


