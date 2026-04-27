from datetime import date, datetime, timedelta
def admin_onboarding_detail_impl(core, username):
    require_admin = core["require_admin"]
    get_onboarding_record = core["get_onboarding_record"]
    abort = core["abort"]
    _session_workplace_id = core["_session_workplace_id"]
    linkify = core["linkify"]
    escape = core["escape"]
    admin_back_link = core["admin_back_link"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]
    session = core["session"]

    gate = require_admin()
    if gate:
        return gate

    rec = get_onboarding_record(username)
    if not rec:
        abort(404)

    rec_wp = (rec.get("Workplace_ID") or "").strip() or "default"
    if rec_wp != _session_workplace_id():
        abort(404)

    def clean_phone(value):
        text = str(value or "").strip()

        # Remove repeated +44 prefixes, including old bad values like:
        # +44 +44 +44 +44 +447424790646
        while text.startswith("+44"):
            text = text[3:].strip()

        return text

    def display_value(key):
        if key in ("PhoneNumber", "EmergencyContactPhoneNumber"):
            return clean_phone(rec.get(key, ""))
        return rec.get(key, "")

    def row(label, key, link=False):
        v_ = display_value(key)
        vv = linkify(v_) if link else escape(v_)
        return f"<tr><th style='width:260px;'>{escape(label)}</th><td>{vv}</td></tr>"

    details = ""
    for label, key in [
        ("Username", "Username"),
        ("First name", "FirstName"),
        ("Last name", "LastName"),
        ("Birth date", "BirthDate"),
        ("Phone", "PhoneNumber"),
        ("Email", "Email"),
        ("Street", "StreetAddress"),
        ("City", "City"),
        ("Postcode", "Postcode"),
        ("Emergency contact", "EmergencyContactName"),
        ("Emergency phone", "EmergencyContactPhoneNumber"),
        ("Medical", "MedicalCondition"),
        ("Medical details", "MedicalDetails"),
        ("Position", "Position"),
        ("CSCS number", "CSCSNumber"),
        ("CSCS expiry", "CSCSExpiryDate"),
        ("Employment type", "EmploymentType"),
        ("Right to work UK", "RightToWorkUK"),
        ("NI", "NationalInsurance"),
        ("UTR", "UTR"),
        ("Start date", "StartDate"),
        ("Bank account", "BankAccountNumber"),
        ("Sort code", "SortCode"),
        ("Account holder", "AccountHolderName"),
        ("Company trading", "CompanyTradingName"),
        ("Company reg", "CompanyRegistrationNo"),
        ("Date of contract", "DateOfContract"),
        ("Site address", "SiteAddress"),
    ]:
        details += row(label, key)

    details += row("Passport/Birth cert", "PassportOrBirthCertLink", link=True)
    details += row("CSCS front/back", "CSCSFrontBackLink", link=True)
    details += row("Public liability", "PublicLiabilityLink", link=True)
    details += row("Share code", "ShareCodeLink", link=True)
    details += row("Contract accepted", "ContractAccepted")
    details += row("Signature name", "SignatureName")

    signature_image_data = str(rec.get("SignatureImageData", "") or "").strip()
    if signature_image_data.startswith("data:image/png;base64,"):
        details += (
            "<tr>"
            "<th style='width:260px;'>Drawn signature</th>"
            f"<td><img src='{escape(signature_image_data)}' alt='Signature' style='max-width:320px; max-height:120px; border:1px solid #e5e7eb; background:#fff; padding:8px;'></td>"
            "</tr>"
        )

    details += row("Signature time", "SignatureDateTime")
    details += row("Last saved", "SubmittedAt")
    def parse_onboarding_date(value):
        text = str(value or "").strip()
        if not text:
            return None

        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(text[:10], fmt).date()
            except Exception:
                pass

        return None

    warning_items = []

    cscs_expiry = display_value("CSCSExpiryDate")
    cscs_date = parse_onboarding_date(cscs_expiry)

    if not cscs_date:
        warning_items.append(("warn", "CSCS expiry date missing"))
    elif cscs_date < date.today():
        warning_items.append(("bad", f"CSCS expired on {cscs_date.strftime('%d/%m/%Y')}"))
    elif cscs_date <= date.today() + timedelta(days=30):
        warning_items.append(("warn", f"CSCS expires soon on {cscs_date.strftime('%d/%m/%Y')}"))

    missing_docs = []

    for label, key in [
        ("Passport/Birth certificate", "PassportOrBirthCertLink"),
        ("CSCS front/back", "CSCSFrontBackLink"),
        ("Public liability", "PublicLiabilityLink"),
        ("Share code", "ShareCodeLink"),
    ]:
        if not str(display_value(key) or "").strip():
            missing_docs.append(label)

    if missing_docs:
        warning_items.append(("warn", "Missing documents: " + ", ".join(missing_docs)))

    if str(display_value("RightToWorkUK") or "").strip().lower() != "yes":
        warning_items.append(("warn", "Right to work needs checking"))

    contract_value = str(display_value("ContractAccepted") or "").strip().lower()

    if contract_value not in {"true", "yes", "1", "accepted", "signed"}:
        warning_items.append(("warn", "Contract not signed"))

    if warning_items:
        warning_rows = []

        for level, text in warning_items:
            if level == "bad":
                bg = "#fee2e2"
                border = "#fecaca"
                color = "#b91c1c"
            else:
                bg = "#fef3c7"
                border = "#fde68a"
                color = "#92400e"

            warning_rows.append(
                f"<div style='padding:8px 10px; border:1px solid {border}; background:{bg}; color:{color}; font-size:13px; font-weight:800; margin-top:6px;'>"
                f"{escape(text)}</div>"
            )

        document_warning_html = f"""
          <div class="card" style="padding:12px; margin-bottom:12px;">
            <h2 style="margin:0;">Document checks</h2>
            <p class="sub" style="margin:4px 0 8px 0;">Expiry and missing-document warnings for this worker.</p>
            {''.join(warning_rows)}
          </div>
        """
    else:
        document_warning_html = """
          <div class="card" style="padding:12px; margin-bottom:12px;">
            <h2 style="margin:0;">Document checks</h2>
            <p class="sub" style="margin:4px 0 0 0;">All key document checks look complete.</p>
          </div>
        """

    content = f"""
          <div class="headerTop">
            <div>
              <h1>Onboarding Details</h1>
              <p class="sub">{escape(username)}</p>
            </div>
            <div class="badge admin">ADMIN</div>
          </div>

                    {admin_back_link()}

          {document_warning_html}

          <div class="card" style="padding:12px;">
            <div class="actionRow" style="margin-bottom:12px; grid-template-columns:1fr auto;">
              <div class="sub">Share or save this form as PDF even if no images were uploaded.</div>
              <a href="/admin/onboarding/{escape(username)}/download" target="_blank" rel="noopener" style="text-decoration:none; font-size:12px; font-weight:700; color:#3b74ad; white-space:nowrap;">PDF</a>
            </div>

            <div class="tablewrap">
              <table style="min-width: 720px;"><tbody>{details}</tbody></table>
            </div>
          </div>
        """

    return render_template_string(
        f"{STYLE}{VIEWPORT}{PWA_TAGS}" +
        layout_shell("admin", session.get("role", "admin"), content)
    )