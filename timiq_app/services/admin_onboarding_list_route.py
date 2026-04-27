from datetime import date, datetime, timedelta
def admin_onboarding_list_impl(core):
    require_admin = core["require_admin"]
    request = core["request"]
    onboarding_sheet = core["onboarding_sheet"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    OnboardingRecord = core["OnboardingRecord"]
    get_onboarding_record = core["get_onboarding_record"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    user_in_same_workplace = core["user_in_same_workplace"]
    escape = core["escape"]
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

    q = (request.args.get("q", "") or "").strip().lower()
    def parse_onboarding_date(value):
        text = str(value or "").strip()
        if not text:
            return None

        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(text[:10], fmt).date()
            except Exception:
                pass

        return None

    def badge_html(text, kind="ok"):
        if kind == "bad":
            bg = "#fee2e2"
            border = "#fecaca"
            color = "#b91c1c"
        elif kind == "warn":
            bg = "#fef3c7"
            border = "#fde68a"
            color = "#92400e"
        else:
            bg = "#dcfce7"
            border = "#bbf7d0"
            color = "#15803d"

        return (
            f"<span style='display:inline-flex; align-items:center; justify-content:center; "
            f"padding:4px 8px; border:1px solid {border}; background:{bg}; color:{color}; "
            f"font-size:11px; font-weight:900; white-space:nowrap; margin:2px;'>"
            f"{escape(text)}</span>"
        )

    def cscs_status_badge(expiry_value):
        d = parse_onboarding_date(expiry_value)
        today = date.today()

        if not d:
            return badge_html("CSCS missing", "warn")

        if d < today:
            return badge_html("CSCS expired", "bad")

        if d <= today + timedelta(days=30):
            return badge_html("CSCS expiring", "warn")

        return badge_html("CSCS valid", "ok")

    def docs_status_badge(rec):
        missing = 0

        for key in [
            "PassportOrBirthCertLink",
            "CSCSFrontBackLink",
            "PublicLiabilityLink",
            "ShareCodeLink",
        ]:
            if not str((rec or {}).get(key, "") or "").strip():
                missing += 1

        if missing <= 0:
            return badge_html("Docs complete", "ok")

        return badge_html(f"{missing} docs missing", "warn")

    def build_status_html(username):
        try:
            full_rec = get_onboarding_record(username) or {}
        except Exception:
            full_rec = {}

        status_parts = [
            cscs_status_badge(full_rec.get("CSCSExpiryDate", "")),
            docs_status_badge(full_rec),
        ]

        if str(full_rec.get("RightToWorkUK", "") or "").strip().lower() == "yes":
            status_parts.append(badge_html("RTW yes", "ok"))
        else:
            status_parts.append(badge_html("RTW check", "warn"))

        contract_value = str(full_rec.get("ContractAccepted", "") or "").strip().lower()

        if contract_value in {"true", "yes", "1", "accepted", "signed"}:
            status_parts.append(badge_html("Contract signed", "ok"))
        else:
            status_parts.append(badge_html("Contract unsigned", "warn"))

        return "<div style='display:flex; gap:4px; flex-wrap:wrap; align-items:center;'>" + "".join(status_parts) + "</div>"
    vals = onboarding_sheet.get_all_values() if not DB_MIGRATION_MODE else [
                                                                               ["Username", "FirstName", "LastName",
                                                                                "SubmittedAt", "Workplace_ID"]
                                                                           ] + [
                                                                               [
                                                                                   str(getattr(rec, "username",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "first_name",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "last_name",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "submitted_at",
                                                                                               "") or "").strip(),
                                                                                   str(getattr(rec, "workplace_id",
                                                                                               "default") or "default").strip(),
                                                                               ]
                                                                               for rec in OnboardingRecord.query.all()
                                                                           ]
    if not vals:
        body = "<tr><td colspan='5'>No onboarding data.</td></tr>"
    else:
        headers = vals[0]

        def idx(name):
            return headers.index(name) if name in headers else None

        i_user = idx("Username")
        i_fn = idx("FirstName")
        i_ln = idx("LastName")
        i_sub = idx("SubmittedAt")
        i_wp = idx("Workplace_ID")
        wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(wp))
        rows_html = []

        rows_html = []
        for r in vals[1:]:
            u = r[i_user] if i_user is not None and i_user < len(r) else ""
            if not u:
                continue
            # Tenant-safe: filter by Onboarding row Workplace_ID (if column exists)
            if i_wp is not None:
                row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                if row_wp not in allowed_wps:
                    continue
            else:
                # Backward compat if Onboarding has no Workplace_ID column
                if not user_in_same_workplace(u):
                    continue
            fn = r[i_fn] if i_fn is not None and i_fn < len(r) else ""
            ln = r[i_ln] if i_ln is not None and i_ln < len(r) else ""
            sub = r[i_sub] if i_sub is not None and i_sub < len(r) else ""
            name = (fn + " " + ln).strip() or u
            if q and (q not in u.lower() and q not in name.lower()):
                continue
            status_html = build_status_html(u)

            rows_html.append(
                f"<tr>"
                f"<td><a href='/admin/onboarding/{escape(u)}' style='color:var(--navy);font-weight:600;'>{escape(name)}</a></td>"
                f"<td>{escape(u)}</td>"
                f"<td>{escape(sub)}</td>"
                f"<td>{status_html}</td>"
                f"<td style='text-align:center; white-space:nowrap;'>"
                f"<a href='/admin/onboarding/{escape(u)}/download' target='_blank' rel='noopener' "
                f"style='display:inline-block; text-decoration:none; font-size:12px; font-weight:700; color:#3b74ad; line-height:1;'>PDF</a>"
                f"</td>"
                f"</tr>"
            )
        body = "".join(rows_html) if rows_html else "<tr><td colspan='5'>No matches.</td></tr>"

    content = f"""
          <div class="headerTop">
            <div>
              <h1>Onboarding</h1>
              <p class="sub">Click a name to view details</p>
            </div>
            <div class="badge admin">ADMIN</div>
          </div>

          {admin_back_link()}

          <div class="card" style="padding:12px;">
            <form method="GET">
              <label class="sub">Search</label>
              <div class="row2">
                <input class="input" name="q" value="{escape(q)}" placeholder="name or username">
                <button class="btnSoft" type="submit" style="margin-top:8px;">Search</button>
              </div>
            </form>

            <div class="tablewrap" style="margin-top:12px;">
              <table style="min-width: 720px;">
                <thead><tr><th>Name</th><th>Username</th><th>Last saved</th><th>Status</th><th style="text-align:center; width:70px;">PDF</th></tr></thead>
                <tbody>{body}</tbody>
              </table>
            </div>
          </div>
        """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )
