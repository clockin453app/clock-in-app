def admin_locations_deactivate_impl(core):
    require_admin = core["require_admin"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    locations_sheet = core["locations_sheet"]
    redirect = core["redirect"]
    _find_location_row_by_name = core["_find_location_row_by_name"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    _session_workplace_id = core["_session_workplace_id"]
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

    if not locations_sheet or not name:
        return redirect("/admin/locations")

    rownum = _find_location_row_by_name(name)
    if rownum:
        try:
            locations_sheet.update_cell(rownum, 5, "FALSE")

            if DB_MIGRATION_MODE:
                try:
                    wp = _session_workplace_id()
                    allowed_wps = set(_workplace_ids_for_read(wp))
                    db_row = Location.query.filter_by(workplace_id=wp, site_name=name).first()
                    if db_row:
                        db_row.active = "FALSE"
                        db.session.commit()
                except Exception:
                    db.session.rollback()
        except Exception:
            pass

    actor = session.get("username", "admin")
    log_audit("LOCATIONS_DEACTIVATE", actor=actor, username="", date_str="", details=name)
    return redirect("/admin/locations")
