import csv
import io


def admin_system_health_impl(core):
    require_master_admin = core["require_master_admin"]
    session = core["session"]
    os = core["os"]
    inspect = core["inspect"]
    db = core["db"]

    APP_ENV = core["APP_ENV"]
    DATABASE_ENABLED = core["DATABASE_ENABLED"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]

    Employee = core["Employee"]
    WorkHour = core["WorkHour"]
    PayrollReport = core["PayrollReport"]
    OnboardingRecord = core["OnboardingRecord"]
    Location = core["Location"]
    AuditLog = core["AuditLog"]

    get_employees = core["get_employees"]
    get_workhours_rows = core["get_workhours_rows"]
    get_payroll_rows = core["get_payroll_rows"]
    get_locations = core["get_locations"]
    onboarding_sheet = core["onboarding_sheet"]

    ONBOARDING_UPLOADS_DIR = core["ONBOARDING_UPLOADS_DIR"]
    DRIVE_TOKEN_STORE_PATH = core["DRIVE_TOKEN_STORE_PATH"]

    _list_current_live_sessions = core["_list_current_live_sessions"]

    datetime = core["datetime"]
    TZ = core["TZ"]
    escape = core["escape"]
    admin_back_link = core["admin_back_link"]

    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    render_template_string = core["render_template_string"]

    gate = require_master_admin()
    if gate:
        return gate

    role = session.get("role", "master_admin")
    now_text = datetime.now(TZ).strftime("%d %b %Y • %H:%M:%S")

    health_rows = []

    def add_row(area, details="", level="ok"):
        if level == "ok":
            badge = "<span class='chip ok'>OK</span>"
        elif level == "warn":
            badge = "<span class='chip warn'>Warning</span>"
        else:
            badge = "<span class='chip bad'>Error</span>"

        health_rows.append(f"""
          <tr>
            <td style="font-weight:800;">{escape(area)}</td>
            <td>{badge}</td>
            <td style="white-space:normal;">{escape(str(details or ""))}</td>
          </tr>
        """)

    def safe_check(label, fn):
        try:
            result = fn()
            add_row(label, result, "ok")
        except Exception as e:
            add_row(label, str(e), "bad")

    add_row(
        "App mode",
        f"APP_ENV={APP_ENV} • DB_MIGRATION_MODE={DB_MIGRATION_MODE} • DATABASE_ENABLED={DATABASE_ENABLED}",
        "ok",
    )

    if DB_MIGRATION_MODE:
        try:
            tables = inspect(db.engine).get_table_names()
            expected_tables = [
                "employees",
                "workhours",
                "payroll_reports",
                "onboarding_records",
                "locations",
                "workplace_settings",
                "audit_logs",
            ]
            missing = [t for t in expected_tables if t not in tables]

            if missing:
                add_row("Database tables", "Missing: " + ", ".join(missing), "warn")
            else:
                add_row("Database tables", f"{len(tables)} tables found", "ok")

        except Exception as e:
            add_row("Database connection", str(e), "bad")

        safe_check("Employees", lambda: f"{Employee.query.count()} rows")
        safe_check("Workhours", lambda: f"{WorkHour.query.count()} rows")
        safe_check("Payroll reports", lambda: f"{PayrollReport.query.count()} rows")
        safe_check("Onboarding records", lambda: f"{OnboardingRecord.query.count()} rows")
        safe_check("Locations", lambda: f"{Location.query.count()} rows")
        safe_check("Audit logs", lambda: f"{AuditLog.query.count()} rows")

    else:
        add_row(
            "Database mode",
            "Database migration mode is OFF. App is using Google Sheets/runtime data.",
            "warn",
        )

        safe_check("Employees data", lambda: f"{len(get_employees() or [])} rows")
        safe_check("Workhours data", lambda: f"{max(0, len(get_workhours_rows() or []) - 1)} rows")
        safe_check("Payroll data", lambda: f"{max(0, len(get_payroll_rows() or []) - 1)} rows")
        safe_check("Locations data", lambda: f"{len(get_locations() or [])} rows")

        try:
            vals = onboarding_sheet.get_all_values()
            add_row("Onboarding data", f"{max(0, len(vals or []) - 1)} rows", "ok")
        except Exception as e:
            add_row("Onboarding data", str(e), "bad")

    try:
        upload_dir = os.environ.get("ONBOARDING_UPLOADS_DIR", "").strip() or ONBOARDING_UPLOADS_DIR

        if upload_dir and os.path.isdir(upload_dir):
            add_row("Onboarding upload storage", f"Folder exists: {upload_dir}", "ok")
        elif upload_dir:
            add_row("Onboarding upload storage", f"Folder not found yet: {upload_dir}", "warn")
        else:
            add_row("Onboarding upload storage", "ONBOARDING_UPLOADS_DIR is not configured.", "warn")

    except Exception as e:
        add_row("Onboarding upload storage", str(e), "bad")

    try:
        drive_token_path = os.environ.get("DRIVE_TOKEN_STORE_PATH", DRIVE_TOKEN_STORE_PATH)

        if drive_token_path and os.path.exists(drive_token_path):
            add_row("Google Drive token", "Drive token file exists.", "ok")
        else:
            add_row("Google Drive token", "Drive token file not found. Drive uploads may use fallback or fail.", "warn")

    except Exception as e:
        add_row("Google Drive token", str(e), "bad")

    try:
        live_rows = _list_current_live_sessions()
        live_count = sum(1 for r in live_rows if r.get("is_live"))
        add_row("Live sessions", f"{live_count} live / {len(live_rows)} tracked", "ok")
    except Exception as e:
        add_row("Live sessions", str(e), "warn")

    table_html = "".join(health_rows) or """
      <tr>
        <td colspan="3" style="padding:16px;">No health checks available.</td>
      </tr>
    """

    content = f"""
      {admin_back_link("/admin")}

      <div class="headerTop">
        <div>
          <h1>System Health</h1>
          <p class="sub">Master Admin only • read-only system checks.</p>
          <p class="sub" style="margin-top:4px;">Checked: {escape(now_text)}</p>
        </div>
        <div class="badge admin">MASTER ADMIN</div>
      </div>

      <div class="card" style="padding:14px; margin-top:12px;">
        <div style="display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; align-items:flex-start;">
          <div>
            <h2 style="margin:0;">Health checks</h2>
            <p class="sub" style="margin:4px 0 0 0;">
              This page does not change anything. It only checks app, database, storage and session status.
            </p>
          </div>

          <a href="/admin/system-health" class="btnTiny" style="text-decoration:none;">Refresh</a>
        </div>

        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:900px;">
            <thead>
              <tr>
                <th>Area</th>
                <th>Status</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {table_html}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card" style="padding:14px; margin-top:12px;">
        <h2 style="margin:0;">Backup exports</h2>
        <p class="sub" style="margin:8px 0 0 0;">
          Master Admin only. These buttons download read-only CSV backups. They do not change data.
        </p>

        <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; margin-top:14px;">
          <a class="btnTiny" style="text-decoration:none; text-align:center;" href="/admin/system-health/backup/employees">Employees CSV</a>
          <a class="btnTiny" style="text-decoration:none; text-align:center;" href="/admin/system-health/backup/workhours">Workhours CSV</a>
          <a class="btnTiny" style="text-decoration:none; text-align:center;" href="/admin/system-health/backup/payroll">Payroll CSV</a>
          <a class="btnTiny" style="text-decoration:none; text-align:center;" href="/admin/system-health/backup/onboarding">Onboarding CSV</a>
          <a class="btnTiny" style="text-decoration:none; text-align:center;" href="/admin/system-health/backup/locations">Locations CSV</a>
          <a class="btnTiny" style="text-decoration:none; text-align:center;" href="/admin/system-health/backup/settings">Settings CSV</a>
          <a class="btnTiny" style="text-decoration:none; text-align:center;" href="/admin/system-health/backup/audit">Audit logs CSV</a>
        </div>
      </div>
    """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", role, content)
    )


