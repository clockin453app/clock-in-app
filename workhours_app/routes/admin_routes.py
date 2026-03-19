"""Route registrations extracted from the legacy monolith.

This keeps the original endpoint names and handler bodies intact while
reducing the size of the main runtime module.
"""

from workhours_app.route_dependencies import (
    BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS,
    COL_DATE,
    COL_HOURS,
    COL_IN,
    COL_OUT,
    COL_PAY,
    COL_USER,
    DB_MIGRATION_MODE,
    Decimal,
    Employee,
    Location,
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    OAUTH_REDIRECT_URI,
    OVERTIME_HOURS,
    OnboardingRecord,
    PayrollReport,
    TZ,
    UNPAID_BREAK_HOURS,
    WorkHour,
    WorkplaceSetting,
    _append_paid_record_safe,
    _compute_hours_from_times,
    _employees_usernames_for_workplace,
    _ensure_employees_columns,
    _ensure_locations_headers,
    _ensure_workhours_geo_headers,
    _find_employee_record,
    _find_location_row_by_name,
    _find_workhours_row_by_user_date,
    _generate_temp_password,
    _generate_unique_username,
    _get_active_locations,
    _get_employee_sites,
    _get_open_shifts,
    _get_user_rate,
    _get_week_range,
    _gs_write_with_retry,
    _is_paid_for_week,
    _list_employee_records_for_workplace,
    _normalize_password_hash_value,
    _sanitize_requested_role,
    _session_workplace_id,
    _svg_chart,
    _svg_clock,
    _svg_doc,
    _svg_grid,
    _svg_user,
    abort,
    and_,
    app,
    date,
    datetime,
    db,
    employees_sheet,
    escape,
    find_open_shift,
    find_row_by_username,
    fmt_hours,
    generate_password_hash,
    get_company_settings,
    get_csrf,
    get_employee_display_name,
    get_employees_compat,
    get_locations,
    get_onboarding_record,
    get_sheet_headers,
    get_workhours_rows,
    gspread,
    initials,
    io,
    linkify,
    locations_sheet,
    log_audit,
    make_response,
    money,
    onboarding_sheet,
    or_,
    re,
    redirect,
    render_app_page,
    request,
    require_admin,
    require_csrf,
    require_master_admin,
    role_label,
    safe_float,
    send_file,
    session,
    set_employee_field,
    settings_sheet,
    timedelta,
    update_employee_password,
    user_in_same_workplace,
    work_sheet,
)

@app.post("/admin/employees/reset-password")
def admin_employee_reset_password():
    gate = require_master_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("username") or "").strip()
    new_password = (request.form.get("new_password") or "").strip()

    if not username or len(new_password) < 8:
        session["_pwreset_ok"] = False
        session["_pwreset_msg"] = "Enter a valid username and a password with at least 8 characters."
        session.pop("_pwreset_user", None)
        session.pop("_pwreset_password", None)
        return redirect("/admin/employees")

    ok = update_employee_password(username, new_password, workplace_id=_session_workplace_id())

    actor = session.get("username", "master_admin")
    if ok:
        log_audit("RESET_PASSWORD", actor=actor, username=username, date_str="", details="current workplace")
        session["_pwreset_ok"] = True
        session["_pwreset_msg"] = f"Password reset successfully for {username}."
        session["_pwreset_user"] = username
        session.pop("_pwreset_password", None)
    else:
        log_audit("RESET_PASSWORD_FAILED", actor=actor, username=username, date_str="", details="current workplace")
        session["_pwreset_ok"] = False
        session["_pwreset_msg"] = f"Could not reset password for {username}."
        session.pop("_pwreset_user", None)
        session.pop("_pwreset_password", None)

    return redirect("/admin/employees")


@app.post("/admin/employees/clear-history")
def admin_clear_employee_history():
    gate = require_master_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("username") or "").strip()
    wp = (_session_workplace_id() or "default").strip() or "default"

    if not username:
        session["_emp_msg"] = "Choose an employee first."
        session["_emp_ok"] = False
        return redirect("/admin/employees")

    try:
        workhours_deleted = WorkHour.query.filter(
            and_(
                or_(
                    WorkHour.employee_email == username,
                ),
                or_(
                    WorkHour.workplace_id == wp,
                    and_(WorkHour.workplace_id.is_(None), WorkHour.workplace == wp),
                    WorkHour.workplace == wp,
                ),
            )
        ).delete(synchronize_session=False)

        payroll_deleted = PayrollReport.query.filter(
            and_(
                PayrollReport.username == username,
                PayrollReport.workplace_id == wp,
            )
        ).delete(synchronize_session=False)

        db.session.commit()

        session["_emp_msg"] = (
            f"Clear history ran for {username}. "
            f"Deleted workhours={int(workhours_deleted or 0)}, "
            f"payroll={int(payroll_deleted or 0)}."
        )
        session["_emp_ok"] = True

    except Exception as e:
        db.session.rollback()
        session["_emp_msg"] = f"Clear history failed: {str(e)}"
        session["_emp_ok"] = False

    return redirect("/admin/employees")


@app.post("/admin/employees/delete")
def admin_delete_employee():
    gate = require_master_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("username") or "").strip()
    wp = (_session_workplace_id() or "default").strip() or "default"

    if not username:
        session["_emp_msg"] = "Choose an employee first."
        session["_emp_ok"] = False
        return redirect("/admin/employees")

    if username == session.get("username"):
        session["_emp_msg"] = "You cannot delete your own account."
        session["_emp_ok"] = False
        return redirect("/admin/employees")
    target_employee = Employee.query.filter(
        and_(
            or_(Employee.username == username, Employee.email == username),
            or_(
                Employee.workplace_id == wp,
                and_(Employee.workplace_id.is_(None), Employee.workplace == wp),
                Employee.workplace == wp,
            ),
        )
    ).first()

    if target_employee and (target_employee.role or "").strip().lower() == "master_admin":
        session["_emp_msg"] = "Master admin account cannot be deleted."
        session["_emp_ok"] = False
        return redirect("/admin/employees")

    try:
        workhours_deleted = WorkHour.query.filter(
            and_(
                or_(
                    WorkHour.employee_email == username,
                ),
                or_(
                    WorkHour.workplace_id == wp,
                    and_(WorkHour.workplace_id.is_(None), WorkHour.workplace == wp),
                    WorkHour.workplace == wp,
                ),
            )
        ).delete(synchronize_session=False)

        payroll_deleted = PayrollReport.query.filter(
            and_(
                PayrollReport.username == username,
                PayrollReport.workplace_id == wp,
            )
        ).delete(synchronize_session=False)

        onboarding_deleted = OnboardingRecord.query.filter(
            and_(
                OnboardingRecord.username == username,
                OnboardingRecord.workplace_id == wp,
            )
        ).delete(synchronize_session=False)

        employees_deleted = Employee.query.filter(
            and_(
                or_(
                    Employee.username == username,
                    Employee.email == username,
                ),
                or_(
                    Employee.workplace_id == wp,
                    and_(Employee.workplace_id.is_(None), Employee.workplace == wp),
                    Employee.workplace == wp,
                ),
            )
        ).delete(synchronize_session=False)

        db.session.commit()

        session["_emp_msg"] = (
            f"Delete ran for {username}. "
            f"Deleted employees={int(employees_deleted or 0)}, "
            f"workhours={int(workhours_deleted or 0)}, "
            f"payroll={int(payroll_deleted or 0)}, "
            f"onboarding={int(onboarding_deleted or 0)}."
        )
        session["_emp_ok"] = True

    except Exception as e:
        db.session.rollback()
        session["_emp_msg"] = f"Delete failed: {str(e)}"
        session["_emp_ok"] = False

    return redirect("/admin/employees")


