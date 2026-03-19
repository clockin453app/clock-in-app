"""Legacy DB-backed adapters that preserve the old sheet-like interface.

These are isolated from the main runtime so Google Sheets compatibility code is
kept in one place while the app runs primarily against the database.
"""

from __future__ import annotations

from decimal import Decimal

import workhours_app.core as core

# Bind core symbols once. This module is imported late in core setup so the
# referenced names already exist.
db = core.db
Employee = core.Employee
WorkHour = core.WorkHour
AuditLog = core.AuditLog
PayrollReport = core.PayrollReport
OnboardingRecord = core.OnboardingRecord
Location = core.Location
WorkplaceSetting = core.WorkplaceSetting
date = core.date
datetime = core.datetime
timedelta = core.timedelta
gspread = core.gspread
PAYROLL_HEADERS = core.PAYROLL_HEADERS
AUDIT_HEADERS = core.AUDIT_HEADERS
TZ = core.TZ
_apply_unpaid_break = core._apply_unpaid_break
_get_user_rate = core._get_user_rate
_session_workplace_id = core._session_workplace_id

def _db_parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _db_parse_datetime(date_value, time_value):
    d = _db_parse_date(date_value) if not isinstance(date_value, date) else date_value
    t = str(time_value or "").strip()
    if not d or not t:
        return None
    if len(t.split(":")) == 2:
        t = t + ":00"
    try:
        return datetime.strptime(f"{d.isoformat()} {t}", "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _db_format_decimal(val):
    if val in (None, ""):
        return ""
    try:
        return str(val)
    except Exception:
        return ""


def _db_bool_text(v, default="TRUE"):
    txt = str(v if v not in (None, "") else default).strip()
    return txt or default


def _db_workhour_metrics(rec):
    hours_val = getattr(rec, "hours", None)
    pay_val = getattr(rec, "pay", None)
    hours_txt = "" if hours_val in (None, "") else str(hours_val)
    pay_txt = "" if pay_val in (None, "") else str(pay_val)

    if hours_txt == "" and rec.clock_in and rec.clock_out:
        try:
            raw_hours = max(0.0, (rec.clock_out - rec.clock_in).total_seconds() / 3600.0)
            computed_hours = round(_apply_unpaid_break(raw_hours), 2)
            hours_txt = str(computed_hours)
            if pay_txt == "":
                pay_txt = str(round(computed_hours * float(_get_user_rate(rec.employee_email or "")), 2))
        except Exception:
            pass
    return hours_txt, pay_txt


def _db_workhour_order_key(rec):
    d = getattr(rec, "date", None) or date.min
    cin = getattr(rec, "clock_in", None) or datetime.min
    user = str(getattr(rec, "employee_email", "") or "")
    return (str(getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"), d, user, cin,
            getattr(rec, "id", 0))


class _ProxySheetBase:
    headers = []
    model = None
    _proxy_id_seed = 1000

    def __init__(self, title):
        self.title = title
        self.id = self._proxy_id_seed
        type(self)._proxy_id_seed += 1
        self.spreadsheet = None

    def get_all_values(self):
        return [self.headers[:]] + [self._row_from_record(rec) for rec in self._records()]

    def get_all_records(self):
        out = []
        for row in self.get_all_values()[1:]:
            out.append({self.headers[i]: row[i] if i < len(row) else "" for i in range(len(self.headers))})
        return out

    def row_values(self, row):
        vals = self.get_all_values()
        if row <= 0 or row > len(vals):
            return []
        return vals[row - 1]

    def append_rows(self, rows, value_input_option=None):
        for row in rows:
            self.append_row(row, value_input_option=value_input_option)

    def insert_row(self, row, index=1):
        if index == 1:
            return
        return self.append_row(row)

    def clear(self):
        return

    def update(self, range_name=None, values=None, **kwargs):
        if values is None:
            values = kwargs.get("values")
        if not range_name or values is None:
            return
        start, end = self._parse_range(range_name)
        start_row, start_col = start
        end_row, end_col = end
        if start_row == 1 and end_row == 1:
            return
        for r_offset, row_vals in enumerate(values):
            rownum = start_row + r_offset
            for c_offset, value in enumerate(row_vals):
                colnum = start_col + c_offset
                self.update_cell(rownum, colnum, value)

    def batch_update(self, updates):
        for upd in updates or []:
            rng = upd.get("range")
            vals = upd.get("values")
            if rng and vals is not None:
                self.update(rng, vals)

    def update_cell(self, row, col, value):
        if row <= 1:
            return
        records = self._records()
        idx = row - 2
        if idx < 0 or idx >= len(records):
            return
        rec = records[idx]
        if col <= 0 or col > len(self.headers):
            return
        self._set_field(rec, self.headers[col - 1], value)
        db.session.commit()

    def _parse_range(self, rng):
        if ":" in rng:
            a, b = rng.split(":", 1)
        else:
            a = b = rng
        return gspread.utils.a1_to_rowcol(a), gspread.utils.a1_to_rowcol(b)

    def _normalize_row(self, row):
        row = list(row or [])
        if len(row) < len(self.headers):
            row += [""] * (len(self.headers) - len(row))
        return row[:len(self.headers)]


class _EmployeesProxy(_ProxySheetBase):
    headers = ["Username", "Password", "Role", "Rate", "EarlyAccess", "OnboardingCompleted", "FirstName", "LastName",
               "Site", "Active", "Workplace_ID", "Site2"]
    model = Employee

    def _records(self):
        return sorted(Employee.query.all(), key=lambda r: (
            str(getattr(r, "workplace_id", None) or getattr(r, "workplace", None) or "default"),
            str(getattr(r, "username", None) or getattr(r, "email", None) or ""), getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            str(getattr(rec, "username", None) or getattr(rec, "email", None) or ""),
            str(getattr(rec, "password", "") or ""),
            str(getattr(rec, "role", "") or ""),
            _db_format_decimal(getattr(rec, "rate", None)),
            _db_bool_text(getattr(rec, "early_access", "TRUE")),
            str(getattr(rec, "onboarding_completed", "") or ""),
            str(getattr(rec, "first_name", "") or ""),
            str(getattr(rec, "last_name", "") or ""),
            str(getattr(rec, "site", "") or ""),
            _db_bool_text(getattr(rec, "active", "TRUE")),
            str(getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"),
            str(getattr(rec, "site2", "") or ""),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        username = str(data.get("Username") or "").strip()
        wp = str(data.get("Workplace_ID") or "default").strip() or "default"
        if not username:
            return
        rec = Employee.query.filter_by(username=username, workplace_id=wp).first()
        if not rec:
            rec = Employee.query.filter_by(email=username, workplace_id=wp).first()
        if not rec:
            rec = Employee(username=username, email=username, workplace_id=wp, workplace=wp)
            db.session.add(rec)
        self._apply_data(rec, data)
        db.session.commit()

    def _apply_data(self, rec, data):
        username = str(
            data.get("Username") or getattr(rec, "username", None) or getattr(rec, "email", None) or "").strip()
        wp = str(data.get("Workplace_ID") or getattr(rec, "workplace_id", None) or getattr(rec, "workplace",
                                                                                           None) or "default").strip() or "default"
        rec.username = username
        rec.email = username
        rec.workplace_id = wp
        rec.workplace = wp
        rec.password = str(data.get("Password") or getattr(rec, "password", "") or "")
        rec.role = str(data.get("Role") or getattr(rec, "role", "") or "")
        rate_txt = str(data.get("Rate") or "").strip()
        rec.rate = Decimal(rate_txt) if rate_txt else None
        rec.early_access = _db_bool_text(data.get("EarlyAccess"), getattr(rec, "early_access", "TRUE"))
        rec.onboarding_completed = str(
            data.get("OnboardingCompleted") or getattr(rec, "onboarding_completed", "") or "")
        rec.first_name = str(data.get("FirstName") or getattr(rec, "first_name", "") or "")
        rec.last_name = str(data.get("LastName") or getattr(rec, "last_name", "") or "")
        rec.name = (" ".join([rec.first_name or "", rec.last_name or ""]).strip() or username)
        rec.site = str(data.get("Site") or getattr(rec, "site", "") or "")
        rec.site2 = str(data.get("Site2") or getattr(rec, "site2", "") or "")
        rec.active = _db_bool_text(data.get("Active"), getattr(rec, "active", "TRUE"))

    def _set_field(self, rec, column, value):
        data = {self.headers[i]: self._row_from_record(rec)[i] for i in range(len(self.headers))}
        data[column] = "" if value is None else str(value)
        self._apply_data(rec, data)


class _SettingsProxy(_ProxySheetBase):
    headers = ["Workplace_ID", "Tax_Rate", "Currency_Symbol", "Company_Name"]
    model = WorkplaceSetting

    def _records(self):
        return sorted(WorkplaceSetting.query.all(),
                      key=lambda r: (str(getattr(r, "workplace_id", "") or ""), getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            str(getattr(rec, "workplace_id", "") or ""),
            _db_format_decimal(getattr(rec, "tax_rate", None)),
            str(getattr(rec, "currency_symbol", "") or ""),
            str(getattr(rec, "company_name", "") or ""),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        wp = str(data.get("Workplace_ID") or "default").strip() or "default"
        rec = WorkplaceSetting.query.filter_by(workplace_id=wp).first()
        if not rec:
            rec = WorkplaceSetting(workplace_id=wp)
            db.session.add(rec)
        self._apply_data(rec, data)
        db.session.commit()

    def _apply_data(self, rec, data):
        rec.workplace_id = str(
            data.get("Workplace_ID") or getattr(rec, "workplace_id", "default") or "default").strip() or "default"
        tax_txt = str(data.get("Tax_Rate") or "").strip()
        rec.tax_rate = Decimal(tax_txt) if tax_txt else Decimal("20")
        rec.currency_symbol = str(data.get("Currency_Symbol") or getattr(rec, "currency_symbol", "£") or "£")
        rec.company_name = str(data.get("Company_Name") or getattr(rec, "company_name", "Main") or "Main")

    def _set_field(self, rec, column, value):
        data = {self.headers[i]: self._row_from_record(rec)[i] for i in range(len(self.headers))}
        data[column] = "" if value is None else str(value)
        self._apply_data(rec, data)


class _LocationsProxy(_ProxySheetBase):
    headers = ["SiteName", "Lat", "Lon", "RadiusMeters", "Active", "Workplace_ID"]
    model = Location

    def _records(self):
        return sorted(Location.query.all(), key=lambda r: (str(getattr(r, "workplace_id", None) or "default"),
                                                           str(getattr(r, "site_name", "") or ""), getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            str(getattr(rec, "site_name", "") or ""),
            _db_format_decimal(getattr(rec, "lat", None)),
            _db_format_decimal(getattr(rec, "lon", None)),
            "" if getattr(rec, "radius_meters", None) is None else str(getattr(rec, "radius_meters")),
            _db_bool_text(getattr(rec, "active", "TRUE")),
            str(getattr(rec, "workplace_id", None) or "default"),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        wp = str(data.get("Workplace_ID") or "default").strip() or "default"
        name = str(data.get("SiteName") or "").strip()
        if not name:
            return
        rec = Location.query.filter_by(workplace_id=wp, site_name=name).first()
        if not rec:
            rec = Location(workplace_id=wp, site_name=name)
            db.session.add(rec)
        self._apply_data(rec, data)
        db.session.commit()

    def _apply_data(self, rec, data):
        rec.site_name = str(data.get("SiteName") or getattr(rec, "site_name", "") or "")
        rec.lat = Decimal(str(data.get("Lat") or getattr(rec, "lat", "0") or "0"))
        rec.lon = Decimal(str(data.get("Lon") or getattr(rec, "lon", "0") or "0"))
        rec.radius_meters = int(float(str(data.get("RadiusMeters") or getattr(rec, "radius_meters", 0) or 0)))
        rec.active = _db_bool_text(data.get("Active"), getattr(rec, "active", "TRUE"))
        rec.workplace_id = str(
            data.get("Workplace_ID") or getattr(rec, "workplace_id", "default") or "default").strip() or "default"

    def _set_field(self, rec, column, value):
        data = {self.headers[i]: self._row_from_record(rec)[i] for i in range(len(self.headers))}
        data[column] = "" if value is None else str(value)
        self._apply_data(rec, data)


class _WorkHoursProxy(_ProxySheetBase):
    headers = ["Username", "Date", "ClockIn", "ClockOut", "Hours", "Pay", "InLat", "InLon", "InAcc", "InSite",
               "InDistM", "InSelfieURL", "OutLat", "OutLon", "OutAcc", "OutSite", "OutDistM", "OutSelfieURL", "Workplace_ID"]
    model = WorkHour

    def _records(self):
        return sorted(WorkHour.query.all(), key=_db_workhour_order_key)

    def _row_from_record(self, rec):
        hours_txt, pay_txt = _db_workhour_metrics(rec)
        cin = rec.clock_in.strftime("%H:%M:%S") if getattr(rec, "clock_in", None) else ""
        cout = rec.clock_out.strftime("%H:%M:%S") if getattr(rec, "clock_out", None) else ""
        d = rec.date.isoformat() if getattr(rec, "date", None) else ""
        return [
            str(getattr(rec, "employee_email", "") or ""),
            d,
            cin,
            cout,
            hours_txt,
            pay_txt,
            _db_format_decimal(getattr(rec, "in_lat", None)),
            _db_format_decimal(getattr(rec, "in_lon", None)),
            _db_format_decimal(getattr(rec, "in_acc", None)),
            str(getattr(rec, "in_site", "") or ""),
            "" if getattr(rec, "in_dist_m", None) is None else str(getattr(rec, "in_dist_m")),
            str(getattr(rec, "in_selfie_url", "") or ""),
            _db_format_decimal(getattr(rec, "out_lat", None)),
            _db_format_decimal(getattr(rec, "out_lon", None)),
            _db_format_decimal(getattr(rec, "out_acc", None)),
            str(getattr(rec, "out_site", "") or ""),
            "" if getattr(rec, "out_dist_m", None) is None else str(getattr(rec, "out_dist_m")),
            str(getattr(rec, "out_selfie_url", "") or ""),
            str(getattr(rec, "workplace_id", None) or getattr(rec, "workplace", None) or "default"),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        username = str(data.get("Username") or "").strip()
        shift_date = _db_parse_date(data.get("Date"))
        wp = str(data.get("Workplace_ID") or _session_workplace_id() or "default").strip() or "default"
        if not username or not shift_date:
            return
        rec = WorkHour.query.filter_by(employee_email=username, date=shift_date, workplace=wp).order_by(
            WorkHour.id.desc()).first()
        if not rec:
            rec = WorkHour(employee_email=username, date=shift_date, workplace=wp, workplace_id=wp)
            db.session.add(rec)
        self._apply_data(rec, data)
        db.session.commit()

    def _apply_data(self, rec, data):
        username = str(data.get("Username") or getattr(rec, "employee_email", "") or "").strip()
        shift_date = _db_parse_date(data.get("Date")) or getattr(rec, "date", None)
        wp = str(data.get("Workplace_ID") or getattr(rec, "workplace_id", None) or getattr(rec, "workplace",
                                                                                           None) or _session_workplace_id() or "default").strip() or "default"
        rec.employee_email = username
        rec.date = shift_date
        rec.workplace = wp
        rec.workplace_id = wp
        cin_txt = str(data.get("ClockIn") or "").strip()
        cout_txt = str(data.get("ClockOut") or "").strip()
        rec.clock_in = _db_parse_datetime(shift_date, cin_txt) if cin_txt else None
        rec.clock_out = _db_parse_datetime(shift_date, cout_txt) if cout_txt else None
        if rec.clock_in and rec.clock_out and rec.clock_out < rec.clock_in:
            rec.clock_out = rec.clock_out + timedelta(days=1)
        hours_txt = str(data.get("Hours") or "").strip()
        pay_txt = str(data.get("Pay") or "").strip()
        rec.hours = Decimal(hours_txt) if hours_txt else None
        rec.pay = Decimal(pay_txt) if pay_txt else None
        for col, attr in {
            "InLat": "in_lat", "InLon": "in_lon", "InAcc": "in_acc", "InSite": "in_site", "InDistM": "in_dist_m",
            "InSelfieURL": "in_selfie_url",
            "OutLat": "out_lat", "OutLon": "out_lon", "OutAcc": "out_acc", "OutSite": "out_site",
            "OutDistM": "out_dist_m", "OutSelfieURL": "out_selfie_url",
        }.items():
            raw = data.get(col)
            if attr.endswith("_site") or attr.endswith("_url"):
                setattr(rec, attr, str(raw or ""))
            elif attr.endswith("_dist_m"):
                setattr(rec, attr, int(float(raw)) if str(raw or "").strip() else None)
            else:
                setattr(rec, attr, Decimal(str(raw)) if str(raw or "").strip() else None)

    def _set_field(self, rec, column, value):
        data = {self.headers[i]: self._row_from_record(rec)[i] for i in range(len(self.headers))}
        data[column] = "" if value is None else str(value)
        self._apply_data(rec, data)


class _PayrollProxy(_ProxySheetBase):
    headers = PAYROLL_HEADERS[:]
    model = PayrollReport

    def _records(self):
        return sorted(PayrollReport.query.all(), key=lambda r: (str(getattr(r, "workplace_id", None) or "default"),
                                                                getattr(r, "week_start", None) or date.min,
                                                                str(getattr(r, "username", "") or ""),
                                                                getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            rec.week_start.isoformat() if getattr(rec, "week_start", None) else "",
            rec.week_end.isoformat() if getattr(rec, "week_end", None) else "",
            str(getattr(rec, "username", "") or ""),
            _db_format_decimal(getattr(rec, "gross", None)),
            _db_format_decimal(getattr(rec, "tax", None)),
            _db_format_decimal(getattr(rec, "net", None)),
            getattr(rec, "paid_at", None).strftime("%Y-%m-%d %H:%M:%S") if getattr(rec, "paid_at", None) else "",
            str(getattr(rec, "paid_by", "") or ""),
            str(getattr(rec, "paid", "") or ""),
            str(getattr(rec, "workplace_id", None) or "default"),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        rec = PayrollReport(
            username=str(data.get("Username") or "").strip(),
            week_start=_db_parse_date(data.get("WeekStart")),
            week_end=_db_parse_date(data.get("WeekEnd")),
            gross=Decimal(str(data.get("Gross") or "0")),
            tax=Decimal(str(data.get("Tax") or "0")),
            net=Decimal(str(data.get("Net") or "0")),
            paid_at=_db_parse_datetime(data.get("WeekEnd") or date.today().isoformat(),
                                       data.get("PaidAt").split(" ")[1] if " " in str(
                                           data.get("PaidAt") or "") else "00:00:00") if str(
                data.get("PaidAt") or "").strip() else None,
            paid_by=str(data.get("PaidBy") or ""),
            paid=str(data.get("Paid") or ""),
            workplace_id=str(data.get("Workplace_ID") or _session_workplace_id() or "default"),
        )
        if str(data.get("PaidAt") or "").strip():
            try:
                rec.paid_at = datetime.strptime(str(data.get("PaidAt")).strip(), "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        db.session.add(rec)
        db.session.commit()

    def _set_field(self, rec, column, value):
        val = "" if value is None else str(value)
        if column == "Paid":
            rec.paid = val
        elif column == "PaidBy":
            rec.paid_by = val
        elif column == "PaidAt":
            rec.paid_at = datetime.strptime(val, "%Y-%m-%d %H:%M:%S") if val else None
        db.session.commit()


class _AuditProxy(_ProxySheetBase):
    headers = AUDIT_HEADERS[:]
    model = AuditLog

    def _records(self):
        return sorted(AuditLog.query.all(),
                      key=lambda r: (getattr(r, "created_at", None) or datetime.min, getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            getattr(rec, "created_at", None).strftime("%Y-%m-%d %H:%M:%S") if getattr(rec, "created_at", None) else "",
            str(getattr(rec, "actor", "") or ""),
            str(getattr(rec, "action", "") or ""),
            str(getattr(rec, "username", None) or getattr(rec, "user_email", "") or ""),
            str(getattr(rec, "date_text", "") or ""),
            str(getattr(rec, "details", "") or ""),
            str(getattr(rec, "workplace_id", None) or "default"),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        ts = str(row[0] or datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")).strip()
        rec = AuditLog(
            created_at=datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") if ts else datetime.now(TZ),
            actor=str(row[1] or ""),
            action=str(row[2] or ""),
            username=str(row[3] or ""),
            user_email=str(row[3] or ""),
            date_text=str(row[4] or ""),
            details=str(row[5] or ""),
            workplace_id=str(row[6] or _session_workplace_id() or "default"),
        )
        db.session.add(rec)
        db.session.commit()

    def _set_field(self, rec, column, value):
        return


class _OnboardingProxy(_ProxySheetBase):
    headers = [
        "Username", "Workplace_ID", "FirstName", "LastName", "BirthDate", "PhoneCountryCode", "PhoneNumber", "Email",
        "StreetAddress", "City", "Postcode", "EmergencyContactName", "EmergencyContactPhoneCountryCode",
        "EmergencyContactPhoneNumber",
        "MedicalCondition", "MedicalDetails", "Position", "CSCSNumber", "CSCSExpiryDate", "EmploymentType",
        "RightToWorkUK",
        "NationalInsurance", "UTR", "StartDate", "BankAccountNumber", "SortCode", "AccountHolderName",
        "CompanyTradingName",
        "CompanyRegistrationNo", "DateOfContract", "SiteAddress", "PassportOrBirthCertLink", "CSCSFrontBackLink",
        "PublicLiabilityLink",
        "ShareCodeLink", "ContractAccepted", "SignatureName", "SignatureDateTime", "SubmittedAt"
    ]
    model = OnboardingRecord

    def _records(self):
        return sorted(OnboardingRecord.query.all(), key=lambda r: (str(getattr(r, "workplace_id", None) or "default"),
                                                                   str(getattr(r, "username", "") or ""),
                                                                   getattr(r, "id", 0)))

    def _row_from_record(self, rec):
        return [
            str(getattr(rec, "username", "") or ""),
            str(getattr(rec, "workplace_id", None) or "default"),
            str(getattr(rec, "first_name", "") or ""),
            str(getattr(rec, "last_name", "") or ""),
            str(getattr(rec, "birth_date", "") or ""),
            str(getattr(rec, "phone_country_code", "") or ""),
            str(getattr(rec, "phone_number", None) or getattr(rec, "phone", "") or ""),
            str(getattr(rec, "email", "") or ""),
            str(getattr(rec, "street_address", None) or getattr(rec, "address", "") or ""),
            str(getattr(rec, "city", "") or ""),
            str(getattr(rec, "postcode", "") or ""),
            str(getattr(rec, "emergency_contact_name", "") or ""),
            str(getattr(rec, "emergency_contact_phone_country_code", "") or ""),
            str(getattr(rec, "emergency_contact_phone_number", None) or getattr(rec, "emergency_contact_phone",
                                                                                "") or ""),
            str(getattr(rec, "medical_condition", "") or ""),
            str(getattr(rec, "medical_details", "") or ""),
            str(getattr(rec, "position", "") or ""),
            str(getattr(rec, "cscs_number", "") or ""),
            str(getattr(rec, "cscs_expiry_date", "") or ""),
            str(getattr(rec, "employment_type", "") or ""),
            str(getattr(rec, "right_to_work_uk", "") or ""),
            str(getattr(rec, "national_insurance", "") or ""),
            str(getattr(rec, "utr", "") or ""),
            str(getattr(rec, "start_date", "") or ""),
            str(getattr(rec, "bank_account_number", "") or ""),
            str(getattr(rec, "sort_code", "") or ""),
            str(getattr(rec, "account_holder_name", "") or ""),
            str(getattr(rec, "company_trading_name", "") or ""),
            str(getattr(rec, "company_registration_no", "") or ""),
            str(getattr(rec, "date_of_contract", "") or ""),
            str(getattr(rec, "site_address", "") or ""),
            str(getattr(rec, "passport_or_birth_cert_link", "") or ""),
            str(getattr(rec, "cscs_front_back_link", "") or ""),
            str(getattr(rec, "public_liability_link", "") or ""),
            str(getattr(rec, "share_code_link", "") or ""),
            str(getattr(rec, "contract_accepted", "") or ""),
            str(getattr(rec, "signature_name", "") or ""),
            str(getattr(rec, "signature_datetime", "") or ""),
            str(getattr(rec, "submitted_at", "") or ""),
        ]

    def append_row(self, row, value_input_option=None):
        row = self._normalize_row(row)
        data = {self.headers[i]: row[i] for i in range(len(self.headers))}
        username = str(data.get("Username") or "").strip()
        wp = str(data.get("Workplace_ID") or _session_workplace_id() or "default").strip() or "default"
        if not username:
            return
        rec = OnboardingRecord.query.filter_by(username=username, workplace_id=wp).first()
        if not rec:
            rec = OnboardingRecord(username=username, workplace_id=wp)
            db.session.add(rec)
        self._apply_data(rec, data)
        db.session.commit()

    def _apply_data(self, rec, data):
        mapping = {
            "FirstName": "first_name", "LastName": "last_name", "BirthDate": "birth_date",
            "PhoneCountryCode": "phone_country_code",
            "PhoneNumber": "phone_number", "Email": "email", "StreetAddress": "street_address", "City": "city",
            "Postcode": "postcode",
            "EmergencyContactName": "emergency_contact_name",
            "EmergencyContactPhoneCountryCode": "emergency_contact_phone_country_code",
            "EmergencyContactPhoneNumber": "emergency_contact_phone_number", "MedicalCondition": "medical_condition",
            "MedicalDetails": "medical_details",
            "Position": "position", "CSCSNumber": "cscs_number", "CSCSExpiryDate": "cscs_expiry_date",
            "EmploymentType": "employment_type",
            "RightToWorkUK": "right_to_work_uk", "NationalInsurance": "national_insurance", "UTR": "utr",
            "StartDate": "start_date",
            "BankAccountNumber": "bank_account_number", "SortCode": "sort_code",
            "AccountHolderName": "account_holder_name",
            "CompanyTradingName": "company_trading_name", "CompanyRegistrationNo": "company_registration_no",
            "DateOfContract": "date_of_contract",
            "SiteAddress": "site_address", "PassportOrBirthCertLink": "passport_or_birth_cert_link",
            "CSCSFrontBackLink": "cscs_front_back_link",
            "PublicLiabilityLink": "public_liability_link", "ShareCodeLink": "share_code_link",
            "ContractAccepted": "contract_accepted",
            "SignatureName": "signature_name", "SignatureDateTime": "signature_datetime", "SubmittedAt": "submitted_at",
        }
        rec.username = str(data.get("Username") or getattr(rec, "username", "") or "")
        rec.workplace_id = str(
            data.get("Workplace_ID") or getattr(rec, "workplace_id", None) or _session_workplace_id() or "default")
        for col, attr in mapping.items():
            setattr(rec, attr, str(data.get(col) or getattr(rec, attr, "") or ""))
        rec.phone = rec.phone_number
        rec.address = rec.street_address
        rec.emergency_contact_phone = rec.emergency_contact_phone_number

    def _set_field(self, rec, column, value):
        data = {self.headers[i]: self._row_from_record(rec)[i] for i in range(len(self.headers))}
        data[column] = "" if value is None else str(value)
        self._apply_data(rec, data)


__all__ = [
    "_db_bool_text",
    "_db_format_decimal",
    "_db_parse_date",
    "_db_parse_datetime",
    "_db_workhour_metrics",
    "_db_workhour_order_key",
    "_AuditProxy",
    "_EmployeesProxy",
    "_LocationsProxy",
    "_OnboardingProxy",
    "_PayrollProxy",
    "_ProxySheetBase",
    "_SettingsProxy",
    "_WorkHoursProxy",
]
