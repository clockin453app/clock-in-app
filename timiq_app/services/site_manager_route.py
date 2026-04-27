def site_manager_impl(core):
    require_login = core["require_login"]
    get_csrf = core["get_csrf"]
    session = core["session"]
    request = core["request"]
    redirect = core["redirect"]

    _find_employee_record = core["_find_employee_record"]
    _list_employee_records_for_workplace = core["_list_employee_records_for_workplace"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]

    get_workhours_rows = core["get_workhours_rows"]
    find_open_shift = core["find_open_shift"]
    _get_active_locations = core["_get_active_locations"]

    datetime = core["datetime"]
    timedelta = core["timedelta"]
    TZ = core["TZ"]

    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]

    escape = core["escape"]
    fmt_hours = core["fmt_hours"]
    get_employee_display_name = core["get_employee_display_name"]

    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    render_template_string = core["render_template_string"]

    gate = require_login()
    if gate:
        return gate

    role = (session.get("role") or "employee").strip().lower()
    if role not in ("site_manager", "admin", "master_admin"):
        return redirect("/")

    csrf = get_csrf()
    current_wp = _session_workplace_id()
    username = session.get("username", "")

    def rec_site_values(rec):
        vals = []

        for key in ("Site", "site", "Site2", "site2"):
            v = str((rec or {}).get(key, "") or "").strip()
            if v:
                vals.append(v)

        clean = []
        seen = set()

        for v in vals:
            k = v.lower()
            if k not in seen:
                seen.add(k)
                clean.append(v)

        return clean

    manager_rec = _find_employee_record(username, current_wp)
    manager_sites = rec_site_values(manager_rec)

    # Admin/master can test all sites from this page.
    if role in ("admin", "master_admin"):
        manager_sites = []
        try:
            for loc in (_get_active_locations() or []):
                name = str(loc.get("name") or loc.get("SiteName") or loc.get("site") or "").strip()
                if name:
                    manager_sites.append(name)
        except Exception:
            manager_sites = []

    manager_site_lowers = {s.lower() for s in manager_sites}

    employee_records = []
    try:
        employee_records = _list_employee_records_for_workplace(current_wp, include_inactive=True)
    except Exception:
        employee_records = []

    managed_users = []
    employee_options = []

    for rec in employee_records:
        u = str(rec.get("Username") or "").strip()
        if not u:
            continue

        active_raw = str(rec.get("Active") or "TRUE").strip().lower()
        if active_raw in ("false", "0", "no", "n", "off"):
            continue

        rec_sites = rec_site_values(rec)
        rec_site_lowers = {s.lower() for s in rec_sites}

        if role == "site_manager":
            if not manager_site_lowers:
                continue

            if not (rec_site_lowers & manager_site_lowers):
                continue

        managed_users.append(u)

        display = get_employee_display_name(u) or u
        site_txt = ", ".join(rec_sites) if rec_sites else "No site"
        employee_options.append(
            f"<option value='{escape(u)}'>{escape(display)} • {escape(site_txt)}</option>"
        )

    managed_users_set = set(managed_users)

    rows = get_workhours_rows()
    headers = rows[0] if rows else []

    wp_idx = headers.index("Workplace_ID") if headers and "Workplace_ID" in headers else None
    in_site_idx = headers.index("InSite") if headers and "InSite" in headers else None
    out_site_idx = headers.index("OutSite") if headers and "OutSite" in headers else None

    today = datetime.now(TZ).date()
    this_monday = today - timedelta(days=today.weekday())

    try:
        wk_offset = max(0, int((request.args.get("wk") or "0").strip()))
    except Exception:
        wk_offset = 0

    week_start = this_monday - timedelta(days=7 * wk_offset)
    week_end = week_start + timedelta(days=6)
    week_start_str = week_start.strftime("%Y-%m-%d")
    week_end_str = week_end.strftime("%Y-%m-%d")

    open_rows = []
    weekly = {}

    for r in rows[1:]:
        if len(r) <= COL_USER or len(r) <= COL_DATE:
            continue

        row_user = str(r[COL_USER] or "").strip()
        if row_user not in managed_users_set:
            continue

        if wp_idx is not None:
            row_wp = str((r[wp_idx] if wp_idx < len(r) else "") or "default").strip() or "default"
            if row_wp not in set(_workplace_ids_for_read(current_wp)):
                continue

        row_site = ""
        if out_site_idx is not None and out_site_idx < len(r):
            row_site = str(r[out_site_idx] or "").strip()
        if not row_site and in_site_idx is not None and in_site_idx < len(r):
            row_site = str(r[in_site_idx] or "").strip()

        if role == "site_manager" and row_site and row_site.lower() not in manager_site_lowers:
            continue

        d = str(r[COL_DATE] or "").strip()
        cin = str((r[COL_IN] if len(r) > COL_IN else "") or "").strip()
        cout = str((r[COL_OUT] if len(r) > COL_OUT else "") or "").strip()
        hours_raw = str((r[COL_HOURS] if len(r) > COL_HOURS else "") or "").strip()

        if cin and not cout:
            open_rows.append({
                "user": row_user,
                "name": get_employee_display_name(row_user) or row_user,
                "date": d,
                "cin": cin[:5],
                "site": row_site,
            })

        if week_start_str <= d <= week_end_str:
            weekly.setdefault(row_user, {"name": get_employee_display_name(row_user) or row_user, "hours": 0.0, "days": {}})

            try:
                h = float(hours_raw or "0")
            except Exception:
                h = 0.0

            weekly[row_user]["hours"] += h
            weekly[row_user]["days"][d] = {
                "cin": cin[:5],
                "cout": cout[:5],
                "hours": h,
                "site": row_site,
            }

    if open_rows:
        open_html_rows = []
        for item in open_rows:
            open_html_rows.append(f"""
                  <tr>
                    <td>{escape(item["name"])}</td>
                    <td>{escape(item["date"])}</td>
                    <td>{escape(item["cin"])}</td>
                    <td>{escape(item["site"])}</td>
                    <td style="min-width:240px;">
                      <form method="POST" action="/site-manager/force-clockout"
                            style="margin:0; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                        <input type="hidden" name="csrf" value="{escape(csrf)}">
                        <input type="hidden" name="user" value="{escape(item["user"])}">
                        <input class="input" type="time" step="1" name="out_time"
                               style="margin-top:0; max-width:150px;" required>
                        <button class="btnTiny" type="submit">Force Clock-Out</button>
                      </form>
                    </td>
                  </tr>
                """)
        open_table_html = "".join(open_html_rows)
    else:
        open_table_html = "<tr><td colspan='5' style='text-align:center; color:#64748b;'>No open shifts for your site.</td></tr>"
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    timesheet_rows = []
    for u in sorted(weekly.keys(), key=lambda x: weekly[x]["name"].lower()):
        item = weekly[u]
        day_cells = []

        for i in range(7):
            d_obj = week_start + timedelta(days=i)
            d_str = d_obj.strftime("%Y-%m-%d")
            rec = item["days"].get(d_str, {})

            if rec:
                day_cells.append(f"""
                  <td style="text-align:center;">
                    <div style="font-weight:900;">{escape(fmt_hours(rec.get("hours", 0)))}</div>
                    <div class="sub" style="margin-top:2px;">{escape(rec.get("cin", ""))} – {escape(rec.get("cout", ""))}</div>
                    <div class="sub" style="margin-top:2px;">{escape(rec.get("site", ""))}</div>
                  </td>
                """)
            else:
                day_cells.append("<td style='text-align:center; color:#94a3b8;'>—</td>")

        timesheet_rows.append(f"""
          <tr>
            <td style="font-weight:900;">{escape(item["name"])}</td>
            {''.join(day_cells)}
            <td class="num" style="font-weight:900;">{escape(fmt_hours(item["hours"]))}</td>
          </tr>
        """)

    if not timesheet_rows:
        timesheet_rows = [
            "<tr><td colspan='9' style='text-align:center; color:#64748b; padding:18px;'>No hours found for this week.</td></tr>"
        ]

    site_options_html = "".join(
        f"<option value='{escape(s)}'>{escape(s)}</option>"
        for s in manager_sites
    )

    if not employee_options:
        employee_options_html = "<option value=''>No employees assigned to your site</option>"
    else:
        employee_options_html = "".join(employee_options)

    prev_wk = wk_offset + 1
    next_wk = max(0, wk_offset - 1)

    no_site_warning = ""
    if role == "site_manager" and not manager_sites:
        no_site_warning = """
          <div class="message error" style="margin-top:12px;">
            No site is assigned to your Site Manager account. Ask an Admin to assign Site/Site2 to your employee profile.
          </div>
        """

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Site Manager</h1>
          <p class="sub">Site-level clocking and hours-only timesheets.</p>
          <p class="sub">Sites: {escape(", ".join(manager_sites) if manager_sites else "None")}</p>
        </div>
        <div class="badge admin">SITE MANAGER</div>
      </div>

      {no_site_warning}

      <div class="card" style="padding:14px; margin-top:12px;">
        <h2 style="margin:0;">Force Clock-In</h2>
        <p class="sub" style="margin-top:4px;">Use this if someone on your site forgot to clock in.</p>

        <form method="POST" action="/site-manager/force-clockin" style="display:flex; gap:10px; flex-wrap:wrap; margin-top:12px;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">

          <input class="input" type="date" name="date" value="{escape(today.strftime("%Y-%m-%d"))}" style="max-width:190px;" required>

          <select class="input" name="user" style="max-width:300px;" required>
            <option value="">Select employee</option>
            {employee_options_html}
          </select>

          <input class="input" type="time" step="1" name="in_time" style="max-width:170px;" required>

          <select class="input" name="site" style="max-width:240px;" required>
            <option value="">Select site</option>
            {site_options_html}
          </select>

          <button class="btnSoft" type="submit">Force Clock-In</button>
        </form>
      </div>

      <div class="card" style="padding:14px; margin-top:12px;">
        <h2 style="margin:0;">Open shifts</h2>
        <p class="sub" style="margin-top:4px;">Currently open shifts for your site.</p>

        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:720px;">
            <thead>
                            <tr>
                <th>Employee</th>
                <th>Date</th>
                <th>Clock In</th>
                <th>Site</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {open_table_html}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card" style="padding:14px; margin-top:12px;">
        <div style="display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; align-items:center;">
          <div>
            <h2 style="margin:0;">Hours-only timesheet</h2>
            <p class="sub" style="margin-top:4px;">
              Week {escape(week_start.strftime("%d %b"))} – {escape(week_end.strftime("%d %b %Y"))}. No pay or money shown.
            </p>
          </div>

          <div style="display:flex; gap:8px; align-items:center;">
            <a class="btnTiny" style="text-decoration:none;" href="/site-manager?wk={prev_wk}">‹ Previous</a>
            <a class="btnTiny" style="text-decoration:none;" href="/site-manager?wk={next_wk}">Next ›</a>
          </div>
        </div>

        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:1100px;">
            <thead>
              <tr>
                <th>Employee</th>
                {''.join(f"<th style='text-align:center;'>{day_names[i]}<br><span class='sub'>{(week_start + timedelta(days=i)).strftime('%d %b')}</span></th>" for i in range(7))}
                <th class="num">Total hours</th>
              </tr>
            </thead>
            <tbody>
              {''.join(timesheet_rows)}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card" style="padding:14px; margin-top:12px;">
        <h2 style="margin:0;">Other tools</h2>
        <p class="sub" style="margin-top:4px;">Clock selfies will be added here in Phase 2 without giving access to Admin payroll.</p>
        <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:12px;">
          <a class="btnTiny" style="text-decoration:none;" href="/clock">Clock In & Out</a>
          <a class="btnTiny" style="text-decoration:none;" href="/my-times">My Time Logs</a>
          <a class="btnTiny" style="text-decoration:none;" href="/work-progress">Work Progress</a>
        </div>
      </div>
    """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("site-manager", role, content)
    )


def site_manager_force_clockin_impl(core):
    require_login = core["require_login"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    redirect = core["redirect"]
    session = core["session"]

    _find_employee_record = core["_find_employee_record"]
    _list_employee_records_for_workplace = core["_list_employee_records_for_workplace"]
    _session_workplace_id = core["_session_workplace_id"]

    get_workhours_rows = core["get_workhours_rows"]
    find_open_shift = core["find_open_shift"]

    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    datetime = core["datetime"]
    WorkHour = core["WorkHour"]
    db = core["db"]
    make_response = core["make_response"]
    work_sheet = core["work_sheet"]
    _find_workhours_row_by_user_date = core["_find_workhours_row_by_user_date"]

    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    COL_PAY = core["COL_PAY"]

    log_audit = core["log_audit"]
    _get_canonical_workhour_for_day = core["_get_canonical_workhour_for_day"]
    _ensure_workhours_geo_headers = core["_ensure_workhours_geo_headers"]

    gate = require_login()
    if gate:
        return gate

    role = (session.get("role") or "employee").strip().lower()
    if role not in ("site_manager", "admin", "master_admin"):
        return redirect("/")

    require_csrf()

    current_wp = _session_workplace_id()
    actor = session.get("username", "")

    username = (request.form.get("user") or "").strip()
    in_time = (request.form.get("in_time") or "").strip()
    date_str = (request.form.get("date") or "").strip()
    site_name = (request.form.get("site") or "").strip()

    if not username or not in_time or not date_str or not site_name:
        return redirect(request.referrer or "/site-manager")

    def rec_sites(rec):
        vals = []
        for key in ("Site", "site", "Site2", "site2"):
            v = str((rec or {}).get(key, "") or "").strip()
            if v:
                vals.append(v.lower())
        return set(vals)

    manager_rec = _find_employee_record(actor, current_wp)
    manager_sites = rec_sites(manager_rec)

    target_rec = _find_employee_record(username, current_wp)
    target_sites = rec_sites(target_rec)

    if role == "site_manager":
        if not manager_sites:
            return make_response("No site assigned to this Site Manager account.", 403)

        if site_name.lower() not in manager_sites:
            return make_response("You can only force clock-in for your assigned site.", 403)

        if not target_rec:
            return make_response("This employee is not in your workplace.", 403)

        if not target_sites or not (target_sites & manager_sites):
            return make_response("This employee is not assigned to your site.", 403)

    if len(in_time.split(":")) == 2:
        in_time = in_time + ":00"

    rows = get_workhours_rows()
    if find_open_shift(rows, username):
        return redirect(request.referrer or "/site-manager")

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            clock_in_dt = datetime.strptime(f"{date_str} {in_time}", "%Y-%m-%d %H:%M:%S")

            db_row = WorkHour(
                employee_email=username,
                date=shift_date,
                clock_in=clock_in_dt,
                clock_out=None,
                hours=None,
                pay=None,
                in_site=site_name,
                out_site=None,
                workplace=current_wp,
                workplace_id=current_wp,
            )

            db.session.add(db_row)
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not force clock in: {e}", 500)

    else:
        _ensure_workhours_geo_headers()

        try:
            vals = work_sheet.get_all_values()
            headers = vals[0] if vals else []
            rownum = _find_workhours_row_by_user_date(vals, username, date_str)

            wp_col = (headers.index("Workplace_ID") + 1) if ("Workplace_ID" in headers) else None
            in_site_col = (headers.index("InSite") + 1) if ("InSite" in headers) else None
            out_site_col = (headers.index("OutSite") + 1) if ("OutSite" in headers) else None

            if rownum:
                work_sheet.update_cell(rownum, COL_IN + 1, in_time)
                work_sheet.update_cell(rownum, COL_OUT + 1, "")
                work_sheet.update_cell(rownum, COL_HOURS + 1, "")
                work_sheet.update_cell(rownum, COL_PAY + 1, "")

                if wp_col:
                    work_sheet.update_cell(rownum, wp_col, current_wp)
                if in_site_col:
                    work_sheet.update_cell(rownum, in_site_col, site_name)
                if out_site_col:
                    work_sheet.update_cell(rownum, out_site_col, "")

            else:
                new_row = [username, date_str, in_time, "", "", ""]

                if headers and "Workplace_ID" in headers:
                    wp_idx = headers.index("Workplace_ID")
                    if len(new_row) <= wp_idx:
                        new_row += [""] * (wp_idx + 1 - len(new_row))
                    new_row[wp_idx] = current_wp

                if headers and "InSite" in headers:
                    in_site_idx = headers.index("InSite")
                    if len(new_row) <= in_site_idx:
                        new_row += [""] * (in_site_idx + 1 - len(new_row))
                    new_row[in_site_idx] = site_name

                if headers and "OutSite" in headers:
                    out_site_idx = headers.index("OutSite")
                    if len(new_row) <= out_site_idx:
                        new_row += [""] * (out_site_idx + 1 - len(new_row))
                    new_row[out_site_idx] = ""

                if headers and len(new_row) < len(headers):
                    new_row += [""] * (len(headers) - len(new_row))

                work_sheet.append_row(new_row)

        except Exception as e:
            return make_response(f"Could not force clock in: {e}", 500)

    log_audit(
        "SITE_MANAGER_FORCE_CLOCK_IN",
        actor=actor,
        username=username,
        date_str=date_str,
        details=f"in={in_time}, site={site_name}",
    )
    return redirect(request.referrer or "/site-manager")


def site_manager_force_clockout_impl(core):
    require_login = core["require_login"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    redirect = core["redirect"]
    session = core["session"]

    _find_employee_record = core["_find_employee_record"]
    _session_workplace_id = core["_session_workplace_id"]

    get_workhours_rows = core["get_workhours_rows"]
    find_open_shift = core["find_open_shift"]

    _get_user_rate = core["_get_user_rate"]
    _compute_hours_from_times = core["_compute_hours_from_times"]
    _get_payroll_rule_for_shift = core["_get_payroll_rule_for_shift"]
    _calculate_shift_pay_from_rule = core["_calculate_shift_pay_from_rule"]
    _save_workhour_rule_snapshot = core["_save_workhour_rule_snapshot"]

    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    datetime = core["datetime"]
    timedelta = core["timedelta"]
    WorkHour = core["WorkHour"]
    db = core["db"]
    make_response = core["make_response"]

    work_sheet = core["work_sheet"]
    gspread = core["gspread"]
    _gs_write_with_retry = core["_gs_write_with_retry"]

    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    COL_PAY = core["COL_PAY"]

    log_audit = core["log_audit"]

    gate = require_login()
    if gate:
        return gate

    role = (session.get("role") or "employee").strip().lower()
    if role not in ("site_manager", "admin", "master_admin"):
        return redirect("/")

    require_csrf()

    current_wp = _session_workplace_id()
    actor = session.get("username", "")

    username = (request.form.get("user") or "").strip()
    out_time = (request.form.get("out_time") or "").strip()

    if not username or not out_time:
        return redirect(request.referrer or "/site-manager")

    def rec_sites(rec):
        vals = []
        for key in ("Site", "site", "Site2", "site2"):
            v = str((rec or {}).get(key, "") or "").strip()
            if v:
                vals.append(v.lower())
        return set(vals)

    manager_rec = _find_employee_record(actor, current_wp)
    manager_sites = rec_sites(manager_rec)

    target_rec = _find_employee_record(username, current_wp)
    target_sites = rec_sites(target_rec)

    if role == "site_manager":
        if not manager_sites:
            return make_response("No site assigned to this Site Manager account.", 403)

        if not target_rec:
            return make_response("This employee is not in your workplace.", 403)

        if not target_sites or not (target_sites & manager_sites):
            return make_response("This employee is not assigned to your site.", 403)

    if len(out_time.split(":")) == 2:
        out_time = out_time + ":00"

    rows = get_workhours_rows()
    osf = find_open_shift(rows, username)

    if not osf:
        return redirect(request.referrer or "/site-manager")

    idx, d, cin = osf

    shift_site = ""
    try:
        row = rows[idx]
        headers = rows[0] if rows else []
        in_site_idx = headers.index("InSite") if "InSite" in headers else None
        out_site_idx = headers.index("OutSite") if "OutSite" in headers else None

        if out_site_idx is not None and out_site_idx < len(row):
            shift_site = str(row[out_site_idx] or "").strip()
        if not shift_site and in_site_idx is not None and in_site_idx < len(row):
            shift_site = str(row[in_site_idx] or "").strip()
    except Exception:
        shift_site = ""

    if role == "site_manager" and shift_site and shift_site.lower() not in manager_sites:
        return make_response("You can only force clock-out shifts for your assigned site.", 403)

    shift_date_obj = datetime.strptime(d, "%Y-%m-%d").date()
    rule_snapshot = _get_payroll_rule_for_shift(
        shift_date_obj,
        current_wp,
    )

    computed_hours = _compute_hours_from_times(
        d,
        cin,
        out_time,
        current_wp,
        rule_snapshot,
    )

    if computed_hours is None:
        return redirect(request.referrer or "/site-manager")

    rate = _get_user_rate(username)
    pay = _calculate_shift_pay_from_rule(computed_hours, rate, rule_snapshot)

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(d, "%Y-%m-%d").date()
            clock_out_dt = datetime.strptime(f"{d} {out_time}", "%Y-%m-%d %H:%M:%S")
            clock_in_dt = datetime.strptime(f"{d} {cin}", "%Y-%m-%d %H:%M:%S")

            if clock_out_dt < clock_in_dt:
                clock_out_dt = clock_out_dt + timedelta(days=1)

            db_row = (
                WorkHour.query
                .filter(
                    WorkHour.employee_email == username,
                    WorkHour.date == shift_date,
                    WorkHour.clock_out.is_(None),
                )
                .order_by(WorkHour.id.desc())
                .first()
            )

            if not db_row:
                return redirect(request.referrer or "/site-manager")

            row_wp = str(getattr(db_row, "workplace_id", "") or getattr(db_row, "workplace", "") or "").strip()
            if row_wp and row_wp != current_wp:
                return make_response("This shift is not in your workplace.", 403)

            db_row.clock_out = clock_out_dt
            db_row.hours = computed_hours
            db_row.pay = pay
            db_row.out_site = shift_site or getattr(db_row, "in_site", "") or ""
            db_row.workplace = current_wp
            db_row.workplace_id = current_wp
            _save_workhour_rule_snapshot(db_row, rule_snapshot)

            db.session.commit()

        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not force clock out: {e}", 500)

    else:
        try:
            sheet_row = idx + 1

            updates = [
                {
                    "range": f"{gspread.utils.rowcol_to_a1(sheet_row, COL_OUT + 1)}:{gspread.utils.rowcol_to_a1(sheet_row, COL_PAY + 1)}",
                    "values": [[out_time, computed_hours, pay]],
                }
            ]

            _gs_write_with_retry(lambda: work_sheet.batch_update(updates))

        except Exception as e:
            return make_response(f"Could not force clock out: {e}", 500)

    log_audit(
        "SITE_MANAGER_FORCE_CLOCK_OUT",
        actor=actor,
        username=username,
        date_str=d,
        details=f"out={out_time}, hours={computed_hours}, site={shift_site}",
    )

    return redirect(request.referrer or "/site-manager")



