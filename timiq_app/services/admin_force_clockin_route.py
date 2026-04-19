def admin_force_clockin_impl(core):
    require_admin = core["require_admin"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    redirect = core["redirect"]
    get_workhours_rows = core["get_workhours_rows"]
    find_open_shift = core["find_open_shift"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    datetime = core["datetime"]
    _workhour_query_for_user = core["_workhour_query_for_user"]
    _session_workplace_id = core["_session_workplace_id"]
    WorkHour = core["WorkHour"]
    db = core["db"]
    make_response = core["make_response"]
    work_sheet = core["work_sheet"]
    gspread = core["gspread"]
    _find_workhours_row_by_user_date = core["_find_workhours_row_by_user_date"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    COL_PAY = core["COL_PAY"]
    session = core["session"]
    log_audit = core["log_audit"]

    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or "").strip()
    in_time = (request.form.get("in_time") or "").strip()
    date_str = (request.form.get("date") or "").strip()

    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or "").strip()
    in_time = (request.form.get("in_time") or "").strip()
    date_str = (request.form.get("date") or "").strip()

    if not username or not in_time or not date_str:
        return redirect(request.referrer or "/admin")

    if len(in_time.split(":")) == 2:
        in_time = in_time + ":00"

    rows = get_workhours_rows()
    if find_open_shift(rows, username):
        return redirect(request.referrer or "/admin")

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            clock_in_dt = datetime.strptime(f"{date_str} {in_time}", "%Y-%m-%d %H:%M:%S")
            db_row = _workhour_query_for_user(username, _session_workplace_id()).filter(
                WorkHour.date == shift_date
            ).order_by(WorkHour.id.desc()).first()

            if db_row:
                db_row.clock_in = clock_in_dt
                db_row.clock_out = None
                db_row.hours = None
                db_row.pay = None
                db_row.workplace = _session_workplace_id()
                db_row.workplace_id = _session_workplace_id()
            else:
                db.session.add(
                    WorkHour(
                        employee_email=username,
                        date=shift_date,
                        clock_in=clock_in_dt,
                        clock_out=None,
                        hours=None,
                        pay=None,
                        workplace=_session_workplace_id(),
                        workplace_id=_session_workplace_id(),
                    )
                )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not force clock in: {e}", 500)
    else:
        try:
            vals = work_sheet.get_all_values()
            headers = vals[0] if vals else []
            rownum = _find_workhours_row_by_user_date(vals, username, date_str)
            wp_col = (headers.index("Workplace_ID") + 1) if ("Workplace_ID" in headers) else None

            if rownum:
                work_sheet.update_cell(rownum, COL_IN + 1, in_time)
                work_sheet.update_cell(rownum, COL_OUT + 1, "")
                work_sheet.update_cell(rownum, COL_HOURS + 1, "")
                work_sheet.update_cell(rownum, COL_PAY + 1, "")
                if wp_col:
                    work_sheet.update_cell(rownum, wp_col, _session_workplace_id())
            else:
                new_row = [username, date_str, in_time, "", "", ""]
                if headers and "Workplace_ID" in headers:
                    wp_idx = headers.index("Workplace_ID")
                    if len(new_row) <= wp_idx:
                        new_row += [""] * (wp_idx + 1 - len(new_row))
                    new_row[wp_idx] = _session_workplace_id()
                if headers and len(new_row) < len(headers):
                    new_row += [""] * (len(headers) - len(new_row))
                work_sheet.append_row(new_row)
        except Exception as e:
            return make_response(f"Could not force clock in: {e}", 500)

    actor = session.get("username", "admin")
    log_audit("FORCE_CLOCK_IN", actor=actor, username=username, date_str=date_str, details=f"in={in_time}")
    return redirect(request.referrer or "/admin")
