def work_progress_impl(core):
    require_login = core["require_login"]
    require_csrf = core["require_csrf"]
    get_csrf = core["get_csrf"]
    request = core["request"]
    session = core["session"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    _session_workplace_id = core["_session_workplace_id"]
    _progress_sites_for_current_workplace = core["_progress_sites_for_current_workplace"]
    _list_work_progress_items_for_session = core["_list_work_progress_items_for_session"]
    _store_work_progress_upload = core["_store_work_progress_upload"]
    escape = core["escape"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    admin_back_link = core["admin_back_link"]

    gate = require_login()
    if gate:
        return gate

    role = session.get("role", "employee")
    username = session.get("username", "")
    wp = _session_workplace_id()
    csrf = get_csrf()
    today_str = datetime.now(TZ).date().isoformat()

    msg = ""
    ok = False

    if request.method == "POST":
        require_csrf()

        site = (request.form.get("site") or "").strip()
        shot_date = (request.form.get("shot_date") or today_str).strip()
        note = (request.form.get("note") or "").strip()
        tag = (request.form.get("tag") or "").strip()
        photo = request.files.get("photo")

        if not site:
            msg = "Site is required."
        elif not photo or not getattr(photo, "filename", ""):
            msg = "Please choose a photo."
        else:
            try:
                _store_work_progress_upload(
                    file_storage=photo,
                    username=username,
                    site=site,
                    note=note,
                    tag=tag,
                    shot_date=shot_date,
                )
                ok = True
                msg = "Progress photo uploaded."
            except Exception as e:
                msg = f"Could not upload photo: {e}"

    site_filter = (request.args.get("site") or "").strip()
    tag_filter = (request.args.get("tag") or "").strip()
    user_filter = (request.args.get("user") or "").strip()

    site_suggestions = _progress_sites_for_current_workplace()
    items = _list_work_progress_items_for_session()

    filtered = []
    for item in items:
        if site_filter and str(item.get("site", "")).strip().lower() != site_filter.lower():
            continue
        if tag_filter and tag_filter.lower() not in str(item.get("tag", "")).strip().lower():
            continue
        if user_filter and user_filter.lower() not in str(item.get("username", "")).strip().lower():
            continue
        filtered.append(item)

    filtered = filtered[:120]

    site_options = "".join(
        f'<option value="{escape(site_name)}"></option>'
        for site_name in site_suggestions
    )

    cards = []
    for item in filtered:
        note_html = ""
        tag_html = ""
        if item.get("note"):
            note_html = f'<div class="sub" style="margin-top:8px;">{escape(item["note"])}</div>'
        if item.get("tag"):
            tag_html = f'<span class="chip">{escape(item["tag"])}</span>'

        cards.append(f"""
            <div class="progressCard">
              <a href="{escape(item["file_url"])}" target="_blank" rel="noopener noreferrer" class="progressThumbLink">
                <img src="{escape(item["file_url"])}" alt="Progress photo" class="progressThumb">
              </a>
              <div class="progressMeta">
                <div class="progressTopLine">
                  <div class="progressSite">{escape(item.get("site", ""))}</div>
                  {tag_html}
                </div>
                <div class="sub">Date: <b>{escape(item.get("date", ""))}</b></div>
                <div class="sub">By: <b>{escape(item.get("username", ""))}</b></div>
                {note_html}
                <div style="margin-top:10px;">
                  <a class="btnTiny" href="{escape(item["file_url"])}" target="_blank" rel="noopener noreferrer">Open full image</a>
                </div>
              </div>
            </div>
        """)

    gallery_html = "".join(cards) if cards else """
      <div class="sub">No progress photos found for this workplace yet.</div>
    """

    back_href = "/admin" if role in ("admin", "master_admin") else "/"
    badge = "ADMIN" if role in ("admin", "master_admin") else "EMPLOYEE"

    content = f"""
      <style>
        .progressFilters {{
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
          gap:10px;
          align-items:end;
        }}

        .progressGrid {{
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
          gap:14px;
        }}

        .progressCard {{
          background:#fff;
          border:1px solid rgba(15,23,42,.08);
          box-shadow:0 8px 18px rgba(15,23,42,.06);
          overflow:hidden;
        }}

        .progressThumb {{
          width:100%;
          height:240px;
          object-fit:cover;
          display:block;
          background:#f8fafc;
        }}

        .progressThumbLink {{
          display:block;
          text-decoration:none;
        }}

        .progressMeta {{
          padding:12px;
        }}

        .progressTopLine {{
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:10px;
          margin-bottom:8px;
        }}

        .progressSite {{
          font-weight:700;
          color:#0f172a;
        }}

        .chip {{
          display:inline-flex;
          align-items:center;
          padding:4px 8px;
          border-radius:999px;
          font-size:12px;
          font-weight:700;
          background:#eef4fb;
          color:#3b74ad;
          border:1px solid rgba(59,116,173,.18);
        }}
      </style>

      <div class="headerTop">
        <div>
          <h1>Work Progress</h1>
          <p class="sub">Upload and review site progress photos for workplace <b>{escape(wp)}</b>.</p>
        </div>
        <div class="badge admin">{badge}</div>
      </div>

      {admin_back_link(back_href)}

      {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
      {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

      <div class="card" style="padding:12px;">
        <h2>Add progress photo</h2>
        <form method="POST" enctype="multipart/form-data" style="margin-top:12px;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">

          <div class="progressFilters">
            <div>
              <label class="sub">Site</label>
              <input class="input" name="site" list="workProgressSites" value="" placeholder="e.g. Kennington" required>
              <datalist id="workProgressSites">{site_options}</datalist>
            </div>

            <div>
              <label class="sub">Date</label>
              <input class="input" type="date" name="shot_date" value="{escape(today_str)}" required>
            </div>

            <div>
              <label class="sub">Tag</label>
              <input class="input" name="tag" placeholder="e.g. brickwork">
            </div>

            <div>
              <label class="sub">Photo</label>
              <input class="input" type="file" name="photo" accept="image/*" required>
            </div>
          </div>

          <label class="sub" style="margin-top:10px;">Note</label>
          <textarea class="input" name="note" rows="3" placeholder="What was completed today?"></textarea>

          <button class="btnSoft" type="submit" style="margin-top:12px;">Add progress photo</button>
        </form>
      </div>

      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>Gallery</h2>

        <form method="GET" class="progressFilters" style="margin-top:12px;">
          <div>
            <label class="sub">Site</label>
            <input class="input" name="site" list="workProgressSites" value="{escape(site_filter)}" placeholder="all sites">
          </div>

          <div>
            <label class="sub">Tag</label>
            <input class="input" name="tag" value="{escape(tag_filter)}" placeholder="optional tag">
          </div>

          <div>
            <label class="sub">Uploaded by</label>
            <input class="input" name="user" value="{escape(user_filter)}" placeholder="optional username">
          </div>

          <div>
            <button class="btnSoft" type="submit">Apply</button>
          </div>
        </form>

        <div class="progressGrid" style="margin-top:14px;">
          {gallery_html}
        </div>
      </div>
    """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("work-progress", role, content)
    )