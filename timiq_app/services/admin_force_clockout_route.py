def admin_force_clockout_impl(core):
    require_admin = core["require_admin"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    redirect = core["redirect"]
    get_workhours_rows = core["get_workhours_rows"]
    find_open_shift = core["find_open_shift"]
    _get_user_rate = core["_get_user_rate"]
    _compute_hours_from_times = core["_compute_hours_from_times"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    datetime = core["datetime"]
    timedelta = core["timedelta"]
    _workhour_query_for_user = core["_workhour_query_for_user"]
    _session_workplace_id = core["_session_workplace_id"]
    WorkHour = core["WorkHour"]
    db = core["db"]
    make_response = core["make_response"]
    work_sheet = core["work_sheet"]
    gspread = core["gspread"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    COL_PAY = core["COL_PAY"]
    _gs_write_with_retry = core["_gs_write_with_retry"]
    session = core["session"]
    log_audit = core["log_audit"]


    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or "").strip()
    out_time = (request.form.get("out_time") or "").strip()

    if not username or not out_time:
        return redirect(request.referrer or "/admin")

    rows = get_workhours_rows()
    osf = find_open_shift(rows, username)
    if not osf:
        return redirect(request.referrer or "/admin")

    idx, d, cin = osf
    rate = _get_user_rate(username)

    if len(out_time.split(":")) == 2:
        out_time = out_time + ":00"

    computed_hours = _compute_hours_from_times(d, cin, out_time)
    if computed_hours is None:
        return redirect(request.referrer or "/admin")

    pay = round(computed_hours * rate, 2)

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(d, "%Y-%m-%d").date()
            clock_out_dt = datetime.strptime(f"{d} {out_time}", "%Y-%m-%d %H:%M:%S")
            clock_in_dt_check = datetime.strptime(f"{d} {cin}", "%Y-%m-%d %H:%M:%S")
            if clock_out_dt < clock_in_dt_check:
                clock_out_dt = clock_out_dt + timedelta(days=1)

            db_row = _workhour_query_for_user(username, _session_workplace_id()).filter(
                WorkHour.date == shift_date
            ).order_by(WorkHour.id.desc()).first()

            if db_row:
                if not getattr(db_row, "clock_in", None):
                    db_row.clock_in = clock_in_dt_check
                db_row.clock_out = clock_out_dt
                db_row.hours = computed_hours
                db_row.pay = pay
                db_row.workplace = _session_workplace_id()
                db_row.workplace_id = _session_workplace_id()
            else:
                db.session.add(
                    WorkHour(
                        employee_email=username,
                        date=shift_date,
                        clock_in=clock_in_dt_check,
                        clock_out=clock_out_dt,
                        hours=computed_hours,
                        pay=pay,
                        workplace=_session_workplace_id(),
                        workplace_id=_session_workplace_id(),
                    )
                )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not force clock out: {e}", 500)
    else:
        sheet_row = idx + 1
        try:
            vals = work_sheet.get_all_values()
            headers = vals[0] if vals else []
            updates = [
                {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_OUT + 1), "values": [[out_time]]},
                {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_HOURS + 1), "values": [[str(computed_hours)]]},
                {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_PAY + 1), "values": [[str(pay)]]},
            ]
            if headers and "Workplace_ID" in headers:
                wp_col = headers.index("Workplace_ID") + 1
                updates.append(
                    {"range": gspread.utils.rowcol_to_a1(sheet_row, wp_col), "values": [[_session_workplace_id()]]})
            _gs_write_with_retry(lambda: work_sheet.batch_update(updates))
        except Exception as e:
            return make_response(f"Could not force clock out: {e}", 500)

    actor = session.get("username", "admin")
    log_audit("FORCE_CLOCK_OUT", actor=actor, username=username, date_str=d,
              details=f"out={out_time} hours={computed_hours} pay={pay}")
    return redirect(request.referrer or "/admin")
