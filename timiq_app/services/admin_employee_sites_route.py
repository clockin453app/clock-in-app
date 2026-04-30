from ..ui.render import render_page
def admin_employee_sites_impl(core):
    require_admin = core["require_admin"]
    get_csrf = core["get_csrf"]
    _get_active_locations = core["_get_active_locations"]
    get_employees_compat = core["get_employees_compat"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    _get_employee_sites = core["_get_employee_sites"]
    initials = core["initials"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    session = core["session"]

    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    sites = _get_active_locations()
    site_names = [s["name"] for s in sites] if sites else []

    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    employees = []
    assigned_total = 0

    for user in get_employees_compat():
        u = (user.get("Username") or "").strip()
        if not u:
            continue

        row_wp = (user.get("Workplace_ID") or "default").strip() or "default"
        if row_wp not in allowed_wps:
            continue

        fn = (user.get("FirstName") or "").strip()
        ln = (user.get("LastName") or "").strip()
        raw_site1 = (user.get("Site") or "").strip()
        raw_site2 = (user.get("Site2") or "").strip()
        raw_site = ", ".join([s for s in [raw_site1, raw_site2] if s])
        disp = (fn + " " + ln).strip() or u

        assigned = _get_employee_sites(u)
        s1 = assigned[0] if len(assigned) > 0 else ""
        s2 = assigned[1] if len(assigned) > 1 else ""

        chips = []
        if assigned:
            assigned_total += 1
            for s in assigned[:2]:
                if s and s in site_names:
                    chips.append({"label": s, "kind": "ok"})
                elif s:
                    chips.append({"label": f"{s}?", "kind": "bad"})

        employees.append({
            "username": u,
            "display_name": disp,
            "initials": initials(disp),
            "raw_site": raw_site,
            "assigned": bool(assigned),
            "site1": s1,
            "site2": s2,
            "chips": chips,
        })

    employees_total = len(employees)
    unassigned_total = max(0, employees_total - assigned_total)

    return render_page(
        template_name="admin/site_access.html",
        active="admin",
        role=session.get("role", "admin"),
        layout_shell=layout_shell,
        style=STYLE,
        viewport=VIEWPORT,
        pwa_tags=PWA_TAGS,
        csrf=csrf,
        employees=employees,
        site_names=site_names,
        employees_total=employees_total,
        assigned_total=assigned_total,
        unassigned_total=unassigned_total,
        sites_total=len(site_names),
    )