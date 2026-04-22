def admin_recalculate_shifts_impl(core):
    require_admin = core["require_admin"]
    require_csrf = core["require_csrf"]
    get_csrf = core["get_csrf"]
    request = core["request"]
    session = core["session"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    admin_back_link = core["admin_back_link"]
    escape = core["escape"]
    datetime = core["datetime"]
    timedelta = core["timedelta"]
    WorkHour = core["WorkHour"]
    PayrollReport = core["PayrollReport"]
    db = core["db"]
    _session_workplace_id = core["_session_workplace_id"]
    _list_employee_records_for_workplace = core["_list_employee_records_for_workplace"]
    _get_user_rate = core["_get_user_rate"]
    _get_payroll_rule_for_shift = core["_get_payroll_rule_for_shift"]
    _compute_hours_from_times = core["_compute_hours_from_times"]
    _calculate_shift_pay_from_rule = core["_calculate_shift_pay_from_rule"]
    _save_workhour_rule_snapshot = core["_save_workhour_rule_snapshot"]
    log_audit = core["log_audit"]

    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    wp = _session_workplace_id()
    msg = ""
    ok = False

    employees = _list_employee_records_for_workplace(wp, include_inactive=True) or []
    employee_options = ['<option value="">All employees</option>']
    for rec in employees:
        uname = str(
            rec.get("Username")
            or rec.get("username")
            or rec.get("Email")
            or rec.get("email")
            or ""
        ).strip()
        label = str(rec.get("Name") or rec.get("name") or uname).strip() or uname
        if uname:
            employee_options.append(
                f'<option value="{escape(uname)}">{escape(label)}</option>'
            )

    username = (request.values.get("username") or "").strip()
    date_from = (request.values.get("date_from") or "").strip()
    date_to = (request.values.get("date_to") or "").strip()
    include_paid = (request.values.get("include_paid") or "").strip() == "yes"

    preview_rows = []

    def is_paid_week(row):
        week_start = row.date - timedelta(days=row.date.weekday())
        week_end = week_start + timedelta(days=6)
        rec = PayrollReport.query.filter_by(
            username=row.employee_email,
            workplace_id=wp,
            week_start=week_start,
            week_end=week_end,
        ).first()
        return bool(
            rec and str(getattr(rec, "paid", "") or "").strip().lower()
            in ("true", "1", "yes", "paid")
        )

    if date_from and date_to:
        try:
            start_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            end_date = datetime.strptime(date_to, "%Y-%m-%d").date()

            q = WorkHour.query.filter(
                WorkHour.workplace_id == wp,
                WorkHour.date >= start_date,
                WorkHour.date <= end_date,
            ).order_by(WorkHour.date.asc(), WorkHour.employee_email.asc(), WorkHour.id.asc())

            if username:
                q = q.filter(WorkHour.employee_email == username)

            rows = q.all()

            for row in rows:
                if not row.clock_in or not row.clock_out:
                    continue
                if (not include_paid) and is_paid_week(row):
                    continue

                cin = row.clock_in.strftime("%H:%M:%S")
                cout = row.clock_out.strftime("%H:%M:%S")
                rule_snapshot = _get_payroll_rule_for_shift(row.date, wp)
                new_hours = _compute_hours_from_times(
                    row.date.isoformat(),
                    cin,
                    cout,
                    wp,
                    rule_snapshot,
                )
                rate = _get_user_rate(row.employee_email)
                new_pay = _calculate_shift_pay_from_rule(new_hours or 0.0, rate, rule_snapshot)

                old_hours = float(row.hours or 0.0)
                old_pay = float(row.pay or 0.0)

                changed = (
                    round(old_hours, 2) != round(float(new_hours or 0.0), 2)
                    or round(old_pay, 2) != round(float(new_pay or 0.0), 2)
                )

                preview_rows.append({
                    "id": row.id,
                    "username": row.employee_email,
                    "date": row.date.isoformat(),
                    "old_hours": old_hours,
                    "new_hours": round(float(new_hours or 0.0), 2),
                    "old_pay": old_pay,
                    "new_pay": round(float(new_pay or 0.0), 2),
                    "changed": changed,
                })
        except Exception as e:
            msg = f"Preview failed: {e}"

    if request.method == "POST" and request.form.get("action") == "apply":
        require_csrf()
        selected_ids = [x.strip() for x in request.form.getlist("selected_ids") if x.strip()]
        if not selected_ids:
            msg = "Select at least one shift."
        else:
            try:
                rows = WorkHour.query.filter(
                    WorkHour.workplace_id == wp,
                    WorkHour.id.in_([int(x) for x in selected_ids]),
                ).all()

                updated = 0
                for row in rows:
                    if not row.clock_in or not row.clock_out:
                        continue

                    cin = row.clock_in.strftime("%H:%M:%S")
                    cout = row.clock_out.strftime("%H:%M:%S")
                    rule_snapshot = _get_payroll_rule_for_shift(row.date, wp)
                    new_hours = _compute_hours_from_times(
                        row.date.isoformat(),
                        cin,
                        cout,
                        wp,
                        rule_snapshot,
                    )
                    rate = _get_user_rate(row.employee_email)
                    new_pay = _calculate_shift_pay_from_rule(new_hours or 0.0, rate, rule_snapshot)

                    row.hours = round(float(new_hours or 0.0), 2)
                    row.pay = round(float(new_pay or 0.0), 2)
                    _save_workhour_rule_snapshot(row, rule_snapshot)
                    updated += 1

                db.session.commit()
                log_audit(
                    "RECALCULATE_SHIFTS",
                    actor=session.get("username", "admin"),
                    details=f"workplace={wp} rows={updated} from={date_from} to={date_to} user={username or 'all'}",
                )
                ok = True
                msg = f"Recalculated {updated} shift(s)."
            except Exception as e:
                db.session.rollback()
                msg = f"Apply failed: {e}"

    rows_html = ""
    if preview_rows:
        body = []
        for row in preview_rows:
            if not row["changed"]:
                continue
            body.append(f"""
                <tr>
                  <td><input type="checkbox" name="selected_ids" value="{row["id"]}" checked></td>
                  <td>{escape(row["username"])}</td>
                  <td>{escape(row["date"])}</td>
                  <td>{row["old_hours"]:.2f}</td>
                  <td>{row["new_hours"]:.2f}</td>
                  <td>{row["old_pay"]:.2f}</td>
                  <td>{row["new_pay"]:.2f}</td>
                </tr>
            """)
        rows_html = "".join(body) if body else "<tr><td colspan='7'>No changed shifts found.</td></tr>"

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Recalculate Shifts</h1>
          <p class="sub">Preview and apply workplace payroll rules to existing shifts for <b>{escape(wp)}</b>.</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {admin_back_link("/admin")}

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

      <div class="card" style="padding:12px;">
        <form method="GET" class="row2">
          <div>
            <label class="sub">Employee</label>
            <select class="input" name="username">
              {''.join(employee_options)}
            </select>
          </div>
          <div>
            <label class="sub">Date from</label>
            <input class="input" type="date" name="date_from" value="{escape(date_from)}" required>
          </div>
          <div>
            <label class="sub">Date to</label>
            <input class="input" type="date" name="date_to" value="{escape(date_to)}" required>
          </div>
          <div>
            <label class="sub">Include paid weeks</label>
            <select class="input" name="include_paid">
              <option value="no" {"selected" if not include_paid else ""}>No</option>
              <option value="yes" {"selected" if include_paid else ""}>Yes</option>
            </select>
          </div>
          <div style="grid-column:1/-1;">
            <button class="btnSoft" type="submit">Preview recalculation</button>
          </div>
        </form>
      </div>

      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>Preview</h2>
        <form method="POST" style="margin-top:12px;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <input type="hidden" name="action" value="apply">

          <div class="tablewrap">
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>Employee</th>
                  <th>Date</th>
                  <th>Old hours</th>
                  <th>New hours</th>
                  <th>Old pay</th>
                  <th>New pay</th>
                </tr>
              </thead>
              <tbody>
                {rows_html}
              </tbody>
            </table>
          </div>

          <button class="btnSoft" type="submit" style="margin-top:12px;">Apply selected recalculations</button>
        </form>
      </div>
    """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", session.get("role", "admin"), content)
    )