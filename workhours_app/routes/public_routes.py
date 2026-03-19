"""Route registrations extracted from the legacy monolith.

This keeps the original endpoint names and handler bodies intact while
reducing the size of the main runtime module.
"""

from workhours_app.route_dependencies import (
    CLOCKIN_EARLIEST,
    CLOCK_SELFIE_DIR,
    CLOCK_SELFIE_REQUIRED,
    COL_DATE,
    COL_HOURS,
    COL_IN,
    COL_OUT,
    COL_PAY,
    COL_USER,
    DB_MIGRATION_MODE,
    OVERTIME_HOURS,
    OnboardingRecord,
    TZ,
    WorkHour,
    _apply_unpaid_break,
    _cache_invalidate_prefix,
    _clear_active_session_token,
    _client_ip,
    _ensure_workhours_geo_headers,
    _find_employee_record,
    _find_workhours_row_by_user_date,
    _get_active_locations,
    _get_employee_site,
    _get_open_shifts,
    _get_site_config,
    _get_user_rate,
    _gs_write_with_retry,
    _issue_active_session_token,
    _login_rate_limit_check,
    _login_rate_limit_clear,
    _login_rate_limit_hit,
    _make_oauth_flow,
    _render_onboarding_page,
    _sanitize_clock_geo,
    _save_drive_token,
    _session_workplace_id,
    _store_clock_selfie,
    _svg_chart,
    _svg_clipboard,
    _svg_clock,
    _svg_doc,
    _svg_grid,
    _svg_user,
    _validate_recent_clock_capture,
    _validate_user_location,
    abort,
    app,
    datetime,
    db,
    employees_sheet,
    escape,
    find_open_shift,
    fmt_hours,
    get_company_settings,
    get_csrf,
    get_employee_display_name,
    get_onboarding_record,
    get_workhours_rows,
    gspread,
    has_any_row_today,
    is_password_valid,
    json,
    log_audit,
    math,
    migrate_password_if_plain,
    money,
    normalized_clock_in_time,
    onboarding_details_block,
    or_,
    os,
    parse_bool,
    redirect,
    render_app_page,
    render_standalone_page,
    request,
    require_admin,
    require_csrf,
    require_login,
    role_label,
    safe_float,
    send_file,
    session,
    set_employee_field,
    set_employee_first_last,
    settings_sheet,
    spreadsheet,
    timedelta,
    update_employee_password,
    update_or_append_onboarding,
    upload_to_drive,
    url_for,
    user_in_same_workplace,
    work_sheet,
)

@app.get("/clock-selfie/<path:filename>")
def view_clock_selfie(filename):
    gate = require_admin()
    if gate:
        return gate

    safe_filename = os.path.basename(filename or "")
    if not safe_filename:
        abort(404)

    full_path = os.path.abspath(os.path.join(CLOCK_SELFIE_DIR, safe_filename))
    base_path = os.path.abspath(CLOCK_SELFIE_DIR)
    if not full_path.startswith(base_path + os.sep):
        abort(403)
    if not os.path.exists(full_path):
        abort(404)

    ext = os.path.splitext(safe_filename)[1].lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(ext, "application/octet-stream")
    return send_file(full_path, mimetype=mime)


@app.get("/manifest.webmanifest")
def manifest():
    return {
        "name": "WorkHours",
        "short_name": "WorkHours",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f6f8fb",
        "theme_color": "#ffffff",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }, 200, {"Content-Type": "application/manifest+json"}


@app.get("/ping")
def ping():
    return "pong", 200


@app.get("/connect-drive")
def connect_drive():
    gate = require_login()
    if gate:
        return gate
    if session.get("role") != "master_admin":
        return redirect(url_for("home"))

    flow = _make_oauth_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["oauth_code_verifier"] = getattr(flow, "code_verifier", None)
    session["oauth_state"] = state
    return redirect(auth_url)


@app.get("/oauth2callback")
def oauth2callback():
    gate = require_login()
    if gate:
        return gate
    if session.get("role") != "master_admin":
        return redirect(url_for("home"))

    returned_state = request.args.get("state")
    expected_state = session.get("oauth_state")
    if not expected_state or returned_state != expected_state:
        abort(400)
    session.pop("oauth_state", None)

    flow = _make_oauth_flow()
    flow.code_verifier = session.get("oauth_code_verifier")
    flow.fetch_token(authorization_response=request.url)
    session.pop("oauth_code_verifier", None)
    creds_user = flow.credentials

    token_dict = {
        "token": creds_user.token,
        "refresh_token": creds_user.refresh_token,
        "token_uri": creds_user.token_uri,
        "client_id": creds_user.client_id,
        "client_secret": creds_user.client_secret,
        "scopes": creds_user.scopes,
    }
    session["drive_connected"] = True
    _save_drive_token(token_dict)
    return redirect(url_for("home"))


@app.route("/login", methods=["GET", "POST"])
def login():
    msg = session.pop("_login_notice", "") if request.method == "GET" else ""
    csrf = get_csrf()

    if request.method == "POST":
        require_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        workplace_id = (request.form.get("workplace_id", "") or "").strip() or "default"
        # Allow entering Company_Name instead of Workplace_ID
        try:
            if settings_sheet and workplace_id:
                svals = settings_sheet.get_all_values()
                if svals and len(svals) > 1:
                    sh = svals[0]
                    i_wp = sh.index("Workplace_ID") if "Workplace_ID" in sh else None
                    i_name = sh.index("Company_Name") if "Company_Name" in sh else None
                    if i_wp is not None and i_name is not None:
                        typed = workplace_id.strip().lower()
                        for rr in svals[1:]:
                            nm = (rr[i_name] if i_name < len(rr) else "").strip().lower()
                            if nm and nm == typed:
                                workplace_id = ((rr[i_wp] if i_wp < len(rr) else "").strip() or workplace_id)
                                break
        except Exception:
            pass

        ip = _client_ip()

        allowed, retry_after = _login_rate_limit_check(ip)
        if not allowed:
            log_audit("LOGIN_LOCKED", actor=ip, username=username, date_str="", details=f"RetryAfter={retry_after}s")
            mins = max(1, int(math.ceil(retry_after / 60)))
            msg = f"Too many login attempts. Try again in {mins} minute(s)."
        else:
            ok_user = None
            if not DB_MIGRATION_MODE:
                try:
                    sid = getattr(spreadsheet, "id", None)
                    wid = getattr(employees_sheet, "id", None)
                    if sid and wid:
                        _cache_invalidate_prefix((sid, wid))
                except Exception:
                    pass

            ok_user = _find_employee_record(username, workplace_id)

            if ok_user and is_password_valid(ok_user.get("Password", ""), password):
                active_raw = str(ok_user.get("Active", "") or "").strip().lower()
                is_active = active_raw not in ("false", "0", "no", "n", "off")

                if not is_active:
                    _login_rate_limit_hit(ip)
                    log_audit("LOGIN_INACTIVE", actor=ip, username=username, date_str="",
                              details="Inactive account login attempt")
                    msg = "Invalid login"
                else:
                    _login_rate_limit_clear(ip)

                    migrate_password_if_plain(username, ok_user.get("Password", ""), password, workplace_id=workplace_id)
                    active_session_token = _issue_active_session_token(username, workplace_id)
                    if not active_session_token:
                        log_audit("LOGIN_SESSION_FAIL", actor=ip, username=username, date_str="",
                                  details=f"Could not start active session workplace={workplace_id}")
                        msg = "Could not start secure session. Please try again."
                    else:
                        session.clear()
                        session["csrf"] = csrf
                        session["username"] = username
                        session["workplace_id"] = workplace_id
                        session["role"] = (ok_user.get("Role", "employee") or "employee").strip().lower()
                        session["rate"] = safe_float(ok_user.get("Rate", 0), 0.0)
                        session["early_access"] = parse_bool(ok_user.get("EarlyAccess", False))
                        session["active_session_token"] = active_session_token
                        return redirect(url_for("home"))
            else:
                _login_rate_limit_hit(ip)
                log_audit("LOGIN_FAIL", actor=ip, username=username, date_str="",
                          details="Invalid username or password")
                msg = "Invalid login"

    html = f"""
    <div class="shell" style="grid-template-columns:1fr; max-width:560px;">
      <div class="main">
        <div class="headerTop">
          <div>
            <h1>WorkHours</h1>
            <p class="sub">Sign in</p>
          </div>
          <div class="badge">Secure</div>
        </div>

        <div class="card" style="padding:14px;">
          <form method="POST">
            <input type="hidden" name="csrf" value="{escape(csrf)}">
            <label class="sub">User</label>
            <input class="input" name="username" required>
            <label class="sub" style="margin-top:10px; display:block;">Workplace ID</label>
            <input class="input" name="workplace_id" value="" placeholder="e.g. default" required>
            <label class="sub" style="margin-top:10px; display:block;">Password</label>
            <input class="input" type="password" name="password" required>
            <button class="btnSoft" type="submit" style="margin-top:12px;">Login</button>
          </form>
          {("<div class='message error'>" + escape(msg) + "</div>") if msg else ""}
        </div>
      </div>
    </div>
    """
    return render_standalone_page(html)


