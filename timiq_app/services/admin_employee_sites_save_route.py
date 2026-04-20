def admin_employee_sites_save_impl(core):
    require_admin = core["require_admin"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    _find_employee_record = core["_find_employee_record"]
    get_sheet_headers = core["get_sheet_headers"]
    employees_sheet = core["employees_sheet"]
    gspread = core["gspread"]
    set_employee_field = core["set_employee_field"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    _session_workplace_id = core["_session_workplace_id"]
    Employee = core["Employee"]
    db = core["db"]
    session = core["session"]
    log_audit = core["log_audit"]
    redirect = core["redirect"]

    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    u = (request.form.get("user") or "").strip()
    s1 = (request.form.get("site1") or "").strip()
    s2 = (request.form.get("site2") or "").strip()

    if s1 and s2 and s1.strip().lower() == s2.strip().lower():
        s2 = ""

    site1_val = s1 or ""
    site2_val = s2 or ""

    if u:
        if not _find_employee_record(u):
            return redirect("/admin/employee-sites")

        try:
            headers = get_sheet_headers(employees_sheet)

            if headers and "Site" not in headers:
                headers = headers + ["Site"]
                end_col = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
                employees_sheet.update(f"A1:{end_col}1", [headers])

            if headers and "Site2" not in headers:
                headers = headers + ["Site2"]
                end_col = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
                employees_sheet.update(f"A1:{end_col}1", [headers])
        except Exception:
            pass

        try:
            set_employee_field(u, "Site", site1_val)
            set_employee_field(u, "Site2", site2_val)
        except Exception:
            pass

        if DB_MIGRATION_MODE:
            try:
                wp = _session_workplace_id()
                db_row = Employee.query.filter_by(username=u, workplace_id=wp).first()
                if not db_row:
                    db_row = Employee.query.filter_by(email=u, workplace_id=wp).first()
                if db_row:
                    db_row.site = site1_val
                    if hasattr(db_row, "site2"):
                        db_row.site2 = site2_val
                    db_row.workplace = wp
                    db_row.workplace_id = wp
                    db.session.commit()
            except Exception:
                db.session.rollback()

        actor = session.get("username", "admin")
        log_audit(
            "EMPLOYEE_SITE_SET",
            actor=actor,
            username=u,
            date_str="",
            details=f"site1={site1_val} site2={site2_val}",
        )

    return redirect("/admin/employee-sites")