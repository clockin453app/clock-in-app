from timiq_app.ui.render import render_page
def admin_employees_impl(core):
    require_admin = core["require_admin"]
    get_csrf = core["get_csrf"]
    request = core["request"]
    session = core["session"]
    require_csrf = core["require_csrf"]
    _sanitize_requested_role = core["_sanitize_requested_role"]
    _ensure_employees_columns = core["_ensure_employees_columns"]
    get_sheet_headers = core["get_sheet_headers"]
    employees_sheet = core["employees_sheet"]
    find_row_by_username = core["find_row_by_username"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    _employee_query_for_write = core["_employee_query_for_write"]
    _session_workplace_id = core["_session_workplace_id"]
    Decimal = core["Decimal"]
    db = core["db"]
    log_audit = core["log_audit"]
    gspread = core["gspread"]
    _normalize_password_hash_value = core["_normalize_password_hash_value"]
    Employee = core["Employee"]
    update_employee_password = core["update_employee_password"]
    make_response = core["make_response"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    _generate_unique_username = core["_generate_unique_username"]
    _generate_temp_password = core["_generate_temp_password"]
    generate_password_hash = core["generate_password_hash"]
    _list_employee_records_for_workplace = core["_list_employee_records_for_workplace"]
    get_employees_compat = core["get_employees_compat"]
    _allowed_assignable_roles_for_actor = core["_allowed_assignable_roles_for_actor"]
    escape = core["escape"]
    admin_back_link = core["admin_back_link"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]

    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    msg = ""
    ok = False
    created = None
    def _parse_optional_tax_percent(raw_value: str):
        raw_value = (raw_value or "").strip()
        if raw_value == "":
            return None, ""

        try:
            value = float(raw_value)
        except Exception:
            return None, "Tax % must be a number."

        if value < 0 or value > 100:
            return None, "Tax % must be between 0 and 100."

        return str(value), ""

    if request.method == "POST":
        require_csrf()
        action = (request.form.get("action") or "create").strip().lower()

        if action == "update":
            edit_username = (request.form.get("edit_username") or "").strip()
            raw_edit_role = (request.form.get("edit_role") or "").strip()
            edit_role = raw_edit_role
            edit_rate_raw = (request.form.get("edit_rate") or "").strip()
            edit_tax_rate_raw = (request.form.get("edit_tax_rate") or "").strip()
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

                rownum = find_row_by_username(employees_sheet, edit_username)
                if not rownum and DB_MIGRATION_MODE:
                    new_rate_str = None
                    if edit_rate_raw != "":
                        try:
                            new_rate_str = str(float(edit_rate_raw))
                        except Exception:
                            ok = False
                            msg = "Hourly rate must be a number."
                    new_tax_rate_str = None
                    if not msg:
                        new_tax_rate_str, tax_msg = _parse_optional_tax_percent(edit_tax_rate_raw)
                        if tax_msg:
                            ok = False
                            msg = tax_msg

                    changed = []
                    if not msg:
                        try:
                            db_row = _employee_query_for_write(edit_username, _session_workplace_id()).first()
                            if not db_row:
                                ok = False
                                msg = "Employee not found in this workplace."
                            else:
                                if edit_role != "" and hasattr(db_row, "role"):
                                    db_row.role = edit_role
                                    changed.append(f"role={edit_role}")

                                if new_rate_str is not None and hasattr(db_row, "rate"):
                                    db_row.rate = Decimal(new_rate_str)
                                    changed.append(f"rate={new_rate_str}")
                                if new_tax_rate_str is not None and hasattr(db_row, "tax_rate"):
                                    db_row.tax_rate = Decimal(new_tax_rate_str)
                                    changed.append(f"tax_rate={new_tax_rate_str}")

                                if edit_early_access in ("TRUE", "FALSE") and hasattr(db_row, "early_access"):
                                    db_row.early_access = edit_early_access
                                    changed.append(f"early_access={edit_early_access}")

                                if not changed:
                                    ok = False
                                    msg = "Nothing to update (enter a new role, rate, and/or early access change)."
                                else:
                                    db.session.commit()
                                    actor = session.get("username", "admin")
                                    log_audit(
                                        "EMPLOYEE_UPDATE",
                                        actor=actor,
                                        username=edit_username,
                                        date_str="",
                                        details=" ".join(changed),
                                    )
                                    ok = True
                                    msg = "Employee updated."
                        except Exception:
                            db.session.rollback()
                            ok = False
                            msg = "Could not update employee."
                elif not rownum:
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
                    new_tax_rate_str = None
                    if not msg:
                        new_tax_rate_str, tax_msg = _parse_optional_tax_percent(edit_tax_rate_raw)
                        if tax_msg:
                            ok = False
                            msg = tax_msg

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
                        if new_tax_rate_str is not None and "TaxRate" in headers:
                            row[headers.index("TaxRate")] = new_tax_rate_str
                            changed.append(f"tax_rate={new_tax_rate_str}")

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
                                log_audit(
                                    "EMPLOYEE_UPDATE",
                                    actor=actor,
                                    username=edit_username,
                                    date_str="",
                                    details=" ".join(changed),
                                )

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
                                        workplace_id_db = (
                                            _row_str("Workplace_ID", _session_workplace_id()) or _session_workplace_id()
                                        )
                                        site_db = _row_str("Site")

                                        rate_db = None
                                        rate_raw_db = _row_str("Rate")
                                        if rate_raw_db != "":
                                            try:
                                                rate_db = Decimal(rate_raw_db)
                                            except Exception:
                                                rate_db = None
                                        tax_rate_db = None
                                        tax_rate_raw_db = _row_str("TaxRate")
                                        if tax_rate_raw_db != "":
                                            try:
                                                tax_rate_db = Decimal(tax_rate_raw_db)
                                            except Exception:
                                                tax_rate_db = None

                                        db_row = _employee_query_for_write(username_db, workplace_id_db).first()

                                        if db_row:
                                            db_row.email = username_db
                                            db_row.name = full_name_db or username_db
                                            db_row.role = role_db
                                            db_row.username = username_db
                                            db_row.first_name = first_name_db
                                            db_row.last_name = last_name_db
                                            db_row.password = password_db or db_row.password
                                            db_row.rate = rate_db
                                            db_row.tax_rate = tax_rate_db
                                            db_row.early_access = early_access_db
                                            db_row.active = active_db
                                            if hasattr(db_row, "site"):
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
                                                    tax_rate=tax_rate_db,
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

                if headers and "Active" not in headers:
                    headers2 = headers + ["Active"]
                    end_col_h = gspread.utils.rowcol_to_a1(1, len(headers2)).replace("1", "")
                    employees_sheet.update(f"A1:{end_col_h}1", [headers2])
                    headers = headers2

                rownum = find_row_by_username(employees_sheet, edit_username)
                if not rownum and DB_MIGRATION_MODE:
                    val = "FALSE" if action == "deactivate" else "TRUE"
                    try:
                        db_row = _employee_query_for_write(edit_username, _session_workplace_id()).first()
                        if not db_row:
                            ok = False
                            msg = "Employee not found in this workplace."
                        else:
                            db_row.active = val
                            if action == "deactivate" and hasattr(db_row, "active_session_token"):
                                db_row.active_session_token = None
                            db.session.commit()
                            actor = session.get("username", "admin")
                            if action == "deactivate":
                                log_audit(
                                    "EMPLOYEE_DEACTIVATE",
                                    actor=actor,
                                    username=edit_username,
                                    date_str="",
                                    details="active=FALSE",
                                )
                                msg = "Employee deactivated."
                            else:
                                log_audit(
                                    "EMPLOYEE_REACTIVATE",
                                    actor=actor,
                                    username=edit_username,
                                    date_str="",
                                    details="active=TRUE",
                                )
                                msg = "Employee reactivated."
                            ok = True
                    except Exception:
                        db.session.rollback()
                        ok = False
                        msg = "Could not update employee."
                elif not rownum:
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
                            log_audit(
                                "EMPLOYEE_DEACTIVATE",
                                actor=actor,
                                username=edit_username,
                                date_str="",
                                details="active=FALSE",
                            )
                            msg = "Employee deactivated."
                        else:
                            log_audit(
                                "EMPLOYEE_REACTIVATE",
                                actor=actor,
                                username=edit_username,
                                date_str="",
                                details="active=TRUE",
                            )
                            msg = "Employee reactivated."

                        if DB_MIGRATION_MODE:
                            try:
                                db_row = _employee_query_for_write(edit_username, _session_workplace_id()).first()
                                if db_row:
                                    db_row.active = val
                                    if action == "deactivate" and hasattr(db_row, "active_session_token"):
                                        db_row.active_session_token = None
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
            tax_rate_raw = (request.form.get("tax_rate") or "").strip()

            if not role_new:
                return make_response("You are not allowed to create a user with that role.", 403)

            try:
                rate_val = float(rate_raw) if rate_raw != "" else 0.0
            except Exception:
                rate_val = 0.0
            tax_rate_str, tax_msg = _parse_optional_tax_percent(tax_rate_raw)
            if tax_msg:
                return make_response(tax_msg, 400)

            tax_rate_db = Decimal(tax_rate_str) if tax_rate_str is not None else None

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
            set_col("TaxRate", tax_rate_str or "")
            set_col("EarlyAccess", "TRUE")
            set_col("OnboardingCompleted", "")
            set_col("FirstName", first)
            set_col("LastName", last)
            set_col("Workplace_ID", wp)

            try:
                employees_sheet.append_row(row)
                actor = session.get("username", "admin")
                log_audit(
                    "EMPLOYEE_CREATE",
                    actor=actor,
                    username=new_username,
                    date_str="",
                    details=f"role={role_new} rate={rate_val}",
                )

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
                            db_row.tax_rate = tax_rate_db
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
                                    tax_rate=tax_rate_db,
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

    wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(wp))
    rows_html = []
    try:
        table_records = _list_employee_records_for_workplace(wp, include_inactive=True)

        for rec in table_records:
            u = (rec.get("Username") or "").strip()
            if not u:
                continue

            fn = (rec.get("FirstName") or "").strip()
            ln = (rec.get("LastName") or "").strip()
            rr = (rec.get("Role") or "").strip()
            rate = str(rec.get("Rate") or "").strip()
            tax_rate = str(rec.get("TaxRate") or "").strip()
            early = str(rec.get("EarlyAccess") or "").strip()
            active = str(rec.get("Active") or "TRUE").strip().lower()

            early_label = "Yes" if early in ("true", "1", "yes") else "No"
            inactive_tag = " (inactive)" if active in ("false", "0", "no", "n", "off") else ""
            disp = ((fn + " " + ln).strip() or u) + inactive_tag

            rows_html.append(
                f"<tr><td>{escape(disp)}</td><td>{escape(u)}</td><td>{escape(rr)}</td><td>{escape(early_label)}</td><td class='num'>{escape(rate)}</td><td class='num'>{escape(tax_rate)}</td></tr>"
            )
    except Exception:
        rows_html = []

    actor_role_page = (session.get("role") or "employee").strip().lower()
    role_suggestions = set(_allowed_assignable_roles_for_actor(actor_role_page))

    try:
        for rec in get_employees_compat():
            row_wp = (rec.get("Workplace_ID") or "default").strip() or "default"
            if row_wp not in allowed_wps:
                continue

            rr = (rec.get("Role") or "").strip()
            if not rr:
                continue

            if rr.lower() == "master_admin":
                continue

            if rr.lower() == "admin" and actor_role_page != "master_admin":
                continue

            role_suggestions.add(rr)
    except Exception:
        pass

    role_suggestions = sorted(role_suggestions, key=lambda x: x.lower())

    role_options_html = "".join(
        f"<option value='{escape(r)}'></option>"
        for r in role_suggestions
    )

    role_select_options_html = "".join(
        f"<option value='{escape(r)}' {'selected' if r == 'employee' else ''}>{escape(r)}</option>"
        for r in role_suggestions
    )
    update_role_options_html = "".join(
        f"<option value='{escape(r)}'>{escape(r)}</option>"
        for r in role_suggestions
    )
    table = "".join(rows_html) if rows_html else "<tr><td colspan='6'>No employees found.</td></tr>"

    created_card = ""
    if created:
        created_card = f"""
        <div class="card" style="padding:12px; margin-top:12px;">
          <h2>Employee created</h2>
          <p class="sub">Give these login details to the employee (they can change password in Profile).</p>
          <div class="card" style="padding:12px; background:rgba(56,189,248,.18); border:1px solid rgba(56,189,248,.35); color:rgba(2,6,23,.95);">
            <div><b>Username:</b> {escape(created["u"])}</div>
            <div><b>Workplace ID:</b> {escape(created["wp"])}</div>
            <div><b>Temp password:</b> {escape(created["p"])}</div>
          </div>
        </div>
        """

    employee_options_html = "<option value='' selected disabled>Select employee</option>"
    delete_employee_options_html = "<option value='' selected disabled>Select employee</option>"
    try:
        wp_now = _session_workplace_id()
        allowed_wps_for_dropdown = set(_workplace_ids_for_read(wp_now))
        records = _list_employee_records_for_workplace(wp_now, include_inactive=True)
        seen_usernames = set()

        def _record_sort_key(rec):
            rec_wp = str(rec.get("Workplace_ID") or "default").strip() or "default"
            return (0 if rec_wp == wp_now else 1, str(rec.get("Username") or "").strip().lower())

        for rec in sorted(records, key=_record_sort_key):
            u = str(rec.get("Username") or "").strip()
            if not u or u in seen_usernames:
                continue

            r_wp = str(rec.get("Workplace_ID") or "default").strip() or "default"
            if r_wp not in allowed_wps_for_dropdown:
                continue

            a = str(rec.get("Active") or "TRUE").strip().lower()
            inactive_tag = " (inactive)" if a in ("false", "0", "no", "n", "off") else ""

            fn = str(rec.get("FirstName") or "").strip()
            ln = str(rec.get("LastName") or "").strip()
            disp = (fn + " " + ln).strip() or u

            role_raw = str(rec.get("Role") or "").strip().lower()
            label = f"{disp}{inactive_tag} ({u})"

            employee_options_html += f"<option value='{escape(u)}'>{escape(label)}</option>"
            seen_usernames.add(u)

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

    employees_total = len(rows_html)
    is_master_admin = session.get("role") == "master_admin"

    return render_page(
        template_name="admin/employees.html",
        active="admin",
        role=session.get("role", "admin"),
        layout_shell=layout_shell,
        style=STYLE,
        viewport=VIEWPORT,
        pwa_tags=PWA_TAGS,
        csrf=csrf,
        wp=wp,
        msg=msg,
        ok=ok,
        created=created,
        reset_ok=reset_ok,
        reset_user=reset_user,
        employee_options_html=employee_options_html,
        delete_employee_options_html=delete_employee_options_html,
        role_select_options_html=role_select_options_html,
        update_role_options_html=update_role_options_html,
        table_rows=table,
        employees_total=employees_total,
        role_count=len(role_suggestions),
        is_master_admin=is_master_admin,
    )