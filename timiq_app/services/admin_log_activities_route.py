def admin_log_activities_impl(core):
    require_admin = core["require_admin"]
    session = core["session"]
    get_company_settings = core["get_company_settings"]
    get_workhours_rows = core["get_workhours_rows"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    COL_PAY = core["COL_PAY"]
    user_in_same_workplace = core["user_in_same_workplace"]
    escape = core["escape"]
    fmt_hours = core["fmt_hours"]
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

    wp_idx = None
    if rows and len(rows) > 0:
        headers = rows[0]
        wp_idx = headers.index("Workplace_ID") if "Workplace_ID" in headers else None

    records = []
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
        cin = (r[COL_IN] if len(r) > COL_IN else "") or ""
        cout = (r[COL_OUT] if len(r) > COL_OUT else "") or ""
        hours = (r[COL_HOURS] if len(r) > COL_HOURS else "") or ""
        pay = (r[COL_PAY] if len(r) > COL_PAY else "") or ""

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
            "date": d_str,
            "cin": cin,
            "cout": cout,
            "hours": hours,
            "pay": pay,
            "status": status,
        })

    records = sorted(
        records,
        key=lambda x: ((x["date"] or ""), (x["cin"] or ""), (x["user"] or "")),
        reverse=True,
    )

    if records:
        table_rows = ""
        for rec in records:
            table_rows += f"""
              <tr>
                <td>{escape(rec['user'])}</td>
                <td>{escape(rec['date'])}</td>
                <td>{escape((rec['cin'] or '')[:5])}</td>
                <td>{escape((rec['cout'] or '')[:5])}</td>
                <td class="num">{escape(fmt_hours(rec['hours']))}</td>
                <td class="num">{escape(currency)}{escape(rec['pay'])}</td>
                <td>{escape(rec['status'])}</td>
              </tr>
            """
    else:
        table_rows = """
          <tr>
            <td colspan="7" style="padding:16px; color:rgba(15,23,42,.65); font-weight:600;">
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

      .logActivitiesTableCard .tablewrap{
        overflow-x:auto;
      }

      .logActivitiesTable{
        width:100% !important;
        min-width:1100px;
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
        width:20% !important;
        text-align:left !important;
      }

      .logActivitiesTable th:nth-child(2),
      .logActivitiesTable td:nth-child(2){
        width:16% !important;
        text-align:center !important;
      }

      .logActivitiesTable th:nth-child(3),
      .logActivitiesTable td:nth-child(3){
        width:10% !important;
        text-align:center !important;
      }

      .logActivitiesTable th:nth-child(4),
      .logActivitiesTable td:nth-child(4){
        width:10% !important;
        text-align:center !important;
      }

      .logActivitiesTable th:nth-child(5),
      .logActivitiesTable td:nth-child(5){
        width:10% !important;
        text-align:right !important;
      }

      .logActivitiesTable th:nth-child(6),
      .logActivitiesTable td:nth-child(6){
        width:14% !important;
        text-align:right !important;
      }

      .logActivitiesTable th:nth-child(7),
      .logActivitiesTable td:nth-child(7){
        width:20% !important;
        text-align:center !important;
      }

      @media (max-width: 900px){
        .logActivitiesTable{
          min-width:980px;
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
          <div class="tablewrap">
            <table class="timeLogsTable logActivitiesTable">
              <thead>
                <tr>
                  <th>Employee</th>
                  <th>Date</th>
                  <th>In</th>
                  <th>Out</th>
                  <th class="num">Hours</th>
                  <th class="num">Pay</th>
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


