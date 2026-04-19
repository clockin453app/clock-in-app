
def admin_company_impl(core):
    require_admin = core["require_admin"]
    get_csrf = core["get_csrf"]
    session = core["session"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    get_company_settings = core["get_company_settings"]
    request = core["request"]
    require_csrf = core["require_csrf"]
    settings_sheet = core["settings_sheet"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    WorkplaceSetting = core["WorkplaceSetting"]
    db = core["db"]
    log_audit = core["log_audit"]
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
    role = session.get("role", "admin")
    wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(wp))

    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    role = session.get("role", "admin")
    wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(wp))

    settings = get_company_settings()
    current_name = (settings.get("Company_Name") or "").strip() or "Main"
    current_logo = (settings.get("Company_Logo_URL") or "").strip()

    msg = ""
    ok = False

    if request.method == "POST":
        require_csrf()
        new_name = (request.form.get("company_name") or "").strip()
        new_logo = (request.form.get("company_logo_url") or "").strip()

        if not new_name:
            msg = "Company name required."
        elif not settings_sheet:
            msg = "Settings sheet not configured."
        else:
            vals = settings_sheet.get_all_values()
            if not vals:
                settings_sheet.append_row(
                    ["Workplace_ID", "Tax_Rate", "Currency_Symbol", "Company_Name", "Company_Logo_URL"])
                vals = settings_sheet.get_all_values()

            hdr = vals[0] if vals else []
            if "Company_Logo_URL" not in hdr:
                settings_sheet.update_cell(1, len(hdr) + 1, "Company_Logo_URL")
                vals = settings_sheet.get_all_values()
                hdr = vals[0] if vals else []

            def idx(n):
                return hdr.index(n) if n in hdr else None

            i_wp = idx("Workplace_ID")
            i_name = idx("Company_Name")
            i_logo = idx("Company_Logo_URL")
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
                    if i_logo is not None:
                        settings_sheet.update_cell(rownum, i_logo + 1, new_logo)
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
                                    db_row.company_logo_url = new_logo
                                    db_row.tax_rate = tax_value
                                    db_row.currency_symbol = currency_value
                                    db.session.commit()
                            except Exception:
                                db.session.rollback()
                else:
                    row = [""] * len(hdr)
                    row[i_wp] = wp
                    row[i_name] = new_name
                    if i_logo is not None:
                        row[i_logo] = new_logo
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
                                db_row.company_logo_url = new_logo
                                db_row.tax_rate = tax_value
                                db_row.currency_symbol = currency_value
                            else:
                                db.session.add(
                                    WorkplaceSetting(
                                        workplace_id=wp,
                                        tax_rate=tax_value,
                                        currency_symbol=currency_value,
                                        company_name=new_name,
                                        company_logo_url=new_logo,
                                    )
                                )

                            db.session.commit()
                        except Exception:
                            db.session.rollback()

                log_audit("SET_COMPANY_NAME", actor=session.get("username", "admin"), details=f"{wp} -> {new_name}")
                ok = True
                msg = "Saved."
                current_name = new_name
                current_logo = new_logo

    content = f"""
          <div class="headerTop">
            <div>
              <h1>Company Settings</h1>
              <p class="sub">Workplace: <b>{escape(wp)}</b></p>
            </div>
            <div class="badge admin">ADMIN</div>
          </div>

          {admin_back_link()}

          {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
          {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

          <div class="payrollEmployeeCard plainSection" style="padding:12px; margin-top:12px;">
            <form method="POST">
              <input type="hidden" name="csrf" value="{escape(csrf)}">
              <label class="sub">Company name</label>
              <input class="input" name="company_name" value="{escape(current_name)}" required>

              <label class="sub" style="margin-top:10px;">Company logo URL</label>
              <input class="input" name="company_logo_url" value="{escape(current_logo)}" placeholder="https://.../logo.png">

              <button class="btnSoft" type="submit" style="margin-top:12px;">Save</button>
            </form>
          </div>
        """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )
