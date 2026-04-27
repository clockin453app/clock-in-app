def admin_onboarding_download_impl(core, username):
    require_admin = core["require_admin"]
    get_onboarding_record = core["get_onboarding_record"]
    abort = core["abort"]
    _session_workplace_id = core["_session_workplace_id"]
    get_company_settings = core["get_company_settings"]
    escape = core["escape"]
    datetime = core["datetime"]
    TZ = core["TZ"]
    page_back_button = core["page_back_button"]
    render_template_string = core["render_template_string"]

    gate = require_admin()
    if gate:
        return gate

    rec = get_onboarding_record(username)
    if not rec:
        abort(404)

    rec_wp = (rec.get("Workplace_ID") or "").strip() or "default"
    if rec_wp != _session_workplace_id():
        abort(404)

    settings = get_company_settings()
    company_name = str(settings.get("Company_Name", "WorkHours") or "WorkHours")
    currency = str(settings.get("Currency_Symbol", "£") or "£")

    display_name = (
            ((rec.get("FirstName") or "").strip() + " " + (rec.get("LastName") or "").strip()).strip()
            or (rec.get("Username") or "").strip()
            or username
    )

    def show(key):
        return escape((rec.get(key, "") or "").strip() or "—")

    def clean_phone_value(key):
        text = str(rec.get(key, "") or "").strip()

        while text.startswith("+44"):
            text = text[3:].strip()

        return escape(text or "—")

    def doc_status(label, key):
        link = (rec.get(key, "") or "").strip()
        if link:
            return f"<tr><th>{escape(label)}</th><td>Uploaded</td></tr>"
        return f"<tr><th>{escape(label)}</th><td>Not uploaded</td></tr>"

    personal_rows = "".join([
        f"<tr><th>First name</th><td>{show('FirstName')}</td></tr>",
        f"<tr><th>Last name</th><td>{show('LastName')}</td></tr>",
        f"<tr><th>Birth date</th><td>{show('BirthDate')}</td></tr>",
        f"<tr><th>Phone</th><td>{clean_phone_value('PhoneNumber')}</td></tr>",
        f"<tr><th>Email</th><td>{show('Email')}</td></tr>",
        f"<tr><th>Street</th><td>{show('StreetAddress')}</td></tr>",
        f"<tr><th>City</th><td>{show('City')}</td></tr>",
        f"<tr><th>Postcode</th><td>{show('Postcode')}</td></tr>",
    ])

    work_rows = "".join([
        f"<tr><th>Emergency contact</th><td>{show('EmergencyContactName')}</td></tr>",
        f"<tr><th>Emergency phone</th><td>{clean_phone_value('EmergencyContactPhoneNumber')}</td></tr>",
        f"<tr><th>Medical condition</th><td>{show('MedicalCondition')}</td></tr>",
        f"<tr><th>Medical details</th><td>{show('MedicalDetails')}</td></tr>",
        f"<tr><th>Position</th><td>{show('Position')}</td></tr>",
        f"<tr><th>CSCS number</th><td>{show('CSCSNumber')}</td></tr>",
        f"<tr><th>CSCS expiry</th><td>{show('CSCSExpiryDate')}</td></tr>",
        f"<tr><th>Employment type</th><td>{show('EmploymentType')}</td></tr>",
        f"<tr><th>Right to work UK</th><td>{show('RightToWorkUK')}</td></tr>",
        f"<tr><th>NI</th><td>{show('NationalInsurance')}</td></tr>",
        f"<tr><th>UTR</th><td>{show('UTR')}</td></tr>",
        f"<tr><th>Start date</th><td>{show('StartDate')}</td></tr>",
    ])

    signature_image_data = str(rec.get("SignatureImageData", "") or "").strip()

    signature_image_row = ""
    if signature_image_data.startswith("data:image/png;base64,"):
        signature_image_row = (
            "<tr>"
            "<th>Drawn signature</th>"
            f"<td><img src='{escape(signature_image_data)}' alt='Signature' "
            "style='max-width:320px; max-height:120px; border:1px solid #e5e7eb; background:#fff; padding:8px;'></td>"
            "</tr>"
        )

    company_rows = "".join([
        f"<tr><th>Bank account</th><td>{show('BankAccountNumber')}</td></tr>",
        f"<tr><th>Sort code</th><td>{show('SortCode')}</td></tr>",
        f"<tr><th>Account holder</th><td>{show('AccountHolderName')}</td></tr>",
        f"<tr><th>Company trading</th><td>{show('CompanyTradingName')}</td></tr>",
        f"<tr><th>Company reg no</th><td>{show('CompanyRegistrationNo')}</td></tr>",
        f"<tr><th>Date of contract</th><td>{show('DateOfContract')}</td></tr>",
        f"<tr><th>Site address</th><td>{show('SiteAddress')}</td></tr>",
        f"<tr><th>Contract accepted</th><td>{show('ContractAccepted')}</td></tr>",
        f"<tr><th>Signature name</th><td>{show('SignatureName')}</td></tr>",
        signature_image_row,
        f"<tr><th>Signature time</th><td>{show('SignatureDateTime')}</td></tr>",
        f"<tr><th>Last saved</th><td>{show('SubmittedAt')}</td></tr>",
    ])

    doc_rows = "".join([
        doc_status("Passport / Birth cert", "PassportOrBirthCertLink"),
        doc_status("CSCS front / back", "CSCSFrontBackLink"),
        doc_status("Public liability", "PublicLiabilityLink"),
        doc_status("Share code", "ShareCodeLink"),
    ])

    page = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Onboarding Form - {escape(display_name)}</title>
      <style>
        body {{
          margin: 0;
          background: #f5f6fb;
          color: #1f2547;
          font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }}

        .printWrap {{
          max-width: 980px;
          margin: 24px auto;
          padding: 0 16px;
        }}

        .toolbar {{
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          margin-bottom: 14px;
        }}

        .btn {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-height: 44px;
          padding: 0 16px;
          border-radius: 0 !important;
          text-decoration: none;
          font-weight: 800;
          border: 1px solid rgba(68,130,195,.12);
          background: #fff;
          color: #4338ca;
          box-shadow: 0 8px 18px rgba(15,23,42,.06);
        }}

        .btnPrimary {{
          color: #fff;
          border: 0;
          background: linear-gradient(90deg, #4f89c7, #3b74ad);
          box-shadow: 0 12px 24px rgba(79,70,229,.20);
        }}

        .sheet {{
          background: #fff;
          border: 1px solid #e7e8f0;
          box-shadow: 0 20px 40px rgba(15,23,42,.08);
        }}

        .sheetHead {{
          padding: 22px 24px 14px;
          border-bottom: 1px solid #ececf4;
        }}

        .sheetTop {{
          display: grid;
          grid-template-columns: 1.2fr 1fr;
          gap: 18px;
          align-items: start;
        }}

        .eyebrow {{
          display: inline-flex;
          align-items: center;
          padding: 8px 12px;
          border-radius: 0 !important;
          border: 1px solid rgba(68,130,195,.12);
          background: rgba(68,130,195,.06);
          color: #3b74ad;
          font-size: 12px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: .05em;
        }}

        .sheetTitle {{
          margin: 14px 0 8px;
          font-size: 34px;
          line-height: 1.02;
          letter-spacing: -.03em;
          font-weight: 900;
          color: #111827;
        }}

        .sheetSub {{
          color: #6f6c85;
          font-size: 14px;
          line-height: 1.6;
        }}

        .meta {{
          text-align: right;
          font-size: 12px;
          line-height: 1.7;
          color: #6b7280;
        }}

        .meta strong {{
          color: #111827;
        }}

        .section {{
          padding: 16px 24px 0;
        }}

        .sectionTitle {{
          margin: 0 0 10px 0;
          color: #3b74ad;
          font-size: 12px;
          font-weight: 900;
          letter-spacing: .07em;
          text-transform: uppercase;
        }}

        table {{
          width: 100%;
          border-collapse: collapse;
          table-layout: fixed;
          background: #fff;
          border: 1px solid #e7e8f0;
        }}

        th, td {{
          border-bottom: 1px solid #edf0f5;
          padding: 10px 12px;
          text-align: left;
          vertical-align: top;
          font-size: 13px;
        }}

        th {{
          width: 240px;
          color: #4b5563;
          background: #f7f8fc;
          font-weight: 800;
        }}

        td {{
          color: #111827;
          word-break: break-word;
        }}

        .bottomSpace {{
          height: 18px;
        }}

        .bar {{
          height: 12px;
          background: linear-gradient(90deg, #4482c3 0%, #3b74ad 40%, #2563eb 100%);
        }}

        @media (max-width: 760px) {{
          .sheetTop {{
            grid-template-columns: 1fr;
          }}
          .meta {{
            text-align: left;
          }}
          th {{
            width: 42%;
          }}
        }}

        @media print {{
          body {{
            background: #fff;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }}
          .toolbar {{
            display: none !important;
          }}
          .printWrap {{
            max-width: none;
            margin: 0;
            padding: 0;
          }}
          .sheet {{
            box-shadow: none;
            border: none;
          }}
        }}
      </style>
    </head>
    <body>
      <div class="printWrap">
        <div class="toolbar">
          {page_back_button(f"/admin/onboarding/{escape(username)}", "Back to details")}
          <button class="btn btnPrimary" onclick="window.print()">Save / Print Form</button>
        </div>

        <div class="sheet">
          <div class="sheetHead">
            <div class="sheetTop">
              <div>
                <div class="eyebrow">Onboarding Form</div>
                <div class="sheetTitle">{escape(display_name)}</div>
                <div class="sheetSub">{escape(company_name)}<br>Starter form / onboarding record</div>
              </div>
              <div class="meta">
                <div><strong>Workplace:</strong> {escape(rec_wp)}</div>
                <div><strong>Generated:</strong> {escape(datetime.now(TZ).strftime("%d/%m/%Y %H:%M"))}</div>
                <div><strong>Last saved:</strong> {show('SubmittedAt')}</div>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="sectionTitle">Personal details</div>
            <table><tbody>{personal_rows}</tbody></table>
          </div>

          <div class="section">
            <div class="sectionTitle">Employment & emergency details</div>
            <table><tbody>{work_rows}</tbody></table>
          </div>

          <div class="section">
            <div class="sectionTitle">Company / contract details</div>
            <table><tbody>{company_rows}</tbody></table>
          </div>

          <div class="section">
            <div class="sectionTitle">Uploaded documents</div>
            <table><tbody>{doc_rows}</tbody></table>
          </div>

          <div class="bottomSpace"></div>
          <div class="bar"></div>
        </div>
      </div>
    </body>
    </html>
    """
    return render_template_string(page)


# ---------- ADMIN LOCATIONS (Geofencing) ----------
