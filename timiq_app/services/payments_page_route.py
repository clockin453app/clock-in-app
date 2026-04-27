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
    escape = core["escape"]
    money = core["money"]
    page_back_button = core["page_back_button"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]

    # PASTE ONLY THE BODY OF payments_page() BELOW THIS LINE

    # PASTE ONLY THE BODY OF payments_page() BELOW THIS LINE

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
    i_pm = idx("PaymentMode")
    i_pa = idx("PaidAt")
    i_pb = idx("PaidBy")
    i_paid = idx("Paid")
    i_wp = idx("Workplace_ID")

    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    def money_float(v):
        try:
            return round(float(str(v or "0").replace("£", "").replace(",", "").strip() or "0"), 2)
        except Exception:
            return 0.0

    def fmt_paid_at(raw):
        raw = str(raw or "").strip()
        if not raw:
            return ""
        try:
            return datetime.fromisoformat(raw).strftime("%d/%m/%y")
        except Exception:
            pass
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%y")
        except Exception:
            pass
        return raw[:10]

    paid_rows = []

    for r in vals[1:]:
        row_user = (r[i_u] if i_u is not None and i_u < len(r) else "").strip()
        if row_user != username:
            continue

        row_wp = ((r[i_wp] if i_wp is not None and i_wp < len(r) else "").strip() or "default")
        if row_wp not in allowed_wps:
            continue

        week_start = (r[i_ws] if i_ws is not None and i_ws < len(r) else "").strip()
        week_end = (r[i_we] if i_we is not None and i_we < len(r) else "").strip()
        paid_at = (r[i_pa] if i_pa is not None and i_pa < len(r) else "").strip()
        paid_by = (r[i_pb] if i_pb is not None and i_pb < len(r) else "").strip()
        paid_flag = (r[i_paid] if i_paid is not None and i_paid < len(r) else "").strip().lower()

        is_paid = bool(paid_at) or paid_flag in {"true", "yes", "1", "paid"}
        if not is_paid:
            continue

        try:
            monday = date.fromisoformat(week_start)
            sunday = date.fromisoformat(week_end)
        except Exception:
            continue

        gross = money_float(r[i_g] if i_g is not None and i_g < len(r) else "0")
        tax = money_float(r[i_t] if i_t is not None and i_t < len(r) else "0")
        net = money_float(r[i_n] if i_n is not None and i_n < len(r) else "0")

        display_tax = money_float(r[i_dt] if i_dt is not None and i_dt < len(r) else tax)
        display_net = money_float(r[i_dn] if i_dn is not None and i_dn < len(r) else net)
        payment_mode = ((r[i_pm] if i_pm is not None and i_pm < len(r) else "") or "").strip().lower()
        if payment_mode not in {"gross", "net"}:
            payment_mode = "gross" if abs(display_tax) < 0.005 and abs(display_net - gross) < 0.005 else "net"

        wk_offset = max(0, (this_monday - monday).days // 7)
        iso = monday.isocalendar()
        period_label = f"Week {iso[1]} • {monday.strftime('%d %b')} – {sunday.strftime('%d %b %Y')}"

        paid_rows.append({
            "monday": monday,
            "period": period_label,
            "paid_at": fmt_paid_at(paid_at),
            "paid_by": paid_by or "-",
            "company": company_name,
            "gross": gross,
            "tax": display_tax,
            "net": display_net,
            "payment_mode": payment_mode,
            "wk_offset": wk_offset,
        })

    paid_rows.sort(key=lambda x: x["monday"], reverse=True)

    row_html = []
    for item in paid_rows:
        row_html.append(f"""
              <tr>
                <td>{escape(item['period'])}</td>
                <td class="num">{escape(currency)}{money(item['gross'])}</td>
                <td class="num">{escape(currency)}{money(item['tax'])}</td>
                <td class="num">{escape(currency)}{money(item['net'])}</td>
                <td class="num">
                  <a class="reportsListDownloadBtn" href="/my-reports-print?wk={item['wk_offset']}&back=payments" title="Open payslip">↓</a>
                </td>
              </tr>
            """)

    if not row_html:
        row_html = [
            "<tr><td colspan='5' style='text-align:center; color:#6f6c85; padding:24px;'>No paid weeks found yet.</td></tr>"
        ]

    page_css = """
        <style>
          .paymentsShell{
            max-width: 1320px;
            margin: 0 auto;
            padding: 6px 0 18px;
          }

          .paymentsHeader{
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:18px;
            margin-bottom:14px;
          }

          .paymentsEyebrow{
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

          .paymentsHeader h1{
            margin:10px 0 8px;
            font-size:clamp(34px,4vw,46px);
            line-height:1.02;
            letter-spacing:-.03em;
            color:#1f2547;
            font-weight:900;
          }

          .paymentsHeader .sub{
            color:#6f6c85;
            font-size:15px;
          }

          .paymentsTableShell{
            overflow:hidden;
            border-radius: 0 !important;
            border:1px solid rgba(68,130,195,.10);
            background:#ffffff;
            box-shadow:0 16px 32px rgba(15,23,42,.08);
          }

          .paymentsTableTop{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:12px;
            padding:16px 18px;
            border-bottom:1px solid rgba(68,130,195,.08);
            background:linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,246,255,.98));
          }

          .paymentsTableTitle{
            font-size:18px;
            font-weight:900;
            color:#1f2547;
          }

          .paymentsTableMeta{
            font-size:13px;
            color:#8a84a3;
            font-weight:700;
          }

          .paymentsTableWrap{
      overflow-x:hidden;
      overflow-y:visible;
    }

    .paymentsTable{
      width:100%;
      min-width:0;
      border-collapse:separate;
      border-spacing:0;
      table-layout:fixed;
    }

          .paymentsTable th,
          .paymentsTable td{
            padding:14px 16px;
            border-bottom:1px solid rgba(68,130,195,.08);
            text-align:left;
            background:#fff;
          }

          .paymentsTable th{
            font-size:12px;
            text-transform:uppercase;
            letter-spacing:.06em;
            color:#7b7693;
            font-weight:800;
          }

          .paymentsTable td{
            color:#1f2547;
            font-size:14px;
          }

          .paymentsTable td.num,
          .paymentsTable th.num{
            text-align:right;
          }

          .paymentsTable th,
    .paymentsTable td{
      padding:12px 8px;
    }

    .paymentsTable th:nth-child(1),
    .paymentsTable td:nth-child(1){
      width:36%;
      white-space:normal;
      line-height:1.25;
    }

    .paymentsTable th:nth-child(2),
    .paymentsTable td:nth-child(2),
    .paymentsTable th:nth-child(3),
    .paymentsTable td:nth-child(3),
    .paymentsTable th:nth-child(4),
    .paymentsTable td:nth-child(4){
      width:15%;
    }

    .paymentsTable th:nth-child(5),
    .paymentsTable td:nth-child(5){
      width:7%;
    }

          .paymentsTable tbody tr:hover td{
            background:rgba(68,130,195,.03);
          }

          .reportsListDownloadBtn{
            width:34px;
            height:34px;
            display:inline-flex;
            align-items:center;
            justify-content:center;
            border-radius: 0 !important;
            border:1px solid rgba(68,130,195,.14);
            background:rgba(68,130,195,.06);
            color:#3b74ad;
            font-size:18px;
            font-weight:900;
            text-decoration:none;
            box-shadow:0 6px 14px rgba(15,23,42,.06);
          }

          .paymentsFooter{
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
      .paymentsHeader{
        flex-direction:column;
      }

      .paymentsTable th,
      .paymentsTable td{
        padding:10px 6px;
      }

      .paymentsTable th:nth-child(1),
      .paymentsTable td:nth-child(1){
        width:36%;
        padding-right:4px;
        line-height:1.15;
      }

      .paymentsTable th:nth-child(2),
      .paymentsTable td:nth-child(2){
        width:19%;
        padding-left:4px;
      }

      .paymentsTable th:nth-child(3),
      .paymentsTable td:nth-child(3),
      .paymentsTable th:nth-child(4),
      .paymentsTable td:nth-child(4){
        width:17%;
      }

      .paymentsTable th:nth-child(5),
      .paymentsTable td:nth-child(5){
        width:11%;
      }
    }
        </style>
        """

    content = f"""
          {page_css}
          {page_back_button("/", "Back to dashboard")}

          <div class="paymentsShell">
            <div class="paymentsHeader">
              <div>
              
                <h1>Payments</h1>
                <p class="sub">{escape(display_name)} • {escape(company_name)}</p>
              </div>
            </div>

            <div class="paymentsTableShell">
              <div class="paymentsTableTop">
                <div class="paymentsTableTitle">Paid weeks</div>
                <div class="paymentsTableMeta">{len(paid_rows)} paid week(s)</div>
              </div>

              <div class="paymentsTableWrap">
                <table class="paymentsTable">
                  <thead>
      <tr>
        <th>Period</th>
        <th class="num">Gross</th>
        <th class="num">CIS Tax</th>
        <th class="num">Net</th>
        <th class="num"></th>
      </tr>
    </thead>
                  <tbody>
                    {''.join(row_html)}
                  </tbody>
                </table>
              </div>


            </div>
          </div>
        """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("payments", role, content))
