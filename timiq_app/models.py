from .extensions import db


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    name = db.Column(db.String(255))
    role = db.Column(db.String(50))
    workplace = db.Column(db.String(255), index=True)
    created_at = db.Column(db.DateTime)

    username = db.Column(db.String(255), index=True)
    first_name = db.Column(db.String(255))
    last_name = db.Column(db.String(255))
    password = db.Column(db.Text)
    rate = db.Column(db.Numeric(10, 2))
    early_access = db.Column(db.String(10))
    active = db.Column(db.String(10))
    workplace_id = db.Column(db.String(255), index=True)
    active_session_token = db.Column(db.String(255), index=True)
    site = db.Column(db.String(255))
    site2 = db.Column(db.String(255))
    onboarding_completed = db.Column(db.String(20))


class WorkHour(db.Model):
    __tablename__ = "workhours"
    id = db.Column(db.Integer, primary_key=True)
    employee_email = db.Column(db.String(255), index=True)
    date = db.Column(db.Date, index=True)
    clock_in = db.Column(db.DateTime)
    clock_out = db.Column(db.DateTime)
    workplace = db.Column(db.String(255), index=True)
    hours = db.Column(db.Numeric(10, 2))
    pay = db.Column(db.Numeric(10, 2))
    in_lat = db.Column(db.Numeric(12, 8))
    in_lon = db.Column(db.Numeric(12, 8))
    in_acc = db.Column(db.Numeric(10, 2))
    in_site = db.Column(db.String(255))
    in_dist_m = db.Column(db.Integer)
    out_lat = db.Column(db.Numeric(12, 8))
    out_lon = db.Column(db.Numeric(12, 8))
    out_acc = db.Column(db.Numeric(10, 2))
    out_site = db.Column(db.String(255))
    out_dist_m = db.Column(db.Integer)
    in_selfie_url = db.Column(db.Text)
    out_selfie_url = db.Column(db.Text)
    workplace_id = db.Column(db.String(255), index=True)
    payroll_rule_id = db.Column(db.Integer, index=True)
    rule_effective_from = db.Column(db.Date)
    snapshot_overtime_after_hours = db.Column(db.Numeric(10, 2))
    snapshot_overtime_multiplier = db.Column(db.Numeric(10, 2))
    snapshot_time_rounding_minutes = db.Column(db.Integer)
    snapshot_break_deduction_minutes = db.Column(db.Integer)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(255))
    user_email = db.Column(db.String(255))
    actor = db.Column(db.String(255))
    username = db.Column(db.String(255))
    date_text = db.Column(db.String(50))
    details = db.Column(db.Text)
    workplace_id = db.Column(db.String(255), index=True)
    created_at = db.Column(db.DateTime)


class PayrollReport(db.Model):
    __tablename__ = "payroll_reports"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), index=True)
    week_start = db.Column(db.Date)
    week_end = db.Column(db.Date)
    gross = db.Column(db.Numeric(10, 2))
    tax = db.Column(db.Numeric(10, 2))
    net = db.Column(db.Numeric(10, 2))
    display_tax = db.Column(db.Numeric(10, 2))
    display_net = db.Column(db.Numeric(10, 2))
    payment_mode = db.Column(db.String(20))
    paid_at = db.Column(db.DateTime)
    paid_by = db.Column(db.String(255))
    paid = db.Column(db.String(50))
    workplace_id = db.Column(db.String(255), index=True)


class OnboardingRecord(db.Model):
    __tablename__ = "onboarding_records"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), index=True)
    workplace_id = db.Column(db.String(255), index=True)

    first_name = db.Column(db.String(255))
    last_name = db.Column(db.String(255))
    birth_date = db.Column(db.String(50))

    phone_country_code = db.Column(db.String(20))
    phone_number = db.Column(db.String(100))
    phone = db.Column(db.String(100))

    email = db.Column(db.String(255))

    street_address = db.Column(db.Text)
    city = db.Column(db.String(255))
    postcode = db.Column(db.String(50))
    address = db.Column(db.Text)

    emergency_contact_name = db.Column(db.String(255))
    emergency_contact_phone_country_code = db.Column(db.String(20))
    emergency_contact_phone_number = db.Column(db.String(100))
    emergency_contact_phone = db.Column(db.String(100))

    medical_condition = db.Column(db.Text)
    medical_details = db.Column(db.Text)

    position = db.Column(db.String(255))
    cscs_number = db.Column(db.String(255))
    cscs_expiry_date = db.Column(db.String(50))
    employment_type = db.Column(db.String(100))
    right_to_work_uk = db.Column(db.String(20))
    national_insurance = db.Column(db.String(100))
    utr = db.Column(db.String(100))
    start_date = db.Column(db.String(50))

    bank_account_number = db.Column(db.String(100))
    sort_code = db.Column(db.String(100))
    account_holder_name = db.Column(db.String(255))

    company_trading_name = db.Column(db.String(255))
    company_registration_no = db.Column(db.String(255))

    date_of_contract = db.Column(db.String(50))
    site_address = db.Column(db.Text)

    passport_or_birth_cert_link = db.Column(db.Text)
    cscs_front_back_link = db.Column(db.Text)
    public_liability_link = db.Column(db.Text)
    share_code_link = db.Column(db.Text)

    contract_accepted = db.Column(db.String(20))
    signature_name = db.Column(db.String(255))
    signature_datetime = db.Column(db.String(100))
    submitted_at = db.Column(db.String(100))


class Location(db.Model):
    __tablename__ = "locations"
    id = db.Column(db.Integer, primary_key=True)
    site_name = db.Column(db.String(255))
    lat = db.Column(db.Numeric(12, 8))
    lon = db.Column(db.Numeric(12, 8))
    radius_meters = db.Column(db.Integer)
    active = db.Column(db.String(50))
    workplace_id = db.Column(db.String(255), index=True)



class WorkplaceSetting(db.Model):
    __tablename__ = "workplace_settings"
    id = db.Column(db.Integer, primary_key=True)
    workplace_id = db.Column(db.String(255), unique=True)
    tax_rate = db.Column(db.Numeric(10, 2))
    currency_symbol = db.Column(db.String(20))
    company_name = db.Column(db.String(255))
    company_logo_url = db.Column(db.Text)
    overtime_after_hours = db.Column(db.Numeric(10, 2))
    overtime_multiplier = db.Column(db.Numeric(10, 2))
    time_rounding_minutes = db.Column(db.Integer)
    break_deduction_minutes = db.Column(db.Integer)

class WorkplacePayrollRule(db.Model):
    __tablename__ = "workplace_payroll_rules"

    id = db.Column(db.Integer, primary_key=True)
    workplace_id = db.Column(db.String(255), index=True, nullable=False)
    effective_from = db.Column(db.Date, index=True, nullable=False)

    overtime_after_hours = db.Column(db.Numeric(10, 2), nullable=False)
    overtime_multiplier = db.Column(db.Numeric(10, 2), nullable=False)
    time_rounding_minutes = db.Column(db.Integer, nullable=False)
    break_deduction_minutes = db.Column(db.Integer, nullable=False)

    created_by = db.Column(db.String(255))
    created_at = db.Column(db.DateTime)
    note = db.Column(db.Text)
    is_active = db.Column(db.String(20), default="true")


