def admin_locations_save_impl(core):
    require_admin = core["require_admin"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    locations_sheet = core["locations_sheet"]
    redirect = core["redirect"]
    _ensure_locations_headers = core["_ensure_locations_headers"]
    _find_location_row_by_name = core["_find_location_row_by_name"]
    _session_workplace_id = core["_session_workplace_id"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    Location = core["Location"]
    db = core["db"]
    session = core["session"]
    log_audit = core["log_audit"]


    gate = require_admin()
    if gate:
        return gate
    require_csrf()

    name = (request.form.get("name") or "").strip()
    orig = (request.form.get("orig_name") or "").strip()
    lat = (request.form.get("lat") or "").strip()
    lon = (request.form.get("lon") or "").strip()
    rad = (request.form.get("rad") or "").strip()
    active = "TRUE" if (request.form.get("active") == "yes") else "FALSE"

    if not locations_sheet or not name:
        return redirect("/admin/locations")

    try:
        float(lat);
        float(lon);
        float(rad)
    except Exception:
        return redirect("/admin/locations")

    _ensure_locations_headers()

    rownum = _find_location_row_by_name(orig or name)
    row = [name, lat, lon, rad, active, _session_workplace_id()]
    try:
        if rownum:
            locations_sheet.update(f"A{rownum}:F{rownum}", [row])
        else:
            locations_sheet.append_row(row)
    except Exception:
        pass

    if DB_MIGRATION_MODE:
        try:
            wp = _session_workplace_id()
            allowed_wps = set(_workplace_ids_for_read(wp))

            db_row = Location.query.filter_by(
                workplace_id=wp,
                site_name=(orig or name)
            ).first()

            if not db_row:
                db_row = Location.query.filter_by(
                    workplace_id=wp,
                    site_name=name
                ).first()

            if db_row:
                db_row.site_name = name
                db_row.lat = float(lat)
                db_row.lon = float(lon)
                db_row.radius_meters = int(float(rad))
                db_row.active = active
            else:
                db.session.add(
                    Location(
                        site_name=name,
                        lat=float(lat),
                        lon=float(lon),
                        radius_meters=int(float(rad)),
                        active=active,
                        workplace_id=wp,
                    )
                )

            db.session.commit()
        except Exception:
            db.session.rollback()

    actor = session.get("username", "admin")
    log_audit("LOCATIONS_SAVE", actor=actor, username="", date_str="",
              details=f"{name} {lat},{lon} r={rad} active={active}")
    return redirect("/admin/locations")
