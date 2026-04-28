def admin_payroll_report_csv_impl(core):
    require_admin = core["require_admin"]
    request = core["request"]
    get_company_settings = core["get_company_settings"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    date = core["date"]
    get_workhours_rows = core["get_workhours_rows"]
    _list_employee_records_for_workplace = core["_list_employee_records_for_workplace"]
    COL_PAY = core["COL_PAY"]
    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_HOURS = core["COL_HOURS"]
    user_in_same_workplace = core["user_in_same_workplace"]
    get_employee_display_name = core["get_employee_display_name"]
    safe_float = core["safe_float"]
    _get_week_range = core["_get_week_range"]
    io = core["io"]
    send_file = core["send_file"]


    gate = require_admin()
    if gate:
        return gate

    username_q = (request.args.get("q") or "").strip().lower()
    date_from = (request.args.get("from") or "").strip()
    date_to = (request.args.get("to") or "").strip()

    try:
        wk_offset = int((request.args.get("wk") or "0").strip())
    except Exception:
        wk_offset = 0

    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    wp = _session_workplace_id()

    allowed_wps = set(_workplace_ids_for_read(wp))
    week_start, week_end = _get_week_range(wk_offset)

    use_range = False
    range_start = range_end = None

    if date_from and date_to:
        try:
            range_start = date.fromisoformat(date_from)
            range_end = date.fromisoformat(date_to)
            use_range = True
            week_start, week_end = date_from, date_to
        except ValueError:
            use_range = False

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    employee_records = []
    try:
        employee_records = _list_employee_records_for_workplace(include_inactive=True)
    except Exception:
        employee_records = []
    current_usernames = {
        (rec.get("Username") or "").strip()
        for rec in employee_records
        if (rec.get("Username") or "").strip()
    }
    employee_tax_rate_lookup = {}
    for rec in employee_records:
        username_key = (rec.get("Username") or "").strip()
        if not username_key:
            continue

        raw_tax_value = rec.get("TaxRate")
        if raw_tax_value is None:
            raw_tax_value = rec.get("tax_rate")

        raw_tax = str(raw_tax_value).strip()
        if raw_tax == "":
            continue

        try:
            employee_tax_rate_lookup[username_key] = max(0.0, min(100.0, float(raw_tax))) / 100.0
        except Exception:
            pass

    def tax_rate_for_user(username):
        return employee_tax_rate_lookup.get((username or "").strip(), tax_rate)

    totals_by_user = {}

    for r in rows[1:]:
        if len(r) <= COL_PAY or len(r) <= COL_USER or len(r) <= COL_DATE:
            continue

        user = (r[COL_USER] or "").strip()
        d_str = (r[COL_DATE] or "").strip()

        if not user or not d_str or user not in current_usernames:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(user):
                continue

        if username_q and username_q not in user.lower() and username_q not in get_employee_display_name(user).lower():
            continue

        try:
            d_obj = date.fromisoformat(d_str)
        except Exception:
            continue

        if use_range:
            if d_obj < range_start or d_obj > range_end:
                continue
        else:
            if d_str < str(week_start)[:10] or d_str > str(week_end)[:10]:
                continue

        hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        gross = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        totals_by_user.setdefault(user, {"hours": 0.0, "gross": 0.0})
        totals_by_user[user]["hours"] += hrs
        totals_by_user[user]["gross"] += gross

    export_rows = []
    for user, vals in totals_by_user.items():
        gross = round(vals["gross"], 2)
        tax = round(gross * tax_rate_for_user(user), 2)
        net = round(gross - tax, 2)
        hours = round(vals["hours"], 2)

        export_rows.append({
            "Employee": get_employee_display_name(user),
            "Username": user,
            "Hours": f"{hours:.2f}",
            "Gross": f"{gross:.2f}",
            "Tax": f"{tax:.2f}",
            "Net": f"{net:.2f}",
        })

    export_rows.sort(key=lambda x: (x.get("Employee") or "").lower())

    import csv
    from io import StringIO

    output = StringIO()
    output.write("sep=,\r\n")
    w = csv.writer(output)
    w.writerow(["WeekStart", "WeekEnd", "Employee", "Hours", "Gross", "Tax", "Net"])

    for r in export_rows:
        w.writerow([
            str(week_start),
            str(week_end),
            r["Employee"],
            r["Hours"],
            r["Gross"],
            r["Tax"],
            r["Net"],
        ])

    buf = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    buf.seek(0)

    filename = f"payroll_{week_start}_to_{week_end}.csv"

    return send_file(
        buf,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
        max_age=0
    )
