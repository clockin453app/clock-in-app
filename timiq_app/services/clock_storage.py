import io
import os

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None


def _compress_selfie_image(file_bytes: bytes, safe_name: str, mime_type: str):
    """
    Resize and compress selfie images to reduce disk usage.
    Target:
    - max width/height: 720px
    - JPEG output
    - try to keep near 350 KB if possible
    """
    if not Image:
        return file_bytes, mime_type, safe_name

    try:
        img = Image.open(io.BytesIO(file_bytes))

        if ImageOps is not None:
            img = ImageOps.exif_transpose(img)

        if img.mode not in ("RGB",):
            img = img.convert("RGB")

        max_side = 720
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

        base_name = os.path.splitext(safe_name or "selfie.jpg")[0]
        final_name = f"{base_name}.jpg"

        target_bytes = 350 * 1024
        quality_steps = [82, 76, 70, 64, 58]

        best_bytes = None

        for quality in quality_steps:
            out = io.BytesIO()
            img.save(
                out,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
            data = out.getvalue()

            best_bytes = data
            if len(data) <= target_bytes:
                break

        return best_bytes, "image/jpeg", final_name

    except Exception:
        return file_bytes, mime_type, safe_name


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

    file_bytes, mime_type, safe_name = _compress_selfie_image(
        file_bytes,
        safe_name,
        mime_type,
    )

    stamp = now_dt.strftime("%Y%m%d_%H%M%S")
    prefix = f"{secure_filename_func(username or 'employee')}_{action}_{stamp}"

    local_url = save_clock_selfie_locally_func(file_bytes, safe_name)

    try:
        upload_bytes_to_drive_func(file_bytes, prefix, safe_name, mime_type)
    except Exception:
        pass

    return local_url