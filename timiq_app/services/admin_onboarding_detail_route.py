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
    details += row("Signature time", "SignatureDateTime")
    details += row("Last saved", "SubmittedAt")

    content = f"""
          <div class="headerTop">
            <div>
              <h1>Onboarding Details</h1>
              <p class="sub">{escape(username)}</p>
            </div>
            <div class="badge admin">ADMIN</div>
          </div>

          {admin_back_link()}

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