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
    week_days = set()

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

        try:
            d_obj = datetime.strptime(d_str, "%Y-%m-%d").date()
            if d_obj >= monday:
                week_hours += h_val
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

    employee_count = 0
    clocked_in_count = 0
    active_locations_count = 0
    onboarding_pending_count = 0

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
                    if done_flag not in ("true", "1", "yes"):
                        onboarding_pending_count += 1
    except Exception:
        pass

    try:
        for s in _get_open_shifts():
            clocked_in_count += 1
    except Exception:
        pass

    try:
        active_locations_count = len(_get_active_locations())
    except Exception:
        active_locations_count = 0

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

        .modernBell{
          width:42px;
          height:42px;
          display:flex;
          align-items:center;
          justify-content:center;
          border-radius:999px;
          background:#fff;
          border:1px solid #e4ebf5;
          box-shadow:0 10px 24px rgba(15,23,42,.06);
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
        .modernMetricIcon.orange{ background:#ffeddc; color:#f97316; }

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

        @media (max-width: 1100px){
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
            grid-template-columns:1fr;
          }
          .modernMetricCard{
            min-height:auto;
          }
          .modernTimesheetTable th:nth-child(2),
          .modernTimesheetTable td:nth-child(2){
            display:none;
          }
        }
      </style>
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
            <div class="modernBell" title="Notifications">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#07152f" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7"></path>
                <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
              </svg>
            </div>
            <div class="modernUserAvatar">{escape(_initials(display_name))}</div>
            <div>{escape(display_name)}</div>
          </div>
        </div>

        <div class="modernMetricGrid">
          <div class="modernMetricCard">
            <div>
              <div class="modernMetricLabel">Active Workers</div>
              <div class="modernMetricValue">{clocked_in_count if role in ("admin", "master_admin") else ("1" if is_clocked_in else "0")}</div>
              <div class="modernMetricSub">On site today</div>
            </div>
            <div class="modernMetricIcon blue">
              <svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M22 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
            </div>
          </div>

          <div class="modernMetricCard">
            <div>
              <div class="modernMetricLabel">Hours This Week</div>
              <div class="modernMetricValue">{escape(fmt_hours(week_hours))}</div>
              <div class="modernMetricSub">Total hours</div>
            </div>
            <div class="modernMetricIcon green">
              <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"></circle><path d="M12 7v6l4 2"></path></svg>
            </div>
          </div>

          <div class="modernMetricCard">
            <div>
              <div class="modernMetricLabel">Sites</div>
              <div class="modernMetricValue">{active_locations_count}</div>
              <div class="modernMetricSub">Active workplaces</div>
            </div>
            <div class="modernMetricIcon purple">
              <svg viewBox="0 0 24 24"><path d="M3 21h18"></path><path d="M5 21V7l8-4v18"></path><path d="M19 21V11l-6-4"></path><path d="M9 9h1"></path><path d="M9 13h1"></path><path d="M9 17h1"></path></svg>
            </div>
          </div>

          <div class="modernMetricCard">
            <div>
              <div class="modernMetricLabel">Forms</div>
              <div class="modernMetricValue">{onboarding_pending_count}</div>
              <div class="modernMetricSub">Pending</div>
            </div>
            <div class="modernMetricIcon orange">
              <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path><path d="M8 13h8"></path><path d="M8 17h6"></path></svg>
            </div>
          </div>
        </div>

        <div class="modernTwoCol">
          <div class="modernPanel">
            <h2 class="modernPanelTitle">Recent Timesheets</h2>
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
            <a class="modernPanelLink" href="{"/admin/log-activities" if role in ("admin", "master_admin") else "/my-times"}">View all timesheets ›</a>
          </div>

          <div class="modernPanel">
            <h2 class="modernPanelTitle">Work Progress</h2>
            <p class="modernPanelSub">Projects overview</p>

            <div class="modernProgressList">
              <div>
                <div class="modernProgressTop"><span>Weekly hours target</span><span>{week_progress_pct}%</span></div>
                <div class="modernProgressTrack"><span style="width:{week_progress_pct}%;"></span></div>
              </div>

              <div>
                <div class="modernProgressTop"><span>Clocked in now</span><span>{clocked_pct}%</span></div>
                <div class="modernProgressTrack"><span style="width:{clocked_pct}%;"></span></div>
              </div>

              <div>
                <div class="modernProgressTop"><span>Onboarding complete</span><span>{forms_pct}%</span></div>
                <div class="modernProgressTrack"><span style="width:{forms_pct}%;"></span></div>
              </div>

              <div>
                <div class="modernProgressTop"><span>Active sites setup</span><span>{sites_pct}%</span></div>
                <div class="modernProgressTrack"><span style="width:{sites_pct}%;"></span></div>
              </div>
            </div>

            <a class="modernPanelLink" href="/work-progress">View all projects ›</a>
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
            <div class="modernOnboardingTitle">Onboarding</div>
            <div class="modernOnboardingText">
              {onboarding_pending_count if role in ("admin", "master_admin") else "Review your"} starter forms need attention.
            </div>
          </div>

          <div>
            <div class="modernOnboardingProgressLabel">{completed_onboarding} / {onboarding_total} completed</div>
            <div class="modernProgressTrack"><span style="width:{onboarding_pct}%;"></span></div>
          </div>

          <a class="modernBtn" href="{"/admin/onboarding" if role in ("admin", "master_admin") else "/onboarding"}">View onboarding</a>
        </div>
      </div>
    """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("home", role, content, shell_class="dashboardShellModern")
    )
