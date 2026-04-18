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
    render_template_string = core["render_template_string"]

    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

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

    page_css = """
        <style>
          .weekReportShell{
            max-width: 760px;
            margin: 0 auto;
            padding: 8px 0 20px;
          }

          .weekReportCard{
            background:#ffffff;
            border:1px solid rgba(68,130,195,.10);
            box-shadow:0 18px 36px rgba(15,23,42,.08);
            padding:20px;
          }

          .weekReportTitle{
            font-size:18px;
            font-weight:900;
            color:#3b74ad;
            margin:0 0 18px 0;
          }

          .weekReportSection{
            background:#f8f7ff;
            border:1px solid rgba(68,130,195,.08);
            padding:16px;
            margin-top:14px;
          }

          .weekReportSectionTitle{
            font-size:15px;
            font-weight:900;
            color:#111827;
            margin:0 0 12px 0;
          }

          .weekReportGrid{
            display:grid;
            grid-template-columns: 140px 1fr;
            gap:10px 14px;
            align-items:start;
          }

          .weekReportLabel{
            color:#6f6c85;
            font-weight:500;
          }

          .weekReportValue{
            color:#111827;
            font-weight:600;
          }

          @media (max-width: 640px){
            .weekReportGrid{
              grid-template-columns: 1fr 1fr;
            }
          }
        </style>
        """

    content = f"""
          {page_css}
          {page_back_button("/my-reports", "Back to timesheets")}

          <div class="weekReportShell">
            <div class="weekReportCard">
              <h1 class="weekReportTitle">{escape(period_label)}</h1>

              <div class="weekReportSection">
                <div class="weekReportSectionTitle">General Info</div>
                <div class="weekReportGrid">
                  <div class="weekReportLabel">Period:</div>
                  <div class="weekReportValue">{escape(full_period)}</div>

                  <div class="weekReportLabel">Payment Date:</div>
                  <div class="weekReportValue">{escape(payment_date)}</div>

                  <div class="weekReportLabel">Company:</div>
                  <div class="weekReportValue">{escape(company_name)}</div>
                </div>
              </div>

              <div class="weekReportSection">
                <div class="weekReportSectionTitle">Estimated Earnings</div>
                <div class="weekReportGrid">
                  <div class="weekReportLabel">Hours/Days:</div>
                  <div class="weekReportValue">{escape(fmt_hours(week_hours))}</div>

                  <div class="weekReportLabel">Rate:</div>
                  <div class="weekReportValue">{escape(currency)}{escape(f"{rate:.2f}")}</div>

                  <div class="weekReportLabel">OT Hours/Days:</div>
                  <div class="weekReportValue">{escape(fmt_hours(overtime_hours))}</div>

                  <div class="weekReportLabel">Adjustments:</div>
                  <div class="weekReportValue">{escape(currency)}0.00</div>

                  <div class="weekReportLabel">Expenses:</div>
                  <div class="weekReportValue">{escape(currency)}0.00</div>

                  <div class="weekReportLabel">Mileage:</div>
                  <div class="weekReportValue">0</div>

                  <div class="weekReportLabel">Gross Pay:</div>
                  <div class="weekReportValue">{escape(currency)}{money(week_gross)}</div>
                </div>
              </div>
            </div>
          </div>
        """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("reports", role, content)
    )
