def home_impl(core):
    require_login = core["require_login"]
    session = core["session"]
    get_employee_display_name = core["get_employee_display_name"]
    get_company_settings = core["get_company_settings"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    get_workhours_rows = core["get_workhours_rows"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    timedelta = core["timedelta"]
    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    COL_PAY = core["COL_PAY"]
    user_in_same_workplace = core["user_in_same_workplace"]
    safe_float = core["safe_float"]
    find_open_shift = core["find_open_shift"]
    employees_sheet = core["employees_sheet"]
    _get_open_shifts = core["_get_open_shifts"]
    _get_active_locations = core["_get_active_locations"]
    math = core["math"]
    money = core["money"]
    fmt_hours = core["fmt_hours"]
    escape = core["escape"]
    role_label = core["role_label"]
    _svg_grid = core["_svg_grid"]
    _svg_clock = core["_svg_clock"]
    _svg_clipboard = core["_svg_clipboard"]
    _icon_admin = core["_icon_admin"]
    _svg_shield = core["_svg_shield"]
    _icon_workplaces = core["_icon_workplaces"]
    _icon_clock = core["_icon_clock"]
    _icon_timelogs = core["_icon_timelogs"]
    _icon_timesheets = core["_icon_timesheets"]
    _icon_payments = core["_icon_payments"]
    _icon_work_progress = core["_icon_work_progress"]
    _icon_starter_form = core["_icon_starter_form"]
    _icon_profile = core["_icon_profile"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    render_template_string = core["render_template_string"]
    request = core["request"]
    url_for = core["url_for"]
    json_mod = core["json"]

    get_payroll_rows = core.get("get_payroll_rows")
    _list_employee_records_for_workplace = core.get("_list_employee_records_for_workplace")
    AuditLog = core.get("AuditLog")
    WorkHour = core.get("WorkHour")
    DB_MIGRATION_MODE = core.get("DB_MIGRATION_MODE", False)

    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")


    display_name = get_employee_display_name(username)
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")

    now = datetime.now(TZ)
    today = now.date()
    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    monday = today - timedelta(days=today.weekday())

    def week_key_for_n(n: int):
        d2 = monday - timedelta(days=7 * n)
        yy, ww, _ = d2.isocalendar()
        return yy, ww

    dashboard_weeks = 8
    chart_window = 5

    try:
        chart_offset = max(0, int((request.args.get("chart") or "0").strip()))
    except Exception:
        chart_offset = 0

    week_keys = [week_key_for_n(i) for i in range(dashboard_weeks - 1, -1, -1)]
    week_labels = [str(k[1]) for k in week_keys]
    weekly_gross = [0.0] * dashboard_weeks

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if len(r) <= COL_USER:
            continue
        row_user = (r[COL_USER] or "").strip()

        # Employees should see ONLY their own totals (Admin can see whole workplace)
        if role not in ("admin", "master_admin") and row_user != username:
            continue

        # Workplace filter (prefer WorkHours row Workplace_ID)
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            # Backward compat if WorkHours has no Workplace_ID column
            if not user_in_same_workplace(row_user):
                continue
        if not r[COL_PAY]:
            continue
        try:
            d = datetime.strptime(r[COL_DATE], "%Y-%m-%d").date()
            yy, ww, _ = d.isocalendar()
        except Exception:
            continue
        for idx, (yy2, ww2) in enumerate(week_keys):
            if yy == yy2 and ww == ww2:
                weekly_gross[idx] += safe_float(r[COL_PAY], 0.0)

    max_chart_offset = max(0, len(week_labels) - chart_window)
    if chart_offset > max_chart_offset:
        chart_offset = max_chart_offset

    end_idx = len(week_labels) - chart_offset
    start_idx = max(0, end_idx - chart_window)

    chart_week_labels = week_labels[start_idx:end_idx]
    chart_weekly_gross = weekly_gross[start_idx:end_idx]

    max_g = max(chart_weekly_gross) if chart_weekly_gross else 0.0
    max_g = max(max_g, 1.0)

    prev_gross = round(chart_weekly_gross[-2], 2) if len(chart_weekly_gross) >= 2 else 0.0
    curr_gross = round(chart_weekly_gross[-1], 2) if chart_weekly_gross else 0.0

    admin_item = ""
    if role in ("admin", "master_admin"):
        admin_item = f"""
                <a class="menuItem nav-admin" href="/admin">
                  <div class="menuLeft"><div class="icoBox">{_svg_shield()}</div><div class="menuText">Admin</div></div>
                  <div class="chev">›</div>
                </a>
                """

    current_sessions_item = ""
    workplaces_item = ""
    if role == "master_admin":
        current_sessions_item = f"""
            <a class="menuItem nav-current-sessions" href="/admin/current-sessions">
              <div class="menuLeft"><div class="icoBox">{_icon_admin(22)}</div><div class="menuText">Current Sessions</div></div>
              <div class="chev">›</div>
            </a>
            """

        workplaces_item = f"""
            <a class="menuItem nav-home" href="/admin/workplaces">
              <div class="menuLeft"><div class="icoBox">{_icon_workplaces(22)}</div><div class="menuText">Workplaces</div></div>
              <div class="chev">›</div>
            </a>
            """


    show_employee_col = role in ("admin", "master_admin")

    recent_rows = []
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if len(r) <= COL_USER:
            continue

        row_user = (r[COL_USER] or "").strip()

        if role not in ("admin", "master_admin") and row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(row_user):
                continue

        cin = (r[COL_IN] if len(r) > COL_IN else "") or ""
        cout = (r[COL_OUT] if len(r) > COL_OUT else "") or ""
        hours = (r[COL_HOURS] if len(r) > COL_HOURS else "") or ""
        pay = (r[COL_PAY] if len(r) > COL_PAY else "") or ""

        if cin and not cout:
            status = "Live"
        elif cin and cout:
            status = "Complete"
        elif cin or cout or hours or pay:
            status = "Partial"
        else:
            status = "Blank"

        recent_rows.append({
            "user": row_user,
            "date": (r[COL_DATE] if len(r) > COL_DATE else "") or "",
            "cin": cin,
            "cout": cout,
            "hours": hours,
            "pay": pay,
            "status": status,
        })

    recent_rows = sorted(
        recent_rows,
        key=lambda x: ((x["date"] or ""), (x["cin"] or ""), (x["user"] or "")),
        reverse=True,
    )[:5]

    if recent_rows:
        header_employee = "<th style='width:18%;'>Employee</th>" if show_employee_col else ""
        body_rows = ""

        for rr in recent_rows:
            employee_td = f"<td style='width:18%;'>{escape(get_employee_display_name(rr['user']))}</td>" if show_employee_col else ""

            body_rows += f"""
              <tr>
                {employee_td}
                <td style="width:18%; text-align:center;">{escape(rr['date'])}</td>
                <td style="width:12%; text-align:center;">{escape((rr['cin'] or '')[:5])}</td>
                <td style="width:12%; text-align:center;">{escape((rr['cout'] or '')[:5])}</td>
                <td class="num" style="width:14%; text-align:center;">{escape(fmt_hours(rr['hours']))}</td>
                <td style="width:14%; text-align:center;">{escape(rr['status'])}</td>
              </tr>
            """

            activity_html = f"""
                  <div class="tablewrap">
                    <table class="timeLogsTable logActivitiesPreviewTable" style="width:100%; min-width:0; table-layout:fixed;">
                      <thead>
                        <tr>
                          {header_employee}
                          <th style="width:18%;">Date</th>
                          <th style="width:12%; text-align:center;">In</th>
                          <th style="width:12%; text-align:center;">Out</th>
                          <th class="num" style="width:14%;">Hours</th>
                          <th style="width:14%; text-align:center;">Status</th>
                        </tr>
                      </thead>
                  <tbody>
                    {body_rows}
                  </tbody>
                </table>
              </div>
            """
    else:
        activity_html = "<div class='activityEmpty'>No log activity yet.</div>"

    today_hours = 0.0
    today_pay = 0.0
    week_hours = 0.0
    week_pay = 0.0
    week_days = set()
    completed_shift_today = False

    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if len(r) <= COL_USER:
            continue

        row_user = (r[COL_USER] or "").strip()

        if row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(row_user):
                continue

        d_str = (r[COL_DATE] if len(r) > COL_DATE else "") or ""
        h_val = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        p_val = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        if d_str == today.strftime("%Y-%m-%d"):
            today_hours += h_val
            today_pay += p_val

            today_clock_in = (r[COL_IN] if len(r) > COL_IN else "") or ""
            today_clock_out = (r[COL_OUT] if len(r) > COL_OUT else "") or ""

            if today_clock_in.strip() and today_clock_out.strip():
                completed_shift_today = True

        try:
            d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
            if d_obj >= monday:
                week_hours += h_val
                week_pay += p_val
                if h_val > 0:
                    week_days.add(d_str)
        except Exception:
            pass

    latest_user_date = None
    latest_user_open = False

    for r in rows[1:]:
        if len(r) <= COL_OUT or len(r) <= COL_USER or len(r) <= COL_DATE:
            continue

        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(row_user):
                continue

        d_str = (r[COL_DATE] or "").strip()
        if not d_str:
            continue

        try:
            d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            continue

        row_has_in = bool((r[COL_IN] or "").strip())
        row_has_out = bool((r[COL_OUT] or "").strip())
        row_is_open = row_has_in and not row_has_out

        if latest_user_date is None or d_obj >= latest_user_date:
            latest_user_date = d_obj
            latest_user_open = row_is_open

    is_clocked_in = latest_user_open
    status_text = "Clocked In" if is_clocked_in else "Clocked Out"
    status_class = "ok" if is_clocked_in else "warn"

    dashboard_active_start_iso = ""
    dashboard_active_start_label = ""
    dashboard_open_shift = find_open_shift(rows, username)
    if dashboard_open_shift:
        _, d, t = dashboard_open_shift
        try:
            start_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
            dashboard_active_start_iso = start_dt.isoformat()
            dashboard_active_start_label = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    # Current site card: shows where the logged-in user is currently clocked in.
    # DB first, sheet fallback. This fixes Manual Clock-In with selected site.
    current_site_name = ""
    current_site_date = ""
    current_site_time = ""

    if DB_MIGRATION_MODE and WorkHour is not None:
        try:
            db_open_shift = (
                WorkHour.query
                .filter(
                    WorkHour.employee_email == username,
                    WorkHour.clock_out.is_(None),
                )
                .order_by(WorkHour.date.desc(), WorkHour.id.desc())
                .first()
            )

            if db_open_shift:
                rec_wp = str(
                    getattr(db_open_shift, "workplace_id", "")
                    or getattr(db_open_shift, "workplace", "")
                    or ""
                ).strip() or "default"

                if rec_wp in allowed_wps:
                    current_site_name = str(
                        getattr(db_open_shift, "in_site", "")
                        or getattr(db_open_shift, "out_site", "")
                        or ""
                    ).strip()

                    rec_date = getattr(db_open_shift, "date", None)
                    rec_clock_in = getattr(db_open_shift, "clock_in", None)

                    current_site_date = rec_date.isoformat() if rec_date else ""
                    current_site_time = rec_clock_in.strftime("%H:%M:%S") if rec_clock_in else ""
        except Exception:
            current_site_name = ""

    if not current_site_name:
        header_lookup = {}
        for i, h in enumerate(headers or []):
            key = str(h or "").strip().lower().replace("_", "").replace(" ", "")
            if key:
                header_lookup[key] = i

        site_idx_candidates = []
        for site_col_name in (
            "insite",
            "outsite",
            "site",
            "clockinsite",
            "location",
            "sitename",
            "insitename",
        ):
            if site_col_name in header_lookup:
                site_idx_candidates.append(header_lookup[site_col_name])

        for r in rows[1:]:
            if len(r) <= max(COL_USER, COL_DATE, COL_IN, COL_OUT):
                continue

            row_user = (r[COL_USER] or "").strip()
            if row_user != username:
                continue

            if wp_idx is not None:
                row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
                if row_wp not in allowed_wps:
                    continue
            else:
                if not user_in_same_workplace(row_user):
                    continue

            d_str = (r[COL_DATE] if len(r) > COL_DATE else "").strip()
            cin = (r[COL_IN] if len(r) > COL_IN else "").strip()
            cout = (r[COL_OUT] if len(r) > COL_OUT else "").strip()

            if not cin or cout:
                continue

            row_site_name = ""
            for site_idx in site_idx_candidates:
                if site_idx < len(r):
                    row_site_name = str(r[site_idx] or "").strip()
                    if row_site_name:
                        break

            if not current_site_date or (d_str, cin) >= (current_site_date, current_site_time):
                current_site_date = d_str
                current_site_time = cin
                current_site_name = row_site_name

        if dashboard_active_start_iso:
            dashboard_site_label = current_site_name or "Site missing"
            dashboard_site_sub = (
                f"Started {dashboard_active_start_label[-8:-3]}"
                if dashboard_active_start_label
                else "Clocked in"
            )
        else:
            dashboard_site_label = "search..."
            dashboard_site_sub = "Please wait"

    if dashboard_active_start_iso:
        dashboard_status_html = f"""
              <div class="dashboardLiveClockWrap">
                <a href="/clock" class="statusLink" title="Open clock page">
                  <span class="chip ok">Clocked In</span>
                </a>
                <div class="dashboardLiveTimer" id="dashboardLiveTimer">00:00:00</div>
                <div class="dashboardLiveHint">Started at {escape(dashboard_active_start_label)}</div>
              </div>
              <script>
                (function() {{
                  const startIso = "{escape(dashboard_active_start_iso)}";
                  const start = new Date(startIso);
                  const el = document.getElementById("dashboardLiveTimer");
                  function pad(n) {{ return String(n).padStart(2, "0"); }}
                  function tick() {{
                    const now = new Date();
                    let diff = Math.floor((now - start) / 1000);
                    if (diff < 0) diff = 0;
                    const h = Math.floor(diff / 3600);
                    const m = Math.floor((diff % 3600) / 60);
                    const s = diff % 60;
                    if (el) el.textContent = pad(h) + ":" + pad(m) + ":" + pad(s);
                  }}
                  tick(); setInterval(tick, 1000);
                }})();
              </script>
            """
    else:
        dashboard_status_html = f'<a href="/clock" class="statusLink" title="Open clock page"><span class="chip {status_class}">{escape(status_text)}</span></a>'

        if dashboard_active_start_iso:
            clock_status_card_html = f"""
              <div class="modernMetricCard">
                <div>
                  <div class="modernMetricLabel">Clock Status</div>
                  <div class="modernMetricValue liveTimeValue" id="dashboardMetricLiveTimer">00:00:00</div>
                  <div class="modernMetricSub">Live time since clock-in</div>
                </div>
                <div class="modernMetricIcon green">
                  <svg viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="9"></circle>
                    <path d="M12 7v6l4 2"></path>
                  </svg>
                </div>

                <script>
                  (function() {{
                    const startIso = "{escape(dashboard_active_start_iso)}";
                    const start = new Date(startIso);
                    const el = document.getElementById("dashboardMetricLiveTimer");

                    function pad(n) {{
                      return String(n).padStart(2, "0");
                    }}

                    function tick() {{
                      if (!el || isNaN(start.getTime())) return;

                      const now = new Date();
                      let diff = Math.floor((now - start) / 1000);
                      if (diff < 0) diff = 0;

                      const h = Math.floor(diff / 3600);
                      const m = Math.floor((diff % 3600) / 60);
                      const s = diff % 60;

                      el.textContent = pad(h) + ":" + pad(m) + ":" + pad(s);
                    }}

                    tick();
                    setInterval(tick, 1000);
                  }})();
                </script>
              </div>
            """
        else:
            clock_status_card_html = f"""
              <div class="modernMetricCard">
                <div>
                  <div class="modernMetricLabel">Clock Status</div>
                  <div class="modernMetricValue">Out</div>
                  <div class="modernMetricSub">Your current status</div>
                </div>
                <div class="modernMetricIcon blue">
                  <svg viewBox="0 0 24 24">
                    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path>
                    <circle cx="9" cy="7" r="4"></circle>
                    <path d="M22 21v-2a4 4 0 0 0-3-3.87"></path>
                    <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
                  </svg>
                </div>
              </div>
            """

    employee_count = 0
    clocked_in_count = 0
    active_locations_count = 0
    onboarding_pending_count = 0
    employee_onboarding_completed = False

    try:
        emp_vals = employees_sheet.get_all_values()
        if emp_vals:
            emp_headers = emp_vals[0]
            i_user = emp_headers.index("Username") if "Username" in emp_headers else None
            i_wp = emp_headers.index("Workplace_ID") if "Workplace_ID" in emp_headers else None
            i_onb = emp_headers.index("OnboardingCompleted") if "OnboardingCompleted" in emp_headers else None

            for r in emp_vals[1:]:
                if i_user is None or i_user >= len(r):
                    continue
                u = (r[i_user] or "").strip()
                if not u:
                    continue

                if i_wp is not None:
                    row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                    if row_wp not in allowed_wps:
                        continue

                employee_count += 1

                if i_onb is not None:
                    done_flag = (r[i_onb] if i_onb < len(r) else "").strip().lower()
                    done_bool = done_flag in ("true", "1", "yes")

                    if u == username:
                        employee_onboarding_completed = done_bool

                    if not done_bool:
                        onboarding_pending_count += 1
    except Exception:
        pass

    try:
        for s in _get_open_shifts():
            clocked_in_count += 1
    except Exception:
        pass

    active_locations = []
    try:
        active_locations = _get_active_locations() or []
        active_locations_count = len(active_locations)
    except Exception:
        active_locations = []
        active_locations_count = 0

    # ================= SMART DASHBOARD: admin/master only, read-only =================
    is_admin_like = role in ("admin", "master_admin")
    current_week_start = monday
    current_week_end = monday + timedelta(days=6)
    current_week_start_str = current_week_start.isoformat()
    current_week_end_str = current_week_end.isoformat()

    week_users_with_work = set()
    open_shift_users = set()
    older_open_shift_count = 0
    live_site_summary = {}

    in_site_idx = headers.index("InSite") if (headers and "InSite" in headers) else None
    out_site_idx = headers.index("OutSite") if (headers and "OutSite" in headers) else None

    for r in rows[1:]:
        if len(r) <= COL_USER or len(r) <= COL_DATE:
            continue

        row_user = (r[COL_USER] or "").strip()
        if not row_user:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(row_user):
                continue

        d_str = (r[COL_DATE] if len(r) > COL_DATE else "").strip()
        cin = (r[COL_IN] if len(r) > COL_IN else "").strip()
        cout = (r[COL_OUT] if len(r) > COL_OUT else "").strip()
        h_val = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        p_val = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        try:
            d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
        except Exception:
            d_obj = None

        if d_obj and current_week_start <= d_obj <= current_week_end and (h_val > 0 or p_val > 0):
            week_users_with_work.add(row_user)

        if cin and not cout:
            open_shift_users.add(row_user)

            if d_obj and d_obj < today:
                older_open_shift_count += 1

            row_in_site = (r[in_site_idx] if in_site_idx is not None and len(r) > in_site_idx else "").strip()
            row_out_site = (r[out_site_idx] if out_site_idx is not None and len(r) > out_site_idx else "").strip()
            site_name = row_out_site or row_in_site or "No site"

            live_site_summary.setdefault(site_name, set())
            live_site_summary[site_name].add(row_user)

    active_employee_records = []
    employee_rate_lookup = {}
    employees_without_site = 0

    try:
        if callable(_list_employee_records_for_workplace):
            try:
                employee_records = _list_employee_records_for_workplace(current_wp, include_inactive=True) or []
            except TypeError:
                employee_records = _list_employee_records_for_workplace(include_inactive=True) or []
        else:
            employee_records = []
    except Exception:
        employee_records = []

    for rec in employee_records:
        rec_wp = str(
            rec.get("Workplace_ID")
            or rec.get("workplace_id")
            or rec.get("workplace")
            or "default"
        ).strip() or "default"

        if rec_wp not in allowed_wps:
            continue

        rec_user = str(rec.get("Username") or rec.get("username") or "").strip()
        if not rec_user:
            continue

        active_raw = str(rec.get("Active") or rec.get("active") or "TRUE").strip().lower()
        is_active_employee = active_raw not in ("false", "0", "no", "n", "off")

        if not is_active_employee:
            continue

        active_employee_records.append(rec)

        rate_raw = rec.get("Rate")
        if rate_raw in (None, ""):
            rate_raw = rec.get("rate")

        try:
            employee_rate_lookup[rec_user] = safe_float(rate_raw, 0.0)
        except Exception:
            employee_rate_lookup[rec_user] = 0.0

        site_1 = str(rec.get("Site") or rec.get("site") or "").strip()
        site_2 = str(rec.get("Site2") or rec.get("site2") or "").strip()
        if not site_1 and not site_2:
            employees_without_site += 1

    missing_rate_users = [
        u for u in week_users_with_work
        if safe_float(employee_rate_lookup.get(u, 0.0), 0.0) <= 0
    ]
    missing_rate_count = len(missing_rate_users)

    payroll_paid_users = set()
    payroll_approved_users = set()

    try:
        payroll_vals = get_payroll_rows() if callable(get_payroll_rows) else []
        payroll_headers = payroll_vals[0] if payroll_vals else []

        def payroll_idx(name):
            return payroll_headers.index(name) if name in payroll_headers else None

        i_ws = payroll_idx("WeekStart")
        i_we = payroll_idx("WeekEnd")
        i_u = payroll_idx("Username")
        i_paid = payroll_idx("Paid")
        i_pa = payroll_idx("PaidAt")
        i_wp = payroll_idx("Workplace_ID")

        for pr in payroll_vals[1:]:
            pr_ws = (pr[i_ws] if i_ws is not None and i_ws < len(pr) else "").strip()
            pr_we = (pr[i_we] if i_we is not None and i_we < len(pr) else "").strip()
            pr_user = (pr[i_u] if i_u is not None and i_u < len(pr) else "").strip()
            pr_paid = (pr[i_paid] if i_paid is not None and i_paid < len(pr) else "").strip().lower()
            pr_paid_at = (pr[i_pa] if i_pa is not None and i_pa < len(pr) else "").strip()
            pr_wp = (pr[i_wp] if i_wp is not None and i_wp < len(pr) else "").strip() or "default"

            if pr_wp not in allowed_wps:
                continue
            if pr_ws != current_week_start_str or pr_we != current_week_end_str:
                continue
            if not pr_user:
                continue

            if pr_paid_at or pr_paid in ("true", "1", "yes", "paid", "locked"):
                payroll_paid_users.add(pr_user)
            elif pr_paid == "approved":
                payroll_approved_users.add(pr_user)
    except Exception:
        payroll_paid_users = set()
        payroll_approved_users = set()

    payroll_awaiting_pay_count = len(payroll_approved_users - payroll_paid_users)
    payroll_paid_count = len(payroll_paid_users)
    payroll_approved_count = len(payroll_approved_users)
    payroll_unapproved_count = len(week_users_with_work - payroll_paid_users - payroll_approved_users)

    smart_warning_count = (
            older_open_shift_count
            + missing_rate_count
            + employees_without_site
            + payroll_unapproved_count
    )

    def smart_status_class(count_value):
        return "bad" if int(count_value or 0) > 0 else "ok"

    def smart_status_text(count_value):
        return "Needs attention" if int(count_value or 0) > 0 else "Clear"

    attention_items = [
        ("Open shifts from previous days", older_open_shift_count, "/admin/log-activities"),
        ("Payroll not approved", payroll_unapproved_count, "/admin/payroll"),
        ("Approved, awaiting payment", payroll_awaiting_pay_count, "/admin/payroll"),
        ("Employees missing rate", missing_rate_count, "/admin/employees"),
        ("Employees without site access", employees_without_site, "/admin/employee-sites"),
        ("Pending starter forms", onboarding_pending_count, "/admin/onboarding"),
    ]

    attention_rows_html = ""
    for label, count_value, href in attention_items:
        tone = smart_status_class(count_value)
        attention_rows_html += f"""
          <a class="smartDashRow" href="{escape(href)}">
            <span>{escape(label)}</span>
            <strong class="{tone}">{int(count_value or 0)}</strong>
          </a>
        """

    live_sites_html = ""
    if live_site_summary:
        for site_name, site_users in sorted(live_site_summary.items(), key=lambda item: item[0].lower()):
            live_sites_html += f"""
              <div class="smartSitePill">
                <span>{escape(site_name)}</span>
                <strong>{len(site_users)}</strong>
              </div>
            """
    else:
        live_sites_html = """
          <div class="smartEmptyLine">No workers currently clocked in.</div>
        """

    warning_rows_html = ""
    smart_warnings = [
        ("Previous-day open shifts", older_open_shift_count),
        ("Missing hourly rates", missing_rate_count),
        ("Missing site access", employees_without_site),
        ("Unapproved payroll rows", payroll_unapproved_count),
        ("No active site locations", 1 if active_locations_count <= 0 else 0),
    ]

    for label, count_value in smart_warnings:
        if int(count_value or 0) <= 0:
            continue

        warning_rows_html += f"""
          <div class="smartWarningLine">
            <span>{escape(label)}</span>
            <strong>{int(count_value or 0)}</strong>
          </div>
        """

    if not warning_rows_html:
        warning_rows_html = """
          <div class="smartGoodLine">No setup or payroll warnings for this workplace.</div>
        """

    recent_actions_html = ""
    if is_admin_like and DB_MIGRATION_MODE and AuditLog is not None:
        try:
            audit_rows = (
                AuditLog.query
                .filter(AuditLog.workplace_id.in_(list(allowed_wps)))
                .order_by(AuditLog.created_at.desc())
                .limit(5)
                .all()
            )

            for a in audit_rows:
                action = str(getattr(a, "action", "") or "").replace("_", " ").title()
                actor = str(getattr(a, "actor", "") or "").strip() or "System"
                target = str(getattr(a, "username", "") or "").strip()
                created = getattr(a, "created_at", None)
                when = created.strftime("%d %b • %H:%M") if created else ""

                detail_text = f"{actor}"
                if target:
                    detail_text += f" → {target}"

                recent_actions_html += f"""
                  <div class="smartActionLine">
                    <div>
                      <strong>{escape(action or "Activity")}</strong>
                      <span>{escape(detail_text)}</span>
                    </div>
                    <em>{escape(when)}</em>
                  </div>
                """
        except Exception:
            recent_actions_html = ""

    if not recent_actions_html:
        recent_actions_html = """
          <div class="smartEmptyLine">No recent admin actions available.</div>
        """

    audit_view_all_link = (
        '<a class="smartMiniLink" href="/admin/audit">View all</a>'
        if role == "master_admin"
        else ""
    )

    audit_view_all_link = (
        '<a class="modernPanelLink small" href="/admin/audit">View all ›</a>'
        if role == "master_admin"
        else ""
    )

    recent_activity_panel_html = ""
    if is_admin_like:
        recent_activity_panel_html = f"""
          <div class="modernPanel modernActivityPanel">
            <div class="modernPanelHeaderRow">
              <div>
                <h2 class="modernPanelTitle">Recent Activity</h2>
                <p class="modernPanelSub">Latest workplace actions.</p>
              </div>
              {audit_view_all_link}
            </div>
            <div class="professionalActionList">
              {recent_actions_html}
            </div>
          </div>
        """

    smart_dashboard_html = ""
    if is_admin_like:
        smart_dashboard_html = f"""
          <div class="professionalDashboard">
            <div class="professionalMainGrid">
              <div class="professionalCard professionalAttentionCard">
                <div class="professionalCardHead">
                  <div>
                    <h2>Operational Attention</h2>
                    <p>Items that may need action before payroll or site review.</p>
                  </div>
                  <span class="professionalStatus {smart_status_class(smart_warning_count)}">
                    {escape(str(int(smart_warning_count or 0)) + " issue" + ("" if int(smart_warning_count or 0) == 1 else "s"))}
                  </span>
                </div>

                <div class="professionalAttentionList">
                  {attention_rows_html}
                </div>
              </div>

              <div class="professionalCard professionalPayrollCard">
                <div class="professionalCardHead">
                  <div>
                    <h2>Payroll Snapshot</h2>
                    <p>{escape(current_week_start.strftime("%d %b"))} – {escape(current_week_end.strftime("%d %b %Y"))}</p>
                  </div>
                  <a class="professionalLink" href="/admin/payroll">Open Payroll</a>
                </div>

                <div class="professionalPayrollStats">
                  <div>
                    <span>Workers</span>
                    <strong>{len(week_users_with_work)}</strong>
                  </div>
                  <div>
                    <span>Approved</span>
                    <strong>{payroll_approved_count}</strong>
                  </div>
                  <div>
                    <span>Paid</span>
                    <strong>{payroll_paid_count}</strong>
                  </div>
                  <div>
                    <span>Awaiting pay</span>
                    <strong>{payroll_awaiting_pay_count}</strong>
                  </div>
                </div>

                <div class="professionalWarnings">
                  {warning_rows_html}
                </div>
              </div>
            </div>

            <div class="professionalLiveStrip">
              <div>
                <strong>Live Attendance</strong>
                <span>{len(open_shift_users)} worker(s) clocked in now.</span>
              </div>
              <div class="professionalLiveSites">
                {live_sites_html}
              </div>
              <a class="professionalLink" href="/admin/log-activities">View logs</a>
            </div>
          </div>
        """

    if role in ("admin", "master_admin"):
        clock_status_card_html = f"""
          <div class="modernMetricCard">
            <div>
              <div class="modernMetricLabel">Active Workers</div>
              <div class="modernMetricValue">{clocked_in_count}</div>
              <div class="modernMetricSub">On site today</div>
            </div>
            <div class="modernMetricIcon blue">
              <svg viewBox="0 0 24 24">
                <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path>
                <circle cx="9" cy="7" r="4"></circle>
                <path d="M22 21v-2a4 4 0 0 0-3-3.87"></path>
                <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
              </svg>
            </div>
          </div>
        """
    elif dashboard_active_start_iso:
        clock_status_card_html = f"""
          <a class="modernMetricCard clockStatusCardLink attendanceCombinedCard isClockedIn" href="/clock" title="Open clock page">
            <div class="attendanceCombinedMain">
              <div class="modernMetricLabel clockLiveLabel">
                <span>Clocked In</span>
                <span class="clockLiveDot" aria-hidden="true"></span>
              </div>
              <div class="modernMetricValue liveTimeValue" id="dashboardMetricLiveTimer">00:00:00</div>
              <div class="modernMetricSub">Live time since clock-in</div>
            </div>

            <div class="attendanceCombinedDivider"></div>

            <div class="attendanceCombinedSite" id="dashboardSiteCard">
              <div class="attendanceSiteText">
                <div class="attendanceSiteLabel">Current Site</div>
                <div class="attendanceSiteValue" id="dashboardSiteLabel">{escape(dashboard_site_label)}</div>
                <div class="attendanceSiteSub" id="dashboardSiteSub">{escape(dashboard_site_sub)}</div>
              </div>

              <div class="modernMetricIcon maps" id="dashboardSiteIcon">
                <svg viewBox="0 0 24 24">
                  <path d="M12 21s7-5.2 7-11a7 7 0 0 0-14 0c0 5.8 7 11 7 11z"></path>
                  <circle cx="12" cy="10" r="2.5"></circle>
                </svg>
              </div>
            </div>
          </a>

          <script>
            (function() {{
              const startIso = "{escape(dashboard_active_start_iso)}";
              const start = new Date(startIso);
              const el = document.getElementById("dashboardMetricLiveTimer");

              function pad(n) {{
                return String(n).padStart(2, "0");
              }}

              function tick() {{
                if (!el || isNaN(start.getTime())) return;

                const now = new Date();
                let diff = Math.floor((now - start) / 1000);
                if (diff < 0) diff = 0;

                const h = Math.floor(diff / 3600);
                const m = Math.floor((diff % 3600) / 60);
                const s = diff % 60;

                el.textContent = pad(h) + ":" + pad(m) + ":" + pad(s);
              }}

              tick();
              setInterval(tick, 1000);
            }})();
          </script>
        """
    else:
        clock_status_card_html = f"""
          <a class="modernMetricCard clockStatusCardLink attendanceCombinedCard" href="/clock" title="Open clock page">
            <div class="attendanceCombinedMain">
              <div class="modernMetricLabel">Clock In</div>
              <div class="modernMetricValue clockStartValue">Start</div>
              <div class="modernMetricSub">Tap to clock in</div>
            </div>

            <div class="attendanceCombinedDivider"></div>

            <div class="attendanceCombinedSite" id="dashboardSiteCard">
              <div class="attendanceSiteText">
                <div class="attendanceSiteLabel">Current Site</div>
                <div class="attendanceSiteValue" id="dashboardSiteLabel">{escape(dashboard_site_label)}</div>
                <div class="attendanceSiteSub" id="dashboardSiteSub">{escape(dashboard_site_sub)}</div>
              </div>

              <div class="modernMetricIcon maps" id="dashboardSiteIcon">
                <svg viewBox="0 0 24 24">
                  <path d="M12 21s7-5.2 7-11a7 7 0 0 0-14 0c0 5.8 7 11 7 11z"></path>
                  <circle cx="12" cy="10" r="2.5"></circle>
                </svg>
              </div>
            </div>
          </a>
        """

    best_week_gross = max(weekly_gross) if weekly_gross else 0.0
    avg_weekly_gross = (sum(weekly_gross) / len(weekly_gross)) if weekly_gross else 0.0
    week_target_hours = 42.5
    week_progress_pct = 0
    if week_target_hours > 0:
        week_progress_pct = int(round(max(0.0, min(1.0, week_hours / week_target_hours)) * 100))
    team_metric_label = "Clocked In Now" if role in ("admin", "master_admin") else "Active Locations"
    team_metric_value = clocked_in_count if role in ("admin", "master_admin") else active_locations_count
    if prev_gross > 0:
        week_delta_pct = ((curr_gross - prev_gross) / prev_gross) * 100.0
    elif curr_gross > 0:
        week_delta_pct = 100.0
    else:
        week_delta_pct = 0.0

    def _nice_chart_axis_max(value: float) -> float:
        try:
            value = float(value or 0.0)
        except Exception:
            value = 0.0
        if value <= 0:
            return 1000.0
        scaled = value * 1.15
        power = 10 ** math.floor(math.log10(scaled))
        normalized = scaled / power
        if normalized <= 1:
            nice = 1
        elif normalized <= 1.5:
            nice = 1.5
        elif normalized <= 2:
            nice = 2
        elif normalized <= 2.5:
            nice = 2.5
        elif normalized <= 5:
            nice = 5
        else:
            nice = 10
        return nice * power

    def _fmt_chart_tick(value: float) -> str:
        try:
            value = float(value or 0.0)
        except Exception:
            value = 0.0
        if abs(value) < 1e-9:
            return "0.0"
        if abs(value - round(value)) < 1e-9:
            return str(int(round(value)))
        return f"{value:.1f}".rstrip("0").rstrip(".")

    chart_y_max = _nice_chart_axis_max(max(chart_weekly_gross) if chart_weekly_gross else 0.0)
    chart_tick_values = [round(chart_y_max * (i / 5.0), 1) for i in range(5, -1, -1)]
    chart_ticks_html = "".join(
        f'<div class=\"grossChartTick\"><span>{escape(_fmt_chart_tick(v))}</span></div>'
        for v in chart_tick_values
    )
    chart_grid_html = "".join(
        f'<div class=\"grossChartGridLine\" style=\"bottom:{int((i / 5.0) * 100)}%;\"></div>'
        for i in range(6)
    )

    chart_bar_parts = []
    for lbl, gross in zip(chart_week_labels, chart_weekly_gross):
        try:
            gross_val = float(gross or 0.0)
        except Exception:
            gross_val = 0.0
        bar_pct = 0.0 if chart_y_max <= 0 else max(0.0, min(100.0, (gross_val / chart_y_max) * 100.0))
        if gross_val > 0 and bar_pct < 6.0:
            bar_pct = 6.0
        chart_bar_parts.append(
            f"<div class='grossChartBarCol'><div class='grossChartBarWrap'><div class='grossChartBar' style='height:{bar_pct:.2f}%;'></div></div><div class='grossChartBarLabel'>{escape(lbl)}</div></div>"
        )
    chart_bars_html = "".join(chart_bar_parts)

    chart_delta_text = ("+" if week_delta_pct > 0 else "") + f"{int(round(week_delta_pct))}%"
    chart_delta_class = "up" if week_delta_pct >= 0 else "down"
    chart_range_label = f"Weeks {chart_week_labels[0]} – {chart_week_labels[-1]}" if chart_week_labels else "Weeks"

    older_chart_offset = min(max_chart_offset, chart_offset + 1)
    newer_chart_offset = max(0, chart_offset - 1)

    chart_prev_html = (
        f'<a class="grossChartArrow" href="{escape(url_for("home", chart=older_chart_offset))}" aria-label="Older weeks" style="text-decoration:none;">‹</a>'
        if chart_offset < max_chart_offset else
        '<span class="grossChartArrow" style="opacity:.25; pointer-events:none;">‹</span>'
    )

    chart_next_html = (
        f'<a class="grossChartArrow" href="{escape(url_for("home", chart=newer_chart_offset))}" aria-label="Newer weeks" style="text-decoration:none;">›</a>'
        if chart_offset > 0 else
        '<span class="grossChartArrow" style="opacity:.25; pointer-events:none;">›</span>'
    )
    chart_section_html = f"""
          <div class=\"grossChartCard plainSection\">
            <div class=\"grossChartSummaryRow\">
              <div class=\"grossSummaryBox\">
                <div class=\"grossSummaryLabel\">Previous Gross</div>
                <div class=\"grossSummaryValue\">{escape(currency)}{money(prev_gross)}</div>
              </div>

              <div class=\"grossSummaryBox\">
                <div class=\"grossSummaryLabel\">Current Gross</div>
                <div class=\"grossSummaryValue\">{escape(currency)}{money(curr_gross)}</div>
                <div class=\"grossSummaryDelta {chart_delta_class}\">{chart_delta_text}</div>
              </div>
            </div>

                        <div class=\"grossChartNav\">
              {chart_prev_html}
              <div class=\"grossChartRangeTitle\">{escape(chart_range_label)}</div>
              {chart_next_html}
            </div>

            <div class=\"grossChartPlot\">
              <div class=\"grossChartYAxis\">
                {chart_ticks_html}
              </div>

              <div class=\"grossChartCanvas\">
                {chart_grid_html}
                <div class=\"grossChartBars\">
                  {chart_bars_html}
                </div>
              </div>
            </div>
          </div>
        """
    activity_cta_html = (
        '<a class="btnTiny" href="/admin/log-activities">View all logs</a>'
        if role in ("admin", "master_admin")
        else '<a class="btnTiny" href="/my-times">View all logs</a>'
    )

    snapshot_html = ""
    if role in ("admin", "master_admin"):
        snapshot_html = f"""
              <div class="sideInfoCard plainSection" id="businessSnapshotCard">
                <div class="sectionHead">
                  <div class="sectionHeadLeft">
                    <div class="sectionIcon">{_svg_grid()}</div>
                    <div>
                      <h2 style="margin:0;">Business Snapshot</h2>
                      <p class="sub" style="margin:4px 0 0 0;">Live workforce and workplace setup overview.</p>
                    </div>
                  </div>
                </div>

                <div class="sideInfoList">
                  <div class="sideInfoRow">
                    <div class="sideInfoLabel">Employees</div>
                    <div class="sideInfoValue" id="snapshotEmployees">{employee_count}</div>
                  </div>

                  <div class="sideInfoRow">
      <div class="sideInfoLabel">Clocked In Now</div>
      <div class="sideInfoValue" style="display:flex; align-items:center; justify-content:flex-end; gap:8px;">
        <span id="snapshotClockedIn">{clocked_in_count}</span>
        <span
          id="snapshotClockedInLive"
          style="
            display:{'inline-flex' if int(clocked_in_count or 0) > 0 else 'none'};
            align-items:center;
            padding:4px 8px;
            border-radius:999px;
            font-size:11px;
            font-weight:700;
            letter-spacing:.02em;
            background:rgba(34,197,94,.12);
            color:#15803d;
            border:1px solid rgba(34,197,94,.24);
          "
        >live</span>
      </div>
    </div>

                  <div class="sideInfoRow">
                    <div class="sideInfoLabel">Active Locations</div>
                    <div class="sideInfoValue" id="snapshotLocations">{active_locations_count}</div>
                  </div>

                  <div class="sideInfoRow">
                    <div class="sideInfoLabel">Onboarding Pending</div>
                    <div class="sideInfoValue" id="snapshotOnboarding">{onboarding_pending_count}</div>
                  </div>
                </div>

                <div class="snapshotFoot">
                  Monitor staffing, access setup and onboarding completion from one place.
                  <span id="snapshotUpdatedAt" style="margin-left:8px; opacity:.7;"></span>
                </div>
              </div>

              <script>
              (function(){{
                const employeesEl = document.getElementById("snapshotEmployees");
                const clockedEl = document.getElementById("snapshotClockedIn");
                const clockedLiveEl = document.getElementById("snapshotClockedInLive");
                const locationsEl = document.getElementById("snapshotLocations");
                const onboardingEl = document.getElementById("snapshotOnboarding");
                const updatedEl = document.getElementById("snapshotUpdatedAt");
                const badgeEl = document.getElementById("snapshotLiveBadge");

                if (!employeesEl || !clockedEl || !locationsEl || !onboardingEl) return;

                let busy = false;

                async function refreshSnapshot(){{
                  if (busy) return;
                  busy = true;

                  try {{
                    const res = await fetch("/api/dashboard-snapshot", {{
                      method: "GET",
                      credentials: "same-origin",
                      cache: "no-store",
                      headers: {{
                        "X-Requested-With": "XMLHttpRequest"
                      }}
                    }});

                    if (!res.ok) return;

                    const data = await res.json();

                    employeesEl.textContent = String(data.employee_count ?? 0);

                     const liveCount = Number(data.clocked_in_count ?? 0);
                     clockedEl.textContent = String(liveCount);

                     if (clockedLiveEl) {{
                     clockedLiveEl.style.display = liveCount > 0 ? "inline-flex" : "none";
                     }}

                    locationsEl.textContent = String(data.active_locations_count ?? 0);
                    onboardingEl.textContent = String(data.onboarding_pending_count ?? 0);

                    if (updatedEl && data.updated_at) {{
                      updatedEl.textContent = "Updated " + data.updated_at;
                    }}

                    if (badgeEl) {{
                      badgeEl.textContent = "Live";
                      badgeEl.style.opacity = "1";
                      setTimeout(function(){{
                        if (badgeEl) badgeEl.style.opacity = ".88";
                      }}, 250);
                    }}
                  }} catch (e) {{
                    console.error("snapshot refresh failed", e);
                  }} finally {{
                    busy = false;
                  }}
                }}

                refreshSnapshot();
                setInterval(refreshSnapshot, 10000);

                document.addEventListener("visibilitychange", function(){{
                  if (!document.hidden) refreshSnapshot();
                }});
              }})();
              </script>
            """

    def _pct(value, total):
        try:
            value = float(value or 0)
            total = float(total or 0)
            if total <= 0:
                return 0
            return int(round(max(0, min(1, value / total)) * 100))
        except Exception:
            return 0

    completed_onboarding = max(0, int(employee_count or 0) - int(onboarding_pending_count or 0))
    onboarding_total = max(int(employee_count or 0), completed_onboarding + int(onboarding_pending_count or 0), 1)
    onboarding_pct = _pct(completed_onboarding, onboarding_total)

    clocked_pct = _pct(clocked_in_count, max(employee_count, 1))
    sites_pct = min(100, max(0, int(active_locations_count or 0) * 25))
    forms_pct = _pct(completed_onboarding, onboarding_total)
    # Employee clock progress: fills from 0% to 100% over 9 hours after clock-in
    clock_shift_target_seconds = 9 * 60 * 60
    clock_shift_progress_pct = 0

    if dashboard_active_start_iso:
        try:
            clock_start_dt = datetime.fromisoformat(dashboard_active_start_iso)
            elapsed_seconds = max(0, int((now - clock_start_dt).total_seconds()))
            clock_shift_progress_pct = int(round(min(1.0, elapsed_seconds / clock_shift_target_seconds) * 100))
        except Exception:
            clock_shift_progress_pct = 0

    is_admin_dashboard = role in ("admin", "master_admin")

    if is_admin_dashboard:
        metric_1_label = "Active Workers"
        metric_1_value = str(clocked_in_count)
        metric_1_sub = "On site today"

        metric_3_label = "Sites"
        metric_3_value = str(active_locations_count)
        metric_3_sub = "Active workplaces"

        metric_4_label = "Forms"
        metric_4_value = str(onboarding_pending_count)
        metric_4_sub = "Pending"

        progress_2_label = "Clocked in now"
        progress_2_pct = clocked_pct

        progress_3_label = "Onboarding complete"
        progress_3_pct = forms_pct

        progress_4_label = "Active sites setup"
        progress_4_pct = sites_pct

        onboarding_card_title = "Onboarding"
        onboarding_card_text = f"{onboarding_pending_count} starter forms need attention."
        onboarding_card_button = "View onboarding"
        onboarding_card_url = "/admin/onboarding"
        onboarding_card_progress_label = f"{completed_onboarding} / {onboarding_total} completed"
        onboarding_card_pct = onboarding_pct

    else:
        metric_1_label = "Clock Status"
        metric_1_value = "In" if is_clocked_in else "Out"
        metric_1_sub = "Your current status"

        metric_3_label = "Days Worked"
        metric_3_value = str(len(week_days))
        metric_3_sub = "This week"

        metric_4_label = "Gross Pay"
        metric_4_value = (
            f'<div class="grossPayValue">'
            f'<span class="grossPayToday">Today: {escape(currency)}{money(today_pay)}</span>'
            f'<span class="grossPayWeek">Week: {escape(currency)}{money(week_pay)}</span>'
            f'</div>'
        )
        metric_4_sub = "Estimated"

        progress_2_label = "Clock progress"
        progress_2_pct = clock_shift_progress_pct if is_clocked_in else 0

        progress_3_label = "Starter form"
        progress_3_pct = 100 if employee_onboarding_completed else 0

        progress_4_label = "Weekly activity"
        progress_4_pct = min(100, len(week_days) * 20)

        if employee_onboarding_completed:
            onboarding_card_title = "My Documents"
            onboarding_card_text = "Starter form complete. View your submitted onboarding details and uploaded documents."
            onboarding_card_button = "View my documents"
            onboarding_card_url = "/onboarding/view"
            onboarding_card_progress_label = "Complete"
            onboarding_card_pct = 100
        else:
            onboarding_card_title = "Onboarding"
            onboarding_card_text = "Review your starter form and upload any required documents."
            onboarding_card_button = "View onboarding"
            onboarding_card_url = "/onboarding/view"
            onboarding_card_progress_label = "0 / 1 completed"
            onboarding_card_pct = 0

    def _initials(name):
        parts = [p for p in str(name or "").strip().split() if p]
        if not parts:
            return "U"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][:1] + parts[-1][:1]).upper()

    modern_recent_rows = ""
    for rr in recent_rows[:4]:
        worker_name = get_employee_display_name(rr["user"]) if show_employee_col else display_name
        worker_initials = _initials(worker_name)
        site_label = current_wp or "Workplace"
        date_label = rr.get("date") or "—"
        hours_label = fmt_hours(rr.get("hours") or "0")

        modern_recent_rows += f"""
          <tr>
            <td>
              <div class="modernWorkerCell">
                <div class="modernAvatar">{escape(worker_initials)}</div>
                <div>
                  <div class="modernWorkerName">{escape(worker_name)}</div>
                  <div class="modernWorkerSub">{escape(rr.get("status") or "")}</div>
                </div>
              </div>
            </td>
            <td>{escape(site_label)}</td>
            <td>{escape(date_label)}</td>
            <td class="modernHours">{escape(hours_label)}</td>
          </tr>
        """

    if not modern_recent_rows:
        modern_recent_rows = """
          <tr>
            <td colspan="4">
              <div class="modernEmpty">No recent timesheets yet.</div>
            </td>
          </tr>
        """

    modern_dashboard_css = """
      <style>
        .dashboardShellModern{
  max-width: none !important;
  width: 100% !important;
  margin: 0 !important;
  display: grid !important;
  grid-template-columns: 230px minmax(0, 1fr) !important;
  gap: 0 !important;
  min-height: calc(100vh - 32px);
  background: #f8fbff;
  border-radius: 0 !important;
}

.dashboardShellModern .main{
  padding: 24px 26px 40px !important;
          background:
            radial-gradient(900px 520px at 85% 0%, rgba(37,99,235,.08), transparent 55%),
            linear-gradient(180deg, #fbfdff 0%, #f5f8fd 100%);
        }

        .dashboardShellModern .topBarFixed{
          margin-bottom: 18px !important;
        }

        .dashboardShellModern .sidebar{
  display: flex !important;
  flex-direction: column !important;
  width: 230px !important;
  min-height: calc(100vh - 32px);
  padding: 26px 14px !important;
  background:
    radial-gradient(500px 360px at 100% 0%, rgba(37,99,235,.22), transparent 48%),
    linear-gradient(180deg, #061b3d 0%, #082b5b 100%) !important;
  border: 0 !important;
  box-shadow: 18px 0 40px rgba(15,23,42,.10) !important;
  color: #fff !important;
}

        .dashboardShellModern .sidebar img{
  max-width: 130px !important;
  width: 130px !important;
  margin: 0 auto 22px auto !important;
}

        .dashboardShellModern .sideItem{
  min-height: 52px !important;
  margin: 4px 0 !important;
  padding: 0 12px !important;
          border-radius: 14px !important;
          border: 1px solid transparent !important;
          background: transparent !important;
          color: rgba(255,255,255,.88) !important;
          box-shadow: none !important;
        }

        .dashboardShellModern .sideItem:hover{
          background: rgba(255,255,255,.08) !important;
          border-color: rgba(255,255,255,.10) !important;
        }

        .dashboardShellModern .sideItem.active{
          background: linear-gradient(135deg, #0b63ff, #0057e7) !important;
          color: #fff !important;
          border-color: rgba(255,255,255,.18) !important;
          box-shadow: 0 14px 30px rgba(0,87,231,.34) !important;
        }

        .dashboardShellModern .sideItem.active::after{
          display: none !important;
        }

        .dashboardShellModern .sideText{
  color: currentColor !important;
  font-size: 14px !important;
  font-weight: 700 !important;
}

        .dashboardShellModern .sideIcon{
          color: currentColor !important;
          width: 28px !important;
          height: 28px !important;
        }

        .dashboardShellModern .sideIcon img,
        .dashboardShellModern .sideIcon svg{
          width: 24px !important;
          height: 24px !important;
        }

        .dashboardShellModern .chev{
          display: none !important;
        }
        
        .dashboardShellModern .menuItem{
  min-height: 52px !important;
  margin: 4px 0 !important;
  padding: 0 12px !important;
  border-radius: 14px !important;
  border: 1px solid transparent !important;
  background: transparent !important;
  color: rgba(255,255,255,.88) !important;
  box-shadow: none !important;
}

.dashboardShellModern .menuItem:hover{
  background: rgba(255,255,255,.08) !important;
  border-color: rgba(255,255,255,.10) !important;
}

.dashboardShellModern .menuItem.active,
.dashboardShellModern .menuItem.nav-home{
  background: linear-gradient(135deg, #0b63ff, #0057e7) !important;
  color: #fff !important;
  border-color: rgba(255,255,255,.18) !important;
  box-shadow: 0 14px 30px rgba(0,87,231,.34) !important;
}

.dashboardShellModern .menuText{
  color: currentColor !important;
  font-size: 14px !important;
  font-weight: 800 !important;
}

.dashboardShellModern .menuLeft{
  display:flex !important;
  align-items:center !important;
  gap:12px !important;
}

.dashboardShellModern .icoBox{
  background: rgba(255,255,255,.10) !important;
  color: currentColor !important;
  border: 1px solid rgba(255,255,255,.12) !important;
  width: 28px !important;
  height: 28px !important;
  border-radius: 8px !important;
}

.dashboardShellModern .icoBox img,
.dashboardShellModern .icoBox svg{
  width: 20px !important;
  height: 20px !important;
}

.dashboardShellModern .menuItem .chev{
  display:none !important;
}
        
        .modernDash{
          max-width: 1180px;
          margin: 0 auto;
        }

        .modernDashHeader{
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:18px;
          padding-bottom:18px;
          border-bottom:1px solid #e4ebf5;
          margin-bottom:26px;
        }

        .modernDashTitle h1{
          color:#07152f;
          font-size:34px;
          line-height:1.05;
          font-weight:900;
          letter-spacing:-.04em;
          margin:0;
        }

        .modernDashTitle p{
          margin:8px 0 0;
          color:#64748b;
          font-size:14px;
          font-weight:600;
        }

        .modernTopUser{
          display:flex;
          align-items:center;
          gap:12px;
          color:#10213f;
          font-weight:800;
        }

                .modernNotifyWrap{
          position:relative;
          display:flex;
          align-items:center;
        }

        .modernBell{
          position:relative;
          width:42px;
          height:42px;
          display:flex;
          align-items:center;
          justify-content:center;
          border-radius:999px;
          background:#fff;
          border:1px solid #e4ebf5;
          box-shadow:0 10px 24px rgba(15,23,42,.06);
          cursor:pointer;
        }

        .modernBell:hover{
          box-shadow:0 14px 30px rgba(15,23,42,.10);
          transform:translateY(-1px);
        }

        .modernBellDot{
          position:absolute;
          top:7px;
          right:7px;
          width:10px;
          height:10px;
          border-radius:999px;
          background:#ef4444;
          border:2px solid #fff;
          box-shadow:0 4px 10px rgba(239,68,68,.35);
        }

        .modernNotifyPanel{
          position:absolute;
          top:calc(100% + 12px);
          right:0;
          width:280px;
          padding:16px;
          border-radius:16px;
          background:#fff;
          border:1px solid #e3ebf6;
          box-shadow:0 18px 40px rgba(15,23,42,.14);
          z-index:50;
          display:none;
        }

        .modernNotifyPanel.open{
          display:block;
        }

        .modernNotifyTitle{
          font-size:15px;
          font-weight:900;
          color:#07152f;
          margin-bottom:8px;
        }

        .modernNotifyText{
          font-size:14px;
          font-weight:700;
          line-height:1.35;
          color:#263650;
        }

        .modernNotifySmall{
          margin-top:8px;
          font-size:12px;
          line-height:1.35;
          font-weight:600;
          color:#64748b;
        }

        .modernNotifyBtn{
          margin-top:12px;
          width:100%;
          min-height:40px;
          border:0;
          border-radius:10px;
          background:linear-gradient(135deg,#0b63ff,#0057e7);
          color:#fff;
          font-weight:900;
          cursor:pointer;
        }

        @media (max-width:620px){
          .modernNotifyPanel{
            right:-80px;
            width:260px;
          }
        }

        .modernUserAvatar{
          width:46px;
          height:46px;
          border-radius:999px;
          display:flex;
          align-items:center;
          justify-content:center;
          color:#fff;
          font-weight:900;
          background:linear-gradient(135deg,#0b63ff,#004bd6);
          box-shadow:0 12px 28px rgba(37,99,235,.25);
        }

                .modernMetricGrid{
          display:grid;
          grid-template-columns:repeat(4,minmax(0,1fr));
          gap:20px;
          margin-bottom:24px;
          align-items:stretch;
        }

        .modernMetricGrid > .modernMetricCard,
        .modernMetricGrid > .dashboardSiteCard{
          height:100%;
          min-height:150px;
          box-sizing:border-box;
        }

        .modernMetricCard{
          background:#fff;
          border:1px solid #e3ebf6;
          border-radius:18px;
          padding:24px 24px;
          box-shadow:0 14px 32px rgba(15,23,42,.06);
          min-height:150px;
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:16px;
        }

        .modernMetricLabel{
          font-size:16px;
          font-weight:900;
          color:#0c1733;
          margin-bottom:22px;
        }

        .modernMetricValue{
          font-size:42px;
          line-height:1;
          font-weight:900;
          color:#07152f;
          letter-spacing:-.04em;
          font-variant-numeric:tabular-nums;
        }
                .liveTimeValue{
          font-size:34px !important;
          letter-spacing:-.03em !important;
          white-space:nowrap;
        }
                .clockStartValue{
  color:#0b63ff !important;
  font-size:38px !important;
  letter-spacing:-.05em !important;
}
        
        .grossPayValue{
  display:flex;
  flex-direction:column;
  gap:4px;
  font-size:28px !important;
  line-height:1.05 !important;
  letter-spacing:-.03em !important;
}

.grossPayValue span{
  display:block;
  white-space:nowrap;
}

.grossPayToday{
  color:#0b63ff;
}

.grossPayWeek{
  color:#07152f;
}

@media (max-width:620px){
  .grossPayValue{
    font-size:22px !important;
  }
}
        
        
        
                .clockLiveLabel{
          display:inline-flex;
          align-items:center;
          gap:8px;
        }

        .clockLiveDot{
          width:9px;
          height:9px;
          border-radius:999px;
          background:#22c55e;
          box-shadow:0 0 0 5px rgba(34,197,94,.14);
          flex:0 0 9px;
        }

                .clockStatusCardLink{
  text-decoration:none !important;
  color:inherit !important;
  min-height:150px;
  transition:transform .15s ease, box-shadow .15s ease, border-color .15s ease;
}

.clockStatusCardLink:hover{
  transform:translateY(-2px);
  border-color:#bfdbfe;
  box-shadow:0 18px 38px rgba(37,99,235,.12);
}

.attendanceCombinedCard{
  grid-column:span 2;
  min-height:150px;
  display:grid !important;
  grid-template-columns:minmax(0,.9fr) 1px minmax(0,1.1fr);
  gap:0;
  padding:0;
  overflow:hidden;
  align-items:stretch;
}

.attendanceCombinedMain,
.attendanceCombinedSite{
  min-width:0;
  min-height:150px;
  padding:24px;
  display:flex;
  flex-direction:column;
  align-items:flex-start;
  justify-content:flex-start;
  gap:0;
  box-sizing:border-box;
}

.attendanceCombinedSite{
  position:relative;
  padding-right:96px;
}

.attendanceCombinedDivider{
  width:1px;
  background:#e8eef7;
  align-self:stretch;
}

.attendanceSiteText{
  min-width:0;
  flex:1 1 auto;
}

.attendanceSiteLabel{
  font-size:16px;
  line-height:1.15;
  font-weight:900;
  color:#0c1733;
  margin:0 0 22px 0;
}

.attendanceSiteValue{
  display:block;
  max-width:100%;
  font-size:34px;
  line-height:1;
  font-weight:900;
  color:#07152f;
  letter-spacing:-.04em;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
  margin:0;
}

.attendanceSiteSub{
  margin-top:16px;
  color:#52627d;
  font-size:14px;
  line-height:1.25;
  font-weight:600;
}
.attendanceCombinedSite .modernMetricIcon{
  position:absolute;
  right:24px;
  top:50%;
  transform:translateY(-50%);
  width:64px;
  height:64px;
  min-width:64px;
  flex:0 0 64px;
  margin:0;
}

.attendanceCombinedSite .modernMetricIcon svg{
  width:30px;
  height:30px;
}

.attendanceCombinedSite.isOnSite{
  background:linear-gradient(180deg, rgba(34,197,94,.05), rgba(34,197,94,.02));
}

.attendanceCombinedSite.isOnSite .attendanceSiteValue{
  color:#0f172a;
}

.liveTimeValue{
  font-size:34px !important;
  letter-spacing:-.03em !important;
  white-space:nowrap;
}

.clockStartValue{
  color:#0b63ff !important;
  font-size:38px !important;
  letter-spacing:-.05em !important;
}

.clockLiveLabel{
  display:inline-flex;
  align-items:center;
  gap:8px;
}

.clockLiveDot{
  width:9px;
  height:9px;
  border-radius:999px;
  background:#22c55e;
  box-shadow:0 0 0 5px rgba(34,197,94,.14);
  flex:0 0 9px;
}

.modernMetricSub{
  margin-top:12px;
  color:#52627d;
  font-size:14px;
  font-weight:600;
}

.modernMetricIcon{
  width:72px;
  height:72px;
  border-radius:999px;
  display:flex;
  align-items:center;
  justify-content:center;
  flex:0 0 72px;
}

.modernMetricIcon svg{
  width:34px;
  height:34px;
  fill:none;
  stroke:currentColor;
  stroke-width:2;
  stroke-linecap:round;
  stroke-linejoin:round;
}

.modernMetricIcon.blue{ background:#eaf2ff; color:#0b63ff; }
.modernMetricIcon.green{ background:#dcfce7; color:#16a34a; }
.modernMetricIcon.purple{ background:#eee9ff; color:#6d5dfc; }
.modernMetricIcon.maps{ background:#fff7db; color:#f4b400; }

.dashboardSiteCard.isOnSite{
  border-color:#bbf7d0 !important;
  box-shadow:0 18px 38px rgba(22,163,74,.10) !important;
}

.dashboardSiteCard.isOnSite:hover{
  border-color:#86efac !important;
  box-shadow:0 18px 38px rgba(22,163,74,.16) !important;
}

.dashboardSiteCard{
  text-decoration:none !important;
  color:inherit !important;
  cursor:pointer;
  transition:transform .15s ease, box-shadow .15s ease, border-color .15s ease;
  min-height:150px;
}

.dashboardSiteCard:hover{
  transform:translateY(-2px);
  border-color:#fde68a;
  box-shadow:0 18px 38px rgba(251,188,4,.14);
}

.dashboardSiteText{
  min-width:0;
  max-width:calc(100% - 88px);
  padding-right:10px;
}

.dashboardSiteValue{
  max-width:100%;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
  font-size:30px !important;
  letter-spacing:-.04em !important;
}

@media (max-width:980px){
  .attendanceCombinedCard{
    grid-column:1 / -1;
  }
}

@media (max-width:620px){
  .liveTimeValue{
    font-size:30px !important;
  }

  .clockStartValue{
    font-size:34px !important;
  }

    .attendanceCombinedCard{
    grid-template-columns:1fr 1px 1fr;
    grid-template-rows:auto;
  }

  .attendanceCombinedDivider{
    display:block;
  }

  .attendanceCombinedMain,
  .attendanceCombinedSite{
    min-height:154px;
    padding:18px 16px;
    align-items:flex-start;
    justify-content:flex-start;
  }

  .attendanceCombinedSite{
    padding-right:66px;
  }

  .attendanceSiteLabel{
  font-size:16px;
  line-height:1.15;
  margin:0 0 22px 0;
}

.attendanceSiteValue{
  font-size:34px !important;
  line-height:1 !important;
  white-space:nowrap !important;
  overflow:hidden !important;
  text-overflow:ellipsis !important;
}

.attendanceSiteSub{
  margin-top:16px;
  font-size:14px;
  line-height:1.25;
}

    .attendanceCombinedSite .modernMetricIcon{
    position:absolute;
    right:14px;
    top:50%;
    transform:translateY(-50%);
    width:42px;
    height:42px;
    min-width:42px;
    flex:0 0 42px;
    margin:0;
  }

  .attendanceCombinedSite .modernMetricIcon svg{
    width:22px;
    height:22px;
  }

  .dashboardSiteValue{
    max-width:210px;
    font-size:30px !important;
  }
}

        .modernMetricSub{
          margin-top:12px;
          color:#52627d;
          font-size:14px;
          font-weight:600;
        }

        .modernMetricIcon{
          width:72px;
          height:72px;
          border-radius:999px;
          display:flex;
          align-items:center;
          justify-content:center;
          flex:0 0 auto;
        }

        .modernMetricIcon svg{
          width:34px;
          height:34px;
          fill:none;
          stroke:currentColor;
          stroke-width:2;
          stroke-linecap:round;
          stroke-linejoin:round;
        }

        .modernMetricIcon.blue{ background:#eaf2ff; color:#0b63ff; }
        .modernMetricIcon.green{ background:#dcfce7; color:#16a34a; }
        .modernMetricIcon.purple{ background:#eee9ff; color:#6d5dfc; }
                .modernMetricIcon.maps{
          background:#fff7db;
          color:#f4b400;
        }

        .dashboardSiteCard.isOnSite{
          border-color:#bbf7d0 !important;
          box-shadow:0 18px 38px rgba(22,163,74,.10) !important;
        }

        .dashboardSiteCard.isOnSite:hover{
          border-color:#86efac !important;
          box-shadow:0 18px 38px rgba(22,163,74,.16) !important;
        }
                       .dashboardSiteCard{
          text-decoration:none !important;
          color:inherit !important;
          cursor:pointer;
          transition:transform .15s ease, box-shadow .15s ease, border-color .15s ease;
        }

                .dashboardSiteCard:hover{
          transform:translateY(-2px);
          border-color:#fde68a;
          box-shadow:0 18px 38px rgba(251,188,4,.14);
        }

        .dashboardSiteText{
          min-width:0;
          padding-right:8px;
        }

                .dashboardSiteValue{
          max-width:100%;
          overflow:hidden;
          text-overflow:ellipsis;
          white-space:nowrap;
          font-size:30px !important;
          letter-spacing:-.04em !important;
        }

        .dashboardSiteCard{
          min-height:150px;
        }

        .dashboardSiteText{
          min-width:0;
          max-width:calc(100% - 88px);
          padding-right:10px;
        }

        @media (max-width:620px){
          .dashboardSiteValue{
            max-width:210px;
            font-size:30px !important;
          }
        }
        

        .modernTwoCol{
          display:grid;
          grid-template-columns:minmax(0,1.05fr) minmax(360px,.95fr);
          gap:24px;
          margin-bottom:24px;
        }

        .modernPanel{
          background:#fff;
          border:1px solid #e3ebf6;
          border-radius:18px;
          padding:24px;
          box-shadow:0 14px 32px rgba(15,23,42,.06);
        }

        .modernPanelTitle{
          font-size:24px;
          line-height:1.1;
          font-weight:900;
          color:#07152f;
          letter-spacing:-.03em;
          margin:0;
        }

        .modernPanelSub{
          margin:8px 0 0;
          color:#52627d;
          font-size:15px;
          font-weight:600;
        }

        .modernTimesheetTable{
          margin-top:18px;
          width:100%;
          border-collapse:collapse;
        }

        .modernTimesheetTable th{
          padding:0 0 12px;
          color:#51617d;
          font-size:14px;
          font-weight:700;
          text-align:left;
          border-bottom:1px solid #e3ebf6;
          background:transparent !important;
        }

        .modernTimesheetTable td{
          padding:14px 0;
          border-bottom:1px solid #edf2f8;
          color:#263650;
          font-size:14px;
          font-weight:600;
          background:transparent !important;
        }

        .modernWorkerCell{
          display:flex;
          align-items:center;
          gap:12px;
        }

        .modernAvatar{
          width:38px;
          height:38px;
          border-radius:999px;
          display:flex;
          align-items:center;
          justify-content:center;
          background:linear-gradient(135deg,#dbeafe,#bfdbfe);
          color:#0b63ff;
          font-size:13px;
          font-weight:900;
        }

        .modernWorkerName{
          color:#10213f;
          font-weight:900;
        }

        .modernWorkerSub{
          margin-top:2px;
          color:#7a8ba5;
          font-size:12px;
          font-weight:700;
        }

        .modernHours{
          color:#0b63ff !important;
          font-weight:900 !important;
          text-align:right;
        }

        .modernPanelLink{
          margin-top:18px;
          display:inline-flex;
          align-items:center;
          gap:8px;
          color:#0b63ff;
          font-weight:900;
          font-size:15px;
        }

        .modernProgressList{
          margin-top:22px;
          display:flex;
          flex-direction:column;
          gap:24px;
        }

        .modernProgressTop{
          display:flex;
          justify-content:space-between;
          gap:14px;
          color:#10213f;
          font-weight:900;
        }

        .modernProgressTrack{
          margin-top:10px;
          height:10px;
          border-radius:999px;
          background:#e9eef6;
          overflow:hidden;
        }

        .modernProgressTrack span{
          display:block;
          height:100%;
          border-radius:999px;
          background:linear-gradient(90deg,#0b63ff,#0057e7);
          box-shadow:0 6px 18px rgba(37,99,235,.22);
        }

        .modernOnboardingCard{
          background:#fff;
          border:1px solid #e3ebf6;
          border-radius:18px;
          padding:22px 28px;
          box-shadow:0 14px 32px rgba(15,23,42,.06);
          display:grid;
          grid-template-columns:auto minmax(0,1fr) minmax(220px,330px) auto;
          align-items:center;
          gap:28px;
        }

        .modernDocIcon{
          width:92px;
          height:92px;
          border-radius:16px;
          display:flex;
          align-items:center;
          justify-content:center;
          background:#f1f6ff;
          color:#0b63ff;
        }

        .modernDocIcon svg{
          width:48px;
          height:48px;
          fill:none;
          stroke:currentColor;
          stroke-width:2;
          stroke-linecap:round;
          stroke-linejoin:round;
        }

        .modernOnboardingTitle{
          font-size:24px;
          font-weight:900;
          color:#07152f;
          letter-spacing:-.03em;
        }

        .modernOnboardingText{
          margin-top:8px;
          color:#52627d;
          font-size:16px;
          line-height:1.4;
          font-weight:600;
        }

        .modernOnboardingProgressLabel{
          color:#263650;
          font-weight:800;
          margin-bottom:10px;
        }

        .modernBtn{
          display:inline-flex;
          align-items:center;
          justify-content:center;
          min-height:54px;
          padding:0 28px;
          border-radius:10px;
          background:linear-gradient(135deg,#0b63ff,#0057e7);
          color:#fff;
          font-weight:900;
          box-shadow:0 14px 28px rgba(37,99,235,.28);
          white-space:nowrap;
        }

        .modernEmpty{
          padding:20px 0;
          color:#64748b;
          font-weight:700;
        }
                /* ================= Professional dashboard layout ================= */

        .professionalDashboard{
          display:grid;
          gap:18px;
          margin:22px 0 24px;
        }

        .professionalMainGrid{
          display:grid;
          grid-template-columns:minmax(0,1.15fr) minmax(360px,.85fr);
          gap:18px;
          align-items:start;
        }

        .professionalCard{
          background:#fff;
          border:1px solid #dbe7f6;
          border-radius:18px;
          box-shadow:0 14px 34px rgba(15,23,42,.055);
          padding:22px;
          min-width:0;
        }

        .professionalCardHead,
        .modernPanelHeaderRow{
          display:flex;
          align-items:flex-start;
          justify-content:space-between;
          gap:16px;
          margin-bottom:18px;
        }

        .professionalCardHead h2{
          margin:0;
          color:#07152f;
          font-size:20px;
          line-height:1.15;
          font-weight:900;
          letter-spacing:-.025em;
        }

        .professionalCardHead p{
          margin:6px 0 0;
          color:#64748b;
          font-size:13px;
          font-weight:700;
          line-height:1.35;
        }

        .professionalStatus{
          display:inline-flex;
          align-items:center;
          justify-content:center;
          min-height:30px;
          padding:0 10px;
          border-radius:999px;
          border:1px solid #dbeafe;
          background:#eff6ff;
          color:#1d4ed8;
          font-size:12px;
          font-weight:900;
          white-space:nowrap;
        }

        .professionalStatus.bad{
          border-color:#fed7aa;
          background:#fff7ed;
          color:#c2410c;
        }

        .professionalAttentionCard{
          background:#fff;
        }

        .professionalAttentionList{
          display:grid;
          gap:0;
        }

        .professionalAttentionList .smartDashRow{
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:16px;
          padding:12px 0;
          border-bottom:1px solid #edf2f8;
          color:#0f172a;
          font-size:14px;
          font-weight:850;
          text-decoration:none;
        }

        .professionalAttentionList .smartDashRow:last-child{
          border-bottom:0;
        }

        .professionalAttentionList .smartDashRow strong{
          min-width:34px;
          text-align:right;
          color:#64748b;
          font-size:14px;
          font-weight:900;
        }

        .professionalAttentionList .smartDashRow strong.bad{
          color:#c2410c;
        }

        .professionalAttentionList .smartDashRow strong.ok{
          color:#64748b;
        }

        .professionalPayrollStats{
          display:grid;
          grid-template-columns:repeat(4,minmax(0,1fr));
          gap:10px;
          margin-bottom:14px;
        }

        .professionalPayrollStats div{
          padding:14px 12px;
          border:1px solid #e2eaf5;
          border-radius:12px;
          background:#f8fbff;
        }

        .professionalPayrollStats span{
          display:block;
          color:#64748b;
          font-size:11px;
          font-weight:900;
          text-transform:uppercase;
          letter-spacing:.045em;
        }

        .professionalPayrollStats strong{
          display:block;
          margin-top:7px;
          color:#07152f;
          font-size:26px;
          line-height:1;
          font-weight:900;
          letter-spacing:-.03em;
        }

        .professionalWarnings{
          display:grid;
          gap:8px;
        }

        .professionalWarnings .smartWarningLine,
        .professionalWarnings .smartGoodLine,
        .professionalWarnings .smartEmptyLine{
          padding:10px 12px;
          border-radius:10px;
          font-size:13px;
          font-weight:850;
        }

        .professionalWarnings .smartWarningLine{
          display:flex;
          justify-content:space-between;
          gap:12px;
          background:#fff7ed;
          border:1px solid #fed7aa;
          color:#9a3412;
        }

        .professionalWarnings .smartGoodLine{
          background:#f8fbff;
          border:1px solid #dbeafe;
          color:#1d4ed8;
        }

        .professionalLiveStrip{
          display:grid;
          grid-template-columns:auto minmax(0,1fr) auto;
          align-items:center;
          gap:16px;
          background:#fff;
          border:1px solid #dbe7f6;
          border-radius:18px;
          box-shadow:0 14px 34px rgba(15,23,42,.045);
          padding:16px 18px;
        }

        .professionalLiveStrip strong{
          display:block;
          color:#07152f;
          font-size:16px;
          font-weight:900;
        }

        .professionalLiveStrip span{
          display:block;
          margin-top:3px;
          color:#64748b;
          font-size:13px;
          font-weight:700;
        }

        .professionalLiveSites{
          min-width:0;
        }

        .professionalLiveSites .smartEmptyLine{
          padding:0;
          border:0;
          background:transparent;
          color:#64748b;
          font-size:13px;
          font-weight:800;
        }

        .professionalLiveSites .smartSitePill{
          display:inline-flex;
          align-items:center;
          gap:10px;
          padding:7px 10px;
          margin:2px 5px 2px 0;
          border-radius:999px;
          border:1px solid #dbeafe;
          background:#eff6ff;
          color:#1d4ed8;
          font-size:12px;
          font-weight:900;
        }

        .professionalLink{
          color:#0b63ff;
          font-size:13px;
          font-weight:900;
          text-decoration:none;
          white-space:nowrap;
        }

        .dashboardActivityGrid{
          grid-template-columns:minmax(0,1.2fr) minmax(360px,.8fr) !important;
          align-items:start;
          margin-bottom:24px;
        }

        .dashboardActivityGrid.singleCol{
          grid-template-columns:1fr !important;
        }

        .modernPanelHeaderRow{
          margin-bottom:16px;
        }

        .modernPanelLink.small{
          margin-top:0 !important;
          font-size:13px;
          white-space:nowrap;
          text-decoration:none;
        }

        .modernActivityPanel{
          align-self:start;
        }

        .professionalActionList{
          display:grid;
          gap:0;
        }

        .professionalActionList .smartActionLine{
          display:flex;
          align-items:flex-start;
          justify-content:space-between;
          gap:14px;
          padding:12px 0;
          border-bottom:1px solid #edf2f8;
        }

        .professionalActionList .smartActionLine:last-child{
          border-bottom:0;
        }

        .professionalActionList .smartActionLine strong{
          display:block;
          color:#07152f;
          font-size:14px;
          font-weight:900;
        }

        .professionalActionList .smartActionLine span{
          display:block;
          margin-top:3px;
          color:#64748b;
          font-size:13px;
          font-weight:700;
        }

        .professionalActionList .smartActionLine em{
          color:#94a3b8;
          font-style:normal;
          font-size:12px;
          font-weight:850;
          white-space:nowrap;
        }

        .dashboardProgressPanel{
          margin-bottom:24px;
        }

        .professionalProgressList{
          gap:20px !important;
        }

        .professionalProgressList .modernProgressTrack span{
          background:linear-gradient(90deg,#0b63ff,#0057e7) !important;
        }

                .modernMetricIcon.blue{ background:#eaf2ff; color:#0b63ff; }
        .modernMetricIcon.green{ background:#dcfce7; color:#16a34a; }
        .modernMetricIcon.purple{ background:#eee9ff; color:#6d5dfc; }
        .modernMetricIcon.orange{ background:#ffeddc; color:#f97316; }
        
        
        
                        .smartDashboardGrid{
          display:grid;
          grid-template-columns:repeat(2,minmax(0,1fr));
          gap:16px;
          margin:18px 0;
          align-items:start;
        }

        .smartWide{
          grid-column:1 / -1;
        }

        .smartLiveStrip{
          padding:16px 18px;
        }

        .smartLiveStrip .smartCardHead{
          margin-bottom:10px;
        }

        .smartLiveStrip .smartSiteList{
          display:block;
        }

        .smartActionsCard .smartActionList{
          display:grid;
          grid-template-columns:repeat(2,minmax(0,1fr));
          column-gap:28px;
          row-gap:0;
        }

        .smartDashboardCard{
  background:#fff;
  border:1px solid rgba(15,23,42,.08);
  box-shadow:0 14px 34px rgba(15,23,42,.06);
  padding:18px;
  min-width:0;
  align-self:start;
}

        .smartDashboardCard.attention{
          border-color:rgba(245,158,11,.22);
          background:linear-gradient(180deg,#ffffff,#fffbeb);
        }

        .smartCardHead{
          display:flex;
          align-items:flex-start;
          justify-content:space-between;
          gap:14px;
          margin-bottom:14px;
        }

        .smartCardHead h2{
          margin:0;
          font-size:16px;
          font-weight:900;
          color:#07152f;
          letter-spacing:-.02em;
        }

        .smartCardHead p{
          margin:5px 0 0 0;
          color:#64748b;
          font-size:12px;
          font-weight:700;
          line-height:1.35;
        }

        .smartBadge{
          display:inline-flex;
          align-items:center;
          justify-content:center;
          white-space:nowrap;
          padding:6px 9px;
          font-size:11px;
          font-weight:900;
          border:1px solid transparent;
        }

        .smartBadge.ok{
          background:#dcfce7;
          color:#166534;
          border-color:#bbf7d0;
        }

        .smartBadge.bad{
          background:#fee2e2;
          color:#b91c1c;
          border-color:#fecaca;
        }

        .smartMiniLink{
          color:#0b63ff;
          font-size:12px;
          font-weight:900;
          white-space:nowrap;
        }

        .smartDashList,
        .smartActionList,
        .smartWarnings,
        .smartSiteList{
          display:grid;
          gap:8px;
        }

        .smartDashRow{
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:12px;
          padding:10px 0;
          border-bottom:1px solid rgba(15,23,42,.06);
          color:#07152f;
          font-size:13px;
          font-weight:800;
        }

        .smartDashRow:last-child{
          border-bottom:0;
        }

        .smartDashRow strong{
          font-size:13px;
          font-weight:900;
        }

        .smartDashRow strong.ok{
          color:#166534;
        }

        .smartDashRow strong.bad{
          color:#b91c1c;
        }

        .smartPayrollStats{
          display:grid;
          grid-template-columns:repeat(4,minmax(0,1fr));
          gap:10px;
          margin-bottom:14px;
        }

        .smartPayrollStats div{
          padding:12px 10px;
          background:#f8fbff;
          border:1px solid rgba(15,23,42,.06);
        }

        .smartPayrollStats span{
          display:block;
          color:#64748b;
          font-size:11px;
          font-weight:900;
          text-transform:uppercase;
          letter-spacing:.04em;
        }

        .smartPayrollStats strong{
          display:block;
          margin-top:4px;
          color:#07152f;
          font-size:22px;
          font-weight:900;
        }

        .smartWarningLine,
        .smartGoodLine,
        .smartEmptyLine{
          padding:9px 10px;
          background:#f8fafc;
          border:1px solid rgba(15,23,42,.06);
          color:#64748b;
          font-size:12px;
          font-weight:800;
        }

        .smartWarningLine{
          display:flex;
          justify-content:space-between;
          gap:12px;
          background:#fff7ed;
          border-color:#fed7aa;
          color:#9a3412;
        }

        .smartGoodLine{
          background:#f0fdf4;
          border-color:#bbf7d0;
          color:#166534;
        }

        .smartSitePill{
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:12px;
          padding:10px 12px;
          background:#eff6ff;
          border:1px solid #dbeafe;
          color:#1e40af;
          font-size:13px;
          font-weight:900;
        }

        .smartSitePill strong{
          color:#07152f;
        }

        .smartActionLine{
          display:flex;
          align-items:flex-start;
          justify-content:space-between;
          gap:12px;
          padding:10px 0;
          border-bottom:1px solid rgba(15,23,42,.06);
        }

        .smartActionLine:last-child{
          border-bottom:0;
        }

        .smartActionLine strong{
          display:block;
          color:#07152f;
          font-size:13px;
          font-weight:900;
        }

        .smartActionLine span{
          display:block;
          margin-top:3px;
          color:#64748b;
          font-size:12px;
          font-weight:700;
        }

        .smartActionLine em{
          color:#94a3b8;
          font-style:normal;
          font-size:11px;
          font-weight:800;
          white-space:nowrap;
        }

        @media (max-width: 1100px){
        
                  .professionalMainGrid,
          .dashboardActivityGrid{
            grid-template-columns:1fr !important;
          }

          .professionalLiveStrip{
            grid-template-columns:1fr;
            align-items:flex-start;
          }

          .professionalPayrollStats{
            grid-template-columns:repeat(2,minmax(0,1fr));
          }
        
                  .smartDashboardGrid{
            grid-template-columns:1fr;
          }

          .smartPayrollStats{
            grid-template-columns:repeat(2,minmax(0,1fr));
          }
          
  .dashboardShellModern{
    display:block !important;
    grid-template-columns:1fr !important;
  }

  .dashboardShellModern .main{
    padding:18px !important;
  }

  .modernMetricGrid{
    grid-template-columns:repeat(2,minmax(0,1fr));
  }

  .modernTwoCol{
    grid-template-columns:1fr;
  }

  .modernOnboardingCard{
    grid-template-columns:1fr;
  }
}
          .modernTwoCol{
            grid-template-columns:1fr;
          }
          .modernOnboardingCard{
            grid-template-columns:1fr;
          }
        }

                @media (max-width: 620px){
          .modernDashHeader{
            align-items:flex-start;
            flex-direction:column;
          }

          .modernMetricGrid{
            grid-template-columns:repeat(2,minmax(0,1fr)) !important;
            gap:14px !important;
          }

          /* Small metric cards only. Do not touch the joined Clock/Site card. */
          .modernMetricGrid > .modernMetricCard:not(.attendanceCombinedCard){
            position:relative !important;
            min-height:150px !important;
            padding:20px 16px 18px !important;
            display:block !important;
            overflow:hidden !important;
          }

          .modernMetricGrid > .modernMetricCard:not(.attendanceCombinedCard) > div:first-child{
            min-width:0 !important;
            max-width:none !important;
            padding-right:0 !important;
          }

          .modernMetricGrid > .modernMetricCard:not(.attendanceCombinedCard) .modernMetricLabel{
            font-size:14px !important;
            line-height:1.15 !important;
            margin:0 0 18px 0 !important;
            max-width:100% !important;
            white-space:nowrap !important;
            overflow:hidden !important;
            text-overflow:ellipsis !important;
          }

          .modernMetricGrid > .modernMetricCard:not(.attendanceCombinedCard) .modernMetricValue{
            font-size:34px !important;
            line-height:1 !important;
            letter-spacing:-0.04em !important;
            max-width:calc(100% - 64px) !important;
          }

          .modernMetricGrid > .modernMetricCard:not(.attendanceCombinedCard) .modernMetricSub{
            margin-top:10px !important;
            font-size:12px !important;
            line-height:1.25 !important;
            max-width:calc(100% - 64px) !important;
          }

          .modernMetricGrid > .modernMetricCard:not(.attendanceCombinedCard) .modernMetricIcon{
            position:absolute !important;
            right:14px !important;
            top:50% !important;
            transform:translateY(-50%) !important;
            width:52px !important;
            height:52px !important;
            min-width:52px !important;
            flex:0 0 52px !important;
            margin:0 !important;
          }

          .modernMetricGrid > .modernMetricCard:not(.attendanceCombinedCard) .modernMetricIcon svg{
            width:26px !important;
            height:26px !important;
          }

          .modernTimesheetTable th:nth-child(2),
          .modernTimesheetTable td:nth-child(2){
            display:none;
          }
        }
        
                @media (max-width: 380px){
          .modernMetricGrid{
            grid-template-columns:1fr !important;
          }

          .modernMetricGrid > .modernMetricCard:not(.attendanceCombinedCard){
            min-height:140px !important;
          }

          .modernMetricGrid > .modernMetricCard:not(.attendanceCombinedCard) .modernMetricValue,
          .modernMetricGrid > .modernMetricCard:not(.attendanceCombinedCard) .modernMetricSub{
            max-width:calc(100% - 72px) !important;
          }

          .modernMetricGrid > .modernMetricCard:not(.attendanceCombinedCard) .modernMetricIcon{
            right:16px !important;
            width:54px !important;
            height:54px !important;
            min-width:54px !important;
          }
        }
        
    
        
      </style>
    """

    reminder_is_employee = role not in ("admin", "master_admin")
    reminder_should_show = reminder_is_employee and not is_clocked_in and not completed_shift_today
    reminder_enabled_js = "true" if reminder_is_employee else "false"
    reminder_clocked_in_js = "true" if is_clocked_in else "false"
    reminder_should_show_js = "true" if reminder_should_show else "false"

    dashboard_geo_sites = []
    try:
        for loc in active_locations:
            site_name = str(
                loc.get("name")
                or loc.get("site_name")
                or loc.get("SiteName")
                or loc.get("Site")
                or ""
            ).strip()

            site_lat = safe_float(loc.get("lat"), None)
            site_lon = safe_float(loc.get("lon"), None)
            site_radius = safe_float(loc.get("radius"), 0.0)

            if site_name and site_lat is not None and site_lon is not None and site_radius > 0:
                dashboard_geo_sites.append({
                    "name": site_name,
                    "lat": float(site_lat),
                    "lon": float(site_lon),
                    "radius": float(site_radius),
                })
    except Exception:
        dashboard_geo_sites = []

    dashboard_geo_sites_json = json_mod.dumps(dashboard_geo_sites)

    current_site_metric_card_html = f"""
      <div class="modernMetricCard dashboardSiteCard" id="dashboardSiteCard" title="Current site">
        <div class="dashboardSiteText">
          <div class="modernMetricLabel">Current Site</div>
          <div class="modernMetricValue dashboardSiteValue" id="dashboardSiteLabel">{escape(dashboard_site_label)}</div>
          <div class="modernMetricSub" id="dashboardSiteSub">{escape(dashboard_site_sub)}</div>
        </div>
        <div class="modernMetricIcon maps" id="dashboardSiteIcon">
          <svg viewBox="0 0 24 24">
            <path d="M12 21s7-5.2 7-11a7 7 0 0 0-14 0c0 5.8 7 11 7 11z"></path>
            <circle cx="12" cy="10" r="2.5"></circle>
          </svg>
        </div>
      </div>
    """

    dashboard_site_geo_script_html = f"""
      <script>
        (function(){{
          const SITES = {dashboard_geo_sites_json};
          const card = document.getElementById("dashboardSiteCard") || document.querySelector(".dashboardSiteCard");
          const label = document.getElementById("dashboardSiteLabel");
          const sub = document.getElementById("dashboardSiteSub");
          const icon = document.getElementById("dashboardSiteIcon");

          if (!card || !label || !sub || !icon) return;

          function setIcon(tone){{
            icon.classList.remove("maps", "green", "blue", "purple", "orange");
            icon.classList.add(tone);
          }}

          function setSite(name, subtitle, tone){{
            label.textContent = name;
            sub.textContent = subtitle;
            setIcon(tone);

            if (tone === "green") {{
              card.classList.add("isOnSite");
            }} else {{
              card.classList.remove("isOnSite");
            }}
          }}

          function distanceMeters(lat1, lon1, lat2, lon2){{
            const R = 6371000;
            const toRad = function(v) {{ return v * Math.PI / 180; }};
            const dLat = toRad(lat2 - lat1);
            const dLon = toRad(lon2 - lon1);
            const a =
              Math.sin(dLat / 2) * Math.sin(dLat / 2) +
              Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
              Math.sin(dLon / 2) * Math.sin(dLon / 2);

            return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
          }}

          function nearestSite(lat, lon){{
            let best = null;

            for (const site of SITES) {{
              const sLat = Number(site.lat);
              const sLon = Number(site.lon);
              const radius = Number(site.radius || 0);

              if (!site.name || !Number.isFinite(sLat) || !Number.isFinite(sLon) || radius <= 0) {{
                continue;
              }}

              const dist = distanceMeters(lat, lon, sLat, sLon);
              const item = {{
                name: String(site.name),
                distance: dist,
                radius: radius,
                inside: dist <= radius
              }};

              if (!best || dist < best.distance) {{
                best = item;
              }}
            }}

            return best;
          }}

          if (!navigator.geolocation) {{
            setSite("Off site", "Location unavailable", "maps");
            return;
          }}

          if (!Array.isArray(SITES) || SITES.length === 0) {{
            setSite("Off site", "No site locations", "maps");
            return;
          }}

          navigator.geolocation.getCurrentPosition(function(pos){{
            const lat = Number(pos.coords.latitude);
            const lon = Number(pos.coords.longitude);
            const best = nearestSite(lat, lon);

            if (!best) {{
              setSite("Off site", "No nearby site", "maps");
              return;
            }}

            if (best.inside) {{
              setSite(best.name, "Location verified", "green");
            }} else {{
              setSite("Off site", "Nearest: " + best.name, "maps");
            }}
          }}, function(){{
            setSite("Off site", "Location unavailable", "maps");
          }}, {{
            enableHighAccuracy: true,
            timeout: 8000,
            maximumAge: 30000
          }});
        }})();
      </script>
    """




    content = f"""
      {modern_dashboard_css}

      <div class="modernDash">
        <div class="modernDashHeader">
          <div class="modernDashTitle">
            <h1>Dashboard</h1>
            <p>{escape(now.strftime("%A • %d %b %Y"))} • {escape(role_label(role))}</p>
          </div>

          <div class="modernTopUser">
                        <div class="modernNotifyWrap">
              <button class="modernBell" id="clockReminderBell" type="button" title="Clock-in reminders">
                <span class="modernBellDot" id="clockReminderDot" style="display:{'block' if reminder_should_show else 'none'};"></span>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#07152f" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7"></path>
                  <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
                </svg>
              </button>

              <div class="modernNotifyPanel" id="clockReminderPanel">
                <div class="modernNotifyTitle">Clock-in reminder</div>
                <div class="modernNotifyText" id="clockReminderText">
                  {'You have not clocked in yet today.' if reminder_should_show else 'No clock-in reminder right now.'}
                </div>
                <div class="modernNotifySmall">
                  Default reminder time: 08:00. Browser notifications need permission once.
                </div>
                <button class="modernNotifyBtn" id="enableClockReminderBtn" type="button">
                  Enable browser reminder
                </button>
              </div>
            </div>
            <div class="modernUserAvatar">{escape(_initials(display_name))}</div>
            <div>{escape(display_name)}</div>
          </div>
        </div>

                  <div class="modernMetricGrid">
          {clock_status_card_html}

                    <div class="modernMetricCard">
            <div>
              <div class="modernMetricLabel">Hours This Week</div>
              <div class="modernMetricValue">{escape(fmt_hours(week_hours))}</div>
              <div class="modernMetricSub">Total hours</div>
            </div>
            <div class="modernMetricIcon blue">
              <svg viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="9"></circle>
                <path d="M12 7v6l4 2"></path>
              </svg>
            </div>
          </div>

          <div class="modernMetricCard">
            <div>
              <div class="modernMetricLabel">{escape(metric_3_label)}</div>
              <div class="modernMetricValue">{escape(metric_3_value)}</div>
              <div class="modernMetricSub">{escape(metric_3_sub)}</div>
            </div>
            <div class="modernMetricIcon purple">
              <svg viewBox="0 0 24 24">
                <path d="M3 21h18"></path>
                <path d="M5 21V7l8-4v18"></path>
                <path d="M19 21V11l-6-4"></path>
                <path d="M9 9h1"></path>
                <path d="M9 13h1"></path>
                <path d="M9 17h1"></path>
              </svg>
            </div>
          </div>

          {current_site_metric_card_html if role in ("admin", "master_admin") else ""}
        </div>
                {dashboard_site_geo_script_html}

        {smart_dashboard_html}

                <div class="modernTwoCol dashboardActivityGrid {'singleCol' if role not in ('admin', 'master_admin') else ''}">
          <div class="modernPanel modernTimesheetsPanel">
            <div class="modernPanelHeaderRow">
              <div>
                <h2 class="modernPanelTitle">Recent Timesheets</h2>
                <p class="modernPanelSub">Latest completed time records.</p>
              </div>
              <a class="modernPanelLink small" href="{"/admin/log-activities" if role in ("admin", "master_admin") else "/my-times"}">View all ›</a>
            </div>

            <table class="modernTimesheetTable">
              <thead>
                <tr>
                  <th>Worker</th>
                  <th>Site</th>
                  <th>Date</th>
                  <th style="text-align:right;">Hours</th>
                </tr>
              </thead>
              <tbody>
                {modern_recent_rows}
              </tbody>
            </table>
          </div>

          {recent_activity_panel_html}
        </div>

        <div class="modernPanel dashboardProgressPanel">
          <div class="modernPanelHeaderRow">
            <div>
              <h2 class="modernPanelTitle">{'Work Progress' if role in ('admin', 'master_admin') else 'My Week'}</h2>
              <p class="modernPanelSub">{'Projects overview' if role in ('admin', 'master_admin') else 'Your work summary'}</p>
            </div>
            <a class="modernPanelLink small" href="{"/work-progress" if role in ("admin", "master_admin") else "/clock"}">
              {'View all projects ›' if role in ('admin', 'master_admin') else 'Open clock page ›'}
            </a>
          </div>

          <div class="modernProgressList professionalProgressList">
            <div>
              <div class="modernProgressTop"><span>Weekly hours target</span><span>{week_progress_pct}%</span></div>
              <div class="modernProgressTrack"><span style="width:{week_progress_pct}%;"></span></div>
            </div>

            <div>
              <div class="modernProgressTop"><span>{escape(progress_2_label)}</span><span>{progress_2_pct}%</span></div>
              <div class="modernProgressTrack"><span style="width:{progress_2_pct}%;"></span></div>
            </div>

            <div>
              <div class="modernProgressTop"><span>{escape(progress_3_label)}</span><span>{progress_3_pct}%</span></div>
              <div class="modernProgressTrack"><span style="width:{progress_3_pct}%;"></span></div>
            </div>

            <div>
              <div class="modernProgressTop"><span>{escape(progress_4_label)}</span><span>{progress_4_pct}%</span></div>
              <div class="modernProgressTrack"><span style="width:{progress_4_pct}%;"></span></div>
            </div>
          </div>
        </div>

        <div class="modernOnboardingCard">
          <div class="modernDocIcon">
            <svg viewBox="0 0 24 24">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <path d="M14 2v6h6"></path>
              <path d="M8 13h8"></path>
              <path d="M8 17h6"></path>
            </svg>
          </div>

          <div>
            <div class="modernOnboardingTitle">{escape(onboarding_card_title)}</div>
            <div class="modernOnboardingText">
              {escape(onboarding_card_text)}
            </div>
          </div>

          <div>
            <div class="modernOnboardingProgressLabel">{escape(onboarding_card_progress_label)}</div>
            <div class="modernProgressTrack"><span style="width:{onboarding_card_pct}%;"></span></div>
          </div>

          <a class="modernBtn" href="{escape(onboarding_card_url)}">{escape(onboarding_card_button)}</a>
        </div>
        
        
                <script>
          (function(){{
            var isEmployee = {reminder_enabled_js};
            var isClockedIn = {reminder_clocked_in_js};
            var shouldShowReminder = {reminder_should_show_js};

            var bell = document.getElementById("clockReminderBell");
            var panel = document.getElementById("clockReminderPanel");
            var btn = document.getElementById("enableClockReminderBtn");
            var dot = document.getElementById("clockReminderDot");
            var text = document.getElementById("clockReminderText");

            if (!bell || !panel) return;

            function closePanel(){{
              panel.classList.remove("open");
            }}

            function openPanel(){{
              panel.classList.add("open");
            }}

            bell.addEventListener("click", function(e){{
              e.preventDefault();
              e.stopPropagation();
              panel.classList.toggle("open");
            }});

            document.addEventListener("click", function(e){{
              if (!panel.contains(e.target) && !bell.contains(e.target)) {{
                closePanel();
              }}
            }});

            function canNotify(){{
              return "Notification" in window;
            }}

            function showBrowserReminder(){{
  if (!isEmployee || isClockedIn || !shouldShowReminder) return;
              if (!canNotify()) return;
              if (Notification.permission !== "granted") return;

              new Notification("TimIQ reminder", {{
                body: "You have not clocked in yet. Please clock in when you arrive on site.",
                icon: "/static/icon-192.png"
              }});
            }}

            function updatePanel(){{
              if (!isEmployee) {{
                if (text) text.textContent = "Admin notifications will be added here later.";
                if (btn) btn.style.display = "none";
                if (dot) dot.style.display = "none";
                return;
              }}

              if (isClockedIn) {{
  if (text) text.textContent = "You are already clocked in.";
  if (dot) dot.style.display = "none";
}} else if (shouldShowReminder) {{
  if (text) text.textContent = "You have not clocked in yet today.";
  if (dot) dot.style.display = "block";
}} else {{
  if (text) text.textContent = "No clock-in reminder right now.";
  if (dot) dot.style.display = "none";
}}

              if (!canNotify()) {{
                if (btn) {{
                  btn.disabled = true;
                  btn.textContent = "Browser notifications not supported";
                }}
                return;
              }}

              if (Notification.permission === "granted") {{
                if (btn) btn.textContent = "Browser reminder enabled";
              }} else if (Notification.permission === "denied") {{
                if (btn) {{
                  btn.disabled = true;
                  btn.textContent = "Notifications blocked in browser";
                }}
              }} else {{
                if (btn) btn.textContent = "Enable browser reminder";
              }}
            }}

            if (btn) {{
              btn.addEventListener("click", function(e){{
                e.preventDefault();
                e.stopPropagation();

                if (!canNotify()) return;

                Notification.requestPermission().then(function(permission){{
                  updatePanel();

                  if (permission === "granted" && shouldShowReminder) {{
                    showBrowserReminder();
                  }}
                }});
              }});
            }}

            function scheduleReminderCheck(){{
  if (!isEmployee || isClockedIn || !shouldShowReminder) return;

              var now = new Date();
              var hour = now.getHours();
              var minute = now.getMinutes();

              // Default reminder: after 08:00, if employee is not clocked in.
              if (hour > 8 || (hour === 8 && minute >= 0)) {{
                showBrowserReminder();
              }}

              // Keep reminding every 30 minutes while the dashboard/app is open.
              window.setInterval(function(){{
                showBrowserReminder();
              }}, 30 * 60 * 1000);
            }}

            updatePanel();
            scheduleReminderCheck();
          }})();
        </script>
        
        
        
        
      </div>
    """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("home", role, content, shell_class="dashboardShellModern")
    )
