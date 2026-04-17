import re



def sanitize_clock_geo(lat_v, lon_v, acc_v, max_clock_location_accuracy_m: float):
    if lat_v is None or lon_v is None:
        return lat_v, lon_v, acc_v

    lat_v = float(lat_v)
    lon_v = float(lon_v)

    if not (-90.0 <= lat_v <= 90.0) or not (-180.0 <= lon_v <= 180.0):
        raise RuntimeError("Invalid location coordinates.")

    if acc_v is not None:
        acc_v = float(acc_v)
        if acc_v < 0:
            raise RuntimeError("Invalid location accuracy.")
        if acc_v > max_clock_location_accuracy_m:
            raise RuntimeError(
                f"Location accuracy is too low ({int(acc_v)}m). Move to an open area and try again."
            )
        acc_v = round(acc_v, 2)

    return round(lat_v, 8), round(lon_v, 8), acc_v


def validate_recent_clock_capture(captured_at_raw: str, now_dt, max_clock_location_age_s: float):
    raw = (captured_at_raw or "").strip()
    if not raw:
        raise RuntimeError("Fresh location capture is required. Please try again.")

    try:
        ts = float(raw)
    except Exception as exc:
        raise RuntimeError("Invalid location capture timestamp.") from exc

    if ts > 1e12:
        ts = ts / 1000.0

    age = abs(now_dt.timestamp() - ts)
    if age > max_clock_location_age_s:
        raise RuntimeError("Location capture expired. Please try again.")



def validate_user_location(
    username: str,
    lat: float | None,
    lon: float | None,
    acc_m: float | None,
    get_employee_sites_func,
    get_active_locations_func,
    get_site_config_func,
    haversine_m_func,
    max_clock_location_accuracy_m: float,
) -> tuple[bool, dict, float]:
    """Returns (ok, site_cfg, distance_m).

    Behavior:
      - If employee has assigned site(s): validate against those sites (passes if inside ANY assigned site radius).
      - If no assigned site exists: fail closed. Clocking requires an explicit site assignment.
    """
    sites = get_employee_sites_func(username)
    active_sites = get_active_locations_func()

    if lat is None or lon is None:
        if sites:
            cfg = get_site_config_func(sites[0]) or {"name": sites[0], "lat": 0.0, "lon": 0.0, "radius": 0.0}
        else:
            cfg = active_sites[0] if active_sites else {"name": "Unknown", "lat": 0.0, "lon": 0.0, "radius": 0.0}
        return False, cfg, 0.0

    latf, lonf = float(lat), float(lon)
    if not (-90.0 <= latf <= 90.0 and -180.0 <= lonf <= 180.0):
        raise RuntimeError("Invalid location data received. Please refresh and try again.")

    try:
        acc_buf = float(acc_m) if acc_m is not None else 0.0
        if acc_buf < 0:
            acc_buf = 0.0
        if acc_buf > max_clock_location_accuracy_m:
            raise RuntimeError(
                "Location accuracy is too low to verify this clock action. Move closer to the site and try again."
            )
    except RuntimeError:
        raise
    except Exception:
        acc_buf = 0.0

    def _inside(dist_m: float, radius_m: float) -> bool:
        buf = min(max(acc_buf, 0.0), 2000.0)
        return dist_m <= (float(radius_m) + buf)

    if not active_sites:
        pref = sites[0] if sites else "Unknown"
        return False, {"name": pref, "lat": 0.0, "lon": 0.0, "radius": 0.0}, 0.0

    if not sites:
        cfg = active_sites[0] if active_sites else {"name": "Unknown", "lat": 0.0, "lon": 0.0, "radius": 0.0}
        return False, cfg, 0.0

    candidates = []
    for sname in sites:
        cfg = get_site_config_func(sname)
        if cfg:
            candidates.append(cfg)

    if not candidates:
        pref = sites[0] if sites else "Unknown"
        return False, {"name": pref, "lat": 0.0, "lon": 0.0, "radius": 0.0}, 0.0

    best_cfg = candidates[0]
    best_dist = haversine_m_func(latf, lonf, best_cfg["lat"], best_cfg["lon"])
    best_ok = _inside(best_dist, float(best_cfg["radius"]))

    for cfg in candidates[1:]:
        dist = haversine_m_func(latf, lonf, cfg["lat"], cfg["lon"])
        ok = _inside(dist, float(cfg["radius"]))
        if ok and (not best_ok or dist < best_dist):
            best_cfg, best_dist, best_ok = cfg, dist, ok
        elif (not best_ok) and dist < best_dist:
            best_cfg, best_dist, best_ok = cfg, dist, ok

    return bool(best_ok), best_cfg, float(best_dist)





def get_site_config(
    site_name: str,
    get_active_locations_func,
):
    target = (site_name or "").strip().lower()
    if not target:
        return None

    for loc in get_active_locations_func():
        name = str(loc.get("name") or loc.get("site_name") or loc.get("SiteName") or loc.get("Site") or "").strip()
        if name.lower() == target:
            return loc
    return None