@app.get("/admin")
def admin():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()

    # NEW: currency from Settings
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    currency_html = escape(currency)
    currency_js = currency.replace("\\", "\\\\").replace('"', '\\"')

    open_shifts = _get_open_shifts()
    employees_total = 0
    onboarding_total = 0
    locations_total = len(_get_active_locations())
    open_total = len(open_shifts)

    try:
        employees_total = len(_list_employee_records_for_workplace())
    except Exception:
        employees_total = 0

    try:
        current_wp = _session_workplace_id()
        if DB_MIGRATION_MODE:
            onboarding_total = sum(
                1
                for rec in OnboardingRecord.query.all()
                if (str(getattr(rec, "workplace_id", "default") or "default").strip() or "default") == current_wp
                and str(getattr(rec, "username", "") or "").strip()
            )
        else:
            vals_onb = onboarding_sheet.get_all_values()
            headers_onb = vals_onb[0] if vals_onb else []
            ucol_onb = headers_onb.index("Username") if "Username" in headers_onb else None
            wp_col_onb = headers_onb.index("Workplace_ID") if "Workplace_ID" in headers_onb else None

            if ucol_onb is not None:
                for r in vals_onb[1:]:
                    u = (r[ucol_onb] if ucol_onb < len(r) else "").strip()
                    if not u:
                        continue
                    if wp_col_onb is not None:
                        row_wp = (r[wp_col_onb] if wp_col_onb < len(r) else "").strip() or "default"
                        if row_wp != current_wp:
                            continue
                    onboarding_total += 1
    except Exception:
        onboarding_total = 0

    if open_shifts:
        rows = []
        for s in open_shifts:
            rate = _get_user_rate(s["user"])
            rows.append(f"""
              <tr>
                <td>
                  <div>
                    <div>
                      <div style="font-weight:600;">{escape(s['name'])}</div>
                      <div class="sub" style="margin:2px 0 0 0;">{escape(s['user'])}</div>
                    </div>
                  </div>
                </td>
                <td>{escape(s['start_label'])}</td>
                <td class="num"><span class="netBadge" data-live-start="{escape(s['start_iso'])}">00:00:00</span></td>
                <td class="num" data-est-hours="{escape(s['start_iso'])}">0.00</td>
                <td class="num" data-est-pay="{escape(s['start_iso'])}" data-rate="{rate}">{currency_html}0.00</td>
                <td style="min-width:240px;">
                  <form method="POST" action="/admin/force-clockout" style="margin:0; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                    <input type="hidden" name="csrf" value="{escape(csrf)}">
                    <input type="hidden" name="user" value="{escape(s['user'])}">
                    <input class="input" type="time" step="1" name="out_time" value="" style="margin-top:0; max-width:150px;">
                    <button class="btnTiny" type="submit">Force Clock-Out</button>
                  </form>
                  <div class="sub" style="margin-top:6px;">Set the correct end time and force close the open shift.</div>
                </td>
              </tr>
            """)

        open_html = f"""
                    <div class="card adminSectionCard" style="margin-top:12px;">
            <div class="adminSectionHead">
              <div class="adminSectionHeadLeft">
                <div class="adminSectionIcon live">{_svg_user()}</div>
                <div>
                  <h2 class="adminSectionTitle">Live Clocked-In</h2>
                  <p class="adminSectionSub">Employees currently clocked in. Live time updates every second.</p>
                </div>
              </div>
              <div class="adminHintChip">{len(open_shifts)} active</div>
            </div>
            <div class="tablewrap adminLiveTableWrap" style="margin-top:12px;">
              <table class="adminLiveTable">
                <thead><tr>
                  <th>Employee</th>
                  <th>Started</th>
                  <th class="num">Live Time</th>
                  <th class="num">Est Hours</th>
                  <th class="num">Est Pay</th>
                  <th>Actions</th>
                </tr></thead>
                <tbody>{''.join(rows)}</tbody>
              </table>
            </div>
            <script>
              (function(){{
                const CURRENCY = "{currency_js}";
                function pad(n){{ return String(n).padStart(2,"0"); }}
                function tick(){{
                  const now = new Date();
                  document.querySelectorAll("[data-live-start]").forEach(el=>{{
                    const startIso = el.getAttribute("data-live-start");
                    const start = new Date(startIso);
                    let diff = Math.floor((now - start)/1000);
                    if(diff < 0) diff = 0;
                    const h = Math.floor(diff/3600);
                    const m = Math.floor((diff%3600)/60);
                    const s = diff%60;
                    el.textContent = pad(h)+":"+pad(m)+":"+pad(s);
                  }});

                  document.querySelectorAll("[data-est-hours]").forEach(el=>{{
                    const startIso = el.getAttribute("data-est-hours");
                    const start = new Date(startIso);
                    let hrs = (now - start) / 3600000.0;
                    if(hrs < 0) hrs = 0;
                    if(hrs >= {BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS}) hrs = Math.max(0, hrs - {UNPAID_BREAK_HOURS});
                    hrs = Math.min(hrs, 16);
                    el.textContent = (Math.round(hrs*100)/100).toFixed(2);
                  }});

                  document.querySelectorAll("[data-est-pay]").forEach(el=>{{
                    const startIso = el.getAttribute("data-est-pay");
                    const rate = parseFloat(el.getAttribute("data-rate") || "0") || 0;
                    const start = new Date(startIso);
                    let hrs = (now - start) / 3600000.0;
                    if(hrs < 0) hrs = 0;
                    if(hrs >= {BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS}) hrs = Math.max(0, hrs - {UNPAID_BREAK_HOURS});
                    hrs = Math.min(hrs, 16);
                    const pay = hrs * rate;
                    el.textContent = CURRENCY + pay.toFixed(2);
                  }});
                }}
                tick(); setInterval(tick, 1000);
              }})();
            </script>
          </div>
        """
    else:
        open_html = f"""
          <div class="card adminSectionCard" style="margin-top:12px;">
            <div class="adminSectionHead">
              <div class="adminSectionHeadLeft">
                <div class="adminSectionIcon live">{_svg_user()}</div>
                <div>
                  <h2 class="adminSectionTitle">Live Clocked-In</h2>
                  <p class="adminSectionSub">See who is currently active on site in real time.</p>
                </div>
              </div>
              <div class="adminHintChip">Live</div>
            </div>
            <p class="sub" style="margin:0;">No one is currently clocked in.</p>
          </div>
        """
    employee_options = ""
    try:
        vals_emp = employees_sheet.get_all_values()
        headers_emp = vals_emp[0] if vals_emp else []
        ucol = headers_emp.index("Username") if "Username" in headers_emp else 0
        wp_col = headers_emp.index("Workplace_ID") if "Workplace_ID" in headers_emp else None
        current_wp = _session_workplace_id()

        for r in vals_emp[1:]:
            u = (r[ucol] if ucol < len(r) else "").strip()
            if not u:
                continue

            # Tenant-safe: filter by Employees row Workplace_ID
            if wp_col is not None:
                row_wp = (r[wp_col] if wp_col < len(r) else "").strip() or "default"
                if row_wp != current_wp:
                    continue

            employee_options += f"<option value='{escape(u)}'>{escape(u)}</option>"
    except Exception:
        employee_options = ""

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Admin</h1>
          <p class="sub">Payroll + onboarding</p>
        </div>
        <div class="badge admin">{escape(role_label(session.get('role', 'admin')))}</div>
      </div>

                  <div class="kpiStrip adminStats" style="margin-bottom:12px;">
        <div class="kpiMini adminStatCard employees">
          <div class="k">Employees</div>
          <div class="v">{employees_total}</div>
        </div>
        <div class="kpiMini adminStatCard clocked">
          <div class="k">Clocked In</div>
          <div class="v">{open_total}</div>
        </div>
        <div class="kpiMini adminStatCard locations">
          <div class="k">Active Locations</div>
          <div class="v">{locations_total}</div>
        </div>
        <div class="kpiMini adminStatCard onboarding">
          <div class="k">Onboarding Records</div>
          <div class="v">{onboarding_total}</div>
        </div>
      </div>

            <div class="card menu" style="padding:14px;">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap;">
          <div>
            <h2>Admin tools</h2>
            <p class="sub">Manage payroll, people, sites, onboarding and drive access.</p>
          </div>
          <div class="badge admin">Control Centre</div>
        </div>

        <div class="adminGrid" style="margin-top:12px;">
          <a class="adminToolCard payroll" href="/admin/payroll">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_chart()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Payroll Report</div>
            <div class="adminToolSub">Weekly payroll, tax, net pay and paid status.</div>
          </a>

          <a class="adminToolCard company" href="/admin/company">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_doc()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Company Settings</div>
            <div class="adminToolSub">Change workplace name and company-level settings.</div>
          </a>

          <a class="adminToolCard onboarding" href="/admin/onboarding">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_doc()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Onboarding</div>
            <div class="adminToolSub">Review starter forms, documents and contract details.</div>
          </a>

          <a class="adminToolCard locations" href="/admin/locations">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_grid()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Locations</div>
            <div class="adminToolSub">Manage geo-fence sites and allowed clock-in zones.</div>
          </a>

          <a class="adminToolCard sites" href="/admin/employee-sites">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_user()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Employee Sites</div>
            <div class="adminToolSub">Assign employees to site locations for clock-in access.</div>
          </a>

          <a class="adminToolCard employees" href="/admin/employees">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_svg_user()}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Employees</div>
            <div class="adminToolSub">Create employees, update rates and manage access.</div>
          </a>

                    {
    f'''
              <a class="adminToolCard drive" href="/connect-drive">
                <div class="adminToolTop">
                  <div class="adminToolIcon">{_svg_grid()}</div>
                  <div class="chev">›</div>
                </div>
                <div class="adminToolTitle">Connect Drive</div>
                <div class="adminToolSub">Reconnect Google Drive for onboarding uploads.</div>
              </a>
            '''
    if (session.get("role") == "master_admin" and OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET and OAUTH_REDIRECT_URI)
    else ""
    }
        </div>
      </div>
            <div class="card adminSectionCard" style="margin-top:12px;">
        <div class="adminSectionHead">
          <div class="adminSectionHeadLeft">
            <div class="adminSectionIcon clockin">{_svg_clock()}</div>
            <div>
              <h2 class="adminSectionTitle">Force Clock-In</h2>
              <p class="adminSectionSub">Use this if someone forgot to clock in. It creates or updates today’s row.</p>
            </div>
          </div>
          <div class="adminHintChip">Admin action</div>
        </div>

                <form method="POST" action="/admin/force-clockin" class="adminFormRow">
          <input type="hidden" name="csrf" value="{escape(csrf)}">

          <div class="adminActionBar">
            <input class="input" type="date" name="date" value="{escape(datetime.now(TZ).strftime('%Y-%m-%d'))}" style="max-width:190px;" required>

            <select class="input" name="user" style="max-width:260px;">
              {employee_options}
            </select>

            <input class="input" type="time" step="1" name="in_time" style="max-width:170px;" required>

            <button class="adminPrimaryBtn" type="submit">Force Clock-In</button>
          </div>
        </form>
      </div>
      {open_html}
    """
    return render_app_page(
        active="admin",
        role=session.get("role", "admin"),
        content_html=content,
    )


@app.route("/admin/company", methods=["GET", "POST"])
def admin_company():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    role = session.get("role", "admin")
    wp = _session_workplace_id()

    settings = get_company_settings()
    current_name = (settings.get("Company_Name") or "").strip() or "Main"

    msg = ""
    ok = False

    if request.method == "POST":
        require_csrf()
        new_name = (request.form.get("company_name") or "").strip()

        if not new_name:
            msg = "Company name required."
        elif not settings_sheet:
            msg = "Settings sheet not configured."
        else:
            vals = settings_sheet.get_all_values()
            if not vals:
                settings_sheet.append_row(["Workplace_ID", "Tax_Rate", "Currency_Symbol", "Company_Name"])
                vals = settings_sheet.get_all_values()

            hdr = vals[0] if vals else []

            def idx(n):
                return hdr.index(n) if n in hdr else None

            i_wp = idx("Workplace_ID")
            i_name = idx("Company_Name")
            i_tax = idx("Tax_Rate")
            i_cur = idx("Currency_Symbol")

            if i_wp is None or i_name is None:
                msg = "Settings headers missing Workplace_ID or Company_Name."
            else:
                rownum = None
                for i in range(1, len(vals)):
                    r = vals[i]
                    row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                    if row_wp == wp:
                        rownum = i + 1
                        break

                if rownum:
                    settings_sheet.update_cell(rownum, i_name + 1, new_name)
                else:
                    row = [""] * len(hdr)
                    row[i_wp] = wp
                    row[i_name] = new_name
                    if i_tax is not None:
                        row[i_tax] = str(settings.get("Tax_Rate", 20.0))
                    if i_cur is not None:
                        row[i_cur] = str(settings.get("Currency_Symbol", "£"))
                    settings_sheet.append_row(row)
                    if DB_MIGRATION_MODE:
                        try:
                            tax_value = settings.get("Tax_Rate", 20.0)
                            try:
                                tax_value = float(tax_value)
                            except Exception:
                                tax_value = 20.0

                            currency_value = str(settings.get("Currency_Symbol", "£") or "£")

                            db_row = WorkplaceSetting.query.filter_by(workplace_id=wp).first()
                            if db_row:
                                db_row.company_name = new_name
                                db_row.tax_rate = tax_value
                                db_row.currency_symbol = currency_value
                            else:
                                db.session.add(
                                    WorkplaceSetting(
                                        workplace_id=wp,
                                        tax_rate=tax_value,
                                        currency_symbol=currency_value,
                                        company_name=new_name,
                                    )
                                )

                            db.session.commit()
                        except Exception:
                            db.session.rollback()

                log_audit("SET_COMPANY_NAME", actor=session.get("username", "admin"), details=f"{wp} -> {new_name}")
                ok = True
                msg = "Saved."
                current_name = new_name

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Company Settings</h1>
          <p class="sub">Workplace: <b>{escape(wp)}</b></p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

      <div class="card payrollEmployeeCard" style="padding:12px; margin-top:12px;">
        <form method="POST">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <label class="sub">Company name</label>
          <input class="input" name="company_name" value="{escape(current_name)}" required>
          <button class="btnSoft" type="submit" style="margin-top:12px;">Save</button>
        </form>
      </div>
    """
    return render_app_page(
        "admin",
        session.get("role", "admin"),
        content,
    )


@app.post("/admin/save-shift")
def admin_save_shift():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or "").strip()
    date_str = (request.form.get("date") or "").strip()
    cin = (request.form.get("cin") or "").strip()
    cout = (request.form.get("cout") or "").strip()
    hours_in = (request.form.get("hours") or "").strip()
    pay_in = (request.form.get("pay") or "").strip()
    recalc = (request.form.get("recalc") == "yes")

    if not username or not date_str:
        return redirect(request.referrer or "/admin/payroll")

    rate = _get_user_rate(username)

    hours_val = None if hours_in == "" else safe_float(hours_in, 0.0)
    pay_val = None if pay_in == "" else safe_float(pay_in, 0.0)

    auto_calc = recalc or (cin and cout and hours_in == "" and pay_in == "")
    if cin and cout and auto_calc:
        computed = _compute_hours_from_times(date_str, cin, cout)
        if computed is not None:
            hours_val = computed
            pay_val = round(computed * rate, 2)

    if hours_in != "" and pay_in == "":
        pay_val = round(safe_float(hours_in, 0.0) * rate, 2)

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            db_row = WorkHour.query.filter_by(
                employee_email=username,
                date=shift_date,
                workplace=_session_workplace_id(),
            ).order_by(WorkHour.id.desc()).first()
            if not db_row:
                db_row = WorkHour(
                    employee_email=username,
                    date=shift_date,
                    workplace=_session_workplace_id(),
                    workplace_id=_session_workplace_id(),
                )
                db.session.add(db_row)

            clock_in_dt = None
            clock_out_dt = None
            if cin:
                if len(cin.split(":")) == 2:
                    cin = cin + ":00"
                clock_in_dt = datetime.strptime(f"{date_str} {cin}", "%Y-%m-%d %H:%M:%S")
            if cout:
                if len(cout.split(":")) == 2:
                    cout = cout + ":00"
                clock_out_dt = datetime.strptime(f"{date_str} {cout}", "%Y-%m-%d %H:%M:%S")
                if clock_in_dt and clock_out_dt < clock_in_dt:
                    clock_out_dt = clock_out_dt + timedelta(days=1)

            db_row.clock_in = clock_in_dt
            db_row.clock_out = clock_out_dt
            db_row.workplace = _session_workplace_id()
            db_row.workplace_id = _session_workplace_id()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not save shift: {e}", 500)
        return redirect(request.referrer or "/admin/payroll")

    hours_cell = "" if hours_val is None else str(hours_val)
    pay_cell = "" if pay_val is None else str(pay_val)

    try:
        vals = work_sheet.get_all_values()
        rownum = _find_workhours_row_by_user_date(vals, username, date_str)
        if rownum:
            work_sheet.update_cell(rownum, COL_IN + 1, cin)
            work_sheet.update_cell(rownum, COL_OUT + 1, cout)
            work_sheet.update_cell(rownum, COL_HOURS + 1, hours_cell)
            work_sheet.update_cell(rownum, COL_PAY + 1, pay_cell)
        else:
            headers = vals[0] if vals else []
            new_row = [username, date_str, cin, cout, hours_cell, pay_cell]
            if headers and "Workplace_ID" in headers:
                wp_idx = headers.index("Workplace_ID")
                if len(new_row) <= wp_idx:
                    new_row += [""] * (wp_idx + 1 - len(new_row))
                new_row[wp_idx] = _session_workplace_id()
            if headers and len(new_row) < len(headers):
                new_row += [""] * (len(headers) - len(new_row))
            work_sheet.append_row(new_row)
    except Exception as e:
        return make_response(f"Could not save shift: {e}", 500)

    return redirect(request.referrer or "/admin/payroll")

    rate = _get_user_rate(username)

    hours_val = None if hours_in == "" else safe_float(hours_in, 0.0)
    pay_val = None if pay_in == "" else safe_float(pay_in, 0.0)

    # Auto-calc when:
    # - admin ticks "Recalculate", OR
    # - admin enters Clock In/Out and leaves Hours+Pay blank
    auto_calc = recalc or (cin and cout and hours_in == "" and pay_in == "")

    if cin and cout and auto_calc:
        computed = _compute_hours_from_times(date_str, cin, cout)
        if computed is not None:
            hours_val = computed
            pay_val = round(computed * rate, 2)

    # Manual hours edit: if Hours is entered but Pay is blank,
    # automatically refresh Pay from the employee rate.
    if hours_in != "" and pay_in == "":
        pay_val = round(safe_float(hours_in, 0.0) * rate, 2)

    hours_cell = "" if hours_val is None else str(hours_val)
    pay_cell = "" if pay_val is None else str(pay_val)

    try:
        vals = work_sheet.get_all_values()
        rownum = _find_workhours_row_by_user_date(vals, username, date_str)
        if rownum:
            work_sheet.update_cell(rownum, COL_IN + 1, cin)
            work_sheet.update_cell(rownum, COL_OUT + 1, cout)
            work_sheet.update_cell(rownum, COL_HOURS + 1, hours_cell)
            work_sheet.update_cell(rownum, COL_PAY + 1, pay_cell)
        else:
            headers = vals[0] if vals else []
            new_row = [username, date_str, cin, cout, hours_cell, pay_cell]

            if headers and "Workplace_ID" in headers:
                wp_idx = headers.index("Workplace_ID")
                if len(new_row) <= wp_idx:
                    new_row += [""] * (wp_idx + 1 - len(new_row))
                new_row[wp_idx] = _session_workplace_id()

            # Pad to header width (prevents misaligned rows if sheet has extra columns)
            if headers and len(new_row) < len(headers):
                new_row += [""] * (len(headers) - len(new_row))

            work_sheet.append_row(new_row)
    except Exception as e:
        return make_response(f"Could not mark payroll row as paid: {e}", 500)

    return redirect(request.referrer or "/admin/payroll")


