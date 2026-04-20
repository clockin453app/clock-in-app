def admin_impl(core):
    require_admin = core["require_admin"]
    get_csrf = core["get_csrf"]
    get_company_settings = core["get_company_settings"]
    escape = core["escape"]
    _get_open_shifts = core["_get_open_shifts"]
    _get_active_locations = core["_get_active_locations"]
    _list_employee_records_for_workplace = core["_list_employee_records_for_workplace"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    OnboardingRecord = core["OnboardingRecord"]
    onboarding_sheet = core["onboarding_sheet"]
    _get_user_rate = core["_get_user_rate"]
    _svg_user = core["_svg_user"]
    BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS = core["BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS"]
    UNPAID_BREAK_HOURS = core["UNPAID_BREAK_HOURS"]
    get_employees_compat = core["get_employees_compat"]
    _icon_payroll_report = core["_icon_payroll_report"]
    _icon_company_settings = core["_icon_company_settings"]
    _icon_onboarding = core["_icon_onboarding"]
    _icon_locations = core["_icon_locations"]
    _icon_employee_sites = core["_icon_employee_sites"]
    _icon_employees = core["_icon_employees"]
    _icon_connect_drive = core["_icon_connect_drive"]
    _svg_clock = core["_svg_clock"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    role_label = core["role_label"]
    session = core["session"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    render_template_string = core["render_template_string"]
    _icon_clock_selfies = core["_icon_clock_selfies"]

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
                    <div class="adminSectionCard plainSection" style="margin-top:12px;">
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
          <div class="adminSectionCard plainSection" style="margin-top:12px;">
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

            employee_options += f"<option value='{escape(u)}'>{escape(disp)} ({escape(u)})</option>"
    except Exception:
        employee_options = ""

    content = f"""
      <style>
        .adminHeroCard,
        .adminSectionCard,
        .adminForceCard{{
          border:1px solid rgba(15,23,42,.08);
          background:linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
          box-shadow:0 18px 40px rgba(15,23,42,.08), inset 0 1px 0 rgba(255,255,255,.78);
        }}
        .adminHeroCard{{padding:18px; border-radius: 0 !important; margin-bottom:12px;}}
        .adminHeroTop{{display:flex; justify-content:space-between; gap:16px; align-items:flex-start; flex-wrap:wrap;}}
        .adminHeroEyebrow{{display:inline-flex; align-items:center; gap:8px; padding:7px 12px; border-radius: 0 !important; font-size:12px; font-weight:800; letter-spacing:.05em; text-transform:uppercase; color:#1d4ed8; background:rgba(59,130,246,.10); border:1px solid rgba(96,165,250,.18); margin-bottom:10px;}}
        .adminHeroCard h1{{color:var(--text); margin:0;}}
        .adminHeroCard .sub{{color:var(--muted);}}
        .adminForceCard{{margin-top:12px; padding:16px; border-radius: 0 !important;}}
        .adminActionBar{{background:rgba(248,250,252,.96); border:1px solid rgba(15,23,42,.08);}}
        .adminActionBar .input{{background:rgba(255,255,255,.96); border:1px solid rgba(15,23,42,.10); color:var(--text); box-shadow:none;}}
        .adminActionBar .input:focus{{border-color:rgba(96,165,250,.34); box-shadow:0 0 0 3px rgba(37,99,235,.10);}}
        .adminPrimaryBtn{{box-shadow:0 14px 28px rgba(37,99,235,.20);}}
      </style>

      {admin_back_link("/")} 


      <div class="adminHeroCard plainSection">
        <div class="adminHeroTop">
          <div>
            <h1>Admin</h1>
            <p class="sub">Payroll, onboarding, employees and workplace controls.</p>
          </div>
          <div class="badge admin">{escape(role_label(session.get('role', 'admin')))}</div>
        </div>
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

            <div class="card menu adminToolsShell" style="padding:14px;">
             <div class="adminGrid">

          <a class="adminToolCard payroll" href="/admin/payroll">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_payroll_report(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Payroll Report</div>
            <div class="adminToolSub">Weekly payroll, tax, net pay and paid status.</div>
          </a>

          <a class="adminToolCard company" href="/admin/company">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_company_settings(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Company Settings</div>
            <div class="adminToolSub">Change workplace name and company-level settings.</div>
          </a>

          <a class="adminToolCard onboarding" href="/admin/onboarding">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_onboarding(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Onboarding</div>
            <div class="adminToolSub">Review starter forms, documents and contract details.</div>
          </a>

          <a class="adminToolCard locations" href="/admin/locations">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_locations(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Locations</div>
            <div class="adminToolSub">Manage geo-fence sites and allowed clock-in zones.</div>
          </a>

          <a class="adminToolCard sites" href="/admin/employee-sites">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_employee_sites(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Employee Sites</div>
            <div class="adminToolSub">Assign employees to site locations for clock-in access.</div>
          </a>
          
          <a class="adminToolCard selfies" href="/admin/clock-selfies">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_clock_selfies(45)}</div>
              <div class="chev">›</div>
             </div>
            <div class="adminToolTitle">Clock Selfies</div>
            <div class="adminToolSub">View employee clock-in and clock-out photos for this workplace.</div>
          </a>

          <a class="adminToolCard employees" href="/admin/employees">
            <div class="adminToolTop">
              <div class="adminToolIcon">{_icon_employees(45)}</div>
              <div class="chev">›</div>
            </div>
            <div class="adminToolTitle">Employees</div>
            <div class="adminToolSub">Create employees, update rates and manage access.</div>
          </a>

                    {
    f'''
              <a class="adminToolCard drive" href="/connect-drive">
                <div class="adminToolTop">
                <div class="adminToolIcon">{_icon_connect_drive(45)}</div>
                <div class="chev">›</div>
                </div>
                <div class="adminToolTitle">Connect Drive</div>
                <div class="adminToolSub">Reconnect Google Drive for onboarding uploads.</div>
              </a>
            '''
    if session.get("role") == "master_admin"
    else ""
    }
        </div>
      </div>
            <div class="card adminForceCard">
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
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell(
            active="admin",
            role=session.get("role", "admin"),
            content_html=content
        )
    )


def admin_back_link(href: str = "/admin") -> str:
    return f"""
      <div style="margin:8px 0 14px;">
        <a href="{href}"
           aria-label="Back"
           title="Back"
           style="
             display:inline-block;
             color:#000;
             text-decoration:none;
             font-size:14px;
             font-weight:400;
             line-height:1.2;
             background:none;
             border:0;
             padding:0;
             box-shadow:none;
           ">
          Back
        </a>
      </div>
    """

