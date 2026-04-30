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
    _get_payroll_rule_for_shift = core["_get_payroll_rule_for_shift"]
    _calculate_shift_pay_from_rule = core["_calculate_shift_pay_from_rule"]
    _save_workhour_rule_snapshot = core["_save_workhour_rule_snapshot"]
    or_ = core["or_"]

    gate = require_admin()
    if gate:
        return gate

    require_csrf()

    username = (request.form.get("user") or "").strip()
    out_time = (request.form.get("out_time") or "").strip()

    if not username or not out_time:
        return redirect(request.referrer or "/admin")

    if len(out_time.split(":")) == 2:
        out_time = out_time + ":00"

    rate = _get_user_rate(username)

    if DB_MIGRATION_MODE:
        try:
            db_row = (
                WorkHour.query
                .filter(
                    WorkHour.employee_email == username,
                    WorkHour.clock_in.isnot(None),
                    WorkHour.clock_out.is_(None),
                    or_(
                        WorkHour.workplace_id == _session_workplace_id(),
                        WorkHour.workplace == _session_workplace_id(),
                    ),
                )
                .order_by(WorkHour.date.desc(), WorkHour.id.desc())
                .first()
            )

            if not db_row:
                return redirect(request.referrer or "/admin")

            shift_date = getattr(db_row, "date", None)
            clock_in_dt = getattr(db_row, "clock_in", None)

            if not shift_date or not clock_in_dt:
                return make_response("Open shift is missing clock-in data.", 500)

            d = shift_date.isoformat()
            cin = clock_in_dt.strftime("%H:%M:%S")

            rule_snapshot = _get_payroll_rule_for_shift(
                shift_date,
                _session_workplace_id(),
            )

            computed_hours = _compute_hours_from_times(
                d,
                cin,
                out_time,
                _session_workplace_id(),
                rule_snapshot,
            )

            if computed_hours is None:
                return redirect(request.referrer or "/admin")

            pay = _calculate_shift_pay_from_rule(
                computed_hours,
                rate,
                rule_snapshot,
            )

            clock_out_dt = datetime.strptime(f"{d} {out_time}", "%Y-%m-%d %H:%M:%S")

            if clock_out_dt < clock_in_dt:
                clock_out_dt = clock_out_dt + timedelta(days=1)

            db_row.clock_out = clock_out_dt
            db_row.hours = computed_hours
            db_row.pay = pay
            db_row.workplace = _session_workplace_id()
            db_row.workplace_id = _session_workplace_id()

            _save_workhour_rule_snapshot(db_row, rule_snapshot)
            db.session.commit()

            actor = session.get("username", "admin")
            log_audit(
                "FORCE_CLOCK_OUT",
                actor=actor,
                username=username,
                date_str=d,
                details=f"out={out_time} hours={computed_hours} pay={pay}",
            )

            return redirect(request.referrer or "/admin")

        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not force clock out: {e}", 500)

    rows = get_workhours_rows()
    osf = find_open_shift(rows, username)

    if not osf:
        return redirect(request.referrer or "/admin")

    idx, d, cin = osf

    shift_date_obj = datetime.strptime(d, "%Y-%m-%d").date()
    rule_snapshot = _get_payroll_rule_for_shift(
        shift_date_obj,
        _session_workplace_id(),
    )

    computed_hours = _compute_hours_from_times(
        d,
        cin,
        out_time,
        _session_workplace_id(),
        rule_snapshot,
    )

    if computed_hours is None:
        return redirect(request.referrer or "/admin")

    pay = _calculate_shift_pay_from_rule(
        computed_hours,
        rate,
        rule_snapshot,
    )

    sheet_row = idx + 1

    try:
        vals = work_sheet.get_all_values()
        headers = vals[0] if vals else []

        updates = [
            {
                "range": gspread.utils.rowcol_to_a1(sheet_row, COL_OUT + 1),
                "values": [[out_time]],
            },
            {
                "range": gspread.utils.rowcol_to_a1(sheet_row, COL_HOURS + 1),
                "values": [[str(computed_hours)]],
            },
            {
                "range": gspread.utils.rowcol_to_a1(sheet_row, COL_PAY + 1),
                "values": [[str(pay)]],
            },
        ]

        if headers and "Workplace_ID" in headers:
            wp_col = headers.index("Workplace_ID") + 1
            updates.append({
                "range": gspread.utils.rowcol_to_a1(sheet_row, wp_col),
                "values": [[_session_workplace_id()]],
            })

        _gs_write_with_retry(lambda: work_sheet.batch_update(updates))

    except Exception as e:
        return make_response(f"Could not force clock out: {e}", 500)

    actor = session.get("username", "admin")
    log_audit(
        "FORCE_CLOCK_OUT",
        actor=actor,
        username=username,
        date_str=d,
        details=f"out={out_time} hours={computed_hours} pay={pay}",
    )

    return redirect(request.referrer or "/admin")