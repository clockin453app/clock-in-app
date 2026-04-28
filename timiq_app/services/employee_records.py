def employee_record_from_model(rec):
    if not rec:
        return None

    username = str(getattr(rec, "username", None) or getattr(rec, "email", "") or "").strip()
    full_name = str(getattr(rec, "name", "") or "").strip()
    first_name = str(getattr(rec, "first_name", "") or "").strip()
    last_name = str(getattr(rec, "last_name", "") or "").strip()

    if (not first_name and not last_name) and full_name:
        parts = [p for p in full_name.split() if p]
        if parts:
            first_name = parts[0]
            last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    rate_val = getattr(rec, "rate", None)
    rate_str = "" if rate_val in (None, "") else str(rate_val).strip()
    tax_rate_val = getattr(rec, "tax_rate", None)
    tax_rate_str = "" if tax_rate_val in (None, "") else str(tax_rate_val).strip()

    return {
        "Username": username,
        "Password": str(getattr(rec, "password", "") or "").strip(),
        "Role": str(getattr(rec, "role", "") or "").strip(),
        "Rate": rate_str,
        "TaxRate": tax_rate_str,
        "EarlyAccess": str(getattr(rec, "early_access", "") or "").strip(),
        "Active": str(getattr(rec, "active", "TRUE") or "TRUE").strip() or "TRUE",
        "FirstName": first_name,
        "LastName": last_name,
        "Site": str(getattr(rec, "site", "") or "").strip(),
        "Site2": str(getattr(rec, "site2", "") or "").strip(),
        "Workplace_ID": str(
            getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"
        ).strip() or "default",
        "OnboardingCompleted": str(getattr(rec, "onboarding_completed", "") or "").strip(),
    }
def employee_records_compat(records):
    out = []

    for rec in (records or []):
        if isinstance(rec, dict):
            username = str(rec.get("Username") or rec.get("username") or rec.get("email") or "").strip()
            first_name = str(rec.get("FirstName") or rec.get("first_name") or "").strip()
            last_name = str(rec.get("LastName") or rec.get("last_name") or "").strip()
            full_name = str(rec.get("Name") or rec.get("name") or "").strip()
            role = str(rec.get("Role") or rec.get("role") or "").strip()

            rate_raw = rec.get("Rate")
            if rate_raw in (None, ""):
                rate_raw = rec.get("rate")
            rate = "" if rate_raw in (None, "") else str(rate_raw).strip()
            tax_rate_raw = rec.get("TaxRate")
            if tax_rate_raw in (None, ""):
                tax_rate_raw = rec.get("tax_rate")
            tax_rate = "" if tax_rate_raw in (None, "") else str(tax_rate_raw).strip()

            early_access = str(rec.get("EarlyAccess") or rec.get("early_access") or "").strip()
            active = str(rec.get("Active") or rec.get("active") or "TRUE").strip() or "TRUE"
            workplace_id = str(
                rec.get("Workplace_ID") or rec.get("workplace_id") or rec.get("workplace") or "default"
            ).strip() or "default"
            site = str(rec.get("Site") or rec.get("site") or "").strip()
            site2 = str(rec.get("Site2") or rec.get("site2") or "").strip()
        else:
            username = str(getattr(rec, "username", None) or getattr(rec, "email", "") or "").strip()
            first_name = str(getattr(rec, "first_name", "") or "").strip()
            last_name = str(getattr(rec, "last_name", "") or "").strip()
            full_name = str(getattr(rec, "name", "") or "").strip()
            role = str(getattr(rec, "role", "") or "").strip()

            rate_val = getattr(rec, "rate", None)
            rate = "" if rate_val is None else str(rate_val).strip()
            tax_rate_val = getattr(rec, "tax_rate", None)
            tax_rate = "" if tax_rate_val is None else str(tax_rate_val).strip()

            early_access = str(getattr(rec, "early_access", "") or "").strip()
            active = str(getattr(rec, "active", "TRUE") or "TRUE").strip() or "TRUE"
            workplace_id = str(
                getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"
            ).strip() or "default"
            site = str(getattr(rec, "site", "") or "").strip()
            site2 = str(getattr(rec, "site2", "") or "").strip()

        if (not first_name and not last_name) and full_name:
            parts = [p for p in full_name.split() if p]
            if parts:
                first_name = parts[0]
                last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

        if not username:
            continue

        out.append({
            "Username": username,
            "FirstName": first_name,
            "LastName": last_name,
            "Role": role,
            "Rate": rate,
            "TaxRate": tax_rate,
            "EarlyAccess": early_access,
            "Active": active,
            "Workplace_ID": workplace_id,
            "Site": site,
            "Site2": site2,
        })

    return out

def find_employee_record(
    username: str,
    workplace_id: str | None = None,
    session_workplace_id: str | None = None,
    workplace_ids_for_read=None,
    password_is_hashed=None,
    ensure_password_hash_for_user=None,
    employee_model=None,
    import_sheet=None,
):
    target_user = (username or "").strip()
    target_wp = (workplace_id or session_workplace_id or "default").strip() or "default"
    allowed_wps = set(workplace_ids_for_read(target_wp))

    if not target_user:
        return None

    if employee_model is not None:
        try:
            for rec in employee_model.query.all():
                row = employee_record_from_model(rec)
                if not row:
                    continue
                if (row.get("Username", "") or "").strip() != target_user:
                    continue
                row_wp = (row.get("Workplace_ID", "") or "default").strip()
                if row_wp not in allowed_wps:
                    continue
                stored_pw = str(row.get("Password", "") or "").strip()
                if stored_pw and not password_is_hashed(stored_pw):
                    row = dict(row)
                    row["Password"] = ensure_password_hash_for_user(
                        target_user, stored_pw, workplace_id=target_wp
                    )
                return row
        except Exception:
            pass

    try:
        for user in import_sheet.get_all_records():
            row_user = (user.get("Username") or "").strip()
            row_wp = (user.get("Workplace_ID") or "").strip() or "default"
            if row_user == target_user and row_wp in allowed_wps:
                stored_pw = str(user.get("Password", "") or "").strip()
                if stored_pw and not password_is_hashed(stored_pw):
                    user = dict(user)
                    user["Password"] = ensure_password_hash_for_user(
                        target_user, stored_pw, workplace_id=target_wp
                    )
                return user
    except Exception:
        pass

    return None

def list_employee_records_for_workplace(
    workplace_id: str | None = None,
    include_inactive: bool = True,
    session_workplace_id: str | None = None,
    workplace_ids_for_read=None,
    employee_model=None,
    import_sheet=None,
):
    target_wp = (workplace_id or session_workplace_id or "default").strip() or "default"
    allowed_wps = set(workplace_ids_for_read(target_wp))
    out = []

    if employee_model is not None:
        try:
            for rec in employee_model.query.all():
                row = employee_record_from_model(rec)
                if not row:
                    continue
                row_wp = (row.get("Workplace_ID", "") or "default").strip()
                if row_wp not in allowed_wps:
                    continue

                if not include_inactive:
                    active_raw = str(row.get("Active", "TRUE") or "TRUE").strip().lower()
                    if active_raw in ("false", "0", "no", "n", "off"):
                        continue

                out.append(row)
            return out
        except Exception:
            pass

    try:
        for user in import_sheet.get_all_records():
            row_wp = (user.get("Workplace_ID") or "").strip() or "default"
            if row_wp not in allowed_wps:
                continue

            if not include_inactive:
                active_raw = str(user.get("Active", "TRUE") or "TRUE").strip().lower()
                if active_raw in ("false", "0", "no", "n", "off"):
                    continue

            out.append(user)
    except Exception:
        pass

    return out

def get_employee_display_name_data(
    username: str,
    session_workplace_id: str,
    workplace_ids_for_read,
    db_migration_mode: bool,
    employee_model,
    employees_sheet,
):
    u = (username or "").strip()
    if not u:
        return ""

    current_wp = session_workplace_id
    allowed_wps = set(workplace_ids_for_read(current_wp))

    if db_migration_mode:
        try:
            rec = employee_model.query.filter(
                employee_model.username == u,
                employee_model.workplace_id.in_(list(allowed_wps))
            ).first()
            if not rec:
                rec = employee_model.query.filter(
                    employee_model.email == u,
                    employee_model.workplace_id.in_(list(allowed_wps))
                ).first()

            if rec:
                first_name = str(getattr(rec, "first_name", "") or "").strip()
                last_name = str(getattr(rec, "last_name", "") or "").strip()
                full_name = str(getattr(rec, "name", "") or "").strip()

                display = (" ".join([first_name, last_name])).strip()
                return display or full_name or u
        except Exception:
            pass

    try:
        vals = employees_sheet.get_all_values()
        if not vals:
            return u

        headers = vals[0]
        if "Username" not in headers:
            return u

        ucol = headers.index("Username")
        wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
        fn_col = headers.index("FirstName") if "FirstName" in headers else None
        ln_col = headers.index("LastName") if "LastName" in headers else None

        for i in range(1, len(vals)):
            row = vals[i]
            row_user = (row[ucol] if len(row) > ucol else "").strip()
            if row_user != u:
                continue

            if wp_col is not None:
                row_wp = ((row[wp_col] if len(row) > wp_col else "").strip() or "default")
                if row_wp not in allowed_wps:
                    continue

            fn = row[fn_col] if fn_col is not None and fn_col < len(row) else ""
            ln = row[ln_col] if ln_col is not None and ln_col < len(row) else ""
            full = (fn + " " + ln).strip()
            return full or u

        return u
    except Exception:
        return u