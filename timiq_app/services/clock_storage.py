import os


def save_clock_selfie_locally(file_bytes: bytes, safe_name: str, clock_selfie_dir: str, token_hex_func, url_for_func) -> str:
    os.makedirs(clock_selfie_dir, exist_ok=True)
    token = token_hex_func(8)
    final_name = f"{token}_{safe_name}"
    full_path = os.path.join(clock_selfie_dir, final_name)
    with open(full_path, "wb") as fh:
        fh.write(file_bytes)
    return url_for_func("view_clock_selfie", filename=final_name)

def store_clock_selfie_impl(
    selfie_data_url: str,
    username: str,
    action: str,
    now_dt,
    validate_clock_selfie_data_func,
    upload_bytes_to_drive_func,
    save_clock_selfie_locally_func,
    secure_filename_func,
) -> str:
    file_bytes, mime_type, safe_name = validate_clock_selfie_data_func(selfie_data_url)
    stamp = now_dt.strftime("%Y%m%d_%H%M%S")
    prefix = f"{secure_filename_func(username or 'employee')}_{action}_{stamp}"

    local_url = save_clock_selfie_locally_func(file_bytes, safe_name)

    try:
        upload_bytes_to_drive_func(file_bytes, prefix, safe_name, mime_type)
    except Exception:
        pass

    return local_url