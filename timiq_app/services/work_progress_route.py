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
    _load_work_progress_index = core["_load_work_progress_index"]
    _save_work_progress_index = core["_save_work_progress_index"]
    _resolve_work_progress_file_path = core["_resolve_work_progress_file_path"]
    _work_progress_safe_text = core["_work_progress_safe_text"]
    _normalize_work_progress_date = core["_normalize_work_progress_date"]
    escape = core["escape"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    admin_back_link = core["admin_back_link"]
    jsonify = core["jsonify"]
    os = core["os"]

    gate = require_login()
    if gate:
        return gate

    role = session.get("role", "employee")
    is_admin = role in ("admin", "master_admin")
    username = session.get("username", "")
    wp = _session_workplace_id()
    csrf = get_csrf()
    today_str = datetime.now(TZ).date().isoformat()

    msg = ""
    ok = False

    def ajax_response(ok_flag: bool, text: str, status: int = 200, **extra):
        payload = {"ok": bool(ok_flag), "message": str(text or "")}
        payload.update(extra)
        return jsonify(payload), status

    def find_entry(item_id: str):
        entries = _load_work_progress_index()
        for idx, entry in enumerate(entries):
            if str(entry.get("id") or "") != str(item_id or ""):
                continue
            entry_wp = str(entry.get("workplace_id") or "").strip() or "default"
            if role != "master_admin" and entry_wp != wp:
                continue
            return entries, idx, entry
        return None, None, None

    site_suggestions = _progress_sites_for_current_workplace()

    valid_site_names = {
        str(site_name).strip().lower(): str(site_name).strip()
        for site_name in site_suggestions
        if str(site_name).strip()
    }

    def normalize_selected_site(raw_value: str) -> str:
        return valid_site_names.get(str(raw_value or "").strip().lower(), "")

    def render_site_select_options(selected_value: str = "", include_all: bool = False) -> str:
        selected_norm = normalize_selected_site(selected_value)
        parts = []

        if include_all:
            parts.append(
                f'<option value="" {"selected" if not selected_norm else ""}>All sites</option>'
            )
        else:
            parts.append('<option value="">Choose site</option>')

        for site_name in site_suggestions:
            site_esc = escape(site_name)
            sel = "selected" if selected_norm == site_name else ""
            parts.append(f'<option value="{site_esc}" {sel}>{site_esc}</option>')

        return "".join(parts)



    if request.method == "POST":
        require_csrf()
        is_ajax = (request.headers.get("X-Requested-With") or "").strip().lower() == "xmlhttprequest"
        action = (request.form.get("action") or "upload").strip().lower()

        if action == "edit":
            if not is_admin:
                return ajax_response(False, "Admin only.", 403) if is_ajax else ("Admin only.", 403)

            item_id = (request.form.get("item_id") or "").strip()
            edit_site = (request.form.get("edit_site") or "").strip()
            edit_date = (request.form.get("edit_date") or today_str).strip()
            edit_tag = (request.form.get("edit_tag") or "").strip()
            edit_note = (request.form.get("edit_note") or "").strip()

            entries, idx, entry = find_entry(item_id)
            normalized_edit_site = normalize_selected_site(edit_site)

            if idx is None:
                msg = "Progress photo not found."
                ok = False
            elif not normalized_edit_site:
                msg = "Please choose a valid site from the dropdown."
                ok = False
            else:
                normalized_date, _ = _normalize_work_progress_date(edit_date)
                entries[idx]["site"] = _work_progress_safe_text(normalized_edit_site, 80)

                entries[idx]["date"] = normalized_date
                entries[idx]["tag"] = _work_progress_safe_text(edit_tag, 50)
                entries[idx]["note"] = _work_progress_safe_text(edit_note, 500)
                _save_work_progress_index(entries)
                msg = "Progress photo updated."
                ok = True

            if is_ajax:
                return ajax_response(ok, msg, 200 if ok else 400)

        elif action == "delete":
            if not is_admin:
                return ajax_response(False, "Admin only.", 403) if is_ajax else ("Admin only.", 403)

            item_id = (request.form.get("item_id") or "").strip()
            entries, idx, entry = find_entry(item_id)

            if idx is None:
                msg = "Progress photo not found."
                ok = False
            else:
                relpath = str(entry.get("relpath") or "").strip()
                full_path = _resolve_work_progress_file_path(relpath, enforce_workplace=False)

                entries.pop(idx)
                _save_work_progress_index(entries)

                try:
                    if full_path and os.path.exists(full_path):
                        os.remove(full_path)
                except Exception:
                    pass

                msg = "Progress photo deleted."
                ok = True

            if is_ajax:
                return ajax_response(ok, msg, 200 if ok else 400)

        else:
            site = (request.form.get("site") or "").strip()
            shot_date = (request.form.get("shot_date") or today_str).strip()
            note = (request.form.get("note") or "").strip()
            tag = (request.form.get("tag") or "").strip()

            photos = [
                f for f in request.files.getlist("photo")
                if f and getattr(f, "filename", "")
            ]

            normalized_site = normalize_selected_site(site)

            if not normalized_site:
                msg = "Please choose a valid site from the dropdown."
                ok = False
            elif not photos:
                msg = "Please choose at least one photo."
                ok = False
            else:
                site = normalized_site


                uploaded_count = 0
                failed = []

                for photo in photos:
                    try:
                        _store_work_progress_upload(
                            file_storage=photo,
                            username=username,
                            site=site,
                            note=note,
                            tag=tag,
                            shot_date=shot_date,
                        )
                        uploaded_count += 1
                    except Exception as e:
                        failed.append(f"{getattr(photo, 'filename', 'photo')}: {e}")

                if uploaded_count and not failed:
                    ok = True
                    msg = f"{uploaded_count} progress photo(s) uploaded."
                elif uploaded_count:
                    ok = True
                    msg = f"{uploaded_count} uploaded, {len(failed)} failed."
                else:
                    ok = False
                    msg = failed[0] if failed else "Could not upload photos."

            if is_ajax:
                return ajax_response(ok, msg, 200 if ok else 400)

    site_filter = (request.args.get("site") or "").strip()
    tag_filter = (request.args.get("tag") or "").strip()
    user_filter = (request.args.get("user") or "").strip()


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


    upload_site_options = render_site_select_options()
    filter_site_options = render_site_select_options(site_filter, include_all=True)

    cards = []
    for item in filtered:
        item_id = escape(str(item.get("id", "")))
        item_site = escape(str(item.get("site", "")))
        item_date = escape(str(item.get("date", "")))
        item_user = escape(str(item.get("username", "")))
        item_tag = escape(str(item.get("tag", "")))
        item_note = escape(str(item.get("note", "")))
        item_url = escape(item["file_url"])

        note_html = f'<div class="progressNote">{item_note}</div>' if item.get("note") else ""
        tag_html = f'<span class="chip">{item_tag}</span>' if item.get("tag") else ""

        admin_tools_html = ""
        if is_admin:
            admin_tools_html = f"""
                <details class="progressAdminTools">
                  <summary>Edit</summary>

                  <form method="POST" class="progressAdminForm" style="margin-top:8px;">
                    <input type="hidden" name="csrf" value="{escape(csrf)}">
                    <input type="hidden" name="action" value="edit">
                    <input type="hidden" name="item_id" value="{item_id}">

                    <label class="sub">Site</label>
                    <select class="input" name="edit_site" required>
                      {render_site_select_options(item.get("site", ""))}
                    </select>

                    <label class="sub" style="margin-top:8px;">Date</label>
                    <input class="input" type="date" name="edit_date" value="{item_date}" required>

                    <label class="sub" style="margin-top:8px;">Tag</label>
                    <input class="input" type="text" name="edit_tag" value="{item_tag}">

                    <label class="sub" style="margin-top:8px;">Note</label>
                    <textarea class="input" name="edit_note" rows="3">{item_note}</textarea>

                    <button class="btnTiny" type="submit" style="margin-top:8px;">Save</button>
                  </form>

                  <form method="POST" style="margin-top:8px;" onsubmit="return confirm('Delete this photo?');">
                    <input type="hidden" name="csrf" value="{escape(csrf)}">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="item_id" value="{item_id}">
                    <button class="btnTiny" type="submit">Delete</button>
                  </form>
                </details>
            """

        cards.append(f"""
            <div class="progressCard">
              <a href="{item_url}" target="_blank" rel="noopener noreferrer" class="progressThumbLink">
                <img src="{item_url}" alt="Progress photo" class="progressThumb">
              </a>
              <div class="progressMeta">
                <div class="progressSite">{item_site}</div>
                <div class="progressSubLine">{item_date}</div>
                <div class="progressSubLine">By: {item_user}</div>
                <div style="margin-top:6px;">{tag_html}</div>
                {note_html}
                <div class="progressActions">
                  <a class="btnTiny" href="{item_url}" target="_blank" rel="noopener noreferrer">Open</a>
                </div>
                {admin_tools_html}
              </div>
            </div>
        """)

    gallery_html = "".join(cards) if cards else """
      <div class="sub">No progress photos found for this workplace yet.</div>
    """

    back_href = "/admin" if is_admin else "/"
    badge = "ADMIN" if is_admin else "EMPLOYEE"

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
          grid-template-columns:repeat(auto-fill,minmax(170px,170px));
          gap:12px;
          align-items:start;
        }}

        .progressCard {{
          background:#fff;
          border:1px solid rgba(15,23,42,.08);
          box-shadow:0 6px 14px rgba(15,23,42,.05);
          overflow:hidden;
          padding:8px;
        }}

        .progressThumb {{
          width:100%;
          aspect-ratio:1 / 1;
          height:auto;
          object-fit:cover;
          display:block;
          background:#f8fafc;
          border:1px solid rgba(15,23,42,.08);
        }}

        .progressThumbLink {{
          display:block;
          text-decoration:none;
        }}

        .progressMeta {{
          padding-top:8px;
        }}

        .progressSite {{
          font-weight:700;
          color:#0f172a;
          font-size:14px;
          line-height:1.2;
        }}

        .progressSubLine {{
          margin-top:4px;
          font-size:12px;
          color:#64748b;
          line-height:1.3;
        }}

        .progressNote {{
          margin-top:6px;
          font-size:12px;
          color:#334155;
          line-height:1.35;
          max-height:48px;
          overflow:hidden;
        }}

        .progressActions {{
          margin-top:8px;
          display:flex;
          gap:6px;
          flex-wrap:wrap;
        }}

        .chip {{
          display:inline-flex;
          align-items:center;
          padding:3px 7px;
          border-radius:999px;
          font-size:11px;
          font-weight:700;
          background:#eef4fb;
          color:#3b74ad;
          border:1px solid rgba(59,116,173,.18);
        }}


        .progressAdminTools {{
          margin-top:8px;
          border-top:1px solid rgba(15,23,42,.08);
          padding-top:8px;
        }}

        .progressAdminTools summary {{
          cursor:pointer;
          font-size:12px;
          font-weight:700;
          color:#3b74ad;
        }}

        .progressAdminForm .input {{
          width:100%;
        }}

        #progressUploadStatus {{
          display:none;
          margin-top:10px;
          font-weight:700;
          color:#3b74ad;
        }}

        @media (max-width: 640px) {{
          .progressGrid {{
            grid-template-columns:repeat(auto-fill,minmax(140px,140px));
            gap:10px;
          }}
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
        <h2>Add progress photos</h2>
        <form method="POST" enctype="multipart/form-data" id="progressUploadForm" style="margin-top:12px;">
          <input type="hidden" name="csrf" value="{escape(csrf)}">
          <input type="hidden" name="action" value="upload">

          <div class="progressFilters">
                        <div>
              <label class="sub">Site</label>
              <select class="input" name="site" required>
                {upload_site_options}
              </select>
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
              <label class="sub">Photos</label>
              <input class="input" type="file" name="photo" accept="image/*" multiple required>
            </div>
          </div>

          <label class="sub" style="margin-top:10px;">Note</label>
          <textarea class="input" name="note" rows="3" placeholder="What was completed today?"></textarea>

          <button class="btnSoft" type="submit" style="margin-top:12px;">Add progress photos</button>
          <div id="progressUploadStatus"></div>
        </form>
      </div>

      <div class="card" style="padding:12px; margin-top:12px;">
        <h2>Gallery</h2>

        <form method="GET" class="progressFilters" style="margin-top:12px;">
                    <div>
            <label class="sub">Site</label>
            <select class="input" name="site">
              {filter_site_options}
            </select>
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

      <script>
        (function() {{
          const form = document.getElementById("progressUploadForm");
          if (!form) return;

          const fileInput = form.querySelector('input[name="photo"]');
          const statusEl = document.getElementById("progressUploadStatus");

          form.addEventListener("submit", async function(e) {{
            const files = Array.from((fileInput && fileInput.files) || []).filter(Boolean);
            if (!files.length) return;

            e.preventDefault();

            const csrf = form.querySelector('input[name="csrf"]').value;
            const site = form.querySelector('select[name="site"]').value.trim();
            const shotDate = form.querySelector('input[name="shot_date"]').value.trim();
            const tag = form.querySelector('input[name="tag"]').value.trim();
            const note = form.querySelector('textarea[name="note"]').value || "";
            const submitBtn = form.querySelector('button[type="submit"]');

            if (!site || !shotDate) {{
              form.submit();
              return;
            }}

            if (submitBtn) submitBtn.disabled = true;
            statusEl.style.display = "block";

            let okCount = 0;
            let failCount = 0;

            for (let i = 0; i < files.length; i++) {{
              const fd = new FormData();
              fd.append("csrf", csrf);
              fd.append("action", "upload");
              fd.append("site", site);
              fd.append("shot_date", shotDate);
              fd.append("tag", tag);
              fd.append("note", note);
              fd.append("photo", files[i], files[i].name);

              statusEl.textContent = "Uploading " + (i + 1) + " of " + files.length + ": " + files[i].name;

              try {{
                const res = await fetch(window.location.pathname, {{
                  method: "POST",
                  body: fd,
                  credentials: "same-origin",
                  headers: {{
                    "X-Requested-With": "XMLHttpRequest"
                  }}
                }});

                const data = await res.json().catch(function() {{
                  return {{ ok: false, message: "Upload failed." }};
                }});

                if (res.ok && data.ok) {{
                  okCount += 1;
                }} else {{
                  failCount += 1;
                }}
              }} catch (err) {{
                failCount += 1;
              }}
            }}

            statusEl.textContent = "Uploaded " + okCount + " of " + files.length + (failCount ? (" • Failed: " + failCount) : "") + " • Refreshing...";
            window.location.reload();
          }});
        }})();
      </script>
    """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("work-progress", role, content)
    )