@app.post("/admin/force-clockin")
def admin_force_clockin():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or "").strip()
    in_time = (request.form.get("in_time") or "").strip()
    dates = [(d or "").strip() for d in request.form.getlist("date")]
    dates = [d for d in dates if d]
    date_str = dates[-1] if dates else datetime.now(TZ).strftime("%Y-%m-%d")
    if not username or not in_time:
        return redirect(request.referrer or "/admin")

    if len(in_time.split(":")) == 2:
        in_time = in_time + ":00"

    rows = get_workhours_rows()
    if find_open_shift(rows, username):
        return redirect(request.referrer or "/admin")

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            clock_in_dt = datetime.strptime(f"{date_str} {in_time}", "%Y-%m-%d %H:%M:%S")
            db_row = WorkHour.query.filter_by(
                employee_email=username,
                date=shift_date,
                workplace=_session_workplace_id(),
            ).order_by(WorkHour.id.desc()).first()
            if db_row:
                db_row.clock_in = clock_in_dt
                db_row.clock_out = None
            else:
                db.session.add(
                    WorkHour(
                        employee_email=username,
                        date=shift_date,
                        clock_in=clock_in_dt,
                        clock_out=None,
                        workplace=_session_workplace_id(),
                        workplace_id=_session_workplace_id(),
                    )
                )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not force clock in: {e}", 500)
    else:
        try:
            vals = work_sheet.get_all_values()
            headers = vals[0] if vals else []
            rownum = _find_workhours_row_by_user_date(vals, username, date_str)
            wp_col = (headers.index("Workplace_ID") + 1) if ("Workplace_ID" in headers) else None
            if rownum:
                work_sheet.update_cell(rownum, COL_IN + 1, in_time)
                if wp_col:
                    work_sheet.update_cell(rownum, wp_col, _session_workplace_id())
            else:
                new_row = [username, date_str, in_time, "", "", ""]
                if "Workplace_ID" in headers:
                    wp_idx = headers.index("Workplace_ID")
                    if len(new_row) <= wp_idx:
                        new_row += [""] * (wp_idx + 1 - len(new_row))
                    new_row[wp_idx] = _session_workplace_id()
                if headers and len(new_row) < len(headers):
                    new_row += [""] * (len(headers) - len(new_row))
                work_sheet.append_row(new_row)
        except Exception as e:
            return make_response(f"Could not force clock in: {e}", 500)

    actor = session.get("username", "admin")
    log_audit("FORCE_CLOCK_IN", actor=actor, username=username, date_str=date_str, details=f"in={in_time}")
    return redirect(request.referrer or "/admin")

    # normalize to HH:MM:SS
    if len(in_time.split(":")) == 2:
        in_time = in_time + ":00"

    try:
        vals = work_sheet.get_all_values()
        headers = vals[0] if vals else []

        # If an open shift already exists, do nothing (avoid duplicates)
        if find_open_shift(vals, username):
            return redirect(request.referrer or "/admin")

        rownum = _find_workhours_row_by_user_date(vals, username, date_str)

        wp_col = (headers.index("Workplace_ID") + 1) if ("Workplace_ID" in headers) else None

        if rownum:
            # Update today's row
            work_sheet.update_cell(rownum, COL_IN + 1, in_time)
            if wp_col:
                work_sheet.update_cell(rownum, wp_col, _session_workplace_id())
        else:
            # Create a new row for today
            new_row = [username, date_str, in_time, "", "", ""]

            if "Workplace_ID" in headers:
                wp_idx = headers.index("Workplace_ID")
                if len(new_row) <= wp_idx:
                    new_row += [""] * (wp_idx + 1 - len(new_row))
                new_row[wp_idx] = _session_workplace_id()

            # Pad to header width (prevents misaligned rows if sheet has extra columns)
            if headers and len(new_row) < len(headers):
                new_row += [""] * (len(headers) - len(new_row))

            work_sheet.append_row(new_row)

    except Exception:
        pass

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            clock_in_dt = datetime.strptime(f"{date_str} {in_time}", "%Y-%m-%d %H:%M:%S")

            db_row = WorkHour.query.filter_by(
                employee_email=username,
                date=shift_date,
                workplace=_session_workplace_id(),
            ).order_by(WorkHour.id.desc()).first()

            if db_row:
                db_row.clock_in = clock_in_dt
                db_row.clock_out = None
            else:
                db.session.add(
                    WorkHour(
                        employee_email=username,
                        date=shift_date,
                        clock_in=clock_in_dt,
                        clock_out=None,
                        workplace=_session_workplace_id(),
                        workplace_id=_session_workplace_id(),
                    )
                )

            db.session.commit()
        except Exception:
            db.session.rollback()

    actor = session.get("username", "admin")
    log_audit("FORCE_CLOCK_IN", actor=actor, username=username, date_str=date_str, details=f"in={in_time}")
    return redirect(request.referrer or "/admin")


@app.post("/admin/force-clockout")
def admin_force_clockout():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or "").strip()
    out_time = (request.form.get("out_time") or "").strip()

    if not username or not out_time:
        return redirect(request.referrer or "/admin")

    rows = get_workhours_rows()
    osf = find_open_shift(rows, username)
    if not osf:
        return redirect(request.referrer or "/admin")

    idx, d, cin = osf
    rate = _get_user_rate(username)

    if len(out_time.split(":")) == 2:
        out_time = out_time + ":00"

    computed_hours = _compute_hours_from_times(d, cin, out_time)
    if computed_hours is None:
        return redirect(request.referrer or "/admin")

    pay = round(computed_hours * rate, 2)

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(d, "%Y-%m-%d").date()
            clock_out_dt = datetime.strptime(f"{d} {out_time}", "%Y-%m-%d %H:%M:%S")
            clock_in_dt_check = datetime.strptime(f"{d} {cin}", "%Y-%m-%d %H:%M:%S")
            if clock_out_dt < clock_in_dt_check:
                clock_out_dt = clock_out_dt + timedelta(days=1)

            db_row = WorkHour.query.filter_by(
                employee_email=username,
                date=shift_date,
                workplace=_session_workplace_id(),
            ).order_by(WorkHour.id.desc()).first()

            if db_row:
                db_row.clock_out = clock_out_dt
            else:
                db.session.add(
                    WorkHour(
                        employee_email=username,
                        date=shift_date,
                        clock_in=None,
                        clock_out=clock_out_dt,
                        workplace=_session_workplace_id(),
                        workplace_id=_session_workplace_id(),
                    )
                )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not force clock out: {e}", 500)
    else:
        sheet_row = idx + 1
        try:
            vals = work_sheet.get_all_values()
            headers = vals[0] if vals else []
            updates = [
                {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_OUT + 1), "values": [[out_time]]},
                {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_HOURS + 1), "values": [[str(computed_hours)]]},
                {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_PAY + 1), "values": [[str(pay)]]},
            ]
            if headers and "Workplace_ID" in headers:
                wp_col = headers.index("Workplace_ID") + 1
                updates.append({"range": gspread.utils.rowcol_to_a1(sheet_row, wp_col), "values": [[_session_workplace_id()]]})
            import copy
            _gs_write_with_retry(lambda: work_sheet.batch_update(copy.deepcopy(updates)))
        except Exception as e:
            return make_response(f"Could not force clock out: {e}", 500)

    actor = session.get("username", "admin")
    log_audit("FORCE_CLOCK_OUT", actor=actor, username=username, date_str=d,
              details=f"out={out_time} hours={computed_hours} pay={pay}")
    return redirect(request.referrer or "/admin")

    rows = get_workhours_rows()
    osf = find_open_shift(rows, username)
    if not osf:
        return redirect(request.referrer or "/admin")

    idx, d, cin = osf  # idx is 0-based data index (within rows list)
    rate = _get_user_rate(username)

    # normalize to HH:MM:SS
    if len(out_time.split(":")) == 2:
        out_time = out_time + ":00"

    computed_hours = _compute_hours_from_times(d, cin, out_time)
    if computed_hours is None:
        return redirect(request.referrer or "/admin")

    pay = round(computed_hours * rate, 2)

    sheet_row = idx + 1

    try:
        vals = work_sheet.get_all_values()
        headers = vals[0] if vals else []

        updates = [
            {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_OUT + 1), "values": [[out_time]]},
            {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_HOURS + 1), "values": [[str(computed_hours)]]},
            {"range": gspread.utils.rowcol_to_a1(sheet_row, COL_PAY + 1), "values": [[str(pay)]]},
        ]

        # Ensure Workplace_ID is set (if column exists)
        if headers and "Workplace_ID" in headers:
            wp_col = headers.index("Workplace_ID") + 1
            updates.append(
                {"range": gspread.utils.rowcol_to_a1(sheet_row, wp_col), "values": [[_session_workplace_id()]]}
            )

        import copy
        _gs_write_with_retry(lambda: work_sheet.batch_update(copy.deepcopy(updates)))
    except Exception:
        pass

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(d, "%Y-%m-%d").date()
            clock_out_dt = datetime.strptime(f"{d} {out_time}", "%Y-%m-%d %H:%M:%S")
            clock_in_dt_check = datetime.strptime(f"{d} {cin}", "%Y-%m-%d %H:%M:%S")

            if clock_out_dt < clock_in_dt_check:
                clock_out_dt = clock_out_dt + timedelta(days=1)

            db_row = WorkHour.query.filter_by(
                employee_email=username,
                date=shift_date,
                workplace=_session_workplace_id(),
            ).order_by(WorkHour.id.desc()).first()

            if db_row:
                db_row.clock_out = clock_out_dt
            else:
                db.session.add(
                    WorkHour(
                        employee_email=username,
                        date=shift_date,
                        clock_in=None,
                        clock_out=clock_out_dt,
                        workplace=_session_workplace_id(),
                        workplace_id=_session_workplace_id(),
                    )
                )

            db.session.commit()
        except Exception:
            db.session.rollback()

    actor = session.get("username", "admin")
    log_audit("FORCE_CLOCK_OUT", actor=actor, username=username, date_str=d,
              details=f"out={out_time} hours={computed_hours} pay={pay}")
    return redirect(request.referrer or "/admin")


@app.post("/admin/mark-paid")
def admin_mark_paid():
    gate = require_admin()
    if gate:
        return gate

    try:
        require_csrf()
    except Exception:
        return redirect(request.referrer or "/admin/payroll")

    try:
        week_start = (request.form.get("week_start") or "").strip()
        week_end = (request.form.get("week_end") or "").strip()
        username = (request.form.get("user") or request.form.get("username") or "").strip()

        gross = safe_float(request.form.get("gross", "0") or "0", 0.0)
        tax = safe_float(request.form.get("tax", "0") or "0", 0.0)
        net = safe_float(request.form.get("net", "0") or "0", 0.0)

        paid_by = session.get("username", "admin")

        if week_start and week_end and username:
            _append_paid_record_safe(week_start, week_end, username, gross, tax, net, paid_by)
    except Exception:
        pass

    return redirect(request.referrer or "/admin/payroll")


