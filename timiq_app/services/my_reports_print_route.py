def my_reports_print_impl(core):
    require_login = core["require_login"]
    session = core["session"]
    get_employee_display_name = core["get_employee_display_name"]
    get_company_settings = core["get_company_settings"]
    datetime = core["datetime"]
    tz = core["tz"]
    request = core["request"]
    timedelta = core["timedelta"]
    get_workhours_rows = core["get_workhours_rows"]
    get_payroll_rows = core["get_payroll_rows"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    col_pay = core["col_pay"]
    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    user_in_same_workplace = core["user_in_same_workplace"]
    safe_float = core["safe_float"]
    _round_to_half_hour = core["_round_to_half_hour"]
    money = core["money"]
    fmt_hours = core["fmt_hours"]
    escape = core["escape"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    page_back_button = core["page_back_button"]
    OVERTIME_HOURS = core["OVERTIME_HOURS"]
    USE_DATABASE = core["USE_DATABASE"]
    OnboardingRecord = core["OnboardingRecord"]
    onboarding_sheet = core["onboarding_sheet"]

    # PASTE ONLY THE BODY OF my_reports_print() BELOW THIS LINE
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

    now = datetime.now(tz)
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

    selected_week_hours = 0.0
    selected_week_pay = 0.0

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
        if len(r) <= col_pay:
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
        pay = safe_float((r[col_pay] if len(r) > col_pay else "") or "0", 0.0)

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

    w_g, w_t, w_n = gross_tax_net(selected_week_pay)
    selected_week_payment_mode = "net"

    payroll_rows = get_payroll_rows()
    p_headers = payroll_rows[0] if payroll_rows else []

    def pidx(name):
        return p_headers.index(name) if name in p_headers else None

    i_p_ws = pidx("WeekStart")
    i_p_we = pidx("WeekEnd")
    i_p_user = pidx("Username")
    i_p_gross = pidx("Gross")
    i_p_tax = pidx("Tax")
    i_p_dt = pidx("DisplayTax")
    i_p_dn = pidx("DisplayNet")
    i_p_pm = pidx("PaymentMode")
    i_p_paid_at = pidx("PaidAt")
    i_p_paid = pidx("Paid")
    i_p_wp = pidx("Workplace_ID")

    ytd_taxable_pay = 0.0
    ytd_cis_tax = 0.0
    pay_date_text = ""
    selected_week_found_in_payroll = False

    for r in payroll_rows[1:]:
        if i_p_user is None or i_p_ws is None or i_p_we is None:
            continue
        if len(r) <= max(i_p_user, i_p_ws, i_p_we):
            continue

        row_user = (r[i_p_user] or "").strip()
        if row_user != username:
            continue

        if i_p_wp is not None:
            row_wp = (r[i_p_wp] if len(r) > i_p_wp else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

        row_ws_str = (r[i_p_ws] or "").strip()
        row_we_str = (r[i_p_we] or "").strip()
        if not row_ws_str or not row_we_str:
            continue

        try:
            row_ws = datetime.strptime(row_ws_str, "%Y-%m-%d").date()
            row_we = datetime.strptime(row_we_str, "%Y-%m-%d").date()
        except Exception:
            continue

        paid_flag = ((r[i_p_paid] if (i_p_paid is not None and len(r) > i_p_paid) else "") or "").strip().lower()
        paid_at_raw = ((r[i_p_paid_at] if (i_p_paid_at is not None and len(r) > i_p_paid_at) else "") or "").strip()

        if paid_flag not in ("true", "1", "yes", "paid") and not paid_at_raw:
            continue

        row_gross = safe_float((r[i_p_gross] if (i_p_gross is not None and len(r) > i_p_gross) else "") or "0", 0.0)
        row_tax = safe_float((r[i_p_tax] if (i_p_tax is not None and len(r) > i_p_tax) else "") or "0", 0.0)
        row_display_tax = safe_float((r[i_p_dt] if (i_p_dt is not None and len(r) > i_p_dt) else "") or "", row_tax)
        row_display_net = safe_float((r[i_p_dn] if (i_p_dn is not None and len(r) > i_p_dn) else "") or "",
                                     round(row_gross - row_tax, 2))
        row_payment_mode = ((r[i_p_pm] if (i_p_pm is not None and len(r) > i_p_pm) else "") or "").strip().lower()
        if row_payment_mode not in {"gross", "net"}:
            row_payment_mode = "gross" if abs(row_display_tax) < 0.005 and abs(
                row_display_net - row_gross) < 0.005 else "net"

        if row_we <= selected_week_end:
            ytd_taxable_pay += row_gross
            ytd_cis_tax += row_display_tax

        if row_ws == selected_week_start and row_we == selected_week_end:
            selected_week_found_in_payroll = True
            pay_date_text = paid_at_raw or row_we_str
            w_g = round(row_gross, 2)
            w_t = round(row_display_tax, 2)
            w_n = round(row_display_net, 2)
            selected_week_payment_mode = row_payment_mode

    if not selected_week_found_in_payroll:
        ytd_taxable_pay += w_g
        ytd_cis_tax += w_t
        pay_date_text = datetime.now(tz).strftime("%Y-%m-%d")

    try:
        pay_date_display = datetime.strptime(pay_date_text, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
    except Exception:
        pay_date_display = (pay_date_text or "")[:10] or datetime.now(tz).strftime("%Y-%m-%d")

    ytd_taxable_pay = round(ytd_taxable_pay, 2)
    ytd_cis_tax = round(ytd_cis_tax, 2)

    week_label = f"Week {selected_week_start.isocalendar()[1]} ({selected_week_start.strftime('%d %b')} – {selected_week_end.strftime('%d %b %Y')})"
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

        rows_html.append(f"""
              <tr class="{row_class}">
                <td><b>{escape(item['day'])}</b></td>
                <td>{escape(item['display_date'])}</td>
                <td style="font-weight:700; text-align:center;">{escape(cin_txt)}</td>
                <td style="font-weight:700; text-align:center;">{escape(cout_txt)}</td>
                <td class="num" style="font-weight:700;">{escape(hrs_txt)}</td>
                <td class="num" style="font-weight:700;">{escape(gross_txt)}</td>
              </tr>
            """)

    rows_html = []
    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        item = week_map[d_str]

        hours_val = round(item["hours"], 2)
        gross_val = round(item["gross"], 2)
        if selected_week_payment_mode == "gross":
            net_val = gross_val
        else:
            net_val = round(gross_val - (gross_val * tax_rate), 2)

        row_class = "overtimeRow" if hours_val > OVERTIME_HOURS else ""

        cin_txt = item["first_in"] if item["first_in"] else ""
        cout_txt = item["last_out"] if item["last_out"] else ""
        hrs_txt = fmt_hours(hours_val) if hours_val > 0 else ""
        gross_txt = money(gross_val) if gross_val > 0 else ""
        net_txt = money(net_val) if net_val > 0 else ""

        rows_html.append(f"""
              <tr class="{row_class}">
                <td><b>{escape(item['day'])}</b></td>
                <td>{escape(item['display_date'])}</td>
                <td style="font-weight:700; text-align:center;">{escape(cin_txt)}</td>
                <td style="font-weight:700; text-align:center;">{escape(cout_txt)}</td>
                <td class="num" style="font-weight:700;">{escape(hrs_txt)}</td>
                <td class="num" style="font-weight:700;">{escape(gross_txt)}</td>
                <td class="num" style="font-weight:800; color:rgba(15,23,42,.92);">{escape(net_txt)}</td>
              </tr>
            """)

    page_css = """
        <style>
          .printSheetWrap{
            max-width: 980px;
            margin: 0 auto;
          }

          .printCard{
            background: #ffffff;
            border: 1px solid #e6e8f0;
            border-radius: 0 !important;
            box-shadow: 0 18px 40px rgba(15,23,42,.08);
            overflow: hidden;
          }

          .printToolbar{
            display:flex;
            justify-content:space-between;
            align-items:center;
            gap:12px;
            margin-bottom:14px;
          }

          .printToolbar .btnSoft{
            text-decoration:none;
          }

          .statementHead{
            padding: 26px 28px 18px;
            border-bottom: 1px solid #ececf4;
            background: #ffffff;
          }

          .statementHeadGrid{
            display:grid;
            grid-template-columns: 1.1fr 1fr .9fr;
            gap: 20px;
            align-items:start;
          }

          .statementCompany{
            min-width:0;
          }

          .statementLogo{
            max-height: 42px;
            max-width: 150px;
            object-fit: contain;
            display:block;
            margin-bottom: 10px;
          }

          .statementCompanyName{
            font-size: 20px;
            font-weight: 800;
            color: #0f172a;
            line-height: 1.15;
          }

          .statementCompanySub{
            margin-top: 8px;
            color: #64748b;
            font-size: 12px;
            line-height: 1.5;
          }

          .statementTitleBlock{
            text-align:center;
            min-width:0;
          }

          .statementTitle{
            font-size: 22px;
            font-weight: 900;
            color: #111827;
            line-height: 1.15;
          }

          .statementPeriod{
            margin-top: 4px;
            font-size: 16px;
            font-weight: 800;
            color: #1f2937;
          }

          .statementMeta{
            justify-self:end;
            min-width: 220px;
            text-align:right;
          }

          .statementMetaRow{
            font-size: 11px;
            color: #6b7280;
            line-height: 1.55;
          }

          .statementMetaRow strong{
            color: #111827;
            font-weight: 800;
          }

          .statementBody{
            padding: 20px 28px 18px;
          }

          .statementTopGrid{
            display:grid;
            grid-template-columns: 1fr 1fr;
            gap: 26px;
            margin-bottom: 18px;
          }

          .statementSectionTitle{
            margin: 0 0 8px 0;
            font-size: 11px;
            font-weight: 900;
            letter-spacing: .08em;
            text-transform: uppercase;
            color: #3b74ad;
          }

          .statementInfoLines{
            color: #111827;
            font-size: 13px;
            line-height: 1.7;
          }

          .statementInfoLines .muted{
            color: #6b7280;
          }

          .statementTopGrid{
      display:grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(280px, .9fr);
      gap: 42px;
      align-items:start;
      margin-bottom: 18px;
    }

    .statementSummary{
      display:grid;
      gap: 6px;
      max-width: 340px;
    }

    .statementSummaryRow{
      display:grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items:end;
      padding: 2px 0;
      font-size: 13px;
      color: #111827;
    }

    .statementSummaryRow .label{
      color: #4b5563;
      font-weight: 500;
    }

    .statementSummaryRow .value{
      font-weight: 500;
      color: #111827;
      white-space: nowrap;
    }

    .statementSummaryRow.total{
      margin-top: 6px;
      padding-top: 8px;
      border-top: 1px solid #e5e7eb;
    }

    .statementSummaryRow.total .label,
    .statementSummaryRow.total .value{
      font-weight: 900;
      color: #111827;
    }

    .statementYtdCol{
      display:flex;
      flex-direction:column;
      align-items:flex-start;
      justify-content:flex-start;
    }

    .statementPayDate{
      margin: 0 0 10px 0;
      font-size: 12px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .04em;
      color: #3b74ad;
      line-height: 1.2;
    }

    .statementYtdBox{
      width: 100%;
      max-width: 300px;
      margin: 0;
    }

    .statementYtdLabel{
      font-size: 12px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .04em;
      color: #3b74ad;
      line-height: 1.2;
    }

    .statementYtdValue{
      color: #111827;
      font-weight: 700;
    }

    .statementYtdRow{
      display:grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items:end;
      margin-top: 4px;
      font-size: 13px;
    }

    .statementYtdRow .label{
      color: #4b5563;
      font-weight: 500;
    }

    .statementYtdRow .value{
      color: #111827;
      font-weight: 500;
      white-space: nowrap;
    }

    @media (max-width: 860px){
      .statementTopGrid{
        grid-template-columns: 1fr;
        gap: 20px;
      }
    }

    .statementSummary{
      display: grid;
      gap: 6px;
      margin-bottom: 18px;
    }

    .statementYtdBox{
      width: 100%;
      max-width: 360px;
      margin: 0 0 18px 0;
    }

    .statementYtdLabel{
      font-size: 12px;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: .04em;
      color: #3b74ad;
      line-height: 1.2;
    }

    .statementYtdValue{
      color: #111827;
      font-weight: 900;
    }

    .statementYtdRow{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: end;
      margin-top: 6px;
      font-size: 13px;
    }

    .statementYtdRow .label{
      color: #4b5563;
    }

    .statementYtdRow .value{
      color: #111827;
      font-weight: 800;
      white-space: nowrap;
    }

    @media (max-width: 860px){
      .statementSummaryHead{
        flex-direction:column;
        align-items:flex-start;
      }
    }

          .statementBottomBar{
            height: 14px;
            background: linear-gradient(90deg, #4482c3 0%, #3b74ad 40%, #315f8f 100%);
          }

          @media (max-width: 860px){
            .statementHeadGrid,
            .statementTopGrid,
            .statementFooterTotals{
              grid-template-columns: 1fr;
            }

            .statementMeta{
              justify-self:start;
              text-align:left;
              min-width:0;
            }

            .statementTitleBlock{
              text-align:left;
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
            .headerTop,
            .badge{
              display:none !important;
              visibility:hidden !important;
            }

            .shell,
            .content,
            .page,
            .main,
            .printSheetWrap{
              margin:0 !important;
              padding:0 !important;
              width:100% !important;
              max-width:none !important;
            }

            body{
              background:#ffffff !important;
              margin:0 !important;
              padding:0 !important;
              -webkit-print-color-adjust: exact;
              print-color-adjust: exact;
            }

            .printCard,
            .statementTableWrap,
            .statementTotalCard{
              box-shadow:none !important;
            }

            .printCard{
              border:none !important;
            }
          }
        </style>
        """
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

    content = f"""
          {page_css}

          <div class="printSheetWrap">
            <div class="printToolbar noPrint">
              {page_back_button(f"/my-reports?wk={wk_offset}", "Back to timesheets")}
              <button class="btnSoft" type="button" onclick="window.print()">Save / Print Payslip</button>
            </div>

            <div class="printCard">
              <div class="statementHead" style="padding:18px 24px 12px;">
                <div class="statementHeadGrid" style="grid-template-columns:1.2fr 1fr; gap:18px;">
                  <div class="statementCompany">
      {f'<img src="{escape(company_logo)}" alt="Company logo" class="statementLogo">' if company_logo else ''}
      <div class="statementCompanyName">{escape(display_name)}</div>
      <div class="statementCompanySub">
        <strong>UTR:</strong> {escape(utr_number)}<br>
        <strong>National Insurance:</strong> {escape(ni_number)}
      </div>
    </div>

    <div class="statementTitleBlock" style="text-align:right;">
      <div class="statementTitle">CIS Pay Statement</div>
      <div class="statementPeriod">{escape(week_label)}</div>
      <div class="statementMetaRow" style="margin-top:10px;">
        <strong>Generated:</strong> {escape(datetime.now(tz).strftime("%d/%m/%Y %H:%M"))}
      </div>
    </div>

                </div>
              </div>

              <div class="statementBody" style="padding:14px 24px 16px;">
              <div class="statementTopGrid">
      <div>
        <div class="statementSectionTitle" style="margin-bottom:8px;">Pay summary</div>

        <div class="statementSummary" style="margin-bottom:0;">
          <div class="statementSummaryRow">
            <div class="label">Hours worked</div>
            <div class="value">{escape(fmt_hours(selected_week_hours))}</div>
          </div>
          <div class="statementSummaryRow">
            <div class="label">Gross pay</div>
            <div class="value">{escape(currency)}{money(w_g)}</div>
          </div>
          <div class="statementSummaryRow">
            <div class="label">Tax</div>
            <div class="value">{escape(currency)}{money(w_t)}</div>
          </div>
          <div class="statementSummaryRow total">
            <div class="label">Total net pay</div>
            <div class="value">{escape(currency)}{money(w_n)}</div>
          </div>
        </div>
      </div>

      <div class="statementYtdCol">
        <div class="statementPayDate">Pay Date: <span class="statementYtdValue">{escape(pay_date_display)}</span></div>

        <div class="statementYtdBox">
          <div class="statementYtdLabel">Year To Date</div>

          <div class="statementYtdRow">
            <div class="label">Taxable Pay</div>
            <div class="value">{escape(currency)}{money(ytd_taxable_pay)}</div>
          </div>

          <div class="statementYtdRow">
            <div class="label">CIS Tax</div>
            <div class="value">{escape(currency)}{money(ytd_cis_tax)}</div>
          </div>
        </div>
      </div>
    </div>

              <div class="statementBottomBar"></div>
            </div>
          </div>
        """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("reports", role, content))
