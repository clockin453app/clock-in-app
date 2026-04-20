def admin_clock_selfies_impl(core):
    require_admin = core["require_admin"]
    request = core["request"]
    session = core["session"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    WorkHour = core["WorkHour"]
    work_sheet = core["work_sheet"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    get_employee_display_name = core["get_employee_display_name"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    escape = core["escape"]
    admin_back_link = core["admin_back_link"]

    gate = require_admin()
    if gate:
        return gate

    wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(wp))

    who = (request.args.get("user") or "").strip()
    kind = (request.args.get("kind") or "in").strip().lower()
    if kind not in ("in", "out", "all"):
        kind = "in"

    rows = []

    if DB_MIGRATION_MODE:
        q = WorkHour.query.filter(WorkHour.workplace_id.in_(allowed_wps))
        if who:
            q = q.filter(WorkHour.employee_email == who)

        db_rows = q.order_by(WorkHour.date.desc(), WorkHour.id.desc()).all()

        for rec in db_rows:
            in_url = str(getattr(rec, "in_selfie_url", "") or "").strip()
            out_url = str(getattr(rec, "out_selfie_url", "") or "").strip()

            if kind == "in" and not in_url:
                continue
            if kind == "out" and not out_url:
                continue
            if kind == "all" and not (in_url or out_url):
                continue

            rows.append({
                "username": str(getattr(rec, "employee_email", "") or ""),
                "date": rec.date.isoformat() if getattr(rec, "date", None) else "",
                "clock_in": rec.clock_in.strftime("%H:%M:%S") if getattr(rec, "clock_in", None) else "",
                "clock_out": rec.clock_out.strftime("%H:%M:%S") if getattr(rec, "clock_out", None) else "",
                "in_selfie_url": in_url,
                "out_selfie_url": out_url,
                "workplace_id": str(getattr(rec, "workplace_id", "") or getattr(rec, "workplace", "") or ""),
            })
    else:
        vals = work_sheet.get_all_values() if work_sheet else []
        if vals:
            headers = vals[0]

            def idx(name):
                return headers.index(name) if name in headers else None

            i_user = idx("Username")
            i_date = idx("Date")
            i_in = idx("ClockIn")
            i_out = idx("ClockOut")
            i_in_url = idx("InSelfieURL")
            i_out_url = idx("OutSelfieURL")
            i_wp = idx("Workplace_ID")

            for r in vals[1:]:
                username = (r[i_user] if i_user is not None and i_user < len(r) else "").strip()
                date_txt = (r[i_date] if i_date is not None and i_date < len(r) else "").strip()
                cin = (r[i_in] if i_in is not None and i_in < len(r) else "").strip()
                cout = (r[i_out] if i_out is not None and i_out < len(r) else "").strip()
                in_url = (r[i_in_url] if i_in_url is not None and i_in_url < len(r) else "").strip()
                out_url = (r[i_out_url] if i_out_url is not None and i_out_url < len(r) else "").strip()
                row_wp = ((r[i_wp] if i_wp is not None and i_wp < len(r) else "").strip() or "default")

                if row_wp not in allowed_wps:
                    continue
                if who and username != who:
                    continue
                if kind == "in" and not in_url:
                    continue
                if kind == "out" and not out_url:
                    continue
                if kind == "all" and not (in_url or out_url):
                    continue

                rows.append({
                    "username": username,
                    "date": date_txt,
                    "clock_in": cin,
                    "clock_out": cout,
                    "in_selfie_url": in_url,
                    "out_selfie_url": out_url,
                    "workplace_id": row_wp,
                })

    def render_selfie(url: str, label: str) -> str:
        u = str(url or "").strip()
        if not u:
            return "<span class='sub'>—</span>"

        u_esc = escape(u)

        if u.startswith("/clock-selfie/"):
            return f"""
                <div class="selfieCell">
                  <div class="selfieLabel">{escape(label)}</div>
                  <a href="{u_esc}" target="_blank" rel="noopener noreferrer" class="selfieThumbLink">
                    <img src="{u_esc}" alt="{escape(label)}" class="selfieThumb">
                  </a>
                </div>
            """

        return f"""
            <div class="selfieCell">
              <div class="selfieLabel">{escape(label)}</div>
              <div class="selfieExternal">
                <div class="sub" style="margin-bottom:8px;">Drive / external image</div>
                <a href="{u_esc}" target="_blank" rel="noopener noreferrer" class="btnTiny selfieOpenBtn">Open image</a>
              </div>
            </div>
        """

    body_rows = []
    for row in rows:
        display_name = get_employee_display_name(row["username"])
        body_rows.append(f"""
            <tr>
              <td>
                <div style="font-weight:700;">{escape(display_name)}</div>
                <div class="sub">{escape(row["username"])}</div>
              </td>
              <td>{escape(row["date"])}</td>
              <td>{escape(row["clock_in"])}</td>
              <td>{escape(row["clock_out"])}</td>
              <td>{render_selfie(row["in_selfie_url"], "Clock In")}</td>
              <td>{render_selfie(row["out_selfie_url"], "Clock Out")}</td>
            </tr>
        """)

    body_html = "".join(body_rows) if body_rows else """
        <tr>
          <td colspan="6" class="sub">No selfies found for this workplace.</td>
        </tr>
    """

    content = f"""
      <style>
        .selfieFilters {{
          display:flex;
          gap:10px;
          flex-wrap:wrap;
          align-items:end;
        }}

        .selfieThumb {{
          width:120px;
          height:120px;
          object-fit:cover;
          display:block;
          background:#fff;
          border:1px solid rgba(15,23,42,.08);
          box-shadow:0 8px 18px rgba(15,23,42,.08);
        }}

        .selfieThumbLink {{
          display:inline-block;
          text-decoration:none;
        }}

        .selfieCell {{
          min-width:140px;
        }}

        .selfieLabel {{
          font-size:12px;
          font-weight:700;
          color:#64748b;
          margin-bottom:8px;
          text-transform:uppercase;
          letter-spacing:.03em;
        }}

        .selfieExternal {{
          width:120px;
          min-height:120px;
          padding:12px;
          border:1px solid rgba(15,23,42,.08);
          background:#fff;
          box-shadow:0 8px 18px rgba(15,23,42,.08);
          display:flex;
          flex-direction:column;
          justify-content:center;
        }}

        .selfieOpenBtn {{
          width:100%;
          text-align:center;
        }}
      </style>

      <div class="headerTop">
        <div>
          <h1>Clock Selfies</h1>
          <p class="sub">View employee clock-in and clock-out photos for this workplace.</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {admin_back_link("/admin")}

      <div class="card" style="padding:12px;">
        <form method="GET" class="selfieFilters">
          <div>
            <label class="sub">Username</label>
            <input class="input" type="text" name="user" value="{escape(who)}" placeholder="optional username filter">
          </div>
          <div>
            <label class="sub">Type</label>
            <select class="input" name="kind">
              <option value="in" {"selected" if kind == "in" else ""}>Clock In only</option>
              <option value="out" {"selected" if kind == "out" else ""}>Clock Out only</option>
              <option value="all" {"selected" if kind == "all" else ""}>Both</option>
            </select>
          </div>
          <button class="btnSoft" type="submit">Apply</button>
        </form>
      </div>

      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>Images</h2>
        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:1100px;">
            <thead>
              <tr>
                <th>Employee</th>
                <th>Date</th>
                <th>Clock In</th>
                <th>Clock Out</th>
                <th>In selfie</th>
                <th>Out selfie</th>
              </tr>
            </thead>
            <tbody>{body_html}</tbody>
          </table>
        </div>
      </div>
    """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )