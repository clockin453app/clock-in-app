from decimal import Decimal


def admin_payroll_status_impl(core):
    require_admin = core["require_admin"]
    require_csrf = core["require_csrf"]
    request = core["request"]
    redirect = core["redirect"]
    session = core["session"]

    _find_employee_record = core["_find_employee_record"]
    is_password_valid = core["is_password_valid"]

    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    PayrollReport = core["PayrollReport"]
    db = core["db"]

    datetime = core["datetime"]
    date = core["date"]
    TZ = core["TZ"]

    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    get_payroll_rows = core["get_payroll_rows"]
    payroll_sheet = core["payroll_sheet"]
    gspread = core["gspread"]
    safe_float = core["safe_float"]
    log_audit = core["log_audit"]

    gate = require_admin()
    if gate:
        return gate

    try:
        require_csrf()
    except Exception:
        return redirect(request.referrer or "/admin/payroll")

    action = (request.form.get("action") or "").strip().lower()
    week_start_raw = (request.form.get("week_start") or "").strip()
    week_end_raw = (request.form.get("week_end") or "").strip()
    username = (request.form.get("user") or request.form.get("username") or "").strip()

    gross = safe_float(request.form.get("gross", "0") or "0", 0.0)
    tax = safe_float(request.form.get("tax", "0") or "0", 0.0)
    net = safe_float(request.form.get("net", "0") or "0", 0.0)

    actor = session.get("username", "admin")
    actor_role = (session.get("role") or "").strip().lower()
    wp = _session_workplace_id()
    unlock_password = (request.form.get("unlock_password") or "").strip()

    if action not in ("approve", "unlock"):
        return redirect(request.referrer or "/admin/payroll")

    if not week_start_raw or not week_end_raw or not username:
        return redirect(request.referrer or "/admin/payroll")

    try:
        week_start = date.fromisoformat(week_start_raw)
        week_end = date.fromisoformat(week_end_raw)
    except Exception:
        return redirect(request.referrer or "/admin/payroll")

    def status_is_paid(value):
        return str(value or "").strip().lower() in ("true", "1", "yes", "paid", "locked")

    def status_is_locked(value):
        return str(value or "").strip().lower() in ("approved", "true", "1", "yes", "paid", "locked")

    def update_sheet_status(new_status, paid_at_value="", paid_by_value=""):
        try:
            vals = get_payroll_rows()
            headers = vals[0] if vals else []

            target_headers = [
                "WeekStart", "WeekEnd", "Username",
                "Gross", "Tax", "Net",
                "DisplayTax", "DisplayNet", "PaymentMode",
                "PaidAt", "PaidBy", "Paid", "Workplace_ID",
            ]

            if not headers:
                payroll_sheet.append_row(target_headers)
                headers = target_headers
                vals = [headers]

            def idx(name):
                return headers.index(name) if name in headers else None

            i_ws = idx("WeekStart")
            i_we = idx("WeekEnd")
            i_u = idx("Username")
            i_wp = idx("Workplace_ID")

            rownum = None
            for n, row in enumerate(vals[1:], start=2):
                row_ws = (row[i_ws] if i_ws is not None and i_ws < len(row) else "").strip()
                row_we = (row[i_we] if i_we is not None and i_we < len(row) else "").strip()
                row_u = (row[i_u] if i_u is not None and i_u < len(row) else "").strip()
                row_wp = (row[i_wp] if i_wp is not None and i_wp < len(row) else "").strip() or "default"

                if row_ws == week_start_raw and row_we == week_end_raw and row_u == username and row_wp == wp:
                    rownum = n
                    break

            if rownum is None:
                row = [""] * len(target_headers)

                def set_target(name, value):
                    if name in target_headers:
                        row[target_headers.index(name)] = value

                set_target("WeekStart", week_start_raw)
                set_target("WeekEnd", week_end_raw)
                set_target("Username", username)
                set_target("Gross", str(round(gross, 2)))
                set_target("Tax", str(round(tax, 2)))
                set_target("Net", str(round(net, 2)))
                set_target("DisplayTax", str(round(tax, 2)))
                set_target("DisplayNet", str(round(net, 2)))
                set_target("PaymentMode", "net")
                set_target("PaidAt", paid_at_value)
                set_target("PaidBy", paid_by_value)
                set_target("Paid", new_status)
                set_target("Workplace_ID", wp)

                payroll_sheet.append_row(row)
                return

            updates = []

            def add_update(col_name, value):
                if col_name not in headers:
                    return
                col = headers.index(col_name) + 1
                updates.append({
                    "range": gspread.utils.rowcol_to_a1(rownum, col),
                    "values": [[value]],
                })

            add_update("Gross", str(round(gross, 2)))
            add_update("Tax", str(round(tax, 2)))
            add_update("Net", str(round(net, 2)))
            add_update("DisplayTax", str(round(tax, 2)))
            add_update("DisplayNet", str(round(net, 2)))
            add_update("PaymentMode", "net")
            add_update("PaidAt", paid_at_value)
            add_update("PaidBy", paid_by_value)
            add_update("Paid", new_status)
            add_update("Workplace_ID", wp)

            if updates:
                payroll_sheet.batch_update(updates)

        except Exception:
            pass

    if DB_MIGRATION_MODE:
        try:
            rec = PayrollReport.query.filter_by(
                username=username,
                workplace_id=wp,
                week_start=week_start,
                week_end=week_end,
            ).first()

            if action == "approve":
                if rec and status_is_paid(getattr(rec, "paid", "")):
                    return redirect(request.referrer or "/admin/payroll")

                if not rec:
                    rec = PayrollReport(
                        username=username,
                        workplace_id=wp,
                        week_start=week_start,
                        week_end=week_end,
                    )
                    db.session.add(rec)

                rec.gross = Decimal(str(round(gross, 2)))
                rec.tax = Decimal(str(round(tax, 2)))
                rec.net = Decimal(str(round(net, 2)))
                rec.display_tax = Decimal(str(round(tax, 2)))
                rec.display_net = Decimal(str(round(net, 2)))
                rec.payment_mode = "net"
                rec.paid = "APPROVED"
                rec.paid_by = actor

                db.session.commit()

                update_sheet_status("APPROVED", "", actor)

                log_audit(
                    "PAYROLL_APPROVE",
                    actor=actor,
                    username=username,
                    date_str=f"{week_start_raw}..{week_end_raw}",
                    details=f"gross={gross} tax={tax} net={net}",
                )

            elif action == "unlock":
                if not rec:
                    return redirect(request.referrer or "/admin/payroll")

                current_status = str(getattr(rec, "paid", "") or "").strip()

                # Paid payroll should not be unlocked here.
                # If you ever need this, make a separate "void payment" function later.
                if status_is_paid(current_status):
                    return redirect(request.referrer or "/admin/payroll")

                # Admin must confirm with their own workplace password.
                actor_rec = _find_employee_record(actor, wp)
                actor_password_hash = actor_rec.get("Password", "") if actor_rec else ""

                if not unlock_password or not actor_password_hash or not is_password_valid(actor_password_hash, unlock_password):
                    log_audit(
                        "PAYROLL_UNLOCK_FAILED",
                        actor=actor,
                        username=username,
                        date_str=f"{week_start_raw}..{week_end_raw}",
                        details="wrong_or_missing_admin_password",
                    )
                    return redirect(request.referrer or "/admin/payroll")

                rec.paid = ""
                rec.paid_by = ""
                rec.paid_at = None

                db.session.commit()

                log_audit(
                    "PAYROLL_UNLOCK",
                    actor=actor,
                    username=username,
                    date_str=f"{week_start_raw}..{week_end_raw}",
                    details=f"previous_status={current_status}",
                )

                update_sheet_status("", "", "")

        except Exception:
            db.session.rollback()

    else:
        if action == "approve":
            update_sheet_status("APPROVED", "", actor)
            log_audit(
                "PAYROLL_APPROVE",
                actor=actor,
                username=username,
                date_str=f"{week_start_raw}..{week_end_raw}",
                details=f"gross={gross} tax={tax} net={net}",
            )

        elif action == "unlock":
            actor_rec = _find_employee_record(actor, wp)
            actor_password_hash = actor_rec.get("Password", "") if actor_rec else ""

            if not unlock_password or not actor_password_hash or not is_password_valid(actor_password_hash, unlock_password):
                log_audit(
                    "PAYROLL_UNLOCK_FAILED",
                    actor=actor,
                    username=username,
                    date_str=f"{week_start_raw}..{week_end_raw}",
                    details="wrong_or_missing_admin_password_sheet_mode",
                )
                return redirect(request.referrer or "/admin/payroll")

            update_sheet_status("", "", "")
            log_audit(
                "PAYROLL_UNLOCK",
                actor=actor,
                username=username,
                date_str=f"{week_start_raw}..{week_end_raw}",
                details="sheet_unlock_confirmed_with_admin_password",
            )
    back_url = request.referrer or "/admin/payroll"
    back_url = (
        back_url
        .replace("&locked_week=1", "")
        .replace("?locked_week=1&", "?")
        .replace("?locked_week=1", "")
    )
    return redirect(back_url)