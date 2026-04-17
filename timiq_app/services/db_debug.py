DB_DEBUG_ALLOWED_COLUMNS = {
    "employees": [
        "id", "username", "role", "first_name", "last_name", "rate", "early_access", "active", "site",
        "site2", "workplace_id", "created_at"
    ],
    "workhours": [
        "id", "employee_email", "date", "clock_in", "clock_out", "hours", "pay", "in_site", "in_dist_m",
        "out_site", "out_dist_m", "workplace", "workplace_id", "created_at"
    ],
    "audit_logs": [
        "id", "action", "user_email", "actor", "username", "date_text", "details", "workplace_id",
        "created_at"
    ],
    "payroll_reports": [
        "id", "username", "week_start", "week_end", "gross", "tax", "net", "paid_at", "paid_by", "paid",
        "workplace_id", "created_at"
    ],
    "onboarding_records": [
        "id", "username", "workplace_id", "first_name", "last_name", "position", "employment_type",
        "right_to_work_uk", "start_date", "contract_accepted", "signature_datetime", "submitted_at"
    ],
    "locations": ["id", "site_name", "radius_meters", "active", "workplace_id", "created_at"],
    "workplace_settings": ["id", "workplace_id", "tax_rate", "currency_symbol", "company_name", "created_at"],
}


def is_sensitive_debug_export_enabled(flag: bool) -> bool:
    return bool(flag)


def redact_value(column_name: str, value):
    col = str(column_name or "").strip().lower()
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        value = value.isoformat()

    secret_markers = (
        "password", "token", "secret", "hash", "bank", "sort_code", "sortcode",
        "national_insurance", "ni", "utr", "passport", "birth_cert", "share_code",
        "public_liability", "cscs_front_back", "selfie", "lat", "lon", "acc",
        "signature", "document", "geo", "medical_details",
    )
    if any(marker in col for marker in secret_markers):
        return "[REDACTED]"

    if col.endswith("_link") or col.endswith("_url"):
        return "[REDACTED]"

    if col in {"email", "phone", "phone_number", "emergency_contact_phone", "emergency_contact_phone_number"}:
        return "[REDACTED]"

    if col in {"bank_account_number", "sort_code", "national_insurance", "utr"}:
        return "[REDACTED]"

    if col in {"birth_date", "street_address", "address", "postcode", "city"}:
        return "[REDACTED]"

    if isinstance(value, str) and len(value) > 500:
        return value[:497] + "..."
    return value


def rows_to_dicts(model, limit=200, allowed_columns=None):
    rows = model.query.limit(limit).all()
    out = []
    allowed = set(allowed_columns or [])
    for row in rows:
        item = {}
        for col in row.__table__.columns:
            if allowed and col.name not in allowed:
                continue
            val = getattr(row, col.name)
            item[col.name] = redact_value(col.name, val)
        out.append(item)
    return out