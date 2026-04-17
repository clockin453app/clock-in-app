def import_onboarding_data(
    onboarding_record_model,
    get_import_sheet_func,
    to_str_func,
    pick_func,
    db_session,
):
    onboarding_record_model.query.delete(synchronize_session=False)

    records = get_import_sheet_func("onboarding").get_all_records()
    count = 0

    for rec in records:
        username = to_str_func(pick_func(rec, "Username", "username"))
        if not username:
            continue

        phone_cc = to_str_func(pick_func(rec, "PhoneCountryCode", "phone_country_code"))
        phone_num = to_str_func(pick_func(rec, "PhoneNumber", "Phone", "phone_number", "phone"))
        ec_cc = to_str_func(pick_func(rec, "EmergencyContactPhoneCountryCode", "emergency_contact_phone_country_code"))
        ec_num = to_str_func(
            pick_func(
                rec,
                "EmergencyContactPhoneNumber",
                "EmergencyContactPhone",
                "Emergency_Contact_Phone",
                "emergency_contact_phone_number",
            )
        )

        street = to_str_func(pick_func(rec, "StreetAddress", "street_address"))
        city = to_str_func(pick_func(rec, "City", "city"))
        postcode = to_str_func(pick_func(rec, "Postcode", "postcode"))

        address_joined = ", ".join([x for x in [street, city, postcode] if x]).strip()
        phone_joined = " ".join([x for x in [phone_cc, phone_num] if x]).strip()
        ec_phone_joined = " ".join([x for x in [ec_cc, ec_num] if x]).strip()

        row = onboarding_record_model(
            username=username,
            workplace_id=to_str_func(pick_func(rec, "Workplace_ID", "workplace_id", default="default")),

            first_name=to_str_func(pick_func(rec, "FirstName", "First_Name", "first_name")),
            last_name=to_str_func(pick_func(rec, "LastName", "Last_Name", "last_name")),
            birth_date=to_str_func(pick_func(rec, "BirthDate", "Birth_Date", "birth_date")),

            phone_country_code=phone_cc,
            phone_number=phone_num,
            phone=phone_joined,

            email=to_str_func(pick_func(rec, "Email", "email")),

            street_address=street,
            city=city,
            postcode=postcode,
            address=address_joined,

            emergency_contact_name=to_str_func(pick_func(rec, "EmergencyContactName", "Emergency_Contact_Name")),
            emergency_contact_phone_country_code=ec_cc,
            emergency_contact_phone_number=ec_num,
            emergency_contact_phone=ec_phone_joined,

            medical_condition=to_str_func(pick_func(rec, "MedicalCondition", "Medical_Condition", "medical_condition")),
            medical_details=to_str_func(pick_func(rec, "MedicalDetails", "medical_details")),

            position=to_str_func(pick_func(rec, "Position", "position")),
            cscs_number=to_str_func(pick_func(rec, "CSCSNumber", "cscs_number")),
            cscs_expiry_date=to_str_func(pick_func(rec, "CSCSExpiryDate", "cscs_expiry_date")),
            employment_type=to_str_func(pick_func(rec, "EmploymentType", "employment_type")),
            right_to_work_uk=to_str_func(pick_func(rec, "RightToWorkUK", "right_to_work_uk")),
            national_insurance=to_str_func(pick_func(rec, "NationalInsurance", "national_insurance")),
            utr=to_str_func(pick_func(rec, "UTR", "utr")),
            start_date=to_str_func(pick_func(rec, "StartDate", "start_date")),

            bank_account_number=to_str_func(pick_func(rec, "BankAccountNumber", "bank_account_number")),
            sort_code=to_str_func(pick_func(rec, "SortCode", "sort_code")),
            account_holder_name=to_str_func(pick_func(rec, "AccountHolderName", "account_holder_name")),

            company_trading_name=to_str_func(pick_func(rec, "CompanyTradingName", "company_trading_name")),
            company_registration_no=to_str_func(pick_func(rec, "CompanyRegistrationNo", "company_registration_no")),

            date_of_contract=to_str_func(pick_func(rec, "DateOfContract", "date_of_contract")),
            site_address=to_str_func(pick_func(rec, "SiteAddress", "site_address")),

            passport_or_birth_cert_link=to_str_func(
                pick_func(rec, "PassportOrBirthCertLink", "passport_or_birth_cert_link")
            ),
            cscs_front_back_link=to_str_func(pick_func(rec, "CSCSFrontBackLink", "cscs_front_back_link")),
            public_liability_link=to_str_func(pick_func(rec, "PublicLiabilityLink", "public_liability_link")),
            share_code_link=to_str_func(pick_func(rec, "ShareCodeLink", "share_code_link")),

            contract_accepted=to_str_func(pick_func(rec, "ContractAccepted", "contract_accepted")),
            signature_name=to_str_func(pick_func(rec, "SignatureName", "signature_name")),
            signature_datetime=to_str_func(
                pick_func(rec, "SignatureDateTime", "signature_datetime", "signature_date_time")
            ),
            submitted_at=to_str_func(pick_func(rec, "SubmittedAt", "submitted_at")),
        )
        db_session.add(row)
        count += 1

    db_session.commit()
    return {"status": "ok", "imported": count}

def import_workhours_data(
    workhour_model,
    get_import_sheet_func,
    to_str_func,
    to_date_func,
    pick_func,
    datetime_cls,
    db_session,
):
    records = get_import_sheet_func("workhours").get_all_records()
    count = 0

    for rec in records:
        username = to_str_func(pick_func(rec, "Username", "username", "User"))
        if not username:
            continue

        shift_date = to_date_func(pick_func(rec, "Date", "date"))
        clock_in_raw = to_str_func(pick_func(rec, "Clock In", "ClockIn", "Clock_In", "clock_in"))
        clock_out_raw = to_str_func(pick_func(rec, "Clock Out", "ClockOut", "Clock_Out", "clock_out"))

        clock_in_val = None
        clock_out_val = None

        if shift_date and clock_in_raw:
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    t = datetime_cls.strptime(clock_in_raw, fmt).time()
                    clock_in_val = datetime_cls.combine(shift_date, t)
                    break
                except Exception:
                    pass

        if shift_date and clock_out_raw:
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    t = datetime_cls.strptime(clock_out_raw, fmt).time()
                    clock_out_val = datetime_cls.combine(shift_date, t)
                    break
                except Exception:
                    pass

        workplace_id = to_str_func(pick_func(rec, "Workplace_ID", "workplace_id", default="default")) or "default"

        row = workhour_model(
            employee_email=username,
            date=shift_date,
            clock_in=clock_in_val,
            clock_out=clock_out_val,
            workplace=workplace_id,
            workplace_id=workplace_id,
        )
        db_session.add(row)
        count += 1

    db_session.commit()
    return {"status": "ok", "imported": count}


def import_payroll_data(
    payroll_report_model,
    get_import_sheet_func,
    to_str_func,
    to_date_func,
    to_datetime_func,
    to_decimal_func,
    pick_func,
    db_session,
):
    records = get_import_sheet_func("payroll").get_all_records()
    count = 0

    for rec in records:
        username = to_str_func(pick_func(rec, "Username", "username", "User"))
        if not username:
            continue

        row = payroll_report_model(
            username=username,
            week_start=to_date_func(pick_func(rec, "Week_Start", "WeekStart", "week_start")),
            week_end=to_date_func(pick_func(rec, "Week_End", "WeekEnd", "week_end")),
            gross=to_decimal_func(pick_func(rec, "Gross", "Gross_Pay", "gross")),
            tax=to_decimal_func(pick_func(rec, "Tax", "Tax_Amount", "tax")),
            net=to_decimal_func(pick_func(rec, "Net", "Net_Pay", "net")),
            paid_at=to_datetime_func(pick_func(rec, "Paid_At", "PaidAt", "paid_at")),
            paid_by=to_str_func(pick_func(rec, "Paid_By", "PaidBy", "paid_by")),
            paid=to_str_func(pick_func(rec, "Paid", "paid")),
            workplace_id=to_str_func(pick_func(rec, "Workplace_ID", "workplace_id", default="default")),
        )
        db_session.add(row)
        count += 1

    db_session.commit()
    return {"status": "ok", "imported": count}