@app.get("/admin/payroll")
def admin_payroll():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    _ensure_workhours_geo_headers()
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    q = (request.args.get("q", "") or "").strip().lower()
    date_from = (request.args.get("from", "") or "").strip()
    date_to = (request.args.get("to", "") or "").strip()

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()

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

    def week_label(d0):
        iso = d0.isocalendar()
        return f"Week {iso[1]} ({d0.strftime('%d %b')} – {(d0 + timedelta(days=6)).strftime('%d %b %Y')})"

    def in_range(d: str) -> bool:
        if not d:
            return False
        if date_from and d < date_from:
            return False
        if date_to and d > date_to:
            return False
        return True

    filtered = []
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        user = (r[COL_USER] or "").strip()
        if not user or user not in current_usernames:
            continue

        # Workplace filter: prefer WorkHours row Workplace_ID (tenant-safe)
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != current_wp:
                continue
        else:
            # Backward compat if WorkHours has no Workplace_ID column
            if not user_in_same_workplace(user):
                continue
        d = (r[COL_DATE] or "").strip()
        if not in_range(d):
            continue
        if q and q not in user.lower():
            continue
        filtered.append({
            "user": user,
            "date": d,
            "cin": (r[COL_IN] if len(r) > COL_IN else "") or "",
            "cout": (r[COL_OUT] if len(r) > COL_OUT else "") or "",
            "hours": (r[COL_HOURS] if len(r) > COL_HOURS else "") or "",
            "pay": (r[COL_PAY] if len(r) > COL_PAY else "") or "",
        })

    by_user = {}
    overall_hours = 0.0
    overall_gross = 0.0

    for row in filtered:
        u = row["user"] or "Unknown"
        by_user.setdefault(u, {"hours": 0.0, "gross": 0.0})
        if row["hours"] != "":
            h = safe_float(row["hours"], 0.0)
            g = safe_float(row["pay"], 0.0)
            by_user[u]["hours"] += h
            by_user[u]["gross"] += g
            overall_hours += h
            overall_gross += g

    overall_tax = round(overall_gross * tax_rate, 2)
    overall_net = round(overall_gross - overall_tax, 2)

    # Week lookup for editable tables
    week_lookup = {}
    for r in rows[1:]:
        if len(r) <= COL_PAY:
            continue
        user = (r[COL_USER] or "").strip()
        d = (r[COL_DATE] or "").strip()
        if not user or not d or user not in current_usernames:
            continue
        # Workplace filter for weekly tables (tenant-safe)
        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != current_wp:
                continue
        else:
            if not user_in_same_workplace(user):
                continue
        if d < week_start_str or d > week_end_str:
            continue
        week_lookup.setdefault(user, {})
        week_lookup[user][d] = {
            "cin": (r[COL_IN] if len(r) > COL_IN else "") or "",
            "cout": (r[COL_OUT] if len(r) > COL_OUT else "") or "",
            "hours": (r[COL_HOURS] if len(r) > COL_HOURS else "") or "",
            "pay": (r[COL_PAY] if len(r) > COL_PAY else "") or "",
        }

    # All users from current employee records only
    all_users = list(current_users)

    if q:
        all_users = [u for u in all_users if q in u.lower() or q in (get_employee_display_name(u) or "").lower()]
    employee_options = ["<option value=''>All employees</option>"]
    for u in sorted(all_users, key=lambda s: get_employee_display_name(s).lower()):
        display = get_employee_display_name(u)
        selected = "selected" if q == u.lower() else ""
        employee_options.append(
            f"<option value='{escape(u)}' {selected}>{escape(display)}</option>"
        )

    # Week dropdown
    week_options = []
    for i in range(0, 52):
        d0 = this_monday - timedelta(days=7 * i)
        selected = "selected" if i == wk_offset else ""
        week_options.append(
            f"<option value='{i}' {selected}>{escape(week_label(d0))}</option>"
        )

    week_nav_html = f"""
      <form method="GET" style="margin-top:10px; display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
        <input type="hidden" name="q" value="{escape(q)}">
        <input type="hidden" name="from" value="{escape(date_from)}">
        <input type="hidden" name="to" value="{escape(date_to)}">

        <label class="sub" style="margin:0; font-weight:700;">Week</label>
        <select class="input" name="wk" style="max-width:320px; margin-top:0;" onchange="this.form.submit()">
          {''.join(week_options)}
        </select>
      </form>
    """
    # Payroll donut chart data (gross by employee for current filtered view)
    chart_palette = [
        "#2563eb", "#7c3aed", "#16a34a", "#f59e0b", "#ef4444",
        "#06b6d4", "#84cc16", "#ec4899", "#14b8a6", "#8b5cf6"
    ]

    chart_rows = []
    for u, vals_u in by_user.items():
        gross_u = round(vals_u.get("gross", 0.0), 2)
        if gross_u <= 0:
            continue
        chart_rows.append({
            "user": u,
            "name": get_employee_display_name(u),
            "gross": gross_u,
        })

    chart_rows = sorted(chart_rows, key=lambda x: x["gross"], reverse=True)
    chart_top = chart_rows[:15]
    other_total = round(sum(x["gross"] for x in chart_rows[15:]), 2)

    chart_segments = []
    for i, item in enumerate(chart_top):
        chart_segments.append({
            "label": item["name"],
            "value": item["gross"],
            "color": chart_palette[i % len(chart_palette)],
        })

    if other_total > 0:
        chart_segments.append({
            "label": "Other",
            "value": other_total,
            "color": "#94a3b8",
        })

    total_chart_value = round(sum(x["value"] for x in chart_segments), 2)

    donut_css = "#e5e7eb"
    legend_html = "<div class='activityEmpty'>No payroll data for current filters.</div>"

    if total_chart_value > 0:
        angle_acc = 0.0
        stops = []
        for seg in chart_segments:
            pct = (seg["value"] / total_chart_value) * 100.0
            start = angle_acc
            end = angle_acc + pct
            stops.append(f"{seg['color']} {start:.2f}% {end:.2f}%")
            angle_acc = end
        donut_css = f"conic-gradient({', '.join(stops)})"

        legend_parts = []
        for seg in chart_segments:
            legend_parts.append(f"""
              <div class="payrollLegendRow">
                <div class="payrollLegendLeft">
                  <span class="payrollLegendDot" style="background:{seg['color']};"></span>
                  <span class="payrollLegendName">{escape(seg['label'])}</span>
                </div>
                <div class="payrollLegendVal">{escape(currency)}{money(seg['value'])}</div>
              </div>
            """)
        legend_html = "".join(legend_parts)
    # KPI strip (PRO)
    kpi_strip = f"""
      <div class="kpiStrip">
        <div class="kpiMini"><div class="k">Hours</div><div class="v">{round(overall_hours, 2)}</div></div>
        <div class="kpiMini"><div class="k">Gross</div><div class="v">{escape(currency)}{money(overall_gross)}</div></div>
        <div class="kpiMini"><div class="k">Tax</div><div class="v">{escape(currency)}{money(overall_tax)}</div></div>
        <div class="kpiMini"><div class="k">Net</div><div class="v">{escape(currency)}{money(overall_net)}</div></div>
      </div>
    """

    # Summary table (polished + paid under name)
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

    sheet_rows = []

    for u in sorted(all_users, key=lambda s: get_employee_display_name(s).lower()):
        display = get_employee_display_name(u)
        user_days = week_lookup.get(u, {})

        total_hours = 0.0
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

            total_hours += hrs
            gross += pay

            form_id = f"payroll_{re.sub(r'[^a-zA-Z0-9]+', '_', u)}_{d_str.replace('-', '_')}"
            has_day_value = bool(cin or cout or hrs > 0 or pay > 0)
            day_cls = "payrollDayCellOT" if hrs > OVERTIME_HOURS else ""

            if has_day_value:
                hrs_txt = f"{show_num(hrs)}h" if hrs > 0 else "—"
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
                           onchange="document.getElementById('{form_id}').submit()">
                       </div>
                       <div class="payrollDayLine">
                         <input
                           class="payrollTimeInput"
                           type="time"
                           step="60"
                           name="cout"
                           value="{escape(cout[:5])}"
                           form="{form_id}"
                           onchange="document.getElementById('{form_id}').submit()">
                       </div>
                       <div class="payrollDayHours">{escape(hrs_txt)}</div>
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

        cells.append(f"<td class='num payrollSummaryTotal'>{show_num(total_hours)}</td>")
        cells.append(
            f"<td class='num payrollSummaryMoney'>{(escape(currency) + money(gross)) if gross > 0 else ''}</td>")
        cells.append(f"<td class='num payrollSummaryMoney'>{(escape(currency) + money(tax)) if tax > 0 else ''}</td>")

        if paid:
            cells.append(
                f"<td class='num payrollSummaryMoney net paidNetCell'><span class='paidNetBadge'>{escape(currency)}{money(net)} · Paid</span></td>")
        elif gross > 0:
            cells.append(f"""
                 <td class='num payrollSummaryMoney net'>
                   <form method="POST" action="/admin/mark-paid" class="payCellForm">
                     <input type="hidden" name="csrf" value="{escape(csrf)}">
                     <input type="hidden" name="week_start" value="{escape(week_start_str)}">
                     <input type="hidden" name="week_end" value="{escape(week_end_str)}">
                     <input type="hidden" name="user" value="{escape(u)}">
                     <input type="hidden" name="gross" value="{gross}">
                     <input type="hidden" name="tax" value="{tax}">
                     <input type="hidden" name="net" value="{net}">
                     <button class="payCellBtn" type="submit">
                       {escape(currency)}{money(net)} <span class="payLabel">Pay</span>
                     </button>
                   </form>
                 </td>
               """)
        else:
            cells.append("<td class='num payrollSummaryMoney'></td>")

        sheet_rows.append("<tr>" + "".join(cells) + "</tr>")

    sheet_html = "".join(sheet_rows)

    # Per-user weekly editable tables
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    blocks = []
    for u in sorted(all_users, key=lambda s: s.lower()):
        display = get_employee_display_name(u)
        user_days = week_lookup.get(u, {})

        # Show the editable weekly table only if the employee has at least 1 REAL record in this week
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
                if h > OVERTIME_HOURS:
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
            overtime_row_class = "overtimeRow" if (str(hrs).strip() != "" and h_val > OVERTIME_HOURS) else ""

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
                hrs_txt = f"{safe_float(hrs, 0.0):.2f}".rstrip("0").rstrip(".")

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

        blocks.append(f"""
          <div class="card payrollEmployeeCard" style="padding:12px; margin-top:12px;">
            <div style="margin-bottom:12px;">
              <div style="font-size:30px; font-weight:800; line-height:1.1; color:rgba(15,23,42,.96);">
                {escape(display)}
              </div>
            </div>

            <div class="tablewrap" style="margin-top:12px;">
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
        <div class="v">{wk_hours:.2f}</div>
    </div>

    <div class="payrollSummaryItem">
        <div class="k">Gross</div>
        <div class="v">{escape(currency)}{money(wk_gross)}</div>
    </div>

    <div class="payrollSummaryItem">
        <div class="k">Tax</div>
        <div class="v">{escape(currency)}{money(wk_tax)}</div>
    </div>

    <div class="payrollSummaryItem net">
        <div class="k">Net</div>
        <div class="v">{escape(currency)}{money(wk_net)}</div>
    </div>

    <div class="payrollSummaryItem paidat">
        <div class="k">Paid at</div>
        <div class="v">{escape(paid_at) if paid and paid_at else "—"}</div>
    </div>
</div>
        """)

    last_updated = datetime.now(TZ).strftime("%d %b %Y • %H:%M")
    csv_url = "/admin/payroll-report.csv"
    if request.query_string:
        csv_url += "?" + request.query_string.decode("utf-8", "ignore")

    content = f"""
      <div class="payrollMenuBackdrop" id="payrollMenuBackdrop"></div>

      <div class="headerTop">
        <div>
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <button type="button" class="payrollMenuToggle" id="payrollMenuToggle">☰ Menu</button>
            <div>
              <h1>Payroll Report</h1>
              <p class="sub">Printable • Updated {escape(last_updated)} • Weekly tables auto-update every week</p>
            </div>
          </div>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

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
              <label class="sub">Date range (summary table only)</label>
              <div class="row2">
                <input class="input" type="date" name="from" value="{escape(date_from)}">
                <input class="input" type="date" name="to" value="{escape(date_to)}">
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

        <div class="card payrollChartCard">
          <div class="sectionHead">
            <div class="sectionHeadLeft">
              <div class="sectionIcon">{_svg_chart()}</div>
              <div>
                <h2 style="margin:0;">Payroll Split</h2>
                <p class="sub" style="margin:4px 0 0 0;">Gross by employee for current filters.</p>
              </div>
            </div>
            <div class="sectionBadge">{len(chart_segments)} segments</div>
          </div>

          <div class="payrollDonutWrap">
            <div class="payrollDonut" style="background:{donut_css};">
              <div class="payrollDonutCenter">
                <div class="k">Total Gross</div>
                <div class="v">{escape(currency)}{money(total_chart_value)}</div>
              </div>
            </div>
          </div>

          <div class="payrollLegend">
            {legend_html}
          </div>
        </div>
      </div>

      {week_nav_html}

              <div class="payrollWrap" style="margin-top:12px;">
        <table class="payrollSheet">
          <thead>
            <tr class="cols">
              <th>Employee</th>
              <th>Mon</th>
              <th>Tue</th>
              <th>Wed</th>
              <th>Thu</th>
              <th>Fri</th>
              <th>Sat</th>
              <th>Sun</th>
              <th class="payrollSummaryTotal">Total</th>
              <th class="payrollSummaryMoney">Gross</th>
              <th class="payrollSummaryMoney">Tax</th>
              <th class="payrollSummaryMoney">Net</th>
            </tr>
          </thead>
          <tbody>
            {sheet_html}
          </tbody>
        </table>
      </div>

      {''.join(blocks)}

<script>
(function(){{
  const tbody = document.querySelector(".payrollWrap .payrollSheet tbody");
  if(!tbody) return;

  let selected = null;

  tbody.querySelectorAll("tr").forEach((tr) => {{
    tr.style.cursor = "pointer";

    tr.addEventListener("click", (e) => {{
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
    """
    return render_app_page(
        active="admin",
        role=session.get("role", "admin"),
        content_html=content,
        shell_class="payrollShell",
    )


@app.get("/admin/payroll-report.csv")
def admin_payroll_report_csv():
    gate = require_admin()
    if gate:
        return gate

    username_q = (request.args.get("q") or "").strip().lower()
    date_from = (request.args.get("from") or "").strip()
    date_to = (request.args.get("to") or "").strip()

    try:
        wk_offset = int((request.args.get("wk") or "0").strip())
    except Exception:
        wk_offset = 0

    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")
    try:
        tax_rate = float(settings.get("Tax_Rate", 20.0)) / 100.0
    except Exception:
        tax_rate = 0.20

    wp = _session_workplace_id()
    week_start, week_end = _get_week_range(wk_offset)

    use_range = False
    range_start = range_end = None

    if date_from and date_to:
        try:
            range_start = date.fromisoformat(date_from)
            range_end = date.fromisoformat(date_to)
            use_range = True
            week_start, week_end = date_from, date_to
        except ValueError:
            use_range = False

    rows = get_workhours_rows()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    employee_records = []
    try:
        employee_records = _list_employee_records_for_workplace(include_inactive=True)
    except Exception:
        employee_records = []
    current_usernames = {
        (rec.get("Username") or "").strip()
        for rec in employee_records
        if (rec.get("Username") or "").strip()
    }

    totals_by_user = {}

    for r in rows[1:]:
        if len(r) <= COL_PAY or len(r) <= COL_USER or len(r) <= COL_DATE:
            continue

        user = (r[COL_USER] or "").strip()
        d_str = (r[COL_DATE] or "").strip()

        if not user or not d_str or user not in current_usernames:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp != wp:
                continue
        else:
            if not user_in_same_workplace(user):
                continue

        if username_q and username_q not in user.lower() and username_q not in get_employee_display_name(user).lower():
            continue

        try:
            d_obj = date.fromisoformat(d_str)
        except Exception:
            continue

        if use_range:
            if d_obj < range_start or d_obj > range_end:
                continue
        else:
            if d_str < str(week_start)[:10] or d_str > str(week_end)[:10]:
                continue

        hrs = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        gross = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)

        totals_by_user.setdefault(user, {"hours": 0.0, "gross": 0.0})
        totals_by_user[user]["hours"] += hrs
        totals_by_user[user]["gross"] += gross

    export_rows = []
    for user, vals in totals_by_user.items():
        gross = round(vals["gross"], 2)
        tax = round(gross * tax_rate, 2)
        net = round(gross - tax, 2)
        hours = round(vals["hours"], 2)

        export_rows.append({
            "Employee": get_employee_display_name(user),
            "Username": user,
            "Hours": f"{hours:.2f}",
            "Gross": f"{gross:.2f}",
            "Tax": f"{tax:.2f}",
            "Net": f"{net:.2f}",
        })

    export_rows.sort(key=lambda x: (x.get("Employee") or "").lower())

    import csv
    from io import StringIO

    output = StringIO()
    output.write("sep=,\r\n")
    w = csv.writer(output)
    w.writerow(["WeekStart", "WeekEnd", "Employee", "Hours", "Gross", "Tax", "Net"])

    for r in export_rows:
        w.writerow([
            str(week_start),
            str(week_end),
            r["Employee"],
            r["Hours"],
            r["Gross"],
            r["Tax"],
            r["Net"],
        ])

    buf = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    buf.seek(0)

    filename = f"payroll_{week_start}_to_{week_end}.csv"

    return send_file(
        buf,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
        max_age=0
    )


