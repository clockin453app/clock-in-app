"""Shared compatibility imports for route modules.

The refactor still relies on the legacy runtime defined in ``core.py``. This
module provides an explicit, audited import surface for routes so the route
files no longer depend on ``from workhours_app.core import *``.
"""

import workhours_app.core as _core_module


class _CoreRef:
    """Late-bound proxy for mutable runtime handles defined in core.py."""

    def __init__(self, name: str):
        self._name = name

    def _target(self):
        return getattr(_core_module, self._name)

    def __getattr__(self, item):
        return getattr(self._target(), item)

    def __bool__(self):
        return bool(self._target())

    def __call__(self, *args, **kwargs):
        return self._target()(*args, **kwargs)

    def __iter__(self):
        return iter(self._target())

    def __repr__(self):
        return repr(self._target())


from workhours_app.core import (
    # Flask / SQLAlchemy runtime
    abort,
    app,
    db,
    jsonify,
    make_response,
    redirect,
    request,
    send_file,
    session,
    url_for,
    # Standard library / third-party helpers re-exported by core
    Decimal,
    date,
    datetime,
    escape,
    generate_password_hash,
    gspread,
    io,
    json,
    math,
    timedelta,
    or_,
    and_,
    os,
    re,
    # Models / settings
    AuditLog,
    BREAK_APPLIES_IF_SHIFT_AT_LEAST_HOURS,
    CLOCKIN_EARLIEST,
    CLOCK_SELFIE_DIR,
    CLOCK_SELFIE_REQUIRED,
    COL_DATE,
    COL_HOURS,
    COL_IN,
    COL_OUT,
    COL_PAY,
    COL_USER,
    DB_MIGRATION_MODE,
    Employee,
    ENABLE_GOOGLE_SHEETS,
    Location,
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    OAUTH_REDIRECT_URI,
    OVERTIME_HOURS,
    OnboardingRecord,
    PayrollReport,
    SHEETS_IMPORT_ENABLED,
    TZ,
    UNPAID_BREAK_HOURS,
    WorkHour,
    WorkplaceSetting,
    # Sheet / proxy handles
                            # Route / rendering helpers
    find_open_shift,
    find_row_by_username,
    fmt_hours,
    get_company_settings,
    get_csrf,
    get_employee_display_name,
    get_employees_compat,
    get_locations,
    get_onboarding_record,
    get_sheet_headers,
    get_workhours_rows,
    has_any_row_today,
    initials,
    is_password_valid,
    linkify,
    log_audit,
    migrate_password_if_plain,
    money,
    normalized_clock_in_time,
    onboarding_details_block,
    parse_bool,
    render_app_page,
    render_standalone_page,
    require_admin,
    require_csrf,
    require_destructive_admin_post,
    require_login,
    require_master_admin,
    require_sensitive_tools_admin,
    role_label,
    safe_float,
    set_employee_field,
    set_employee_first_last,
    update_employee_password,
    update_or_append_onboarding,
    upload_to_drive,
    user_in_same_workplace,
    # Low-level compatibility helpers kept in core for now
    _append_paid_record_safe,
    _apply_unpaid_break,
    _cache_invalidate_prefix,
    _clear_active_session_token,
    _client_ip,
    _compute_hours_from_times,
    _employees_usernames_for_workplace,
    _ensure_employees_columns,
    _ensure_locations_headers,
    _ensure_workhours_geo_headers,
    _find_employee_record,
    _find_location_row_by_name,
    _find_workhours_row_by_user_date,
    _generate_temp_password,
    _generate_unique_username,
    _get_active_locations,
    _get_employee_site,
    _get_employee_sites,
    _get_import_sheet,
    _get_open_shifts,
    _get_site_config,
    _get_user_rate,
    _get_week_range,
    _gs_write_with_retry,
    _is_paid_for_week,
    _is_sensitive_debug_export_enabled,
    _issue_active_session_token,
    _list_employee_records_for_workplace,
    _login_rate_limit_check,
    _login_rate_limit_clear,
    _login_rate_limit_hit,
    _make_oauth_flow,
    _normalize_password_hash_value,
    _pick,
    _render_onboarding_page,
    _rows_to_dicts,
    _sanitize_clock_geo,
    _sanitize_requested_role,
    _save_drive_token,
    _session_workplace_id,
    _store_clock_selfie,
    _svg_chart,
    _svg_clipboard,
    _svg_clock,
    _svg_doc,
    _svg_grid,
    _svg_user,
    _to_date,
    _to_datetime,
    _to_decimal,
    _to_int,
    _to_str,
    _validate_recent_clock_capture,
    _validate_user_location,
    _DB_DEBUG_ALLOWED_COLUMNS,
)


# Mutable runtime handles must stay late-bound because initialize_runtime()
# assigns them after this module is imported.
employees_sheet = _CoreRef("employees_sheet")
locations_sheet = _CoreRef("locations_sheet")
onboarding_sheet = _CoreRef("onboarding_sheet")
settings_sheet = _CoreRef("settings_sheet")
spreadsheet = _CoreRef("spreadsheet")
work_sheet = _CoreRef("work_sheet")

__all__ = [name for name in globals() if not name.startswith("__")]
