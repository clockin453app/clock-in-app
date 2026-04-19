def admin_mark_paid_impl(core):
    require_admin = core["require_admin"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    redirect = core["redirect"]
    safe_float = core["safe_float"]
    session = core["session"]
    _append_paid_record_safe = core["_append_paid_record_safe"]

    gate = require_admin()
    if gate:
        return gate


    try:
        require_csrf()
    except Exception:
        return redirect(request.referrer or "/admin/payroll")

    try:
        week_start = (request.form.get("week_start") or "").strip()
        week_end = (request.form.get("week_end") or "").strip()
        username = (request.form.get("user") or request.form.get("username") or "").strip()

        gross = safe_float(request.form.get("gross", "0") or "0", 0.0)
        tax = safe_float(request.form.get("tax", "0") or "0", 0.0)
        net = safe_float(request.form.get("net", "0") or "0", 0.0)

        payment_mode = (request.form.get("payment_mode") or "net").strip().lower()
        display_tax = safe_float(request.form.get("display_tax", "") or "", tax)
        display_net = safe_float(request.form.get("display_net", "") or "", net)

        paid_by = session.get("username", "admin")

        if week_start and week_end and username:
            _append_paid_record_safe(
                week_start,
                week_end,
                username,
                gross,
                tax,
                net,
                paid_by,
                payment_mode=payment_mode,
                display_tax=display_tax,
                display_net=display_net,
            )
    except Exception:
        pass

    return redirect(request.referrer or "/admin/payroll")