def get_active_locations(
    session_workplace_id_func,
    workplace_ids_for_read_func,
    db_migration_mode: bool,
    location_model,
    safe_float_func,
    locations_sheet_obj,
):
    out = []
    current_wp = session_workplace_id_func()
    allowed_wps = set(workplace_ids_for_read_func(current_wp))

    if db_migration_mode:
        try:
            for rec in location_model.query.all():
                row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

                name = str(getattr(rec, "site_name", "") or "").strip()
                active = str(getattr(rec, "active", "TRUE") or "TRUE").strip().upper()
                lat = safe_float_func(getattr(rec, "lat", None), None)
                lon = safe_float_func(getattr(rec, "lon", None), None)
                rad = safe_float_func(getattr(rec, "radius_meters", None), 0.0)

                if not name:
                    continue
                if active not in ("TRUE", "YES", "1"):
                    continue
                if lat is None or lon is None or rad <= 0:
                    continue

                out.append({"name": name, "lat": float(lat), "lon": float(lon), "radius": float(rad)})
            return out
        except Exception:
            pass

    if not locations_sheet_obj:
        return out

    try:
        vals = locations_sheet_obj.get_all_values()
        if not vals:
            return out
        headers = vals[0]

        def idx(n):
            return headers.index(n) if n in headers else None

        i_name = idx("SiteName")
        i_lat = idx("Lat")
        i_lon = idx("Lon")
        i_rad = idx("RadiusMeters")
        i_act = idx("Active")
        i_wp = idx("Workplace_ID")

        for r in vals[1:]:
            if i_wp is not None:
                row_wp = (r[i_wp] if i_wp < len(r) else "").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

            name = (r[i_name] if i_name is not None and i_name < len(r) else "").strip()
            if not name:
                continue

            active = (r[i_act] if i_act is not None and i_act < len(r) else "TRUE").strip().upper()
            if active not in ("TRUE", "YES", "1"):
                continue

            lat = safe_float_func(r[i_lat] if i_lat is not None and i_lat < len(r) else "", None)
            lon = safe_float_func(r[i_lon] if i_lon is not None and i_lon < len(r) else "", None)
            rad = safe_float_func(r[i_rad] if i_rad is not None and i_rad < len(r) else "", 0.0)

            if lat is None or lon is None or rad <= 0:
                continue

            out.append({"name": name, "lat": float(lat), "lon": float(lon), "radius": float(rad)})
    except Exception:
        return []

    return out


def get_employee_sites(
    username: str,
    session_workplace_id_func,
    workplace_ids_for_read_func,
    db_migration_mode: bool,
    employee_model,
    employees_sheet_obj,
):
    current_wp = session_workplace_id_func()
    allowed_wps = set(workplace_ids_for_read_func(current_wp))

    def _normalize_sites(raw_values):
        sites = []
        for raw in raw_values:
            raw = (raw or "").strip()
            if not raw:
                continue
            for part in re.split(r"[;,]", raw):
                p = (part or "").strip()
                if p:
                    sites.append(p)

        seen = set()
        out = []
        for s in sites:
            key = s.lower()
            if key not in seen:
                seen.add(key)
                out.append(s)
        return out

    if db_migration_mode:
        try:
            rec = employee_model.query.filter_by(username=username, workplace_id=current_wp).first()
            if not rec:
                rec = employee_model.query.filter_by(email=username, workplace_id=current_wp).first()
            if rec:
                raw1 = str(getattr(rec, "site", "") or "").strip()
                raw2 = str(getattr(rec, "site2", "") or "").strip() if hasattr(rec, "site2") else ""
                return _normalize_sites([raw1, raw2])
        except Exception:
            pass

    try:
        vals = employees_sheet_obj.get_all_values()
        if not vals:
            return []
        headers = vals[0]
        if "Username" not in headers:
            return []
        ucol = headers.index("Username")
        wp_col = headers.index("Workplace_ID") if "Workplace_ID" in headers else None
        scol = headers.index("Site") if "Site" in headers else None
        s2col = headers.index("Site2") if "Site2" in headers else None

        for i in range(1, len(vals)):
            row = vals[i]
            if len(row) > ucol and (row[ucol] or "").strip() == username:
                if wp_col is not None:
                    row_wp = (row[wp_col] if len(row) > wp_col else "").strip() or "default"
                    if row_wp not in allowed_wps:
                        continue

                raw1 = (row[scol] or "").strip() if scol is not None and scol < len(row) else ""
                raw2 = (row[s2col] or "").strip() if s2col is not None and s2col < len(row) else ""
                return _normalize_sites([raw1, raw2])
    except Exception:
        return []

    return []


def get_employee_site(
    username: str,
    get_employee_sites_func,
) -> str:
    """Backwards-compatible: return primary site (first) or empty."""
    sites = get_employee_sites_func(username)
    return sites[0] if sites else ""


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    from math import radians, sin, cos, asin, sqrt

    r = 6371000.0
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dl / 2) ** 2
    c = 2 * asin(sqrt(a))
    return r * c



def ensure_workhours_geo_headers(
    work_sheet_obj,
    gspread_mod,
    workhours_geo_headers,
):
    try:
        vals = work_sheet_obj.get_all_values()
        if not vals:
            return
        headers = vals[0]
        base_headers = ["Username", "Date", "ClockIn", "ClockOut", "Hours", "Pay", "Workplace_ID"]
        if not headers:
            return
        if len(headers) < len(base_headers):
            headers = base_headers[:]
        missing = [h for h in (["Workplace_ID"] + workhours_geo_headers) if h not in headers]
        if missing:
            headers = headers + missing
            work_sheet_obj.update(
                f"A1:{gspread_mod.utils.rowcol_to_a1(1, len(headers)).replace('1', '')}1",
                [headers],
            )
    except Exception:
        return