@app.get("/admin/onboarding")
def admin_onboarding_list():
    gate = require_admin()
    if gate:
        return gate

    q = (request.args.get("q", "") or "").strip().lower()
    vals = onboarding_sheet.get_all_values() if not DB_MIGRATION_MODE else [
                                                                               ["Username", "FirstName", "LastName",
                                                                                "SubmittedAt", "Workplace_ID"]
                                                                           ] + [
                                                                               [
                                                                                   str(getattr(rec, "username",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "first_name",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "last_name",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "submitted_at",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "workplace_id",
                                                                                               "default") or "default").strip(),
                                                                               ]
                                                                               for rec in OnboardingRecord.query.all()
                                                                           ]
    if not vals:
        body = "<tr><td colspan='3'>No onboarding data.</td></tr>"
    else:
        headers = vals[0]

        def idx(name):
            return headers.index(name) if name in headers else None

        i_user = idx("Username")
        i_fn = idx("FirstName")
        i_ln = idx("LastName")
        i_sub = idx("SubmittedAt")
        i_wp = idx("Workplace_ID")
        current_wp = _session_workplace_id()

        rows_html = []
        for r in vals[1:]:
            u = r[i_user] if i_user is not None and i_user < len(r) else ""
            if not u:
                continue
            # Tenant-safe: filter by Onboarding row Workplace_ID (if column exists)
            if i_wp is not None:
                row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                if row_wp != current_wp:
                    continue
            else:
                # Backward compat if Onboarding has no Workplace_ID column
                if not user_in_same_workplace(u):
                    continue
            fn = r[i_fn] if i_fn is not None and i_fn < len(r) else ""
            ln = r[i_ln] if i_ln is not None and i_ln < len(r) else ""
            sub = r[i_sub] if i_sub is not None and i_sub < len(r) else ""
            name = (fn + " " + ln).strip() or u
            if q and (q not in u.lower() and q not in name.lower()):
                continue
            rows_html.append(
                f"<tr><td><a href='/admin/onboarding/{escape(u)}' style='color:var(--navy);font-weight:600;'>{escape(name)}</a></td>"
                f"<td>{escape(u)}</td><td>{escape(sub)}</td></tr>"
            )
        body = "".join(rows_html) if rows_html else "<tr><td colspan='3'>No matches.</td></tr>"

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Onboarding</h1>
          <p class="sub">Click a name to view details</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      <div class="card" style="padding:12px;">
        <form method="GET">
          <label class="sub">Search</label>
          <div class="row2">
            <input class="input" name="q" value="{escape(q)}" placeholder="name or username">
            <button class="btnSoft" type="submit" style="margin-top:8px;">Search</button>
          </div>
        </form>

        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width: 640px;">
            <thead><tr><th>Name</th><th>Username</th><th>Last saved</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </div>
    """
    return render_app_page(
        "admin",
        session.get("role", "admin"),
        content,
    )


@app.get("/admin/onboarding/<username>")
def admin_onboarding_detail(username):
    gate = require_admin()
    if gate:
        return gate
    rec = get_onboarding_record(username)
    if not rec:
        abort(404)
    # Tenant-safe: ensure the record is for the current workplace (if field exists)
    rec_wp = (rec.get("Workplace_ID") or "").strip() or "default"
    if rec_wp != _session_workplace_id():
        abort(404)

    def row(label, key, link=False):
        v_ = rec.get(key, "")
        vv = linkify(v_) if link else escape(v_)
        return f"<tr><th style='width:260px;'>{escape(label)}</th><td>{vv}</td></tr>"

    details = ""
    for label, key in [
        ("Username", "Username"), ("First name", "FirstName"), ("Last name", "LastName"),
        ("Birth date", "BirthDate"), ("Phone CC", "PhoneCountryCode"), ("Phone", "PhoneNumber"),
        ("Email", "Email"), ("Street", "StreetAddress"), ("City", "City"), ("Postcode", "Postcode"),
        ("Emergency contact", "EmergencyContactName"), ("Emergency CC", "EmergencyContactPhoneCountryCode"),
        ("Emergency phone", "EmergencyContactPhoneNumber"),
        ("Medical", "MedicalCondition"), ("Medical details", "MedicalDetails"),
        ("Position", "Position"), ("CSCS number", "CSCSNumber"), ("CSCS expiry", "CSCSExpiryDate"),
        ("Employment type", "EmploymentType"), ("Right to work UK", "RightToWorkUK"),
        ("NI", "NationalInsurance"), ("UTR", "UTR"), ("Start date", "StartDate"),
        ("Bank account", "BankAccountNumber"), ("Sort code", "SortCode"), ("Account holder", "AccountHolderName"),
        ("Company trading", "CompanyTradingName"), ("Company reg", "CompanyRegistrationNo"),
        ("Date of contract", "DateOfContract"), ("Site address", "SiteAddress"),
    ]:
        details += row(label, key)

    details += row("Passport/Birth cert", "PassportOrBirthCertLink", link=True)
    details += row("CSCS front/back", "CSCSFrontBackLink", link=True)
    details += row("Public liability", "PublicLiabilityLink", link=True)
    details += row("Share code", "ShareCodeLink", link=True)
    details += row("Contract accepted", "ContractAccepted")
    details += row("Signature name", "SignatureName")
    details += row("Signature time", "SignatureDateTime")
    details += row("Last saved", "SubmittedAt")

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Onboarding Details</h1>
          <p class="sub">{escape(username)}</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      <div class="card" style="padding:12px;">
        <div class="tablewrap">
          <table style="min-width: 720px;"><tbody>{details}</tbody></table>
        </div>
      </div>
    """
    return render_app_page(
        "admin",
        session.get("role", "admin"),
        content,
    )


@app.get("/admin/locations")
def admin_locations():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    _ensure_locations_headers()

    all_rows = []
    try:
        current_wp = _session_workplace_id()

        records = Location.query.all() if DB_MIGRATION_MODE else (get_locations() or [])
        for rec in records:
            if isinstance(rec, dict):
                row_wp = (rec.get("Workplace_ID") or rec.get("workplace_id") or "default").strip()
                if row_wp != current_wp:
                    continue

                name = str(rec.get("SiteName") or rec.get("site_name") or rec.get("Site") or "").strip()
                lat = str(rec.get("Lat") or rec.get("lat") or "").strip()
                lon = str(rec.get("Lon") or rec.get("lon") or "").strip()
                rad = str(rec.get("RadiusMeters") or rec.get("radius_meters") or rec.get("Radius") or "").strip()
                act = str(rec.get("Active") or rec.get("active") or "TRUE").strip()
            else:
                row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip()
                if row_wp != current_wp:
                    continue

                name = str(getattr(rec, "site_name", "") or "").strip()
                lat = str(getattr(rec, "lat", "") or "").strip()
                lon = str(getattr(rec, "lon", "") or "").strip()
                rad = str(getattr(rec, "radius_meters", "") or "").strip()
                act = str(getattr(rec, "active", "TRUE") or "TRUE").strip()

            if name:
                all_rows.append({
                    "name": name,
                    "lat": lat,
                    "lon": lon,
                    "rad": rad,
                    "act": act
                })
    except Exception:
        all_rows = []

    def _is_active(v):
        return str(v or "").strip().lower() not in ("false", "0", "no", "n", "off")

    def row_html(s):
        act_on = _is_active(s.get("act", "TRUE"))
        badge = "<span class='chip ok'>Active</span>" if act_on else "<span class='chip warn'>Inactive</span>"
        return f"""
          <tr>
            <td><b>{escape(s.get('name', ''))}</b><div class='sub' style='margin:2px 0 0 0;'>{badge}<div class='sub' style='margin:6px 0 0 0;'><a href='/admin/locations?site={escape(s.get('name', ''))}' style='color:var(--navy);font-weight:600;'>View map</a></div></td>
            <td class='num'>{escape(s.get('lat', ''))}</td>
            <td class='num'>{escape(s.get('lon', ''))}</td>
            <td class='num'>{escape(s.get('rad', ''))}</td>
            <td style='min-width:340px;'>
              <form method="POST" action="/admin/locations/save" style="margin:0; display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                <input type="hidden" name="csrf" value="{escape(csrf)}">
                <input type="hidden" name="orig_name" value="{escape(s.get('name', ''))}">
                <input class="input" name="name" value="{escape(s.get('name', ''))}" placeholder="Site name" style="margin-top:0; max-width:160px;">
                <input class="input" name="lat" value="{escape(s.get('lat', ''))}" placeholder="Lat" style="margin-top:0; max-width:120px;">
                <input class="input" name="lon" value="{escape(s.get('lon', ''))}" placeholder="Lon" style="margin-top:0; max-width:120px;">
                <input class="input" name="rad" value="{escape(s.get('rad', ''))}" placeholder="Radius m" style="margin-top:0; max-width:110px;">
                <label class="sub" style="display:flex; align-items:center; gap:8px; margin:0;">
                  <input type="checkbox" name="active" value="yes" {"checked" if act_on else ""}>
                  Active
                </label>
                <button class="btnTiny" type="submit">Save</button>
              </form>
              <form method="POST" action="/admin/locations/deactivate" style="margin-top:8px;">
                <input type="hidden" name="csrf" value="{escape(csrf)}">
                <input type="hidden" name="name" value="{escape(s.get('name', ''))}">
                <button class="btnTiny dark" type="submit">Deactivate</button>
              </form>
            </td>
          </tr>
        """

    table_body = "".join(
        [row_html(r) for r in all_rows]) if all_rows else "<tr><td colspan='5'>No locations yet.</td></tr>"

    # Map preview (no API key): OpenStreetMap embed for selected site
    selected = (request.args.get("site") or "").strip()
    chosen = None
    for rr in all_rows:
        if selected and rr.get("name", "").strip().lower() == selected.lower():
            chosen = rr
            break
    if not chosen and all_rows:
        chosen = all_rows[0]

    map_card = ""
    if chosen:
        try:
            latf = float((chosen.get("lat") or "0").strip())
            lonf = float((chosen.get("lon") or "0").strip())
            delta = 0.006
            left = lonf - delta
            right = lonf + delta
            top = latf + delta
            bottom = latf - delta
            # OSM embed URL
            osm = f"https://www.openstreetmap.org/export/embed.html?bbox={left}%2C{bottom}%2C{right}%2C{top}&layer=mapnik&marker={latf}%2C{lonf}"
            map_card = f"""
              <div class="card" style="padding:12px; margin-top:12px;">
                <h2>Map preview</h2>
                <div class="sub" style="margin-top:6px;">{escape(chosen.get('name', ''))} • {escape(chosen.get('lat', ''))}, {escape(chosen.get('lon', ''))}</div>
                <div style="margin-top:12px; border-radius:18px; overflow:hidden; border:1px solid rgba(11,18,32,.10);">
                  <iframe title="map" src="{osm}" style="width:100%; height:320px; border:0;" loading="lazy"></iframe>
                </div>
                <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
                  <a href="https://www.google.com/maps?q={latf},{lonf}" target="_blank" rel="noopener noreferrer" style="color:var(--navy); font-weight:600;">Open in Google Maps</a>
                  <a href="https://www.openstreetmap.org/?mlat={latf}&mlon={lonf}#map=18/{latf}/{lonf}" target="_blank" rel="noopener noreferrer" style="color:var(--navy); font-weight:600;">Open in OSM</a>
                </div>
              </div>
            """
        except Exception:
            map_card = ""

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Locations</h1>
          <p class="sub">Clock in/out will only work inside an allowed location radius.</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {map_card}

      <div class="card" style="padding:12px;">
        <h2>Add location</h2>
        <form method="POST" action="/admin/locations/save">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <input type="hidden" name="orig_name" value="">
          <div class="row2">
            <div>
              <label class="sub">Site name</label>
              <input class="input" name="name" placeholder="e.g. Site A" required>
            </div>
            <div>
              <label class="sub">Radius (meters)</label>
              <input class="input" name="rad" placeholder="e.g. 150" required>
            </div>
          </div>
          <div class="row2">
            <div>
              <label class="sub">Latitude</label>
              <input class="input" name="lat" placeholder="e.g. 51.5074" required>
            </div>
            <div>
              <label class="sub">Longitude</label>
              <input class="input" name="lon" placeholder="e.g. -0.1278" required>
            </div>
          </div>
          <label class="sub" style="display:flex; align-items:center; gap:8px; margin-top:10px;">
            <input type="checkbox" name="active" value="yes" checked> Active
          </label>
          <button class="btnSoft" type="submit" style="margin-top:12px;">Add</button>
        </form>
      </div>

      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>All locations</h2>
        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:980px;">
            <thead><tr><th>Site</th><th class="num">Lat</th><th class="num">Lon</th><th class="num">Radius (m)</th><th>Manage</th></tr></thead>
            <tbody>{table_body}</tbody>
          </table>
        </div>
        <p class="sub" style="margin-top:10px;">
          Tip: Use your phone’s Google Maps to read the site latitude/longitude (drop a pin → share → coordinates).
        </p>
      </div>
    """
    return render_app_page(
        "admin",
        session.get("role", "admin"),
        content,
    )


@app.post("/admin/locations/save")
def admin_locations_save():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    name = (request.form.get("name") or "").strip()
    orig = (request.form.get("orig_name") or "").strip()
    lat = (request.form.get("lat") or "").strip()
    lon = (request.form.get("lon") or "").strip()
    rad = (request.form.get("rad") or "").strip()
    active = "TRUE" if (request.form.get("active") == "yes") else "FALSE"

    if not locations_sheet or not name:
        return redirect("/admin/locations")

    try:
        float(lat);
        float(lon);
        float(rad)
    except Exception:
        return redirect("/admin/locations")

    _ensure_locations_headers()

    rownum = _find_location_row_by_name(orig or name)
    row = [name, lat, lon, rad, active, _session_workplace_id()]
    try:
        if rownum:
            locations_sheet.update(f"A{rownum}:F{rownum}", [row])
        else:
            locations_sheet.append_row(row)
    except Exception:
        pass

    if DB_MIGRATION_MODE:
        try:
            wp = _session_workplace_id()

            db_row = Location.query.filter_by(
                workplace_id=wp,
                site_name=(orig or name)
            ).first()

            if not db_row:
                db_row = Location.query.filter_by(
                    workplace_id=wp,
                    site_name=name
                ).first()

            if db_row:
                db_row.site_name = name
                db_row.lat = float(lat)
                db_row.lon = float(lon)
                db_row.radius_meters = int(float(rad))
                db_row.active = active
            else:
                db.session.add(
                    Location(
                        site_name=name,
                        lat=float(lat),
                        lon=float(lon),
                        radius_meters=int(float(rad)),
                        active=active,
                        workplace_id=wp,
                    )
                )

            db.session.commit()
        except Exception:
            db.session.rollback()

    actor = session.get("username", "admin")
    log_audit("LOCATIONS_SAVE", actor=actor, username="", date_str="",
              details=f"{name} {lat},{lon} r={rad} active={active}")
    return redirect("/admin/locations")


@app.post("/admin/locations/deactivate")
def admin_locations_deactivate():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    name = (request.form.get("name") or "").strip()
    if not locations_sheet or not name:
        return redirect("/admin/locations")

    rownum = _find_location_row_by_name(name)
    if rownum:
        try:
            locations_sheet.update_cell(rownum, 5, "FALSE")

            if DB_MIGRATION_MODE:
                try:
                    wp = _session_workplace_id()
                    db_row = Location.query.filter_by(workplace_id=wp, site_name=name).first()
                    if db_row:
                        db_row.active = "FALSE"
                        db.session.commit()
                except Exception:
                    db.session.rollback()
        except Exception:
            pass

    actor = session.get("username", "admin")
    log_audit("LOCATIONS_DEACTIVATE", actor=actor, username="", date_str="", details=name)
    return redirect("/admin/locations")


@app.get("/admin/employee-sites")
def admin_employee_sites():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()

    sites = _get_active_locations()
    site_names = [s["name"] for s in sites] if sites else []

    rows_html = []
    employee_rows = get_employees_compat()

    def build_opts(current: str):
        opts = []
        cur = (current or "").strip()
        cur_l = cur.lower()

        if cur and (cur not in site_names):
            opts.append(f"<option value='{escape(cur)}' selected>{escape(cur)} (inactive/unknown)</option>")

        if not site_names:
            opts.append("<option value='' selected>(No active locations)</option>")
        else:
            opts.append("<option value=''>— None —</option>")
            for n in site_names:
                sel = "selected" if (n.strip().lower() == cur_l and cur) else ""
                opts.append(f"<option value='{escape(n)}' {sel}>{escape(n)}</option>")

        return "".join(opts)

    current_wp = _session_workplace_id()

    for user in employee_rows:
        u = (user.get("Username") or "").strip()
        if not u:
            continue

        row_wp = (user.get("Workplace_ID") or "default").strip() or "default"
        if row_wp != current_wp:
            continue

        fn = (user.get("FirstName") or "").strip()
        ln = (user.get("LastName") or "").strip()
        raw_site = (user.get("Site") or "").strip()
        disp = (fn + " " + ln).strip() or u

        assigned = _get_employee_sites(u)
        s1 = assigned[0] if len(assigned) > 0 else ""
        s2 = assigned[1] if len(assigned) > 1 else ""

        chips = []
        if not assigned:
            chips.append("<span class='chip warn'>No site (fallback to any active)</span>")
        else:
            for s in assigned[:2]:
                if s and s in site_names:
                    chips.append(f"<span class='chip ok'>{escape(s)}</span>")
                elif s:
                    chips.append(f"<span class='chip bad'>{escape(s)}?</span>")

        rows_html.append(f"""
          <tr>
            <td>
              <div style='display:flex; align-items:center; gap:10px;'>
                <div class='avatar'>{escape(initials(disp))}</div>
                <div>
                  <div style='font-weight:600;'>{escape(disp)}</div>
                  <div class='sub' style='margin:2px 0 0 0;'>{escape(u)}</div>
                  <div style='margin-top:6px; display:flex; gap:6px; flex-wrap:wrap;'>{''.join(chips)}</div>
                </div>
              </div>
            </td>
            <td style='min-width:420px;'>
              <form method='POST' action='/admin/employee-sites/save' style='margin:0; display:flex; gap:8px; align-items:center; flex-wrap:wrap;'>
                <input type='hidden' name='csrf' value='{escape(csrf)}'>
                <input type='hidden' name='user' value='{escape(u)}'>
                <select class='input' name='site1' style='margin-top:0; max-width:200px;'>
                  {build_opts(s1)}
                </select>
                <select class='input' name='site2' style='margin-top:0; max-width:200px;'>
                  {build_opts(s2)}
                </select>
                <button class='btnTiny' type='submit'>Save</button>
              </form>
              <div class='sub' style='margin-top:6px;'>Tip: leave both blank to allow clock-in at any active site.</div>
            </td>
            <td class='sub'>{escape(raw_site) if raw_site else ''}</td>
          </tr>
        """)

    body = "".join(rows_html) if rows_html else "<tr><td colspan='3'>No employees found.</td></tr>"

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Employee Sites</h1>
          <p class="sub">Assign each employee to up to 2 sites (used for geo-fence clock in/out).</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      <div class="card" style="padding:12px;">
        <p class="sub" style="margin-top:0;">
          This updates the <b>Employees → Site</b> column. You can save <b>two sites</b>; they will be stored as <b>Site1,Site2</b>.
          If no site is set for an employee, the app falls back to <b>any active</b> location.
        </p>
        <a href="/admin/locations" style="display:inline-block; margin-top:8px;">
          <button class="btnSoft" type="button">Manage Locations</button>
        </a>
      </div>

      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>Employees</h2>
        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:980px;">
            <thead><tr><th>Employee</th><th>Assign site(s)</th><th>Raw</th></tr></thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </div>
    """

    return render_app_page(
        "admin",
        session.get("role", "admin"),
        content,
    )


