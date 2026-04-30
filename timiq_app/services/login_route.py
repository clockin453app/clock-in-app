def login_impl(core):
    request = core["request"]
    session = core["session"]
    get_csrf = core["get_csrf"]
    require_csrf = core["require_csrf"]
    _client_ip = core["_client_ip"]
    _login_rate_limit_check = core["_login_rate_limit_check"]
    log_audit = core["log_audit"]
    math = core["math"]
    DB_MIGRATION_MODE = core["DB_MIGRATION_MODE"]
    spreadsheet = core["spreadsheet"]
    employees_sheet = core["employees_sheet"]
    _cache_invalidate_prefix = core["_cache_invalidate_prefix"]
    _find_employee_record = core["_find_employee_record"]
    is_password_valid = core["is_password_valid"]
    _login_rate_limit_hit = core["_login_rate_limit_hit"]
    _login_rate_limit_clear = core["_login_rate_limit_clear"]
    migrate_password_if_plain = core["migrate_password_if_plain"]
    _issue_active_session_token = core["_issue_active_session_token"]
    safe_float = core["safe_float"]
    parse_bool = core["parse_bool"]
    redirect = core["redirect"]
    url_for = core["url_for"]
    get_company_settings = core["get_company_settings"]
    escape = core["escape"]
    render_template_string = core["render_template_string"]
    STYLE = core["STYLE"]
    VIEWPORT = core["VIEWPORT"]
    PWA_TAGS = core["PWA_TAGS"]
    _find_global_master_admin_record = core["_find_global_master_admin_record"]
    _issue_global_master_admin_session_token = core["_issue_global_master_admin_session_token"]

    msg = session.pop("_login_notice", "") if request.method == "GET" else ""
    csrf = get_csrf()

    if request.method == "POST":
        require_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        workplace_id = (request.form.get("workplace_id", "") or "").strip()
        ip = _client_ip()

        login_usernames = [username]
        if username.lower() == "masteradmin":
            login_usernames = ["masteradmin", "master_admin"]
        elif username.lower() == "master_admin":
            login_usernames = ["master_admin", "masteradmin"]

        allowed, retry_after = _login_rate_limit_check(ip)
        if not allowed:
            log_audit("LOGIN_LOCKED", actor=ip, username=username, date_str="",
                      details=f"RetryAfter={retry_after}s")
            mins = max(1, int(math.ceil(retry_after / 60)))
            msg = f"Too many login attempts. Try again in {mins} minute(s)."
        else:
            matched_global_username = username
            global_admin = None

            for candidate_username in login_usernames:
                global_admin = _find_global_master_admin_record(candidate_username)
                if global_admin:
                    matched_global_username = str(global_admin.get("username") or candidate_username).strip()
                    break

            if global_admin:
                if is_password_valid(global_admin.get("password_hash", ""), password):
                    active_raw = str(global_admin.get("active", "TRUE") or "TRUE").strip().lower()
                    is_active = active_raw not in ("false", "0", "no", "n", "off")

                    if not is_active:
                        _login_rate_limit_hit(ip)
                        log_audit("LOGIN_INACTIVE", actor=ip, username=matched_global_username, date_str="",
                                  details="Inactive global master admin login attempt")
                        msg = "Invalid login"
                    else:
                        _login_rate_limit_clear(ip)
                        active_session_token = _issue_global_master_admin_session_token(matched_global_username)
                        if not active_session_token:
                            log_audit("LOGIN_SESSION_FAIL", actor=ip, username=matched_global_username, date_str="",
                                      details="Could not start global master admin session")
                            msg = "Could not start secure session. Please try again."
                        else:
                            selected_workplace = workplace_id or (session.get("workplace_id") or "").strip() or "default"
                            session.clear()
                            session["csrf"] = csrf
                            session["username"] = matched_global_username
                            session["workplace_id"] = selected_workplace
                            session["role"] = "master_admin"
                            session["auth_scope"] = "global_master_admin"
                            session["rate"] = 0.0
                            session["early_access"] = True
                            session["active_session_token"] = active_session_token
                            log_audit("LOGIN_OK", actor=ip, username=matched_global_username, date_str="",
                                      details=f"global master admin workplace={selected_workplace}")
                            return redirect(url_for("home"))
                else:
                    _login_rate_limit_hit(ip)
                    log_audit("LOGIN_FAIL", actor=ip, username=username, date_str="",
                              details="Invalid global master admin username or password")
                    msg = "Invalid login"

            else:
                if not workplace_id:
                    msg = "Workplace ID is required."
                else:
                    if not DB_MIGRATION_MODE:
                        try:
                            sid = getattr(spreadsheet, "id", None)
                            wid = getattr(employees_sheet, "id", None)
                            if sid and wid:
                                _cache_invalidate_prefix((sid, wid))
                        except Exception:
                            pass

                    ok_user = None
                    matched_username = username
                    for candidate_username in login_usernames:
                        ok_user = _find_employee_record(candidate_username, workplace_id)
                        if ok_user:
                            matched_username = candidate_username
                            break

                    if ok_user and is_password_valid(ok_user.get("Password", ""), password):
                        active_raw = str(ok_user.get("Active", "") or "").strip().lower()
                        is_active = active_raw not in ("false", "0", "no", "n", "off")

                        if not is_active:
                            _login_rate_limit_hit(ip)
                            log_audit("LOGIN_INACTIVE", actor=ip, username=username, date_str="",
                                      details="Inactive account login attempt")
                            msg = "Invalid login"
                        else:
                            _login_rate_limit_clear(ip)

                            migrate_password_if_plain(
                                matched_username,
                                ok_user.get("Password", ""),
                                password,
                                workplace_id=workplace_id,
                            )
                            active_session_token = _issue_active_session_token(matched_username, workplace_id)
                            if not active_session_token:
                                log_audit("LOGIN_SESSION_FAIL", actor=ip, username=matched_username, date_str="",
                                          details=f"Could not start active session workplace={workplace_id}")
                                msg = "Could not start secure session. Please try again."
                            else:
                                session.clear()
                                session["csrf"] = csrf
                                session["username"] = matched_username
                                session["workplace_id"] = workplace_id
                                session["role"] = (ok_user.get("Role", "employee") or "employee").strip().lower()
                                session["rate"] = safe_float(ok_user.get("Rate", 0), 0.0)
                                session["early_access"] = parse_bool(ok_user.get("EarlyAccess", False))
                                session.pop("auth_scope", None)
                                session["active_session_token"] = active_session_token
                                return redirect(url_for("home"))
                    else:
                        _login_rate_limit_hit(ip)
                        log_audit("LOGIN_FAIL", actor=ip, username=username, date_str="",
                                  details="Invalid username or password")
                        msg = "Invalid login"

    try:
        company_name = (get_company_settings().get("Company_Name") or "").strip() or "Main"
    except Exception:
        company_name = "Main"

    entered_username = (request.form.get("username", "") or "").strip() if request.method == "POST" else ""
    entered_workplace_id = (request.form.get("workplace_id", "") or "").strip() if request.method == "POST" else ""

    login_page_style = """
    <style>
      html,
      body{
        width:100%;
        min-height:100%;
        margin:0;
        overflow-x:hidden;
        background:#f6f9fd;
        -webkit-text-size-adjust:100%;
        text-size-adjust:100%;
      }

      body{
        font-family:Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
        background:
          radial-gradient(900px 520px at 86% 0%, rgba(37,99,235,.08), transparent 55%),
          linear-gradient(180deg, #fbfdff 0%, #f6f9fd 100%);
      }

      .loginOnlyPage{
        width:100%;
        min-height:100vh;
        padding:40px 22px;
        display:flex;
        align-items:center;
        justify-content:center;
        box-sizing:border-box;
      }

      .loginOnlyCard{
        width:100%;
        max-width:520px;
        background:#ffffff;
        border:1px solid #dfe8f4;
        border-radius:24px;
        box-shadow:0 28px 70px rgba(15,23,42,.12);
        overflow:hidden;
        box-sizing:border-box;
      }

      .loginOnlyHero{
        padding:32px 38px 24px;
        border-bottom:1px solid #e6edf6;
        background:
          radial-gradient(circle at top right, rgba(37,99,235,.07), transparent 34%),
          linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
      }

      .loginOnlyLogo{
        display:inline-flex;
        align-items:center;
        gap:8px;
        padding:18px 24px;
        margin:0 0 14px 0;
        background:#1f2d63;
        text-decoration:none;
        white-space:nowrap;
      }

      .loginOnlyLogoClock{
        width:38px;
        height:38px;
        flex:0 0 38px;
        display:block;
      }

      .loginOnlyLogoWord{
        display:inline-flex;
        align-items:center;
        font-size:34px;
        line-height:1;
        letter-spacing:-0.075em;
        font-weight:900;
        white-space:nowrap;
      }

      .loginOnlyLogoTim{
        color:#ffffff;
      }

      .loginOnlyLogoIQ{
        color:#7fc7ee;
      }

      .loginOnlyLead{
        margin:0;
        color:#56647d;
        font-size:14px;
        line-height:1.5;
        font-weight:600;
      }

      .loginOnlyBody{
        padding:32px 38px 38px;
      }

      .loginOnlyTitle{
        margin:0 0 22px 0;
        color:#101a3d;
        font-size:34px;
        line-height:1.08;
        letter-spacing:-.035em;
        font-weight:850;
      }

      .loginOnlyForm{
        display:grid;
        gap:15px;
      }

      .loginOnlyLabel{
        display:block;
        margin:0 0 8px 0;
        color:#5f6f89;
        font-size:13px;
        font-weight:750;
      }

      .loginOnlyInput{
        width:100%;
        height:56px;
        min-height:56px;
        padding:0 17px;
        border-radius:12px;
        border:1px solid #d7e1ee;
        background:#ffffff;
        color:#101a3d;
        box-shadow:0 6px 18px rgba(15,23,42,.035);
        font-size:15px;
        font-weight:650;
        line-height:20px;
        font-family:Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
        box-sizing:border-box;
        appearance:none;
      }

      .loginOnlyInput::placeholder{
        color:#94a3b8;
      }

      .loginOnlyInput:focus{
        border-color:rgba(37,99,235,.45);
        box-shadow:0 0 0 4px rgba(37,99,235,.08), 0 8px 24px rgba(15,23,42,.08);
        outline:none;
      }

      .loginOnlyHint{
        margin-top:6px;
        color:#7b86a0;
        font-size:12px;
        line-height:1.4;
        font-weight:600;
      }

      .loginOnlyPasswordWrap{
        position:relative;
      }

      .loginOnlyPasswordInput{
        padding-right:56px;
      }

      .loginOnlyEyeBtn{
        position:absolute;
        right:11px;
        top:50%;
        transform:translateY(-50%);
        width:36px;
        height:36px;
        border:0;
        border-radius:999px;
        background:rgba(31,45,99,.06);
        color:#1f2d63;
        display:flex;
        align-items:center;
        justify-content:center;
        cursor:pointer;
        padding:0;
      }

      .loginOnlyEyeBtn:hover{
        background:rgba(31,45,99,.11);
      }

      .loginOnlyEyeBtn .eyeIcon{
        width:20px;
        height:20px;
        fill:none;
        stroke:currentColor;
        stroke-width:2;
        stroke-linecap:round;
        stroke-linejoin:round;
      }

      .loginOnlyEyeBtn .eyeOpen{
        display:none;
      }

      .loginOnlyEyeBtn .eyeClosed{
        display:block;
      }

      .loginOnlyEyeBtn.isVisible .eyeOpen{
        display:block;
      }

      .loginOnlyEyeBtn.isVisible .eyeClosed{
        display:none;
      }

      .loginOnlyButton{
        margin-top:8px;
        width:100%;
        min-height:56px;
        border:0;
        border-radius:12px;
        background:linear-gradient(135deg, #0b63ff, #0057e7);
        color:#ffffff;
        font-size:15px;
        font-weight:850;
        letter-spacing:.01em;
        box-shadow:0 14px 30px rgba(37,99,235,.20);
        cursor:pointer;
      }

      .loginOnlyButton:hover{
        filter:brightness(1.02);
      }

      .loginOnlyMessage{
        margin-top:16px;
      }

      .loginOnlyFooter{
        margin-top:18px;
        color:#7b86a0;
        font-size:13px;
        line-height:1.6;
        font-weight:600;
      }

      @media (max-width:620px){
        .loginOnlyPage{
          padding:18px 14px;
        }

        .loginOnlyCard{
          max-width:100%;
          border-radius:20px;
        }

        .loginOnlyHero{
          padding:24px 22px 18px;
        }

        .loginOnlyBody{
          padding:24px 22px 28px;
        }

        .loginOnlyLogo{
          padding:16px 20px;
        }

        .loginOnlyLogoClock{
          width:34px;
          height:34px;
          flex-basis:34px;
        }

        .loginOnlyLogoWord{
          font-size:30px;
        }

        .loginOnlyTitle{
          font-size:30px;
        }

        .loginOnlyInput,
        .loginOnlyButton{
          height:54px;
          min-height:54px;
        }
      }
            /* ===== LOGIN FINAL SIZE + PLACEHOLDER CLEANUP ===== */

      .loginOnlyPage{
        padding:34px 24px !important;
        align-items:center !important;
        justify-content:center !important;
      }

      .loginOnlyCard{
        max-width:680px !important;
        border-radius:24px !important;
      }

      .loginOnlyHero{
        padding:40px 48px 30px !important;
      }

      .loginOnlyLogo{
        padding:20px 28px !important;
        margin-bottom:16px !important;
      }

      .loginOnlyLogoClock{
        width:42px !important;
        height:42px !important;
        flex-basis:42px !important;
      }

      .loginOnlyLogoWord{
        font-size:38px !important;
      }

      .loginOnlyLead{
        font-size:15px !important;
        line-height:1.55 !important;
      }

      .loginOnlyBody{
        padding:38px 48px 46px !important;
      }

      .loginOnlyTitle{
        font-size:40px !important;
        line-height:1.04 !important;
        margin-bottom:28px !important;
      }

      .loginOnlyForm{
        gap:18px !important;
      }

      .loginOnlyLabel{
        font-size:13px !important;
        font-weight:750 !important;
        margin-bottom:8px !important;
      }

      .loginOnlyInput{
        height:62px !important;
        min-height:62px !important;
        padding:0 20px !important;
        font-size:15px !important;
        font-weight:500 !important;
        color:#111b3f !important;
        border-radius:14px !important;
        background:#ffffff !important;
      }

      .loginOnlyInput::placeholder{
        color:rgba(100,116,139,.62) !important;
        font-weight:500 !important;
        opacity:1 !important;
      }

      .loginOnlyPasswordInput{
        padding-right:58px !important;
      }

      .loginOnlyEyeBtn{
        right:12px !important;
        width:38px !important;
        height:38px !important;
      }

      .loginOnlyButton{
        min-height:62px !important;
        margin-top:10px !important;
        border-radius:14px !important;
        background:linear-gradient(135deg, #0b63ff, #0057e7) !important;
        font-size:15px !important;
        font-weight:850 !important;
      }

      .loginOnlyFooter{
        margin-top:20px !important;
        font-size:13px !important;
        line-height:1.65 !important;
        max-width:520px !important;
      }

      @media (max-width:620px){
        .loginOnlyPage{
          padding:18px 14px !important;
        }

        .loginOnlyCard{
          max-width:100% !important;
        }

        .loginOnlyHero{
          padding:24px 22px 18px !important;
        }

        .loginOnlyBody{
          padding:24px 22px 30px !important;
        }

        .loginOnlyTitle{
          font-size:30px !important;
        }

        .loginOnlyInput,
        .loginOnlyButton{
          height:54px !important;
          min-height:54px !important;
        }
      }
    </style>
    """
    login_viewport = '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">'

    html = f"""
    <div class="loginOnlyPage">
      <div class="loginOnlyCard">
        <div class="loginOnlyHero">
          <div class="loginOnlyLogo" aria-label="TimIQ">
            <svg class="loginOnlyLogoClock" viewBox="0 0 64 64" fill="none" aria-hidden="true">
              <path d="M7 25H26" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
              <path d="M10 34H24" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
              <path d="M16 43H22" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
              <rect x="31" y="8" width="11" height="6" rx="2" fill="#7FC7EE"/>
              <rect x="47.5" y="14" width="6" height="6" rx="1.5" transform="rotate(45 47.5 14)" fill="#7FC7EE"/>
              <circle cx="36" cy="32" r="18" stroke="#7FC7EE" stroke-width="5.5"/>
              <path d="M36 32V18A14 14 0 0 1 50 32H36Z" fill="#4B83C6"/>
            </svg>

            <span class="loginOnlyLogoWord">
              <span class="loginOnlyLogoTim">Tim</span><span class="loginOnlyLogoIQ">IQ</span>
            </span>
          </div>

          <p class="loginOnlyLead">Clock-in, attendance and payroll in one secure workspace.</p>
        </div>

        <div class="loginOnlyBody">
          <div class="loginOnlyTitle">Sign in to continue</div>

          <form method="POST" class="loginOnlyForm" onsubmit="var f=this,ae=document.activeElement;if(ae&&ae.blur)ae.blur();window.scrollTo(0,0);setTimeout(f.submit.bind(f),180);return false;">
            <input type="hidden" name="csrf" value="{escape(csrf)}">

            <div>
              <label class="loginOnlyLabel" for="login-username">Username</label>
              <input
                id="login-username"
                class="loginOnlyInput"
                name="username"
                value="{escape(entered_username)}"
                autocomplete="username"
                autocapitalize="none"
                spellcheck="false"
                placeholder="Enter your username"
                required>
            </div>

            <div>
              <label class="loginOnlyLabel" for="login-workplace">Workplace ID</label>
              <input
                id="login-workplace"
                class="loginOnlyInput"
                name="workplace_id"
                value="{escape(entered_workplace_id)}"
                autocomplete="off"
                autocapitalize="none"
                autocorrect="off"
                spellcheck="false"
                inputmode="text"
                enterkeyhint="next"
                placeholder="e.g. north01">
              <div class="loginOnlyHint">Required for workplace users.</div>
            </div>

            <div>
              <label class="loginOnlyLabel" for="login-password">Password</label>

              <div class="loginOnlyPasswordWrap">
                <input
                  id="login-password"
                  class="loginOnlyInput loginOnlyPasswordInput"
                  type="password"
                  name="password"
                  autocomplete="current-password"
                  placeholder="Enter your password"
                  required>

                <button
                  class="loginOnlyEyeBtn"
                  type="button"
                  data-password-toggle="login-password"
                  aria-label="Show password"
                  aria-pressed="false">
                  <svg class="eyeIcon eyeOpen" viewBox="0 0 24 24">
                    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"></path>
                    <circle cx="12" cy="12" r="3"></circle>
                  </svg>

                  <svg class="eyeIcon eyeClosed" viewBox="0 0 24 24">
                    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"></path>
                    <circle cx="12" cy="12" r="3"></circle>
                    <path d="M4 20L20 4"></path>
                  </svg>
                </button>
              </div>
            </div>

            <button class="loginOnlyButton" type="submit">Sign in</button>
          </form>

          {("<div class='message error loginOnlyMessage'>" + escape(msg) + "</div>") if msg else ""}

          <div class="loginOnlyFooter">
            Use the same credentials provided by your administrator. After sign-in you can access clock-in, timesheets and payroll tools based on your role.
          </div>
        </div>
      </div>

      <script>
        (function(){{
          document.querySelectorAll("[data-password-toggle]").forEach(function(btn){{
            btn.addEventListener("click", function(){{
              var inputId = btn.getAttribute("data-password-toggle");
              var input = document.getElementById(inputId);
              if (!input) return;

              var isHidden = input.type === "password";
              input.type = isHidden ? "text" : "password";

              btn.classList.toggle("isVisible", isHidden);
              btn.setAttribute("aria-pressed", isHidden ? "true" : "false");
              btn.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
            }});
          }});
        }})();
      </script>
    </div>
    """
    return render_template_string(f"{login_viewport}{PWA_TAGS}{login_page_style}{html}")