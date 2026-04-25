def onboarding_impl(core):
    require_login = core["require_login"]
    get_csrf = core["get_csrf"]
    session = core["session"]
    get_employee_display_name = core["get_employee_display_name"]
    get_onboarding_record = core["get_onboarding_record"]
    request = core["request"]
    require_csrf = core["require_csrf"]
    store_onboarding_file_local = core["store_onboarding_file_local"]
    upload_onboarding_file_persistent = core["upload_onboarding_file_persistent"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    _render_onboarding_page = core["_render_onboarding_page"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    update_or_append_onboarding = core["update_or_append_onboarding"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    OnboardingRecord = core["OnboardingRecord"]
    _session_workplace_id = core["_session_workplace_id"]
    db = core["db"]
    make_response = core["make_response"]
    set_employee_first_last = core["set_employee_first_last"]
    set_employee_field = core["set_employee_field"]

    # PASTE ONLY THE BODY OF onboarding() BELOW THIS LINE

    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    session_username = session["username"]
    role = session.get("role", "employee")

    if role in ("admin", "master_admin"):
        username = (request.args.get("user") or request.form.get(
            "user") or session_username).strip() or session_username
    else:
        username = session_username

    msg = ""
    msg_ok = False
    typed = None
    missing_fields = set()

    try:
        display_name = get_employee_display_name(username) or username
    except Exception as e:
        display_name = username
        msg = f"Could not load employee name: {e}"
        msg_ok = False

    try:
        existing = get_onboarding_record(username)
    except Exception as e:
        existing = None
        msg = f"Could not load onboarding record: {e}"
        msg_ok = False

    if request.method == "POST":
        require_csrf()
        typed = request.form.to_dict(flat=True)
        submit_type = request.form.get("submit_type", "draft")
        is_final = (submit_type == "final")

        def g(name):
            return (request.form.get(name, "") or "").strip()

        def clean_phone_input(value):
            text = str(value or "").strip()

            # Clean old copied/saved values like: +44 +44 +44 +447424790646
            while text.startswith("+44"):
                text = text[3:].strip()

            return text

        first = g("first");
        last = g("last");
        birth = g("birth")

        # Prefix removed from Starter Form. Store only the actual phone number.
        phone_cc = ""
        phone_num = clean_phone_input(g("phone_num"))

        street = g("street");
        city = g("city");
        postcode = g("postcode")
        email = g("email")
        ec_name = g("ec_name");

        # Prefix removed from Starter Form. Store only the actual emergency phone number.
        ec_cc = ""
        ec_phone = clean_phone_input(g("ec_phone"))
        medical = g("medical");
        medical_details = g("medical_details")
        position = g("position");
        cscs_no = g("cscs_no");
        cscs_exp = g("cscs_exp")
        emp_type = g("emp_type");
        rtw = g("rtw")
        ni = g("ni");
        utr = g("utr");
        start_date = g("start_date")
        acc_no = g("acc_no");
        sort_code = g("sort_code");
        acc_name = g("acc_name")
        comp_trading = g("comp_trading");
        comp_reg = g("comp_reg")
        contract_date = g("contract_date");
        site_address = g("site_address")
        contract_accept = (request.form.get("contract_accept", "") == "yes")
        signature_name = g("signature_name")

        passport_file = request.files.get("passport_file")
        cscs_file = request.files.get("cscs_file")
        pli_file = request.files.get("pli_file")
        share_file = request.files.get("share_file")

        missing = []

        def req(value, input_name, label):
            if not value:
                missing.append(label)
                missing_fields.add(input_name)

        if is_final:
            req(first, "first", "First Name")
            req(last, "last", "Last Name")
            req(birth, "birth", "Birth Date")
            req(phone_num, "phone_num", "Phone Number")
            req(email, "email", "Email")
            req(ec_name, "ec_name", "Emergency Contact Name")
            req(ec_phone, "ec_phone", "Emergency Contact Phone")

            if medical not in ("yes", "no"):
                missing.append("Medical condition (Yes/No)")
                missing_fields.add("medical")

            req(position, "position", "Position")
            req(cscs_no, "cscs_no", "CSCS Number")
            req(cscs_exp, "cscs_exp", "CSCS Expiry Date")
            req(emp_type, "emp_type", "Employment Type")

            if rtw not in ("yes", "no"):
                missing.append("Right to work UK (Yes/No)")
                missing_fields.add("rtw")

            req(ni, "ni", "National Insurance")
            req(utr, "utr", "UTR")
            req(start_date, "start_date", "Start Date")
            req(acc_no, "acc_no", "Bank Account Number")
            req(sort_code, "sort_code", "Sort Code")
            req(acc_name, "acc_name", "Account Holder Name")
            req(contract_date, "contract_date", "Date of Contract")
            req(site_address, "site_address", "Site address")

            if not contract_accept:
                missing.append("Contract acceptance")
                missing_fields.add("contract_accept")

            req(signature_name, "signature_name", "Signature name")

            if not passport_file or not passport_file.filename:
                missing.append("Passport/Birth Certificate file")
                missing_fields.add("passport_file")
            if not cscs_file or not cscs_file.filename:
                missing.append("CSCS (front/back) file")
                missing_fields.add("cscs_file")
            if not pli_file or not pli_file.filename:
                missing.append("Public Liability file")
                missing_fields.add("pli_file")
            if not share_file or not share_file.filename:
                missing.append("Share code file")
                missing_fields.add("share_file")

        if missing:
            msg = "Missing required (final): " + ", ".join(missing)
            msg_ok = False
        else:
            def v(key: str) -> str:
                return (existing or {}).get(key, "")

            passport_link = v("PassportOrBirthCertLink")
            cscs_link = v("CSCSFrontBackLink")
            pli_link = v("PublicLiabilityLink")
            share_link = v("ShareCodeLink")

            try:
                if passport_file and passport_file.filename:
                    passport_link = upload_onboarding_file_persistent(passport_file, username, "passport")
                if cscs_file and cscs_file.filename:
                    cscs_link = upload_onboarding_file_persistent(cscs_file, username, "cscs")
                if pli_file and pli_file.filename:
                    pli_link = upload_onboarding_file_persistent(pli_file, username, "pli")
                if share_file and share_file.filename:
                    share_link = upload_onboarding_file_persistent(share_file, username, "share")
            except Exception as e:
                msg = f"Upload error: {e}"
                msg_ok = False
                existing = get_onboarding_record(username)
                return render_template_string(
                    f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell(
                        "agreements", role,
                        _render_onboarding_page(display_name, role, csrf, existing, msg, msg_ok, typed, set())
                    )
                )

            now_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

            data = {
                "FirstName": first,
                "LastName": last,
                "BirthDate": birth,
                "PhoneCountryCode": phone_cc,
                "PhoneNumber": phone_num,
                "StreetAddress": street,
                "City": city,
                "Postcode": postcode,
                "Email": email,
                "EmergencyContactName": ec_name,
                "EmergencyContactPhoneCountryCode": ec_cc,
                "EmergencyContactPhoneNumber": ec_phone,
                "MedicalCondition": medical,
                "MedicalDetails": medical_details,
                "Position": position,
                "CSCSNumber": cscs_no,
                "CSCSExpiryDate": cscs_exp,
                "EmploymentType": emp_type,
                "RightToWorkUK": rtw,
                "NationalInsurance": ni,
                "UTR": utr,
                "StartDate": start_date,
                "BankAccountNumber": acc_no,
                "SortCode": sort_code,
                "AccountHolderName": acc_name,
                "CompanyTradingName": comp_trading,
                "CompanyRegistrationNo": comp_reg,
                "DateOfContract": contract_date,
                "SiteAddress": site_address,
                "PassportOrBirthCertLink": passport_link,
                "CSCSFrontBackLink": cscs_link,
                "PublicLiabilityLink": pli_link,
                "ShareCodeLink": share_link,
                "ContractAccepted": "TRUE" if (is_final and contract_accept) else "FALSE",
                "SignatureName": signature_name,
                "SignatureDateTime": now_str if is_final else "",
                "SubmittedAt": now_str,
            }

            update_or_append_onboarding(username, data)
            if DB_MIGRATION_MODE:
                try:
                    phone_full = " ".join([x for x in [phone_cc, phone_num] if x]).strip()
                    emergency_phone_full = " ".join([x for x in [ec_cc, ec_phone] if x]).strip()
                    address_full = ", ".join([x for x in [street, city, postcode] if x]).strip()

                    db_row = OnboardingRecord.query.filter_by(username=username,
                                                              workplace_id=_session_workplace_id()).first()

                    if db_row:
                        db_row.first_name = first
                        db_row.last_name = last
                        db_row.birth_date = birth
                        db_row.phone = phone_full
                        db_row.email = email
                        db_row.address = address_full
                        db_row.emergency_contact_name = ec_name
                        db_row.emergency_contact_phone = emergency_phone_full
                        db_row.medical_condition = medical
                        db_row.position = position
                    else:
                        db.session.add(
                            OnboardingRecord(
                                username=username,
                                workplace_id=_session_workplace_id(),
                                first_name=first,
                                last_name=last,
                                birth_date=birth,
                                phone=phone_full,
                                email=email,
                                address=address_full,
                                emergency_contact_name=ec_name,
                                emergency_contact_phone=emergency_phone_full,
                                medical_condition=medical,
                                position=position,
                            )
                        )

                    db.session.commit()
                except Exception:
                    db.session.rollback()
            set_employee_first_last(username, first, last)
            if is_final:
                set_employee_field(username, "OnboardingCompleted", "TRUE")
                set_employee_field(username, "Workplace_ID", _session_workplace_id())

            existing = get_onboarding_record(username)
            msg = "Saved draft." if not is_final else "Submitted final successfully."
            msg_ok = True
            typed = None
            missing_fields = set()

    try:
        content = _render_onboarding_page(display_name, role, csrf, existing, msg, msg_ok, typed, missing_fields)
    except Exception as e:
        return make_response(f"Could not render onboarding page: {e}", 500)

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("agreements", role, content)
    )
