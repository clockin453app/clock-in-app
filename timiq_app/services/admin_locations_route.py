from ..ui.render import render_page
def admin_locations_impl(core):
    require_admin = core["require_admin"]
    get_csrf = core["get_csrf"]
    _ensure_locations_headers = core["_ensure_locations_headers"]
    _session_workplace_id = core["_session_workplace_id"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]
    Location = core["Location"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    get_locations = core["get_locations"]
    request = core["request"]
    session = core["session"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]

    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    _ensure_locations_headers()

    locations = []

    def is_active(value):
        return str(value or "").strip().lower() not in ("false", "0", "no", "n", "off")

    try:
        current_wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(current_wp))

        records = Location.query.all() if DB_MIGRATION_MODE else (get_locations() or [])

        for rec in records:
            if isinstance(rec, dict):
                row_wp = str(rec.get("Workplace_ID") or rec.get("workplace_id") or "default").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

                name = str(rec.get("SiteName") or rec.get("site_name") or rec.get("Site") or "").strip()
                lat = str(rec.get("Lat") or rec.get("lat") or "").strip()
                lon = str(rec.get("Lon") or rec.get("lon") or "").strip()
                rad = str(rec.get("RadiusMeters") or rec.get("radius_meters") or rec.get("Radius") or "").strip()
                act = str(rec.get("Active") or rec.get("active") or "TRUE").strip()
            else:
                row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip() or "default"
                if row_wp not in allowed_wps:
                    continue

                name = str(getattr(rec, "site_name", "") or "").strip()
                lat = str(getattr(rec, "lat", "") or "").strip()
                lon = str(getattr(rec, "lon", "") or "").strip()
                rad = str(getattr(rec, "radius_meters", "") or "").strip()
                act = str(getattr(rec, "active", "TRUE") or "TRUE").strip()

            if name:
                locations.append({
                    "name": name,
                    "lat": lat,
                    "lon": lon,
                    "rad": rad,
                    "act": act,
                    "active": is_active(act),
                })

    except Exception:
        locations = []

    selected = (request.args.get("site") or "").strip()
    chosen_raw = None

    for item in locations:
        if selected and item.get("name", "").strip().lower() == selected.lower():
            chosen_raw = item
            break

    if not chosen_raw and locations:
        chosen_raw = locations[0]

    chosen = None
    if chosen_raw:
        try:
            latf = float((chosen_raw.get("lat") or "0").strip())
            lonf = float((chosen_raw.get("lon") or "0").strip())
            delta = 0.006

            left = lonf - delta
            right = lonf + delta
            top = latf + delta
            bottom = latf - delta

            osm_url = (
                "https://www.openstreetmap.org/export/embed.html"
                f"?bbox={left}%2C{bottom}%2C{right}%2C{top}"
                f"&layer=mapnik&marker={latf}%2C{lonf}"
            )

            chosen = {
                "name": chosen_raw.get("name", ""),
                "lat": chosen_raw.get("lat", ""),
                "lon": chosen_raw.get("lon", ""),
                "osm_url": osm_url,
                "google_url": f"https://www.google.com/maps?q={latf},{lonf}",
                "osm_link": f"https://www.openstreetmap.org/?mlat={latf}&mlon={lonf}#map=18/{latf}/{lonf}",
            }
        except Exception:
            chosen = None

    total_locations = len(locations)
    active_locations = sum(1 for item in locations if item.get("active"))

    return render_page(
        template_name="admin/locations.html",
        active="admin",
        role=session.get("role", "admin"),
        layout_shell=layout_shell,
        style=STYLE,
        viewport=VIEWPORT,
        pwa_tags=PWA_TAGS,
        csrf=csrf,
        locations=locations,
        chosen=chosen,
        total_locations=total_locations,
        active_locations=active_locations,
        current_workplace=_session_workplace_id(),
    )


def admin_back_link(href: str = "/admin") -> str:
    return f"""
    <div style="margin:8px 0 14px;">
      <a href="{href}"
         aria-label="Back"
         title="Back"
         style="
           display:inline-block;
           color:#000;
           text-decoration:none;
           font-size:14px;
           font-weight:400;
           line-height:1.2;
           background:none;
           border:0;
           padding:0;
           box-shadow:none;
         ">
        Back
      </a>
    </div>
    """
