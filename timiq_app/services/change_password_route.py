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
    render_template_string = core["render_template_string"]
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

    content = f"""
          {page_back_button("/", "Back to dashboard")}

          <div class="headerTop">
            <div>
              <h1>Profile</h1>
              <p class="sub">{escape(display_name)}</p>
            </div>
            <div class="badge {'admin' if role == 'admin' else ''}">{escape(role.upper())}</div>
          </div>

          {("<div class='message'>" + escape(msg) + "</div>") if (msg and ok) else ""}
          {("<div class='message error'>" + escape(msg) + "</div>") if (msg and not ok) else ""}

          <div class="card" style="padding:14px;">
            <h2>My Details</h2>
            <p class="sub">Saved from Starter Form (files not shown).</p>
            {details_html}
          </div>

          <div class="card" style="padding:14px; margin-top:12px;">
            <h2>Change Password</h2>
            <form method="POST">
              <input type="hidden" name="csrf" value="{escape(csrf)}">
              <label class="sub">Current password</label>
              <input class="input" type="password" name="current" required>

              <label class="sub" style="margin-top:10px; display:block;">New password</label>
              <input class="input" type="password" name="new1" required>

              <label class="sub" style="margin-top:10px; display:block;">Repeat new password</label>
              <input class="input" type="password" name="new2" required>

              <button class="btnSoft" type="submit" style="margin-top:12px;">Save</button>
            </form>
          </div>
        """
    return render_template_string(f"{STYLE}{VIEWPORT}{PWA_TAGS}" + layout_shell("profile", role, content))
