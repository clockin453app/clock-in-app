def payments_page_impl(core):
    require_login = core["require_login"]
    session = core["session"]
    get_employee_display_name = core["get_employee_display_name"]
    get_company_settings = core["get_company_settings"]
    datetime = core["datetime"]
    date = core["date"]
    TZ = core["TZ"]
    timedelta = core["timedelta"]
    get_payroll_rows = core["get_payroll_rows"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
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
    this_monday = today - timedelta(days=today.weekday())

    vals = get_payroll_rows()
    headers = vals[0] if vals else []

    def idx(name):
        return headers.index(name) if name in headers else None

    i_ws = idx("WeekStart")
    i_we = idx("WeekEnd")
    i_u = idx("Username")
    i_g = idx("Gross")
    i_t = idx("Tax")
    i_n = idx("Net")
    i_dt = idx("DisplayTax")
    i_dn = idx("DisplayNet")
    i_pa = idx("PaidAt")
    i_paid = idx("Paid")
    i_wp = idx("Workplace_ID")

    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    def money_float(value):
        try:
            cleaned = str(value or "0").replace(currency, "").replace("£", "").replace(",", "").strip()
            return round(float(cleaned or "0"), 2)
        except Exception:
            return 0.0

    paid_rows = []

    for row in vals[1:]:
        row_user = (row[i_u] if i_u is not None and i_u < len(row) else "").strip()
        if row_user != username:
            continue

        row_wp = (row[i_wp] if i_wp is not None and i_wp < len(row) else "").strip() or "default"
        if row_wp not in allowed_wps:
            continue

        week_start_raw = (row[i_ws] if i_ws is not None and i_ws < len(row) else "").strip()
        week_end_raw = (row[i_we] if i_we is not None and i_we < len(row) else "").strip()
        paid_at = (row[i_pa] if i_pa is not None and i_pa < len(row) else "").strip()
        paid_flag = (row[i_paid] if i_paid is not None and i_paid < len(row) else "").strip().lower()

        is_paid = bool(paid_at) or paid_flag in {"true", "yes", "1", "paid"}
        if not is_paid:
            continue

        try:
            monday = date.fromisoformat(week_start_raw)
            sunday = date.fromisoformat(week_end_raw)
        except Exception:
            continue

        gross = money_float(row[i_g] if i_g is not None and i_g < len(row) else "0")
        tax = money_float(row[i_t] if i_t is not None and i_t < len(row) else "0")
        net = money_float(row[i_n] if i_n is not None and i_n < len(row) else "0")

        display_tax = money_float(row[i_dt] if i_dt is not None and i_dt < len(row) else tax)
        display_net = money_float(row[i_dn] if i_dn is not None and i_dn < len(row) else net)

        week_offset = max(0, (this_monday - monday).days // 7)
        iso = monday.isocalendar()
        period_label = f"Week {iso[1]} • {monday.strftime('%d %b')} – {sunday.strftime('%d %b %Y')}"

        paid_rows.append({
            "monday": monday,
            "period": period_label,
            "gross_text": f"{currency}{money(gross)}",
            "tax_text": f"{currency}{money(display_tax)}",
            "net_text": f"{currency}{money(display_net)}",
            "payslip_url": f"/my-reports-print?wk={week_offset}&back=payments",
        })

    paid_rows.sort(key=lambda item: item["monday"], reverse=True)

    return render_page(
        template_name="employee/pay_history.html",
        active="payments",
        role=role,
        layout_shell=layout_shell,
        style=STYLE,
        viewport=VIEWPORT,
        pwa_tags=PWA_TAGS,
        display_name=display_name,
        company_name=company_name,
        page_back_html=page_back_button("/", "Back to dashboard"),
        paid_rows=paid_rows,
    )