@app.get("/logout")
def logout_confirm():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    role = session.get("role", "employee")

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Logout</h1>
          <p class="sub">Are you sure you want to log out?</p>
        </div>
        <div class="badge {'admin' if role == 'admin' else ''}">{escape(role.upper())}</div>
      </div>

      <div class="card" style="padding:14px;">
        <form method="POST" action="/logout" style="margin:0;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <div class="actionRow" style="grid-template-columns: 1fr 1fr;">
            <a href="/" style="display:block;">
              <button class="btnSoft" type="button" style="width:100%;">Cancel</button>
            </a>
            <button class="btnOut" type="submit" style="width:100%;">Logout</button>
          </div>
        </form>
      </div>
    """
    return render_app_page("home", role, content)


@app.post("/logout")
def logout():
    require_csrf()
    username = (session.get("username") or "").strip()
    workplace_id = (session.get("workplace_id") or "default").strip() or "default"
    active_session_token = str(session.get("active_session_token") or "")
    if username and active_session_token:
        _clear_active_session_token(username, workplace_id, expected_token=active_session_token)
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def home():
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

    monday = today - timedelta(days=today.weekday())

    def week_key_for_n(n: int):
        d2 = monday - timedelta(days=7 * n)
        yy, ww, _ = d2.isocalendar()
        return yy, ww

    dashboard_weeks = 8
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
            if row_wp != current_wp:
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

    max_g = max(weekly_gross) if weekly_gross else 0.0
    max_g = max(max_g, 1.0)

    prev_gross = round(weekly_gross[-2], 2) if len(weekly_gross) >= 2 else 0.0
    curr_gross = round(weekly_gross[-1], 2)

    admin_item = ""
    if role in ("admin", "master_admin"):
        admin_item = f"""
        <a class="menuItem nav-admin" href="/admin">
          <div class="menuLeft"><div class="icoBox">{_svg_grid()}</div><div class="menuText">Admin</div></div>
          <div class="chev">›</div>
        </a>
        """

    workplaces_item = ""
    if role == "master_admin":
        workplaces_item = f"""
        <a class="menuItem nav-home" href="/admin/workplaces">
          <div class="menuLeft"><div class="icoBox">{_svg_grid()}</div><div class="menuText">Workplaces</div></div>
          <div class="chev">›</div>
        </a>
        """
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
            if row_wp != current_wp:
                continue
        else:
            if not user_in_same_workplace(row_user):
                continue

        recent_rows.append({
            "date": (r[COL_DATE] if len(r) > COL_DATE else "") or "",
            "cin": (r[COL_IN] if len(r) > COL_IN else "") or "",
            "cout": (r[COL_OUT] if len(r) > COL_OUT else "") or "",
            "hours": (r[COL_HOURS] if len(r) > COL_HOURS else "") or "",
            "pay": (r[COL_PAY] if len(r) > COL_PAY else "") or "",
        })

    recent_rows = sorted(recent_rows, key=lambda x: x["date"], reverse=True)[:5]

    if recent_rows:
        activity_html = """
          <div class="activityRow activityHead">
            <div>Date</div><div>In</div><div>Out</div><div>Hours</div><div>Pay</div>
          </div>
        """
        for rr in recent_rows:
            activity_html += f"""
              <div class="activityRow">
                <div>{escape(rr['date'])}</div>
                <div>{escape((rr['cin'] or '')[:5])}</div>
                <div>{escape((rr['cout'] or '')[:5])}</div>
                <div>{escape(fmt_hours(rr['hours']))}</div>
                <div>{escape(currency)}{escape(rr['pay'])}</div>
              </div>
            """
    else:
        activity_html = "<div class='activityEmpty'>No recent activity yet.</div>"
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

        if role not in ("admin", "master_admin") and row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != current_wp:
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

    is_clocked_in = bool(find_open_shift(rows, username))
    status_text = "Clocked In" if is_clocked_in else "Clocked Out"
    status_class = "ok" if is_clocked_in else "warn"
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
                    if row_wp != current_wp:
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

    snapshot_html = ""
    if role in ("admin", "master_admin"):
        snapshot_html = f"""
          <div class="card sideInfoCard">
            <div class="sectionHead">
              <div class="sectionHeadLeft">
                <div class="sectionIcon">{_svg_grid()}</div>
                <div>
                  <h2 style="margin:0;">Business Snapshot</h2>
                  <p class="sub" style="margin:4px 0 0 0;">Current workplace overview.</p>
                </div>
              </div>
              <div class="sectionBadge">Live</div>
            </div>

            <div class="sideInfoList">
              <div class="sideInfoRow">
                <div class="sideInfoLabel">Employees</div>
                <div class="sideInfoValue">{employee_count}</div>
              </div>

              <div class="sideInfoRow">
                <div class="sideInfoLabel">Clocked In Now</div>
                <div class="sideInfoValue">{clocked_in_count}</div>
              </div>

              <div class="sideInfoRow">
                <div class="sideInfoLabel">Active Locations</div>
                <div class="sideInfoValue">{active_locations_count}</div>
              </div>

              <div class="sideInfoRow">
                <div class="sideInfoLabel">Onboarding Pending</div>
                <div class="sideInfoValue">{onboarding_pending_count}</div>
              </div>
            </div>
          </div>
        """

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Dashboard</h1>
          <p class="sub">Welcome, {escape(display_name)}</p>
        </div>
        <div class="badge {'admin' if role in ('admin', 'master_admin') else ''}">{escape(role_label(role))}</div>
      </div>
<div class="kpiRow">
  <div class="card kpi kpiFancy">
    <div class="kpiTop">
      <p class="label">Previous Gross</p>
      <span class="chip">Week total</span>
    </div>
    <p class="value">{escape(currency)}{money(prev_gross)}</p>
    <p class="sub">Previous week</p>
  </div>

  <div class="card kpi kpiFancy kpiPrimary">
    <div class="kpiTop">
      <p class="label">Current Gross</p>
      <span class="chip {'ok' if curr_gross >= prev_gross else 'warn'}">
        {'▲' if curr_gross >= prev_gross else '▼'}
        {money(((curr_gross - prev_gross) / (prev_gross if prev_gross > 0 else 1.0)) * 100.0)}%
      </span>
    </div>
    <p class="value">{escape(currency)}{money(curr_gross)}</p>
    <p class="sub">This week (so far)</p>
  </div>
</div>

          <div class="card graphCard">
        <div class="graphTop">
          <div>
            <div class="graphTitle">Weekly Gross</div>
            <div class="sub">Last 8 weeks performance</div>
          </div>
          <div class="graphRange">Weeks {escape(week_labels[0])} – {escape(week_labels[-1])}</div>
        </div>

        <div class="graphShell">
          <div class="bars">
            {''.join([
        f"""
              <div class="barCol">
                <div class="barValue">{escape(currency)}{money(g)}</div>
                <div class="barTrack">
                  <div class="bar" style="height:{int((g / max_g) * 165)}px;"></div>
                </div>
              </div>
              """
        for g in weekly_gross
    ])}
          </div>

          <div class="barLabels">
            {''.join([f"<div>{escape(x)}</div>" for x in week_labels])}
          </div>
        </div>
      </div>

      <div class="dashboardLower">
        <div class="card quickCard">
          <div class="quickGrid">
            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_clock()}</div>
                <div class="miniText">Status</div>
              </div>
              <div class="chip {status_class}">{status_text}</div>
            </div>

            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_clipboard()}</div>
                <div class="miniText">Today Hours</div>
              </div>
              <div class="miniText">{fmt_hours(today_hours)}</div>
            </div>

            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_chart()}</div>
                <div class="miniText">Today Gross</div>
              </div>
              <div class="miniText">{escape(currency)}{money(today_pay)}</div>
            </div>

            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_grid()}</div>
                <div class="miniText">Week Hours</div>
              </div>
              <div class="miniText">{fmt_hours(week_hours)}</div>
            </div>

            <div class="quickMini">
              <div class="left">
                <div class="miniIcon">{_svg_doc()}</div>
                <div class="miniText">Days Logged</div>
              </div>
              <div class="miniText">{len(week_days)}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="dashboardBottom">
        <div class="card activityCard">
          <div class="sectionHead">
            <div class="sectionHeadLeft">
              <div class="sectionIcon">{_svg_clipboard()}</div>
              <div>
                <h2 style="margin:0;">Recent Activity</h2>
                <p class="sub" style="margin:4px 0 0 0;">Latest logged work entries.</p>
              </div>
            </div>
            <div class="sectionBadge">Last 5 rows</div>
          </div>

          <div class="activityList">
            {activity_html}
          </div>
        </div>

        {snapshot_html}
      </div>

      <div class="card menu dashboardMainMenu">
  <a class="menuItem nav-clock" href="/clock">
    <div class="menuLeft"><div class="icoBox">{_svg_clock()}</div><div class="menuText">Clock In & Out</div></div>
    <div class="chev">›</div>
  </a>
  <a class="menuItem nav-times" href="/my-times">
    <div class="menuLeft"><div class="icoBox">{_svg_clipboard()}</div><div class="menuText">Time logs</div></div>
    <div class="chev">›</div>
  </a>
  <a class="menuItem nav-reports" href="/my-reports">
    <div class="menuLeft"><div class="icoBox">{_svg_chart()}</div><div class="menuText">Timesheets</div></div>
    <div class="chev">›</div>
  </a>
  <a class="menuItem nav-agreements" href="/onboarding">
    <div class="menuLeft"><div class="icoBox">{_svg_doc()}</div><div class="menuText">Starter Form</div></div>
    <div class="chev">›</div>
  </a>
  {admin_item}
  {workplaces_item}
  <a class="menuItem nav-profile" href="/password">
    <div class="menuLeft"><div class="icoBox">{_svg_user()}</div><div class="menuText">Profile</div></div>
    <div class="chev">›</div>
  </a>
</div>
    """
    return render_app_page("home", role, content)


