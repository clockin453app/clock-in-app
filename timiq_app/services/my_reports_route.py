def my_reports_impl(core):
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
    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    COL_PAY = core["COL_PAY"]
    safe_float = core["safe_float"]
    escape = core["escape"]
    fmt_hours = core["fmt_hours"]
    money = core["money"]
    USE_DATABASE = core["USE_DATABASE"]
    OnboardingRecord = core["OnboardingRecord"]
    onboarding_sheet = core["onboarding_sheet"]
    OVERTIME_HOURS = core["OVERTIME_HOURS"]
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

    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    company_name = str(settings.get("Company_Name") or "Main").strip() or "Main"
    company_logo = str(settings.get("Company_Logo_URL") or "").strip()

    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    now = datetime.now(TZ)
    today = now.date()

    # week selector: 0=this week, 1=last week, etc.
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

    daily_hours = 0.0
    daily_pay = 0.0
    month_hours = 0.0
    month_pay = 0.0
    selected_week_hours = 0.0
    selected_week_pay = 0.0

    # build selected week map
    week_map = {}
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        d_display = d.strftime("%y-%m-%d")
        week_map[d_str] = {
            "day": day_labels[i],
            "date": d_str,
            "display_date": d_display,
            "first_in": "",
            "last_out": "",
            "hours": 0.0,
            "gross": 0.0,
        }

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
        if not d_str:
            continue

        try:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        cin = ((r[COL_IN] if len(r) > COL_IN else "") or "").strip()
        cout = ((r[COL_OUT] if len(r) > COL_OUT else "") or "").strip()
        hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        pay = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        if d == today:
            daily_hours += hrs
            daily_pay += pay

        if d.year == today.year and d.month == today.month:
            month_hours += hrs
            month_pay += pay

        if selected_week_start <= d <= selected_week_end:
            selected_week_hours += hrs
            selected_week_pay += pay

            item = week_map.get(d_str)
            if item is not None:
                item["hours"] += hrs
                item["gross"] += pay

                cin_short = cin[:5] if cin else ""
                cout_short = cout[:5] if cout else ""

                if cin_short:
                    if not item["first_in"] or cin_short < item["first_in"]:
                        item["first_in"] = cin_short

                if cout_short:
                    if not item["last_out"] or cout_short > item["last_out"]:
                        item["last_out"] = cout_short

    def gross_tax_net(gross):
        gross = round(gross, 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)
        return gross, tax, net

    d_g, d_t, d_n = gross_tax_net(daily_pay)
    w_g, w_t, w_n = gross_tax_net(selected_week_pay)
    m_g, m_t, m_n = gross_tax_net(month_pay)

    # weekly summary list (all weeks with data)
    week_summaries = {}

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
        if not d_str:
            continue

        try:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        gross = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        if hrs <= 0 and gross <= 0:
            continue

        monday = d - timedelta(days=d.weekday())
        sunday = monday + timedelta(days=6)
        key = monday.strftime("%Y-%m-%d")

        rec = week_summaries.setdefault(key, {
            "monday": monday,
            "sunday": sunday,
            "hours": 0.0,
            "gross": 0.0,
            "payment_date": d,
        })

        rec["hours"] += hrs
        rec["gross"] += gross

        if d > rec["payment_date"]:
            rec["payment_date"] = d
    payroll_vals = get_payroll_rows()
    payroll_headers = payroll_vals[0] if payroll_vals else []

    def pidx(name):
        return payroll_headers.index(name) if name in payroll_headers else None

    p_ws = pidx("WeekStart")
    p_u = pidx("Username")
    p_pa = pidx("PaidAt")
    p_paid = pidx("Paid")
    p_wp = pidx("Workplace_ID")

    paid_week_keys = set()

    for r in payroll_vals[1:]:
        row_user = (r[p_u] if p_u is not None and p_u < len(r) else "").strip()
        if row_user != username:
            continue

        row_wp = ((r[p_wp] if p_wp is not None and p_wp < len(r) else "").strip() or "default")
        if row_wp not in allowed_wps:
            continue

        week_start = (r[p_ws] if p_ws is not None and p_ws < len(r) else "").strip()
        paid_at = (r[p_pa] if p_pa is not None and p_pa < len(r) else "").strip()
        paid_flag = (r[p_paid] if p_paid is not None and p_paid < len(r) else "").strip().lower()

        is_paid = bool(paid_at) or paid_flag in {"true", "yes", "1", "paid"}
        if is_paid and week_start:
            paid_week_keys.add(week_start)

    weekly_list = []
    for key in sorted(week_summaries.keys(), reverse=True):
        rec = week_summaries[key]
        monday = rec["monday"]
        sunday = rec["sunday"]
        gross = round(rec["gross"], 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)

        iso = monday.isocalendar()
        period_label = f"Week {iso[1]} • {monday.strftime('%d %b')} – {sunday.strftime('%d %b %Y')}"
        wk_link_offset = max(0, (this_monday - monday).days // 7)

        weekly_list.append({
            "period": period_label,
            "company": company_name,
            "hours": round(rec["hours"], 2),
            "gross": gross,
            "tax": tax,
            "net": net,
            "wk_offset": wk_link_offset,
            "is_paid": key in paid_week_keys,
        })

    return render_page(
        template_name="employee/timesheets.html",
        active="reports",
        role=role,
        layout_shell=layout_shell,
        style=STYLE,
        viewport=VIEWPORT,
        pwa_tags=PWA_TAGS,
        display_name=display_name,
        company_name=company_name,
        page_back_html=page_back_button("/", "Back to dashboard"),
        weekly_list=weekly_list,
        currency=currency,
        money=money,
        fmt_hours=fmt_hours,
    )