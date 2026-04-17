from werkzeug.utils import secure_filename


def detect_upload_kind(file_bytes: bytes):
    if file_bytes.startswith(b"%PDF-"):
        return ".pdf", "application/pdf"
    if file_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if len(file_bytes) >= 12 and file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


def validate_upload_file(
    file_storage,
    upload_max_bytes: int,
    allowed_upload_exts,
    allowed_upload_mimes,
):
    if not file_storage or not getattr(file_storage, "filename", ""):
        raise RuntimeError("Missing upload file.")

    original = secure_filename(file_storage.filename or "upload") or "upload"
    _, ext = __import__("os").path.splitext(original)
    ext = (ext or "").lower()

    file_bytes = file_storage.read()
    file_storage.stream.seek(0)

    if not file_bytes:
        raise RuntimeError("Uploaded file is empty.")
    if len(file_bytes) > upload_max_bytes:
        raise RuntimeError(f"File too large. Max size is {upload_max_bytes // (1024 * 1024)}MB.")

    detected = detect_upload_kind(file_bytes)
    if not detected:
        raise RuntimeError("Unsupported file type. Upload PDF, JPG, PNG, or WEBP only.")

    detected_ext, detected_mime = detected
    claimed_mime = (getattr(file_storage, "mimetype", "") or "application/octet-stream").lower()

    if ext and ext not in allowed_upload_exts:
        raise RuntimeError("Unsupported file extension. Upload PDF, JPG, PNG, or WEBP only.")
    if claimed_mime not in allowed_upload_mimes:
        raise RuntimeError("Unsupported upload content type.")

    safe_base = __import__("os").path.splitext(original)[0] or "upload"
    safe_name = f"{safe_base}{detected_ext}"
    return file_bytes, detected_mime, safe_name

import base64
import binascii


def validate_clock_selfie_data_impl(
    selfie_data_url: str,
    allowed_clock_selfie_mimes,
    clock_selfie_max_bytes: int,
    detect_upload_kind_func,
):
    raw = (selfie_data_url or "").strip()
    if not raw:
        raise RuntimeError("Selfie is required before clocking in or out.")
    if not raw.startswith("data:image/") or "," not in raw:
        raise RuntimeError("Invalid selfie image data.")

    header, b64_data = raw.split(",", 1)
    declared_mime = header.split(";", 1)[0][5:].lower()
    if declared_mime not in allowed_clock_selfie_mimes:
        raise RuntimeError("Unsupported selfie format. Use JPG, PNG, or WEBP.")

    try:
        file_bytes = base64.b64decode(b64_data, validate=True)
    except (binascii.Error, ValueError):
        raise RuntimeError("Could not read selfie image.")

    if not file_bytes:
        raise RuntimeError("Captured selfie image is empty.")
    if len(file_bytes) > clock_selfie_max_bytes:
        raise RuntimeError(f"Selfie image is too large. Max size is {clock_selfie_max_bytes // (1024 * 1024)}MB.")

    detected = detect_upload_kind_func(file_bytes)
    if not detected:
        raise RuntimeError("Unsupported selfie format. Use JPG, PNG, or WEBP.")
    detected_ext, detected_mime = detected
    if detected_mime not in allowed_clock_selfie_mimes:
        raise RuntimeError("Selfie must be an image file.")

    safe_name = f"selfie{detected_ext}"
    return file_bytes, detected_mime, safe_name