@app.route("/clock", methods=["GET", "POST"])
def clock_page():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

    rate = _get_user_rate(username)
    early_access = bool(session.get("early_access", False))

    now = datetime.now(TZ)
    today_str = now.strftime("%Y-%m-%d")

    # Geo-fence config (employee assigned site -> Locations sheet)
    _ensure_workhours_geo_headers()
    site_pref = _get_employee_site(username)
    site_cfg = _get_site_config(site_pref)  # may be None

    msg = ""
    msg_class = "message"

    def _read_float(name):
        try:
            v = (request.form.get(name) or "").strip()
            return float(v) if v else None
        except Exception:
            return None

    if request.method == "POST":
        require_csrf()
        action = (request.form.get("action") or "").strip()
        selfie_data = (request.form.get("selfie_data") or "").strip()

        if CLOCK_SELFIE_REQUIRED and action in ("in", "out") and not selfie_data:
            msg = "Selfie is required before clocking in or out."
            msg_class = "message error"
        else:
            lat_v = _read_float("lat")
            lon_v = _read_float("lon")
            acc_v = _read_float("acc")

            try:
                if lat_v is not None and lon_v is not None:
                    _validate_recent_clock_capture(request.form.get("geo_ts"), now)
                    lat_v, lon_v, acc_v = _sanitize_clock_geo(lat_v, lon_v, acc_v)
                ok_loc, cfg, dist_m = _validate_user_location(username, lat_v, lon_v, acc_v)

                if not ok_loc:
                    if not site_cfg and not cfg.get("radius"):
                        msg = "Location system is not configured. Ask Admin to create Locations sheet and set your Site."
                    elif lat_v is None or lon_v is None:
                        msg = "Location is required. Please allow location access and try again."
                    else:
                        msg = f"Outside site radius. Distance: {int(dist_m)}m (limit {int(cfg['radius'])}m) • Site: {cfg['name']}"
                    msg_class = "message error"
                else:
                    rows = work_sheet.get_all_values()

                    if action == "in":
                        open_shift = find_open_shift(rows, username)

                        if open_shift:
                            msg = "You are already clocked in."
                            msg_class = "message error"

                        elif has_any_row_today(rows, username, today_str):
                            msg = "You already completed your shift for today."
                            msg_class = "message error"

                        else:
                            selfie_url = _store_clock_selfie(selfie_data, username, "clock_in", now) if CLOCK_SELFIE_REQUIRED else ""
                            cin = normalized_clock_in_time(now, early_access)

                            headers_now = work_sheet.row_values(1)
                            new_row = [username, today_str, cin, "", "", ""]

                            if headers_now and "Workplace_ID" in headers_now:
                                wp_idx = headers_now.index("Workplace_ID")
                                if len(new_row) <= wp_idx:
                                    new_row += [""] * (wp_idx + 1 - len(new_row))
                                new_row[wp_idx] = _session_workplace_id()

                            if headers_now and len(new_row) < len(headers_now):
                                new_row += [""] * (len(headers_now) - len(new_row))

                            _gs_write_with_retry(lambda: work_sheet.append_row(new_row, value_input_option="USER_ENTERED"))

                            vals = work_sheet.get_all_values()
                            rownum = _find_workhours_row_by_user_date(vals, username, today_str)
                            if rownum:
                                headers = vals[0] if vals else []

                                def _col(name):
                                    return headers.index(name) + 1 if name in headers else None

                                import copy

                                updates = []
                                for k, v in [
                                    ("InLat", lat_v), ("InLon", lon_v), ("InAcc", acc_v),
                                    ("InSite", cfg.get("name", "")), ("InDistM", int(dist_m)),
                                    ("InSelfieURL", selfie_url), ("Workplace_ID", _session_workplace_id()),
                                ]:
                                    c = _col(k)
                                    if c:
                                        updates.append({
                                            "range": gspread.utils.rowcol_to_a1(rownum, c),
                                            "values": [["" if v is None else v]],
                                        })

                                if updates:
                                    _gs_write_with_retry(lambda: work_sheet.batch_update(copy.deepcopy(updates)))

                                if DB_MIGRATION_MODE:
                                    try:
                                        shift_date = datetime.strptime(today_str, "%Y-%m-%d").date()
                                        clock_in_dt = datetime.strptime(f"{today_str} {cin}", "%Y-%m-%d %H:%M:%S")

                                        db_row = WorkHour.query.filter(
                                            WorkHour.employee_email == username,
                                            WorkHour.date == shift_date,
                                            or_(WorkHour.workplace_id == _session_workplace_id(), WorkHour.workplace == _session_workplace_id()),
                                        ).order_by(WorkHour.id.desc()).first()

                                        if db_row:
                                            db_row.clock_in = clock_in_dt
                                            db_row.clock_out = None
                                            db_row.in_selfie_url = selfie_url
                                        else:
                                            db.session.add(
                                                WorkHour(
                                                    employee_email=username,
                                                    date=shift_date,
                                                    clock_in=clock_in_dt,
                                                    clock_out=None,
                                                    workplace=_session_workplace_id(),
                                                    workplace_id=_session_workplace_id(),
                                                    in_selfie_url=selfie_url,
                                                )
                                            )

                                        db.session.commit()
                                    except Exception:
                                        db.session.rollback()

                            if (not early_access) and (now.time() < CLOCKIN_EARLIEST):
                                msg = f"Clocked in successfully (counted from 08:00) • {cfg['name']} ({int(dist_m)}m)"
                            else:
                                msg = f"Clocked in successfully • {cfg['name']} ({int(dist_m)}m)"

                    elif action == "out":
                        osf = find_open_shift(rows, username)

                        if not osf:
                            if has_any_row_today(rows, username, today_str):
                                msg = "You already clocked out today."
                            else:
                                msg = "No active shift found."
                            msg_class = "message error"

                        else:
                            selfie_url = _store_clock_selfie(selfie_data, username, "clock_out", now) if CLOCK_SELFIE_REQUIRED else ""
                            i, d, t = osf
                            cin_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
                            raw_hours = max(0.0, (now - cin_dt).total_seconds() / 3600.0)
                            hours_rounded = round(_apply_unpaid_break(raw_hours), 2)
                            pay = round(hours_rounded * float(rate), 2)

                            sheet_row = i + 1
                            cout = now.strftime("%H:%M:%S")

                            updates = [
                                {
                                    "range": f"{gspread.utils.rowcol_to_a1(sheet_row, COL_OUT + 1)}:{gspread.utils.rowcol_to_a1(sheet_row, COL_PAY + 1)}",
                                    "values": [[cout, hours_rounded, pay]],
                                }
                            ]

                            vals = work_sheet.get_all_values()
                            headers = vals[0] if vals else []

                            def _col(name):
                                return headers.index(name) + 1 if name in headers else None

                            for k, v in [
                                ("OutLat", lat_v), ("OutLon", lon_v), ("OutAcc", acc_v),
                                ("OutSite", cfg.get("name", "")), ("OutDistM", int(dist_m)),
                                ("OutSelfieURL", selfie_url),
                            ]:
                                c = _col(k)
                                if c:
                                    updates.append({
                                        "range": gspread.utils.rowcol_to_a1(sheet_row, c),
                                        "values": [["" if v is None else str(v)]],
                                    })

                            import copy
                            if updates:
                                _gs_write_with_retry(lambda: work_sheet.batch_update(copy.deepcopy(updates)))

                            if DB_MIGRATION_MODE:
                                try:
                                    shift_date = datetime.strptime(d, "%Y-%m-%d").date()
                                    clock_out_dt = datetime.strptime(f"{d} {cout}", "%Y-%m-%d %H:%M:%S")
                                    clock_in_dt_check = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")

                                    if clock_out_dt < clock_in_dt_check:
                                        clock_out_dt = clock_out_dt + timedelta(days=1)

                                    db_row = WorkHour.query.filter(
                                        WorkHour.employee_email == username,
                                        WorkHour.date == shift_date,
                                        or_(WorkHour.workplace_id == _session_workplace_id(), WorkHour.workplace == _session_workplace_id()),
                                    ).order_by(WorkHour.id.desc()).first()

                                    if db_row:
                                        db_row.clock_out = clock_out_dt
                                        db_row.out_selfie_url = selfie_url
                                    else:
                                        db.session.add(
                                            WorkHour(
                                                employee_email=username,
                                                date=shift_date,
                                                clock_in=None,
                                                clock_out=clock_out_dt,
                                                workplace=_session_workplace_id(),
                                                workplace_id=_session_workplace_id(),
                                                out_selfie_url=selfie_url,
                                            )
                                        )

                                    db.session.commit()
                                except Exception:
                                    db.session.rollback()

                            msg = f"Clocked out successfully • {cfg['name']} ({int(dist_m)}m) • Total today: {hours_rounded:.2f}h"

                    else:
                        msg = "Invalid action."
                        msg_class = "message error"
            except Exception as e:
                if isinstance(e, RuntimeError):
                    msg = str(e) or "Unable to process selfie."
                    msg_class = "message error"
                else:
                    app.logger.exception("Clock POST failed")
                    msg = "Internal error while saving. Please refresh and try again."
                    msg_class = "message error"

    # Active shift timer
    rows2 = work_sheet.get_all_values()
    osf2 = find_open_shift(rows2, username)
    active_start_iso = ""
    active_start_label = ""
    if osf2:
        _, d, t = osf2
        try:
            start_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
            active_start_iso = start_dt.isoformat()
            active_start_label = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    if active_start_iso:
        timer_html = f"""
        <div class="clockStatus clockStatusLive">Clocked in</div>
        <div class="timerBig" id="timerDisplay">00:00:00</div>
        <div class="clockHint">Started at {escape(active_start_label)}</div>
        <div class="timerSub">
          <span class="chip ok" id="otChip">Normal</span>
        </div>
        <script>
          (function() {{
            const startIso = "{escape(active_start_iso)}";
            const start = new Date(startIso);
            const el = document.getElementById("timerDisplay");
            function pad(n) {{ return String(n).padStart(2, "0"); }}
            function tick() {{
              const now = new Date();
              let diff = Math.floor((now - start) / 1000);
              if (diff < 0) diff = 0;
              const h = Math.floor(diff / 3600);
              const m = Math.floor((diff % 3600) / 60);
              const s = diff % 60;
              el.textContent = pad(h) + ":" + pad(m) + ":" + pad(s);

              const otEl = document.getElementById("otChip");
              if (otEl) {{
                const startedAtEight = (start.getHours() === 8 && start.getMinutes() === 0);
                const overtime = startedAtEight && (diff >= 9 * 3600);
                if (overtime) {{
                  otEl.textContent = "Overtime";
                  otEl.className = "chip warn";
                }} else {{
                  otEl.textContent = "Normal";
                  otEl.className = "chip ok";
                }}
              }}
            }}
            tick(); setInterval(tick, 1000);
          }})();
        </script>
        """
    else:
        timer_html = f"""
        <div class="clockStatus clockStatusIdle">Not clocked in</div>
        <div class="timerBig">00:00:00</div>
        <div class="clockHint">Tap Clock In to start your shift.</div>
        """

    # Map config for front-end (if site configured)
    if site_cfg:
        site_json = json.dumps(
            {"name": site_cfg["name"], "lat": site_cfg["lat"], "lon": site_cfg["lon"], "radius": site_cfg["radius"]})
    else:
        site_json = json.dumps(None)

    leaflet_tags = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin=""/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
"""

    content = f"""
      {leaflet_tags}

{f'''
<div class="statusCard {'statusCardError' if msg_class=='message error' else 'statusCardOk'}">
  <div class="statusCardTitle">{'Attention needed' if msg_class=='message error' else 'Status'}</div>
  <div class="statusCardText">{escape(msg)}</div>
</div>
''' if msg else ""}

<div class="card clockCard">
  <div class="clockTop">
    <div class="clockStateWrap">
      {timer_html}
    </div>
  </div>

  <div class="clockPanel">
    <div id="geoStatus">📍 Waiting for location…</div>
  </div>

  <div class="clockPanel">
    <div id="map" style="height:240px; min-height:240px; border-radius:14px; overflow:hidden; border:1px solid #dbe5f1;"></div>
  </div>

  <div class="clockPanel" style="padding:14px;">
    <div style="display:flex; justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap;">
      <div>
        <div style="font-weight:700; color:var(--navy);">Selfie required</div>
        <div class="sub">Take a selfie before clocking in or out.</div>
      </div>
      <div style="display:flex; gap:8px; flex-wrap:wrap;">
        <button class="btnSoft" id="takeSelfieBtn" type="button">Take selfie</button>
        <button class="btnSoft" id="retakeSelfieBtn" type="button" disabled>Retake</button>
      </div>
    </div>

    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px;">
      <video id="selfieVideo" autoplay playsinline muted style="width:100%; border-radius:14px; border:1px solid #dbe5f1; background:#0f172a; min-height:220px; object-fit:cover;"></video>
      <img id="selfiePreview" alt="Selfie preview" style="width:100%; border-radius:14px; border:1px solid #dbe5f1; background:#f8fafc; min-height:220px; object-fit:cover; display:none;">
    </div>
    <canvas id="selfieCanvas" style="display:none;"></canvas>
    <div id="selfieStatus" class="sub" style="margin-top:10px;">No selfie captured yet.</div>
  </div>

  <form method="POST" class="actionRow" id="geoClockForm">
  <input type="hidden" name="csrf" value="{escape(csrf)}">
  <input type="hidden" name="action" id="geoAction" value="">
  <input type="hidden" name="lat" id="geoLat" value="">
  <input type="hidden" name="lon" id="geoLon" value="">
  <input type="hidden" name="acc" id="geoAcc" value="">
  <input type="hidden" name="geo_ts" id="geoTs" value="">
  <input type="hidden" name="selfie_data" id="selfieData" value="">

  <button class="btn btnIn" id="btnClockIn" type="button">Clock In</button>
  <button class="btn btnOut" id="btnClockOut" type="button">Clock Out</button>
