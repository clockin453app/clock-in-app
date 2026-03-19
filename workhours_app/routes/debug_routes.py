"""Route registrations extracted from the legacy monolith.

This keeps the original endpoint names and handler bodies intact while
reducing the size of the main runtime module.
"""

from workhours_app.route_dependencies import (
    AuditLog,
    DB_MIGRATION_MODE,
    Decimal,
    ENABLE_GOOGLE_SHEETS,
    Employee,
    Location,
    OnboardingRecord,
    PayrollReport,
    SHEETS_IMPORT_ENABLED,
    WorkHour,
    WorkplaceSetting,
    _DB_DEBUG_ALLOWED_COLUMNS,
    _get_import_sheet,
    _is_sensitive_debug_export_enabled,
    _normalize_password_hash_value,
    _pick,
    _rows_to_dicts,
    _to_date,
    _to_datetime,
    _to_decimal,
    _to_int,
    _to_str,
    abort,
    app,
    datetime,
    db,
    get_locations,
    jsonify,
    require_destructive_admin_post,
    require_sensitive_tools_admin,
)

@app.route("/db-test")
def db_test():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate

    try:
        with app.app_context():
            tables = db.inspect(db.engine).get_table_names()
        return {"database": "connected", "tables": tables}
    except Exception as e:
        return {"database": "error", "message": str(e)}, 500


