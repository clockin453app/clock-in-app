def my_week_report_impl(core):
    require_login = core["require_login"]
    session = core["session"]
    get_employee_display_name = core["get_employee_display_name"]
    get_company_settings = core["get_company_settings"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    request = core["request"]
    timedelta = core["timedelta"]
    get_workhours_rows = core["get_workhours_rows"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    safe_float = core["safe_float"]
    _get_user_rate = core["_get_user_rate"]
    OVERTIME_HOURS = core["OVERTIME_HOURS"]
    fmt_hours = core["fmt_hours"]
    escape = core["escape"]
    money = core["money"]
    page_back_button = core["page_back_button"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    render_page = core["render_page"]

    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)


    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    company_name = str(settings.get("Company_Name") or "Main").strip() or "Main"

    now = datetime.now(TZ)
    today = now.date()

    wk_offset_raw = (request.args.get("wk", "0") or "0").strip()
    try:
        wk_offset = max(0, int(wk_offset_raw))
    except Exception:
        wk_offset = 0

    this_monday = today - timedelta(days=today.weekday())
    selected_week_start = this_monday - timedelta(days=7 * wk_offset)
    selected_week_end = selected_week_start + timedelta(days=6)

    vals = get_workhours_rows()
    rows = vals if vals else []
    headers = rows[0] if rows else []

    def idx(name):
        return headers.index(name) if name in headers else None

    COL_USER = idx("Username")
    COL_DATE = idx("Date")
    COL_HOURS = idx("Hours")
    COL_PAY = idx("Pay")
    COL_WP = idx("Workplace_ID")

    allowed_wps = set(_workplace_ids_for_read())

    week_hours = 0.0
    week_gross = 0.0
    worked_days = 0
    overtime_hours = 0.0

    for r in rows[1:]:
        if COL_USER is None or COL_DATE is None:
            continue

        row_user = (r[COL_USER] if COL_USER < len(r) else "").strip()
        if row_user != username:
            continue

        if COL_WP is not None:
            row_wp = (r[COL_WP] if COL_WP < len(r) else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

        d_str = (r[COL_DATE] if COL_DATE < len(r) else "").strip()
        if not d_str:
            continue

        try:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        if d < selected_week_start or d > selected_week_end:
            continue

        hrs = safe_float((r[COL_HOURS] if COL_HOURS is not None and COL_HOURS < len(r) else "") or "0", 0.0)
        pay = safe_float((r[COL_PAY] if COL_PAY is not None and COL_PAY < len(r) else "") or "0", 0.0)

        week_hours += hrs
        week_gross += pay

        if hrs > 0:
            worked_days += 1
            if hrs > 8.5:
                overtime_hours += (hrs - 8.5)

    week_hours = round(week_hours, 2)
    week_gross = round(week_gross, 2)
    overtime_hours = round(overtime_hours, 2)

    rate = round(_get_user_rate(username), 2)

    iso = selected_week_start.isocalendar()
    period_label = f"Week {iso[1]} {selected_week_start.strftime('%Y')}/{str(selected_week_end.year)[-2:]}"
    full_period = f"{selected_week_start.strftime('%d %b %Y')} – {selected_week_end.strftime('%d %b %Y')}"
    payment_date = selected_week_end.strftime("%d/%m/%y")

    return render_page(
        template_name="employee/week_report.html",
        active="reports",
        role=role,
        layout_shell=layout_shell,
        style=STYLE,
        viewport=VIEWPORT,
        pwa_tags=PWA_TAGS,
        page_back_html=page_back_button("/my-reports", "Back to timesheets"),
        display_name=display_name,
        company_name=company_name,
        period_label=period_label,
        full_period=full_period,
        payment_date=payment_date,
        week_hours=week_hours,
        week_gross=week_gross,
        overtime_hours=overtime_hours,
        rate=rate,
        currency=currency,
        money=money,
        fmt_hours=fmt_hours,
    )