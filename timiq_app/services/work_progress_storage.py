import os


def build_work_progress_storage_runtime(core):
    os_mod = core["os"]
    json_mod = core["json"]
    io_mod = core["io"]
    time_mod = core["time"]
    secrets_mod = core["secrets"]
    datetime_cls = core["datetime"]
    timedelta_cls = core["timedelta"]
    url_for_func = core["url_for"]
    session_obj = core["session"]
    TZ = core["TZ"]
    BASE_DIR = core["BASE_DIR"]
    secure_filename_func = core["secure_filename"]
    validate_upload_file_func = core["validate_upload_file"]
    get_user_drive_service_func = core["get_user_drive_service"]
    get_service_account_drive_service_func = core["get_service_account_drive_service"]
    UPLOAD_FOLDER_ID = core["UPLOAD_FOLDER_ID"]
    MediaIoBaseUpload = core["MediaIoBaseUpload"]
    Image = core["Image"]
    ImageOps = core["ImageOps"]
    _session_workplace_id = core["_session_workplace_id"]
    _get_active_locations = core["_get_active_locations"]
    _workplace_ids_for_read = core["_workplace_ids_for_read"]

    WORK_PROGRESS_BASE_DIR = os_mod.path.join(
        os_mod.environ.get(
            "CLOCK_SELFIE_BASE_DIR",
            os_mod.path.join(BASE_DIR, "instance"),
        ).strip(),
        "work_progress",
    )
    WORK_PROGRESS_INDEX_PATH = os_mod.path.join(WORK_PROGRESS_BASE_DIR, "_index.json")
    WORK_PROGRESS_MAX_BYTES = int(
        os_mod.environ.get("WORK_PROGRESS_MAX_BYTES", str(8 * 1024 * 1024)) or str(8 * 1024 * 1024)
    )
    _ALLOWED_WORK_PROGRESS_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
    _ALLOWED_WORK_PROGRESS_MIMES = {
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/octet-stream",
    }
    WORK_PROGRESS_IMAGE_MAX_DIM = int(os_mod.environ.get("WORK_PROGRESS_IMAGE_MAX_DIM", "1600") or "1600")
    WORK_PROGRESS_IMAGE_QUALITY = int(os_mod.environ.get("WORK_PROGRESS_IMAGE_QUALITY", "82") or "82")

    WORK_PROGRESS_AUTO_ARCHIVE_ENABLED = str(
        os_mod.environ.get("WORK_PROGRESS_AUTO_ARCHIVE_ENABLED", "false") or "false"
    ).strip().lower() in ("1", "true", "yes", "on")

    WORK_PROGRESS_ARCHIVE_DAYS = int(
        os_mod.environ.get("WORK_PROGRESS_ARCHIVE_DAYS", "30") or "30"
    )

    WORK_PROGRESS_AUTO_ARCHIVE_INTERVAL_S = int(
        os_mod.environ.get("WORK_PROGRESS_AUTO_ARCHIVE_INTERVAL_S", "86400") or "86400"
    )

    def _ensure_work_progress_storage():
        os_mod.makedirs(WORK_PROGRESS_BASE_DIR, exist_ok=True)

    def _work_progress_folder_name(value: str) -> str:
        return secure_filename_func(str(value or "").strip()) or "default"

    def _work_progress_safe_text(value: str, limit: int = 200) -> str:
        return str(value or "").strip()[:limit]

    def _normalize_work_progress_date(value: str) -> tuple[str, str]:
        raw = (value or "").strip()
        try:
            d = datetime_cls.strptime(raw, "%Y-%m-%d").date()
        except Exception:
            d = datetime_cls.now(TZ).date()
        return d.isoformat(), d.strftime("%Y-%m")

    def _progress_sites_for_current_workplace() -> list[str]:
        sites = []
        seen = set()

        for rec in (_get_active_locations() or []):
            name = str(
                rec.get("SiteName")
                or rec.get("site_name")
                or rec.get("name")
                or rec.get("site")
                or ""
            ).strip()

            if not name:
                continue

            low = name.lower()
            if low in seen:
                continue

            seen.add(low)
            sites.append(name)

        return sorted(sites, key=str.lower)

    def _load_work_progress_index() -> list[dict]:
        _ensure_work_progress_storage()

        if not os_mod.path.exists(WORK_PROGRESS_INDEX_PATH):
            return []

        try:
            with open(WORK_PROGRESS_INDEX_PATH, "r", encoding="utf-8") as fh:
                data = json_mod.load(fh)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_work_progress_index(entries: list[dict]):
        _ensure_work_progress_storage()

        tmp_path = WORK_PROGRESS_INDEX_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json_mod.dump(entries, fh, ensure_ascii=False, indent=2)

        os_mod.replace(tmp_path, WORK_PROGRESS_INDEX_PATH)

    def _resolve_work_progress_file_path(relpath: str, enforce_workplace: bool = True) -> str | None:
        raw = str(relpath or "").replace("\\", "/").strip().lstrip("/")
        if not raw:
            return None

        normalized = os_mod.path.normpath(raw).replace("\\", "/")
        if normalized.startswith("../") or normalized == "..":
            return None

        parts = [p for p in normalized.split("/") if p not in ("", ".")]
        if len(parts) < 3:
            return None

        if enforce_workplace and session_obj.get("role") != "master_admin":
            expected_wp = _work_progress_folder_name(_session_workplace_id())
            if parts[0] != expected_wp:
                return None

        base_path = os_mod.path.abspath(WORK_PROGRESS_BASE_DIR)
        full_path = os_mod.path.abspath(os_mod.path.join(base_path, *parts))

        if not full_path.startswith(base_path + os_mod.sep):
            return None

        return full_path

    def _optimize_work_progress_image(file_bytes: bytes, detected_mime: str, safe_name: str) -> tuple[bytes, str, str]:
        if Image is None or ImageOps is None:
            return file_bytes, detected_mime, safe_name

        try:
            with Image.open(io_mod.BytesIO(file_bytes)) as img:
                img = ImageOps.exif_transpose(img)

                if img.mode not in ("RGB", "L"):
                    alpha = None
                    if "A" in img.getbands():
                        alpha = img.getchannel("A")
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    bg.paste(img.convert("RGBA"), mask=alpha)
                    img = bg
                elif img.mode == "L":
                    img = img.convert("RGB")
                else:
                    img = img.convert("RGB")

                max_dim = max(400, int(WORK_PROGRESS_IMAGE_MAX_DIM or 1600))
                resample_owner = getattr(Image, "Resampling", Image)
                resample_filter = getattr(resample_owner, "LANCZOS", getattr(Image, "LANCZOS", 3))
                img.thumbnail((max_dim, max_dim), resample_filter)

                quality = max(55, min(95, int(WORK_PROGRESS_IMAGE_QUALITY or 82)))

                out = io_mod.BytesIO()
                img.save(
                    out,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=True,
                )

                base_name = os_mod.path.splitext(
                    secure_filename_func(safe_name or "progress.jpg")
                )[0] or "progress"
                final_name = f"{base_name}.jpg"
                return out.getvalue(), "image/jpeg", final_name
        except Exception:
            return file_bytes, detected_mime, safe_name

    def _store_work_progress_upload(file_storage, username: str, site: str, note: str, tag: str, shot_date: str) -> dict:
        wp = _session_workplace_id()
        wp_folder = _work_progress_folder_name(wp)

        site_clean = _work_progress_safe_text(site, 80)
        note_clean = _work_progress_safe_text(note, 500)
        tag_clean = _work_progress_safe_text(tag, 50)
        shot_date_clean, month_key = _normalize_work_progress_date(shot_date)

        original_bytes, detected_mime, safe_name = validate_upload_file_func(
            file_storage,
            WORK_PROGRESS_MAX_BYTES,
            _ALLOWED_WORK_PROGRESS_EXTS,
            _ALLOWED_WORK_PROGRESS_MIMES,
        )

        file_bytes, detected_mime, safe_name = _optimize_work_progress_image(
            original_bytes,
            detected_mime,
            safe_name,
        )

        month_folder = _work_progress_folder_name(month_key)
        final_name = f"{secrets_mod.token_hex(8)}_{secure_filename_func(safe_name or 'progress.jpg')}"
        relpath = f"{wp_folder}/{month_folder}/{final_name}"

        full_dir = os_mod.path.join(WORK_PROGRESS_BASE_DIR, wp_folder, month_folder)
        os_mod.makedirs(full_dir, exist_ok=True)

        full_path = os_mod.path.join(full_dir, final_name)
        with open(full_path, "wb") as fh:
            fh.write(file_bytes)

        entries = _load_work_progress_index()

        record = {
            "id": secrets_mod.token_hex(12),
            "workplace_id": wp,
            "site": site_clean,
            "date": shot_date_clean,
            "username": str(username or "").strip(),
            "note": note_clean,
            "tag": tag_clean,
            "relpath": relpath,
            "mime_type": detected_mime,
            "storage": "local",
            "archive_url": "",
            "original_bytes": len(original_bytes),
            "stored_bytes": len(file_bytes),
            "created_at": datetime_cls.now(TZ).isoformat(timespec="seconds"),
        }

        entries.append(record)
        _save_work_progress_index(entries)

        try:
            _maybe_run_auto_work_progress_archive()
        except Exception:
            pass

        return record

    def _list_work_progress_items_for_session() -> list[dict]:
        current_wp = _session_workplace_id()
        expected_wp = _work_progress_folder_name(current_wp)

        items = []
        for item in _load_work_progress_index():
            item_wp = _work_progress_folder_name(item.get("workplace_id", "default"))
            if item_wp != expected_wp:
                continue

            storage = str(item.get("storage") or "local").strip().lower()
            archive_url = str(item.get("archive_url") or "").strip()

            if storage == "drive" and archive_url:
                row = dict(item)
                row["file_url"] = archive_url
                items.append(row)
                continue

            relpath = str(item.get("relpath") or "").strip()
            full_path = _resolve_work_progress_file_path(relpath, enforce_workplace=False)
            if not full_path or not os_mod.path.exists(full_path):
                continue

            row = dict(item)
            row["file_url"] = url_for_func("view_work_progress_file", relpath=relpath)
            items.append(row)

        items.sort(
            key=lambda x: (
                str(x.get("date", "")),
                str(x.get("created_at", "")),
            ),
            reverse=True,
        )
        return items

    def _get_work_progress_archive_drive_service():
        drive_service = get_user_drive_service_func()
        if not drive_service:
            drive_service = get_service_account_drive_service_func()
        if not drive_service:
            raise RuntimeError("Drive archive is not available.")
        return drive_service

    def _drive_find_or_create_folder(drive_service, folder_name: str, parent_id: str | None = None) -> str:
        safe_name = str(folder_name or "").strip()
        if not safe_name:
            raise RuntimeError("Folder name required.")

        safe_name_q = safe_name.replace("'", "\\'")

        q_parts = [
            "mimeType='application/vnd.google-apps.folder'",
            f"name='{safe_name_q}'",
            "trashed=false",
        ]
        if parent_id:
            q_parts.append(f"'{parent_id}' in parents")

        res = drive_service.files().list(
            q=" and ".join(q_parts),
            fields="files(id,name)",
            pageSize=10,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        files = res.get("files", [])
        if files:
            return files[0]["id"]

        body = {
            "name": safe_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            body["parents"] = [parent_id]

        created = drive_service.files().create(
            body=body,
            fields="id,name",
            supportsAllDrives=True,
        ).execute()

        return created["id"]

    def _upload_local_work_progress_to_archive(local_file_path: str, workplace_id: str, month_key: str, site_name: str) -> str:
        drive_service = _get_work_progress_archive_drive_service()

        root_id = _drive_find_or_create_folder(drive_service, "Work Progress Archive")
        wp_id = _drive_find_or_create_folder(drive_service, workplace_id, root_id)
        month_id = _drive_find_or_create_folder(drive_service, month_key, wp_id)
        site_id = _drive_find_or_create_folder(
            drive_service,
            _work_progress_folder_name(site_name or "site"),
            month_id,
        )

        filename = os_mod.path.basename(local_file_path)
        ext = os_mod.path.splitext(filename)[1].lower()
        mime_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(ext, "application/octet-stream")

        with open(local_file_path, "rb") as fh:
            media = MediaIoBaseUpload(io_mod.BytesIO(fh.read()), mimetype=mime_type, resumable=False)

        created = drive_service.files().create(
            body={
                "name": filename,
                "parents": [site_id],
            },
            media_body=media,
            fields="id,webViewLink",
            supportsAllDrives=True,
        ).execute()

        file_id = created["id"]
        return created.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"

    def _work_progress_archive_settings() -> dict:
        return {
            "enabled": bool(WORK_PROGRESS_AUTO_ARCHIVE_ENABLED),
            "days": max(1, int(WORK_PROGRESS_ARCHIVE_DAYS or 30)),
            "interval_s": max(60, int(WORK_PROGRESS_AUTO_ARCHIVE_INTERVAL_S or 86400)),
        }

    def _archive_old_work_progress_files(days: int = 30, workplace_scope: str = "session") -> dict:
        days = max(1, int(days or 30))
        cutoff_date = datetime_cls.now(TZ).date() - timedelta_cls(days=days)

        if workplace_scope == "all":
            allowed_wps = None
        else:
            current_wp = _session_workplace_id()
            allowed_wps = set(_workplace_ids_for_read(current_wp))

        entries = _load_work_progress_index()
        archived_files = 0
        updated_rows = 0
        errors = []
        changed = False
        files_to_delete = []

        for idx, item in enumerate(entries):
            row_wp = str(item.get("workplace_id") or "default").strip() or "default"
            if allowed_wps is not None and row_wp not in allowed_wps:
                continue

            if str(item.get("storage") or "local").strip().lower() == "drive":
                continue

            date_txt = str(item.get("date") or "").strip()
            try:
                row_date = datetime_cls.strptime(date_txt, "%Y-%m-%d").date()
            except Exception:
                continue

            if row_date >= cutoff_date:
                continue

            relpath = str(item.get("relpath") or "").strip()
            full_path = _resolve_work_progress_file_path(relpath, enforce_workplace=False)
            if not full_path or not os_mod.path.exists(full_path):
                continue

            try:
                archive_url = _upload_local_work_progress_to_archive(
                    full_path,
                    row_wp,
                    row_date.strftime("%Y-%m"),
                    str(item.get("site") or ""),
                )

                entries[idx]["archive_url"] = archive_url
                entries[idx]["storage"] = "drive"
                entries[idx]["archived_at"] = datetime_cls.now(TZ).isoformat(timespec="seconds")
                entries[idx]["local_relpath"] = relpath
                entries[idx].pop("relpath", None)

                files_to_delete.append(full_path)
                archived_files += 1
                updated_rows += 1
                changed = True
            except Exception as e:
                errors.append(f"{relpath}:{e}")

        if changed:
            try:
                _save_work_progress_index(entries)
            except Exception as e:
                return {
                    "archived_files": 0,
                    "updated_rows": 0,
                    "errors": [str(e)],
                }

        for local_path in files_to_delete:
            try:
                if os_mod.path.exists(local_path):
                    os_mod.remove(local_path)
            except Exception as e:
                errors.append(f"delete:{local_path}:{e}")

        return {
            "archived_files": archived_files,
            "updated_rows": updated_rows,
            "errors": errors,
        }

    def _maybe_run_auto_work_progress_archive():
        cfg = _work_progress_archive_settings()
        if not cfg.get("enabled"):
            return

        marker_path = os_mod.path.join(WORK_PROGRESS_BASE_DIR, ".auto_archive_marker")
        now_ts = time_mod.time()

        try:
            os_mod.makedirs(WORK_PROGRESS_BASE_DIR, exist_ok=True)
        except Exception:
            return

        try:
            if os_mod.path.exists(marker_path):
                last_run = os_mod.path.getmtime(marker_path)
                if (now_ts - last_run) < int(cfg["interval_s"]):
                    return
        except Exception:
            pass

        try:
            _archive_old_work_progress_files(days=int(cfg["days"]), workplace_scope="all")
        except Exception:
            return

        try:
            with open(marker_path, "w", encoding="utf-8") as fh:
                fh.write(str(int(now_ts)))
        except Exception:
            pass

    return {
        "WORK_PROGRESS_BASE_DIR": WORK_PROGRESS_BASE_DIR,
        "WORK_PROGRESS_INDEX_PATH": WORK_PROGRESS_INDEX_PATH,
        "WORK_PROGRESS_MAX_BYTES": WORK_PROGRESS_MAX_BYTES,
        "_ALLOWED_WORK_PROGRESS_EXTS": _ALLOWED_WORK_PROGRESS_EXTS,
        "_ALLOWED_WORK_PROGRESS_MIMES": _ALLOWED_WORK_PROGRESS_MIMES,
        "WORK_PROGRESS_IMAGE_MAX_DIM": WORK_PROGRESS_IMAGE_MAX_DIM,
        "WORK_PROGRESS_IMAGE_QUALITY": WORK_PROGRESS_IMAGE_QUALITY,
        "WORK_PROGRESS_AUTO_ARCHIVE_ENABLED": WORK_PROGRESS_AUTO_ARCHIVE_ENABLED,
        "WORK_PROGRESS_ARCHIVE_DAYS": WORK_PROGRESS_ARCHIVE_DAYS,
        "WORK_PROGRESS_AUTO_ARCHIVE_INTERVAL_S": WORK_PROGRESS_AUTO_ARCHIVE_INTERVAL_S,
        "_ensure_work_progress_storage": _ensure_work_progress_storage,
        "_work_progress_folder_name": _work_progress_folder_name,
        "_work_progress_safe_text": _work_progress_safe_text,
        "_normalize_work_progress_date": _normalize_work_progress_date,
        "_progress_sites_for_current_workplace": _progress_sites_for_current_workplace,
        "_load_work_progress_index": _load_work_progress_index,
        "_save_work_progress_index": _save_work_progress_index,
        "_resolve_work_progress_file_path": _resolve_work_progress_file_path,
        "_optimize_work_progress_image": _optimize_work_progress_image,
        "_store_work_progress_upload": _store_work_progress_upload,
        "_list_work_progress_items_for_session": _list_work_progress_items_for_session,
        "_get_work_progress_archive_drive_service": _get_work_progress_archive_drive_service,
        "_drive_find_or_create_folder": _drive_find_or_create_folder,
        "_upload_local_work_progress_to_archive": _upload_local_work_progress_to_archive,
        "_work_progress_archive_settings": _work_progress_archive_settings,
        "_archive_old_work_progress_files": _archive_old_work_progress_files,
        "_maybe_run_auto_work_progress_archive": _maybe_run_auto_work_progress_archive,
    }