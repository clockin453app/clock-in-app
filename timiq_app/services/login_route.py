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
        width:100% !important;
        max-width:100% !important;
        overflow-x:hidden !important;
        -webkit-text-size-adjust:100% !important;
        text-size-adjust:100% !important;
      }

      body{
        touch-action:manipulation;
      }

      .loginShellPro,
      .loginShellPro .main,
      .loginCardPro{
        width:100% !important;
        max-width:760px !important;
        box-sizing:border-box !important;
      }

      @media (max-width:560px){
        .loginShellPro{
          max-width:100% !important;
          margin:0 !important;
          padding:0 !important;
        }

        .loginShellPro .main{
          width:100% !important;
          max-width:100% !important;
          padding:0 !important;
          margin:0 !important;
        }

        .loginCardPro{
          width:100% !important;
          max-width:100% !important;
          margin:0 !important;
          border-left:0 !important;
          border-right:0 !important;
        }
      }
      .loginShellPro{
        max-width: 760px;
        margin: 0 auto;
        padding: 22px 0 30px;
      }

      .loginCardPro{
        overflow: hidden;
        border-radius: 0 !important;
        border: 1px solid rgba(68,130,195,.10) !important;
        background:
          radial-gradient(circle at top right, rgba(68,130,195,.05), transparent 32%),
          radial-gradient(circle at top left, rgba(37,99,235,.05), transparent 28%),
          linear-gradient(180deg, #ffffff 0%, #f8fbfe 100%) !important;
        box-shadow: 0 24px 60px rgba(15,23,42,.10) !important;
      }

      .loginBrandWrap{
        display:flex;
        flex-direction:column;
        align-items:flex-start;
      }

      .loginLogoNew{
  display:inline-flex;
  align-items:center;
  gap:5px;
  background:#1f2d63;
  padding:24px 34px;
  text-decoration:none;
  margin:0 0 10px 0;
}

.loginLogoClock{
  width:46px;
  height:46px;
  flex:0 0 46px;
  display:block;
}

.loginLogoWord{
  display:inline-flex;
  align-items:center;
  font-family:Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  font-size:34px;
  line-height:1;
  letter-spacing:-0.075em;
  font-weight:900;
}

.loginLogoTim{
  color:#ffffff;
}

.loginLogoIQ{
  color:#7fc7ee;
}

      .loginHeroPro{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 18px;
        padding: 26px 28px 20px 28px;
        border-bottom: 1px solid rgba(68,130,195,.08);
        background: linear-gradient(180deg, rgba(255,255,255,.82), rgba(248,247,255,.96));
      }

      .loginEyebrow{
        display: inline-flex;
        align-items: center;
        padding: 8px 14px;
        border-radius: 0 !important;
        border: 1px solid rgba(68,130,195,.12);
        background: rgba(68,130,195,.06);
        color: #4482c3;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: .05em;
        text-transform: uppercase;
      }

      .loginHeroPro h1{
        margin: 16px 0 10px 0;
        font-size: clamp(52px, 7vw, 74px);
        line-height: .95;
        letter-spacing: -.04em;
        color: #1f2547;
        font-weight: 900;
      }

      .loginLead{
        margin: 0;
        color: #6f6c85 !important;
        font-size: 18px;
        line-height: 1.65;
        max-width: 560px;
      }

      .loginHeroBadge{
        flex: 0 0 auto;
        align-self: flex-start;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 48px;
        padding: 0 18px;
        border-radius: 0 !important;
        border: 1px solid rgba(37,99,235,.10);
        background: linear-gradient(180deg, #f3f7ff, #edf2ff);
        color: #4f46e5;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: .05em;
        text-transform: uppercase;
        box-shadow: 0 8px 20px rgba(15,23,42,.06);
      }

      .loginFormWrap{
        padding: 26px 28px 28px 28px;
      }

      .loginSectionTitle{
        margin: 0 0 14px 0;
        color: #1f2547;
        font-size: 28px;
        font-weight: 800;
        letter-spacing: -.02em;
      }

      .loginFormGrid{
        display: grid;
        gap: 14px;
      }

      .loginFieldLabel{
        display: block;
        margin: 0 0 8px 0;
        color: #6f6c85;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: .02em;
      }

                  .loginInput{
        margin-top: 0 !important;
        height: 56px !important;
        min-height: 56px !important;
        padding: 0 16px !important;
        border-radius: 0 !important;
        border: 1px solid rgba(68,130,195,.12) !important;
        background: #ffffff !important;
        color: #1f2547 !important;
        box-shadow: 0 6px 18px rgba(15,23,42,.04);

        font-size: 16px !important;
        line-height: 20px !important;
        font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif !important;
        -webkit-appearance: none !important;
        appearance: none !important;
        transform: none !important;
        zoom: 1 !important;
        box-sizing: border-box !important;
      }

      .loginInput::placeholder{
        color: #9a96ad;
      }

      .loginInput:focus{
        border-color: rgba(79,70,229,.35) !important;
        box-shadow: 0 0 0 4px rgba(68,130,195,.08), 0 8px 24px rgba(15,23,42,.08) !important;
        outline: none;
      }

      .loginPrimaryBtn{
        margin-top: 4px;
        width: 100%;
        min-height: 58px;
        border: 0;
        border-radius: 0 !important;
        background: linear-gradient(90deg, #2563eb, #5b8cff);
        color: #ffffff;
        font-size: 17px;
        font-weight: 800;
        letter-spacing: .01em;
        box-shadow: 0 14px 30px rgba(37,99,235,.20);
        transition: transform .18s ease, box-shadow .18s ease, filter .18s ease;
      }

      .loginPrimaryBtn:hover{
        transform: translateY(-1px);
        box-shadow: 0 18px 34px rgba(37,99,235,.24);
        filter: brightness(1.02);
      }

      .loginMessageWrap{
        margin-top: 16px;
      }

      .loginMetaGrid{
        margin-top: 20px;
        display: grid;
        grid-template-columns: repeat(3, minmax(0,1fr));
        gap: 12px;
      }

      .loginMetaCard{
        padding: 14px 16px;
        border-radius: 0 !important;
        border: 1px solid rgba(68,130,195,.10);
        background: linear-gradient(180deg, #ffffff, #f8f7ff);
        box-shadow: 0 10px 24px rgba(15,23,42,.06);
      }

      .loginMetaLabel{
        display: block;
        margin: 0 0 6px 0;
        color: #8a84a3;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .08em;
        text-transform: uppercase;
      }

      .loginMetaValue{
        display: block;
        color: #1f2547;
        font-size: 15px;
        font-weight: 800;
        line-height: 1.45;
      }

      .loginFooterNote{
        margin-top: 16px;
        color: #8a84a3;
        font-size: 14px;
        line-height: 1.65;
      }

      @media (max-width: 760px){
        .loginShellPro{
          max-width: 100%;
          padding-top: 10px;
        }

        .loginLogoNew{
  padding:20px 28px;
}

.loginLogoClock{
  width:38px;
  height:38px;
  flex-basis:38px;
}

.loginLogoWord{
  font-size:28px;
}

        .loginHeroPro{
          padding: 22px 20px 18px 20px;
          flex-direction: column;
          align-items: flex-start;
        }

        .loginHeroPro h1{
          font-size: 48px;
        }

        .loginFormWrap{
          padding: 20px;
        }

        .loginMetaGrid{
          grid-template-columns: 1fr;
        }
      }

            @media (max-width: 560px){
        .loginHeroPro h1{
          font-size: 40px;
        }

        .loginBrandLogo{
          width:150px;
        }

        .loginLead{
          font-size: 15px;
          line-height: 1.6;
        }

        .loginSectionTitle{
          font-size: 22px;
        }

        .loginInput{
          height: 54px !important;
          font-size: 16px !important;
        }

        .loginPrimaryBtn{
          min-height: 54px;
          font-size: 16px;
        }
      }
    </style>
    """
    login_viewport = '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">'

    html = f"""
    <div class="shell loginShellPro" style="grid-template-columns:1fr;">
      <div class="main">

        <div class="card loginCardPro">
          <div class="loginHeroPro">
            <div class="loginBrandWrap">
              <div class="loginLogoNew" aria-label="TimIQ">
  <svg class="loginLogoClock" viewBox="0 0 64 64" fill="none" aria-hidden="true">
    <path d="M7 25H26" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
    <path d="M10 34H24" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
    <path d="M16 43H22" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
    <rect x="31" y="8" width="11" height="6" rx="2" fill="#7FC7EE"/>
    <rect x="47.5" y="14" width="6" height="6" rx="1.5" transform="rotate(45 47.5 14)" fill="#7FC7EE"/>
    <circle cx="36" cy="32" r="18" stroke="#7FC7EE" stroke-width="5.5"/>
    <path d="M36 32V18A14 14 0 0 1 50 32H36Z" fill="#4B83C6"/>
  </svg>

  <span class="loginLogoWord">
    <span class="loginLogoTim">Tim</span><span class="loginLogoIQ">IQ</span>
  </span>
</div>
              <p class="sub loginLead">Clock-in, attendance and payroll in one secure workspace.</p>
            </div>
          </div>

          <div class="loginFormWrap">
            <div class="loginSectionTitle">Sign in to continue</div>
            <form method="POST" class="loginFormGrid" onsubmit="var f=this,ae=document.activeElement;if(ae&&ae.blur)ae.blur();window.scrollTo(0,0);setTimeout(f.submit.bind(f),180);return false;">
              <input type="hidden" name="csrf" value="{escape(csrf)}">

              <div>
                <label class="loginFieldLabel" for="login-username">Username</label>
                <input id="login-username" class="input loginInput" name="username" value="{escape(entered_username)}" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="Enter your username" required>
              </div>

                                          <div>
                <label class="loginFieldLabel" for="login-workplace">Workplace ID</label>
                <input
                  id="login-workplace"
                  class="input loginInput"
                  name="workplace_id"
                  value="{escape(entered_workplace_id)}"
                  autocomplete="off"
                  autocapitalize="none"
                  autocorrect="off"
                  spellcheck="false"
                  inputmode="text"
                  enterkeyhint="next"
                  placeholder="e.g. north01">
                <div class="sub" style="margin-top:6px; font-size:12px;">
                  Required for workplace users. Global master admin can leave this blank.
                </div>
              </div>

              <div>
                <label class="loginFieldLabel" for="login-password">Password</label>
                <input id="login-password" class="input loginInput" type="password" name="password" autocomplete="current-password" placeholder="Enter your password" required>
              </div>

              <button class="loginPrimaryBtn" type="submit">Sign in</button>
            </form>

            {("<div class='message error loginMessageWrap'>" + escape(msg) + "</div>") if msg else ""}

            <div class="loginFooterNote">Use the same credentials provided by your administrator. After sign-in you can access clock-in, timesheets and payroll tools based on your role.</div>
          </div>
        </div>
      </div>
    </div>
    """
    return render_template_string(f"{login_viewport}{PWA_TAGS}{STYLE}{login_page_style}{html}")