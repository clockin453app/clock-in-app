def admin_payroll_impl(core):
    require_admin = core["require_admin"]
    get_csrf = core["get_csrf"]
    _ensure_workhours_geo_headers = core["_ensure_workhours_geo_headers"]
    get_company_settings = core["get_company_settings"]
    request = core["request"]
    date = core["date"]
    get_workhours_rows = core["get_workhours_rows"]
    get_payroll_rows = core["get_payroll_rows"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    WorkHour = core["WorkHour"]
    and_ = core["and_"]
    or_ = core["or_"]
    _list_employee_records_for_workplace = core["_list_employee_records_for_workplace"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    timedelta = core["timedelta"]
    COL_PAY = core["COL_PAY"]
    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    user_in_same_workplace = core["user_in_same_workplace"]
    _round_to_half_hour = core["_round_to_half_hour"]
    safe_float = core["safe_float"]
    get_employee_display_name = core["get_employee_display_name"]
    url_for = core["url_for"]
    build_payroll_chart_and_kpis = core["build_payroll_chart_and_kpis"]
    _is_paid_for_week = core["_is_paid_for_week"]
    _get_paid_record_for_week = core["_get_paid_record_for_week"]
    OVERTIME_HOURS = core["OVERTIME_HOURS"]
    re = core["re"]
    fmt_hours = core["fmt_hours"]
    money = core["money"]
    escape = core["escape"]
    _svg_clipboard = core["_svg_clipboard"]
    _svg_chart = core["_svg_chart"]
    build_payroll_employee_card = core["build_payroll_employee_card"]
    admin_back_link = core["admin_back_link"]
    session = core["session"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    _calculate_shift_pay = core["_calculate_shift_pay"]
    _calculate_shift_pay_from_rule = core["_calculate_shift_pay_from_rule"]
    _get_user_rate = core["_get_user_rate"]
    _get_active_locations = core["_get_active_locations"]


    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    _ensure_workhours_geo_headers()
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    company_name = str(settings.get("Company_Name") or "Main").strip() or "Main"
    company_logo = str(settings.get("Company_Logo_URL") or "").strip()
    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    try:
        overtime_after = float(settings.get("Overtime_After_Hours", 8.5) or 8.5)
    except Exception:
        overtime_after = 8.5

    try:
        overtime_multiplier = max(1.0, float(settings.get("Overtime_Multiplier", 1.5) or 1.5))
    except Exception:
        overtime_multiplier = 1.5

    def calc_o_hours(username, d_str, hours_value):
        h = safe_float(hours_value, 0.0)

        rule = _get_saved_shift_rule(username, d_str)
        row_overtime_after = overtime_after
        row_overtime_multiplier = overtime_multiplier

        if rule:
            if rule.get("overtime_after_hours") is not None:
                row_overtime_after = float(rule["overtime_after_hours"])
            if rule.get("overtime_multiplier") is not None:
                row_overtime_multiplier = max(1.0, float(rule["overtime_multiplier"]))

        if h <= row_overtime_after or row_overtime_multiplier <= 1.0:
            return 0.0

        extra = (h - row_overtime_after) * (row_overtime_multiplier - 1.0)
        return round(extra, 2)

    def calc_day_gross(username, d_str, hours_value, stored_pay=""):
        if str(stored_pay).strip() != "":
            return round(safe_float(stored_pay, 0.0), 2)

        h = safe_float(hours_value, 0.0)
        if h <= 0:
            return 0.0

        rule = _get_saved_shift_rule(username, d_str)
        if rule:
            row_overtime_after = overtime_after
            row_overtime_multiplier = overtime_multiplier

            if rule.get("overtime_after_hours") is not None:
                row_overtime_after = float(rule["overtime_after_hours"])
            if rule.get("overtime_multiplier") is not None:
                row_overtime_multiplier = max(1.0, float(rule["overtime_multiplier"]))

            return round(
                _calculate_shift_pay_from_rule(
                    h,
                    _get_user_rate(username),
                    {
                        "overtime_after_hours": row_overtime_after,
                        "overtime_multiplier": row_overtime_multiplier,
                    },
                ),
                2,
            )

        try:
            return round(_calculate_shift_pay(h, _get_user_rate(username)), 2)
        except Exception:
            return round(safe_float(stored_pay, 0.0), 2)

    q = (request.args.get("q", "") or "").strip().lower()

    def site_text_color(site_name: str) -> str:
        key = str(site_name or "").strip().lower()
        if not key:
            return "#6f6c85"

        total = 0
        for i, ch in enumerate(key):
            total += (i + 1) * ord(ch)

        hue = total % 360
        return f"hsl({hue}, 65%, 38%)"
    date_from = (request.args.get("from", "") or "").strip()
    date_to = (request.args.get("to", "") or "").strip()
    ym = (request.args.get("ym", "") or "").strip()
    use_range = False
    range_start = None
    range_end = None

    if date_from and date_to:
        try:
            range_start = date.fromisoformat(date_from)
            range_end = date.fromisoformat(date_to)
            use_range = True
        except ValueError:
            use_range = False
            range_start = None
            range_end = None

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    in_site_idx = headers.index("InSite") if (headers and "InSite" in headers) else None
    out_site_idx = headers.index("OutSite") if (headers and "OutSite" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    def _get_saved_shift_rule(username, d_str):
        if not DB_MIGRATION_MODE:
            return None

        try:
            shift_date = date.fromisoformat(d_str)
        except Exception:
            return None

        rec = (
            WorkHour.query
            .filter(
                and_(
                    WorkHour.employee_email == username,
                    WorkHour.date == shift_date,
                    or_(
                        WorkHour.workplace_id.in_(allowed_wps),
                        and_(WorkHour.workplace_id.is_(None), WorkHour.workplace.in_(allowed_wps)),
                        WorkHour.workplace.in_(allowed_wps),
                    ),
                )
            )
            .order_by(WorkHour.id.desc())
            .first()
        )

        if not rec:
            return None

        try:
            ot_after = float(getattr(rec, "snapshot_overtime_after_hours", None))
        except Exception:
            ot_after = None

        try:
            ot_mult = float(getattr(rec, "snapshot_overtime_multiplier", None))
        except Exception:
            ot_mult = None

        return {
            "overtime_after_hours": ot_after,
            "overtime_multiplier": ot_mult,
        }

    employee_records = []
    try:
        employee_records = _list_employee_records_for_workplace(include_inactive=True)
    except Exception:
        employee_records = []
    current_users = [
        (rec.get("Username") or "").strip()
        for rec in employee_records
        if (rec.get("Username") or "").strip()
    ]
    current_usernames = set(current_users)


    month_start = None
    month_end = None

    try:
        if ym:
            month_start = datetime.strptime(ym + "-01", "%Y-%m-%d").date()
        else:
            month_start = datetime.now(TZ).date().replace(day=1)
            ym = month_start.strftime("%Y-%m")
        if month_start.month == 12:
            month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)
    except Exception:
        month_start = datetime.now(TZ).date().replace(day=1)
        ym = month_start.strftime("%Y-%m")
        if month_start.month == 12:
            month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)



    today = datetime.now(TZ).date()
    wk_offset_raw = (request.args.get("wk", "0") or "0").strip()
    try:
        wk_offset = max(0, int(wk_offset_raw))
    except Exception:
        wk_offset = 0

    this_monday = today - timedelta(days=today.weekday())
    week_start = this_monday - timedelta(days=7 * wk_offset)
    week_end = week_start + timedelta(days=6)
    week_start_str = week_start.strftime("%Y-%m-%d")
    week_end_str = week_end.strftime("%Y-%m-%d")
    db_site_lookup = {}

    if DB_MIGRATION_MODE:
        try:
            db_site_rows = (
                WorkHour.query
                .filter(
                    and_(
                        or_(
                            WorkHour.workplace_id.in_(allowed_wps),
                            and_(WorkHour.workplace_id.is_(None), WorkHour.workplace.in_(allowed_wps)),
                            WorkHour.workplace.in_(allowed_wps),
                        ),
                        WorkHour.date >= week_start,
                        WorkHour.date <= week_end,
                    )
                )
                .order_by(WorkHour.date.asc(), WorkHour.id.asc())
                .all()
            )

            for rec in db_site_rows:
                rec_user = str(getattr(rec, "employee_email", "") or "").strip()
                rec_date = rec.date.isoformat() if getattr(rec, "date", None) else ""
                rec_cin = rec.clock_in.strftime("%H:%M") if getattr(rec, "clock_in", None) else ""
                rec_cout = rec.clock_out.strftime("%H:%M") if getattr(rec, "clock_out", None) else ""
                rec_site = str(
                    getattr(rec, "out_site", "")
                    or getattr(rec, "in_site", "")
                    or ""
                ).strip()

                if not rec_user or not rec_date:
                    continue

                db_site_lookup[(rec_user, rec_date, rec_cin, rec_cout)] = rec_site
        except Exception:
            db_site_lookup = {}

    def week_label(d0):
        iso = d0.isocalendar()
        return f"Week {iso[1]} ({d0.strftime('%d %b')} – {(d0 + timedelta(days=6)).strftime('%d %b %Y')})"

    def in_range(d: str) -> bool:
        if not d:
            return False

        if use_range and range_start and range_end:
            try:
                d_obj = date.fromisoformat(d)
            except Exception:
                return False
            return range_start <= d_obj <= range_end

        return week_start_str <= d <= week_end_str

    filtered = []
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        user = (r[COL_USER] or "").strip()
        if not user or user not in current_usernames:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(user):
                continue

        d = (r[COL_DATE] or "").strip()
        if not in_range(d):
            continue
        if q and q not in user.lower():
            continue

        row_data = {
            "user": user,
            "date": d,
            "cin": (r[COL_IN] if len(r) > COL_IN else "") or "",
            "cout": (r[COL_OUT] if len(r) > COL_OUT else "") or "",
            "hours": (r[COL_HOURS] if len(r) > COL_HOURS else "") or "",
            "pay": (r[COL_PAY] if len(r) > COL_PAY else "") or "",
        }
        if row_data["hours"] != "":
            row_data["pay"] = str(calc_day_gross(user, d, row_data["hours"], row_data["pay"]))
        filtered.append(row_data)

    by_user = {}
    overall_hours = 0.0
    overall_o = 0.0
    overall_gross = 0.0

    for row in filtered:
        u = row["user"] or "Unknown"
        by_user.setdefault(u, {"hours": 0.0, "o": 0.0, "gross": 0.0})
        if row["hours"] != "":
            worked_h = safe_float(row["hours"], 0.0)
            o_h = calc_o_hours(u, row["date"], worked_h)
            paid_h = worked_h + o_h
            g = safe_float(row["pay"], 0.0)

            by_user[u]["hours"] += paid_h
            by_user[u]["o"] += o_h
            by_user[u]["gross"] += g

            overall_hours += paid_h
            overall_o += o_h
            overall_gross += g

    overall_tax = round(overall_gross * tax_rate, 2)
    overall_net = round(overall_gross - overall_tax, 2)

    monthly_by_user = {}

    for row in filtered:
        u = row["user"] or "Unknown"
        d_str = str(row.get("date") or "").strip()
        if not d_str:
            continue

        try:
            d_obj = date.fromisoformat(d_str)
        except Exception:
            continue

        if d_obj < month_start or d_obj > month_end:
            continue

        monthly_by_user.setdefault(u, {
            "days": 0,
            "hours": 0.0,
            "overtime": 0.0,
            "gross": 0.0,
        })

        worked_h = safe_float(row.get("hours", 0.0), 0.0)
        gross_h = safe_float(row.get("pay", 0.0), 0.0)
        overtime_h = calc_o_hours(u, d_str, worked_h)

        if worked_h > 0:
            monthly_by_user[u]["days"] += 1

        monthly_by_user[u]["hours"] += worked_h
        monthly_by_user[u]["overtime"] += overtime_h
        monthly_by_user[u]["gross"] += gross_h

    monthly_rows_html = []

    for u in sorted(monthly_by_user.keys(), key=lambda s: get_employee_display_name(s).lower()):
        rec = monthly_by_user[u]
        gross = round(rec["gross"], 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)

        monthly_rows_html.append(f"""
            <tr>
              <td style="text-align:left;">{escape(get_employee_display_name(u))}</td>
              <td style="text-align:right;">{int(rec['days'])}</td>
              <td style="text-align:right;">{escape(fmt_hours(round(rec['hours'], 2)))}</td>
              <td style="text-align:right;">{escape(fmt_hours(round(rec['overtime'], 2)))}</td>
              <td style="text-align:right;">{escape(currency)}{escape(money(gross))}</td>
              <td style="text-align:right;">{escape(currency)}{escape(money(tax))}</td>
              <td style="text-align:right;">{escape(currency)}{escape(money(net))}</td>
            </tr>
        """)

    if not monthly_rows_html:
        monthly_rows_html = [
            "<tr><td colspan='7' style='text-align:center; color:#6f6c85; padding:18px;'>No payroll rows for this month.</td></tr>"
        ]

    month_label = month_start.strftime("%B %Y")

    week_lookup = {}
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        user = (r[COL_USER] or "").strip()
        d = (r[COL_DATE] or "").strip()
        if not user or not d:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(user):
                continue

        if d < week_start_str or d > week_end_str:
            continue

        row_hours = (r[COL_HOURS] if len(r) > COL_HOURS else "") or ""
        row_pay = (r[COL_PAY] if len(r) > COL_PAY else "") or ""
        if row_hours != "":
            row_pay = str(calc_day_gross(user, d, row_hours, row_pay))

        week_lookup.setdefault(user, {})

        row_cin = ((r[COL_IN] if len(r) > COL_IN else "") or "").strip()
        row_cout = ((r[COL_OUT] if len(r) > COL_OUT else "") or "").strip()
        row_in_site = (r[in_site_idx] if in_site_idx is not None and len(r) > in_site_idx else "").strip()
        row_out_site = (r[out_site_idx] if out_site_idx is not None and len(r) > out_site_idx else "").strip()
        row_site = row_out_site or row_in_site or db_site_lookup.get((user, d, row_cin[:5], row_cout[:5]), "") or ""

        week_lookup[user][d] = {
            "cin": row_cin,
            "cout": row_cout,
            "hours": row_hours,
            "pay": row_pay,
            "site": row_site,
        }

    all_users = sorted(set(current_users) | set(week_lookup.keys()), key=lambda s: s.lower())

    if q:
        all_users = [u for u in all_users if q in u.lower() or q in (get_employee_display_name(u) or "").lower()]

    employee_options = ["<option value=''>All employees</option>"]
    for u in sorted(all_users, key=lambda s: get_employee_display_name(s).lower()):
        display = get_employee_display_name(u)
        selected = "selected" if q == u.lower() else ""
        employee_options.append(
            f"<option value='{escape(u)}' {selected}>{escape(display)}</option>"
        )

    week_options = []
    for i in range(0, 52):
        d0 = this_monday - timedelta(days=7 * i)
        selected = "selected" if i == wk_offset else ""
        week_options.append(
            f"<option value='{i}' {selected}>{escape(week_label(d0))}</option>"
        )

    prev_wk = min(51, wk_offset + 1)
    next_wk = max(0, wk_offset - 1)

    payroll_refresh_url = url_for(
        "admin_payroll",
        q=q,
        **{
            "from": date_from,
            "to": date_to,
            "wk": wk_offset,
            "ym": ym,
        }
    )

    payroll_week_bar_html = f"""
          <div style="display:flex; align-items:center; justify-content:space-between; gap:14px; flex-wrap:wrap;">
            <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">

              <form method="GET" style="margin:0;">
                <input type="hidden" name="q" value="{escape(q)}">
                <input type="hidden" name="from" value="{escape(date_from)}">
                <input type="hidden" name="to" value="{escape(date_to)}">
                <input type="hidden" name="wk" value="{prev_wk}">
                <button type="submit"
                        title="Previous week"
                        aria-label="Previous week"
                        style="width:38px; height:38px; border-radius:0 !important; border:1px solid rgba(68,130,195,.14); background:#fff; color:#3b74ad; font-size:22px; font-weight:900; cursor:pointer;">
                  ‹
                </button>
              </form>

              <form method="GET" style="margin:0; display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                <input type="hidden" name="q" value="{escape(q)}">
                <input type="hidden" name="from" value="{escape(date_from)}">
                <input type="hidden" name="to" value="{escape(date_to)}">

                <div style="font-size:12px; font-weight:800; letter-spacing:.06em; text-transform:uppercase; color:#6f6c85;">
                  Week
                </div>

                <select name="wk"
                        onchange="this.form.submit()"
                        style="min-width:320px; max-width:100%; height:40px; padding:0 12px; border-radius:0 !important; border:1px solid rgba(68,130,195,.14); background:#fff; color:#1f2547; font-size:14px; font-weight:400;">
                  {''.join(week_options)}
                </select>
              </form>

              <form method="GET" style="margin:0;">
                <input type="hidden" name="q" value="{escape(q)}">
                <input type="hidden" name="from" value="{escape(date_from)}">
                <input type="hidden" name="to" value="{escape(date_to)}">
                <input type="hidden" name="wk" value="{next_wk}">
                <button type="submit"
                        title="Next week"
                        aria-label="Next week"
                        style="width:38px; height:38px; border-radius:0 !important; border:1px solid rgba(68,130,195,.14); background:#fff; color:#3b74ad; font-size:22px; font-weight:900; cursor:pointer;"
                        {"disabled style='width:38px; height:38px; border-radius:0 !important; border:1px solid rgba(68,130,195,.14); background:#f8f7ff; color:#c4b5fd; font-size:22px; font-weight:900; cursor:not-allowed;'" if wk_offset == 0 else ""}
                >
                  ›
                </button>
              </form>
            </div>

            <div style="font-size:13px; color:#6f6c85;">
              Browse the weekly history shown in the payroll table.
            </div>
          </div>
        """


    monthly_filter_html = f"""
      <div class="card plainSection" style="margin-top:16px; padding:18px;">
                <div style="display:grid; grid-template-columns:1fr auto; gap:16px; align-items:end; margin-bottom:16px;">
          <div>
            <h3 style="margin:0;">Monthly Payroll Summary</h3>
            <div class="sub" style="margin-top:4px;">One row per employee for {escape(month_label)}.</div>
          </div>

                    <form method="GET" style="display:flex; gap:12px; align-items:end; margin:0;">
            <div style="width:220px;">
              <label class="sub">Month</label>
              <input class="input" type="month" name="ym" value="{escape(ym)}">
            </div>

            <input type="hidden" name="q" value="{escape(q)}">
            <input type="hidden" name="wk" value="{wk_offset}">
            <input type="hidden" name="from" value="{escape(date_from)}">
            <input type="hidden" name="to" value="{escape(date_to)}">

            <button type="submit"
                    style="height:42px; padding:0 18px; border:1px solid rgba(68,130,195,.18); background:#5b8fca; color:#fff; font-weight:700; cursor:pointer; border-radius:0;">
              Apply
            </button>
          </form>
        </div>

        <div class="tablewrap">
          <table style="width:100%; min-width:900px; table-layout:fixed; border-collapse:collapse;">
            <colgroup>
                            <col style="width:28%;">
              <col style="width:9%;">
              <col style="width:11%;">
              <col style="width:10%;">
              <col style="width:14%;">
              <col style="width:14%;">
              <col style="width:14%;">
            </colgroup>
            <thead>
              <tr>
                <th style="text-align:left;">Employee</th>
                <th style="text-align:right;">Days</th>
                <th style="text-align:right;">Hours</th>
                <th style="text-align:right;">OT</th>
                <th style="text-align:right;">Gross</th>
                <th style="text-align:right;">CIS Tax</th>
                <th style="text-align:right;">NET/PAY</th>
              </tr>
            </thead>
            <tbody>
              {''.join(monthly_rows_html)}
            </tbody>
          </table>
        </div>
      </div>
    """



    pie_html, kpi_strip = build_payroll_chart_and_kpis(
        filtered=filtered,
        q=q,
        currency=currency,
        overall_hours=overall_hours,
        overall_gross=overall_gross,
        overall_tax=overall_tax,
        overall_net=overall_net,
        get_employee_display_name=get_employee_display_name,
        money=money,
        safe_float=safe_float,
    )

    summary_rows = []
    for u in sorted(all_users, key=lambda s: s.lower()):
        gross = round(by_user.get(u, {}).get("gross", 0.0), 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)
        hours = round(by_user.get(u, {}).get("hours", 0.0), 2)

        display = get_employee_display_name(u)
        paid, paid_at = _is_paid_for_week(week_start_str, week_end_str, u)

        paid_line = ""
        if paid:
            paid_line = f"<div class='sub' style='margin:2px 0 0 0;'><span class='chip ok'>Paid</span></div>"
            if paid_at:
                paid_line += f"<div class='sub' style='margin:2px 0 0 0;'>Paid at: {escape(paid_at)}</div>"
        else:
            paid_line = "<div class='sub' style='margin:2px 0 0 0;'><span class='chip warn'>Not paid</span></div>"

        mark_paid_btn = ""
        if (not paid) and gross > 0:
            mark_paid_btn = f"""
                  <form method="POST" action="/admin/mark-paid" style="margin:0;">
                    <input type="hidden" name="csrf" value="{escape(csrf)}">
                    <input type="hidden" name="week_start" value="{escape(week_start_str)}">
                    <input type="hidden" name="week_end" value="{escape(week_end_str)}">
                    <input type="hidden" name="user" value="{escape(u)}">
                    <input type="hidden" name="gross" value="{gross}">
                    <input type="hidden" name="tax" value="{tax}">
                    <input type="hidden" name="net" value="{net}">
                    <button class="btnTiny dark" type="submit">Paid</button>
                  </form>
                """

        row_class = "rowHasValue" if gross > 0 else ""

        name_cell = f"""
              <div>
                <div>
                  <div style="font-weight:600;">{escape(display)}</div>
                  <div class="sub" style="margin:2px 0 0 0;">{escape(u)}</div>
                  {paid_line}
                </div>
              </div>
            """

        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    grand_hours = 0.0
    grand_o = 0.0
    grand_gross = 0.0
    grand_tax = 0.0
    grand_net = 0.0

    sheet_rows = []

    for u in sorted(all_users, key=lambda s: get_employee_display_name(s).lower()):
        display = get_employee_display_name(u)
        user_days = week_lookup.get(u, {})

        total_hours = 0.0
        total_o = 0.0
        gross = 0.0

        def show_num(v):
            try:
                vv = float(v)
                return "" if abs(vv) < 0.005 else fmt_hours(vv)
            except Exception:
                return ""

        cells = [f"""
              <td class="payrollEmpCell">
                <span class="emp">{escape(display)}</span>
              </td>
            """]

        for di in range(7):
            d_str = (week_start + timedelta(days=di)).strftime("%Y-%m-%d")
            rec = user_days.get(d_str, {}) if isinstance(user_days, dict) else {}

            cin = ((rec.get("cin", "") if isinstance(rec, dict) else "") or "").strip()
            cout = ((rec.get("cout", "") if isinstance(rec, dict) else "") or "").strip()
            hrs = safe_float((rec.get("hours", "0") if isinstance(rec, dict) else "0"), default=0.0)
            pay = safe_float((rec.get("pay", "0") if isinstance(rec, dict) else "0"), default=0.0)
            o_hours = calc_o_hours(u, d_str, hrs)

            total_o += o_hours
            total_hours += (hrs + o_hours)
            gross += pay

            form_id = f"payroll_{re.sub(r'[^a-zA-Z0-9]+', '_', u)}_{d_str.replace('-', '_')}"
            has_day_value = bool(cin or cout or hrs > 0 or pay > 0)
            day_cls = "payrollDayCellOT" if o_hours > 0 else ""

            if has_day_value:
                hrs_txt = f"{show_num(hrs)}h" if hrs > 0 else "—"
                site_name = str((rec.get("site", "") if isinstance(rec, dict) else "") or "").strip()

                if site_name:
                    site_color = site_text_color(site_name)
                    site_html = f"<div class='payrollDaySiteText' title='{escape(site_name)}' style='color:{site_color};'>{escape(site_name)}</div>"
                else:
                    site_html = "<div class='payrollDaySiteText' style='color:#6f6c85;'>No site</div>"

                day_inner = f"""
                         <div class="payrollDayStack">
                           <div class="payrollDayLine">
                             <input
                               class="payrollTimeInput"
                               type="time"
                               step="60"
                               name="cin"
                               value="{escape(cin[:5])}"
                               form="{form_id}"
                               data-autosave="1">
                           </div>
                           <div class="payrollDayLine">
                             <input
                               class="payrollTimeInput"
                               type="time"
                               step="60"
                               name="cout"
                               value="{escape(cout[:5])}"
                               form="{form_id}"
                               data-autosave="1">
                           </div>
                           <div class="payrollDayHours">{escape(hrs_txt)}</div>
                           {site_html}
                         </div>
                       """
            else:
                day_inner = '<div class="payrollDayEmpty">—</div>'

            cells.append(f"""
                     <td class="payrollDayCell {day_cls}">
                       {day_inner}
                       <form id="{form_id}" method="POST" action="/admin/save-shift" style="display:none;">
      <input type="hidden" name="csrf" value="{escape(csrf)}">
      <input type="hidden" name="user" value="{escape(u)}">
      <input type="hidden" name="date" value="{escape(d_str)}">
    </form>
                     </td>
                   """)

        gross = round(gross, 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)

        paid, _paid_at = _is_paid_for_week(week_start_str, week_end_str, u)

        cells.append(
            f"<td class='num payrollSummaryTotal' style='color:#7c3aed !important; font-weight:900;'>{show_num(total_o)}</td>")
        cells.append(
            f"<td class='num payrollSummaryTotal' style='color:#1d4ed8 !important; font-weight:900;'>{show_num(total_hours)}</td>")
        cells.append(
            f"<td class='num payrollSummaryMoney'>{(escape(currency) + money(gross)) if gross > 0 else ''}</td>")
        cells.append(f"<td class='num payrollSummaryMoney'>{(escape(currency) + money(tax)) if tax > 0 else ''}</td>")

        paid_rec = _get_paid_record_for_week(week_start_str, week_end_str, u)
        paid = bool(paid_rec.get("paid"))
        paid_display_net = round(float(paid_rec.get("display_net", 0.0) or 0.0), 2)
        paid_mode = str(paid_rec.get("payment_mode") or "net").strip().lower()

        pay_form_key = f"{re.sub(r'[^a-zA-Z0-9]+', '_', u)}_{week_start_str.replace('-', '_')}_{week_end_str.replace('-', '_')}"
        pay_week_text = f"{week_start.strftime('%d %b %Y')} – {week_end.strftime('%d %b %Y')}"
        pay_display_name = escape(display)
        net_amount_text = f"{escape(currency)}{money(net)}"
        gross_amount_text = f"{escape(currency)}{money(gross)}"

        if paid:
            paid_label = "Gross Paid" if paid_mode == "gross" else "Paid"
            cells.append(
                f"<td class='num payrollSummaryMoney net paidNetCell' style='width:150px; min-width:150px; white-space:nowrap;'><span class='paidNetBadge'>{escape(currency)}{money(paid_display_net)} · {escape(paid_label)}</span></td>"
            )
        elif gross > 0:
            cells.append(f"""
                     <td class='num payrollSummaryMoney net' style='width:150px; min-width:150px; white-space:nowrap;'>
                       <div style="display:flex; flex-direction:column; gap:4px; align-items:flex-end;">

                         <form id="pay_net_{pay_form_key}" method="POST" action="/admin/mark-paid" class="payCellForm"
      style="margin:0; width:auto; display:flex; justify-content:flex-end;">
  <input type="hidden" name="csrf" value="{escape(csrf)}">
  <input type="hidden" name="week_start" value="{escape(week_start_str)}">
  <input type="hidden" name="week_end" value="{escape(week_end_str)}">
  <input type="hidden" name="user" value="{escape(u)}">
  <input type="hidden" name="gross" value="{gross}">
  <input type="hidden" name="tax" value="{tax}">
  <input type="hidden" name="net" value="{net}">
  <input type="hidden" name="payment_mode" value="net">
  <input type="hidden" name="display_tax" value="{tax}">
  <input type="hidden" name="display_net" value="{net}">
  <button class="confirmPayTrigger"
        type="button"
        data-form-id="pay_net_{pay_form_key}"
        data-pay-kind="net"
        data-pay-type-label="Net payment"
        data-pay-employee="{pay_display_name}"
        data-pay-week="{escape(pay_week_text)}"
        data-pay-amount="{net_amount_text}"
        style="display:grid; grid-template-columns:1fr 34px; align-items:center; gap:4px; width:108px; min-width:108px; height:26px; padding:0 5px; border:1px solid #ecd58a; background:#fff6d8; color:#1f2547; font-size:10px; font-weight:800; white-space:nowrap; cursor:pointer; box-sizing:border-box;">
  <span style="text-align:left; overflow:hidden;">{escape(currency)}{money(net)}</span>
  <span style="display:inline-flex; align-items:center; justify-content:center; width:34px; height:15px; background:#f6e7b3; color:#b45309; font-size:9px; font-weight:800;">Net</span>
</button>
</form>

                         <form id="pay_gross_{pay_form_key}" method="POST" action="/admin/mark-paid" class="payCellForm"
      style="margin:0; width:auto; display:flex; justify-content:flex-end;">
  <input type="hidden" name="csrf" value="{escape(csrf)}">
  <input type="hidden" name="week_start" value="{escape(week_start_str)}">
  <input type="hidden" name="week_end" value="{escape(week_end_str)}">
  <input type="hidden" name="user" value="{escape(u)}">
  <input type="hidden" name="gross" value="{gross}">
  <input type="hidden" name="tax" value="{tax}">
  <input type="hidden" name="net" value="{net}">
  <input type="hidden" name="payment_mode" value="gross">
  <input type="hidden" name="display_tax" value="0">
  <input type="hidden" name="display_net" value="{gross}">
  <button class="confirmPayTrigger"
        type="button"
        data-form-id="pay_gross_{pay_form_key}"
        data-pay-kind="gross"
        data-pay-type-label="Gross payment"
        data-pay-employee="{pay_display_name}"
        data-pay-week="{escape(pay_week_text)}"
        data-pay-amount="{gross_amount_text}"
        style="display:grid; grid-template-columns:1fr 34px; align-items:center; gap:4px; width:108px; min-width:108px; height:26px; padding:0 5px; border:1px solid #5b21b6; background:#6d28d9; color:#fff; font-size:10px; font-weight:800; white-space:nowrap; cursor:pointer; box-sizing:border-box;">
  <span style="text-align:left; overflow:hidden;">{escape(currency)}{money(gross)}</span>
  <span style="display:inline-flex; align-items:center; justify-content:center; width:34px; height:15px; background:rgba(255,255,255,.16); color:#f3e8ff; font-size:8px; font-weight:800;">Gross</span>
</button>
</form>

                       </div>
                     </td>
                   """)
        else:
            cells.append("<td class='num payrollSummaryMoney'></td>")

        grand_o += total_o
        grand_hours += total_hours
        grand_gross += gross
        grand_tax += tax
        grand_net += net

        sheet_rows.append("<tr>" + "".join(cells) + "</tr>")


    sheet_html = "".join(sheet_rows)

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    blocks = []
    for u in sorted(all_users, key=lambda s: s.lower()):
        display = get_employee_display_name(u)
        user_days = week_lookup.get(u, {})

        has_any = False
        for rec in user_days.values():
            if isinstance(rec, dict) and (
                rec.get("cin") or
                rec.get("cout") or
                safe_float(rec.get("hours", "0"), 0.0) > 0 or
                safe_float(rec.get("pay", "0"), 0.0) > 0
            ):
                has_any = True
                break

        if not has_any:
            continue

        wk_hours = 0.0
        wk_gross = 0.0
        wk_overtime_days = 0

        for di in range(7):
            d_str = (week_start + timedelta(days=di)).strftime("%Y-%m-%d")
            rec = user_days.get(d_str)
            if rec and rec.get("hours"):
                h = safe_float(rec.get("hours", "0"), 0.0)
                wk_hours += h
                if calc_o_hours(u, d_str, h) > 0:
                    wk_overtime_days += 1
            if rec and rec.get("pay"):
                wk_gross += safe_float(rec.get("pay", "0"), 0.0)

        wk_hours = round(wk_hours, 2)
        wk_gross = round(wk_gross, 2)
        wk_tax = round(wk_gross * tax_rate, 2)
        wk_net = round(wk_gross - wk_tax, 2)

        paid, paid_at = _is_paid_for_week(week_start_str, week_end_str, u)

        rows_html = []
        for di in range(7):
            d_dt = week_start + timedelta(days=di)
            d_str = d_dt.strftime("%Y-%m-%d")
            d_display = d_dt.strftime("%y-%m-%d")
            rec = user_days.get(d_str)

            cin = rec["cin"] if rec else ""
            cout = rec["cout"] if rec else ""
            hrs = rec["hours"] if rec else ""
            pay = rec["pay"] if rec else ""

            h_val = safe_float(hrs, 0.0) if str(hrs).strip() != "" else 0.0
            overtime_row_class = "overtimeRow" if (str(hrs).strip() != "" and calc_o_hours(u, d_str, h_val) > 0) else ""

            if rec:
                if cout.strip() == "" and cin.strip() != "":
                    status_html = "<span class='chip bad'>Open</span>"
                elif cin.strip() and cout.strip():
                    status_html = "<span class='chip ok'>Complete</span>"
                else:
                    status_html = "<span class='chip warn'>Partial</span>"
            else:
                status_html = "<span class='chip'>Missing</span>"

            ot_badge = ""
            if overtime_row_class:
                ot_badge = "<span class='overtimeChip'>Overtime</span>"

            has_row = bool(
                rec and (
                    str(cin).strip() or
                    str(cout).strip() or
                    str(hrs).strip() or
                    str(pay).strip()
                )
            )

            cin_txt = ""
            if has_row and str(cin).strip() not in ("", "--:--", "--:--:--"):
                cin_txt = str(cin).strip()[:5]

            cout_txt = ""
            if has_row and str(cout).strip() not in ("", "--:--", "--:--:--"):
                cout_txt = str(cout).strip()[:5]

            hrs_txt = ""
            if has_row:
                hrs_txt = fmt_hours(hrs)

            pay_txt = ""
            if has_row:
                pay_txt = money(safe_float(pay, 0.0))

            rows_html.append(f"""
                  <tr class="{overtime_row_class}">
                    <td><b>{day_names[di]}</b></td>
                    <td style="text-align:center;">{escape(d_display)}</td>
                    <td style="font-weight:700; text-align:center;">{escape(cin_txt)}</td>
                    <td style="font-weight:700; text-align:center;">{escape(cout_txt)}</td>
                    <td class="num" style="font-weight:700;">{escape(hrs_txt)}</td>
                    <td class="num" style="font-weight:700;">{escape(pay_txt)}</td>
                    <td class="num" style="font-weight:800; color:rgba(15,23,42,.92);">{escape(money(round(safe_float(pay, 0.0) * (1 - tax_rate), 2))) if has_row else ""}</td>
                  </tr>
                """)

        blocks.append(
            build_payroll_employee_card(
                display=display,
                rows_html=rows_html,
                wk_hours=wk_hours,
                wk_gross=wk_gross,
                wk_tax=wk_tax,
                wk_net=wk_net,
                paid=paid,
                paid_at=paid_at,
                currency=currency,
                money=money,
            )
        )

    last_updated = datetime.now(TZ).strftime("%d %b %Y • %H:%M")
    csv_url = "/admin/payroll-report.csv"
    if request.query_string:
        csv_url += "?" + request.query_string.decode("utf-8", "ignore")

    range_detail_html = ""

    if use_range and range_start and range_end:
        detail_rows = []

        for r in rows[1:]:
            if len(r) <= COL_PAY or len(r) <= COL_USER or len(r) <= COL_DATE:
                continue

            user = (r[COL_USER] or "").strip()
            d_str = (r[COL_DATE] or "").strip()
            if not user or not d_str:
                continue

            if wp_idx is not None:
                row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
                if row_wp not in allowed_wps:
                    continue
            else:
                if not user_in_same_workplace(user):
                    continue

            display_name = get_employee_display_name(user)
            if q and q not in user.lower() and q not in display_name.lower():
                continue

            try:
                d_obj = date.fromisoformat(d_str)
            except Exception:
                continue

            if d_obj < range_start or d_obj > range_end:
                continue

            cin = ((r[COL_IN] if len(r) > COL_IN else "") or "").strip()
            cout = ((r[COL_OUT] if len(r) > COL_OUT else "") or "").strip()
            hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
            gross = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

            if hrs <= 0 and gross <= 0 and not cin and not cout:
                continue

            tax = round(gross * tax_rate, 2)
            net = round(gross - tax, 2)

            detail_rows.append({
                "employee": display_name,
                "date_obj": d_obj,
                "date": d_obj.strftime("%d/%m/%Y"),
                "day": d_obj.strftime("%a"),
                "clock_in": cin[:5] if cin else "",
                "clock_out": cout[:5] if cout else "",
                "hours": hrs,
                "gross": gross,
                "tax": tax,
                "net": net,
            })

        detail_rows.sort(key=lambda x: (x["employee"].lower(), x["date_obj"]))

        if detail_rows:
            body_html = []
            for item in detail_rows:
                body_html.append(f"""
                      <tr>
                        <td>{escape(item['employee'])}</td>
                        <td>{escape(item['day'])}</td>
                        <td>{escape(item['date'])}</td>
                        <td style="text-align:center;">{escape(item['clock_in'])}</td>
                        <td style="text-align:center;">{escape(item['clock_out'])}</td>
                        <td class="num">{escape(fmt_hours(item['hours']))}</td>
                        <td class="num">{escape(currency)}{escape(money(item['gross']))}</td>
                        <td class="num">{escape(currency)}{escape(money(item['tax']))}</td>
                        <td class="num">{escape(currency)}{escape(money(item['net']))}</td>
                      </tr>
                    """)

            range_detail_html = f"""
                  <div class="card plainSection" style="margin-top:12px; padding:16px;">
                    <div class="sectionHead">
                      <div class="sectionHeadLeft">
                        <div class="sectionIcon">{_svg_clipboard()}</div>
                        <div>
                          <h2 style="margin:0;">Logged days in selected range</h2>
                          <p class="sub" style="margin:4px 0 0 0;">
                            {escape(range_start.strftime("%d %b %Y"))} – {escape(range_end.strftime("%d %b %Y"))}
                          </p>
                        </div>
                      </div>
                    </div>

                    <div class="tablewrap" style="margin-top:12px;">
                      <table class="rangeDetailTable">
                        <thead>
                          <tr>
                            <th>Employee</th>
                            <th>Day</th>
                            <th>Date</th>
                            <th>Clock In</th>
                            <th>Clock Out</th>
                            <th class="num">Hours</th>
                            <th class="num">Gross</th>
                            <th class="num">CIS Tax</th>
                            <th class="num">Net</th>
                          </tr>
                        </thead>
                        <tbody>
                          {''.join(body_html)}
                        </tbody>
                      </table>
                    </div>
                  </div>
                """
        else:
            range_detail_html = f"""
                  <div class="card plainSection" style="margin-top:12px; padding:16px;">
                    <div class="sectionHead">
                      <div class="sectionHeadLeft">
                        <div class="sectionIcon">{_svg_clipboard()}</div>
                        <div>
                          <h2 style="margin:0;">Logged days in selected range</h2>
                          <p class="sub" style="margin:4px 0 0 0;">
                            {escape(range_start.strftime("%d %b %Y"))} – {escape(range_end.strftime("%d %b %Y"))}
                          </p>
                        </div>
                      </div>
                    </div>
                    <p class="sub" style="margin-top:12px;">No logged days found for this range.</p>
                  </div>
                """

    payroll_refresh_url = url_for(
        "admin_payroll",
        q=q,
        **{
            "from": date_from,
            "to": date_to,
            "wk": wk_offset,
            "ym": ym,
        }
    )

    back_href = f"/admin/payroll?wk={wk_offset}" if use_range else "/admin"

    pay_confirm_modal_html = """
      <div id="payConfirmBackdrop" style="display:none; position:fixed; inset:0; background:rgba(15,23,42,.55); z-index:1200;"></div>

      <div id="payConfirmModal"
           style="display:none; position:fixed; left:50%; top:50%; transform:translate(-50%, -50%);
                  width:min(460px, calc(100vw - 32px)); background:#fff; border:1px solid rgba(15,23,42,.14);
                  box-shadow:0 24px 60px rgba(15,23,42,.28); z-index:1201; padding:20px; border-radius:0;">
        <div style="font-size:20px; font-weight:800; color:#1f2547;">Confirm payment</div>
        <div class="sub" style="margin-top:6px;">This action cannot be undone.</div>

        <div style="margin-top:16px; display:grid; gap:10px;">
          <div>
            <div class="sub">Employee</div>
            <div id="payConfirmEmployee" style="font-weight:700; color:#1f2547;"></div>
          </div>

          <div>
            <div class="sub">Week</div>
            <div id="payConfirmWeek" style="font-weight:700; color:#1f2547;"></div>
          </div>

          <div>
            <div class="sub">Payment type</div>
            <div id="payConfirmType" style="font-weight:700; color:#1f2547;"></div>
          </div>

          <div>
            <div class="sub">Amount</div>
            <div id="payConfirmAmount" style="font-weight:800; color:#1f2547; font-size:20px;"></div>
          </div>
        </div>

        <label style="display:flex; align-items:flex-start; gap:10px; margin-top:16px; padding:12px;
                      background:#f8f7ff; border:1px solid rgba(109,40,217,.12);">
          <input type="checkbox" id="payConfirmCheck" style="margin-top:2px;">
          <span style="color:#1f2547;">I understand this payment action cannot be undone.</span>
        </label>

        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:16px;">
          <button type="button" id="payConfirmCancel"
                  style="height:42px; padding:0 16px; border:1px solid rgba(15,23,42,.14);
                         background:#fff; color:#1f2547; font-weight:700; cursor:pointer;">
            Cancel
          </button>

          <button type="button" id="payConfirmSubmit" disabled
                  style="height:42px; padding:0 18px; border:1px solid rgba(68,130,195,.18);
                         background:#cbd5e1; color:#fff; font-weight:800; cursor:not-allowed;">
            Confirm payment
          </button>
        </div>
      </div>
    """

    content = f"""
          <div class="payrollMenuBackdrop" id="payrollMenuBackdrop"></div>

          <div class="headerTop">
            <div>
              <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                <button type="button" class="payrollMenuToggle" id="payrollMenuToggle" aria-label="Toggle menu"></button>
                <div>
                  <h1>Payroll Report</h1>
                  <p class="sub"> Updated {escape(last_updated)} </p>
                </div>
              </div>
            </div>
            <div class="badge admin">ADMIN</div>
          </div>

          {admin_back_link(back_href)}

          {f"""
          <div id="payrollLiveRegion"
               data-refresh-url="{escape(payroll_refresh_url)}"
               data-refresh-ms="10000">
            <div class="payrollWrap" style="margin-top:12px;">
      <table class="payrollSheet">
        <thead>
            <tr>
        <th>Employee</th>
        <th class="payrollDayCell">Mon</th>
        <th class="payrollDayCell">Tue</th>
        <th class="payrollDayCell">Wed</th>
        <th class="payrollDayCell">Thu</th>
        <th class="payrollDayCell">Fri</th>
        <th class="payrollDayCell">Sat</th>
        <th class="payrollDayCell">Sun</th>
        <th class="payrollSummaryTotal">O</th>
        <th class="payrollSummaryTotal">Hours</th>
        <th class="payrollSummaryMoney">Gross</th>
        <th class="payrollSummaryMoney" style="width:110px; min-width:110px; text-align:right;">CIS Tax</th>
        <th class="payrollSummaryMoney" style="width:150px; min-width:150px; text-align:right;">NET/PAY</th>
      </tr>
    </thead>
        <tbody>
          {sheet_html}
        </tbody>
      </table>

      <div style="padding:14px 18px; border-top:1px solid rgba(109,40,217,.10); background:linear-gradient(180deg,#ffffff,#faf8ff);">
        {payroll_week_bar_html}
      </div>
    </div>

    <div class="payrollTopGrid" style="margin-top:12px;">
            <div class="card payrollFiltersCard">
              <form method="GET">
                <div>
                  <label class="sub">Employee</label>
                  <select class="input" name="q">
                    {''.join(employee_options)}
                  </select>
                </div>

                <div style="margin-top:10px;">
                  <label class="sub">Date range</label>
                  <div class="row2 payrollDateRow">
                    <div>
                      <input class="input" type="date" name="from" value="{escape(date_from)}">
                    </div>
                    <div>
                      <input class="input" type="date" name="to" value="{escape(date_to)}">
                    </div>
                  </div>
                </div>

                <input type="hidden" name="wk" value="{wk_offset}">
                <button class="btnSoft" type="submit" style="margin-top:12px;">Apply</button>
              </form>

              {kpi_strip}

              <div style="margin-top:10px;">
                <a href="{csv_url}">
                  <button class="btnTiny csvDownload" type="button">Download CSV</button>
                </a>
              </div>
            </div>

            <div class="payrollChartCard plainSection">
              <div class="sectionHead">
                <div class="sectionHeadLeft">
                  <div class="sectionIcon">{_svg_chart()}</div>
                  <div>
                    <h2 style="margin:0;">Payroll Split</h2>
                    <p class="sub" style="margin:4px 0 0 0;">Gross by employee for current filters.</p>
                  </div>
                </div>
              </div>

              <div class="payrollPieSection">
                {pie_html}
              </div>
            </div>
          
                    </div>
          </div>
          
          """ if not use_range else f"""
          <div class="payrollTopGrid">
            <div class="card payrollFiltersCard">
              <form method="GET">
                <div>
                  <label class="sub">Employee</label>
                  <select class="input" name="q">
                    {''.join(employee_options)}
                  </select>
                </div>

                <div style="margin-top:10px;">
                  <label class="sub">Date range</label>
                  <div class="row2 payrollDateRow">
                    <div>
                      <input class="input" type="date" name="from" value="{escape(date_from)}">
                    </div>
                    <div>
                      <input class="input" type="date" name="to" value="{escape(date_to)}">
                    </div>
                  </div>
                </div>

                <input type="hidden" name="wk" value="{wk_offset}">
                <button class="btnSoft" type="submit" style="margin-top:12px;">Apply</button>
              </form>

              {kpi_strip}

              <div style="margin-top:10px;">
                <a href="{csv_url}">
                  <button class="btnTiny csvDownload" type="button">Download CSV</button>
                </a>
              </div>
            </div>

            <div class="payrollChartCard plainSection">
              <div class="sectionHead">
                <div class="sectionHeadLeft">
                  <div class="sectionIcon">{_svg_chart()}</div>
                  <div>
                    <h2 style="margin:0;">Payroll Split</h2>
                    <p class="sub" style="margin:4px 0 0 0;">Gross by employee for current filters.</p>
                  </div>
                </div>
              </div>

              <div class="payrollPieSection">
                {pie_html}
              </div>
            </div>
          </div>

                {range_detail_html}
                
                    """}

                              {monthly_filter_html if not use_range else ""}
          {''.join(blocks) if not use_range else ""}
          {pay_confirm_modal_html}

    <script>
    (function(){{
      const region = document.getElementById("payrollLiveRegion");
      if (!region) return;

      const refreshUrl = region.getAttribute("data-refresh-url");
      const refreshMs = parseInt(region.getAttribute("data-refresh-ms") || "10000", 10);

      let busy = false;
      let pendingAutosave = 0;
      const timers = new WeakMap();

      function syncPendingAutosaveFlag(){{
        region.setAttribute("data-pending-autosave", pendingAutosave > 0 ? "1" : "0");
      }}

      function clearTimer(input){{
        if (timers.has(input)) {{
          clearTimeout(timers.get(input));
          timers.delete(input);
          pendingAutosave = Math.max(0, pendingAutosave - 1);
          syncPendingAutosaveFlag();
        }}
      }}

      function submitLater(input, delay){{
        const formId = input.getAttribute("form");
        if (!formId) return;

        const form = document.getElementById(formId);
        if (!form) return;

        clearTimer(input);

        pendingAutosave += 1;
        syncPendingAutosaveFlag();

        const t = setTimeout(function(){{
          timers.delete(input);
          pendingAutosave = Math.max(0, pendingAutosave - 1);
          syncPendingAutosaveFlag();

          if (!document.body.contains(input)) return;
          if (document.activeElement === input) return;

          form.submit();
        }}, delay);

        timers.set(input, t);
      }}

      function bindRowSelection(root){{
        const tbody = root.querySelector(".payrollWrap .payrollSheet tbody");
        if (!tbody) return;

        let selected = null;

        tbody.querySelectorAll("tr").forEach(function(tr){{
          if (tr.dataset.rowBound === "1") return;
          tr.dataset.rowBound = "1";

          tr.style.cursor = "pointer";

          tr.addEventListener("click", function(e){{
            if (e.target.closest("input, button, form, a, select")) return;

            if (selected === tr) {{
              tr.classList.remove("is-selected");
              selected = null;
              return;
            }}

            if (selected) selected.classList.remove("is-selected");
            tr.classList.add("is-selected");
            selected = tr;
          }});
        }});
      }}

      function bindAutosave(root){{
        root.querySelectorAll('.payrollTimeInput[data-autosave="1"]').forEach(function(input){{
          if (input.dataset.autosaveBound === "1") return;
          input.dataset.autosaveBound = "1";

          input.addEventListener("focus", function(){{
            clearTimer(input);
          }});

          input.addEventListener("input", function(){{
            clearTimer(input);
          }});

          input.addEventListener("change", function(){{
            clearTimer(input);
          }});

          input.addEventListener("keydown", function(e){{
            if (e.key === "Enter") {{
              e.preventDefault();
              submitLater(input, 80);
            }}
          }});

          input.addEventListener("blur", function(){{
            const v = (input.value || "").trim();
            if (v === "" || v.length >= 4) {{
              submitLater(input, 120);
            }}
          }});
        }});
      }}

      function bindPayrollRegion(root){{
        bindRowSelection(root);
        bindAutosave(root);
      }}

           function hasActiveEditing(){{
        const active = document.activeElement;
        if (!active) return false;
        if (!region.contains(active)) return false;

        if (active.matches("input, select, textarea")) return true;
        if (active.closest("form")) return true;

        return false;
      }}

      async function refreshPayrollRegion(){{
        if (!refreshUrl) return;
        if (busy) return;
        if (document.hidden) return;
        if (hasActiveEditing()) return;
        if (region.getAttribute("data-pending-autosave") === "1") return;

        busy = true;

        const currentWrap = region.querySelector(".payrollWrap");
        const scrollLeft = currentWrap ? currentWrap.scrollLeft : 0;
        const scrollTop = currentWrap ? currentWrap.scrollTop : 0;

        try {{
          const res = await fetch(refreshUrl, {{
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
            headers: {{
              "X-Requested-With": "XMLHttpRequest"
            }}
          }});

          if (!res.ok) return;

          const html = await res.text();
          const doc = new DOMParser().parseFromString(html, "text/html");
          const incoming = doc.getElementById("payrollLiveRegion");
          if (!incoming) return;

          region.innerHTML = incoming.innerHTML;
          syncPendingAutosaveFlag();

          const newWrap = region.querySelector(".payrollWrap");
          if (newWrap) {{
            newWrap.scrollLeft = scrollLeft;
            newWrap.scrollTop = scrollTop;
          }}

          bindPayrollRegion(region);
        }} catch (err) {{
          console.error("Payroll live refresh failed:", err);
        }} finally {{
          busy = false;
        }}
      }}

      bindPayrollRegion(region);
      syncPendingAutosaveFlag();

      setInterval(refreshPayrollRegion, refreshMs);

      document.addEventListener("visibilitychange", function(){{
        if (!document.hidden) {{
          refreshPayrollRegion();
        }}
      }});
    }})();
    </script>

    <script>
    (function(){{
      const shell = document.querySelector(".shell.payrollShell");
      const btn = document.getElementById("payrollMenuToggle");
      const backdrop = document.getElementById("payrollMenuBackdrop");

      if (!shell || !btn) return;

      function closeMenu(){{
        shell.classList.remove("payrollMenuOpen");
      }}

      btn.addEventListener("click", function(e){{
        e.preventDefault();
        e.stopPropagation();
        shell.classList.toggle("payrollMenuOpen");
      }});

      if (backdrop) {{
        backdrop.addEventListener("click", closeMenu);
      }}

      document.addEventListener("keydown", function(e){{
        if (e.key === "Escape") closeMenu();
      }});
    }})();
    </script>
        <script>
    (function(){{
      const backdrop = document.getElementById("payConfirmBackdrop");
      const modal = document.getElementById("payConfirmModal");
      const employeeEl = document.getElementById("payConfirmEmployee");
      const weekEl = document.getElementById("payConfirmWeek");
      const typeEl = document.getElementById("payConfirmType");
      const amountEl = document.getElementById("payConfirmAmount");
      const checkEl = document.getElementById("payConfirmCheck");
      const cancelBtn = document.getElementById("payConfirmCancel");
      const submitBtn = document.getElementById("payConfirmSubmit");

      if (!backdrop || !modal || !employeeEl || !weekEl || !typeEl || !amountEl || !checkEl || !cancelBtn || !submitBtn) return;

      let activeForm = null;
      let activeTrigger = null;

      function closePayModal(){{
        modal.style.display = "none";
        backdrop.style.display = "none";
        checkEl.checked = false;
        submitBtn.disabled = true;
        submitBtn.style.cursor = "not-allowed";
        submitBtn.style.background = "#cbd5e1";
        submitBtn.textContent = "Confirm payment";
        activeForm = null;
        activeTrigger = null;
      }}

      function openPayModal(trigger){{
        const formId = trigger.getAttribute("data-form-id") || "";
        const form = document.getElementById(formId);
        if (!form) return;

        activeForm = form;
        activeTrigger = trigger;

        const payKind = trigger.getAttribute("data-pay-kind") || "net";
        const payTypeLabel = trigger.getAttribute("data-pay-type-label") || "Payment";
        const employee = trigger.getAttribute("data-pay-employee") || "";
        const weekText = trigger.getAttribute("data-pay-week") || "";
        const amountText = trigger.getAttribute("data-pay-amount") || "";

        employeeEl.textContent = employee;
        weekEl.textContent = weekText;
        typeEl.textContent = payTypeLabel;
        amountEl.textContent = amountText;

        checkEl.checked = false;
        submitBtn.disabled = true;
        submitBtn.style.cursor = "not-allowed";

        if (payKind === "gross") {{
          submitBtn.textContent = "Confirm Gross Payment";
          submitBtn.style.background = "#6d28d9";
        }} else {{
          submitBtn.textContent = "Confirm Net Payment";
          submitBtn.style.background = "#d97706";
        }}

        modal.style.display = "block";
        backdrop.style.display = "block";
      }}

      document.addEventListener("click", function(e){{
        const trigger = e.target.closest(".confirmPayTrigger");
        if (trigger) {{
          e.preventDefault();
          openPayModal(trigger);
          return;
        }}

        if (e.target === backdrop || e.target === cancelBtn) {{
          e.preventDefault();
          closePayModal();
        }}
      }});

      checkEl.addEventListener("change", function(){{
        submitBtn.disabled = !checkEl.checked;
        submitBtn.style.cursor = checkEl.checked ? "pointer" : "not-allowed";
      }});

      submitBtn.addEventListener("click", function(){{
        if (!activeForm || !checkEl.checked) return;

        if (activeTrigger) {{
          activeTrigger.disabled = true;
          activeTrigger.style.opacity = "0.65";
          activeTrigger.style.cursor = "not-allowed";
        }}

        closePayModal();
        activeForm.submit();
      }});

      document.addEventListener("keydown", function(e){{
        if (e.key === "Escape") {{
          closePayModal();
        }}
      }});
    }})();
    </script>
    
        """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell(
            active="admin",
            role=session.get("role", "admin"),
            content_html=content,
            shell_class="payrollShell"
        )
    )