def admin_system_backup_export_impl(core, dataset):
    require_master_admin = core["require_master_admin"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    make_response = core["make_response"]

    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]

    Employee = core["Employee"]
    WorkHour = core["WorkHour"]
    PayrollReport = core["PayrollReport"]
    OnboardingRecord = core["OnboardingRecord"]
    Location = core["Location"]
    WorkplaceSetting = core["WorkplaceSetting"]
    AuditLog = core["AuditLog"]

    get_employees = core["get_employees"]
    get_workhours_rows = core["get_workhours_rows"]
    get_payroll_rows = core["get_payroll_rows"]
    get_locations = core["get_locations"]
    get_settings = core["get_settings"]
    onboarding_sheet = core["onboarding_sheet"]
    audit_sheet = core["audit_sheet"]

    gate = require_master_admin()
    if gate:
        return gate

    dataset = str(dataset or "").strip().lower()
    allowed = {
        "employees",
        "workhours",
        "payroll",
        "onboarding",
        "locations",
        "settings",
        "audit",
    }

    if dataset not in allowed:
        response = make_response("Unknown backup dataset", 404)
        response.headers["Content-Type"] = "text/plain; charset=utf-8"
        return response

    def clean_value(value):
        if value is None:
            return ""
        try:
            if hasattr(value, "isoformat"):
                return value.isoformat()
        except Exception:
            pass
        return str(value)

    def model_rows(model, exclude=None):
        exclude = set(exclude or [])
        columns = [c.name for c in model.__table__.columns if c.name not in exclude]
        rows = [columns]

        for rec in model.query.order_by(model.id.asc()).all():
            rows.append([clean_value(getattr(rec, col, "")) for col in columns])

        return rows

    def dict_rows(items, exclude=None):
        exclude = set(exclude or [])
        items = list(items or [])

        headers = []
        seen = set()

        for item in items:
            if not isinstance(item, dict):
                continue

            for key in item.keys():
                key = str(key)

                if key in exclude:
                    continue

                if key not in seen:
                    seen.add(key)
                    headers.append(key)

        rows = [headers]

        for item in items:
            if not isinstance(item, dict):
                continue

            rows.append([clean_value(item.get(h, "")) for h in headers])

        return rows

    if DB_MIGRATION_MODE:
        if dataset == "employees":
            rows = model_rows(Employee, exclude={"password", "active_session_token"})
        elif dataset == "workhours":
            rows = model_rows(WorkHour)
        elif dataset == "payroll":
            rows = model_rows(PayrollReport)
        elif dataset == "onboarding":
            rows = model_rows(OnboardingRecord)
        elif dataset == "locations":
            rows = model_rows(Location)
        elif dataset == "settings":
            rows = model_rows(WorkplaceSetting)
        else:
            rows = model_rows(AuditLog)

    else:
        if dataset == "employees":
            rows = dict_rows(
                get_employees(),
                exclude={"Password", "password", "ActiveSessionToken", "active_session_token"},
            )
        elif dataset == "workhours":
            rows = get_workhours_rows() or []
        elif dataset == "payroll":
            rows = get_payroll_rows() or []
        elif dataset == "onboarding":
            rows = onboarding_sheet.get_all_values() or []
        elif dataset == "locations":
            rows = dict_rows(get_locations())
        elif dataset == "settings":
            rows = dict_rows(get_settings())
        else:
            rows = audit_sheet.get_all_values() or []

    output = io.StringIO()
    writer = csv.writer(output)

    for row in rows:
        if isinstance(row, dict):
            writer.writerow([clean_value(v) for v in row.values()])
        elif isinstance(row, (list, tuple)):
            writer.writerow([clean_value(v) for v in row])
        else:
            writer.writerow([clean_value(row)])

    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    filename = f"timiq_backup_{dataset}_{stamp}.csv"

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-store"

    return response