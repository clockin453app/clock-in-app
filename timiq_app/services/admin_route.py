from ..ui.render import render_page
def admin_impl(core):
    require_admin = core["require_admin"]
    get_csrf = core["get_csrf"]
    get_company_settings = core["get_company_settings"]
    _get_open_shifts = core["_get_open_shifts"]
    _get_active_locations = core["_get_active_locations"]
    _list_employee_records_for_workplace = core["_list_employee_records_for_workplace"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    OnboardingRecord = core["OnboardingRecord"]
    onboarding_sheet = core["onboarding_sheet"]

    BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS = core["BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS"]
    UNPAID_BREAK_HOURS = core["UNPAID_BREAK_HOURS"]
    get_employees_compat = core["get_employees_compat"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    role_label = core["role_label"]
    session = core["session"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]

    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    get_company_settings()

    open_shifts = _get_open_shifts()

    force_clockout_options = []
    seen_force_clockout = set()

    for s in open_shifts:
        u = str(s.get("user") or "").strip()
        if not u or u in seen_force_clockout:
            continue

        seen_force_clockout.add(u)

        name = str(s.get("name") or u).strip()
        start_label = str(s.get("start_label") or "").strip()
        start_iso = str(s.get("start_iso") or "").strip()

        force_clockout_options.append({
            "username": u,
            "label": f"{name} ({u})",
            "name": name,
            "start_label": start_label,
            "start_iso": start_iso,
        })

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
        allowed_wps = set(_workplace_ids_for_read(current_wp))

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
                        if row_wp not in allowed_wps:
                            continue

                    onboarding_total += 1
    except Exception:
        onboarding_total = 0

    employee_options = []
    try:
        current_wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(current_wp))

        for rec in get_employees_compat():
            u = str(rec.get("Username") or "").strip()
            if not u:
                continue

            row_wp = str(rec.get("Workplace_ID") or "default").strip() or "default"
            if row_wp not in allowed_wps:
                continue

            fn = str(rec.get("FirstName") or "").strip()
            ln = str(rec.get("LastName") or "").strip()
            disp = (fn + " " + ln).strip() or u

            employee_options.append({
                "username": u,
                "label": f"{disp} ({u})",
            })
    except Exception:
        employee_options = []
        force_clockout_options = []
        seen_force_clockout = set()

        for s in open_shifts:
            u = str(s.get("user") or "").strip()
            if not u or u in seen_force_clockout:
                continue

            seen_force_clockout.add(u)

            name = str(s.get("name") or u).strip()
            start_label = str(s.get("start_label") or "").strip()
            start_iso = str(s.get("start_iso") or "").strip()

            force_clockout_options.append({
                "username": u,
                "label": f"{name} ({u})",
                "name": name,
                "start_label": start_label,
                "start_iso": start_iso,
            })

    site_options = []
    try:
        for rec in (_get_active_locations() or []):
            nm = str(rec.get("name") or rec.get("SiteName") or rec.get("site") or "").strip()
            if nm:
                site_options.append(nm)
    except Exception:
        site_options = []

    return render_page(
        template_name="admin/management.html",
        active="admin",
        role=session.get("role", "admin"),
        layout_shell=layout_shell,
        style=STYLE,
        viewport=VIEWPORT,
        pwa_tags=PWA_TAGS,
        page_css="/static/css/pages/admin-management.css?v=100",
        csrf=csrf,
        today_value=datetime.now(TZ).strftime("%Y-%m-%d"),
        now_time_value=datetime.now(TZ).strftime("%H:%M"),
        force_clockout_options=force_clockout_options,
        role_label_text=role_label(session.get("role", "admin")),
        is_master_admin=session.get("role") == "master_admin",
        employees_total=employees_total,
        onboarding_total=onboarding_total,
        locations_total=locations_total,
        open_total=open_total,
        open_shifts=open_shifts,
        employee_options=employee_options,
        site_options=site_options,
        break_applies_hours=BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS,
        unpaid_break_hours=UNPAID_BREAK_HOURS,
    )


