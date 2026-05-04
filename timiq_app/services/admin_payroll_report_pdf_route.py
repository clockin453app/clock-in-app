def admin_payroll_report_pdf_impl(core):
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
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
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
    company_name = str(settings.get("Company_Name") or "TimIQ").strip() or "TimIQ"
    try:
        default_tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        default_tax_rate = 0.20

    wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(wp))

    period_start_str, period_end_str = _get_week_range(wk_offset)
    period_start = date.fromisoformat(period_start_str)
    period_end = date.fromisoformat(period_end_str)

    if date_from and date_to:
        try:
            period_start = date.fromisoformat(date_from)
            period_end = date.fromisoformat(date_to)
            period_start_str = date_from
            period_end_str = date_to
        except ValueError:
            pass

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None

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

        raw_tax = str(raw_tax_value or "").strip()
        if not raw_tax:
            continue

        try:
            employee_tax_rate_lookup[username_key] = max(0.0, min(100.0, float(raw_tax))) / 100.0
        except Exception:
            pass

    def tax_rate_for_user(username):
        return employee_tax_rate_lookup.get((username or "").strip(), default_tax_rate)

    def money_value(value):
        return f"{currency}{round(float(value or 0.0), 2):,.2f}"

    def hours_value(value):
        val = round(float(value or 0.0), 2)
        return str(int(val)) if abs(val - int(val)) < 0.001 else f"{val:.2f}".rstrip("0").rstrip(".")

    by_user = {}

    for r in rows[1:]:
        if len(r) <= max(COL_PAY, COL_USER, COL_DATE, COL_HOURS):
            continue

        user = (r[COL_USER] or "").strip()
        d_str = (r[COL_DATE] or "").strip()[:10]

        if not user or not d_str or user not in current_usernames:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(user):
                continue

        display_name = get_employee_display_name(user)
        if username_q and username_q not in user.lower() and username_q not in display_name.lower():
            continue

        try:
            d_obj = date.fromisoformat(d_str)
        except Exception:
            continue

        if d_obj < period_start or d_obj > period_end:
            continue

        clock_in = (r[COL_IN] if len(r) > COL_IN else "") or ""
        clock_out = (r[COL_OUT] if len(r) > COL_OUT else "") or ""
        hours = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        gross = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)
        tax = round(gross * tax_rate_for_user(user), 2)
        net = round(gross - tax, 2)

        user_bucket = by_user.setdefault(user, {
            "display": display_name,
            "username": user,
            "hours": 0.0,
            "gross": 0.0,
            "tax": 0.0,
            "net": 0.0,
            "days": [],
        })

        user_bucket["hours"] += hours
        user_bucket["gross"] += gross
        user_bucket["tax"] += tax
        user_bucket["net"] += net
        user_bucket["days"].append({
            "date": d_str,
            "clock_in": str(clock_in).strip(),
            "clock_out": str(clock_out).strip(),
            "hours": hours,
            "gross": gross,
            "tax": tax,
            "net": net,
        })

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, LongTable

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=7 * mm,
        rightMargin=7 * mm,
        topMargin=6 * mm,
        bottomMargin=7 * mm,
        title=f"Payroll Report {period_start_str} to {period_end_str}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PayrollTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=14,
        textColor=colors.HexColor("#07152f"),
        alignment=0,
        spaceAfter=2,
    )
    sub_style = ParagraphStyle(
        "PayrollSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=8,
        textColor=colors.HexColor("#52627a"),
        spaceAfter=4,
    )
    emp_style = ParagraphStyle(
        "EmployeeHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=9,
        textColor=colors.HexColor("#07152f"),
        spaceBefore=3,
        spaceAfter=2,
    )

    story = [
        Paragraph("Payroll Report", title_style),
        Paragraph(f"{company_name} - {period_start_str} to {period_end_str}", sub_style),
    ]

    grand_hours = sum(float(v["hours"] or 0) for v in by_user.values())
    grand_gross = sum(float(v["gross"] or 0) for v in by_user.values())
    grand_tax = sum(float(v["tax"] or 0) for v in by_user.values())
    grand_net = sum(float(v["net"] or 0) for v in by_user.values())

    summary_table = Table([
        ["Employees", "Total Hours", "Gross", "CIS Tax", "Net Pay"],
        [str(len(by_user)), hours_value(grand_hours), money_value(grand_gross), money_value(grand_tax), money_value(grand_net)],
    ], colWidths=[34 * mm, 36 * mm, 38 * mm, 38 * mm, 38 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f7ff")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#52627a")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dbe6f3")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [summary_table, Spacer(1, 4)]

    if not by_user:
        story.append(Paragraph("No payroll rows found for this period.", sub_style))
    else:
        for user, bucket in sorted(by_user.items(), key=lambda item: (item[1]["display"] or "").lower()):
            story.append(Paragraph(f"{bucket['display']} ({bucket['username']})", emp_style))

            table_rows = [["Date", "Clock In", "Clock Out", "Hours", "Gross", "CIS Tax", "Net Pay"]]
            for day in sorted(bucket["days"], key=lambda x: x["date"]):
                table_rows.append([
                    day["date"],
                    day["clock_in"],
                    day["clock_out"],
                    hours_value(day["hours"]),
                    money_value(day["gross"]),
                    money_value(day["tax"]),
                    money_value(day["net"]),
                ])

            table_rows.append([
                "TOTAL", "", "",
                hours_value(bucket["hours"]),
                money_value(bucket["gross"]),
                money_value(bucket["tax"]),
                money_value(bucket["net"]),
            ])

            table = LongTable(
                table_rows,
                colWidths=[22 * mm, 24 * mm, 24 * mm, 18 * mm, 28 * mm, 28 * mm, 28 * mm],
                repeatRows=1,
                splitByRow=1,
            )
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f7ff")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#52627a")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fbfdff")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dbe6f3")),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("FONTSIZE", (0, 0), (-1, -1), 6),
                ("LEADING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]))
            story += [table, Spacer(1, 3)]

    def add_page_number(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#667085"))
        canvas.drawRightString(290 * mm, 4 * mm, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buf.seek(0)

    filename = f"payroll_{period_start_str}_to_{period_end_str}.pdf"

    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )
