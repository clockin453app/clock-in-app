def admin_log_activities_impl(core):
    require_admin = core["require_admin"]
    session = core["session"]
    request = core["request"]
    get_company_settings = core["get_company_settings"]
    get_workhours_rows = core["get_workhours_rows"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    WorkHour = core["WorkHour"]
    and_ = core["and_"]
    or_ = core["or_"]
    _get_active_locations = core["_get_active_locations"]
    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    COL_PAY = core["COL_PAY"]
    user_in_same_workplace = core["user_in_same_workplace"]
    get_employee_display_name = core["get_employee_display_name"]
    escape = core["escape"]
    fmt_hours = core["fmt_hours"]
    safe_float = core["safe_float"]
    money = core["money"]
    page_back_button = core["page_back_button"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    render_template_string = core["render_template_string"]

    gate = require_admin()
    if gate:
        return gate

    role = session.get("role", "admin")
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")

    rows = get_workhours_rows()
    allowed_wps = set(_workplace_ids_for_read())
    selected_site = (request.args.get("site") or "").strip()

    db_site_lookup = {}
    if DB_MIGRATION_MODE:
        try:
            db_rows = (
                WorkHour.query
                .filter(
                    and_(
                        or_(
                            WorkHour.workplace_id.in_(allowed_wps),
                            and_(WorkHour.workplace_id.is_(None), WorkHour.workplace.in_(allowed_wps)),
                            WorkHour.workplace.in_(allowed_wps),
                        )
                    )
                )
                .order_by(WorkHour.date.desc(), WorkHour.id.desc())
                .all()
            )

            for rec in db_rows:
                rec_user = str(getattr(rec, "employee_email", "") or "").strip()
                rec_date = rec.date.isoformat() if getattr(rec, "date", None) else ""
                rec_cin = rec.clock_in.strftime("%H:%M") if getattr(rec, "clock_in", None) else ""
                rec_cout = rec.clock_out.strftime("%H:%M") if getattr(rec, "clock_out", None) else ""
                rec_site = str(
                    getattr(rec, "out_site", "")
                    or getattr(rec, "in_site", "")
                    or ""
                ).strip()

                if not rec_user or not rec_date:
                    continue

                db_site_lookup[(rec_user, rec_date, rec_cin, rec_cout)] = rec_site
        except Exception:
            db_site_lookup = {}


    wp_idx = None
    in_site_idx = None
    out_site_idx = None
    if rows and len(rows) > 0:
        headers = rows[0]
        wp_idx = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
        in_site_idx = headers.index("InSite") if "InSite" in headers else None
        out_site_idx = headers.index("OutSite") if "OutSite" in headers else None

    records = []
    live_site_summary = {}
    for r in rows[1:]:
        if len(r) <= COL_PAY or len(r) <= COL_USER:
            continue

        row_user = (r[COL_USER] or "").strip()
        if not row_user:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(row_user):
                continue

        d_str = (r[COL_DATE] if len(r) > COL_DATE else "") or ""
        cin = ((r[COL_IN] if len(r) > COL_IN else "") or "").strip()
        cout = ((r[COL_OUT] if len(r) > COL_OUT else "") or "").strip()
        hours = (r[COL_HOURS] if len(r) > COL_HOURS else "") or ""
        pay = (r[COL_PAY] if len(r) > COL_PAY else "") or ""

        row_in_site = (r[in_site_idx] if in_site_idx is not None and len(r) > in_site_idx else "").strip()
        row_out_site = (r[out_site_idx] if out_site_idx is not None and len(r) > out_site_idx else "").strip()
        row_site = row_out_site or row_in_site or db_site_lookup.get((row_user, d_str, cin[:5], cout[:5]), "") or ""

        if cin and not cout:
            summary_site = row_site or "No site"
            live_site_summary.setdefault(summary_site, {
                "employees": set(),
                "logs": 0,
            })
            live_site_summary[summary_site]["employees"].add(row_user)
            live_site_summary[summary_site]["logs"] += 1

        if selected_site and row_site.lower() != selected_site.lower():
            continue

        if cin and not cout:
            status = "Live"
        elif cin and cout:
            status = "Complete"
        elif cin or cout or hours or pay:
            status = "Partial"
        else:
            status = "Blank"

        records.append({
            "user": row_user,
            "display": get_employee_display_name(row_user),
            "date": d_str,
            "cin": cin,
            "cout": cout,
            "hours": hours,
            "pay": pay,
            "status": status,
            "site": row_site,
        })

        records = sorted(
            records,
            key=lambda x: ((x["date"] or ""), (x["cin"] or ""), (x["user"] or "")),
            reverse=True,
        )

    site_names = []
    seen_sites = set()

    try:
        for rec in (_get_active_locations() or []):
            nm = str(rec.get("name") or rec.get("SiteName") or rec.get("site") or "").strip()
            if nm and nm.lower() not in seen_sites:
                seen_sites.add(nm.lower())
                site_names.append(nm)
    except Exception:
        pass

    for rec in records:
        nm = str(rec.get("site") or "").strip()
        if nm and nm.lower() not in seen_sites:
            seen_sites.add(nm.lower())
            site_names.append(nm)

    site_options_html = ['<option value="">All sites</option>']
    for nm in sorted(site_names, key=str.lower):
        selected_attr = "selected" if selected_site.lower() == nm.lower() else ""
        site_options_html.append(f"<option value='{escape(nm)}' {selected_attr}>{escape(nm)}</option>")
    site_options_html = "".join(site_options_html)

    total_logs = len(records)
    total_employees = len({str(rec.get("user") or "").strip().lower() for rec in records if str(rec.get("user") or "").strip()})
    total_hours = round(sum(safe_float(rec.get("hours", 0), 0.0) for rec in records), 2)
    total_pay = round(sum(safe_float(rec.get("pay", 0), 0.0) for rec in records), 2)

    site_summary_items = []
    for site_name, info in sorted(live_site_summary.items(), key=lambda kv: (-len(kv[1]["employees"]), kv[0].lower())):
        emp_count = len(info["employees"])
        live_count = int(info["logs"])
        site_summary_items.append(f"""
          <div class="logSiteMiniCard">
            <div class="logSiteMiniName">{escape(site_name)}</div>
            <div class="logSiteMiniMeta">
              <span>{emp_count} employee{'s' if emp_count != 1 else ''}</span>
              <span>•</span>
              <span>{live_count} live</span>
            </div>
          </div>
        """)

    site_summary_html = "".join(site_summary_items) if site_summary_items else """
      <div class="sub" style="padding:6px 0;">No one is currently clocked in.</div>
    """

    if records:
        table_rows = ""
        for rec in records:
            table_rows += f"""
              <tr>
                <td>{escape(rec.get('display') or rec['user'])}</td>
                <td>{escape(rec['date'])}</td>
                <td>{escape((rec['cin'] or '')[:5])}</td>
                <td>{escape((rec['cout'] or '')[:5])}</td>
                <td class="num">{escape(fmt_hours(rec['hours']))}</td>
                <td>{escape(rec['status'])}</td>
              </tr>
            """
    else:
        table_rows = """
          <tr>
            <td colspan="6" style="padding:16px; color:rgba(15,23,42,.65); font-weight:600;">
              No log activity found.
            </td>
          </tr>
        """

    page_css = """
    <style>
      .logActivitiesPageShell{
        display:flex;
        flex-direction:column;
        gap:16px;
      }

      .logActivitiesHero{
        padding:16px;
      }

      .logActivitiesHeroTop{
        display:flex;
        align-items:flex-start;
        justify-content:space-between;
        gap:12px;
        flex-wrap:wrap;
      }

      .logActivitiesEyebrow{
        font-size:12px;
        font-weight:800;
        letter-spacing:.08em;
        text-transform:uppercase;
        color:#315f8f;
        margin-bottom:6px;
      }

      .logActivitiesTableCard{
        padding:16px;
      }
      
      .logSiteSummaryRow{
  display:flex;
  flex-wrap:wrap;
  gap:10px;
  margin-bottom:14px;
}

.logSiteMiniCard{
  padding:10px 12px;
  border:1px solid rgba(15,23,42,.08);
  background:rgba(248,250,252,.9);
  min-width:170px;
}

.logSiteMiniName{
  font-size:13px;
  font-weight:700;
  color:#1f2547;
  line-height:1.2;
}

.logSiteMiniMeta{
  margin-top:4px;
  display:flex;
  gap:6px;
  flex-wrap:wrap;
  font-size:11px;
  color:#6f6c85;
  line-height:1.2;
}

      .logActivitiesTableCard .tablewrap{
        overflow-x:auto;
      }

            .logActivitiesTable{
  width:100% !important;
  min-width:1080px;
  table-layout:fixed !important;
}

.logActivitiesTable th,
.logActivitiesTable td{
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}

.logActivitiesTable th:nth-child(1),
.logActivitiesTable td:nth-child(1){
  width:24% !important;
  text-align:left !important;
}

.logActivitiesTable th:nth-child(2),
.logActivitiesTable td:nth-child(2){
  width:18% !important;
  text-align:center !important;
}

.logActivitiesTable th:nth-child(3),
.logActivitiesTable td:nth-child(3){
  width:12% !important;
  text-align:center !important;
}

.logActivitiesTable th:nth-child(4),
.logActivitiesTable td:nth-child(4){
  width:12% !important;
  text-align:center !important;
}

.logActivitiesTable th:nth-child(5),
.logActivitiesTable td:nth-child(5){
  width:12% !important;
  text-align:right !important;
}

.logActivitiesTable th:nth-child(6),
.logActivitiesTable td:nth-child(6){
  width:22% !important;
  text-align:center !important;
}

@media (max-width: 900px){
  .logActivitiesTable{
    min-width:1020px;
  }
}
    </style>
    """

    content = f"""
      {page_css}
      {page_back_button("/", "Back to dashboard")}

      <div class="logActivitiesPageShell">
        <div class="logActivitiesHero plainSection">
          <div class="logActivitiesHeroTop">
            <div>
              <div class="logActivitiesEyebrow">Admin logs</div>
              <h1 style="margin:0;">Log Activities</h1>
              <p class="sub" style="margin:6px 0 0 0;">All employee clock logs and work activity for the current workplace scope.</p>
            </div>
            <div class="badge admin">ALL LOGS</div>
          </div>
        </div>

                <div class="logActivitiesTableCard plainSection">
          <form method="GET" style="display:flex; gap:12px; align-items:end; flex-wrap:wrap; margin-bottom:14px;">
            <div style="min-width:220px;">
              <label class="sub">Site</label>
              <select class="input" name="site">
                {site_options_html}
              </select>
            </div>
            <button class="btnSoft" type="submit">Apply</button>
          </form>
          
          <div style="margin-bottom:8px;">
  <div class="sub" style="font-weight:700;">Live clocked in by site</div>
</div>
<div class="logSiteSummaryRow">
  {site_summary_html}
</div>


          <div class="tablewrap">
            <table class="timeLogsTable logActivitiesTable">
              <thead>
  <tr>
    <th>Employee</th>
    <th>Date</th>
    <th>In</th>
    <th>Out</th>
    <th class="num">Hours</th>
    <th>Status</th>
  </tr>
</thead>
              <tbody>
                {table_rows}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("admin", role, content)
    )


