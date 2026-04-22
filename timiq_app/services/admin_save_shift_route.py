def admin_save_shift_impl(core):
    require_admin = core["require_admin"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    redirect = core["redirect"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    datetime = core["datetime"]
    WorkHour = core["WorkHour"]
    db = core["db"]
    make_response = core["make_response"]
    work_sheet = core["work_sheet"]
    _find_workhours_row_by_user_date = core["_find_workhours_row_by_user_date"]
    _get_user_rate = core["_get_user_rate"]
    safe_float = core["safe_float"]
    _compute_hours_from_times = core["_compute_hours_from_times"]
    _workhour_query_for_user = core["_workhour_query_for_user"]
    _session_workplace_id = core["_session_workplace_id"]
    timedelta = core["timedelta"]
    gspread = core["gspread"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    COL_PAY = core["COL_PAY"]
    _gs_write_with_retry = core["_gs_write_with_retry"]
    _calculate_shift_pay = core["_calculate_shift_pay"]
    _get_canonical_workhour_for_day = core["_get_canonical_workhour_for_day"]
    _get_payroll_rule_for_shift = core["_get_payroll_rule_for_shift"]
    _calculate_shift_pay_from_rule = core["_calculate_shift_pay_from_rule"]
    _save_workhour_rule_snapshot = core["_save_workhour_rule_snapshot"]


    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or request.form.get("username") or "").strip()
    date_str = (request.form.get("date") or "").strip()
    cin = (request.form.get("cin") or request.form.get("clock_in") or "").strip()
    cout = (request.form.get("cout") or request.form.get("clock_out") or "").strip()
    hours_in = (request.form.get("hours") or "").strip()
    pay_in = (request.form.get("pay") or "").strip()
    recalc = (request.form.get("recalc") == "yes")

    if not username or not date_str:
        return redirect(request.referrer or "/admin/payroll")

    # If the admin clears all fields for a day, treat that as "delete this shift".
    delete_shift = (cin == "" and cout == "" and hours_in == "" and pay_in == "")

    if delete_shift:
        if DB_MIGRATION_MODE:
            try:
                shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                deleted = WorkHour.query.filter(
                    WorkHour.employee_email == username,
                    WorkHour.date == shift_date,
                    WorkHour.workplace_id == _session_workplace_id(),
                ).delete(synchronize_session=False)

                db.session.commit()
            except Exception as e:
                db.session.rollback()
                return make_response(f"Could not delete shift: {e}", 500)

            return redirect(request.referrer or "/admin/payroll")

        try:
            vals = work_sheet.get_all_values()
            rownum = _find_workhours_row_by_user_date(vals, username, date_str)
            if rownum:
                work_sheet.delete_rows(rownum)
        except Exception as e:
            return make_response(f"Could not delete shift: {e}", 500)

        return redirect(request.referrer or "/admin/payroll")

    rate = _get_user_rate(username)
    hours_val = None if hours_in == "" else safe_float(hours_in, 0.0)
    pay_val = None if pay_in == "" else safe_float(pay_in, 0.0)
    rule_snapshot = None

    if cin and cout:
        shift_date_for_rule = datetime.strptime(date_str, "%Y-%m-%d").date()
        rule_snapshot = _get_payroll_rule_for_shift(
            shift_date_for_rule,
            _session_workplace_id(),
        )
        computed = _compute_hours_from_times(
            date_str,
            cin,
            cout,
            _session_workplace_id(),
            rule_snapshot,
        )
        if computed is not None:
            hours_val = computed
            pay_val = _calculate_shift_pay_from_rule(computed, rate, rule_snapshot)
    elif hours_in != "":
        shift_date_for_rule = datetime.strptime(date_str, "%Y-%m-%d").date()
        rule_snapshot = _get_payroll_rule_for_shift(
            shift_date_for_rule,
            _session_workplace_id(),
        )
        pay_val = _calculate_shift_pay_from_rule(
            safe_float(hours_in, 0.0),
            rate,
            rule_snapshot,
        )

    hours_cell = "" if hours_val is None else str(hours_val)
    pay_cell = "" if pay_val is None else str(pay_val)

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            db_row = _get_canonical_workhour_for_day(
                username,
                shift_date,
                _session_workplace_id(),
            )

            clock_in_dt = None
            clock_out_dt = None
            cin_db = cin
            cout_db = cout

            if cin_db:
                if len(cin_db.split(":")) == 2:
                    cin_db = cin_db + ":00"
                clock_in_dt = datetime.strptime(f"{date_str} {cin_db}", "%Y-%m-%d %H:%M:%S")

            if cout_db:
                if len(cout_db.split(":")) == 2:
                    cout_db = cout_db + ":00"
                clock_out_dt = datetime.strptime(f"{date_str} {cout_db}", "%Y-%m-%d %H:%M:%S")
                if clock_in_dt and clock_out_dt < clock_in_dt:
                    clock_out_dt = clock_out_dt + timedelta(days=1)

            db_row.clock_in = clock_in_dt
            db_row.clock_out = clock_out_dt
            db_row.hours = float(hours_cell) if hours_cell != "" else None
            db_row.pay = float(pay_cell) if pay_cell != "" else None
            db_row.workplace = _session_workplace_id()
            db_row.workplace_id = _session_workplace_id()

            if rule_snapshot is None:
                rule_snapshot = _get_payroll_rule_for_shift(
                    shift_date,
                    _session_workplace_id(),
                )
            _save_workhour_rule_snapshot(db_row, rule_snapshot)

            db.session.commit()


        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not save shift: {e}", 500)
        return redirect(request.referrer or "/admin/payroll")

    try:
        vals = work_sheet.get_all_values()
        headers = vals[0] if vals else []
        rownum = _find_workhours_row_by_user_date(vals, username, date_str)

        if not rownum:
            new_row = [username, date_str, cin, cout, hours_cell, pay_cell]
            if headers and "Workplace_ID" in headers:
                wp_idx = headers.index("Workplace_ID")
                if len(new_row) <= wp_idx:
                    new_row += [""] * (wp_idx + 1 - len(new_row))
                new_row[wp_idx] = _session_workplace_id()
            if headers and len(new_row) < len(headers):
                new_row += [""] * (len(headers) - len(new_row))
            work_sheet.append_row(new_row)
        else:
            updates = [
                {"range": gspread.utils.rowcol_to_a1(rownum, COL_IN + 1), "values": [[cin]]},
                {"range": gspread.utils.rowcol_to_a1(rownum, COL_OUT + 1), "values": [[cout]]},
                {"range": gspread.utils.rowcol_to_a1(rownum, COL_HOURS + 1), "values": [[hours_cell]]},
                {"range": gspread.utils.rowcol_to_a1(rownum, COL_PAY + 1), "values": [[pay_cell]]},
            ]
            if headers and "Workplace_ID" in headers:
                wp_col = headers.index("Workplace_ID") + 1
                updates.append(
                    {"range": gspread.utils.rowcol_to_a1(rownum, wp_col), "values": [[_session_workplace_id()]]})
            _gs_write_with_retry(lambda: work_sheet.batch_update(updates))
    except Exception as e:
        return make_response(f"Could not save shift: {e}", 500)

    return redirect(request.referrer or "/admin/payroll")