@app.post("/admin/employee-sites/save")
def admin_employee_sites_save():
    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    u = (request.form.get("user") or "").strip()
    s1 = (request.form.get("site1") or "").strip()
    s2 = (request.form.get("site2") or "").strip()

    if s1 and s2 and s1.strip().lower() == s2.strip().lower():
        s2 = ""

    site_val = f"{s1},{s2}" if (s1 and s2) else (s1 or s2 or "")

    if u:
        if not _find_employee_record(u):
            return redirect("/admin/employee-sites")

        try:
            headers = get_sheet_headers(employees_sheet)
            if headers and "Site" not in headers:
                headers2 = headers + ["Site"]
                end_col = gspread.utils.rowcol_to_a1(1, len(headers2)).replace("1", "")
                employees_sheet.update(f"A1:{end_col}1", [headers2])
        except Exception:
            pass

        try:
            set_employee_field(u, "Site", site_val)
        except Exception:
            pass

        if DB_MIGRATION_MODE:
            try:
                wp = _session_workplace_id()
                db_row = Employee.query.filter_by(username=u, workplace_id=wp).first()
                if not db_row:
                    db_row = Employee.query.filter_by(email=u, workplace_id=wp).first()
                if db_row:
                    db_row.site = site_val
                    db_row.workplace = wp
                    db_row.workplace_id = wp
                    db.session.commit()
            except Exception:
                db.session.rollback()

        actor = session.get("username", "admin")
        log_audit("EMPLOYEE_SITE_SET", actor=actor, username=u, date_str="", details=f"site={site_val}")

    return redirect("/admin/employee-sites")


