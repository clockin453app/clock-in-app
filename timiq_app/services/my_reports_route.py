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
    render_template_string = core["render_template_string"]

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

    list_rows_html = []
    for item in weekly_list:
        list_rows_html.append(f"""
              <tr>
                <td>{escape(item['period'])}{" <span title='Paid' style='display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;margin-left:8px;border-radius:999px;background:rgba(22,163,74,.12);color:#169c2f;font-size:12px;font-weight:900;vertical-align:middle;'>£</span>" if item['is_paid'] else ""}</td>
                <td class="num">{escape(fmt_hours(item['hours']))}</td>
                <td class="num">{escape(currency)}{money(item['gross'])}</td>
                <td class="num">{escape(currency)}{money(item['tax'])}</td>
                <td class="num">{escape(currency)}{money(item['net'])}</td>
                <td>{escape(item['company'])}</td>
                <td class="num">
                  <a class="reportsListDownloadBtn"
                     href="/my-week-report?wk={item['wk_offset']}"
                     target="_blank"
                     rel="noopener"
                     title="View slip">
                    &#8250;
                  </a>
                </td>
              </tr>
            """)

    if not list_rows_html:
        list_rows_html = [
            "<tr><td colspan='8' style='text-align:center; color:#6f6c85; padding:24px;'>No weekly timesheet records found.</td></tr>"
        ]

    page_css = """
        <style>
          .reportsListShell{
            max-width: 1320px;
            margin: 0 auto;
            padding: 6px 0 18px;
          }

          .reportsListHeader{
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:18px;
            margin-bottom:14px;
          }

          .reportsListEyebrow{
            display:inline-flex;
            align-items:center;
            padding:8px 14px;
            border-radius: 0 !important;
            border:1px solid rgba(68,130,195,.12);
            background:rgba(68,130,195,.06);
            color:#3b74ad;
            font-size:12px;
            font-weight:800;
            text-transform:uppercase;
            letter-spacing:.06em;
          }

          .reportsListHeader h1{
            margin:10px 0 8px;
            font-size:clamp(34px,4vw,46px);
            line-height:1.02;
            letter-spacing:-.03em;
            color:#1f2547;
            font-weight:900;
          }

          .reportsListHeader .sub{
            color:#6f6c85;
            font-size:15px;
          }

          .reportsListTopActions{
            display:flex;
            align-items:center;
            gap:10px;
            flex-wrap:wrap;
          }

          .reportsListTopActions .btnSoft{
            text-decoration:none;
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-height:46px;
            padding:0 16px;
            border-radius: 0 !important;
            font-weight:800;
            background:#ffffff;
            border:1px solid rgba(68,130,195,.12);
            color:#4338ca;
            box-shadow:0 8px 18px rgba(15,23,42,.06);
          }

          .reportsListTopActions .btnPrimary{
            text-decoration:none;
            display:inline-flex;
            align-items:center;
            justify-content:center;
            min-height:46px;
            padding:0 18px;
            border-radius: 0 !important;
            font-weight:800;
            color:#ffffff;
            background:linear-gradient(90deg, #4f89c7, #3b74ad);
            box-shadow:0 12px 24px rgba(79,70,229,.20);
          }

          .reportsListTableShell{
            border:1px solid rgba(68,130,195,.10);
            border-radius: 0 !important;
            overflow:hidden;
            background:linear-gradient(180deg, #ffffff, #f8fbfe);
            box-shadow:0 18px 36px rgba(15,23,42,.08);
          }

          .reportsListTableTop{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:12px;
            padding:14px 18px;
            border-bottom:1px solid rgba(68,130,195,.08);
            background:linear-gradient(180deg, rgba(68,130,195,.04), rgba(255,255,255,.85));
          }

          .reportsListTableTitle{
            font-size:18px;
            font-weight:800;
            color:#1f2547;
          }

          .reportsListTableMeta{
            color:#6f6c85;
            font-size:14px;
            font-weight:600;
          }

          .reportsListTableWrap{
            overflow:auto;
            background:#ffffff;
          }

          .reportsListTable{
      width:100%;
      min-width:0;
      border-collapse:separate;
      border-spacing:0;
      table-layout:fixed;
      background:#ffffff;
    }

    .reportsListTable th:nth-child(1),
    .reportsListTable td:nth-child(1){
      width:240px;
      min-width:240px;
      max-width:240px;
      white-space:nowrap;
      padding-right:2px;
    }

    .reportsListTable th:nth-child(2),
    .reportsListTable td:nth-child(2){
      width:52px;
      min-width:52px;
      max-width:52px;
      white-space:nowrap;
      text-align:left !important;
      padding-left:2px;
      padding-right:4px;
    }

    .reportsListTable th:nth-child(3),
    .reportsListTable td:nth-child(3),
    .reportsListTable th:nth-child(4),
    .reportsListTable td:nth-child(4),
    .reportsListTable th:nth-child(5),
    .reportsListTable td:nth-child(5){
      width:110px;
      min-width:110px;
      max-width:110px;
      white-space:nowrap;
    }

    .reportsListTable th:nth-child(6),
    .reportsListTable td:nth-child(6){
      width:230px;
      min-width:230px;
      max-width:230px;
      white-space:nowrap;
    }

    .reportsListTable th:nth-child(7),
    .reportsListTable td:nth-child(7){
      width:52px;
      min-width:52px;
      max-width:52px;
    }

    .reportsListTable thead th{
      background:#f4f5fb;
      color:#6b7280;
      font-size:12px;
      font-weight:800;
      text-transform:uppercase;
      letter-spacing:.04em;
      padding:12px 6px;
      border-bottom:1px solid #e8eaf2;
      text-align:left;
      white-space:nowrap;
    }

    .reportsListTable tbody td{
      padding:13px 6px;
      color:#1f2547;
      font-size:14px;
      font-weight:700;
      border-bottom:1px solid #edf0f5;
      white-space:nowrap;
      background:#ffffff;
    }

          .reportsListTable tbody tr:nth-child(even) td{
            background:#fcfbff;
          }

          .reportsListTable tbody tr:hover td{
            background:#f7f4ff;
          }

          .reportsListTable td.num,
          .reportsListTable th.num{
            text-align:right;
            font-variant-numeric:tabular-nums;
          }

          .reportsListTable tbody tr:last-child td{
            border-bottom:0;
          }

          .reportsListDownloadBtn{
            display:inline-flex;
            align-items:center;
            justify-content:center;
            width:34px;
            height:34px;
            border-radius: 0 !important;
            border:1px solid rgba(68,130,195,.14);
            background:rgba(68,130,195,.06);
            color:#3b74ad;
            font-size:18px;
            font-weight:900;
            text-decoration:none;
            box-shadow:0 6px 14px rgba(15,23,42,.06);
            transition:transform .16s ease, box-shadow .16s ease, background .16s ease;
          }

          .reportsListDownloadBtn:hover{
            transform:translateY(-1px);
            background:rgba(68,130,195,.10);
            box-shadow:0 10px 18px rgba(15,23,42,.10);
          }

          .reportsListFooter{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:12px;
            padding:12px 18px 16px;
            border-top:1px solid rgba(68,130,195,.08);
            background:#ffffff;
            color:#8a84a3;
            font-size:13px;
          }

          @media (max-width: 820px){
            .reportsListHeader{
              flex-direction:column;
            }

            .reportsListTopActions{
              width:100%;
            }

            .reportsListTopActions .btnSoft,
            .reportsListTopActions .btnPrimary{
              width:100%;
            }
          }

          @media print{
            .sidebar,
            .topbar,
            .mobileNav,
            .bottomNav,
            .dashboardMainMenu,
            .payrollMenuBackdrop,
            .payrollMenuToggle,
            #payrollMenuBackdrop,
            #payrollMenuToggle,
            .noPrint,
            .badge{
              display:none !important;
              visibility:hidden !important;
            }

            .shell,
            .content,
            .page,
            .main,
            .reportsListShell{
              margin:0 !important;
              padding:0 !important;
              width:100% !important;
              max-width:none !important;
            }

            body{
              background:#fff !important;
              margin:0 !important;
              padding:0 !important;
            }

            .reportsListTableShell{
              box-shadow:none !important;
            }
          }
        </style>
        """
    week_label = f"Week {selected_week_start.isocalendar()[1]} ({selected_week_start.strftime('%d %b')} – {selected_week_end.strftime('%d %b %Y')})"
    ni_number = ""
    utr_number = ""

    if USE_DATABASE:
        allowed_wps = set(_workplace_ids_for_read())
        onboard_rec = (
            OnboardingRecord.query
            .filter(OnboardingRecord.username == username)
            .filter(OnboardingRecord.workplace_id.in_(allowed_wps))
            .order_by(OnboardingRecord.id.desc())
            .first()
        )
        if onboard_rec:
            ni_number = str(getattr(onboard_rec, "national_insurance", "") or "").strip()
            utr_number = str(getattr(onboard_rec, "utr", "") or "").strip()
    else:
        try:
            allowed_wps = set(_workplace_ids_for_read())
            for rec in reversed(onboarding_sheet.get_all_records()):
                rec_user = str(rec.get("Username") or "").strip()
                rec_wp = str(rec.get("Workplace_ID") or "default").strip() or "default"
                if rec_user == username and rec_wp in allowed_wps:
                    ni_number = str(rec.get("NationalInsurance") or "").strip()
                    utr_number = str(rec.get("UTR") or "").strip()
                    break
        except Exception:
            pass

    ni_number = ni_number or "—"
    utr_number = utr_number or "—"
    rows_html = []
    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        item = week_map[d_str]

        hours_val = round(item["hours"], 2)
        gross_val = round(item["gross"], 2)

        row_class = "overtimeRow" if hours_val > OVERTIME_HOURS else ""

        cin_txt = item["first_in"] if item["first_in"] else ""
        cout_txt = item["last_out"] if item["last_out"] else ""
        hrs_txt = fmt_hours(hours_val) if hours_val > 0 else ""
        gross_txt = money(gross_val) if gross_val > 0 else ""

    content = f"""
          {page_css}

          {page_back_button("/", "Back to dashboard")}

          <div class="reportsListShell">
            <div class="reportsListHeader">
              <div>
                <div class="reportsListEyebrow">Timesheets</div>
                <h1>Timesheets</h1>
                <p class="sub">{escape(display_name)} • {escape(company_name)}</p>
              </div>

            </div>

            <div class="reportsListTableShell">
              <div class="reportsListTableTop">
                <div class="reportsListTableTitle">All weekly timesheets</div>
                <div class="reportsListTableMeta">{len(weekly_list)} week(s)</div>
              </div>

              <div class="reportsListTableWrap">
                <table class="reportsListTable">
    <thead>
      <tr>
       <th>Period</th>
    <th class="num">Hours</th>
    <th class="num">Gross Pay</th>
    <th class="num">CIS Tax</th>
    <th class="num">Take Home</th>
    <th>Company</th>
    <th class="num">View</th> 
      </tr>
    </thead>
                  <tbody>
                    {''.join(list_rows_html)}
                  </tbody>
                </table>
              </div>


            </div>
          </div>
        """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("reports", role, content))
