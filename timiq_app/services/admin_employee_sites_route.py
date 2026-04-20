def admin_employee_sites_impl(core):
    require_admin = core["require_admin"]
    get_csrf = core["get_csrf"]
    _get_active_locations = core["_get_active_locations"]
    get_employees_compat = core["get_employees_compat"]
    escape = core["escape"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    _get_employee_sites = core["_get_employee_sites"]
    initials = core["initials"]
    admin_back_link = core["admin_back_link"]
    render_template_string = core["render_template_string"]
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

    allowed_wps = set(_workplace_ids_for_read(current_wp))

    for user in employee_rows:
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
        if not assigned:
            chips.append("<span class='chip warn'>No site assigned (clock-in blocked)</span>")
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
                  <div class='sub' style='margin-top:6px;'></div>
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

          {admin_back_link()}

          <div class="card" style="padding:12px;">
            <p class="sub" style="margin-top:0;">
              This updates the <b>Employees → Site</b> column. You can save <b>two sites</b>; they will be stored as <b>Site1,Site2</b>.
              If no site is set for an employee, clock-in is <b>blocked</b> until a site is assigned.
            </p>
            <a href="/admin/locations" style="display:inline-block; margin-top:8px;">
              <button class="btnSoft" type="button">Manage Locations</button>
            </a>
          </div>

          <div class="card" style="padding:12px; margin-top:12px;">
            <h2>Employees</h2>
            <div class="tablewrap" style="margin-top:12px;">
              <table style="min-width:980px;">
                <thead><tr><th>Employee</th><th>Assign site(s)</th><th></th></tr></thead>
                <tbody>{body}</tbody>
              </table>
            </div>
          </div>
        """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )
