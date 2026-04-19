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
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
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

    site_val = f"{s1},{s2}" if (s1 and s2) else (s1 or s2 or "")

    if u:
        if not _find_employee_record(u):
            return redirect("/admin/employee-sites")

        try:
            headers = get_sheet_headers(employees_sheet)
            if headers and "Site" not in headers:
                headers2 = headers + ["Site"]
                end_col = gspread.utils.rowcol_to_a1(1, len(headers2)).replace("1", "")
                employees_sheet.update(f"A1:{end_col}1", [headers2])
        except Exception:
            pass

        try:
            set_employee_field(u, "Site", site_val)
        except Exception:
            pass

        if DB_MIGRATION_MODE:
            try:
                wp = _session_workplace_id()
                allowed_wps = set(_workplace_ids_for_read(wp))
                db_row = Employee.query.filter_by(username=u, workplace_id=wp).first()
                if not db_row:
                    db_row = Employee.query.filter_by(email=u, workplace_id=wp).first()
                if db_row:
                    db_row.site = site_val
                    db_row.workplace = wp
                    db_row.workplace_id = wp
                    db.session.commit()
            except Exception:
                db.session.rollback()

        actor = session.get("username", "admin")
        log_audit("EMPLOYEE_SITE_SET", actor=actor, username=u, date_str="", details=f"site={site_val}")

    return redirect("/admin/employee-sites")
