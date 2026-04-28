def admin_audit_impl(core):
    require_master_admin = core["require_master_admin"]
    session = core["session"]
    request = core["request"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    escape = core["escape"]
    page_back_button = core.get("page_back_button")
    admin_back_link = core.get("admin_back_link")

    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    AuditLog = core["AuditLog"]
    audit_sheet = core.get("audit_sheet")
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    _session_workplace_id = core["_session_workplace_id"]

    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    render_template_string = core["render_template_string"]

    gate = require_master_admin()
    if gate:
        return gate

    role = session.get("role", "master_admin")
    current_wp = _session_workplace_id()

    # Master Admin audit page should see all workplace audit rows.
    # Normal workplace filtering still applies if this page is ever reused outside master admin.
    if session.get("role") == "master_admin":
        allowed_wps = None
    else:
        allowed_wps = set(_workplace_ids_for_read(current_wp))

    q = (request.args.get("q") or "").strip().lower()
    action_filter = (request.args.get("action") or "").strip().lower()
    actor_filter = (request.args.get("actor") or "").strip().lower()

    def nice_action(value):
        return str(value or "").replace("_", " ").replace("-", " ").title()

    def clean_dt(value):
        if not value:
            return ""
        try:
            return value.strftime("%d %b %Y • %H:%M:%S")
        except Exception:
            pass
        raw = str(value or "").strip()
        try:
            return datetime.fromisoformat(raw).strftime("%d %b %Y • %H:%M:%S")
        except Exception:
            return raw

    def row_matches(item):
        searchable = " ".join([
            str(item.get("action") or ""),
            str(item.get("actor") or ""),
            str(item.get("username") or ""),
            str(item.get("details") or ""),
            str(item.get("workplace_id") or ""),
            str(item.get("date_text") or ""),
        ]).lower()

        if q and q not in searchable:
            return False

        if action_filter and action_filter not in str(item.get("action") or "").lower():
            return False

        # Actor filter should match either the real actor OR the target account.
        # Some audit rows store IP addresses in Actor and the actual account in Username.
        if actor_filter:
            actor_text = str(item.get("actor") or "").lower()
            username_text = str(item.get("username") or "").lower()
            if actor_filter not in actor_text and actor_filter not in username_text:
                return False

        return True

    audit_items = []

    if DB_MIGRATION_MODE:
        try:
            query = AuditLog.query

            if allowed_wps is not None:
                query = query.filter(AuditLog.workplace_id.in_(list(allowed_wps)))

            query = AuditLog.query

            if allowed_wps is not None:
                query = query.filter(AuditLog.workplace_id.in_(list(allowed_wps)))

            db_rows = (
                query
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(500)
                .all()
            )

            for rec in db_rows:
                item = {
                    "created_at": getattr(rec, "created_at", None),
                    "when": clean_dt(getattr(rec, "created_at", None)),
                    "actor": str(getattr(rec, "actor", "") or "").strip(),
                    "action": str(getattr(rec, "action", "") or "").strip(),
                    "username": str(getattr(rec, "username", "") or "").strip(),
                    "date_text": str(getattr(rec, "date_text", "") or "").strip(),
                    "details": str(getattr(rec, "details", "") or "").strip(),
                    "workplace_id": str(getattr(rec, "workplace_id", "") or "").strip() or "default",
                }

                if allowed_wps is not None and item["workplace_id"] not in allowed_wps:
                    continue

                if row_matches(item):
                    audit_items.append(item)
        except Exception:
            audit_items = []
    else:
        try:
            vals = audit_sheet.get_all_values() if audit_sheet else []
            headers = vals[0] if vals else []

            def idx(name):
                return headers.index(name) if name in headers else None

            i_ts = idx("Timestamp")
            i_actor = idx("Actor")
            i_action = idx("Action")
            i_user = idx("Username")
            i_date = idx("Date")
            i_details = idx("Details")
            i_wp = idx("Workplace_ID")

            for row in reversed(vals[1:]):
                row_wp = (row[i_wp] if i_wp is not None and i_wp < len(row) else "").strip() or "default"
                if allowed_wps is not None and row_wp not in allowed_wps:
                    continue

                item = {
                    "created_at": None,
                    "when": clean_dt(row[i_ts] if i_ts is not None and i_ts < len(row) else ""),
                    "actor": (row[i_actor] if i_actor is not None and i_actor < len(row) else "").strip(),
                    "action": (row[i_action] if i_action is not None and i_action < len(row) else "").strip(),
                    "username": (row[i_user] if i_user is not None and i_user < len(row) else "").strip(),
                    "date_text": (row[i_date] if i_date is not None and i_date < len(row) else "").strip(),
                    "details": (row[i_details] if i_details is not None and i_details < len(row) else "").strip(),
                    "workplace_id": row_wp,
                }

                if row_matches(item):
                    audit_items.append(item)

                if len(audit_items) >= 300:
                    break
        except Exception:
            audit_items = []

    audit_items = audit_items[:200]

    total_count = len(audit_items)
    unique_actor_values = set()
    for item in audit_items:
        actor_value = str(item.get("actor") or "").strip()
        username_value = str(item.get("username") or "").strip()

        if actor_value:
            unique_actor_values.add(actor_value)

        if username_value:
            unique_actor_values.add(username_value)

    unique_actors = sorted(unique_actor_values, key=lambda x: x.lower())
    unique_actions = sorted({item["action"] for item in audit_items if item.get("action")}, key=lambda x: x.lower())

    table_rows = ""
    for item in audit_items:
        action = nice_action(item.get("action"))
        actor = item.get("actor") or "System"
        target = item.get("username") or "—"
        date_text = item.get("date_text") or "—"
        details = item.get("details") or ""
        workplace_id = item.get("workplace_id") or "default"
        when = item.get("when") or "—"

        table_rows += f"""
          <tr>
            <td>
              <div class="auditActionTitle">{escape(action or "Activity")}</div>
              <div class="auditActionSub">{escape(details)}</div>
            </td>
            <td>{escape(actor)}</td>
            <td>{escape(target)}</td>
            <td>{escape(date_text)}</td>
            <td>{escape(workplace_id)}</td>
            <td>{escape(when)}</td>
          </tr>
        """

    if not table_rows:
        table_rows = """
          <tr>
            <td colspan="6">
              <div class="auditEmpty">No admin activity found for the current filters.</div>
            </td>
          </tr>
        """

    action_options = '<option value="">All actions</option>'
    for action in unique_actions:
        selected = "selected" if action_filter and action_filter == action.lower() else ""
        action_options += f'<option value="{escape(action)}" {selected}>{escape(nice_action(action))}</option>'

    actor_options = '<option value="">All users / actors</option>'
    for actor in unique_actors:
        selected = "selected" if actor_filter and actor_filter == actor.lower() else ""
        actor_options += f'<option value="{escape(actor)}" {selected}>{escape(actor)}</option>'

    back_html = admin_back_link() if callable(admin_back_link) else (
        page_back_button("/admin", "Back") if callable(page_back_button) else '<a href="/admin">← Back</a>'
    )

    audit_css = """
      <style>
        .auditPageWrap{
          display:grid;
          gap:14px;
        }

        .auditHeader{
          display:flex;
          align-items:flex-start;
          justify-content:space-between;
          gap:14px;
          padding:22px 24px;
          background:#fff;
          border:1px solid #dbe7f6;
          box-shadow:0 18px 44px rgba(15,23,42,.06);
        }

        .auditHeader h1{
          margin:0;
          color:#07152f;
          font-size:30px;
          line-height:1.05;
          font-weight:900;
          letter-spacing:-.04em;
        }

        .auditHeader p{
          margin:8px 0 0 0;
          color:#52627d;
          font-size:14px;
          font-weight:700;
        }

        .auditBadge{
          display:inline-flex;
          align-items:center;
          justify-content:center;
          min-height:34px;
          padding:0 12px;
          border:1px solid #dbeafe;
          background:#eff6ff;
          color:#0b63ff;
          font-size:12px;
          font-weight:900;
          white-space:nowrap;
        }

        .auditFilters{
          display:grid;
          grid-template-columns:minmax(220px,1fr) 210px 210px auto;
          gap:10px;
          padding:14px;
          background:#fff;
          border:1px solid #dbe7f6;
          box-shadow:0 12px 30px rgba(15,23,42,.04);
        }

        .auditFilters input,
        .auditFilters select{
          height:40px;
          padding:0 12px;
          border:1px solid #cfd9e8;
          background:#fff;
          color:#07152f;
          font-size:13px;
          font-weight:700;
        }

        .auditFilters button,
        .auditFilters a{
          min-height:40px;
          display:inline-flex;
          align-items:center;
          justify-content:center;
          padding:0 16px;
          border:1px solid #0b63ff;
          background:#0b63ff;
          color:#fff;
          font-size:13px;
          font-weight:900;
          text-decoration:none;
          white-space:nowrap;
        }

        .auditFilters a{
          background:#fff;
          color:#0b63ff;
          border-color:#bfdbfe;
        }

        .auditTableCard{
          background:#fff;
          border:1px solid #dbe7f6;
          box-shadow:0 18px 44px rgba(15,23,42,.06);
          overflow:hidden;
        }

        .auditTableHead{
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:12px;
          padding:16px 18px;
          border-bottom:1px solid #e6eef8;
        }

        .auditTableHead h2{
          margin:0;
          color:#07152f;
          font-size:18px;
          font-weight:900;
        }

        .auditTableHead span{
          color:#64748b;
          font-size:12px;
          font-weight:800;
        }

        .auditTableWrap{
          overflow:auto;
        }

        .auditTable{
          width:100%;
          min-width:980px;
          border-collapse:collapse;
        }

        .auditTable th{
          padding:12px 14px;
          text-align:left;
          background:#f8fbff;
          color:#64748b;
          font-size:11px;
          font-weight:900;
          text-transform:uppercase;
          letter-spacing:.05em;
          border-bottom:1px solid #e6eef8;
        }

        .auditTable td{
          padding:14px;
          border-bottom:1px solid #edf2f8;
          color:#0f172a;
          font-size:13px;
          font-weight:700;
          vertical-align:top;
        }

        .auditTable tr:last-child td{
          border-bottom:0;
        }

        .auditActionTitle{
          color:#07152f;
          font-weight:900;
        }

        .auditActionSub{
          margin-top:4px;
          color:#64748b;
          font-size:12px;
          font-weight:700;
          white-space:normal;
          line-height:1.35;
        }

        .auditEmpty{
          padding:26px;
          color:#64748b;
          font-weight:800;
          text-align:center;
        }

        @media (max-width:900px){
          .auditFilters{
            grid-template-columns:1fr;
          }

          .auditHeader{
            flex-direction:column;
          }
        }
      </style>
    """

    content = f"""
      {back_html}

      <div class="auditPageWrap">
        <div class="auditHeader">
          <div>
            <h1>Admin Activity</h1>
            <p>Master Admin audit trail for payroll, employee, login and management actions.</p>
          </div>
          <div class="auditBadge">MASTER ADMIN</div>
        </div>

        <form class="auditFilters" method="GET">
          <input type="search" name="q" value="{escape(q)}" placeholder="Search action, actor, employee, details...">

          <select name="action">
            {action_options}
          </select>

          <select name="actor">
            {actor_options}
          </select>

          <div style="display:flex; gap:8px;">
            <button type="submit">Apply</button>
            <a href="/admin/audit">Clear</a>
          </div>
        </form>

        <div class="auditTableCard">
          <div class="auditTableHead">
            <h2>Activity log</h2>
            <span>{total_count} record(s)</span>
          </div>

          <div class="auditTableWrap">
            <table class="auditTable">
              <thead>
                <tr>
                  <th style="width:28%;">Action</th>
                  <th style="width:14%;">Actor</th>
                  <th style="width:14%;">Target</th>
                  <th style="width:12%;">Date Ref</th>
                  <th style="width:14%;">Workplace</th>
                  <th style="width:18%;">When</th>
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
        f"{STYLE}{VIEWPORT}{PWA_TAGS}{audit_css}" +
        layout_shell("admin", role, content)
    )