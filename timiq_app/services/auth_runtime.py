def build_auth_runtime(core):
    os = core["os"]
    json = core["json"]
    time_mod = core["time"]
    datetime_cls = core["datetime"]
    TZ = core["TZ"]
    secrets = core["secrets"]
    session = core["session"]
    request = core["request"]
    _fernet = core["_fernet"]
    BASE_DIR = core["BASE_DIR"]
    get_client_ip_func = core["get_client_ip_func"]
    get_session_workplace_id_func = core["get_session_workplace_id_func"]

    GLOBAL_MASTER_ADMIN_STORE_PATH = os.environ.get(
        "GLOBAL_MASTER_ADMIN_STORE_PATH",
        os.path.join(BASE_DIR, "instance", "global_master_admins.enc"),
    )
    GLOBAL_MASTER_ADMIN_SEED_JSON = os.environ.get("GLOBAL_MASTER_ADMIN_SEED_JSON", "").strip()

    LIVE_SESSION_STORE_PATH = (
        os.environ.get("LIVE_SESSION_STORE_PATH", "/var/data/live_sessions.enc").strip()
        or "/var/data/live_sessions.enc"
    )
    LIVE_SESSION_TTL_SECONDS = max(30, int(os.environ.get("LIVE_SESSION_TTL_SECONDS", "180") or "180"))
    LIVE_SESSION_RETENTION_SECONDS = max(
        LIVE_SESSION_TTL_SECONDS * 4,
        int(os.environ.get("LIVE_SESSION_RETENTION_SECONDS", "86400") or "86400"),
    )

    def _global_master_admin_store_default():
        return {"admins": []}

    def _normalize_global_master_admin_record(raw):
        if not isinstance(raw, dict):
            return None

        username = str(raw.get("username", "") or "").strip()
        password_hash = str(raw.get("password_hash", "") or "").strip()
        if not username or not password_hash:
            return None

        return {
            "username": username,
            "password_hash": password_hash,
            "active": str(raw.get("active", "TRUE") or "TRUE").strip() or "TRUE",
            "active_session_token": str(raw.get("active_session_token", "") or "").strip(),
        }

    def _save_global_master_admin_store(data: dict):
        base = _global_master_admin_store_default()
        admins = []

        for raw in (data or {}).get("admins", []) or []:
            rec = _normalize_global_master_admin_record(raw)
            if rec:
                admins.append(rec)

        base["admins"] = admins

        parent = os.path.dirname(GLOBAL_MASTER_ADMIN_STORE_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)

        payload = json.dumps(base, ensure_ascii=False, indent=2).encode("utf-8")
        f = _fernet()
        if f:
            payload = f.encrypt(payload)

        tmp_path = GLOBAL_MASTER_ADMIN_STORE_PATH + ".tmp"
        with open(tmp_path, "wb") as fh:
            fh.write(payload)
        os.replace(tmp_path, GLOBAL_MASTER_ADMIN_STORE_PATH)

    def _seed_global_master_admin_store_from_env():
        if os.path.exists(GLOBAL_MASTER_ADMIN_STORE_PATH):
            return

        raw = GLOBAL_MASTER_ADMIN_SEED_JSON
        if not raw:
            return

        try:
            data = json.loads(raw)
            if isinstance(data, list):
                data = {"admins": data}
            if not isinstance(data, dict):
                return
            _save_global_master_admin_store(data)
        except Exception:
            return

    def _load_global_master_admin_store() -> dict:
        _seed_global_master_admin_store_from_env()

        if not os.path.exists(GLOBAL_MASTER_ADMIN_STORE_PATH):
            return _global_master_admin_store_default()

        try:
            with open(GLOBAL_MASTER_ADMIN_STORE_PATH, "rb") as fh:
                payload = fh.read()

            f = _fernet()
            if f:
                payload = f.decrypt(payload)

            data = json.loads(payload.decode("utf-8"))
            if isinstance(data, list):
                data = {"admins": data}
            if not isinstance(data, dict):
                return _global_master_admin_store_default()

            admins = []
            for raw in data.get("admins", []) or []:
                rec = _normalize_global_master_admin_record(raw)
                if rec:
                    admins.append(rec)

            return {"admins": admins}
        except Exception:
            return _global_master_admin_store_default()

    def _find_global_master_admin_record(username: str):
        target = str(username or "").strip().lower()
        if not target:
            return None

        data = _load_global_master_admin_store()
        for rec in data.get("admins", []) or []:
            if str(rec.get("username", "") or "").strip().lower() == target:
                return rec
        return None

    def _issue_global_master_admin_session_token(username: str):
        target = str(username or "").strip().lower()
        if not target:
            return None

        data = _load_global_master_admin_store()
        admins = data.get("admins", []) or []

        for rec in admins:
            if str(rec.get("username", "") or "").strip().lower() != target:
                continue

            token = secrets.token_urlsafe(32)
            rec["active_session_token"] = token
            _save_global_master_admin_store({"admins": admins})
            return token

        return None

    def _clear_global_master_admin_session_token(username: str, expected_token: str | None = None):
        target = str(username or "").strip().lower()
        if not target:
            return False

        data = _load_global_master_admin_store()
        admins = data.get("admins", []) or []

        for rec in admins:
            if str(rec.get("username", "") or "").strip().lower() != target:
                continue

            current = str(rec.get("active_session_token", "") or "")
            if expected_token and current and current != expected_token:
                return False

            rec["active_session_token"] = ""
            _save_global_master_admin_store({"admins": admins})
            return True

        return False

    def _validate_global_master_admin_session():
        username = (session.get("username") or "").strip()
        if not username:
            return False, ""

        session_token = str(session.get("active_session_token") or "")
        if not session_token:
            return False, "Your session has expired. Please log in again."

        rec = _find_global_master_admin_record(username)
        if not rec:
            return False, "Your global admin account is no longer available. Please log in again."

        active_raw = str(rec.get("active", "TRUE") or "TRUE").strip().lower()
        if active_raw in ("false", "0", "no", "n", "off"):
            return False, "Your global admin account is inactive. Please log in again."

        stored_token = str(rec.get("active_session_token", "") or "")
        if not stored_token or stored_token != session_token:
            return False, "Your global admin account was signed in on another device. Please log in again."

        return True, ""

    def _live_session_store_default():
        return {"sessions": []}

    def _normalize_live_session_entry(raw):
        if not isinstance(raw, dict):
            return None

        session_key = str(raw.get("session_key", "") or "").strip()
        username = str(raw.get("username", "") or "").strip()
        active_session_token = str(raw.get("active_session_token", "") or "").strip()

        if not session_key or not username or not active_session_token:
            return None

        try:
            last_seen_epoch = int(raw.get("last_seen_epoch", 0) or 0)
        except Exception:
            last_seen_epoch = 0

        return {
            "session_key": session_key,
            "username": username,
            "role": str(raw.get("role", "") or "").strip() or "employee",
            "workplace_id": str(raw.get("workplace_id", "") or "").strip() or "default",
            "auth_scope": str(raw.get("auth_scope", "") or "").strip() or "employee_workplace",
            "active_session_token": active_session_token,
            "ip": str(raw.get("ip", "") or "").strip(),
            "user_agent": str(raw.get("user_agent", "") or "").strip()[:220],
            "last_seen_epoch": last_seen_epoch,
            "last_seen_iso": str(raw.get("last_seen_iso", "") or "").strip(),
        }

    def _prune_live_session_entries(entries, now_ts=None):
        now_ts = int(now_ts or time_mod.time())
        cutoff = now_ts - LIVE_SESSION_RETENTION_SECONDS
        out = []

        for raw in entries or []:
            rec = _normalize_live_session_entry(raw)
            if not rec:
                continue
            if rec["last_seen_epoch"] < cutoff:
                continue
            out.append(rec)

        return out

    def _save_live_session_store(data: dict):
        base = _live_session_store_default()
        sessions_data = _prune_live_session_entries((data or {}).get("sessions", []))
        base["sessions"] = sessions_data

        parent = os.path.dirname(LIVE_SESSION_STORE_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)

        payload = json.dumps(base, ensure_ascii=False, indent=2).encode("utf-8")
        f = _fernet()
        if f:
            payload = f.encrypt(payload)

        tmp_path = LIVE_SESSION_STORE_PATH + ".tmp"
        with open(tmp_path, "wb") as fh:
            fh.write(payload)
        os.replace(tmp_path, LIVE_SESSION_STORE_PATH)

    def _load_live_session_store() -> dict:
        if not os.path.exists(LIVE_SESSION_STORE_PATH):
            return _live_session_store_default()

        try:
            with open(LIVE_SESSION_STORE_PATH, "rb") as fh:
                payload = fh.read()

            f = _fernet()
            if f:
                payload = f.decrypt(payload)

            data = json.loads(payload.decode("utf-8"))
            if not isinstance(data, dict):
                return _live_session_store_default()

            sessions_data = _prune_live_session_entries(data.get("sessions", []))
            return {"sessions": sessions_data}
        except Exception:
            return _live_session_store_default()

    def _touch_live_session_presence():
        username = (session.get("username") or "").strip()
        active_session_token = str(session.get("active_session_token") or "")
        if not username or not active_session_token:
            return

        role = (session.get("role") or "employee").strip().lower() or "employee"
        auth_scope = (session.get("auth_scope") or "employee_workplace").strip().lower() or "employee_workplace"

        try:
            workplace_id = (get_session_workplace_id_func() or "default").strip() or "default"
        except Exception:
            workplace_id = "default"

        session_key = f"{auth_scope}:{username}:{active_session_token}"

        now_ts = int(time_mod.time())
        now_iso = datetime_cls.now(TZ).isoformat(timespec="seconds")
        ip = ""
        ua = ""

        try:
            ip = (get_client_ip_func() or "").strip()
        except Exception:
            ip = ""

        try:
            ua = str(request.headers.get("User-Agent", "") or "").strip()[:220]
        except Exception:
            ua = ""

        data = _load_live_session_store()
        sessions_data = [x for x in data.get("sessions", []) if str(x.get("session_key", "") or "") != session_key]

        sessions_data.append({
            "session_key": session_key,
            "username": username,
            "role": role,
            "workplace_id": workplace_id,
            "auth_scope": auth_scope,
            "active_session_token": active_session_token,
            "ip": ip,
            "user_agent": ua,
            "last_seen_epoch": now_ts,
            "last_seen_iso": now_iso,
        })

        _save_live_session_store({"sessions": sessions_data})

    def _remove_live_session_presence(session_key: str = "", active_session_token: str = ""):
        data = _load_live_session_store()
        sessions_data = []

        for raw in data.get("sessions", []):
            rec = _normalize_live_session_entry(raw)
            if not rec:
                continue

            if session_key and rec["session_key"] == session_key:
                continue
            if active_session_token and rec["active_session_token"] == active_session_token:
                continue

            sessions_data.append(rec)

        _save_live_session_store({"sessions": sessions_data})

    def _list_current_live_sessions():
        now_ts = int(time_mod.time())
        out = []

        for raw in _load_live_session_store().get("sessions", []):
            rec = _normalize_live_session_entry(raw)
            if not rec:
                continue

            age_s = max(0, now_ts - int(rec.get("last_seen_epoch", 0) or 0))
            rec["age_seconds"] = age_s
            rec["is_live"] = age_s <= LIVE_SESSION_TTL_SECONDS
            out.append(rec)

        out.sort(key=lambda x: (not x["is_live"], x["age_seconds"], x["username"].lower()))
        return out

    return {
        "GLOBAL_MASTER_ADMIN_STORE_PATH": GLOBAL_MASTER_ADMIN_STORE_PATH,
        "GLOBAL_MASTER_ADMIN_SEED_JSON": GLOBAL_MASTER_ADMIN_SEED_JSON,
        "LIVE_SESSION_STORE_PATH": LIVE_SESSION_STORE_PATH,
        "LIVE_SESSION_TTL_SECONDS": LIVE_SESSION_TTL_SECONDS,
        "LIVE_SESSION_RETENTION_SECONDS": LIVE_SESSION_RETENTION_SECONDS,
        "_find_global_master_admin_record": _find_global_master_admin_record,
        "_issue_global_master_admin_session_token": _issue_global_master_admin_session_token,
        "_clear_global_master_admin_session_token": _clear_global_master_admin_session_token,
        "_validate_global_master_admin_session": _validate_global_master_admin_session,
        "_touch_live_session_presence": _touch_live_session_presence,
        "_remove_live_session_presence": _remove_live_session_presence,
        "_list_current_live_sessions": _list_current_live_sessions,
    }