</form>

    <a href="/my-times">
      <button class="btnSoft" type="button">View time logs</button>
    </a>
  </div>
</div>

      <script>
        (function(){{
          const SITE = {site_json};
          const statusEl = document.getElementById("geoStatus");
          const form = document.getElementById("geoClockForm");
          const act = document.getElementById("geoAction");
          const latEl = document.getElementById("geoLat");
          const lonEl = document.getElementById("geoLon");
          const accEl = document.getElementById("geoAcc");
          const geoTsEl = document.getElementById("geoTs");

          const btnIn = document.getElementById("btnClockIn");
          const btnOut = document.getElementById("btnClockOut");
          const selfieDataEl = document.getElementById("selfieData");
          const selfieVideo = document.getElementById("selfieVideo");
          const selfiePreview = document.getElementById("selfiePreview");
          const selfieCanvas = document.getElementById("selfieCanvas");
          const selfieStatus = document.getElementById("selfieStatus");
          const takeSelfieBtn = document.getElementById("takeSelfieBtn");
          const retakeSelfieBtn = document.getElementById("retakeSelfieBtn");
          let selfieStream = null;
          let selfieTriedAutostart = false;

          function setDisabled(v){{
            btnIn.disabled = v;
            btnOut.disabled = v;
            btnIn.style.opacity = v ? "0.6" : "1";
            btnOut.style.opacity = v ? "0.6" : "1";
          }}

          // Map
          let map = null;
          let siteMarker = null;
          let radiusCircle = null;
          let youMarker = null;

          function initMap(){{
            const start = SITE ? [SITE.lat, SITE.lon] : [51.505, -0.09];
            map = L.map("map", {{ zoomControl: true }}).setView(start, SITE ? 16 : 5);
            L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
              maxZoom: 19,
              attribution: "&copy; OpenStreetMap"
            }}).addTo(map);

            if(SITE){{
              siteMarker = L.marker([SITE.lat, SITE.lon]).addTo(map).bindPopup(SITE.name);
              radiusCircle = L.circle([SITE.lat, SITE.lon], {{
                radius: SITE.radius
              }}).addTo(map);
            }}
          }}

          function haversineMeters(lat1, lon1, lat2, lon2){{
            const R = 6371000;
            const toRad = (x)=> x * Math.PI / 180;
            const dLat = toRad(lat2-lat1);
            const dLon = toRad(lon2-lon1);
            const a = Math.sin(dLat/2)*Math.sin(dLat/2) +
                      Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*
                      Math.sin(dLon/2)*Math.sin(dLon/2);
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            return R * c;
          }}

          function updateStatus(lat, lon, acc){{
            if(!SITE){{
              statusEl.textContent = "📍 Location captured (no site configured)";
              return;
            }}
            const dist = haversineMeters(lat, lon, SITE.lat, SITE.lon);
            const ok = dist <= SITE.radius;
            statusEl.textContent = ok
              ? `📍 Location OK: ${{SITE.name}} (${{Math.round(dist)}}m)`
              : `📍 Outside radius: ${{Math.round(dist)}}m (limit ${{Math.round(SITE.radius)}}m)`;
            statusEl.style.color = ok ? "var(--green)" : "var(--red)";
          }}

          function updateYouMarker(lat, lon){{
            if(!map) return;
            if(!youMarker){{
              youMarker = L.marker([lat, lon]).addTo(map);
            }} else {{
              youMarker.setLatLng([lat, lon]);
            }}
          }}

          function stopSelfieCamera(){{
            if(selfieStream){{
              selfieStream.getTracks().forEach(track => track.stop());
              selfieStream = null;
            }}
            selfieVideo.srcObject = null;
            takeSelfieBtn.disabled = true;
          }}

          async function startSelfieCamera(){{
            if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){{
              selfieStatus.textContent = "Camera preview is not supported on this device/browser.";
              return;
            }}
            try {{
              stopSelfieCamera();
              selfieStream = await navigator.mediaDevices.getUserMedia({{ video: {{ facingMode: "user", width: {{ ideal: 1280 }}, height: {{ ideal: 720 }} }}, audio: false }});
              selfieVideo.srcObject = selfieStream;
              if (selfieVideo.play) {{
                try {{ await selfieVideo.play(); }} catch(e) {{}}
              }}
              takeSelfieBtn.disabled = false;
              selfieStatus.textContent = "Camera ready. Take your selfie.";
            }} catch(err) {{
              console.log(err);
              selfieStatus.textContent = "Could not open camera. Please allow camera permission and try again.";
            }}
          }}

          function setSelfieData(dataUrl){{
            selfieDataEl.value = dataUrl || "";
            if(dataUrl){{
              selfiePreview.src = dataUrl;
              selfiePreview.style.display = "block";
              retakeSelfieBtn.disabled = false;
              selfieStatus.textContent = "Selfie ready.";
            }} else {{
              selfiePreview.src = "";
              selfiePreview.style.display = "none";
              retakeSelfieBtn.disabled = true;
              selfieStatus.textContent = "No selfie captured yet.";
            }}
          }}

          function captureSelfieFrame(){{
            if(!selfieVideo || !selfieVideo.videoWidth || !selfieVideo.videoHeight){{
              alert("Open the camera first, then take your selfie.");
              return;
            }}
            const maxW = 960;
            const scale = Math.min(1, maxW / selfieVideo.videoWidth);
            const width = Math.max(320, Math.round(selfieVideo.videoWidth * scale));
            const height = Math.max(240, Math.round(selfieVideo.videoHeight * scale));
            selfieCanvas.width = width;
            selfieCanvas.height = height;
            const ctx = selfieCanvas.getContext("2d");
            ctx.drawImage(selfieVideo, 0, 0, width, height);
            const dataUrl = selfieCanvas.toDataURL("image/jpeg", 0.88);
            setSelfieData(dataUrl);
            stopSelfieCamera();
          }}

          function requestLocationAndSubmit(actionValue){{
            if(!selfieDataEl.value){{
              alert("Please take a selfie before clocking in or out.");
              selfieStatus.textContent = "Selfie required before clocking in or out.";
              return;
            }}
            
            stopSelfieCamera();
            
            if(!navigator.geolocation){{
              alert("Geolocation is not supported on this device/browser.");
              return;
            }}
            setDisabled(true);
            statusEl.style.color = "var(--muted)";
            statusEl.textContent = "📍 Getting your location…";

            navigator.geolocation.getCurrentPosition((pos)=>{{
              const lat = pos.coords.latitude;
              const lon = pos.coords.longitude;
              const acc = pos.coords.accuracy;

              latEl.value = lat;
              lonEl.value = lon;
              accEl.value = acc;
              geoTsEl.value = String(Date.now());

              updateStatus(lat, lon, acc);
              updateYouMarker(lat, lon);

              act.value = actionValue;
              form.submit();
            }}, (err)=>{{
              console.log(err);
              alert("Location is required to clock in/out. Please allow location permission and try again.");
              statusEl.textContent = "📍 Location required. Please allow permission.";
              statusEl.style.color = "var(--red)";
              setDisabled(false);
            }}, {{
              enableHighAccuracy: true,
              timeout: 12000,
              maximumAge: 0
            }});
          }}

                    initMap();

          // Try to show status + marker before pressing buttons
          if(navigator.geolocation){{
            navigator.geolocation.getCurrentPosition((pos)=>{{
              const lat = pos.coords.latitude;
              const lon = pos.coords.longitude;
              const acc = pos.coords.accuracy;
              updateStatus(lat, lon, acc);
              updateYouMarker(lat, lon);
            }}, ()=>{{
              statusEl.textContent = "📍 Location required. Please allow permission.";
              statusEl.style.color = "var(--red)";
            }}, {{ enableHighAccuracy:true, timeout: 8000, maximumAge: 0 }});
          }}

          takeSelfieBtn.addEventListener("click", async ()=> {{
  const hasLiveCamera = !!(selfieStream || (selfieVideo && selfieVideo.srcObject));

  if(!hasLiveCamera){{
    await startSelfieCamera();
    selfieStatus.textContent = "Camera ready. Tap Take selfie again to capture.";
    return;
  }}

  captureSelfieFrame();
}});

          retakeSelfieBtn.addEventListener("click", ()=> {{
            setSelfieData("");
            startSelfieCamera();
          }});

          window.addEventListener("pagehide", ()=> {{
            stopSelfieCamera();
          }});

          window.addEventListener("beforeunload", ()=> {{
            stopSelfieCamera();
          }});

          document.addEventListener("visibilitychange", ()=> {{
            if(document.hidden){{
              stopSelfieCamera();
            }}
          }});
          takeSelfieBtn.disabled = false;
          selfieStatus.textContent = "Tap Take selfie to open the camera.";

          btnIn.addEventListener("click", ()=> requestLocationAndSubmit("in"));
          btnOut.addEventListener("click", ()=> requestLocationAndSubmit("out"));
        }})();
      </script>
    """
    return render_app_page("clock", role, content)


@app.get("/my-times")
def my_times():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")

    rows = work_sheet.get_all_values()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    body = []
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        if len(r) <= COL_USER:
            continue
        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        # Workplace filter (only if WorkHours has Workplace_ID column)
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != current_wp:
                continue
        else:
            # Backward compat if sheet has no Workplace_ID column
            if not user_in_same_workplace(row_user):
                continue

        body.append(
            f"<tr><td>{escape(r[COL_DATE])}</td><td>{escape(r[COL_IN])}</td>"
            f"<td>{escape(r[COL_OUT])}</td><td class='num'>{escape(r[COL_HOURS])}</td><td class='num'>{escape(currency)}{escape(r[COL_PAY])}</td></tr>"
        )
    table = "".join(body) if body else "<tr><td colspan='5'>No records yet.</td></tr>"

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Time logs</h1>
          <p class="sub">{escape(display_name)} • Clock history</p>
        </div>
        <div class="badge {'admin' if role == 'admin' else ''}">{escape(role.upper())}</div>
      </div>

      <div class="card payrollShell" style="padding:12px;">
        <div class="tablewrap">
          <table style="min-width:640px;">
            <thead><tr><th>Date</th><th>Clock In</th><th>Clock Out</th><th class="num" style="text-align:center;">Hours</th>
<th class="num" style="text-align:center;">Pay</th>
</tr></thead>
            <tbody>{table}</tbody>
          </table>
        </div>
      </div>
    """
    return render_app_page("times", role, content)


