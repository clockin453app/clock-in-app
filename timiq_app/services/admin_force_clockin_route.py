def admin_force_clockin_impl(core):
    require_admin = core["require_admin"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    redirect = core["redirect"]
    get_workhours_rows = core["get_workhours_rows"]
    find_open_shift = core["find_open_shift"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    datetime = core["datetime"]
    _workhour_query_for_user = core["_workhour_query_for_user"]
    _session_workplace_id = core["_session_workplace_id"]
    WorkHour = core["WorkHour"]
    db = core["db"]
    make_response = core["make_response"]
    work_sheet = core["work_sheet"]
    gspread = core["gspread"]
    _find_workhours_row_by_user_date = core["_find_workhours_row_by_user_date"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]
    COL_HOURS = core["COL_HOURS"]
    COL_PAY = core["COL_PAY"]
    session = core["session"]
    log_audit = core["log_audit"]
    _get_canonical_workhour_for_day = core["_get_canonical_workhour_for_day"]
    _get_active_locations = core["_get_active_locations"]
    _ensure_workhours_geo_headers = core["_ensure_workhours_geo_headers"]


    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    username = (request.form.get("user") or "").strip()
    in_time = (request.form.get("in_time") or "").strip()
    date_str = (request.form.get("date") or "").strip()
    site_name = (request.form.get("site") or "").strip()

    if not username or not in_time or not date_str or not site_name:
        return redirect(request.referrer or "/admin")

    if len(in_time.split(":")) == 2:
        in_time = in_time + ":00"

    try:
        active_sites = []
        for rec in (_get_active_locations() or []):
            nm = str(rec.get("name") or rec.get("SiteName") or rec.get("site") or "").strip()
            if nm:
                active_sites.append(nm)

        if active_sites and site_name.lower() not in {s.lower() for s in active_sites}:
            return make_response("Invalid site selected.", 400)
    except Exception:
        pass

    rows = get_workhours_rows()
    if find_open_shift(rows, username):
        return redirect(request.referrer or "/admin")

    if DB_MIGRATION_MODE:
        try:
            shift_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            clock_in_dt = datetime.strptime(f"{date_str} {in_time}", "%Y-%m-%d %H:%M:%S")
            db_row = _get_canonical_workhour_for_day(
                username,
                shift_date,
                _session_workplace_id(),
            )

            db_row.clock_in = clock_in_dt
            db_row.clock_out = None
            db_row.hours = None
            db_row.pay = None
            db_row.in_site = site_name
            db_row.out_site = None
            db_row.workplace = _session_workplace_id()
            db_row.workplace_id = _session_workplace_id()
            db.session.commit()


        except Exception as e:
            db.session.rollback()
            return make_response(f"Could not force clock in: {e}", 500)
    else:
        _ensure_workhours_geo_headers()
        try:
            vals = work_sheet.get_all_values()
            headers = vals[0] if vals else []
            rownum = _find_workhours_row_by_user_date(vals, username, date_str)

            wp_col = (headers.index("Workplace_ID") + 1) if ("Workplace_ID" in headers) else None
            in_site_col = (headers.index("InSite") + 1) if ("InSite" in headers) else None
            out_site_col = (headers.index("OutSite") + 1) if ("OutSite" in headers) else None

            if rownum:
                work_sheet.update_cell(rownum, COL_IN + 1, in_time)
                work_sheet.update_cell(rownum, COL_OUT + 1, "")
                work_sheet.update_cell(rownum, COL_HOURS + 1, "")
                work_sheet.update_cell(rownum, COL_PAY + 1, "")

                if wp_col:
                    work_sheet.update_cell(rownum, wp_col, _session_workplace_id())
                if in_site_col:
                    work_sheet.update_cell(rownum, in_site_col, site_name)
                if out_site_col:
                    work_sheet.update_cell(rownum, out_site_col, "")
            else:
                new_row = [username, date_str, in_time, "", "", ""]

                if headers and "Workplace_ID" in headers:
                    wp_idx = headers.index("Workplace_ID")
                    if len(new_row) <= wp_idx:
                        new_row += [""] * (wp_idx + 1 - len(new_row))
                    new_row[wp_idx] = _session_workplace_id()

                if headers and "InSite" in headers:
                    in_site_idx = headers.index("InSite")
                    if len(new_row) <= in_site_idx:
                        new_row += [""] * (in_site_idx + 1 - len(new_row))
                    new_row[in_site_idx] = site_name

                if headers and "OutSite" in headers:
                    out_site_idx = headers.index("OutSite")
                    if len(new_row) <= out_site_idx:
                        new_row += [""] * (out_site_idx + 1 - len(new_row))
                    new_row[out_site_idx] = ""

                if headers and len(new_row) < len(headers):
                    new_row += [""] * (len(headers) - len(new_row))

                work_sheet.append_row(new_row)
        except Exception as e:
            return make_response(f"Could not force clock in: {e}", 500)

    actor = session.get("username", "admin")
    log_audit("FORCE_CLOCK_IN", actor=actor, username=username, date_str=date_str, details=f"in={in_time}, site={site_name}")
    return redirect(request.referrer or "/admin")
