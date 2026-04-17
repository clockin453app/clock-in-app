def get_payroll_rows_data(
    db_migration_mode: bool,
    payroll_sheet,
    payroll_report_model,
    workplace_ids_for_read,
):
    target_headers = [
        "WeekStart", "WeekEnd", "Username",
        "Gross", "Tax", "Net",
        "DisplayTax", "DisplayNet", "PaymentMode",
        "PaidAt", "PaidBy", "Paid", "Workplace_ID",
    ]

    old_headers = [
        "WeekStart", "WeekEnd", "Username",
        "Gross", "Tax", "Net",
        "PaidAt", "PaidBy", "Paid", "Workplace_ID",
    ]

    def _date_str(v):
        if not v:
            return ""
        try:
            return v.isoformat()
        except Exception:
            return str(v)

    def _dt_str(v):
        if not v:
            return ""
        try:
            return v.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                return v.isoformat(sep=" ")
            except Exception:
                return str(v)

    def _normalize_old_sheet_row(row):
        r = list(row[:10])
        while len(r) < 10:
            r.append("")
        return r[:6] + ["", "", ""] + r[6:10]

    def _normalize_current_sheet_row(row):
        r = list(row[:13])
        while len(r) < 13:
            r.append("")
        return r

    if not db_migration_mode:
        vals = payroll_sheet.get_all_values() if payroll_sheet else []
        if not vals:
            return [target_headers]

        raw_headers = [str(h or "").strip() for h in (vals[0] or [])]
        out = [target_headers]

        if raw_headers[:len(old_headers)] == old_headers:
            for row in vals[1:]:
                out.append(_normalize_old_sheet_row(row))
            return out

        if raw_headers[:len(target_headers)] == target_headers:
            for row in vals[1:]:
                r = list(row)

                if len(r) <= 10:
                    out.append(_normalize_old_sheet_row(r))
                    continue

                raw_col7 = str(r[6] if len(r) > 6 else "").strip()
                raw_col8 = str(r[7] if len(r) > 7 else "").strip()
                raw_col9 = str(r[8] if len(r) > 8 else "").strip().lower()

                looks_like_legacy_paidat = ("-" in raw_col7 and ":" in raw_col7) or ("/" in raw_col7 and ":" in raw_col7)
                looks_like_legacy_paidflag = raw_col9 in {"", "true", "false", "yes", "no", "paid", "1", "0"}

                if len(r) < 13 and (looks_like_legacy_paidat or looks_like_legacy_paidflag):
                    out.append(_normalize_old_sheet_row(r))
                else:
                    out.append(_normalize_current_sheet_row(r))
            return out

        for row in vals[1:]:
            r = list(row)
            if len(r) <= 10:
                out.append(_normalize_old_sheet_row(r))
            else:
                out.append(_normalize_current_sheet_row(r))
        return out

    out = [target_headers]

    try:
        rows = payroll_report_model.query.all()
    except Exception:
        return out

    items = []
    for rec in rows:
        row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip() or "default"

        allowed_wps = set(workplace_ids_for_read())
        if row_wp not in allowed_wps:
            continue

        gross = getattr(rec, "gross", None)
        tax = getattr(rec, "tax", None)
        net = getattr(rec, "net", None)

        payment_mode = str(getattr(rec, "payment_mode", "") or "").strip().lower()
        display_tax = getattr(rec, "display_tax", None)
        display_net = getattr(rec, "display_net", None)

        if payment_mode not in {"gross", "net"}:
            payment_mode = "net"

        if display_tax is None:
            display_tax = tax
        if display_net is None:
            display_net = net

        items.append([
            str(getattr(rec, "week_start", "") and _date_str(getattr(rec, "week_start")) or ""),
            str(getattr(rec, "week_end", "") and _date_str(getattr(rec, "week_end")) or ""),
            str(getattr(rec, "username", "") or "").strip(),
            "" if gross is None else str(gross),
            "" if tax is None else str(tax),
            "" if net is None else str(net),
            "" if display_tax is None else str(display_tax),
            "" if display_net is None else str(display_net),
            payment_mode,
            _dt_str(getattr(rec, "paid_at", None)),
            str(getattr(rec, "paid_by", "") or "").strip(),
            str(getattr(rec, "paid", "") or "").strip(),
            row_wp,
        ])

    items.sort(key=lambda r: ((r[0] or ""), (r[2] or "")))
    out.extend(items)
    return out


def get_workhours_rows_data(
    db_migration_mode: bool,
    work_sheet,
    workhour_model,
    workplace_ids_for_read,
    round_to_half_hour_func,
    apply_unpaid_break_func,
    get_user_rate_func,
):
    if not db_migration_mode:
        return work_sheet.get_all_values()

    headers = ["Username", "Date", "ClockIn", "ClockOut", "Hours", "Pay", "Workplace_ID"]
    out = [headers]

    try:
        rows = workhour_model.query.all()
    except Exception:
        return out

    def _to_time_str(v):
        if not v:
            return ""
        try:
            return v.strftime("%H:%M:%S")
        except Exception:
            return ""

    def _to_date_str(v):
        if not v:
            return ""
        try:
            return v.isoformat()
        except Exception:
            return str(v)

    items = []
    for rec in rows:
        username = str(
            getattr(rec, "employee_email", None)
            or getattr(rec, "username", None)
            or getattr(rec, "user_email", None)
            or ""
        ).strip()
        if not username:
            continue

        row_wp = str(
            getattr(rec, "workplace_id", None)
            or getattr(rec, "workplace", None)
            or "default"
        ).strip() or "default"

        allowed_wps = set(workplace_ids_for_read())
        if row_wp not in allowed_wps:
            continue

        d = getattr(rec, "date", None)
        cin = getattr(rec, "clock_in", None)
        cout = getattr(rec, "clock_out", None)

        hours_val = ""
        pay_val = ""

        if cin and cout:
            try:
                raw_hours = max(0.0, (cout - cin).total_seconds() / 3600.0)
                hours_num = round_to_half_hour_func(apply_unpaid_break_func(raw_hours))
                pay_num = round(hours_num * float(get_user_rate_func(username)), 2)
                hours_val = str(hours_num)
                pay_val = str(pay_num)
            except Exception:
                hours_val = ""
                pay_val = ""

        items.append([
            username,
            _to_date_str(d),
            _to_time_str(cin),
            _to_time_str(cout),
            hours_val,
            pay_val,
            row_wp,
        ])

    items.sort(key=lambda r: ((r[1] or ""), (r[0] or ""), (r[2] or "")))
    out.extend(items)
    return out