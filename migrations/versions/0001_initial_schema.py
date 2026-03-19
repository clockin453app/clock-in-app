"""Initial schema"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255)),
        sa.Column("role", sa.String(length=50)),
        sa.Column("workplace", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("username", sa.String(length=255)),
        sa.Column("first_name", sa.String(length=255)),
        sa.Column("last_name", sa.String(length=255)),
        sa.Column("password", sa.Text()),
        sa.Column("rate", sa.Numeric(10, 2)),
        sa.Column("early_access", sa.String(length=10)),
        sa.Column("active", sa.String(length=10)),
        sa.Column("workplace_id", sa.String(length=255)),
        sa.Column("active_session_token", sa.String(length=255)),
        sa.Column("site", sa.String(length=255)),
        sa.Column("site2", sa.String(length=255)),
        sa.Column("onboarding_completed", sa.String(length=20)),
    )
    op.create_index("ix_employees_email", "employees", ["email"])
    op.create_index("ix_employees_username", "employees", ["username"])
    op.create_index("ix_employees_workplace", "employees", ["workplace"])
    op.create_index("ix_employees_workplace_id", "employees", ["workplace_id"])
    op.create_index("ix_employees_active_session_token", "employees", ["active_session_token"])

    op.create_table(
        "workhours",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_email", sa.String(length=255)),
        sa.Column("date", sa.Date()),
        sa.Column("clock_in", sa.DateTime()),
        sa.Column("clock_out", sa.DateTime()),
        sa.Column("workplace", sa.String(length=255)),
        sa.Column("hours", sa.Numeric(10, 2)),
        sa.Column("pay", sa.Numeric(10, 2)),
        sa.Column("in_lat", sa.Numeric(12, 8)),
        sa.Column("in_lon", sa.Numeric(12, 8)),
        sa.Column("in_acc", sa.Numeric(10, 2)),
        sa.Column("in_site", sa.String(length=255)),
        sa.Column("in_dist_m", sa.Integer()),
        sa.Column("out_lat", sa.Numeric(12, 8)),
        sa.Column("out_lon", sa.Numeric(12, 8)),
        sa.Column("out_acc", sa.Numeric(10, 2)),
        sa.Column("out_site", sa.String(length=255)),
        sa.Column("out_dist_m", sa.Integer()),
        sa.Column("in_selfie_url", sa.Text()),
        sa.Column("out_selfie_url", sa.Text()),
        sa.Column("workplace_id", sa.String(length=255)),
    )
    op.create_index("ix_workhours_employee_email", "workhours", ["employee_email"])
    op.create_index("ix_workhours_date", "workhours", ["date"])
    op.create_index("ix_workhours_workplace", "workhours", ["workplace"])
    op.create_index("ix_workhours_workplace_id", "workhours", ["workplace_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(length=255)),
        sa.Column("user_email", sa.String(length=255)),
        sa.Column("actor", sa.String(length=255)),
        sa.Column("username", sa.String(length=255)),
        sa.Column("date_text", sa.String(length=50)),
        sa.Column("details", sa.Text()),
        sa.Column("workplace_id", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_audit_logs_workplace_id", "audit_logs", ["workplace_id"])

    op.create_table(
        "payroll_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=255)),
        sa.Column("week_start", sa.Date()),
        sa.Column("week_end", sa.Date()),
        sa.Column("gross", sa.Numeric(10, 2)),
        sa.Column("tax", sa.Numeric(10, 2)),
        sa.Column("net", sa.Numeric(10, 2)),
        sa.Column("paid_at", sa.DateTime()),
        sa.Column("paid_by", sa.String(length=255)),
        sa.Column("paid", sa.String(length=50)),
        sa.Column("workplace_id", sa.String(length=255)),
    )
    op.create_index("ix_payroll_reports_username", "payroll_reports", ["username"])
    op.create_index("ix_payroll_reports_workplace_id", "payroll_reports", ["workplace_id"])

    op.create_table(
        "onboarding_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=255)),
        sa.Column("workplace_id", sa.String(length=255)),
        sa.Column("first_name", sa.String(length=255)),
        sa.Column("last_name", sa.String(length=255)),
        sa.Column("birth_date", sa.String(length=50)),
        sa.Column("phone_country_code", sa.String(length=20)),
        sa.Column("phone_number", sa.String(length=100)),
        sa.Column("phone", sa.String(length=100)),
        sa.Column("email", sa.String(length=255)),
        sa.Column("street_address", sa.Text()),
        sa.Column("city", sa.String(length=255)),
        sa.Column("postcode", sa.String(length=50)),
        sa.Column("address", sa.Text()),
        sa.Column("emergency_contact_name", sa.String(length=255)),
        sa.Column("emergency_contact_phone_country_code", sa.String(length=20)),
        sa.Column("emergency_contact_phone_number", sa.String(length=100)),
        sa.Column("emergency_contact_phone", sa.String(length=100)),
        sa.Column("medical_condition", sa.Text()),
        sa.Column("medical_details", sa.Text()),
        sa.Column("position", sa.String(length=255)),
        sa.Column("cscs_number", sa.String(length=255)),
        sa.Column("cscs_expiry_date", sa.String(length=50)),
        sa.Column("employment_type", sa.String(length=100)),
        sa.Column("right_to_work_uk", sa.String(length=20)),
        sa.Column("national_insurance", sa.String(length=100)),
        sa.Column("utr", sa.String(length=100)),
        sa.Column("start_date", sa.String(length=50)),
        sa.Column("bank_account_number", sa.String(length=100)),
        sa.Column("sort_code", sa.String(length=100)),
        sa.Column("account_holder_name", sa.String(length=255)),
        sa.Column("company_trading_name", sa.String(length=255)),
        sa.Column("company_registration_no", sa.String(length=255)),
        sa.Column("date_of_contract", sa.String(length=50)),
        sa.Column("site_address", sa.Text()),
        sa.Column("passport_or_birth_cert_link", sa.Text()),
        sa.Column("cscs_front_back_link", sa.Text()),
        sa.Column("public_liability_link", sa.Text()),
        sa.Column("share_code_link", sa.Text()),
        sa.Column("contract_accepted", sa.String(length=20)),
        sa.Column("signature_name", sa.String(length=255)),
        sa.Column("signature_datetime", sa.String(length=100)),
        sa.Column("submitted_at", sa.String(length=100)),
    )
    op.create_index("ix_onboarding_records_username", "onboarding_records", ["username"])
    op.create_index("ix_onboarding_records_workplace_id", "onboarding_records", ["workplace_id"])

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site_name", sa.String(length=255)),
        sa.Column("lat", sa.Numeric(12, 8)),
        sa.Column("lon", sa.Numeric(12, 8)),
        sa.Column("radius_meters", sa.Integer()),
        sa.Column("active", sa.String(length=50)),
        sa.Column("workplace_id", sa.String(length=255)),
    )
    op.create_index("ix_locations_workplace_id", "locations", ["workplace_id"])

    op.create_table(
        "workplace_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workplace_id", sa.String(length=255), unique=True),
        sa.Column("tax_rate", sa.Numeric(10, 2)),
        sa.Column("currency_symbol", sa.String(length=20)),
        sa.Column("company_name", sa.String(length=255)),
    )


def downgrade() -> None:
    op.drop_table("workplace_settings")
    op.drop_index("ix_locations_workplace_id", table_name="locations")
    op.drop_table("locations")
    op.drop_index("ix_onboarding_records_workplace_id", table_name="onboarding_records")
    op.drop_index("ix_onboarding_records_username", table_name="onboarding_records")
    op.drop_table("onboarding_records")
    op.drop_index("ix_payroll_reports_workplace_id", table_name="payroll_reports")
    op.drop_index("ix_payroll_reports_username", table_name="payroll_reports")
    op.drop_table("payroll_reports")
    op.drop_index("ix_audit_logs_workplace_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_workhours_workplace_id", table_name="workhours")
    op.drop_index("ix_workhours_workplace", table_name="workhours")
    op.drop_index("ix_workhours_date", table_name="workhours")
    op.drop_index("ix_workhours_employee_email", table_name="workhours")
    op.drop_table("workhours")
    op.drop_index("ix_employees_active_session_token", table_name="employees")
    op.drop_index("ix_employees_workplace_id", table_name="employees")
    op.drop_index("ix_employees_workplace", table_name="employees")
    op.drop_index("ix_employees_username", table_name="employees")
    op.drop_index("ix_employees_email", table_name="employees")
    op.drop_table("employees")