@app.route("/admin/employees", methods=["GET", "POST"])
def admin_employees():
    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    msg = ""
    ok = False
    created = None

    if request.method == "POST":
        require_csrf()
        action = (request.form.get("action") or "create").strip().lower()

        if action == "update":
            edit_username = (request.form.get("edit_username") or "").strip()
            raw_edit_role = (request.form.get("edit_role") or "").strip()
            edit_role = raw_edit_role
            edit_rate_raw = (request.form.get("edit_rate") or "").strip()
            edit_early_access = (request.form.get("edit_early_access") or "").strip()
            actor_role = (session.get("role") or "employee").strip().lower()
            if raw_edit_role:
                sanitized_role = _sanitize_requested_role(raw_edit_role, actor_role)
                if not sanitized_role:
                    ok = False
                    msg = "You are not allowed to assign that role."
                else:
                    edit_role = sanitized_role

            if not edit_username:
                ok = False
                msg = "Enter a username to update."
            else:
                _ensure_employees_columns()
                headers = get_sheet_headers(employees_sheet)

                rownum = find_row_by_username(employees_sheet, edit_username)  # tenant-safe
                if not rownum:
                    ok = False
                    msg = "Employee not found in this workplace."
                else:
                    new_rate_str = None
                    if edit_rate_raw != "":
                        try:
                            new_rate_str = str(float(edit_rate_raw))
                        except Exception:
                            ok = False
                            msg = "Hourly rate must be a number."

                    if not msg:
                        existing = employees_sheet.row_values(rownum)
                        row = (existing + [""] * max(0, len(headers) - len(existing)))[:len(headers)]

                        changed = []

                        if edit_role != "" and "Role" in headers:
                            row[headers.index("Role")] = edit_role
                            changed.append(f"role={edit_role}")

                        if new_rate_str is not None and "Rate" in headers:
                            row[headers.index("Rate")] = new_rate_str
                            changed.append(f"rate={new_rate_str}")

                        if edit_early_access in ("TRUE", "FALSE") and "EarlyAccess" in headers:
                            row[headers.index("EarlyAccess")] = edit_early_access
                            changed.append(f"early_access={edit_early_access}")

                        if not changed:
                            ok = False
                            msg = "Nothing to update (enter a new role, rate, and/or early access change)."
                        else:
                            end_col = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
                            try:
                                employees_sheet.update(f"A{rownum}:{end_col}{rownum}", [row])
                                actor = session.get("username", "admin")
                                log_audit("EMPLOYEE_UPDATE", actor=actor, username=edit_username, date_str="",
                                          details=" ".join(changed))

                                if DB_MIGRATION_MODE:
                                    try:
                                        def _row_str(col_name, default=""):
                                            if headers and col_name in headers:
                                                idx = headers.index(col_name)
                                                if idx < len(row):
                                                    return str(row[idx] or "").strip()
                                            return default

                                        username_db = _row_str("Username", edit_username) or edit_username
                                        first_name_db = _row_str("FirstName")
                                        last_name_db = _row_str("LastName")
                                        full_name_db = (" ".join([first_name_db, last_name_db])).strip()
                                        role_db = _row_str("Role")
                                        password_db = _normalize_password_hash_value(_row_str("Password"))
                                        early_access_db = _row_str("EarlyAccess")
                                        active_db = _row_str("Active", "TRUE") or "TRUE"
                                        workplace_id_db = _row_str("Workplace_ID",
                                                                   _session_workplace_id()) or _session_workplace_id()
                                        site_db = _row_str("Site")

                                        rate_db = None
                                        rate_raw_db = _row_str("Rate")
                                        if rate_raw_db != "":
                                            try:
                                                rate_db = Decimal(rate_raw_db)
                                            except Exception:
                                                rate_db = None

                                        db_row = Employee.query.filter_by(username=username_db, workplace_id=workplace_id_db).first()
                                        if not db_row:
                                            db_row = Employee.query.filter_by(email=username_db, workplace_id=workplace_id_db).first()

                                        if db_row:
                                            db_row.email = username_db
                                            db_row.name = full_name_db or username_db
                                            db_row.role = role_db
                                            db_row.workplace = workplace_id_db
                                            db_row.username = username_db
                                            db_row.first_name = first_name_db
                                            db_row.last_name = last_name_db
                                            db_row.password = password_db or db_row.password
                                            db_row.rate = rate_db
                                            db_row.early_access = early_access_db
                                            db_row.active = active_db
                                            db_row.workplace_id = workplace_id_db
                                            db_row.site = site_db
                                        else:
                                            db.session.add(
                                                Employee(
                                                    email=username_db,
                                                    name=full_name_db or username_db,
                                                    role=role_db,
                                                    workplace=workplace_id_db,
                                                    created_at=None,
                                                    username=username_db,
                                                    first_name=first_name_db,
                                                    last_name=last_name_db,
                                                    password=password_db,
                                                    rate=rate_db,
                                                    early_access=early_access_db,
                                                    active=active_db,
                                                    workplace_id=workplace_id_db,
                                                    site=site_db,
                                                )
                                            )

                                        db.session.commit()
                                    except Exception:
                                        db.session.rollback()

                                ok = True
                                msg = "Employee updated."
                            except Exception:
                                ok = False
                                msg = "Could not update employee (sheet write failed)."

        elif action in ("deactivate", "reactivate"):
            edit_username = (request.form.get("edit_username") or "").strip()
            if not edit_username:
                ok = False
                msg = "Choose an employee."
            else:
                _ensure_employees_columns()
                headers = get_sheet_headers(employees_sheet)

                # Ensure Active column exists
                if headers and "Active" not in headers:
                    headers2 = headers + ["Active"]
                    end_col_h = gspread.utils.rowcol_to_a1(1, len(headers2)).replace("1", "")
                    employees_sheet.update(f"A1:{end_col_h}1", [headers2])
                    headers = headers2

                rownum = find_row_by_username(employees_sheet, edit_username)  # tenant-safe
                if not rownum:
                    ok = False
                    msg = "Employee not found in this workplace."
                else:
                    existing = employees_sheet.row_values(rownum)
                    row = (existing + [""] * max(0, len(headers) - len(existing)))[:len(headers)]

                    val = "FALSE" if action == "deactivate" else "TRUE"
                    if "Active" in headers:
                        row[headers.index("Active")] = val

                    end_col = gspread.utils.rowcol_to_a1(1, len(headers)).replace("1", "")
                    try:
                        employees_sheet.update(f"A{rownum}:{end_col}{rownum}", [row])
                        actor = session.get("username", "admin")
                        if action == "deactivate":
                            log_audit("EMPLOYEE_DEACTIVATE", actor=actor, username=edit_username, date_str="",
                                      details="active=FALSE")
                            msg = "Employee deactivated."
                        else:
                            log_audit("EMPLOYEE_REACTIVATE", actor=actor, username=edit_username, date_str="",
                                      details="active=TRUE")
                            msg = "Employee reactivated."

                        if DB_MIGRATION_MODE:
                            try:
                                db_row = Employee.query.filter_by(username=edit_username, workplace_id=_session_workplace_id()).first()
                                if not db_row:
                                    db_row = Employee.query.filter_by(email=edit_username, workplace_id=_session_workplace_id()).first()

                                if db_row:
                                    db_row.active = val
                                    if action == "deactivate":
                                        db_row.active_session_token = None
                                    db_row.workplace = _session_workplace_id()
                                    db_row.workplace_id = _session_workplace_id()
                                    db.session.commit()
                            except Exception:
                                db.session.rollback()

                        ok = True
                    except Exception:
                        ok = False
                        msg = "Could not update employee (sheet write failed)."

        elif action == "reset_password":
            if session.get("role") != "master_admin":
                ok = False
                msg = "Only master admin can reset passwords."
            else:
                packed_target = (request.form.get("reset_target") or "").strip()
                legacy_username = (request.form.get("reset_username") or "").strip()
                new_password = (request.form.get("new_password") or "").strip()

                target_wp = (_session_workplace_id() or "default").strip() or "default"
                reset_username = legacy_username
                if packed_target and "||" in packed_target:
                    target_wp, reset_username = packed_target.split("||", 1)
                    target_wp = (target_wp or "").strip() or "default"
                    reset_username = (reset_username or "").strip()

                if not reset_username:
                    ok = False
                    msg = "Choose a user to reset."
                elif len(new_password) < 8:
                    ok = False
                    msg = "New password must be at least 8 characters."
                else:
                    changed = update_employee_password(reset_username, new_password, workplace_id=target_wp)
                    if changed:
                        actor = session.get("username", "master_admin")
                        log_audit(
                            "EMPLOYEE_PASSWORD_RESET",
                            actor=actor,
                            username=reset_username,
                            date_str="",
                            details=f"manual reset workplace={target_wp}",
                        )
                        ok = True
                        msg = f"Password reset for {reset_username} ({target_wp})."
                    else:
                        ok = False
                        msg = "Could not reset password for that user."

        elif action == "create":
            first = (request.form.get("first") or "").strip()
            last = (request.form.get("last") or "").strip()
            actor_role = (session.get("role") or "employee").strip().lower()
            raw_role_new = (request.form.get("role") or "employee").strip() or "employee"
            role_new = _sanitize_requested_role(raw_role_new, actor_role)
            rate_raw = (request.form.get("rate") or "").strip()

            if not role_new:
                return make_response("You are not allowed to create a user with that role.", 403)

            try:
                rate_val = float(rate_raw) if rate_raw != "" else 0.0
            except Exception:
                rate_val = 0.0

            wp = _session_workplace_id()

            _ensure_employees_columns()
            headers = get_sheet_headers(employees_sheet)

            new_username = _generate_unique_username(first, last, wp)
            temp_pw = _generate_temp_password(10)
            hashed = generate_password_hash(temp_pw)

            row = [""] * (len(headers) if headers else 0)

            def set_col(col_name: str, value: str):
                if headers and col_name in headers:
                    row[headers.index(col_name)] = value

            set_col("Username", new_username)
            set_col("Password", hashed)
            set_col("Role", role_new)
            set_col("Rate", str(rate_val))
            set_col("EarlyAccess", "TRUE")
            set_col("OnboardingCompleted", "")
            set_col("FirstName", first)
            set_col("LastName", last)
            set_col("Workplace_ID", wp)

            try:
                employees_sheet.append_row(row)
                actor = session.get("username", "admin")
                log_audit("EMPLOYEE_CREATE", actor=actor, username=new_username, date_str="",
                          details=f"role={role_new} rate={rate_val}")

                if DB_MIGRATION_MODE:
                    try:
                        full_name = (" ".join([first, last])).strip()

                        db_row = Employee.query.filter_by(username=new_username, workplace_id=wp).first()
                        if not db_row:
                            db_row = Employee.query.filter_by(email=new_username, workplace_id=wp).first()

                        if db_row:
                            db_row.email = new_username
                            db_row.name = full_name or new_username
                            db_row.role = role_new
                            db_row.workplace = wp
                            db_row.username = new_username
                            db_row.first_name = first
                            db_row.last_name = last
                            db_row.password = hashed
                            db_row.rate = Decimal(str(rate_val))
                            db_row.early_access = "TRUE"
                            db_row.active = "TRUE"
                            db_row.workplace_id = wp
                            db_row.site = ""
                        else:
                            db.session.add(
                                Employee(
                                    email=new_username,
                                    name=full_name or new_username,
                                    role=role_new,
                                    workplace=wp,
                                    created_at=None,
                                    username=new_username,
                                    first_name=first,
                                    last_name=last,
                                    password=hashed,
                                    rate=Decimal(str(rate_val)),
                                    early_access="TRUE",
                                    active="TRUE",
                                    workplace_id=wp,
                                    site="",
                                )
                            )

                        db.session.commit()
                    except Exception:
                        db.session.rollback()

                ok = True
                msg = "Employee created."
                created = {"u": new_username, "p": temp_pw, "wp": wp}
            except Exception:
                ok = False
                msg = "Could not create employee (sheet write failed)."

        else:
            ok = False
            msg = "Unknown action."

    # List employees in this workplace
    wp = _session_workplace_id()
    rows_html = []
    try:
        records = []

        if DB_MIGRATION_MODE:
            for rec in Employee.query.all():
                username = str(getattr(rec, "username", None) or getattr(rec, "email", "") or "").strip()
                first_name = str(getattr(rec, "first_name", "") or "").strip()
                last_name = str(getattr(rec, "last_name", "") or "").strip()
                full_name = str(getattr(rec, "name", "") or "").strip()
                role = str(getattr(rec, "role", "") or "").strip()

                rate_val = getattr(rec, "rate", None)
                rate = "" if rate_val is None else str(rate_val).strip()

                early_access = str(getattr(rec, "early_access", "") or "").strip()
                workplace_id = str(
                    getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"
                ).strip() or "default"

                if (not first_name and not last_name) and full_name:
                    parts = [p for p in full_name.split() if p]
                    if parts:
                        first_name = parts[0]
                        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

                if not username:
                    continue

                records.append({
                    "Username": username,
                    "FirstName": first_name,
                    "LastName": last_name,
                    "Role": role,
                    "Rate": rate,
                    "EarlyAccess": early_access,
                    "Workplace_ID": workplace_id,
                })
        else:
            records = get_employees_compat()

        headers = ["Username", "FirstName", "LastName", "Role", "Rate", "EarlyAccess", "Workplace_ID"]
        vals = [headers] + [
            [
                rec.get("Username", ""),
                rec.get("FirstName", ""),
                rec.get("LastName", ""),
                rec.get("Role", ""),
                rec.get("Rate", ""),
                rec.get("EarlyAccess", ""),
                rec.get("Workplace_ID", ""),
            ]
            for rec in records
        ]

        for rec in records:
            u = (rec.get("Username") or "").strip()
            if not u:
                continue

            row_wp = (rec.get("Workplace_ID") or "default").strip() or "default"
            if row_wp != wp:
                continue

            fn = (rec.get("FirstName") or "").strip()
            ln = (rec.get("LastName") or "").strip()
            rr = (rec.get("Role") or "").strip()
            rate = str(rec.get("Rate") or "").strip()
            early = str(rec.get("EarlyAccess") or "").strip()
            early_label = "Yes" if early.lower() in ("true", "1", "yes") else "No"
            disp = (fn + " " + ln).strip() or u

            rows_html.append(
                f"<tr><td>{escape(disp)}</td><td>{escape(u)}</td><td>{escape(rr)}</td><td>{escape(early_label)}</td><td class='num'>{escape(rate)}</td></tr>"
            )
    except Exception:
        rows_html = []
    # Role suggestions from Employees sheet (this workplace)
    role_suggestions = ["employee", "manager", "admin"]
    try:
        found = set()
        # reuse vals/headers from above if they exist
        if "vals" in locals() and "headers" in locals() and headers and "Role" in headers:
            i_role2 = headers.index("Role")
            i_wp2 = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
            for r in (vals[1:] if len(vals) > 1 else []):
                if i_wp2 is not None:
                    row_wp = (r[i_wp2] if i_wp2 < len(r) else "").strip() or "default"
                    if row_wp != wp:
                        continue
                rr = (r[i_role2] if i_role2 < len(r) else "").strip()
                if rr:
                    found.add(rr)
        role_suggestions = sorted(set(role_suggestions) | found, key=lambda x: x.lower())
    except Exception:
        pass

    role_options_html = "".join(f"<option value='{escape(r)}'></option>" for r in role_suggestions)
    table = "".join(rows_html) if rows_html else "<tr><td colspan='4'>No employees found.</td></tr>"

    created_card = ""
    if created:
        created_card = f"""
        <div class="card" style="padding:12px; margin-top:12px;">
          <h2>Employee created</h2>
          <p class="sub">Give these login details to the employee (they can change password in Profile).</p>
          <div class="card" style="padding:12px; background:rgba(56,189,248,.18); border:1px solid rgba(56,189,248,.35); color:rgba(2,6,23,.95);">
            <div><b>Username:</b> {escape(created["u"])}</div>
            <div><b>Company:</b> {escape(get_company_settings().get("Company_Name") or created["wp"])}</div>
            <div><b>Temp password:</b> {escape(created["p"])}</div>
          </div>
        </div>
        """
        # Build employee dropdown options (this workplace)
    employee_options_html = "<option value='' selected disabled>Select employee</option>"
    delete_employee_options_html = "<option value='' selected disabled>Select employee</option>"
    try:
        wp_now = _session_workplace_id()
        records = []

        if DB_MIGRATION_MODE:
            for rec in Employee.query.all():
                username = str(getattr(rec, "username", None) or getattr(rec, "email", "") or "").strip()
                first_name = str(getattr(rec, "first_name", "") or "").strip()
                last_name = str(getattr(rec, "last_name", "") or "").strip()
                full_name = str(getattr(rec, "name", "") or "").strip()
                active = str(getattr(rec, "active", "TRUE") or "TRUE").strip()
                workplace_id = str(
                    getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"
                ).strip() or "default"

                if (not first_name and not last_name) and full_name:
                    parts = [p for p in full_name.split() if p]
                    if parts:
                        first_name = parts[0]
                        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

                if not username:
                    continue

                role = str(getattr(rec, "role", "") or "").strip()

                records.append({
                    "Username": username,
                    "FirstName": first_name,
                    "LastName": last_name,
                    "Role": role,
                    "Active": active,
                    "Workplace_ID": workplace_id,
                })
        else:
            records = get_employees_compat()

        for rec in records:
            u = str(rec.get("Username") or "").strip()
            if not u:
                continue

            r_wp = str(rec.get("Workplace_ID") or "default").strip() or "default"
            if r_wp != wp_now:
                continue

            a = str(rec.get("Active") or "TRUE").strip().lower()
            inactive_tag = " (inactive)" if a in ("false", "0", "no") else ""

            fn = str(rec.get("FirstName") or "").strip()
            ln = str(rec.get("LastName") or "").strip()
            disp = (fn + " " + ln).strip() or u

            role_raw = str(rec.get("Role") or "").strip().lower()
            label = f"{disp}{inactive_tag} ({u})"

            employee_options_html += f"<option value='{escape(u)}'>{escape(label)}</option>"

            if role_raw != "master_admin":
                delete_employee_options_html += f"<option value='{escape(u)}'>{escape(label)}</option>"
    except Exception:
        pass

    reset_user = session.pop("_pwreset_user", "")
    session.pop("_pwreset_password", None)
    reset_msg = session.pop("_pwreset_msg", "")
    reset_ok = session.pop("_pwreset_ok", None)
    emp_msg = session.pop("_emp_msg", "")
    emp_ok = session.pop("_emp_ok", None)

    if reset_ok is not None:
        msg = reset_msg
        ok = bool(reset_ok)

    if emp_ok is not None:
        msg = emp_msg
        ok = bool(emp_ok)

    reset_card = ""
    if session.get("role") == "master_admin":
        reset_card = f"""
          <div class="card" style="padding:12px; margin-top:12px;">
            <h2>Reset Password</h2>
            <p class="sub">Master admin can reset passwords only for users in the current workplace.</p>

            <form method="POST" action="/admin/employees/reset-password" style="margin-top:12px;">
              <input type="hidden" name="csrf" value="{escape(csrf)}">

              <label class="sub">Username</label>
              <select class="input" name="username" required>
                {employee_options_html}
              </select>

              <label class="sub" style="margin-top:10px;">New password</label>
              <input class="input" type="password" name="new_password" minlength="8" required>

              <button class="btnSoft" type="submit" style="margin-top:12px;">Reset password</button>
            </form>
          </div>
       """
    reset_result_card = ""
    if reset_ok and reset_user:
        reset_result_card = f"""
          <div class="card" style="padding:12px; margin-top:12px; background:rgba(56,189,248,.12); border:1px solid rgba(56,189,248,.35);">
            <h2>Password Updated</h2>
            <p class="sub">Password was updated successfully for this user.</p>
            <div style="font-weight:700; margin-top:8px;">User: {escape(reset_user)}</div>
          </div>
        """
    danger_card = ""
    if session.get("role") == "master_admin":
        danger_card = f"""
      <div class="card" style="padding:12px; margin-top:12px; border:1px solid rgba(239,68,68,.25);">
        <h2>Clear / Delete Employee</h2>
        <p class="sub">Clear timesheet + payroll history, or delete the employee completely.</p>

        <form method="POST" action="/admin/employees/clear-history" style="margin-top:12px;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">

          <label class="sub">Employee</label>
          <select class="input" name="username" required>
            {employee_options_html}
          </select>

          <button class="btnSoft" type="submit" style="margin-top:12px;"
                  onclick="return confirm('Clear all clock and payroll history for this employee?');">
            Clear history
          </button>
        </form>

        <form method="POST" action="/admin/employees/delete" style="margin-top:12px;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">

          <label class="sub">Delete employee</label>
          <select class="input" name="username" required>
            {delete_employee_options_html}
          </select>

          <button class="btnSoft" type="submit" style="margin-top:12px; background:#7f1d1d; border-color:#7f1d1d;"
                  onclick="return confirm('Delete this employee completely? This cannot be undone.');">
            Delete account
          </button>
        </form>
      </div>
    """

    content = f"""

      <div class="headerTop">
        <div>
          <h1>Create Employee</h1>
          <p class="sub">Create a new employee login (auto username + temp password)</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
{("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

{reset_result_card}
{danger_card}

      <div class="card" style="padding:12px;">
        <form method="POST">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <div class="row2">
            <div>
              <label class="sub">First name</label>
              <input class="input" name="first" placeholder="e.g. John" required>
            </div>
            <div>
              <label class="sub">Last name</label>
              <input class="input" name="last" placeholder="e.g. Smith" required>
            </div>
          </div>

          <div class="row2">
            <div>
              <label class="sub">Role</label>
              <input class="input" name="role" list="role_list" value="employee">
              <datalist id="role_list">
                {role_options_html}
              </datalist>
            </div>
            <div>
              <label class="sub">Hourly rate</label>
              <input class="input" name="rate" placeholder="e.g. 25">
            </div>
          </div>

          <button class="btnSoft" type="submit" style="margin-top:12px;">Create</button>
        </form>
        <p class="sub" style="margin-top:10px;">Note: this creates the user inside Workplace_ID <b>{escape(wp)}</b>.</p>
      </div>

      {created_card}
      <div class="card" style="padding:12px; margin-top:12px;">
  <h2>Update Employee</h2>
  <p class="sub">Update role and/or hourly rate for an existing username in this workplace.</p>

  <form method="POST" style="margin-top:12px;">
    <input type="hidden" name="csrf" value="{escape(csrf)}">
   <div style="margin-top:12px; display:flex; gap:10px;">
  <button class="btnSoft" type="submit" name="action" value="update">Save changes</button>

  <button class="btnSoft" type="submit" name="action" value="deactivate"
          onclick="return confirm('Deactivate this employee?')">
    Deactivate
  </button>

  <button class="btnSoft" type="submit" name="action" value="reactivate"
          onclick="return confirm('Reactivate this employee?')">
    Reactivate
  </button>
</div>

    <label class="sub">Username</label>
    <select class="input" name="edit_username" required>
     {employee_options_html}
    </select>   

    <div class="row2" style="margin-top:10px;">
  <div>
    <label class="sub">New role (optional)</label>
    <input class="input" name="edit_role" list="role_list" placeholder="Leave blank to keep existing">
  </div>
  <div>
    <label class="sub">New hourly rate (optional)</label>
    <input class="input" name="edit_rate" placeholder="Leave blank to keep existing">
  </div>
</div>

<div style="margin-top:10px;">
  <label class="sub">Early Access</label>
  <select class="input" name="edit_early_access">
    <option value="">Keep current</option>
    <option value="TRUE">Enabled</option>
    <option value="FALSE">Disabled</option>
  </select>
</div>
  </form>
</div>
      {reset_card}
      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>Employees (this workplace)</h2>
        <div class="tablewrap" style="margin-top:12px;">
          <table class="employeesTable">
            <thead>
              <tr>
                <th>Name</th>
                <th>Username</th>
                <th>Role</th>
                <th>Early Access</th>
                <th class="num">Rate</th>
              </tr>
            </thead>
            <tbody>{table}</tbody>
          </table>
        </div>
      </div>
    """
    return render_app_page(
        "admin",
        session.get("role", "admin"),
        content,
    )


