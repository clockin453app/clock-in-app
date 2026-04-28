def admin_workplaces_impl(core):
    require_master_admin = core["require_master_admin"]
    get_csrf = core["get_csrf"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    session = core["session"]
    settings_sheet = core["settings_sheet"]
    re = core["re"]
    _employees_usernames_for_workplace = core["_employees_usernames_for_workplace"]
    _ensure_employees_columns = core["_ensure_employees_columns"]
    get_sheet_headers = core["get_sheet_headers"]
    employees_sheet = core["employees_sheet"]
    generate_password_hash = core["generate_password_hash"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    WorkplaceSetting = core["WorkplaceSetting"]
    db = core["db"]
    Decimal = core["Decimal"]
    Employee = core["Employee"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    escape = core["escape"]
    page_back_button = core["page_back_button"]
    role_label = core["role_label"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]

    # PASTE ONLY THE BODY OF admin_workplaces() BELOW THIS LINE

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

        allowed_wps = set(_workplace_ids_for_read(current_wp))

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
          {page_back_button("/admin", "Back to Admin")}

          <div class="headerTop">
            <div>
              <h1>Companies</h1>
              <p class="sub">Master admin only.</p>
            </div>
            <div class="badge admin">{escape(role_label(session.get('role', 'master_admin')))}</div>
          </div>


          {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
          {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

          <div class="card" style="padding:12px;">
            <h2>Create company</h2>
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
      <h2>Existing companies</h2>
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
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("workplaces", "master_admin", content))
