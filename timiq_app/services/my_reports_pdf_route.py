def my_reports_pdf_impl(core):
    require_login = core["require_login"]
    session = core["session"]
    get_employee_display_name = core["get_employee_display_name"]
    get_company_settings = core["get_company_settings"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    request = core["request"]
    timedelta = core["timedelta"]
    get_workhours_rows = core["get_workhours_rows"]
    get_payroll_rows = core["get_payroll_rows"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    COL_PAY = core["COL_PAY"]
    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    safe_float = core["safe_float"]
    _round_to_half_hour = core["_round_to_half_hour"]
    money = core["money"]
    fmt_hours = core["fmt_hours"]
    io = core["io"]
    send_file = core["send_file"]
    secure_filename = core["secure_filename"]

    gate = require_login()
    if gate:
        return gate

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception:
        return {"error": "PDF library missing. Install reportlab."}, 500

    username = session["username"]
    display_name = get_employee_display_name(username)

    settings = get_company_settings()
    company_name = (settings.get("Company_Name", "") or "").strip() or "Company"
    currency = (settings.get("Currency", "£") or "£").strip() or "£"

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

    total_tax = round(total_gross * tax_rate, 2)
    total_net = round(total_gross - total_tax, 2)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_width, page_height = A4

    left = 40
    y = page_height - 40

    def line(text, size=10, bold=False, step=16):
        nonlocal y
        if y < 60:
            pdf.showPage()
            y = page_height - 40
        font_name = "Helvetica-Bold" if bold else "Helvetica"
        pdf.setFont(font_name, size)
        pdf.drawString(left, y, str(text))
        y -= step

    pdf.setTitle(f"Payslip {display_name} {selected_week_start.isoformat()}")

    line(company_name, size=16, bold=True, step=22)
    line("Payslip / Timesheet", size=12, bold=True, step=18)
    line(f"Employee: {display_name}", size=11, step=16)
    line(f"Week: {selected_week_start.isoformat()} to {selected_week_end.isoformat()}", size=11, step=20)

    line("Day | Date | In | Out | Hours | Gross | Net", size=10, bold=True, step=16)
    line("-" * 90, size=9, step=12)

    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        item = week_map[d_str]

        gross_val = round(item["gross"], 2)
        tax_val = round(gross_val * tax_rate, 2)
        net_val = round(gross_val - tax_val, 2)
        hours_val = round(item["hours"], 2)

        row_text = (
            f"{item['day']} | {item['date']} | "
            f"{item['clock_in'] or '-'} | {item['clock_out'] or '-'} | "
            f"{hours_val:.2f} | {currency}{gross_val:.2f} | {currency}{net_val:.2f}"
        )
        line(row_text, size=9, step=14)

    y -= 8
    line("Totals", size=11, bold=True, step=16)
    line(f"Total Hours: {round(total_hours, 2):.2f}", size=10, step=14)
    line(f"Gross Pay: {currency}{round(total_gross, 2):.2f}", size=10, step=14)
    line(f"Tax: {currency}{total_tax:.2f}", size=10, step=14)
    line(f"Net Pay: {currency}{total_net:.2f}", size=10, bold=True, step=16)

    pdf.save()
    buffer.seek(0)

    filename = (
        f"payslip_{secure_filename(username)}_"
        f"{selected_week_start.isoformat()}_to_{selected_week_end.isoformat()}.pdf"
    )

    response = send_file(
        buffer,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=filename,
        max_age=0,
        conditional=False,
    )

    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response