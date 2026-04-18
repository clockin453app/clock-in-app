def my_times_impl(core):
    require_login = core["require_login"]
    session = core["session"]
    get_employee_display_name = core["get_employee_display_name"]
    get_company_settings = core["get_company_settings"]
    work_sheet = core["work_sheet"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    timedelta = core["timedelta"]
    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    COL_PAY = core["COL_PAY"]
    user_in_same_workplace = core["user_in_same_workplace"]
    safe_float = core["safe_float"]
    escape = core["escape"]
    fmt_hours = core["fmt_hours"]
    money = core["money"]
    page_back_button = core["page_back_button"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    render_template_string = core["render_template_string"]

    gate = require_login()
    if gate:
        return gate

    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)
    settings = get_company_settings()
    currency = str(settings.get("Currency_Symbol", "£") or "£")

    rows = work_sheet.get_all_values()
    headers = rows[0] if rows else []
    wp_idx = headers.index("Workplace_ID") if (headers and "Workplace_ID" in headers) else None
    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp))

    records = []
    total_hours = 0.0
    total_pay = 0.0
    last_clock_date = "—"
    today_count = 0
    week_count = 0
    today = datetime.now(TZ).date()
    week_start = today - timedelta(days=today.weekday())

    for r in rows[1:]:
        if len(r) <= COL_PAY or len(r) <= COL_USER:
            continue
        row_user = (r[COL_USER] or "").strip()
        if row_user != username:
            continue

        if wp_idx is not None:
            row_wp = (r[wp_idx] if len(r) > wp_idx else "").strip() or "default"
            if row_wp not in allowed_wps:
                continue
        else:
            if not user_in_same_workplace(row_user):
                continue

        d_raw = (r[COL_DATE] if len(r) > COL_DATE else "").strip()
        hours_val = safe_float((r[COL_HOURS] if len(r) > COL_HOURS else "") or "0", 0.0)
        pay_val = safe_float((r[COL_PAY] if len(r) > COL_PAY else "") or "0", 0.0)
        total_hours += hours_val
        total_pay += pay_val
        if d_raw:
            last_clock_date = d_raw
            try:
                row_date = datetime.strptime(d_raw, "%Y-%m-%d").date()
                if row_date == today:
                    today_count += 1
                if week_start <= row_date <= today:
                    week_count += 1
            except Exception:
                pass

        records.append({
            "date": d_raw,
            "clock_in": (r[COL_IN] if len(r) > COL_IN else "") or "",
            "clock_out": (r[COL_OUT] if len(r) > COL_OUT else "") or "",
            "hours": hours_val,
            "pay": pay_val,
        })

    def _time_log_sort_key(rec):
        d = str(rec.get("date") or "").strip()
        t = str(rec.get("clock_in") or "00:00:00").strip()

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(f"{d} {t}", fmt)
            except Exception:
                pass

        return datetime.min

    records.sort(key=_time_log_sort_key, reverse=True)

    table_rows = []
    for rec in records:
        table_rows.append(
            f"<tr><td>{escape(rec['date'])}</td><td>{escape(rec['clock_in'])}</td><td>{escape(rec['clock_out'])}</td><td class='num'>{escape(fmt_hours(rec['hours']))}</td><td class='num'>{escape(currency)}{escape(money(rec['pay']))}</td></tr>"
        )
    table = "".join(table_rows) if table_rows else "<tr><td colspan='5'>No records yet.</td></tr>"

    page_css = """
        <style>
          .timeLogsPageShell{ display:grid; gap:14px; }
          .timeLogsHero{
            padding:18px;
            border-radius: 0 !important;
            border:1px solid rgba(96,165,250,.16);
            background:linear-gradient(180deg, rgba(242,247,251,.98), rgba(255,255,255,.98));
            box-shadow:0 18px 40px rgba(15,23,42,.08), inset 0 1px 0 rgba(255,255,255,.78);
          }
          .timeLogsSummaryCard,
          .timeLogsTableCard{
            border:1px solid rgba(15,23,42,.08);
            background:linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
            box-shadow:0 14px 30px rgba(15,23,42,.06);
          }
          .timeLogsHeroTop{ display:flex; justify-content:space-between; gap:14px; align-items:flex-start; flex-wrap:wrap; }
          .timeLogsEyebrow{ display:inline-flex; align-items:center; gap:8px; padding:7px 12px; border-radius: 0 !important; font-size:12px; font-weight:800; letter-spacing:.05em; text-transform:uppercase; color:#3b74ad; background:rgba(68,130,195,.10); border:1px solid rgba(68,130,195,.16); }
          .timeLogsHero h1{ margin:12px 0 0; font-size:clamp(34px, 5vw, 46px); color:var(--text); }
          .timeLogsHero .sub{ color:var(--muted); }
          .timeLogsSummaryGrid{ display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:12px; }
          .timeLogsSummaryCard{ padding:14px 16px; border-radius: 0 !important; }
          .timeLogsSummaryCard .k{ font-size:12px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; color:#64748b; }
          .timeLogsSummaryCard .v{ margin-top:8px; font-size:clamp(24px, 3vw, 34px); font-weight:800; color:var(--text); }
          .timeLogsSummaryCard .sub{ margin-top:6px; color:var(--muted); }
          .timeLogsTableCard{ padding:12px; border-radius: 0 !important; }
          .timeLogsTable{ width:100%; min-width:720px; border-collapse:separate; border-spacing:0; overflow:hidden; border:1px solid rgba(15,23,42,.08); border-radius: 0 !important; background:rgba(255,255,255,.98); }
          .timeLogsTable thead th{ padding:14px 16px; font-size:12px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; color:#475569; background:linear-gradient(180deg, rgba(248,250,252,.98), rgba(241,245,249,.98)); border-bottom:1px solid rgba(15,23,42,.08); }
          .timeLogsTable tbody td{ padding:16px; color:var(--text); font-weight:700; font-variant-numeric:tabular-nums; border-bottom:1px solid rgba(15,23,42,.08); }
          .timeLogsTable tbody tr:nth-child(even) td{ background:rgba(248,250,252,.92); }
          .timeLogsTable tbody tr:hover td{ background:rgba(59,130,246,.06); }
          .timeLogsTable td.num, .timeLogsTable th.num{ text-align:right; }
          .timeLogsTable tbody tr:last-child td{ border-bottom:0; }
          @media (max-width: 960px){ .timeLogsSummaryGrid{ grid-template-columns:1fr 1fr; } }
          @media (max-width: 700px){ .timeLogsSummaryGrid{ grid-template-columns:1fr; } .timeLogsHero{ padding:16px; border-radius: 0 !important; } .timeLogsTableCard{ padding:10px; border-radius: 0 !important; } }
        </style>
        """

    content = f"""
      {page_css}
      {page_back_button("/", "Back to dashboard")}

      <div class="timeLogsPageShell">
        <div class="timeLogsHero plainSection">
          <div class="timeLogsHeroTop">
            <div>
              <div class="timeLogsEyebrow">Clock history</div>
              <h1>Time logs</h1>
              <p class="sub">{escape(display_name)} • Review every saved clock in and out entry.</p>
            </div>
            <div class="badge {'admin' if role == 'admin' else ''}">{escape(role.upper())}</div>
          </div>
        </div>

        <div class="timeLogsSummaryGrid">
          <div class="timeLogsSummaryCard plainMetric"><div class="k">Entries</div><div class="v">{len(records)}</div><div class="sub">Saved shifts</div></div>
          <div class="timeLogsSummaryCard plainMetric"><div class="k">Total Hours</div><div class="v">{escape(fmt_hours(total_hours))}</div><div class="sub">Across all records</div></div>
          <div class="timeLogsSummaryCard plainMetric"><div class="k">Total Pay</div><div class="v">{escape(currency)}{escape(money(total_pay))}</div><div class="sub">Recorded gross pay</div></div>
          <div class="timeLogsSummaryCard plainMetric"><div class="k">Recent Activity</div><div class="v">{escape(str(last_clock_date))}</div><div class="sub">Today: {today_count} • This week: {week_count}</div></div>
        </div>

        <div class="timeLogsTableCard plainSection">
          <div class="tablewrap">
            <table class="timeLogsTable">
              <thead><tr><th>Date</th><th>Clock In</th><th>Clock Out</th><th class='num'>Hours</th><th class='num'>Pay</th></tr></thead>
              <tbody>{table}</tbody>
            </table>
          </div>
        </div>
      </div>
    """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("times", role, content))


