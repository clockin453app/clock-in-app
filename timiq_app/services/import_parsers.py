from decimal import Decimal
from datetime import datetime


def pick(rec, *keys, default=""):
    for k in keys:
        if k in rec and rec.get(k) not in (None, ""):
            return rec.get(k)
    return default


def to_str(v):
    return str(v).strip() if v is not None else ""


def to_decimal(v, default=None):
    s = to_str(v)
    if not s:
        return default
    s = s.replace("£", "").replace(",", "").strip()
    try:
        return Decimal(s)
    except Exception:
        return default


def to_int(v, default=None):
    s = to_str(v)
    if not s:
        return default
    try:
        return int(float(s))
    except Exception:
        return default


def to_date(v):
    s = to_str(v)
    if not s:
        return None

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass

    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None


def to_datetime(v):
    s = to_str(v)
    if not s:
        return None

    candidates = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%H:%M:%S",
        "%H:%M",
    ]
    for fmt in candidates:
        try:
            parsed = datetime.strptime(s, fmt)
            if fmt in ("%H:%M:%S", "%H:%M"):
                return parsed
            return parsed
        except Exception:
            pass

    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None