
def clock_page_impl(core):
    require_login = core["require_login"]
    require_csrf = core["require_csrf"]
    get_csrf = core["get_csrf"]
    session = core["session"]

    get_employee_display_name = core["get_employee_display_name"]
    _get_user_rate = core["_get_user_rate"]
    _find_employee_record = core["_find_employee_record"]
    _session_workplace_id = core["_session_workplace_id"]
    parse_bool = core["parse_bool"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    _ensure_workhours_geo_headers = core["_ensure_workhours_geo_headers"]
    _get_employee_site = core["_get_employee_site"]
    _get_site_config = core["_get_site_config"]
    request = core["request"]
    CLOCK_SELFIE_REQUIRED = core["CLOCK_SELFIE_REQUIRED"]
    _validate_recent_clock_capture = core["_validate_recent_clock_capture"]
    _sanitize_clock_geo = core["_sanitize_clock_geo"]
    _validate_user_location = core["_validate_user_location"]
    _get_employee_sites = core["_get_employee_sites"]
    _get_active_locations = core["_get_active_locations"]
    work_sheet = core["work_sheet"]
    find_open_shift = core["find_open_shift"]
    has_any_row_today = core["has_any_row_today"]
    _store_clock_selfie = core["_store_clock_selfie"]
    normalized_clock_in_time = core["normalized_clock_in_time"]
    _gs_write_with_retry = core["_gs_write_with_retry"]
    _find_workhours_row_by_user_date = core["_find_workhours_row_by_user_date"]
    gspread = core["gspread"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    WorkHour = core["WorkHour"]
    or_ = core["or_"]
    db = core["db"]
    CLOCKIN_EARLIEST = core["CLOCKIN_EARLIEST"]
    redirect = core["redirect"]
    url_for = core["url_for"]
    _logger = core["_logger"]
    get_workhours_rows = core["get_workhours_rows"]
    escape = core["escape"]
    json = core["json"]
    get_company_settings = core["get_company_settings"]
    page_back_button = core["page_back_button"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    timedelta = core["timedelta"]
    COL_OUT = core["COL_OUT"]
    COL_PAY = core["COL_PAY"]
    _round_to_half_hour = core["_round_to_half_hour"]
    _apply_unpaid_break = core["_apply_unpaid_break"]
    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)

    rate = _get_user_rate(username)
    early_access = bool(session.get("early_access", False))
    try:
        live_user = _find_employee_record(username, _session_workplace_id())
        if live_user:
            early_access = parse_bool(live_user.get("EarlyAccess", early_access))
            session["early_access"] = early_access
    except Exception:
        pass

    now = datetime.now(TZ)
    today_str = now.strftime("%Y-%m-%d")

    # Geo-fence config (all employee assigned sites -> Locations sheet)
    _ensure_workhours_geo_headers()

    assigned_site_names = _get_employee_sites(username)
    site_cfgs = []

    for sname in assigned_site_names:
        cfg = _get_site_config(sname)
        if cfg:
            site_cfgs.append({
                "name": cfg["name"],
                "lat": cfg["lat"],
                "lon": cfg["lon"],
                "radius": cfg["radius"],
            })

    site_cfg = site_cfgs[0] if site_cfgs else None

    msg = ""
    msg_class = "message"

    def _read_float(name):
        try:
            v = (request.form.get(name) or "").strip()
            return float(v) if v else None
        except Exception:
            return None

    if request.method == "POST":
        require_csrf()
        action = (request.form.get("action") or "").strip()
        selfie_data = (request.form.get("selfie_data") or "").strip()

        if CLOCK_SELFIE_REQUIRED and action in ("in", "out") and not selfie_data:
            msg = "Selfie is required before clocking in or out."
            msg_class = "message error"
        else:
            lat_v = _read_float("lat")
            lon_v = _read_float("lon")
            acc_v = _read_float("acc")

            try:
                if lat_v is not None and lon_v is not None:
                    _validate_recent_clock_capture(request.form.get("geo_ts"), now)
                    lat_v, lon_v, acc_v = _sanitize_clock_geo(lat_v, lon_v, acc_v)
                ok_loc, cfg, dist_m = _validate_user_location(username, lat_v, lon_v, acc_v)

                if not ok_loc:
                    if (not _get_employee_sites(username)) and _get_active_locations():
                        msg = "No site is assigned to your account. Ask Admin to assign your site first."
                    elif not site_cfg and not cfg.get("radius"):
                        msg = "Location system is not configured. Ask Admin to create Locations and set your site."
                    elif lat_v is None or lon_v is None:
                        msg = "Location is required. Please allow location access and try again."
                    else:
                        msg = f"Outside site radius. Distance: {int(dist_m)}m (limit {int(cfg['radius'])}m) • Site: {cfg['name']}"
                    msg_class = "message error"
                else:
                    rows = work_sheet.get_all_values()

                    if action == "in":
                        open_shift = find_open_shift(rows, username)

                        if open_shift:
                            msg = "You are already clocked in."
                            msg_class = "message error"

                        elif has_any_row_today(rows, username, today_str):
                            msg = "You already completed your shift for today."
                            msg_class = "message error"

                        else:
                            selfie_url = _store_clock_selfie(selfie_data, username, "clock_in",
                                                             now) if CLOCK_SELFIE_REQUIRED else ""
                            cin = normalized_clock_in_time(now, early_access)

                            headers_now = work_sheet.row_values(1)
                            new_row = [username, today_str, cin, "", "", ""]

                            if headers_now and "Workplace_ID" in headers_now:
                                wp_idx = headers_now.index("Workplace_ID")
                                if len(new_row) <= wp_idx:
                                    new_row += [""] * (wp_idx + 1 - len(new_row))
                                new_row[wp_idx] = _session_workplace_id()

                            if headers_now and len(new_row) < len(headers_now):
                                new_row += [""] * (len(headers_now) - len(new_row))

                            _gs_write_with_retry(
                                lambda: work_sheet.append_row(new_row, value_input_option="USER_ENTERED"))

                            vals = work_sheet.get_all_values()
                            rownum = _find_workhours_row_by_user_date(vals, username, today_str)
                            if rownum:
                                headers = vals[0] if vals else []

                                def _col(name):
                                    return headers.index(name) + 1 if name in headers else None

                                import copy

                                updates = []
                                for k, v in [
                                    ("InLat", lat_v), ("InLon", lon_v), ("InAcc", acc_v),
                                    ("InSite", cfg.get("name", "")), ("InDistM", int(dist_m)),
                                    ("InSelfieURL", selfie_url), ("Workplace_ID", _session_workplace_id()),
                                ]:
                                    c = _col(k)
                                    if c:
                                        updates.append({
                                            "range": gspread.utils.rowcol_to_a1(rownum, c),
                                            "values": [["" if v is None else v]],
                                        })

                                if updates:
                                    _gs_write_with_retry(lambda: work_sheet.batch_update(copy.deepcopy(updates)))

                                if DB_MIGRATION_MODE:
                                    try:
                                        shift_date = datetime.strptime(today_str, "%Y-%m-%d").date()
                                        clock_in_dt = datetime.strptime(f"{today_str} {cin}", "%Y-%m-%d %H:%M:%S")

                                        db_row = WorkHour.query.filter(
                                            WorkHour.employee_email == username,
                                            WorkHour.date == shift_date,
                                            or_(WorkHour.workplace_id == _session_workplace_id(),
                                                WorkHour.workplace == _session_workplace_id()),
                                        ).order_by(WorkHour.id.desc()).first()

                                        if db_row:
                                            db_row.clock_in = clock_in_dt
                                            db_row.clock_out = None
                                            db_row.in_selfie_url = selfie_url
                                        else:
                                            db.session.add(
                                                WorkHour(
                                                    employee_email=username,
                                                    date=shift_date,
                                                    clock_in=clock_in_dt,
                                                    clock_out=None,
                                                    workplace=_session_workplace_id(),
                                                    workplace_id=_session_workplace_id(),
                                                    in_selfie_url=selfie_url,
                                                )
                                            )

                                        db.session.commit()
                                    except Exception:
                                        db.session.rollback()

                            if (not early_access) and (now.time() < CLOCKIN_EARLIEST):
                                msg = f"Clocked in successfully (counted from 08:00) • {cfg['name']} ({int(dist_m)}m)"
                            else:
                                msg = f"Clocked in successfully • {cfg['name']} ({int(dist_m)}m)"

                            return redirect(url_for("home"))

                    elif action == "out":
                        osf = find_open_shift(rows, username)

                        if not osf:
                            if has_any_row_today(rows, username, today_str):
                                msg = "You already clocked out today."
                            else:
                                msg = "No active shift found."
                            msg_class = "message error"

                        else:
                            selfie_url = _store_clock_selfie(selfie_data, username, "clock_out",
                                                             now) if CLOCK_SELFIE_REQUIRED else ""
                            i, d, t = osf
                            cin_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
                            raw_hours = max(0.0, (now - cin_dt).total_seconds() / 3600.0)
                            hours_rounded = _round_to_half_hour(_apply_unpaid_break(raw_hours))
                            pay = round(hours_rounded * float(rate), 2)

                            sheet_row = i + 1
                            cout = now.strftime("%H:%M:%S")

                            updates = [
                                {
                                    "range": f"{gspread.utils.rowcol_to_a1(sheet_row, COL_OUT + 1)}:{gspread.utils.rowcol_to_a1(sheet_row, COL_PAY + 1)}",
                                    "values": [[cout, hours_rounded, pay]],
                                }
                            ]

                            vals = work_sheet.get_all_values()
                            headers = vals[0] if vals else []

                            def _col(name):
                                return headers.index(name) + 1 if name in headers else None

                            for k, v in [
                                ("OutLat", lat_v), ("OutLon", lon_v), ("OutAcc", acc_v),
                                ("OutSite", cfg.get("name", "")), ("OutDistM", int(dist_m)),
                                ("OutSelfieURL", selfie_url),
                            ]:
                                c = _col(k)
                                if c:
                                    updates.append({
                                        "range": gspread.utils.rowcol_to_a1(sheet_row, c),
                                        "values": [["" if v is None else str(v)]],
                                    })

                            import copy
                            if updates:
                                _gs_write_with_retry(lambda: work_sheet.batch_update(copy.deepcopy(updates)))

                            if DB_MIGRATION_MODE:
                                try:
                                    shift_date = datetime.strptime(d, "%Y-%m-%d").date()
                                    clock_out_dt = datetime.strptime(f"{d} {cout}", "%Y-%m-%d %H:%M:%S")
                                    clock_in_dt_check = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S")

                                    if clock_out_dt < clock_in_dt_check:
                                        clock_out_dt = clock_out_dt + timedelta(days=1)

                                    db_row = WorkHour.query.filter(
                                        WorkHour.employee_email == username,
                                        WorkHour.date == shift_date,
                                        or_(WorkHour.workplace_id == _session_workplace_id(),
                                            WorkHour.workplace == _session_workplace_id()),
                                    ).order_by(WorkHour.id.desc()).first()

                                    if db_row:
                                        db_row.clock_out = clock_out_dt
                                        db_row.out_selfie_url = selfie_url
                                    else:
                                        db.session.add(
                                            WorkHour(
                                                employee_email=username,
                                                date=shift_date,
                                                clock_in=None,
                                                clock_out=clock_out_dt,
                                                workplace=_session_workplace_id(),
                                                workplace_id=_session_workplace_id(),
                                                out_selfie_url=selfie_url,
                                            )
                                        )

                                    db.session.commit()
                                except Exception:
                                    db.session.rollback()

                            msg = f"Clocked out successfully • {cfg['name']} ({int(dist_m)}m) • Total today: {hours_rounded:.2f}h"

                    else:
                        msg = "Invalid action."
                        msg_class = "message error"
            except Exception as e:
                if isinstance(e, RuntimeError):
                    msg = str(e) or "Unable to process selfie."
                    msg_class = "message error"
                else:
                    _logger.exception("Clock POST failed")
                    msg = "Internal error while saving. Please refresh and try again."
                    msg_class = "message error"

    # Active shift timer
    rows2 = get_workhours_rows()
    osf2 = find_open_shift(rows2, username)
    active_start_iso = ""
    active_start_label = ""
    if osf2:
        _, d, t = osf2
        try:
            start_dt = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
            active_start_iso = start_dt.isoformat()
            active_start_label = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    if active_start_iso:
        timer_html = f"""
            <div class="clockStatus clockStatusLive">Clocked in</div>
            <div class="timerBig" id="timerDisplay">00:00:00</div>
            <div class="clockHint">Started at {escape(active_start_label)}</div>
            <div class="timerSub">
              <span class="chip ok" id="otChip">Normal</span>
            </div>
            <script>
              (function() {{
                const startIso = "{escape(active_start_iso)}";
                const start = new Date(startIso);
                const el = document.getElementById("timerDisplay");
                function pad(n) {{ return String(n).padStart(2, "0"); }}
                function tick() {{
                  const now = new Date();
                  let diff = Math.floor((now - start) / 1000);
                  if (diff < 0) diff = 0;
                  const h = Math.floor(diff / 3600);
                  const m = Math.floor((diff % 3600) / 60);
                  const s = diff % 60;
                  el.textContent = pad(h) + ":" + pad(m) + ":" + pad(s);

                  const otEl = document.getElementById("otChip");
                  if (otEl) {{
                    const startedAtEight = (start.getHours() === 8 && start.getMinutes() === 0);
                    const overtime = startedAtEight && (diff >= 9 * 3600);
                    if (overtime) {{
                      otEl.textContent = "Overtime";
                      otEl.className = "chip warn";
                    }} else {{
                      otEl.textContent = "Normal";
                      otEl.className = "chip ok";
                    }}
                  }}
                }}
                tick(); setInterval(tick, 1000);
              }})();
            </script>
            """
    else:
        timer_html = f"""
            <div class="clockStatus clockStatusIdle">Not clocked in</div>
            <div class="timerBig">00:00:00</div>
            <div class="clockHint">Tap Clock In to start your shift.</div>
            """

    # Map config for front-end (if site configured)
    sites_json = json.dumps(site_cfgs)

    leaflet_tags = """
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin=""/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
    """

    company_name = str(get_company_settings().get("Company_Name") or "Main").strip() or "Main"
    msg_html = ""
    if msg:
        msg_state = "ok" if msg_class != "message error" else ""
        msg_html = f'<div class="clockInlineMsg {msg_state}">{escape(msg)}</div>'

    content = f"""
          {leaflet_tags}
          <style>
            .clockFlowWrap {{
      position: relative;
      max-width: 860px;
      margin: 0 auto;
      padding: 18px 0 10px;
    }}

    .clockInlineMsg {{
      margin: 0 0 18px;
      padding: 14px 16px;
      border-radius: 0 !important;
      border: 1px solid rgba(220,38,38,.16);
      background: linear-gradient(180deg, #fff5f5, #ffffff);
      color: #b91c1c;
      box-shadow: 0 10px 24px rgba(15,23,42,.08);
    }}

    .clockInlineMsg.ok {{
      border-color: rgba(22,163,74,.18);
      background: linear-gradient(180deg, #f0fdf4, #ffffff);
      color: #166534;
    }}

    .clockStep {{
      padding: 28px 22px 30px;
      border-radius: 0 !important;
      border: 1px solid rgba(68,130,195,.10);
      background:
        radial-gradient(circle at top right, rgba(68,130,195,.05), transparent 34%),
        radial-gradient(circle at top left, rgba(37,99,235,.05), transparent 30%),
        linear-gradient(180deg, #ffffff 0%, #f8fbfe 100%);
      box-shadow: 0 18px 42px rgba(15,23,42,.10);
    }}

    .clockStepLabel {{
      text-align: center;
      color: #2563eb;
      font-size: 17px;
      font-weight: 800;
      letter-spacing: .02em;
      margin-bottom: 12px;
    }}

    .clockHeroTitle {{
      margin: 0 0 12px;
      text-align: center;
      color: #1f2547;
      font-size: clamp(32px, 5vw, 44px);
      line-height: 1.06;
      font-weight: 900;
    }}

    .clockStageCard {{
      border-radius: 0 !important;
      border: 1px solid rgba(68,130,195,.10);
      overflow: hidden;
      background: #ffffff;
      box-shadow: 0 14px 34px rgba(15,23,42,.08);
    }}

    .clockSelfieStage {{
      position: relative;
      min-height: 320px;
      display: grid;
      place-items: center;
      padding: 24px;
      background:
        radial-gradient(circle at center, rgba(37,99,235,.05), transparent 52%),
        linear-gradient(180deg, #fcfcff, #f4f7ff);
    }}

    .clockSelfiePlaceholder {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 12px;
      color: #4338ca;
      opacity: .96;
      text-align: center;
    }}

    .clockSelfiePlaceholderIcon {{
      font-size: 76px;
      line-height: 1;
    }}

    .clockSelfiePlaceholderText {{
      font-size: 15px;
      color: #6f6c85;
      max-width: 420px;
    }}

    .clockSelfieVideo {{
      display: none;
      width: 100%;
      min-height: 320px;
      border-radius: 0 !important;
      object-fit: cover;
      background: #e9beef;
      border: 1px solid rgba(68,130,195,.10);
    }}

    .clockCaptureBar {{
      display: flex;
      gap: 12px;
      padding: 18px;
      align-items: center;
      background: linear-gradient(180deg, #ffffff, #f8f9ff);
      border-top: 1px solid rgba(68,130,195,.08);
    }}

    .clockPrimaryBtn,
    .clockPrimaryAction,
    .clockSecondaryAction,
    .clockGhostBtn {{
      border: 0;
      border-radius: 0 !important;
      font-weight: 800;
      transition: transform .18s ease, box-shadow .18s ease, opacity .18s ease, filter .18s ease;
    }}

    .clockPrimaryBtn,
    .clockPrimaryAction {{
      background: linear-gradient(90deg, #4f89c7, #3b74ad);
      color: #ffffff;
      box-shadow: 0 12px 26px rgba(79,70,229,.22);
    }}

    .clockPrimaryBtn:hover,
    .clockPrimaryAction:hover,
    .clockSecondaryAction:hover,
    .clockGhostBtn:hover {{
      transform: translateY(-1px);
      filter: brightness(1.03);
    }}

    .clockPrimaryBtn {{
      display: inline-flex;
      width: 100%;
      align-items: center;
      justify-content: center;
      gap: 14px;
      min-height: 72px;
      font-size: 20px;
    }}

    .clockPrimaryBtnArrow {{
      font-size: 34px;
      line-height: 1;
      margin-top: -1px;
    }}

    .clockGhostBtn {{
      min-width: 128px;
      min-height: 72px;
      padding: 0 22px;
      background: #f8f7ff;
      color: #3b74ad;
      border: 1px solid rgba(68,130,195,.12);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.8);
    }}

    .clockDistanceAlert {{
      margin: 20px auto 16px;
      max-width: 520px;
      padding: 14px 18px;
      border-radius: 0 !important;
      text-align: center;
      border: 1px solid rgba(220,38,38,.14);
      background: linear-gradient(180deg, #fff7f7, #ffffff);
      box-shadow: 0 10px 24px rgba(15,23,42,.06);
    }}

    .clockDistanceAlertTitle {{
      font-size: 18px;
      font-weight: 800;
      color: #dc2626;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }}

    .clockDistanceAlertMeta {{
      margin-top: 5px;
      font-size: 15px;
      color: #6f6c85;
    }}

    .clockDistanceAlert.is-ok {{
      border-color: rgba(22,163,74,.18);
      background: linear-gradient(180deg, #f0fdf4, #ffffff);
    }}

    .clockDistanceAlert.is-ok .clockDistanceAlertTitle {{
      color: #15803d;
    }}

    .clockDistanceAlert.is-ok .clockDistanceAlertMeta {{
      color: #166534;
    }}

    .clockMapShell {{
      border-radius: 0 !important;
      overflow: hidden;
      border: 1px solid rgba(68,130,195,.10);
      box-shadow: 0 14px 30px rgba(15,23,42,.08);
      background: #ffffff;
    }}

    .clockFooterNote {{
      margin: 18px 6px 0;
      text-align: center;
      color: #6f6c85;
      font-size: 15px;
    }}

    .clockFooterNote strong {{
      color: #1f2a37;
    }}

    .clockHidden {{
      display: none !important;
    }}

    .clockStepTwo {{
      display: none;
      text-align: center;
      padding-top: 10px;
    }}

    .clockCapturedRow {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: #1f2a37;
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 22px;
    }}

    .clockCapturedIcon {{
      width: 32px;
      height: 32px;
      display: inline-grid;
      place-items: center;
      border-radius: 0 !important;
      background: rgba(68,130,195,.10);
      color: #3b74ad;
      font-size: 18px;
      font-weight: 900;
    }}

    .clockFinalSelfie {{
      width: min(220px, 52vw);
      aspect-ratio: 1 / 1;
      margin: 0 auto 28px;
      border-radius: 0 !important;
      object-fit: cover;
      background: #ffffff;
      border: 1px solid rgba(68,130,195,.10);
      box-shadow: 0 14px 30px rgba(15,23,42,.10);
      display: none;
    }}

    .clockTimerStage {{
      margin: 0 auto 24px;
      max-width: 540px;
      padding: 8px 0 0;
    }}

    .clockTimerStage .clockStatusIdle,
    .clockTimerStage .clockStatusLive {{
      background: transparent !important;
      color: #2563eb !important;
      font-size: 16px !important;
      font-weight: 700 !important;
      margin-bottom: 10px !important;
      padding: 0 !important;
      border: 0 !important;
      box-shadow: none !important;
    }}

    .clockTimerStage .timerBig {{
      font-size: clamp(54px, 11vw, 80px) !important;
      line-height: 1 !important;
      letter-spacing: 1.5px !important;
      color: #1f2a37 !important;
      margin: 0 !important;
      font-weight: 800 !important;
    }}

    .clockTimerStage .clockHint {{
      margin-top: 12px !important;
      color: #6f6c85 !important;
      font-size: 14px !important;
    }}

    .clockTimerStage .timerSub {{
      margin-top: 12px !important;
    }}

    .clockActionStack {{
      max-width: 560px;
      margin: 0 auto;
      display: grid;
      gap: 14px;
    }}

    .clockPrimaryAction,
    .clockSecondaryAction {{
      width: 100%;
      min-height: 82px;
      font-size: clamp(22px, 4vw, 28px);
      letter-spacing: .04em;
      text-transform: uppercase;
    }}

    .clockSecondaryAction {{
      background: #ffffff;
      color: #2563eb;
      border: 1px solid rgba(37,99,235,.14);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.78);
    }}

    .clockSecondaryAction[disabled],
    .clockGhostBtn[disabled] {{
      opacity: .5;
      cursor: not-allowed;
      transform: none;
    }}

    .clockTextLink {{
      display: inline-block;
      margin-top: 18px;
      color: #3b74ad;
      font-weight: 700;
      text-decoration: none;
    }}

    .clockBackLink {{
      margin-top: 16px;
      background: transparent;
      border: 0;
      color: #3b74ad;
      font-weight: 700;
      cursor: pointer;
    }}

    .clockMetaText {{
      margin-top: 14px;
      color: #6f6c85;
      font-size: 14px;
      text-align: center;
    }}

    @media (max-width: 640px) {{
      .clockFlowWrap {{ padding-top: 10px; }}
      .clockStep {{
        padding: 22px 14px 24px;
        border-radius: 0 !important;
      }}
      .clockHeroTitle {{
        font-size: 28px;
        margin-bottom: 16px;
      }}
      .clockSelfieStage {{
        min-height: 240px;
        padding: 16px;
      }}
      .clockSelfieVideo {{
        min-height: 240px;
      }}
      .clockCaptureBar {{
        flex-direction: column;
      }}
      .clockGhostBtn {{
        width: 100%;
        min-height: 58px;
      }}
      .clockPrimaryBtn {{
        min-height: 62px;
        font-size: 18px;
      }}
      .clockPrimaryAction,
      .clockSecondaryAction {{
        min-height: 72px;
        font-size: 20px;
      }}
    }} .clockFlowWrap {{ padding-top: 10px; }} .clockStep {{ padding: 22px 14px 24px; border-radius: 0 !important; }} .clockHeroTitle {{ font-size: 28px; margin-bottom: 20px; }} .clockSelfieStage {{ min-height: 240px; padding: 16px; }} .clockSelfieVideo {{ min-height: 240px; }} .clockCaptureBar {{ flex-direction: column; }} .clockGhostBtn {{ width: 100%; min-height: 58px; }} .clockPrimaryBtn {{ min-height: 62px; font-size: 18px; }} .clockPrimaryAction, .clockSecondaryAction {{ min-height: 72px; font-size: 20px; }} }}

          </style>

          {page_back_button("/", "Back to dashboard")}

          <div class="clockFlowWrap">
            {msg_html}

            <div class="clockStep" id="clockStepOne">
              <div class="clockStepLabel">Step 1 of 2</div>
              <h1 class="clockHeroTitle">Take a selfie to continue</h1>

              <div class="clockStageCard">
                <div class="clockSelfieStage">
                  <div class="clockSelfiePlaceholder" id="clockSelfiePlaceholder">
                    <div class="clockSelfiePlaceholderIcon">&#128247;</div>
                    <div class="clockSelfiePlaceholderText">Open the camera and capture a clear front-facing selfie.</div>
                  </div>
                  <video id="selfieVideo" class="clockSelfieVideo" autoplay playsinline muted></video>
                </div>
                <div class="clockCaptureBar">
                  <button class="clockPrimaryBtn" id="takeSelfieBtn" type="button">
                    <span class="clockPrimaryBtnText">Take Selfie</span>
                    <span class="clockPrimaryBtnArrow">&#8250;</span>
                  </button>
                  <button class="clockGhostBtn" id="retakeSelfieBtn" type="button" disabled>Retake</button>
                </div>
              </div>

              <div class="clockMetaText" id="selfieStatus">Tap Take Selfie to open the camera.</div>
              <div id="geoStatus" class="clockHidden" aria-live="polite"></div>

              <div class="clockDistanceAlert clockHidden" id="geoAlert">
  <div class="clockDistanceAlertTitle" id="geoAlertTitle">📍 Checking your location</div>
  <div class="clockDistanceAlertMeta" id="geoAlertMeta">Waiting for location permission…</div>
</div>

              <div class="clockMapShell">
                <div id="map" style="height:280px; min-height:280px;"></div>
              </div>

              <div class="clockFooterNote" id="clockFooterNote">You'll be able to <strong>clock in</strong> after taking a selfie.</div>
            </div>

            <div class="clockStep clockStepTwo" id="clockStepTwo">
              <div class="clockStepLabel">Step 2 of 2</div>
              <div class="clockCapturedRow">
                <span class="clockCapturedIcon">✓</span>
                <span>Selfie captured</span>
              </div>

              <img id="selfiePreviewFinal" class="clockFinalSelfie" alt="Selfie preview">
              <canvas id="selfieCanvas" class="clockHidden"></canvas>

              <div class="clockTimerStage">
                {timer_html}
              </div>

              <form method="POST" id="geoClockForm" class="clockActionStack">
                <input type="hidden" name="csrf" value="{escape(csrf)}">
                <input type="hidden" name="action" id="geoAction" value="">
                <input type="hidden" name="lat" id="geoLat" value="">
                <input type="hidden" name="lon" id="geoLon" value="">
                <input type="hidden" name="acc" id="geoAcc" value="">
                <input type="hidden" name="geo_ts" id="geoTs" value="">
                <input type="hidden" name="selfie_data" id="selfieData" value="">

                <button class="clockPrimaryAction" id="btnClockIn" type="button">Clock In</button>
                <button class="clockSecondaryAction" id="btnClockOut" type="button">Clock Out</button>
              </form>

              <a href="/my-times" class="clockTextLink">View time logs</a>
              <div><button class="clockBackLink" id="backToStepOne" type="button">Retake selfie</button></div>
            </div>
          </div>

          <script>
            (function() {{
              const SITES = {sites_json};
              const statusEl = document.getElementById("geoStatus");
              const form = document.getElementById("geoClockForm");
              const act = document.getElementById("geoAction");
              const latEl = document.getElementById("geoLat");
              const lonEl = document.getElementById("geoLon");
              const accEl = document.getElementById("geoAcc");
              const geoTsEl = document.getElementById("geoTs");

              const btnIn = document.getElementById("btnClockIn");
              const btnOut = document.getElementById("btnClockOut");
              const selfieDataEl = document.getElementById("selfieData");
              const selfieVideo = document.getElementById("selfieVideo");
              const selfieCanvas = document.getElementById("selfieCanvas");
              const selfieStatus = document.getElementById("selfieStatus");
              const takeSelfieBtn = document.getElementById("takeSelfieBtn");
              const takeSelfieBtnText = takeSelfieBtn.querySelector(".clockPrimaryBtnText");
              const retakeSelfieBtn = document.getElementById("retakeSelfieBtn");
              const backToStepOneBtn = document.getElementById("backToStepOne");
              const stepOne = document.getElementById("clockStepOne");
              const stepTwo = document.getElementById("clockStepTwo");
              const selfiePlaceholder = document.getElementById("clockSelfiePlaceholder");
              const selfiePreviewFinal = document.getElementById("selfiePreviewFinal");
              const geoAlert = document.getElementById("geoAlert");
              const geoAlertTitle = document.getElementById("geoAlertTitle");
              const geoAlertMeta = document.getElementById("geoAlertMeta");
              const footerNote = document.getElementById("clockFooterNote");
              let selfieStream = null;

              function setDisabled(v) {{
                btnIn.disabled = v;
                btnOut.disabled = v;
              }}

              function syncSteps() {{
                const hasSelfie = !!selfieDataEl.value;
                stepOne.style.display = hasSelfie ? "none" : "block";
                stepTwo.style.display = hasSelfie ? "block" : "none";
                if (hasSelfie) {{
                  selfiePreviewFinal.src = selfieDataEl.value;
                  selfiePreviewFinal.style.display = "block";
                }} else {{
                  selfiePreviewFinal.src = "";
                  selfiePreviewFinal.style.display = "none";
                }}
              }}

              function updateCaptureUi(cameraLive) {{
                selfiePlaceholder.style.display = cameraLive ? "none" : "flex";
                selfieVideo.style.display = cameraLive ? "block" : "none";
                takeSelfieBtnText.textContent = cameraLive ? "Capture Selfie" : "Take Selfie";
              }}

              function stopSelfieCamera() {{
                if (selfieStream) {{
                  selfieStream.getTracks().forEach(track => track.stop());
                  selfieStream = null;
                }}
                selfieVideo.srcObject = null;
                updateCaptureUi(false);
              }}

              async function startSelfieCamera() {{
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{
                  selfieStatus.textContent = "Camera preview is not supported on this device/browser.";
                  return;
                }}
                try {{
                  stopSelfieCamera();
                  selfieStream = await navigator.mediaDevices.getUserMedia({{ video: {{ facingMode: "user", width: {{ ideal: 1280 }}, height: {{ ideal: 720 }} }}, audio: false }});
                  selfieVideo.srcObject = selfieStream;
                  if (selfieVideo.play) {{
                    try {{ await selfieVideo.play(); }} catch (e) {{}}
                  }}
                  updateCaptureUi(true);
                  selfieStatus.textContent = "Camera ready. Tap capture when you're centered.";
                }} catch (err) {{
                  console.log(err);
                  selfieStatus.textContent = "Could not open camera. Please allow camera permission and try again.";
                }}
              }}

              function setSelfieData(dataUrl) {{
                selfieDataEl.value = dataUrl || "";
                if (dataUrl) {{
                  retakeSelfieBtn.disabled = false;
                  selfieStatus.textContent = "Selfie captured.";
                  footerNote.innerHTML = "Selfie captured. You can now <strong>clock in</strong>.";
                }} else {{
                  retakeSelfieBtn.disabled = true;
                  selfieStatus.textContent = "Tap Take Selfie to open the camera.";
                  footerNote.innerHTML = "You'll be able to <strong>clock in</strong> after taking a selfie.";
                }}
                syncSteps();
              }}

              function captureSelfieFrame() {{
                if (!selfieVideo || !selfieVideo.videoWidth || !selfieVideo.videoHeight) {{
                  selfieStatus.textContent = "Open the camera first, then capture your selfie.";
                  return;
                }}
                const maxW = 960;
                const scale = Math.min(1, maxW / selfieVideo.videoWidth);
                const width = Math.max(320, Math.round(selfieVideo.videoWidth * scale));
                const height = Math.max(240, Math.round(selfieVideo.videoHeight * scale));
                selfieCanvas.width = width;
                selfieCanvas.height = height;
                const ctx = selfieCanvas.getContext("2d");
                ctx.drawImage(selfieVideo, 0, 0, width, height);
                const dataUrl = selfieCanvas.toDataURL("image/jpeg", 0.88);
                setSelfieData(dataUrl);
                stopSelfieCamera();
              }}

              let map = null;
              let youMarker = null;

                            function initMap() {{
                const hasSites = Array.isArray(SITES) && SITES.length > 0;
                const start = hasSites ? [SITES[0].lat, SITES[0].lon] : [51.505, -0.09];

                map = L.map("map", {{ zoomControl: true }}).setView(start, hasSites ? 16 : 5);

                L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
                  maxZoom: 19,
                  attribution: "&copy; OpenStreetMap"
                }}).addTo(map);

                if (hasSites) {{
                  const bounds = [];
                  for (const site of SITES) {{
                    L.marker([site.lat, site.lon]).addTo(map).bindPopup(site.name);
                    L.circle([site.lat, site.lon], {{ radius: site.radius }}).addTo(map);
                    bounds.push([site.lat, site.lon]);
                  }}
                  if (bounds.length > 1) {{
                    map.fitBounds(bounds, {{ padding: [30, 30] }});
                  }}
                }}
              }}

              function haversineMeters(lat1, lon1, lat2, lon2) {{
                const R = 6371000;
                const toRad = (x) => x * Math.PI / 180;
                const dLat = toRad(lat2 - lat1);
                const dLon = toRad(lon2 - lon1);
                const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                          Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
                          Math.sin(dLon / 2) * Math.sin(dLon / 2);
                const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
                return R * c;
              }}
                            function getBestSiteMatch(lat, lon) {{
                if (!Array.isArray(SITES) || !SITES.length) return null;

                let best = null;

                for (const site of SITES) {{
                  const dist = haversineMeters(lat, lon, site.lat, site.lon);
                  const ok = dist <= site.radius;

                  if (!best) {{
                    best = {{ site, dist, ok }};
                    continue;
                  }}

                  if (ok && (!best.ok || dist < best.dist)) {{
                    best = {{ site, dist, ok }};
                  }} else if (!best.ok && dist < best.dist) {{
                    best = {{ site, dist, ok }};
                  }}
                }}

                return best;
              }}

                function updateStatus(lat, lon, acc) {{
  geoAlert.classList.remove("clockHidden");

  const best = getBestSiteMatch(lat, lon);

  if (!best) {{
    statusEl.textContent = "Location captured (no site configured).";
    geoAlert.className = "clockDistanceAlert is-ok";
    geoAlertTitle.textContent = "📍 Location captured";
    geoAlertMeta.textContent = "No active site radius is configured for this account.";
    return;
  }}

  const site = best.site;
  const dist = best.dist;
  const ok = best.ok;

  statusEl.textContent = ok
    ? `Location OK: ${{site.name}} (${{Math.round(dist)}}m)`
    : `Outside radius: ${{Math.round(dist)}}m (limit ${{Math.round(site.radius)}}m) • Site: ${{site.name}}`;

  geoAlert.className = `clockDistanceAlert ${{ok ? 'is-ok' : 'is-error'}}`;
  geoAlertTitle.textContent = ok
    ? "📍 You are at the correct site"
    : "📍 You are too far from the site";

  geoAlertMeta.textContent = `Distance: ${{Math.round(dist)}}m (limit ${{Math.round(site.radius)}}m) • Site: ${{site.name}}`;
}}

              function updateYouMarker(lat, lon) {{
                if (!map) return;
                if (!youMarker) {{
                  youMarker = L.marker([lat, lon]).addTo(map);
                }} else {{
                  youMarker.setLatLng([lat, lon]);
                }}
              }}

              function requestLocationAndSubmit(actionValue) {{
                if (!selfieDataEl.value) {{
                  syncSteps();
                  selfieStatus.textContent = "Selfie required before clocking in or out.";
                  return;
                }}

                stopSelfieCamera();

                if (!navigator.geolocation) {{
                  alert("Geolocation is not supported on this device/browser.");
                  return;
                }}

                setDisabled(true);
                statusEl.textContent = "Getting your location…";

                navigator.geolocation.getCurrentPosition((pos) => {{
                  const lat = pos.coords.latitude;
                  const lon = pos.coords.longitude;
                  const acc = pos.coords.accuracy;

                  latEl.value = lat;
                  lonEl.value = lon;
                  accEl.value = acc;
                  geoTsEl.value = String(Date.now());

                  updateStatus(lat, lon, acc);
                  updateYouMarker(lat, lon);

                  act.value = actionValue;
                  form.submit();
                }}, (err) => {{
                  console.log(err);
                  alert("Location is required to clock in or out. Please allow location permission and try again.");
                  statusEl.textContent = "Location required. Please allow permission.";
                  setDisabled(false);
                }}, {{ enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }});
              }}

              initMap();

              if (navigator.geolocation) {{
                navigator.geolocation.getCurrentPosition((pos) => {{
                  const lat = pos.coords.latitude;
                  const lon = pos.coords.longitude;
                  updateStatus(lat, lon, pos.coords.accuracy);
                  updateYouMarker(lat, lon);
                }}, () => {{
                  geoAlert.className = "clockDistanceAlert is-error";
                  geoAlertTitle.textContent = "📍 Location permission needed";
                  geoAlertMeta.textContent = "Allow location access so we can verify your site.";
                }}, {{ enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }});
              }}

              takeSelfieBtn.addEventListener("click", async () => {{
                const hasLiveCamera = !!(selfieStream || (selfieVideo && selfieVideo.srcObject));
                if (!hasLiveCamera) {{
                  await startSelfieCamera();
                  return;
                }}
                captureSelfieFrame();
              }});

              retakeSelfieBtn.addEventListener("click", async () => {{
                setSelfieData("");
                await startSelfieCamera();
              }});

              backToStepOneBtn.addEventListener("click", async () => {{
                setSelfieData("");
                await startSelfieCamera();
              }});

              window.addEventListener("pagehide", stopSelfieCamera);
              window.addEventListener("beforeunload", stopSelfieCamera);
              document.addEventListener("visibilitychange", () => {{
                if (document.hidden) stopSelfieCamera();
              }});

              btnIn.addEventListener("click", () => requestLocationAndSubmit("in"));
              btnOut.addEventListener("click", () => requestLocationAndSubmit("out"));

              updateCaptureUi(false);
syncSteps();
            }})();
          </script>
        """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("clock", role, content))