@app.get("/my-reports")
def my_reports():
    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")

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
            if row_wp != current_wp:
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

    # week dropdown
    week_options = []
    for i in range(0, 52):
        d0 = this_monday - timedelta(days=7 * i)
        d1 = d0 + timedelta(days=6)
        iso = d0.isocalendar()
        label = f"Week {iso[1]} ({d0.strftime('%d %b')} – {d1.strftime('%d %b %Y')})"
        selected = "selected" if i == wk_offset else ""
        week_options.append(f"<option value='{i}' {selected}>{escape(label)}</option>")

    # weekly rows
    rows_html = []
    for i in range(7):
        d = selected_week_start + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        item = week_map[d_str]

        hours_val = round(item["hours"], 2)
        gross_val = round(item["gross"], 2)
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
      .myReportsTopGrid{
        margin-top:12px;
        display:grid;
        grid-template-columns: 1fr 1fr;
        gap:12px;
      }

      .myReportsMonthCard{
        margin-top:12px;
      }

      .myReportsWeekPicker{
        margin-top:12px;
        padding:12px;
      }

      .myReportsWeekTable{
        margin-top:12px;
        padding:10px;
      }

      .myReportsWeekTable .tablewrap{
        margin-top:10px;
      }

      .myReportsWeekTable .payrollSummaryBar{
  margin-top: 10px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.myReportsWeekTable .payrollSummaryItem{
  padding: 6px 8px;
  border-radius: 12px;
}

.myReportsWeekTable .payrollSummaryItem .k{
  font-size: 10px;
}

.myReportsWeekTable .payrollSummaryItem .v{
  font-size: 14px;
  line-height: 1.1;
}

.myReportsWeekTable .payrollSummaryItem:nth-child(1),
.myReportsWeekTable .payrollSummaryItem:nth-child(2),
.myReportsWeekTable .payrollSummaryItem:nth-child(3),
.myReportsWeekTable .payrollSummaryItem:nth-child(4){
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
  border-color: rgba(11,18,32,.08);
}

.myReportsWeekTable .payrollSummaryItem:nth-child(1) .k,
.myReportsWeekTable .payrollSummaryItem:nth-child(2) .k,
.myReportsWeekTable .payrollSummaryItem:nth-child(3) .k,
.myReportsWeekTable .payrollSummaryItem:nth-child(4) .k{
  color: var(--muted);
}

.myReportsWeekTable .payrollSummaryItem:nth-child(1) .v,
.myReportsWeekTable .payrollSummaryItem:nth-child(2) .v,
.myReportsWeekTable .payrollSummaryItem:nth-child(3) .v,
.myReportsWeekTable .payrollSummaryItem:nth-child(4) .v{
  color: rgba(15,23,42,.96);
}
      .myReportsWeekTable .weeklyEditTable{
        table-layout: fixed;
        width: 100%;
        min-width: 0;
      }

      .myReportsWeekTable .weeklyEditTable thead th,
.myReportsWeekTable .weeklyEditTable tbody td{
  padding: 7px 3px;
  font-size: 12px;
}

      .myReportsWeekTable .weeklyEditTable thead th{
  white-space: nowrap;
  letter-spacing: 0;
  font-size: 10px;
}

      .myReportsWeekTable .weeklyEditTable tbody td{
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .myReportsWeekTable .weeklyEditTable th:nth-child(1),
.myReportsWeekTable .weeklyEditTable td:nth-child(1){
  width: 38px;
}

.myReportsWeekTable .weeklyEditTable th:nth-child(2),
.myReportsWeekTable .weeklyEditTable td:nth-child(2){
  width: 78px;
  text-align: center;
}

.myReportsWeekTable .weeklyEditTable th:nth-child(3),
.myReportsWeekTable .weeklyEditTable td:nth-child(3),
.myReportsWeekTable .weeklyEditTable th:nth-child(4),
.myReportsWeekTable .weeklyEditTable td:nth-child(4){
  width: 56px;
  text-align: center;
}

.myReportsWeekTable .weeklyEditTable th:nth-child(5),
.myReportsWeekTable .weeklyEditTable td:nth-child(5){
  width: 46px;
}

.myReportsWeekTable .weeklyEditTable th:nth-child(6),
.myReportsWeekTable .weeklyEditTable td:nth-child(6),
.myReportsWeekTable .weeklyEditTable th:nth-child(7),
.myReportsWeekTable .weeklyEditTable td:nth-child(7){
  width: 64px;
}

      @media (max-width: 780px){
  .myReportsTopGrid{
    grid-template-columns: 1fr;
  }

  .myReportsWeekTable{
    padding:6px;
  }

  .myReportsWeekTable .tablewrap{
    margin-top:8px;
    border-radius:14px;
  }

  .myReportsWeekTable .weeklyEditTable thead th,
  .myReportsWeekTable .weeklyEditTable tbody td{
    padding: 7px 3px;
    font-size: 11px;
  }

  .myReportsWeekTable .weeklyEditTable th:nth-child(1),
.myReportsWeekTable .weeklyEditTable td:nth-child(1){
  width: 32px;
}

.myReportsWeekTable .weeklyEditTable th:nth-child(2),
.myReportsWeekTable .weeklyEditTable td:nth-child(2){
  width: 68px;
  text-align: center;
}

.myReportsWeekTable .weeklyEditTable th:nth-child(3),
.myReportsWeekTable .weeklyEditTable td:nth-child(3),
.myReportsWeekTable .weeklyEditTable th:nth-child(4),
.myReportsWeekTable .weeklyEditTable td:nth-child(4){
  width: 48px;
}

.myReportsWeekTable .weeklyEditTable th:nth-child(5),
.myReportsWeekTable .weeklyEditTable td:nth-child(5){
  width: 38px;
}

.myReportsWeekTable .weeklyEditTable th:nth-child(6),
.myReportsWeekTable .weeklyEditTable td:nth-child(6),
.myReportsWeekTable .weeklyEditTable th:nth-child(7),
.myReportsWeekTable .weeklyEditTable td:nth-child(7){
  width: 54px;
}

  .payrollSummaryBar{
    grid-template-columns: 1fr 1fr;
    gap:8px;
  }

  .payrollSummaryItem{
    padding:8px 10px;
    border-radius:14px;
  }

  .payrollSummaryItem .k{
    font-size:11px;
  }

  .payrollSummaryItem .v{
    font-size:16px;
  }
}

    </style>
    """

    week_label = f"Week {selected_week_start.isocalendar()[1]} ({selected_week_start.strftime('%d %b')} – {selected_week_end.strftime('%d %b %Y')})"

    content = f"""
      {page_css}

      <div class="headerTop">
        <div>
          <h1>Timesheets</h1>
          <p class="sub">{escape(display_name)} • Totals + tax + net</p>
        </div>
        <div class="badge {'admin' if role == 'admin' else ''}">{escape(role.upper())}</div>
      </div>

      <div class="myReportsTopGrid">
        <div class="card kpi">
          <p class="label">Today Gross</p>
          <p class="value">{escape(currency)}{money(d_g)}</p>
          <p class="sub">Hours: {escape(fmt_hours(daily_hours))} • Tax: {escape(currency)}{money(d_t)} • Net: {escape(currency)}{money(d_n)}</p>
        </div>

        <div class="card kpi">
          <p class="label">Selected Week Gross</p>
          <p class="value">{escape(currency)}{money(w_g)}</p>
          <p class="sub">Hours: {escape(fmt_hours(selected_week_hours))} • Tax: {escape(currency)}{money(w_t)} • Net: {escape(currency)}{money(w_n)}</p>
        </div>
      </div>

      <div class="card kpi myReportsMonthCard">
        <p class="label">This Month Gross</p>
        <p class="value">{escape(currency)}{money(m_g)}</p>
        <p class="sub">Hours: {escape(fmt_hours(month_hours))} • Tax: {escape(currency)}{money(m_t)} • Net: {escape(currency)}{money(m_n)}</p>
      </div>

      <div class="card myReportsWeekPicker">
        <form method="GET">
          <label class="sub" style="display:block; margin-bottom:6px;">Choose week</label>
          <select class="input" name="wk" onchange="this.form.submit()">
            {''.join(week_options)}
          </select>
        </form>
      </div>

      <div class="card myReportsWeekTable">
        <div style="margin-bottom:12px;">
          <div style="font-size:30px; font-weight:800; line-height:1.1; color:rgba(15,23,42,.96);">
            {escape(display_name)}
          </div>
          <div class="sub" style="margin-top:6px;">{escape(week_label)}</div>
        </div>

        <div class="tablewrap">
          <table class="weeklyEditTable">
            <colgroup>
  <col style="width:38px;">
  <col style="width:78px;">
  <col style="width:56px;">
  <col style="width:56px;">
  <col style="width:46px;">
  <col style="width:64px;">
  <col style="width:64px;">
</colgroup>
            <thead>
              <tr>
                <th>Day</th>
                <th>Date</th>
                <th>Clock In</th>
                <th>Clock Out</th>
                <th class="num">Hours</th>
                <th class="num">Gross</th>
                <th class="num">Net</th>
              </tr>
            </thead>
            <tbody>
              {''.join(rows_html)}
            </tbody>
          </table>
        </div>

        <div class="payrollSummaryBar">
          <div class="payrollSummaryItem">
            <div class="k">Hours</div>
            <div class="v">{escape(fmt_hours(selected_week_hours))}</div>
          </div>

          <div class="payrollSummaryItem">
            <div class="k">Gross</div>
            <div class="v">{escape(currency)}{money(w_g)}</div>
          </div>

          <div class="payrollSummaryItem">
            <div class="k">Tax</div>
            <div class="v">{escape(currency)}{money(w_t)}</div>
          </div>

          <div class="payrollSummaryItem net">
            <div class="k">Net</div>
            <div class="v">{escape(currency)}{money(w_n)}</div>
          </div>
        </div>
      </div>
    """

    return render_app_page("reports", role, content)


@app.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)
    existing = get_onboarding_record(username)

    msg = ""
    msg_ok = False

    typed = None
    missing_fields = set()

    if request.method == "POST":
        require_csrf()
        typed = request.form.to_dict(flat=True)
        submit_type = request.form.get("submit_type", "draft")
        is_final = (submit_type == "final")

        def g(name):
            return (request.form.get(name, "") or "").strip()

        first = g("first");
        last = g("last");
        birth = g("birth")
        phone_cc = g("phone_cc") or "+44";
        phone_num = g("phone_num")
        street = g("street");
        city = g("city");
        postcode = g("postcode")
        email = g("email")
        ec_name = g("ec_name");
        ec_cc = g("ec_cc") or "+44";
        ec_phone = g("ec_phone")
        medical = g("medical");
        medical_details = g("medical_details")
        position = g("position");
        cscs_no = g("cscs_no");
        cscs_exp = g("cscs_exp")
        emp_type = g("emp_type");
        rtw = g("rtw")
        ni = g("ni");
        utr = g("utr");
        start_date = g("start_date")
        acc_no = g("acc_no");
        sort_code = g("sort_code");
        acc_name = g("acc_name")
        comp_trading = g("comp_trading");
        comp_reg = g("comp_reg")
        contract_date = g("contract_date");
        site_address = g("site_address")
        contract_accept = (request.form.get("contract_accept", "") == "yes")
        signature_name = g("signature_name")

        passport_file = request.files.get("passport_file")
        cscs_file = request.files.get("cscs_file")
        pli_file = request.files.get("pli_file")
        share_file = request.files.get("share_file")

        missing = []

        def req(value, input_name, label):
            if not value:
                missing.append(label)
                missing_fields.add(input_name)

        if is_final:
            req(first, "first", "First Name")
            req(last, "last", "Last Name")
            req(birth, "birth", "Birth Date")
            req(phone_num, "phone_num", "Phone Number")
            req(email, "email", "Email")
            req(ec_name, "ec_name", "Emergency Contact Name")
            req(ec_phone, "ec_phone", "Emergency Contact Phone")

            if medical not in ("yes", "no"):
                missing.append("Medical condition (Yes/No)")
                missing_fields.add("medical")

            req(position, "position", "Position")
            req(cscs_no, "cscs_no", "CSCS Number")
            req(cscs_exp, "cscs_exp", "CSCS Expiry Date")
            req(emp_type, "emp_type", "Employment Type")

            if rtw not in ("yes", "no"):
                missing.append("Right to work UK (Yes/No)")
                missing_fields.add("rtw")

            req(ni, "ni", "National Insurance")
            req(utr, "utr", "UTR")
            req(start_date, "start_date", "Start Date")
            req(acc_no, "acc_no", "Bank Account Number")
            req(sort_code, "sort_code", "Sort Code")
            req(acc_name, "acc_name", "Account Holder Name")
            req(contract_date, "contract_date", "Date of Contract")
            req(site_address, "site_address", "Site address")

            if not contract_accept:
                missing.append("Contract acceptance")
                missing_fields.add("contract_accept")

            req(signature_name, "signature_name", "Signature name")

            if not passport_file or not passport_file.filename:
                missing.append("Passport/Birth Certificate file")
                missing_fields.add("passport_file")
            if not cscs_file or not cscs_file.filename:
                missing.append("CSCS (front/back) file")
                missing_fields.add("cscs_file")
            if not pli_file or not pli_file.filename:
                missing.append("Public Liability file")
                missing_fields.add("pli_file")
            if not share_file or not share_file.filename:
                missing.append("Share code file")
                missing_fields.add("share_file")

        if missing:
            msg = "Missing required (final): " + ", ".join(missing)
            msg_ok = False
        else:
            def v(key: str) -> str:
                return (existing or {}).get(key, "")

            passport_link = v("PassportOrBirthCertLink")
            cscs_link = v("CSCSFrontBackLink")
            pli_link = v("PublicLiabilityLink")
            share_link = v("ShareCodeLink")

            try:
                if passport_file and passport_file.filename:
                    passport_link = upload_to_drive(passport_file, f"{username}_passport")
                if cscs_file and cscs_file.filename:
                    cscs_link = upload_to_drive(cscs_file, f"{username}_cscs")
                if pli_file and pli_file.filename:
                    pli_link = upload_to_drive(pli_file, f"{username}_pli")
                if share_file and share_file.filename:
                    share_link = upload_to_drive(share_file, f"{username}_share")
            except Exception as e:
                msg = f"Upload error: {e}"
                msg_ok = False
                existing = get_onboarding_record(username)
                return render_app_page(
                    "agreements",
                    role,
                    _render_onboarding_page(display_name, role, csrf, existing, msg, msg_ok, typed, set()),
                )

            now_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

            data = {
                "FirstName": first,
                "LastName": last,
                "BirthDate": birth,
                "PhoneCountryCode": phone_cc,
                "PhoneNumber": phone_num,
                "StreetAddress": street,
                "City": city,
                "Postcode": postcode,
                "Email": email,
                "EmergencyContactName": ec_name,
                "EmergencyContactPhoneCountryCode": ec_cc,
                "EmergencyContactPhoneNumber": ec_phone,
                "MedicalCondition": medical,
                "MedicalDetails": medical_details,
                "Position": position,
                "CSCSNumber": cscs_no,
                "CSCSExpiryDate": cscs_exp,
                "EmploymentType": emp_type,
                "RightToWorkUK": rtw,
                "NationalInsurance": ni,
                "UTR": utr,
                "StartDate": start_date,
                "BankAccountNumber": acc_no,
                "SortCode": sort_code,
                "AccountHolderName": acc_name,
                "CompanyTradingName": comp_trading,
                "CompanyRegistrationNo": comp_reg,
                "DateOfContract": contract_date,
                "SiteAddress": site_address,
                "PassportOrBirthCertLink": passport_link,
                "CSCSFrontBackLink": cscs_link,
                "PublicLiabilityLink": pli_link,
                "ShareCodeLink": share_link,
                "ContractAccepted": "TRUE" if (is_final and contract_accept) else "FALSE",
                "SignatureName": signature_name,
                "SignatureDateTime": now_str if is_final else "",
                "SubmittedAt": now_str,
            }

            update_or_append_onboarding(username, data)
            if DB_MIGRATION_MODE:
                try:
                    phone_full = " ".join([x for x in [phone_cc, phone_num] if x]).strip()
                    emergency_phone_full = " ".join([x for x in [ec_cc, ec_phone] if x]).strip()
                    address_full = ", ".join([x for x in [street, city, postcode] if x]).strip()

                    db_row = OnboardingRecord.query.filter_by(username=username, workplace_id=_session_workplace_id()).first()

                    if db_row:
                        db_row.first_name = first
                        db_row.last_name = last
                        db_row.birth_date = birth
                        db_row.phone = phone_full
                        db_row.email = email
                        db_row.address = address_full
                        db_row.emergency_contact_name = ec_name
                        db_row.emergency_contact_phone = emergency_phone_full
                        db_row.medical_condition = medical
                        db_row.position = position
                    else:
                        db.session.add(
                            OnboardingRecord(
                                username=username,
                                workplace_id=_session_workplace_id(),
                                first_name=first,
                                last_name=last,
                                birth_date=birth,
                                phone=phone_full,
                                email=email,
                                address=address_full,
                                emergency_contact_name=ec_name,
                                emergency_contact_phone=emergency_phone_full,
                                medical_condition=medical,
                                position=position,
                            )
                        )

                    db.session.commit()
                except Exception:
                    db.session.rollback()
            set_employee_first_last(username, first, last)
            if is_final:
                set_employee_field(username, "OnboardingCompleted", "TRUE")
                set_employee_field(username, "Workplace_ID", _session_workplace_id())

            existing = get_onboarding_record(username)
            msg = "Saved draft." if not is_final else "Submitted final successfully."
            msg_ok = True
            typed = None
            missing_fields = set()

    content = _render_onboarding_page(display_name, role, csrf, existing, msg, msg_ok, typed, missing_fields)
    return render_app_page("agreements", role, content)


@app.route("/password", methods=["GET", "POST"])
def change_password():
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

    details_html = onboarding_details_block(username)

    msg = ""
    ok = False

    if request.method == "POST":
        require_csrf()
        current = request.form.get("current", "")
        new1 = request.form.get("new1", "")
        new2 = request.form.get("new2", "")

        stored_pw = None
        user_row = _find_employee_record(username)
        if user_row:
            stored_pw = user_row.get("Password", "")

        if stored_pw is None or not is_password_valid(stored_pw, current):
            msg = "Current password is incorrect."
            ok = False
        elif len(new1) < 8:
            msg = "New password too short (min 8)."
            ok = False
        elif new1 != new2:
            msg = "New passwords do not match."
            ok = False
        else:
            ok = update_employee_password(username, new1)
            msg = "Password updated successfully." if ok else "Could not update password."

        details_html = onboarding_details_block(username)

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Profile</h1>
          <p class="sub">{escape(display_name)}</p>
        </div>
        <div class="badge {'admin' if role == 'admin' else ''}">{escape(role.upper())}</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

      <div class="card" style="padding:14px;">
        <h2>My Details</h2>
        <p class="sub">Saved from Starter Form (files not shown).</p>
        {details_html}
      </div>

      <div class="card" style="padding:14px; margin-top:12px;">
        <h2>Change Password</h2>
        <form method="POST">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <label class="sub">Current password</label>
          <input class="input" type="password" name="current" required>

          <label class="sub" style="margin-top:10px; display:block;">New password</label>
          <input class="input" type="password" name="new1" required>

          <label class="sub" style="margin-top:10px; display:block;">Repeat new password</label>
          <input class="input" type="password" name="new2" required>

          <button class="btnSoft" type="submit" style="margin-top:12px;">Save</button>
        </form>
      </div>
    """
    return render_app_page("profile", role, content)


