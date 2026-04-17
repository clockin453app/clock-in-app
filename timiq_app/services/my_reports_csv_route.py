def my_reports_csv_impl(core):
    require_login = core["require_login"]
    session = core["session"]
    get_employee_display_name = core["get_employee_display_name"]
    get_company_settings = core["get_company_settings"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    request = core["request"]
    timedelta = core["timedelta"]
    get_workhours_rows = core["get_workhours_rows"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    COL_PAY = core["COL_PAY"]
    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    safe_float = core["safe_float"]
    io = core["io"]
    secure_filename = core["secure_filename"]
    send_file = core["send_file"]

    # PASTE ONLY THE BODY OF my_reports_csv() BELOW THIS LINE

    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    display_name = get_employee_display_name(username)

    settings = get_company_settings()
    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    now = datetime.now(TZ)
    today = now.date()

    try:
        wk_offset = max(0, int((request.args.get("wk", "0") or "0").strip()))
    except Exception:
        wk_offset = 0

    this_monday = today - timedelta(days=today.weekday())
    selected_week_start = this_monday - timedelta(days=7 * wk_offset)
    selected_week_end = selected_week_start + timedelta(days=6)

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    week_map = {}

    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        week_map[d_str] = {
            "day": day_labels[i],
            "date": d_str,
            "clock_in": "",
            "clock_out": "",
            "hours": 0.0,
            "gross": 0.0,
        }

    total_hours = 0.0
    total_gross = 0.0

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue

        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

        d_str = (r[COL_DATE] if len(r) > COL_DATE else "").strip()
        if not d_str or d_str not in week_map:
            continue

        try:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        if not (selected_week_start <= d <= selected_week_end):
            continue

        cin = ((r[COL_IN] if len(r) > COL_IN else "") or "").strip()
        cout = ((r[COL_OUT] if len(r) > COL_OUT else "") or "").strip()
        hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        gross = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        item = week_map[d_str]
        item["hours"] += hrs
        item["gross"] += gross

        cin_short = cin[:5] if cin else ""
        cout_short = cout[:5] if cout else ""

        if cin_short:
            if not item["clock_in"] or cin_short < item["clock_in"]:
                item["clock_in"] = cin_short

        if cout_short:
            if not item["clock_out"] or cout_short > item["clock_out"]:
                item["clock_out"] = cout_short

        total_hours += hrs
        total_gross += gross

    import csv
    from io import StringIO

    output = StringIO()
    output.write("sep=,\r\n")
    writer = csv.writer(output)
    writer.writerow([
        "Employee", "WeekStart", "WeekEnd", "Day", "Date",
        "ClockIn", "ClockOut", "Hours", "Gross", "Tax", "Net"
    ])

    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        item = week_map[d_str]

        gross_val = round(item["gross"], 2)
        tax_val = round(gross_val * tax_rate, 2)
        net_val = round(gross_val - tax_val, 2)
        hours_val = round(item["hours"], 2)

        writer.writerow([
            display_name,
            selected_week_start.isoformat(),
            selected_week_end.isoformat(),
            item["day"],
            item["date"],
            item["clock_in"],
            item["clock_out"],
            f"{hours_val:.2f}",
            f"{gross_val:.2f}",
            f"{tax_val:.2f}",
            f"{net_val:.2f}",
        ])

    total_tax = round(total_gross * tax_rate, 2)
    total_net = round(total_gross - total_tax, 2)

    writer.writerow([])
    writer.writerow([
        "TOTAL", "", "", "", "", "", "",
        f"{round(total_hours, 2):.2f}",
        f"{round(total_gross, 2):.2f}",
        f"{total_tax:.2f}",
        f"{total_net:.2f}",
    ])

    buf = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    buf.seek(0)

    filename = f"timesheet_{secure_filename(username)}_{selected_week_start.isoformat()}_to_{selected_week_end.isoformat()}.csv"

    return send_file(
        buf,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
        max_age=0
    )
