from ..ui.render import render_page
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
    role_label = core["role_label"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]

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

                                    db_admin = Employee.query.filter_by(
                                        username=admin_username,
                                        workplace_id=workplace_id
                                    ).first()

                                    if not db_admin:
                                        db_admin = Employee.query.filter_by(
                                            email=admin_username,
                                            workplace_id=workplace_id
                                        ).first()

                                    admin_hash = generate_password_hash(admin_password)
                                    admin_name = (" ".join([admin_first, admin_last])).strip() or admin_username

                                    if db_admin:
                                        db_admin.email = admin_username
                                        db_admin.username = admin_username
                                        db_admin.first_name = admin_first
                                        db_admin.last_name = admin_last
                                        db_admin.name = admin_name
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
                                                name=admin_name,
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

    companies = []
    current_wp = _session_workplace_id()
    current_currency = "—"

    try:
        vals = settings_sheet.get_all_values() if settings_sheet else []
        headers = vals[0] if vals else []

        def idx(name):
            return headers.index(name) if headers and name in headers else None

        i_wp = idx("Workplace_ID")
        i_tax = idx("Tax_Rate")
        i_cur = idx("Currency_Symbol")
        i_name = idx("Company_Name")

        _workplace_ids_for_read(current_wp)

        for r in (vals[1:] if len(vals) > 1 else []):
            wp = (r[i_wp] if i_wp is not None and i_wp < len(r) else "").strip()
            if not wp:
                continue

            tax = (r[i_tax] if i_tax is not None and i_tax < len(r) else "").strip()
            cur = (r[i_cur] if i_cur is not None and i_cur < len(r) else "").strip()
            name = (r[i_name] if i_name is not None and i_name < len(r) else "").strip() or wp

            is_current = wp == current_wp
            if is_current:
                current_currency = cur or "—"

            companies.append({
                "workplace_id": wp,
                "name": name,
                "tax": tax or "—",
                "currency": cur or "—",
                "is_current": is_current,
            })

    except Exception:
        companies = []

    return render_page(
        template_name="admin/companies.html",
        active="workplaces",
        role="master_admin",
        layout_shell=layout_shell,
        style=STYLE,
        viewport=VIEWPORT,
        pwa_tags=PWA_TAGS,
        csrf=csrf,
        msg=msg,
        ok=ok,
        created_info=created_info,
        role_label_text=role_label(session.get("role", "master_admin")),
        current_workplace=current_wp,
        current_currency=current_currency,
        companies=companies,
    )