@app.route("/admin/workplaces", methods=["GET", "POST"])
def admin_workplaces():
    gate = require_master_admin()
    if gate:
        return gate

    csrf = get_csrf()
    msg = ""
    ok = False
    created_info = None

    if request.method == "POST":
        require_csrf()
        action = (request.form.get("action") or "").strip().lower()

        if action == "switch":
            target_wp = (request.form.get("target_workplace") or "").strip()

            found = False
            try:
                vals = settings_sheet.get_all_values() if settings_sheet else []
                headers = vals[0] if vals else []
                i_wp = headers.index("Workplace_ID") if headers and "Workplace_ID" in headers else None

                if i_wp is not None:
                    for r in (vals[1:] if len(vals) > 1 else []):
                        row_wp = (r[i_wp] if i_wp < len(r) else "").strip()
                        if row_wp == target_wp:
                            found = True
                            break
            except Exception:
                found = False

            if not target_wp:
                msg = "No workplace selected."
            elif not found:
                msg = "Workplace not found."
            else:
                session["workplace_id"] = target_wp
                ok = True
                msg = f"Opened workplace: {target_wp}"

        elif action == "create":
            workplace_id_raw = (request.form.get("workplace_id") or "").strip()
            company_name = (request.form.get("company_name") or "").strip()
            tax_rate = (request.form.get("tax_rate") or "20").strip()
            currency_symbol = (request.form.get("currency_symbol") or "£").strip() or "£"

            admin_first = (request.form.get("admin_first") or "").strip()
            admin_last = (request.form.get("admin_last") or "").strip()
            admin_username = (request.form.get("admin_username") or "").strip()
            admin_password = (request.form.get("admin_password") or "").strip()

            workplace_id = re.sub(r"[^a-zA-Z0-9_-]", "", workplace_id_raw).strip().lower()

            if not workplace_id:
                msg = "Workplace ID is required."
            elif not company_name:
                msg = "Company name is required."
            elif not admin_first:
                msg = "Admin first name is required."
            elif not admin_last:
                msg = "Admin last name is required."
            elif not admin_username:
                msg = "Admin username is required."
            elif len(admin_password) < 8:
                msg = "Admin password must be at least 8 characters."
            else:
                exists = False
                try:
                    vals = settings_sheet.get_all_values() if settings_sheet else []
                    headers = vals[0] if vals else []

                    if not vals:
                        settings_sheet.append_row(["Workplace_ID", "Tax_Rate", "Currency_Symbol", "Company_Name"])
                        vals = settings_sheet.get_all_values()
                        headers = vals[0] if vals else []

                    i_wp = headers.index("Workplace_ID") if headers and "Workplace_ID" in headers else None

                    if i_wp is not None:
                        for r in (vals[1:] if len(vals) > 1 else []):
                            row_wp = (r[i_wp] if i_wp < len(r) else "").strip().lower()
                            if row_wp == workplace_id:
                                exists = True
                                break

                    if exists:
                        msg = "That workplace already exists."
                    else:
                        existing_users = _employees_usernames_for_workplace(workplace_id)
                        if admin_username.lower() in existing_users:
                            msg = "That admin username already exists in this workplace."
                        else:
                            settings_row = [""] * len(headers)

                            if "Workplace_ID" in headers:
                                settings_row[headers.index("Workplace_ID")] = workplace_id
                            if "Tax_Rate" in headers:
                                settings_row[headers.index("Tax_Rate")] = tax_rate
                            if "Currency_Symbol" in headers:
                                settings_row[headers.index("Currency_Symbol")] = currency_symbol
                            if "Company_Name" in headers:
                                settings_row[headers.index("Company_Name")] = company_name

                            settings_sheet.append_row(settings_row)

                            _ensure_employees_columns()
                            emp_headers = get_sheet_headers(employees_sheet)
                            emp_row = [""] * len(emp_headers)

                            def set_emp(col_name, value):
                                if col_name in emp_headers:
                                    emp_row[emp_headers.index(col_name)] = value

                            set_emp("Username", admin_username)
                            set_emp("Password", generate_password_hash(admin_password))
                            set_emp("Role", "admin")
                            set_emp("Rate", "0")
                            set_emp("EarlyAccess", "TRUE")
                            set_emp("OnboardingCompleted", "")
                            set_emp("FirstName", admin_first)
                            set_emp("LastName", admin_last)
                            set_emp("Site", "")
                            set_emp("Workplace_ID", workplace_id)
                            if "Active" in emp_headers:
                                set_emp("Active", "TRUE")

                            employees_sheet.append_row(emp_row)
                            if DB_MIGRATION_MODE:
                                try:
                                    db_setting = WorkplaceSetting.query.filter_by(workplace_id=workplace_id).first()
                                    if not db_setting:
                                        db_setting = WorkplaceSetting(workplace_id=workplace_id)
                                        db.session.add(db_setting)

                                    db_setting.tax_rate = Decimal(str(tax_rate or "20"))
                                    db_setting.currency_symbol = currency_symbol
                                    db_setting.company_name = company_name

                                    db_admin = Employee.query.filter_by(username=admin_username,
                                                                        workplace_id=workplace_id).first()
                                    if not db_admin:
                                        db_admin = Employee.query.filter_by(email=admin_username,
                                                                            workplace_id=workplace_id).first()

                                    admin_hash = generate_password_hash(admin_password)

                                    if db_admin:
                                        db_admin.email = admin_username
                                        db_admin.username = admin_username
                                        db_admin.first_name = admin_first
                                        db_admin.last_name = admin_last
                                        db_admin.name = (" ".join([admin_first, admin_last])).strip() or admin_username
                                        db_admin.password = admin_hash
                                        db_admin.role = "admin"
                                        db_admin.rate = Decimal("0")
                                        db_admin.early_access = "TRUE"
                                        db_admin.active = "TRUE"
                                        db_admin.site = ""
                                        db_admin.workplace = workplace_id
                                        db_admin.workplace_id = workplace_id
                                    else:
                                        db.session.add(
                                            Employee(
                                                email=admin_username,
                                                username=admin_username,
                                                first_name=admin_first,
                                                last_name=admin_last,
                                                name=(" ".join([admin_first, admin_last])).strip() or admin_username,
                                                password=admin_hash,
                                                role="admin",
                                                rate=Decimal("0"),
                                                early_access="TRUE",
                                                active="TRUE",
                                                site="",
                                                workplace=workplace_id,
                                                workplace_id=workplace_id,
                                                created_at=None,
                                            )
                                        )

                                    db.session.commit()
                                except Exception:
                                    db.session.rollback()

                            if DB_MIGRATION_MODE:
                                try:
                                    db_setting = WorkplaceSetting.query.filter_by(workplace_id=workplace_id).first()
                                    if not db_setting:
                                        db_setting = WorkplaceSetting(workplace_id=workplace_id)
                                        db.session.add(db_setting)

                                    db_setting.tax_rate = Decimal(str(tax_rate or "20"))
                                    db_setting.currency_symbol = currency_symbol
                                    db_setting.company_name = company_name

                                    db_admin = Employee.query.filter_by(username=admin_username,
                                                                        workplace_id=workplace_id).first()
                                    if not db_admin:
                                        db_admin = Employee.query.filter_by(email=admin_username,
                                                                            workplace_id=workplace_id).first()

                                    admin_hash = generate_password_hash(admin_password)

                                    if db_admin:
                                        db_admin.email = admin_username
                                        db_admin.username = admin_username
                                        db_admin.first_name = admin_first
                                        db_admin.last_name = admin_last
                                        db_admin.name = (" ".join([admin_first, admin_last])).strip() or admin_username
                                        db_admin.password = admin_hash
                                        db_admin.role = "admin"
                                        db_admin.rate = Decimal("0")
                                        db_admin.early_access = "TRUE"
                                        db_admin.active = "TRUE"
                                        db_admin.site = ""
                                        db_admin.workplace = workplace_id
                                        db_admin.workplace_id = workplace_id
                                    else:
                                        db.session.add(
                                            Employee(
                                                email=admin_username,
                                                username=admin_username,
                                                first_name=admin_first,
                                                last_name=admin_last,
                                                name=(" ".join([admin_first, admin_last])).strip() or admin_username,
                                                password=admin_hash,
                                                role="admin",
                                                rate=Decimal("0"),
                                                early_access="TRUE",
                                                active="TRUE",
                                                site="",
                                                workplace=workplace_id,
                                                workplace_id=workplace_id,
                                                created_at=None,
                                            )
                                        )

                                    db.session.commit()
                                except Exception:
                                    db.session.rollback()

                            session["workplace_id"] = workplace_id
                            ok = True
                            msg = f"Created workplace: {workplace_id}"
                            created_info = {
                                "workplace_id": workplace_id,
                                "company_name": company_name,
                                "admin_username": admin_username,
                                "admin_password": admin_password,
                            }
                except Exception:
                    msg = "Could not create workplace."

    rows_html = []

    try:
        vals = settings_sheet.get_all_values() if settings_sheet else []
        headers = vals[0] if vals else []

        def idx(name):
            return headers.index(name) if headers and name in headers else None

        i_wp = idx("Workplace_ID")
        i_tax = idx("Tax_Rate")
        i_cur = idx("Currency_Symbol")
        i_name = idx("Company_Name")

        current_wp = _session_workplace_id()

        for r in (vals[1:] if len(vals) > 1 else []):
            wp = (r[i_wp] if i_wp is not None and i_wp < len(r) else "").strip()
            if not wp:
                continue

            tax = (r[i_tax] if i_tax is not None and i_tax < len(r) else "").strip()
            cur = (r[i_cur] if i_cur is not None and i_cur < len(r) else "").strip()
            name = (r[i_name] if i_name is not None and i_name < len(r) else "").strip() or wp
            status_text = "Current" if wp == current_wp else ""

            if wp == current_wp:
                open_btn = "<span style='font-weight:600; color: rgba(15,23,42,.55);'>Opened</span>"
            else:
                open_btn = f"""
                  <form method="POST" style="margin:0;">
                    <input type="hidden" name="csrf" value="{escape(csrf)}">
                    <input type="hidden" name="action" value="switch">
                    <input type="hidden" name="target_workplace" value="{escape(wp)}">
                    <button class="btnTiny" type="submit">Open</button>
                  </form>
                """

            rows_html.append(f"""
              <tr>
                <td style="width:36%;">
                  <div style="font-weight:700;">{escape(name)}</div>
                  <div class="sub" style="margin:2px 0 0 0;">{escape(wp)}</div>
                </td>
                <td class="num" style="width:12%; text-align:right;">{escape(tax)}</td>
                <td style="width:12%; text-align:center;">{escape(cur)}</td>
                <td style="width:16%; text-align:left; font-weight:600; color: rgba(15,23,42,.72);">{escape(status_text)}</td>
                <td style="width:14%; text-align:center;">{open_btn}</td>
              </tr>
            """)
    except Exception:
        rows_html = []

    table_html = "".join(rows_html) if rows_html else "<tr><td colspan='5'>No workplaces found.</td></tr>"

    created_card = ""
    if created_info:
        created_card = f"""
          <div class="card" style="padding:12px; margin-top:12px;">
            <h2>First admin created</h2>
            <div class="sub">Save these details now.</div>
            <div class="card" style="padding:12px; margin-top:10px; background:rgba(56,189,248,.18); border:1px solid rgba(56,189,248,.35); color:rgba(2,6,23,.95);">
              <div><b>Company:</b> {escape(created_info["company_name"])}</div>
              <div><b>Workplace ID:</b> {escape(created_info["workplace_id"])}</div>
              <div><b>Admin username:</b> {escape(created_info["admin_username"])}</div>
              <div><b>Admin password:</b> {escape(created_info["admin_password"])}</div>
            </div>
          </div>
        """

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Workplaces</h1>
          <p class="sub">Master admin only.</p>
        </div>
        <div class="badge admin">{escape(role_label(session.get('role', 'master_admin')))}</div>
      </div>

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

      <div class="card" style="padding:12px;">
        <h2>Create workplace</h2>
        <form method="POST">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <input type="hidden" name="action" value="create">

          <div class="row2">
            <div>
              <label class="sub">Workplace ID</label>
              <input class="input" name="workplace_id" placeholder="e.g. nw01" required>
            </div>
            <div>
              <label class="sub">Company name</label>
              <input class="input" name="company_name" placeholder="e.g. Newera North" required>
            </div>
          </div>

          <div class="row2">
            <div>
              <label class="sub">Tax rate</label>
              <input class="input" name="tax_rate" value="20" required>
            </div>
            <div>
              <label class="sub">Currency symbol</label>
              <input class="input" name="currency_symbol" value="£" required>
            </div>
          </div>

          <h2 style="margin-top:14px;">First admin</h2>

          <div class="row2">
            <div>
              <label class="sub">First name</label>
              <input class="input" name="admin_first" required>
            </div>
            <div>
              <label class="sub">Last name</label>
              <input class="input" name="admin_last" required>
            </div>
          </div>

          <div class="row2">
            <div>
              <label class="sub">Username</label>
              <input class="input" name="admin_username" required>
            </div>
            <div>
              <label class="sub">Password</label>
              <input class="input" name="admin_password" required>
            </div>
          </div>

          <button class="btnSoft" type="submit" style="margin-top:12px;">Create workplace</button>
        </form>
      </div>

      {created_card}

      <div class="card" style="padding:12px; margin-top:12px;">
  <h2>Existing workplaces</h2>
  <div class="tablewrap workplacesTableWrap" style="margin-top:12px;">
    <table class="workplacesTable" style="table-layout:fixed;">
      <thead>
        <tr>
          <th style="width:36%; text-align:left;">Company</th>
          <th class="num" style="width:12%; text-align:right;">Tax</th>
          <th style="width:12%; text-align:center;">Currency</th>
          <th style="width:16%; text-align:left;">Status</th>
          <th style="width:14%; text-align:center;">Open</th>
        </tr>
      </thead>
      <tbody>{table_html}</tbody>
    </table>
  </div>
</div>
    """
    return render_app_page("workplaces", "master_admin", content)