@app.route("/db/employees")
def db_view_employees():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(Employee, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["employees"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/workhours")
def db_view_workhours():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(WorkHour, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["workhours"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/audit")
def db_view_audit():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(AuditLog, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["audit_logs"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/payroll")
def db_view_payroll():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(PayrollReport, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["payroll_reports"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/onboarding")
def db_view_onboarding():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(OnboardingRecord, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["onboarding_records"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/locations")
def db_view_locations():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(Location, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["locations"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/db/settings")
def db_view_settings():
    gate = require_sensitive_tools_admin()
    if gate:
        return gate
    if not _is_sensitive_debug_export_enabled():
        abort(404)

    try:
        return jsonify(_rows_to_dicts(WorkplaceSetting, allowed_columns=_DB_DEBUG_ALLOWED_COLUMNS["workplace_settings"]))
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.post("/db/upgrade-employees-table")
def db_upgrade_employees_table():
    gate = require_destructive_admin_post("db_upgrade_employees_table")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403

    try:
        statements = [
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS username VARCHAR(255)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS first_name VARCHAR(255)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS last_name VARCHAR(255)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS password TEXT",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS rate NUMERIC(10,2)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS early_access VARCHAR(10)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS active VARCHAR(10)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS workplace_id VARCHAR(255)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS active_session_token VARCHAR(255)",
            "ALTER TABLE employees ADD COLUMN IF NOT EXISTS site VARCHAR(255)",
        ]

        with db.engine.begin() as conn:
            for sql in statements:
                conn.exec_driver_sql(sql)

            cols = [
                row[0]
                for row in conn.exec_driver_sql(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'employees'
                    ORDER BY ordinal_position
                    """
                ).fetchall()
            ]

        return {
            "status": "ok",
            "table": "employees",
            "columns": cols,
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.post("/db/upgrade-onboarding-table")
def db_upgrade_onboarding_table():
    gate = require_destructive_admin_post("db_upgrade_onboarding_table")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403

    try:
        statements = [
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS workplace_id VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS phone_country_code VARCHAR(20)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS phone_number VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS street_address TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS city VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS postcode VARCHAR(50)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS emergency_contact_phone_country_code VARCHAR(20)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS emergency_contact_phone_number VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS medical_details TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS cscs_number VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS cscs_expiry_date VARCHAR(50)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS employment_type VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS right_to_work_uk VARCHAR(20)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS national_insurance VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS utr VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS start_date VARCHAR(50)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS bank_account_number VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS sort_code VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS account_holder_name VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS company_trading_name VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS company_registration_no VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS date_of_contract VARCHAR(50)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS site_address TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS passport_or_birth_cert_link TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS cscs_front_back_link TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS public_liability_link TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS share_code_link TEXT",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS contract_accepted VARCHAR(20)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS signature_name VARCHAR(255)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS signature_date_time VARCHAR(100)",
            "ALTER TABLE onboarding_records ADD COLUMN IF NOT EXISTS submitted_at VARCHAR(100)",
        ]

        with db.engine.begin() as conn:
            for sql in statements:
                conn.exec_driver_sql(sql)

            cols = [
                row[0]
                for row in conn.exec_driver_sql(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'onboarding_records'
                    ORDER BY ordinal_position
                    """
                ).fetchall()
            ]

        return {"status": "ok", "table": "onboarding_records", "columns": cols}
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-employees")
def import_employees():
    gate = require_destructive_admin_post("import_employees")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        Employee.query.delete(synchronize_session=False)

        records = _get_import_sheet("employees").get_all_records()
        count = 0

        for rec in records:
            username = str(rec.get("Username", "")).strip()
            if not username:
                continue

            first_name = str(rec.get("FirstName", "")).strip()
            last_name = str(rec.get("LastName", "")).strip()
            full_name = (" ".join([first_name, last_name])).strip()

            role = str(rec.get("Role", "")).strip()
            workplace_id = str(rec.get("Workplace_ID", "")).strip() or "default"
            password = _normalize_password_hash_value(str(rec.get("Password", "")).strip())
            early_access = str(rec.get("EarlyAccess", "")).strip()
            active = str(rec.get("Active", "")).strip() or "TRUE"
            site = str(rec.get("Site", "")).strip()

            rate_raw = str(rec.get("Rate", "")).strip()
            rate_val = None
            if rate_raw != "":
                try:
                    rate_val = Decimal(rate_raw.replace("£", "").replace(",", "").strip())
                except Exception:
                    rate_val = None

            employee = Employee(
                email=username,
                name=full_name,
                role=role,
                workplace=workplace_id,
                created_at=None,
                username=username,
                first_name=first_name,
                last_name=last_name,
                password=password,
                rate=rate_val,
                early_access=early_access,
                active=active,
                workplace_id=workplace_id,
                site=site,
            )
            db.session.add(employee)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-locations")
def import_locations():
    gate = require_destructive_admin_post("import_locations")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        Location.query.delete(synchronize_session=False)

        records = get_locations()
        count = 0

        for rec in records:
            site_name = _to_str(_pick(rec, "Site", "SiteName", "site_name", "Name"))
            if not site_name:
                continue

            row = Location(
                site_name=site_name,
                lat=_to_decimal(_pick(rec, "Lat", "Latitude", "lat")),
                lon=_to_decimal(_pick(rec, "Lon", "Lng", "Longitude", "lon")),
                radius_meters=_to_int(_pick(rec, "Radius", "RadiusMeters", "radius_meters")),
                active=_to_str(_pick(rec, "Active", "active", default="yes")),
                workplace_id=_to_str(_pick(rec, "Workplace_ID", "workplace_id", default="default")),
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-settings")
def import_settings():
    gate = require_destructive_admin_post("import_settings")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        WorkplaceSetting.query.delete(synchronize_session=False)

        records = _get_import_sheet("settings").get_all_records()
        count = 0

        for rec in records:
            workplace_id = _to_str(_pick(rec, "Workplace_ID", "workplace_id", default="default"))
            if not workplace_id:
                workplace_id = "default"

            row = WorkplaceSetting(
                workplace_id=workplace_id,
                tax_rate=_to_decimal(_pick(rec, "Tax_Rate", "TaxRate", "tax_rate")),
                currency_symbol=_to_str(_pick(rec, "Currency_Symbol", "Currency", "currency_symbol")),
                company_name=_to_str(_pick(rec, "Company_Name", "Company", "company_name")),
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-audit")
def import_audit():
    gate = require_destructive_admin_post("import_audit")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        AuditLog.query.delete(synchronize_session=False)

        records = _get_import_sheet("audit").get_all_records()
        count = 0

        for rec in records:
            action = _to_str(_pick(rec, "Action", "action"))
            user_email = _to_str(_pick(rec, "Username", "User", "Actor", "user_email"))

            if not action and not user_email:
                continue

            row = AuditLog(
                action=action or "unknown",
                user_email=user_email,
                created_at=_to_datetime(_pick(rec, "Timestamp", "Created_At", "DateTime", "created_at")),
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-payroll")
def import_payroll():
    gate = require_destructive_admin_post("import_payroll")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        PayrollReport.query.delete(synchronize_session=False)

        records = _get_import_sheet("payroll").get_all_records()
        count = 0

        for rec in records:
            username = _to_str(_pick(rec, "Username", "username", "User"))
            if not username:
                continue

            row = PayrollReport(
                username=username,
                week_start=_to_date(_pick(rec, "Week_Start", "WeekStart", "week_start")),
                week_end=_to_date(_pick(rec, "Week_End", "WeekEnd", "week_end")),
                gross=_to_decimal(_pick(rec, "Gross", "Gross_Pay", "gross")),
                tax=_to_decimal(_pick(rec, "Tax", "Tax_Amount", "tax")),
                net=_to_decimal(_pick(rec, "Net", "Net_Pay", "net")),
                paid_at=_to_datetime(_pick(rec, "Paid_At", "PaidAt", "paid_at")),
                paid_by=_to_str(_pick(rec, "Paid_By", "PaidBy", "paid_by")),
                paid=_to_str(_pick(rec, "Paid", "paid")),
                workplace_id=_to_str(_pick(rec, "Workplace_ID", "workplace_id", default="default")),
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-onboarding")
def import_onboarding():
    gate = require_destructive_admin_post("import_onboarding")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        OnboardingRecord.query.delete(synchronize_session=False)

        records = _get_import_sheet("onboarding").get_all_records()
        count = 0

        for rec in records:
            username = _to_str(_pick(rec, "Username", "username"))
            if not username:
                continue

            phone_cc = _to_str(_pick(rec, "PhoneCountryCode", "phone_country_code"))
            phone_num = _to_str(_pick(rec, "PhoneNumber", "Phone", "phone_number", "phone"))
            ec_cc = _to_str(_pick(rec, "EmergencyContactPhoneCountryCode", "emergency_contact_phone_country_code"))
            ec_num = _to_str(
                _pick(rec, "EmergencyContactPhoneNumber", "EmergencyContactPhone", "Emergency_Contact_Phone",
                      "emergency_contact_phone_number"))

            street = _to_str(_pick(rec, "StreetAddress", "street_address"))
            city = _to_str(_pick(rec, "City", "city"))
            postcode = _to_str(_pick(rec, "Postcode", "postcode"))

            address_joined = ", ".join([x for x in [street, city, postcode] if x]).strip()
            phone_joined = " ".join([x for x in [phone_cc, phone_num] if x]).strip()
            ec_phone_joined = " ".join([x for x in [ec_cc, ec_num] if x]).strip()

            row = OnboardingRecord(
                username=username,
                workplace_id=_to_str(_pick(rec, "Workplace_ID", "workplace_id", default="default")),

                first_name=_to_str(_pick(rec, "FirstName", "First_Name", "first_name")),
                last_name=_to_str(_pick(rec, "LastName", "Last_Name", "last_name")),
                birth_date=_to_str(_pick(rec, "BirthDate", "Birth_Date", "birth_date")),

                phone_country_code=phone_cc,
                phone_number=phone_num,
                phone=phone_joined,

                email=_to_str(_pick(rec, "Email", "email")),

                street_address=street,
                city=city,
                postcode=postcode,
                address=address_joined,

                emergency_contact_name=_to_str(_pick(rec, "EmergencyContactName", "Emergency_Contact_Name")),
                emergency_contact_phone_country_code=ec_cc,
                emergency_contact_phone_number=ec_num,
                emergency_contact_phone=ec_phone_joined,

                medical_condition=_to_str(_pick(rec, "MedicalCondition", "Medical_Condition", "medical_condition")),
                medical_details=_to_str(_pick(rec, "MedicalDetails", "medical_details")),

                position=_to_str(_pick(rec, "Position", "position")),
                cscs_number=_to_str(_pick(rec, "CSCSNumber", "cscs_number")),
                cscs_expiry_date=_to_str(_pick(rec, "CSCSExpiryDate", "cscs_expiry_date")),
                employment_type=_to_str(_pick(rec, "EmploymentType", "employment_type")),
                right_to_work_uk=_to_str(_pick(rec, "RightToWorkUK", "right_to_work_uk")),
                national_insurance=_to_str(_pick(rec, "NationalInsurance", "national_insurance")),
                utr=_to_str(_pick(rec, "UTR", "utr")),
                start_date=_to_str(_pick(rec, "StartDate", "start_date")),

                bank_account_number=_to_str(_pick(rec, "BankAccountNumber", "bank_account_number")),
                sort_code=_to_str(_pick(rec, "SortCode", "sort_code")),
                account_holder_name=_to_str(_pick(rec, "AccountHolderName", "account_holder_name")),

                company_trading_name=_to_str(_pick(rec, "CompanyTradingName", "company_trading_name")),
                company_registration_no=_to_str(_pick(rec, "CompanyRegistrationNo", "company_registration_no")),

                date_of_contract=_to_str(_pick(rec, "DateOfContract", "date_of_contract")),
                site_address=_to_str(_pick(rec, "SiteAddress", "site_address")),

                passport_or_birth_cert_link=_to_str(
                    _pick(rec, "PassportOrBirthCertLink", "passport_or_birth_cert_link")),
                cscs_front_back_link=_to_str(_pick(rec, "CSCSFrontBackLink", "cscs_front_back_link")),
                public_liability_link=_to_str(_pick(rec, "PublicLiabilityLink", "public_liability_link")),
                share_code_link=_to_str(_pick(rec, "ShareCodeLink", "share_code_link")),

                contract_accepted=_to_str(_pick(rec, "ContractAccepted", "contract_accepted")),
                signature_name=_to_str(_pick(rec, "SignatureName", "signature_name")),
                signature_datetime=_to_str(
                    _pick(rec, "SignatureDateTime", "signature_datetime", "signature_date_time")),
                submitted_at=_to_str(_pick(rec, "SubmittedAt", "submitted_at")),
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


@app.post("/import-workhours")
def import_workhours():
    gate = require_destructive_admin_post("import_workhours")
    if gate:
        return gate

    if not DB_MIGRATION_MODE:
        return {"error": "migration mode disabled"}, 403
    if not ENABLE_GOOGLE_SHEETS or not SHEETS_IMPORT_ENABLED:
        return {"error": "Google Sheets import disabled"}, 403

    try:
        WorkHour.query.delete(synchronize_session=False)

        records = _get_import_sheet("workhours").get_all_records()
        count = 0

        for rec in records:
            username = _to_str(_pick(rec, "Username", "username", "User"))
            if not username:
                continue

            shift_date = _to_date(_pick(rec, "Date", "date"))
            clock_in_raw = _to_str(_pick(rec, "Clock In", "ClockIn", "Clock_In", "clock_in"))
            clock_out_raw = _to_str(_pick(rec, "Clock Out", "ClockOut", "Clock_Out", "clock_out"))

            clock_in_val = None
            clock_out_val = None

            if shift_date and clock_in_raw:
                for fmt in ("%H:%M:%S", "%H:%M"):
                    try:
                        t = datetime.strptime(clock_in_raw, fmt).time()
                        clock_in_val = datetime.combine(shift_date, t)
                        break
                    except Exception:
                        pass

            if shift_date and clock_out_raw:
                for fmt in ("%H:%M:%S", "%H:%M"):
                    try:
                        t = datetime.strptime(clock_out_raw, fmt).time()
                        clock_out_val = datetime.combine(shift_date, t)
                        break
                    except Exception:
                        pass

            _workplace_id = _to_str(_pick(rec, "Workplace_ID", "workplace_id", default="default")) or "default"

            row = WorkHour(
                employee_email=username,
                date=shift_date,
                clock_in=clock_in_val,
                clock_out=clock_out_val,
                workplace=_workplace_id,
                workplace_id=_workplace_id,
            )
            db.session.add(row)
            count += 1

        db.session.commit()
        return {"status": "ok", "imported": count}

    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}, 500