from decimal import Decimal


def import_employees_data(
    employee_model,
    get_import_sheet_func,
    normalize_password_hash_value_func,
    db_session,
):
    records = get_import_sheet_func("employees").get_all_records()
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
        password = normalize_password_hash_value_func(str(rec.get("Password", "")).strip())
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

        employee = employee_model(
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
        db_session.add(employee)
        count += 1

    db_session.commit()
    return {"status": "ok", "imported": count}


def import_settings_data(
    workplace_setting_model,
    get_import_sheet_func,
    to_str_func,
    to_decimal_func,
    pick_func,
    db_session,
):
    workplace_setting_model.query.delete(synchronize_session=False)

    records = get_import_sheet_func("settings").get_all_records()
    count = 0

    for rec in records:
        workplace_id = to_str_func(pick_func(rec, "Workplace_ID", "workplace_id", default="default"))
        if not workplace_id:
            workplace_id = "default"

        row = workplace_setting_model(
            workplace_id=workplace_id,
            tax_rate=to_decimal_func(pick_func(rec, "Tax_Rate", "TaxRate", "tax_rate")),
            currency_symbol=to_str_func(pick_func(rec, "Currency_Symbol", "Currency", "currency_symbol")),
            company_name=to_str_func(pick_func(rec, "Company_Name", "Company", "company_name")),
        )
        db_session.add(row)
        count += 1

    db_session.commit()
    return {"status": "ok", "imported": count}


def import_locations_data(
    location_model,
    get_locations_func,
    to_str_func,
    to_decimal_func,
    to_int_func,
    pick_func,
    db_session,
):
    location_model.query.delete(synchronize_session=False)

    records = get_locations_func()
    count = 0

    for rec in records:
        site_name = to_str_func(pick_func(rec, "Site", "SiteName", "site_name", "Name"))
        if not site_name:
            continue

        row = location_model(
            site_name=site_name,
            lat=to_decimal_func(pick_func(rec, "Lat", "Latitude", "lat")),
            lon=to_decimal_func(pick_func(rec, "Lon", "Lng", "Longitude", "lon")),
            radius_meters=to_int_func(pick_func(rec, "Radius", "RadiusMeters", "radius_meters")),
            active=to_str_func(pick_func(rec, "Active", "active", default="yes")),
            workplace_id=to_str_func(pick_func(rec, "Workplace_ID", "workplace_id", default="default")),
        )
        db_session.add(row)
        count += 1

    db_session.commit()
    return {"status": "ok", "imported": count}

def import_audit_data(
    audit_log_model,
    get_import_sheet_func,
    to_str_func,
    to_datetime_func,
    pick_func,
    db_session,
):
    audit_log_model.query.delete(synchronize_session=False)

    records = get_import_sheet_func("audit").get_all_records()
    count = 0

    for rec in records:
        action = to_str_func(pick_func(rec, "Action", "action"))
        user_email = to_str_func(pick_func(rec, "Username", "User", "Actor", "user_email"))

        if not action and not user_email:
            continue

        row = audit_log_model(
            action=action or "unknown",
            user_email=user_email,
            created_at=to_datetime_func(pick_func(rec, "Timestamp", "Created_At", "DateTime", "created_at")),
        )
        db_session.add(row)
        count += 1

    db_session.commit()
    return {"status": "ok", "imported": count}