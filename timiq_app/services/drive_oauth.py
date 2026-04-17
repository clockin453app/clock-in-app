import os
import json
import base64
import hashlib


def make_oauth_flow(client_id, client_secret, redirect_uri, flow_cls, oauth_scopes):
    if not (client_id and client_secret and redirect_uri):
        raise RuntimeError(
            "Missing Drive OAuth env vars. Set OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, OAUTH_REDIRECT_URI."
        )

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }

    return flow_cls.from_client_config(
        client_config,
        scopes=oauth_scopes,
        redirect_uri=redirect_uri,
    )


def ensure_instance_dir(store_path: str):
    d = os.path.dirname(store_path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def fernet_instance(fernet_cls, drive_token_encryption_key: str, secret_key: str):
    if not fernet_cls:
        return None

    try:
        if drive_token_encryption_key:
            return fernet_cls(drive_token_encryption_key.encode("utf-8"))

        if secret_key:
            derived_key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode("utf-8")).digest())
            return fernet_cls(derived_key)
    except Exception:
        return None

    return None


def save_drive_token_impl(token_dict: dict, store_path: str, fernet_func):
    ensure_instance_dir(store_path)
    payload = json.dumps(token_dict).encode("utf-8")
    f = fernet_func()
    if not f:
        raise RuntimeError(
            "Encrypted Drive token storage is unavailable. Install cryptography and configure token encryption."
        )
    with open(store_path, "wb") as fp:
        fp.write(f.encrypt(payload))


def load_drive_token_impl(store_path: str, fernet_func, drive_token_env: str, invalid_token_cls):
    try:
        if os.path.exists(store_path):
            f = fernet_func()
            if not f:
                return None
            with open(store_path, "rb") as fh:
                blob = fh.read()
            try:
                blob = f.decrypt(blob)
            except invalid_token_cls:
                return None
            return json.loads(blob.decode("utf-8"))
    except Exception:
        pass

    if drive_token_env:
        try:
            return json.loads(drive_token_env)
        except Exception:
            return None
    return None


def get_service_account_drive_service_impl(build_func, creds):
    try:
        return build_func("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        return None


def get_user_drive_service_impl(
    load_drive_token_func,
    user_credentials_cls,
    request_cls,
    save_drive_token_func,
    build_func,
):
    token_data = load_drive_token_func()
    if not token_data:
        return None

    creds_user = user_credentials_cls(**token_data)
    if creds_user.expired and creds_user.refresh_token:
        creds_user.refresh(request_cls())
        token_data["token"] = creds_user.token
        if creds_user.refresh_token:
            token_data["refresh_token"] = creds_user.refresh_token
        save_drive_token_func(token_data)

    return build_func("drive", "v3", credentials=creds_user, cache_discovery=False)