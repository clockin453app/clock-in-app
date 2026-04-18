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
    escape = core["escape"]
    session = core["session"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    render_template_string = core["render_template_string"]

    gate = require_admin()
    if gate:
        return gate

    csrf = get_csrf()
    _ensure_locations_headers()

    all_rows = []
    try:
        current_wp = _session_workplace_id()
        allowed_wps = set(_workplace_ids_for_read(current_wp))

        records = Location.query.all() if DB_MIGRATION_MODE else (get_locations() or [])
        for rec in records:
            if isinstance(rec, dict):
                row_wp = (rec.get("Workplace_ID") or rec.get("workplace_id") or "default").strip()
                if row_wp not in allowed_wps:
                    continue

                name = str(rec.get("SiteName") or rec.get("site_name") or rec.get("Site") or "").strip()
                lat = str(rec.get("Lat") or rec.get("lat") or "").strip()
                lon = str(rec.get("Lon") or rec.get("lon") or "").strip()
                rad = str(rec.get("RadiusMeters") or rec.get("radius_meters") or rec.get("Radius") or "").strip()
                act = str(rec.get("Active") or rec.get("active") or "TRUE").strip()
            else:
                row_wp = str(getattr(rec, "workplace_id", "default") or "default").strip()
                if row_wp not in allowed_wps:
                    continue

                name = str(getattr(rec, "site_name", "") or "").strip()
                lat = str(getattr(rec, "lat", "") or "").strip()
                lon = str(getattr(rec, "lon", "") or "").strip()
                rad = str(getattr(rec, "radius_meters", "") or "").strip()
                act = str(getattr(rec, "active", "TRUE") or "TRUE").strip()

            if name:
                all_rows.append({
                    "name": name,
                    "lat": lat,
                    "lon": lon,
                    "rad": rad,
                    "act": act
                })
    except Exception:
        all_rows = []

    def _is_active(v):
        return str(v or "").strip().lower() not in ("false", "0", "no", "n", "off")

    def row_html(s):
        act_on = _is_active(s.get("act", "TRUE"))
        badge = "<span class='chip ok'>Active</span>" if act_on else "<span class='chip warn'>Inactive</span>"
        return f"""
          <tr>
            <td><b>{escape(s.get('name', ''))}</b><div class='sub' style='margin:2px 0 0 0;'>{badge}<div class='sub' style='margin:6px 0 0 0;'><a href='/admin/locations?site={escape(s.get('name', ''))}' style='color:var(--navy);font-weight:600;'>View map</a></div></td>
            <td class='num'>{escape(s.get('lat', ''))}</td>
            <td class='num'>{escape(s.get('lon', ''))}</td>
            <td class='num'>{escape(s.get('rad', ''))}</td>
            <td style='min-width:340px;'>
              <form method="POST" action="/admin/locations/save" style="margin:0; display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
                <input type="hidden" name="csrf" value="{escape(csrf)}">
                <input type="hidden" name="orig_name" value="{escape(s.get('name', ''))}">
                <input class="input" name="name" value="{escape(s.get('name', ''))}" placeholder="Site name" style="margin-top:0; max-width:160px; color:#f8fafc; -webkit-text-fill-color:#f8fafc; caret-color:#f8fafc;">
                <input class="input" name="lat" value="{escape(s.get('lat', ''))}" placeholder="Lat" style="margin-top:0; max-width:120px; color:#f8fafc; -webkit-text-fill-color:#f8fafc; caret-color:#f8fafc;">
                <input class="input" name="lon" value="{escape(s.get('lon', ''))}" placeholder="Lon" style="margin-top:0; max-width:120px; color:#f8fafc; -webkit-text-fill-color:#f8fafc; caret-color:#f8fafc;">
                <input class="input" name="rad" value="{escape(s.get('rad', ''))}" placeholder="Radius m" style="margin-top:0; max-width:110px; color:#f8fafc; -webkit-text-fill-color:#f8fafc; caret-color:#f8fafc;">
                <label class="sub" style="display:flex; align-items:center; gap:8px; margin:0;">
                  <input type="checkbox" name="active" value="yes" {"checked" if act_on else ""}>
                  Active
                </label>
                <button class="btnTiny" type="submit">Save</button>
              </form>
              <form method="POST" action="/admin/locations/deactivate" style="margin-top:8px;">
                <input type="hidden" name="csrf" value="{escape(csrf)}">
                <input type="hidden" name="name" value="{escape(s.get('name', ''))}">
                <button class="btnTiny dark" type="submit">Deactivate</button>
              </form>
            </td>
          </tr>
        """

    table_body = "".join(
        [row_html(r) for r in all_rows]) if all_rows else "<tr><td colspan='5'>No locations yet.</td></tr>"

    # Map preview (no API key): OpenStreetMap embed for selected site
    selected = (request.args.get("site") or "").strip()
    chosen = None
    for rr in all_rows:
        if selected and rr.get("name", "").strip().lower() == selected.lower():
            chosen = rr
            break
    if not chosen and all_rows:
        chosen = all_rows[0]

    map_card = ""
    if chosen:
        try:
            latf = float((chosen.get("lat") or "0").strip())
            lonf = float((chosen.get("lon") or "0").strip())
            delta = 0.006
            left = lonf - delta
            right = lonf + delta
            top = latf + delta
            bottom = latf - delta
            # OSM embed URL
            osm = f"https://www.openstreetmap.org/export/embed.html?bbox={left}%2C{bottom}%2C{right}%2C{top}&layer=mapnik&marker={latf}%2C{lonf}"
            map_card = f"""
              <div class="card" style="padding:12px; margin-top:12px;">
                <h2>Map preview</h2>
                <div class="sub" style="margin-top:6px;">{escape(chosen.get('name', ''))} • {escape(chosen.get('lat', ''))}, {escape(chosen.get('lon', ''))}</div>
                <div style="margin-top:12px; border-radius: 0 !important; overflow:hidden; border:1px solid rgba(11,18,32,.10);">
                  <iframe title="map" src="{osm}" style="width:100%; height:320px; border:0;" loading="lazy"></iframe>
                </div>
                <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
                  <a href="https://www.google.com/maps?q={latf},{lonf}" target="_blank" rel="noopener noreferrer" style="color:var(--navy); font-weight:600;">Open in Google Maps</a>
                  <a href="https://www.openstreetmap.org/?mlat={latf}&mlon={lonf}#map=18/{latf}/{lonf}" target="_blank" rel="noopener noreferrer" style="color:var(--navy); font-weight:600;">Open in OSM</a>
                </div>
              </div>
            """
        except Exception:
            map_card = ""

    content = f"""
      <div class="headerTop">
        <div>
          <h1>Locations</h1>
          <p class="sub">Clock in/out will only work inside an allowed location radius.</p>
        </div>
        <div class="badge admin">ADMIN</div>
      </div>

      {admin_back_link()}

      {map_card}

      <div class="card" style="padding:12px;">
        <h2>Add location</h2>
        <form method="POST" action="/admin/locations/save">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <input type="hidden" name="orig_name" value="">
          <div class="row2">
            <div>
              <label class="sub">Site name</label>
              <input class="input" name="name" placeholder="e.g. Site A" required>
            </div>
            <div>
              <label class="sub">Radius (meters)</label>
              <input class="input" name="rad" placeholder="e.g. 150" required>
            </div>
          </div>
          <div class="row2">
            <div>
              <label class="sub">Latitude</label>
              <input class="input" name="lat" placeholder="e.g. 51.5074" required>
            </div>
            <div>
              <label class="sub">Longitude</label>
              <input class="input" name="lon" placeholder="e.g. -0.1278" required>
            </div>
          </div>
          <label class="sub" style="display:flex; align-items:center; gap:8px; margin-top:10px;">
            <input type="checkbox" name="active" value="yes" checked> Active
          </label>
          <button class="btnSoft" type="submit" style="margin-top:12px;">Add</button>
        </form>
      </div>

      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>All locations</h2>
        <div class="tablewrap" style="margin-top:12px;">
          <table style="min-width:980px;">
            <thead><tr><th>Site</th><th class="num">Lat</th><th class="num">Lon</th><th class="num">Radius (m)</th><th>Manage</th></tr></thead>
            <tbody>{table_body}</tbody>
          </table>
        </div>
        <p class="sub" style="margin-top:10px;">
          Tip: Use your phone’s Google Maps to read the site latitude/longitude (drop a pin → share → coordinates).
        </p>
      </div>
    """
    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )



def admin_back_link(href: str = "/admin") -> str:
    return f"""
      <div style="margin:8px 0 14px;">
        <a href="{href}"
           aria-label="Back"
           title="Back"
           style="
             display:inline-flex;
             align-items:center;
             justify-content:center;
             width:32px;
             height:32px;
             border-radius: 0 !important;
             background:#ffffff;
             border:1px solid #cbd5e1;
             color:#64748b;
             text-decoration:none;
             box-shadow:0 1px 2px rgba(15,23,42,.06);
             font-size:18px;
             font-weight:700;
             line-height:1;
           ">
          &#8249;
        </a>
      </div>
    """
