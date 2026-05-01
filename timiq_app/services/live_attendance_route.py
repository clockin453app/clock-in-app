import math
from ..ui.render import render_page as default_render_page


def live_attendance_impl(core):
    require_admin = core["require_admin"]
    session = core["session"]
    request = core["request"]

    datetime = core["datetime"]
    TZ = core["TZ"]

    get_workhours_rows = core["get_workhours_rows"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]

    COL_USER = core["COL_USER"]
    COL_DATE = core["COL_DATE"]
    COL_IN = core["COL_IN"]
    COL_OUT = core["COL_OUT"]

    get_employee_display_name = core["get_employee_display_name"]
    role_label = core.get("role_label", lambda r: str(r).replace("_", " ").title())

    DB_MIGRATION_MODE = core.get("DB_MIGRATION_MODE", False)
    Employee = core.get("Employee")
    WorkHour = core.get("WorkHour")
    Location = core.get("Location")
    WorkplaceSetting = core.get("WorkplaceSetting")

    get_employees_compat = core.get("get_employees_compat")
    employees_sheet = core.get("employees_sheet")
    locations_sheet = core.get("locations_sheet")
    _get_active_locations = core.get("_get_active_locations")

    layout_shell = core["layout_shell"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]

    render_page = core.get("render_page") or default_render_page

    gate = require_admin()
    if gate:
        return gate

    role = str(session.get("role", "employee") or "employee").strip().lower()
    is_master_admin = role == "master_admin"

    current_wp = _session_workplace_id()
    allowed_wps = set(_workplace_ids_for_read(current_wp) or [])
    if not allowed_wps:
        allowed_wps = {str(current_wp or "default").strip() or "default"}

    now_dt = datetime.now(TZ)
    today = now_dt.date()

    selected_site = (request.args.get("site") or "all").strip()
    selected_role = (request.args.get("role") or "all").strip()
    selected_workplace = (request.args.get("workplace") or "all").strip()
    search_query = (request.args.get("q") or "").strip()

    try:
        page = max(1, int(request.args.get("page") or "1"))
    except Exception:
        page = 1

    try:
        per_page = int(request.args.get("per_page") or "10")
    except Exception:
        per_page = 10

    if per_page not in (10, 25, 50):
        per_page = 10

    def row_wp(value):
        return str(value or "default").strip() or "default"

    def is_active_value(value):
        text = str(value if value is not None else "true").strip().lower()
        return text not in ("false", "0", "no", "off", "inactive", "disabled")

    def parse_date_value(value):
        if not value:
            return None

        if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
            try:
                if hasattr(value, "date"):
                    return value.date()
            except Exception:
                pass
            return value

        text = str(value).strip()
        if not text:
            return None

        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(text[:10], fmt).date()
            except Exception:
                pass

        try:
            return datetime.fromisoformat(text).date()
        except Exception:
            return None

    def parse_time_value(value):
        if not value:
            return None

        if hasattr(value, "hour") and hasattr(value, "minute"):
            try:
                if hasattr(value, "time"):
                    return value.time()
            except Exception:
                pass
            return value

        text = str(value).strip()
        if not text:
            return None

        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
            try:
                return datetime.strptime(text, fmt).time()
            except Exception:
                pass

        return None

    def make_dt(date_value, clock_value):
        date_obj = parse_date_value(date_value)
        time_obj = parse_time_value(clock_value)

        if not date_obj or not time_obj:
            return None

        try:
            value = datetime.combine(date_obj, time_obj)
            if getattr(value, "tzinfo", None) is None:
                value = value.replace(tzinfo=TZ)
            return value
        except Exception:
            return None

    def time_label(dt_value):
        if not dt_value:
            return "—"
        return dt_value.strftime("%I:%M %p").lstrip("0")

    def today_label():
        return today.strftime("%d %b %Y")

    def duration_label(seconds):
        seconds = max(0, int(seconds or 0))
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def initials(name):
        parts = [p for p in str(name or "").strip().split() if p]
        if not parts:
            return "U"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    def normalise_job(value):
        return str(value or "Employee").strip().replace("_", " ").title() or "Employee"

    def employee_key(username, workplace_id):
        return (str(username or "").strip().lower(), row_wp(workplace_id).lower())

    def can_admin_see_workplace(workplace_id):
        if is_master_admin:
            return True
        return row_wp(workplace_id) in allowed_wps

    def workplace_display_name(workplace_id):
        workplace_id = row_wp(workplace_id)

        if DB_MIGRATION_MODE and WorkplaceSetting is not None:
            try:
                rec = WorkplaceSetting.query.filter_by(workplace_id=workplace_id).first()
                if rec and getattr(rec, "company_name", None):
                    return str(rec.company_name).strip()
            except Exception:
                pass

        return workplace_id.replace("_", " ").replace("-", " ").upper()

    employee_lookup = {}
    employee_rows = []

    def add_employee(username, display, job, workplace_id, site="", active=True):
        username = str(username or "").strip()
        if not username or not active:
            return

        workplace_id = row_wp(workplace_id)
        if not can_admin_see_workplace(workplace_id):
            return

        display = str(display or get_employee_display_name(username) or username).strip()
        job = normalise_job(job)
        site = str(site or "Main Site").strip() or "Main Site"

        item = {
            "username": username,
            "display": display,
            "initials": initials(display),
            "job": job,
            "site": site,
            "workplace": workplace_id,
            "workplace_label": workplace_display_name(workplace_id),
        }

        key = employee_key(username, workplace_id)
        employee_lookup[key] = item
        employee_lookup.setdefault((username.lower(), ""), item)

        if key not in {(e["username"].lower(), e["workplace"].lower()) for e in employee_rows}:
            employee_rows.append(item)

    def load_employees():
        if DB_MIGRATION_MODE and Employee is not None:
            try:
                for rec in Employee.query.all():
                    username = (
                        getattr(rec, "username", None)
                        or getattr(rec, "email", None)
                        or ""
                    )
                    workplace_id = (
                        getattr(rec, "workplace_id", None)
                        or getattr(rec, "workplace", None)
                        or "default"
                    )
                    display = (
                        getattr(rec, "name", None)
                        or f"{getattr(rec, 'first_name', '') or ''} {getattr(rec, 'last_name', '') or ''}".strip()
                        or username
                    )
                    job = getattr(rec, "role", None) or "Employee"
                    site = getattr(rec, "site", None) or getattr(rec, "site2", None) or "Main Site"
                    active = is_active_value(getattr(rec, "active", "true"))

                    add_employee(username, display, job, workplace_id, site, active)
            except Exception:
                pass

        try:
            if callable(get_employees_compat):
                for rec in get_employees_compat() or []:
                    username = (
                        rec.get("Username")
                        or rec.get("username")
                        or rec.get("Email")
                        or rec.get("email")
                        or ""
                    )
                    workplace_id = (
                        rec.get("Workplace_ID")
                        or rec.get("workplace_id")
                        or rec.get("workplace")
                        or "default"
                    )
                    first = str(rec.get("FirstName") or rec.get("first_name") or "").strip()
                    last = str(rec.get("LastName") or rec.get("last_name") or "").strip()
                    display = (
                        rec.get("DisplayName")
                        or rec.get("Name")
                        or f"{first} {last}".strip()
                        or username
                    )
                    job = (
                        rec.get("JobTitle")
                        or rec.get("Job_Title")
                        or rec.get("Trade")
                        or rec.get("Position")
                        or rec.get("Role")
                        or rec.get("role")
                        or "Employee"
                    )
                    site = rec.get("Site") or rec.get("site") or rec.get("SiteName") or "Main Site"
                    active = is_active_value(rec.get("Active") or rec.get("active") or "true")

                    add_employee(username, display, job, workplace_id, site, active)
        except Exception:
            pass

        try:
            if employees_sheet is not None:
                values = employees_sheet.get_all_values()
                headers = values[0] if values else []
                for row in values[1:]:
                    rec = {}
                    for i, header in enumerate(headers):
                        rec[str(header or "").strip()] = row[i] if i < len(row) else ""

                    username = rec.get("Username") or rec.get("Email") or rec.get("email") or ""
                    workplace_id = rec.get("Workplace_ID") or rec.get("Workplace") or "default"
                    display = (
                        rec.get("DisplayName")
                        or rec.get("Name")
                        or f"{rec.get('FirstName', '')} {rec.get('LastName', '')}".strip()
                        or username
                    )
                    job = rec.get("JobTitle") or rec.get("Trade") or rec.get("Role") or "Employee"
                    site = rec.get("Site") or rec.get("SiteName") or "Main Site"
                    active = is_active_value(rec.get("Active") or "true")

                    add_employee(username, display, job, workplace_id, site, active)
        except Exception:
            pass

    load_employees()

    attendance_by_key = {}

    def employee_meta(username, workplace_id):
        key = employee_key(username, workplace_id)
        meta = employee_lookup.get(key) or employee_lookup.get((str(username or "").lower(), "")) or {}

        display = str(
            meta.get("display")
            or get_employee_display_name(username)
            or username
        ).strip()

        job = normalise_job(meta.get("job") or "Employee")
        site = str(meta.get("site") or "Main Site").strip() or "Main Site"

        return display, job, site

    def make_attendance_item(username, workplace_id, start_dt, end_dt, site_name):
        display, job, employee_site = employee_meta(username, workplace_id)
        site_name = str(site_name or employee_site or "Main Site").strip() or "Main Site"

        meta = (
                employee_lookup.get(employee_key(username, workplace_id))
                or employee_lookup.get((str(username or "").strip().lower(), ""))
                or {}
        )
        workplace_label = meta.get("workplace_label") or workplace_display_name(workplace_id)

        duration_end_dt = end_dt or now_dt
        elapsed_seconds = max(0, int((duration_end_dt - start_dt).total_seconds()))

        status_key = "present"
        start_time = parse_time_value(start_dt)
        if start_time and (start_time.hour, start_time.minute) > (9, 0):
            status_key = "late"

        return {
            "username": username,
            "display": display,
            "initials": initials(display),
            "job": job,
            "site": site_name,
            "workplace": row_wp(workplace_id),
            "workplace_label": workplace_label,
            "clock_in": time_label(start_dt),
            "clock_out": time_label(end_dt) if end_dt else "—",
            "date_label": "Today",
            "elapsed": duration_label(elapsed_seconds),
            "elapsed_seconds": elapsed_seconds,
            "status_key": status_key,
            "older_open": False,
            "sort_key": start_dt.isoformat(),
        }

    used_db = False

    if DB_MIGRATION_MODE and WorkHour is not None:
        try:
            db_rows = (
                WorkHour.query
                .filter(WorkHour.date == today)
                .order_by(WorkHour.date.desc(), WorkHour.id.desc())
                .all()
            )
            used_db = True

            for rec in db_rows:
                username = str(getattr(rec, "employee_email", "") or "").strip()
                if not username:
                    continue

                workplace_id = row_wp(
                    getattr(rec, "workplace_id", None)
                    or getattr(rec, "workplace", None)
                )

                if not can_admin_see_workplace(workplace_id):
                    continue

                start_dt = make_dt(getattr(rec, "date", None), getattr(rec, "clock_in", None))
                if not start_dt:
                    continue

                clock_out_value = getattr(rec, "clock_out", None)
                end_dt = make_dt(getattr(rec, "date", None), clock_out_value) if clock_out_value else None

                site_name = (
                    getattr(rec, "in_site", None)
                    or getattr(rec, "out_site", None)
                    or getattr(rec, "site_name", None)
                    or "Main Site"
                )

                key = employee_key(username, workplace_id)
                attendance_by_key[key] = make_attendance_item(username, workplace_id, start_dt, end_dt, site_name)

        except Exception:
            used_db = False
            attendance_by_key = {}

    if not used_db:
        try:
            rows = get_workhours_rows() or []
            headers = rows[0] if rows else []

            def idx(*names):
                for name in names:
                    if name in headers:
                        return headers.index(name)
                return None

            wp_idx = idx("Workplace_ID", "WorkplaceId", "Workplace")
            in_site_idx = idx("InSite", "Site", "SiteName", "Location")
            out_site_idx = idx("OutSite")

            for row in rows[1:]:
                if len(row) <= max(COL_USER, COL_DATE, COL_IN, COL_OUT):
                    continue

                username = str(row[COL_USER] or "").strip()
                if not username:
                    continue

                workplace_id = "default"
                if wp_idx is not None and wp_idx < len(row):
                    workplace_id = row_wp(row[wp_idx])

                if not can_admin_see_workplace(workplace_id):
                    continue

                date_raw = str(row[COL_DATE] or "").strip()
                if parse_date_value(date_raw) != today:
                    continue

                clock_in_raw = str(row[COL_IN] or "").strip()
                clock_out_raw = str(row[COL_OUT] or "").strip()

                if not clock_in_raw:
                    continue

                start_dt = make_dt(date_raw, clock_in_raw)
                if not start_dt:
                    continue

                end_dt = make_dt(date_raw, clock_out_raw) if clock_out_raw else None

                site_name = ""
                if in_site_idx is not None and in_site_idx < len(row):
                    site_name = str(row[in_site_idx] or "").strip()
                if not site_name and out_site_idx is not None and out_site_idx < len(row):
                    site_name = str(row[out_site_idx] or "").strip()
                site_name = site_name or "Main Site"

                key = employee_key(username, workplace_id)
                attendance_by_key[key] = make_attendance_item(username, workplace_id, start_dt, end_dt, site_name)

        except Exception:
            attendance_by_key = {}

    attendance_items = []
    used_employee_keys = set()

    for employee in employee_rows:
        key = employee_key(employee["username"], employee["workplace"])
        used_employee_keys.add(key)

        if key in attendance_by_key:
            attendance_items.append(attendance_by_key[key])
        else:
            attendance_items.append({
                "username": employee["username"],
                "display": employee["display"],
                "initials": employee["initials"],
                "job": employee["job"],
                "site": employee["site"],
                "workplace": employee["workplace"],
                "workplace_label": employee.get("workplace_label") or workplace_display_name(employee["workplace"]),
                "clock_in": "—",
                "clock_out": "—",
                "date_label": "Today",
                "elapsed": "—",
                "elapsed_seconds": 0,
                "status_key": "absent",
                "older_open": False,
                "sort_key": "99-" + employee["display"].lower(),
            })

    for key, item in attendance_by_key.items():
        if key not in used_employee_keys:
            attendance_items.append(item)
    workplace_options = []
    seen_workplaces = set()

    for item in attendance_items:
        workplace_value = str(item.get("workplace") or "").strip()
        if not workplace_value:
            continue

        workplace_key = workplace_value.lower()
        if workplace_key in seen_workplaces:
            continue

        seen_workplaces.add(workplace_key)
        workplace_options.append({
            "value": workplace_value,
            "label": item.get("workplace_label") or workplace_value,
        })

    workplace_options = sorted(
        workplace_options,
        key=lambda item: item["label"].lower()
    )

    if selected_workplace.lower() != "all":
        attendance_items = [
            item for item in attendance_items
            if str(item.get("workplace") or "").lower() == selected_workplace.lower()
        ]

    if selected_site.lower() != "all":
        attendance_items = [
            item for item in attendance_items
            if item.get("site", "").lower() == selected_site.lower()
        ]

    if selected_role.lower() != "all":
        attendance_items = [
            item for item in attendance_items
            if item.get("job", "").lower() == selected_role.lower()
        ]

    if search_query:
        q = search_query.lower()
        attendance_items = [
            item for item in attendance_items
            if q in item.get("display", "").lower()
            or q in item.get("username", "").lower()
            or q in item.get("site", "").lower()
            or q in item.get("job", "").lower()
            or q in item.get("status_key", "").lower()
        ]

    status_order = {"present": 0, "late": 1, "break": 2, "absent": 3}
    attendance_items = sorted(
        attendance_items,
        key=lambda item: (
            status_order.get(item.get("status_key"), 9),
            item.get("display", "").lower(),
        ),
    )

    present_count = sum(1 for item in attendance_items if item.get("status_key") != "absent")
    late_count = sum(1 for item in attendance_items if item.get("status_key") == "late")
    open_shift_count = sum(1 for item in attendance_items if item.get("clock_out") == "—" and item.get("status_key") != "absent")
    total_visible = len(attendance_items)
    attendance_rate = round((present_count * 100.0 / total_visible), 1) if total_visible else 0

    site_counts = {}
    for item in attendance_items:
        if item.get("status_key") == "absent":
            continue
        site = item.get("site") or "Main Site"
        site_counts[site] = site_counts.get(site, 0) + 1

    def active_location_names():
        names = []

        try:
            if is_master_admin and DB_MIGRATION_MODE and Location is not None:
                for rec in Location.query.all():
                    active = str(getattr(rec, "active", "TRUE") or "TRUE").strip().lower()
                    name = str(
                        getattr(rec, "site_name", "")
                        or getattr(rec, "name", "")
                        or ""
                    ).strip()
                    if name and active not in ("false", "0", "no", "off"):
                        names.append(name)

            elif is_master_admin and locations_sheet is not None:
                values = locations_sheet.get_all_values()
                headers = values[0] if values else []

                i_name = headers.index("SiteName") if "SiteName" in headers else 0
                i_active = headers.index("Active") if "Active" in headers else None

                for row in values[1:]:
                    name = str(row[i_name] if i_name < len(row) else "").strip()
                    active = str(
                        row[i_active] if i_active is not None and i_active < len(row) else "TRUE"
                    ).strip().lower()

                    if name and active not in ("false", "0", "no", "off"):
                        names.append(name)

            elif callable(_get_active_locations):
                for loc in _get_active_locations() or []:
                    name = str(
                        loc.get("name")
                        or loc.get("site_name")
                        or loc.get("SiteName")
                        or loc.get("Site")
                        or ""
                    ).strip()
                    if name:
                        names.append(name)

        except Exception:
            names = []

        return sorted(set(names), key=lambda x: x.lower())

    location_names = active_location_names()
    active_site_count = len(set(location_names) | set(site_counts.keys()))

    alert_rows = []
    for item in attendance_items:
        if item.get("status_key") == "absent":
            alert_rows.append({
                "employee": item["display"],
                "site": item["site"],
                "issue": "Missed Clock-in",
                "expected": "08:00 AM",
                "actual": "—",
                "date": today_label(),
            })
        elif item.get("status_key") == "late":
            alert_rows.append({
                "employee": item["display"],
                "site": item["site"],
                "issue": "Late Arrival",
                "expected": "09:00 AM",
                "actual": item["clock_in"],
                "date": today_label(),
            })
        elif item.get("elapsed_seconds", 0) >= 10 * 3600:
            alert_rows.append({
                "employee": item["display"],
                "site": item["site"],
                "issue": "Overtime Alert",
                "expected": "08:00 h",
                "actual": item["elapsed"],
                "date": today_label(),
            })

    site_options = sorted(
        set(location_names) | set(item["site"] for item in attendance_items if item.get("site")),
        key=lambda x: x.lower()
    )

    role_options = sorted(
        set(item["job"] for item in attendance_items if item.get("job")),
        key=lambda x: x.lower()
    )

    total_count = len(attendance_items)
    total_pages = max(1, int(math.ceil(total_count / float(per_page or 1))))

    if page > total_pages:
        page = total_pages

    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    page_items = attendance_items[start_index:end_index]

    if total_pages <= 8:
        pagination_pages = list(range(1, total_pages + 1))
    else:
        pagination_pages = [1, 2, 3, 4, 5, total_pages]

    return render_page(
        template_name="admin/live_attendance.html",
        active="current-sessions",
        role=role,
        layout_shell=layout_shell,
        style=STYLE,
        viewport=VIEWPORT,
        pwa_tags=PWA_TAGS,

        is_master_admin=is_master_admin,
        role_badge="MASTER ADMIN" if is_master_admin else "ADMIN",
        role_label_text=role_label(role),

        live_count=present_count,
        open_shift_count=open_shift_count,
        active_site_count=active_site_count,
        alerts_count=late_count,
        attendance_rate=attendance_rate,

        sessions=page_items,
        alert_rows=alert_rows,

        site_options=site_options,
        role_options=role_options,

        selected_site=selected_site,
        selected_role=selected_role,
        selected_workplace=selected_workplace,
        workplace_options=workplace_options,
        search_query=search_query,

        page=page,
        per_page=per_page,
        total_pages=total_pages,
        pagination_pages=pagination_pages,
        range_start=(start_index + 1) if total_count else 0,
        range_end=min(end_index, total_count),
        total_count=total_count,
    )