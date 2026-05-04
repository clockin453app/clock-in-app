def change_password_impl(core):
    require_login = core["require_login"]
    get_csrf = core["get_csrf"]
    session = core["session"]
    get_employee_display_name = core["get_employee_display_name"]
    onboarding_details_block = core["onboarding_details_block"]
    request = core["request"]
    require_csrf = core["require_csrf"]
    _find_employee_record = core["_find_employee_record"]
    is_password_valid = core["is_password_valid"]
    update_employee_password = core["update_employee_password"]
    page_back_button = core["page_back_button"]
    escape = core["escape"]
    render_page = core["render_page"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    layout_shell = core["layout_shell"]

    gate = require_login()
    if gate:
        return gate

    csrf = get_csrf()
    username = session["username"]
    role = session.get("role", "employee")
    display_name = get_employee_display_name(username)


    details_html = onboarding_details_block(username)

    msg = ""
    ok = False

    if request.method == "POST":
        require_csrf()
        current = request.form.get("current", "")
        new1 = request.form.get("new1", "")
        new2 = request.form.get("new2", "")

        stored_pw = None
        user_row = _find_employee_record(username)
        if user_row:
            stored_pw = user_row.get("Password", "")

        if stored_pw is None or not is_password_valid(stored_pw, current):
            msg = "Current password is incorrect."
            ok = False
        elif len(new1) < 8:
            msg = "New password too short (min 8)."
            ok = False
        elif new1 != new2:
            msg = "New passwords do not match."
            ok = False
        else:
            ok = update_employee_password(username, new1)
            msg = "Password updated successfully." if ok else "Could not update password."

        details_html = onboarding_details_block(username)

    return render_page(
        template_name="account/change_password.html",
        active="profile",
        role=role,
        layout_shell=layout_shell,
        style=STYLE,
        viewport=VIEWPORT,
        pwa_tags=PWA_TAGS,
        page_back_html=page_back_button("/", "Back to dashboard"),
        csrf=csrf,
        display_name=display_name,
        details_html=details_html,
        msg=msg,
        ok=ok,
    )
