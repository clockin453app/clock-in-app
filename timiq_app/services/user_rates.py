def get_user_rate_data(
    username: str,
    session_workplace_id: str,
    workplace_ids_for_read,
    db_migration_mode: bool,
    employee_model,
    employees_sheet,
    session_obj,
    safe_float_func,
):
    current_wp = session_workplace_id
    allowed_wps = set(workplace_ids_for_read(current_wp))
    u = (username or "").strip()

    if db_migration_mode:
        try:
            rec = employee_model.query.filter_by(username=u, workplace_id=current_wp).first()
            if not rec:
                rec = employee_model.query.filter_by(email=u, workplace_id=current_wp).first()

            if rec is not None:
                rate_val = getattr(rec, "rate", None)
                if rate_val not in (None, ""):
                    return safe_float_func(rate_val, 0.0)
        except Exception:
            pass

    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return safe_float_func(session_obj.get("rate", 0), 0.0)

        headers = vals[0]
        if "Username" not in headers:
            return safe_float_func(session_obj.get("rate", 0), 0.0)

        ucol = headers.index("Username")
        rcol = headers.index("Rate") if "Rate" in headers else None
        wpcol = headers.index("Workplace_ID") if "Workplace_ID" in headers else None

        for r in vals[1:]:
            if len(r) <= ucol:
                continue
            if (r[ucol] or "").strip() != u:
                continue

            if wpcol is not None:
                row_wp = (r[wpcol] if len(r) > wpcol else "").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

            if rcol is not None and rcol < len(r):
                return safe_float_func(r[rcol], default=0.0)

        return safe_float_func(session_obj.get("rate", 0), 0.0)
    except Exception:
        return safe_float_func(session_obj.get("rate", 0), 0.0)