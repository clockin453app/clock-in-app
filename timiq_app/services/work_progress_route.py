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
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    render_page = core["render_page"]
    admin_back_link = core["admin_back_link"]
    jsonify = core["jsonify"]
    os = core["os"]
    import io
    import re
    import zipfile
    from flask import send_file

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

    def find_entries(item_ids):
        wanted = {str(x or "").strip() for x in (item_ids or []) if str(x or "").strip()}
        entries = _load_work_progress_index()
        matches = []

        for idx, entry in enumerate(entries):
            entry_id = str(entry.get("id") or "").strip()
            if not entry_id or entry_id not in wanted:
                continue

            entry_wp = str(entry.get("workplace_id") or "").strip() or "default"
            if role != "master_admin" and entry_wp != wp:
                continue

            matches.append((idx, entry))

        return entries, matches

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

        elif action == "bulk_delete":
            if not is_admin:
                return ajax_response(False, "Admin only.", 403) if is_ajax else ("Admin only.", 403)

            selected_ids = request.form.getlist("selected_ids")
            entries, matches = find_entries(selected_ids)

            if not matches:
                msg = "No photos selected."
                ok = False
            else:
                delete_paths = []
                for _, entry in matches:
                    relpath = str(entry.get("relpath") or "").strip()
                    full_path = _resolve_work_progress_file_path(relpath, enforce_workplace=False)
                    if full_path:
                        delete_paths.append(full_path)

                for idx, _entry in sorted(matches, key=lambda x: x[0], reverse=True):
                    entries.pop(idx)

                _save_work_progress_index(entries)

                for full_path in delete_paths:
                    try:
                        if os.path.exists(full_path):
                            os.remove(full_path)
                    except Exception:
                        pass

                msg = f"{len(matches)} progress photo(s) deleted."
                ok = True

            if is_ajax:
                return ajax_response(ok, msg, 200 if ok else 400)


        elif action == "bulk_download":
            selected_ids = request.form.getlist("selected_ids")
            _entries, matches = find_entries(selected_ids)

            if not matches:
                msg = "No photos selected."
                ok = False
                if is_ajax:
                    return ajax_response(ok, msg, 400)
            else:
                archive_buffer = io.BytesIO()
                used_names = {}
                added = 0

                with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for _idx, entry in matches:
                        relpath = str(entry.get("relpath") or "").strip()
                        full_path = _resolve_work_progress_file_path(relpath, enforce_workplace=False)

                        if not full_path or not os.path.exists(full_path):
                            continue

                        site_part = _work_progress_safe_text(str(entry.get("site") or "site"), 40) or "site"
                        date_part = _work_progress_safe_text(str(entry.get("date") or today_str), 20) or today_str
                        user_part = _work_progress_safe_text(str(entry.get("username") or "user"), 40) or "user"
                        ext = os.path.splitext(full_path)[1] or ".jpg"

                        base_name = re.sub(
                            r"[^A-Za-z0-9._-]+",
                            "_",
                            f"{date_part}_{site_part}_{user_part}{ext}"
                        )

                        if base_name in used_names:
                            used_names[base_name] += 1
                            stem, ext2 = os.path.splitext(base_name)
                            arcname = f"{stem}_{used_names[base_name]}{ext2}"
                        else:
                            used_names[base_name] = 1
                            arcname = base_name

                        zf.write(full_path, arcname=arcname)
                        added += 1

                if added <= 0:
                    msg = "No files available for download."
                    ok = False
                    if is_ajax:
                        return ajax_response(ok, msg, 400)
                else:
                    archive_buffer.seek(0)
                    zip_name = f"work_progress_{wp}_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.zip"
                    return send_file(
                        archive_buffer,
                        mimetype="application/zip",
                        as_attachment=True,
                        download_name=zip_name
                    )


        elif action == "bulk_edit":
            if not is_admin:
                return ajax_response(False, "Admin only.", 403) if is_ajax else ("Admin only.", 403)

            selected_ids = request.form.getlist("selected_ids")
            bulk_site_raw = (request.form.get("bulk_site") or "").strip()
            bulk_tag_raw = (request.form.get("bulk_tag") or "").strip()

            entries, matches = find_entries(selected_ids)
            normalized_bulk_site = normalize_selected_site(bulk_site_raw) if bulk_site_raw else ""
            bulk_tag_clean = _work_progress_safe_text(bulk_tag_raw, 50)

            if not matches:
                msg = "No photos selected."
                ok = False
            elif not normalized_bulk_site and not bulk_tag_clean:
                msg = "Choose a site or enter a tag for bulk edit."
                ok = False
            else:
                for idx, _entry in matches:
                    if normalized_bulk_site:
                        entries[idx]["site"] = _work_progress_safe_text(normalized_bulk_site, 80)
                    if bulk_tag_clean:
                        entries[idx]["tag"] = bulk_tag_clean

                _save_work_progress_index(entries)
                msg = f"{len(matches)} progress photo(s) updated."
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
        item_id_raw = str(item.get("id", ""))
        item_site_raw = str(item.get("site", ""))
        item_date_raw = str(item.get("date", ""))
        item_user_raw = str(item.get("username", ""))
        item_tag_raw = str(item.get("tag", ""))
        item_note_raw = str(item.get("note", ""))

        item_id = escape(item_id_raw)
        item_site = escape(item_site_raw)
        item_date = escape(item_date_raw)
        item_user = escape(item_user_raw)
        item_tag = escape(item_tag_raw)
        item_note = escape(item_note_raw)
        item_note_attr = escape(item_note_raw).replace("\n", "&#10;")
        item_url = escape(item["file_url"])

        note_html = ""
        tag_html = ""

        select_html = ""
        if is_admin:
            select_html = f"""
                        <label class="progressSelectBox">
                          <input
                            type="checkbox"
                            class="progressBulkCheck"
                            name="selected_ids"
                            form="progressBulkActionForm"
                            value="{item_id}">
                          <span>Select</span>
                        </label>
                    """

            card_class = "progressCard progressCardSelectable" if is_admin else "progressCard"

            cards.append(f"""
                <div class="{card_class}">
              {select_html}
              <a href="{item_url}" target="_blank" rel="noopener noreferrer" class="progressThumbLink">
                <img src="{item_url}" alt="Progress photo" class="progressThumb">
              </a>
              <div class="progressMeta">
                <div class="progressSite">{item_site}</div>
                <div class="progressSubLine">{item_date}</div>
                <div class="progressSubLine">By: {item_user}</div>
              </div>
            </div>
        """)

    gallery_html = "".join(cards) if cards else """
      <div class="sub">No progress photos found for this workplace yet.</div>
    """

    back_href = "/admin" if is_admin else "/"
    badge = "ADMIN" if is_admin else "EMPLOYEE"

    return render_page(
        template_name="admin_tools/work_progress.html",
        active="work-progress",
        role=role,
        layout_shell=layout_shell,
        style=STYLE,
        viewport=VIEWPORT,
        pwa_tags=PWA_TAGS,
        workplace_id=wp,
        csrf=csrf,
        today_str=today_str,
        msg=msg,
        ok=ok,
        is_admin=is_admin,
        page_back_html=admin_back_link(back_href),
        upload_site_options=upload_site_options,
        filter_site_options=filter_site_options,
        tag_filter=tag_filter,
        user_filter=user_filter,
        gallery_html=gallery_html,
    )
