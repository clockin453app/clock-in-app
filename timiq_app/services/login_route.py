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
      :root{
        --bg:#f6f9fd;
        --panel:#ffffff;
        --line:#dbe5f2;
        --line-strong:#d2ddec;
        --text:#0a1833;
        --muted:#7183a6;
        --blue:#0b63ff;
        --blue-2:#1f8cff;
        --navy:#0c1f58;
        --hero:#0a2e88;
        --hero-dark:#081a4a;
        --cyan:#72c7f6;
      }

      *{box-sizing:border-box;}

      html,body{
        margin:0;
        padding:0;
        width:100%;
        min-height:100%;
      }

      body{
        font-family:Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        color:var(--text);
        background:
          radial-gradient(1200px 600px at 85% 8%, rgba(126,211,247,.18), transparent 60%),
          linear-gradient(180deg, #f9fbfe 0%, #f4f8fc 100%);
        overflow-x:hidden;
        -webkit-font-smoothing:antialiased;
        -moz-osx-font-smoothing:grayscale;
      }

      .login-page{
        width:100%;
        min-height:100vh;
        display:grid;
        grid-template-columns:48% 52%;
      }

      /* LEFT DESKTOP HERO */
      .login-hero{
  position:relative;
  min-height:100vh;
  overflow:hidden;
  color:#fff;
  padding:54px 56px 46px;
  background:
    radial-gradient(680px 360px at 70% 62%, rgba(37,122,255,.34), transparent 58%),
    linear-gradient(180deg, rgba(7,24,74,.90), rgba(10,46,136,.92)),
    linear-gradient(135deg, #081a4a 0%, #0a2e88 100%);
}

      .login-hero::before{
        content:"";
        position:absolute;
        inset:0;
        background:
          linear-gradient(90deg, rgba(255,255,255,.04) 1px, transparent 1px),
          linear-gradient(180deg, rgba(255,255,255,.04) 1px, transparent 1px);
        background-size:36px 36px;
        opacity:.18;
        pointer-events:none;
      }

      .hero-inner{
        position:relative;
        z-index:2;
        display:flex;
        flex-direction:column;
        height:100%;
      }

      .hero-logo{
        display:flex;
        align-items:center;
        gap:12px;
      }

      .hero-logo svg{
        width:42px;
        height:42px;
        flex:0 0 42px;
      }

      .hero-logo-text{
        font-size:34px;
        font-weight:900;
        letter-spacing:-.06em;
        line-height:1;
      }

      .hero-logo-text .tim{color:#fff;}
      .hero-logo-text .iq{color:#7fc7ee;}

      .hero-copy{
        max-width:470px;
        margin-top:72px;
      }

      .hero-copy h1{
  margin:0;
  font-size:68px;
  line-height:.96;
  font-weight:900;
  letter-spacing:-.06em;
  color:#ffffff !important;
  text-shadow:none;
}
.login-hero .hero-copy,
.login-hero .hero-copy h1,
.login-hero .hero-copy h1 *{
  color:#ffffff !important;
}

.login-hero .hero-copy h1 .accent{
  color:#72c7f6 !important;
}

.hero-copy h1 .accent{
  color:#72c7f6 !important;
}

      .hero-copy .hero-rule{
        width:54px;
        height:3px;
        border-radius:999px;
        background:#72c7f6;
        margin:34px 0 28px;
        opacity:.9;
      }

      .hero-copy p{
  margin:0;
  max-width:420px;
  color:rgba(255,255,255,.92);
  font-size:18px;
  line-height:1.65;
  font-weight:500;
}

      .hero-features{
        margin-top:52px;
        display:grid;
        gap:26px;
        max-width:390px;
      }

      .hero-feature{
        display:grid;
        grid-template-columns:52px 1fr;
        gap:16px;
        align-items:start;
      }

      .hero-feature-icon{
        width:52px;
        height:52px;
        border-radius:999px;
        border:1px solid rgba(255,255,255,.14);
        background:rgba(255,255,255,.10);
        display:flex;
        align-items:center;
        justify-content:center;
        color:#ffffff;
        backdrop-filter:blur(2px);
      }

      .hero-feature-icon svg{
        width:22px;
        height:22px;
        stroke:currentColor;
        fill:none;
        stroke-width:2;
        stroke-linecap:round;
        stroke-linejoin:round;
      }

      .hero-feature strong{
        display:block;
        font-size:16px;
        line-height:1.25;
        font-weight:800;
        color:#ffffff;
        margin-bottom:4px;
      }

      .hero-feature span{
        display:block;
        color:rgba(255,255,255,.88);
        font-size:15px;
        line-height:1.45;
        font-weight:500;
      }

      .hero-scene{
  position:absolute;
  inset:auto 0 0 0;
  height:50%;
  z-index:1;
  pointer-events:none;
  opacity:1;
}

.hero-scene svg{
  width:100%;
  height:100%;
  display:block;
}

      .hero-dots{
        position:absolute;
        right:50px;
        top:92px;
        width:96px;
        height:64px;
        z-index:1;
        opacity:.22;
      }

      .hero-dots::before{
        content:"";
        position:absolute;
        inset:0;
        background-image:radial-gradient(rgba(255,255,255,.9) 1.2px, transparent 1.2px);
        background-size:16px 16px;
      }

      /* RIGHT DESKTOP PANEL */
      .login-main{
        min-height:100vh;
        padding:54px 54px 32px;
        display:flex;
        flex-direction:column;
        justify-content:space-between;
        background:
          radial-gradient(760px 340px at 85% 0%, rgba(126,211,247,.20), transparent 55%),
          linear-gradient(180deg, #fdfefe 0%, #f9fbfe 100%);
      }

      .login-main-center{
        flex:1;
        display:flex;
        align-items:center;
        justify-content:center;
      }

      .login-card{
        width:min(100%, 700px);
        background:#fff;
        border:1px solid #e3ebf5;
        border-radius:20px;
        padding:58px 62px 48px;
        box-shadow:0 20px 60px rgba(12,31,88,.08);
      }

      .login-card h1{
        margin:0;
        color:var(--navy);
        font-size:58px;
        line-height:.98;
        font-weight:900;
        letter-spacing:-.055em;
      }

      .login-card .subtitle{
        margin:14px 0 34px;
        color:#7b8aa8;
        font-size:18px;
        line-height:1.5;
        font-weight:500;
      }

      .login-form{
        display:grid;
        gap:20px;
      }

      .field label{
        display:block;
        margin:0 0 10px;
        color:#15264b;
        font-size:16px;
        font-weight:800;
        line-height:1.2;
      }

      .input-wrap{
        position:relative;
      }

      .input-icon{
        position:absolute;
        top:50%;
        left:18px;
        transform:translateY(-50%);
        color:#a8b5ca;
        width:22px;
        height:22px;
        pointer-events:none;
        display:flex;
        align-items:center;
        justify-content:center;
      }

      .input-icon svg{
        width:22px;
        height:22px;
        stroke:currentColor;
        fill:none;
        stroke-width:2;
        stroke-linecap:round;
        stroke-linejoin:round;
      }

      .login-input{
        width:100%;
        height:66px;
        border:1px solid #d8e2ef;
        border-radius:14px;
        background:#fff;
        color:var(--text);
        padding:0 20px 0 56px;
        font-size:18px;
        font-weight:600;
        outline:none;
        transition:border-color .18s ease, box-shadow .18s ease;
      }

      .login-input::placeholder{
        color:#9aa7bd;
        font-weight:500;
      }

      .login-input:focus{
        border-color:#9ec2ff;
        box-shadow:0 0 0 4px rgba(11,99,255,.08);
      }

      .input-note{
        margin-top:10px;
        color:#7b8aa8;
        font-size:14px;
        line-height:1.4;
        font-weight:600;
      }

      .password-input{
        padding-right:64px;
      }

      .toggle-pass{
        position:absolute;
        top:50%;
        right:12px;
        transform:translateY(-50%);
        width:44px;
        height:44px;
        border-radius:12px;
        border:1px solid #d8e2ef;
        background:#fff;
        color:#0b63ff;
        cursor:pointer;
        display:flex;
        align-items:center;
        justify-content:center;
      }

      .toggle-pass svg{
        width:21px;
        height:21px;
        stroke:currentColor;
        fill:none;
        stroke-width:2;
        stroke-linecap:round;
        stroke-linejoin:round;
      }

      .toggle-pass .eye-open{display:none;}
      .toggle-pass.is-visible .eye-open{display:block;}
      .toggle-pass.is-visible .eye-closed{display:none;}

      .login-row{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:18px;
        margin-top:2px;
      }

      .remember{
        display:flex;
        align-items:center;
        gap:12px;
        font-size:16px;
        font-weight:600;
        color:#1b2b50;
        user-select:none;
      }

      .remember input{
        width:19px;
        height:19px;
        accent-color:#0b63ff;
      }

      .forgot-link{
        color:#0b63ff;
        text-decoration:none;
        font-size:16px;
        font-weight:700;
      }

      .login-btn{
        width:100%;
        height:66px;
        border:0;
        border-radius:14px;
        margin-top:8px;
        background:linear-gradient(90deg, #1478ff 0%, #0b63ff 100%);
        color:#fff;
        font-size:24px;
        font-weight:800;
        letter-spacing:-.02em;
        cursor:pointer;
        display:flex;
        align-items:center;
        justify-content:center;
        gap:14px;
        box-shadow:0 16px 34px rgba(11,99,255,.20);
      }

      .login-btn svg{
        width:22px;
        height:22px;
        stroke:currentColor;
        fill:none;
        stroke-width:2;
        stroke-linecap:round;
        stroke-linejoin:round;
      }

      .message.error{
        margin-top:14px;
        border-radius:12px;
        padding:12px 14px;
        background:#fff2f2;
        border:1px solid #ffd0d0;
        color:#b42318;
        font-weight:700;
        font-size:14px;
      }

      .secure-box{
        margin-top:28px;
        text-align:center;
      }

      .secure-title{
        display:grid;
        grid-template-columns:1fr auto 1fr;
        align-items:center;
        gap:14px;
        color:#1d2b52;
        font-size:16px;
        font-weight:800;
      }

      .secure-title::before,
      .secure-title::after{
        content:"";
        height:1px;
        background:#dbe5f2;
      }

      .secure-title span{
        display:inline-flex;
        align-items:center;
        gap:10px;
      }

      .secure-title svg{
        width:20px;
        height:20px;
        stroke:#0b63ff;
        fill:none;
        stroke-width:2;
        stroke-linecap:round;
        stroke-linejoin:round;
      }

      .secure-box p{
        margin:16px auto 0;
        max-width:520px;
        color:#7b8aa8;
        font-size:16px;
        line-height:1.6;
        font-weight:500;
      }

      .support-box{
        margin-top:28px;
        border:1px solid #dbe5f2;
        border-radius:16px;
        padding:18px 20px;
        display:grid;
        grid-template-columns:48px 1fr auto;
        gap:16px;
        align-items:center;
        text-decoration:none;
        background:#fff;
      }

      .support-icon{
        width:48px;
        height:48px;
        border-radius:999px;
        border:2px solid #7f93b2;
        color:#4c6287;
        display:flex;
        align-items:center;
        justify-content:center;
        font-size:28px;
        font-weight:800;
      }

      .support-copy strong{
        display:block;
        color:#15264b;
        font-size:16px;
        line-height:1.25;
        font-weight:800;
      }

      .support-copy span{
        display:block;
        margin-top:4px;
        color:#607392;
        font-size:15px;
        line-height:1.45;
        font-weight:500;
      }

      .support-arrow{
        color:#6f819f;
        font-size:32px;
        line-height:1;
      }
      /* DESKTOP should look like picture 2 */
.login-row,
.secure-box,
.support-box{
  display:none;
}

.login-btn svg{
  display:none;
}

/* MOBILE should look like picture 3 */
@media (max-width: 980px){
  body{
    background:#f7f9fd;
  }

  .login-page{
    display:block;
    min-height:100vh;
    background:#f7f9fd;
  }

  .login-hero{
    display:none;
  }

  .login-main{
    min-height:100vh;
    padding:0 0 24px;
    background:#f7f9fd;
  }

  .login-main-center{
    display:block;
    padding:0;
  }

  .login-row{
    display:flex;
  }

  .secure-box{
    display:block;
  }

  .support-box{
    display:grid;
  }

  .login-btn svg{
    display:block;
  }

  .mobile-hero{
    display:block;
    position:relative;
    overflow:hidden;
    height:360px;
    min-height:360px;
    background:
      linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
  }

  .mobile-hero::before{
    content:"";
    position:absolute;
    inset:0;
    z-index:1;
    pointer-events:none;
    background:
      radial-gradient(280px 140px at 26% 12%, rgba(214,228,249,.80), transparent 70%),
      radial-gradient(260px 160px at 84% 78%, rgba(204,229,255,.35), transparent 72%);
  }

  .mobile-wave{
    display:block;
    position:absolute;
    inset:0;
    width:100%;
    height:100%;
    z-index:0;
    pointer-events:none;
    opacity:.95;
  }

  .mobile-hero-copy,
  .mobile-hero-art{
    position:absolute;
    z-index:2;
  }

  .mobile-hero-copy{
    left:24px;
    top:106px;
    width:178px;
  }

  .mobile-logo{
    display:flex;
    align-items:center;
    gap:10px;
    margin:0;
  }

  .mobile-logo svg{
    width:33px;
    height:33px;
    flex:0 0 33px;
  }

  .mobile-logo-text{
    font-size:33px;
    line-height:1;
    font-weight:900;
    letter-spacing:-.06em;
  }

  .mobile-logo-text .tim{color:#081844;}
  .mobile-logo-text .iq{color:#0b63ff;}

  .mobile-hero-copy p{
    margin:20px 0 0;
    width:188px;
    max-width:188px;
    color:#4f6485;
    font-size:15px;
    line-height:1.5;
    font-weight:500;
  }

  .mobile-hero-art{
    right:18px;
    top:86px;
    width:150px;
  }

  .mobile-hero-art svg{
    display:block;
    width:100%;
    height:auto;
  }

  .login-card{
    width:calc(100% - 24px);
    max-width:none;
    margin:-8px auto 0;
    background:#fff;
    border:1px solid #e4ebf5;
    border-radius:22px;
    padding:28px 20px 22px;
    box-shadow:0 10px 30px rgba(12,31,88,.08);
  }

  .login-card h1{
    font-size:34px;
    line-height:1.02;
    letter-spacing:-.05em;
    color:#081844;
    margin-bottom:0;
  }

  .login-card .subtitle{
    margin:12px 0 28px;
    color:#6e7f9c;
    font-size:15px;
    line-height:1.45;
    font-weight:500;
  }

  .login-form{
    gap:20px;
  }

  .field label{
    display:inline-block;
    margin:0 0 -9px 54px;
    padding:0 9px;
    position:relative;
    z-index:2;
    background:#fff;
    color:#081844;
    font-size:13px;
    font-weight:900;
    line-height:1;
  }

  .input-wrap{
    position:relative;
  }

  .login-input{
    height:58px;
    border-radius:14px;
    padding:0 20px 0 52px;
    font-size:15px;
    font-weight:500;
    border:1px solid #dde6f0;
    box-shadow:0 1px 2px rgba(12,31,88,.03);
  }

  .login-input::placeholder{
    color:#8a98b0;
    font-weight:500;
  }

  .input-icon{
    left:16px;
    width:21px;
    height:21px;
    color:#0b63ff;
  }

  .input-icon svg{
    width:21px;
    height:21px;
  }

  .input-note{
    margin-top:10px;
    color:#7a89a1;
    font-size:14px;
    line-height:1.35;
    font-weight:500;
  }

  .password-input{
    padding-right:58px;
  }

  .toggle-pass{
    width:40px;
    height:40px;
    right:9px;
    border-radius:12px;
    border:1px solid #dde6f0;
    background:#fff;
    color:#0b63ff;
  }

  .login-row{
    align-items:center;
    justify-content:space-between;
    gap:12px;
    margin-top:2px;
  }

  .remember,
  .forgot-link{
    font-size:14px;
    font-weight:600;
  }

  .remember{
    color:#1d2b50;
    gap:10px;
  }

  .remember input{
    width:18px;
    height:18px;
    accent-color:#0b63ff;
  }

  .forgot-link{
    color:#0b63ff;
  }

  .login-btn{
    height:60px;
    border-radius:14px;
    margin-top:4px;
    padding:0 18px 0 22px;
    background:linear-gradient(90deg, #1679ff 0%, #0b63ff 100%);
    box-shadow:0 10px 24px rgba(11,99,255,.22);
    display:flex;
    align-items:center;
    justify-content:space-between;
  }

  .login-btn::before{
    display:none;
  }

  .login-btn span{
    flex:1;
    text-align:center;
    font-size:18px;
    font-weight:800;
    color:#fff;
    letter-spacing:-.02em;
    margin-left:20px;
  }

  .login-btn svg{
    width:26px;
    height:26px;
    flex:0 0 26px;
  }

  .secure-box{
    margin-top:30px;
    text-align:center;
  }

  .secure-title{
    font-size:16px;
    gap:14px;
    color:#1d2b52;
    font-weight:800;
  }

  .secure-title::before,
  .secure-title::after{
    content:"";
    height:1px;
    background:#e1e8f2;
  }

  .secure-box p{
    margin:14px auto 0;
    max-width:300px;
    font-size:14px;
    line-height:1.6;
    color:#7a89a1;
    font-weight:500;
  }

  .support-box{
    margin-top:26px;
    padding:16px;
    border-radius:18px;
    grid-template-columns:48px 1fr auto;
    gap:14px;
    border:1px solid #dde6f0;
    background:#fff;
  }

  .support-icon{
    width:48px;
    height:48px;
    font-size:28px;
    border:2px solid #8aa0bf;
    color:#506887;
  }

  .support-copy strong{
    font-size:16px;
    font-weight:800;
    color:#15264b;
  }

  .support-copy span{
    font-size:14px;
    color:#607392;
  }

  .support-arrow{
    font-size:28px;
    color:#6f819f;
  }

  .login-footer{
    display:none;
  }
}

      @media (max-width: 640px){
  .mobile-hero{
    height:344px;
    min-height:344px;
  }

  .mobile-hero-copy{
    left:24px;
    top:108px;
    width:172px;
  }

  .mobile-logo svg{
    width:31px;
    height:31px;
    flex:0 0 31px;
  }

  .mobile-logo-text{
    font-size:31px;
  }

  .mobile-hero-copy p{
    margin-top:18px;
    width:170px;
    max-width:170px;
    font-size:14px;
    line-height:1.5;
  }

  .mobile-hero-art{
    right:16px;
    top:90px;
    width:136px;
  }

  .login-card{
    width:calc(100% - 20px);
    padding:28px 18px 20px;
  }

  .login-card h1{
    font-size:31px;
  }

  .login-card .subtitle{
    font-size:14px;
    margin-bottom:24px;
  }
}

      @media (max-width: 430px){
  .mobile-hero{
    height:334px;
    min-height:334px;
  }

  .mobile-hero-copy{
    left:22px;
    top:108px;
    width:164px;
  }

  .mobile-hero-copy p{
    width:160px;
    max-width:160px;
  }

  .mobile-hero-art{
    right:14px;
    top:94px;
    width:126px;
  }

  .remember,
  .forgot-link{
    font-size:14px;
  }
}


      /* FINAL FIX: keep desktop and mobile isolated.
         This block intentionally comes last so it overrides older mobile rules above. */
      .mobile-hero,
      .mobile-wave{
        display:none;
      }

      @media (min-width: 981px){
        .mobile-hero,
        .mobile-wave{
          display:none !important;
        }

        .login-main{
          min-height:100vh;
          padding:54px 54px 32px;
          display:flex;
          flex-direction:column;
          justify-content:space-between;
          background:
            radial-gradient(760px 340px at 85% 0%, rgba(126,211,247,.20), transparent 55%),
            linear-gradient(180deg, #fdfefe 0%, #f9fbfe 100%);
        }

        .login-main-center{
          flex:1;
          display:flex;
          align-items:center;
          justify-content:center;
          padding:0;
        }

        .login-card{
          width:min(100%, 700px);
          max-width:700px;
          margin:0;
          border-radius:20px;
          padding:58px 62px 48px;
          box-shadow:0 20px 60px rgba(12,31,88,.08);
        }

        .login-card h1{
          font-size:58px;
          line-height:.98;
          letter-spacing:-.055em;
        }

        .login-card .subtitle{
          font-size:18px;
          margin:14px 0 34px;
        }

        .login-row,
        .secure-box,
        .support-box{
          display:none !important;
        }

        .login-btn{
          height:66px;
          justify-content:center;
          padding:0 22px;
          font-size:24px;
          font-weight:800;
        }

        .login-btn span{
          font-size:24px;
          font-weight:800;
          margin:0;
        }

        .login-btn svg{
          display:none !important;
        }
      }

      @media (max-width: 980px){
        html,
        body{
          width:100%;
          min-height:100%;
          background:#f7faff;
        }

        body{
          overflow-x:hidden;
        }

        .login-page{
          display:block;
          width:100%;
          min-height:100vh;
          background:linear-gradient(180deg, #f8fbff 0%, #f4f8fe 100%);
        }

        .login-hero{
          display:none !important;
        }

        .login-main{
          display:block;
          min-height:100vh;
          padding:0 0 24px;
          background:transparent;
        }

        .login-main-center{
          display:block;
          padding:0;
        }

        .mobile-hero{
          display:block !important;
          position:relative;
          overflow:hidden;
          height:350px;
          min-height:350px;
          background:linear-gradient(180deg, #f8fbff 0%, #eef6ff 100%);
        }

        .mobile-hero::before{
          content:"";
          position:absolute;
          inset:0;
          z-index:1;
          pointer-events:none;
          background:
            radial-gradient(300px 150px at 50% -5%, rgba(255,255,255,.95), transparent 72%),
            linear-gradient(180deg, rgba(255,255,255,.15), rgba(255,255,255,.50));
        }

        .mobile-wave{
          display:block !important;
          position:absolute;
          inset:0;
          width:100%;
          height:100%;
          z-index:0;
          pointer-events:none;
        }

        .mobile-hero-copy,
        .mobile-hero-art{
          position:absolute;
          z-index:2;
        }

        .mobile-hero-copy{
          left:32px;
          top:112px;
          width:190px;
        }

        .mobile-logo{
          display:flex;
          align-items:center;
          gap:10px;
        }

        .mobile-logo svg{
          width:34px;
          height:34px;
          flex:0 0 34px;
        }

        .mobile-logo-text{
          font-size:34px;
          line-height:1;
          font-weight:900;
          letter-spacing:-.06em;
        }

        .mobile-logo-text .tim{color:#081844;}
        .mobile-logo-text .iq{color:#0b63ff;}

        .mobile-hero-copy p{
          margin:22px 0 0;
          width:196px;
          max-width:196px;
          color:#536781;
          font-size:15px;
          line-height:1.55;
          font-weight:500;
        }

        .mobile-hero-art{
          right:24px;
          top:86px;
          width:152px;
        }

        .mobile-hero-art svg{
          display:block;
          width:100%;
          height:auto;
        }

        .login-card{
          width:calc(100% - 40px);
          max-width:640px;
          margin:-2px auto 0;
          background:#fff;
          border:1px solid #dfe9f5;
          border-radius:24px;
          padding:30px 36px 24px;
          box-shadow:0 18px 45px rgba(12,31,88,.08);
        }

        .login-card h1{
          margin:0;
          color:#081844;
          font-size:34px;
          line-height:1.02;
          font-weight:900;
          letter-spacing:-.055em;
        }

        .login-card .subtitle{
          margin:12px 0 28px;
          color:#6e7f9c;
          font-size:15px;
          line-height:1.45;
          font-weight:500;
        }

        .login-form{
          display:grid;
          gap:20px;
        }

        .field label{
          display:inline-block;
          position:relative;
          z-index:2;
          margin:0 0 -9px 54px;
          padding:0 9px;
          background:#fff;
          color:#081844;
          font-size:13px;
          font-weight:900;
          line-height:1;
        }

        .input-wrap{
          position:relative;
        }

        .login-input{
          width:100%;
          height:58px;
          border:1px solid #dce6f2;
          border-radius:14px;
          background:#fff;
          padding:0 20px 0 52px;
          color:#081844;
          font-size:15px;
          font-weight:600;
          box-shadow:0 2px 8px rgba(12,31,88,.035);
        }

        .login-input::placeholder{
          color:#8b98ae;
          font-weight:500;
        }

        .input-icon{
          left:16px;
          width:21px;
          height:21px;
          color:#0b63ff;
        }

        .input-icon svg{
          width:21px;
          height:21px;
        }

        .input-note{
          margin-top:10px;
          color:#7a89a1;
          font-size:14px;
          line-height:1.35;
          font-weight:600;
        }

        .password-input{
          padding-right:58px;
        }

        .toggle-pass{
          width:40px;
          height:40px;
          right:9px;
          border-radius:12px;
          border:1px solid #dce6f2;
          background:#fff;
          color:#0b63ff;
        }

        .login-row{
          display:flex !important;
          align-items:center;
          justify-content:space-between;
          gap:12px;
          margin-top:2px;
        }

        .remember,
        .forgot-link{
          font-size:15px;
          font-weight:800;
        }

        .remember{
          display:flex;
          align-items:center;
          gap:10px;
          color:#1d2b50;
        }

        .remember input{
          appearance:none;
          -webkit-appearance:none;
          width:18px;
          height:18px;
          border:1.5px solid #9aabc5;
          border-radius:4px;
          background:#fff;
          position:relative;
          display:inline-grid;
          place-items:center;
          margin:0;
        }

        .remember input:checked{
          border-color:#0b63ff;
          background:#0b63ff;
        }

        .remember input:checked::after{
          content:"";
          width:8px;
          height:4px;
          border-left:2px solid #fff;
          border-bottom:2px solid #fff;
          transform:rotate(-45deg) translate(1px,-1px);
        }

        .forgot-link{
          color:#0b63ff;
          text-decoration:none;
        }

        .login-btn{
          height:60px;
          border-radius:14px;
          margin-top:2px;
          padding:0 18px 0 22px;
          background:linear-gradient(90deg, #1679ff 0%, #0b63ff 100%);
          box-shadow:0 16px 30px rgba(11,99,255,.22);
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:0;
        }

        .login-btn::before{
          content:"";
          width:26px;
          height:26px;
          flex:0 0 26px;
        }

        .login-btn span{
          flex:1;
          text-align:center;
          color:#fff;
          font-size:19px;
          font-weight:800;
          letter-spacing:-.02em;
          margin:0;
        }

        .login-btn svg{
          display:block !important;
          width:26px;
          height:26px;
          flex:0 0 26px;
        }

        .secure-box{
          display:block !important;
          margin-top:30px;
          text-align:center;
        }

        .secure-title{
          display:grid;
          grid-template-columns:1fr auto 1fr;
          align-items:center;
          gap:14px;
          color:#1d2b52;
          font-size:16px;
          font-weight:800;
        }

        .secure-title::before,
        .secure-title::after{
          content:"";
          height:1px;
          background:#e1e8f2;
        }

        .secure-title span{
          display:inline-flex;
          align-items:center;
          gap:10px;
          white-space:nowrap;
        }

        .secure-box p{
          margin:14px auto 0;
          max-width:320px;
          color:#7a89a1;
          font-size:14px;
          line-height:1.6;
          font-weight:500;
        }

        .support-box{
          display:grid !important;
          margin-top:26px;
          padding:16px;
          border:1px solid #dce6f2;
          border-radius:18px;
          background:#fff;
          grid-template-columns:48px 1fr auto;
          gap:14px;
          align-items:center;
        }

        .support-icon{
          width:48px;
          height:48px;
          border:2px solid #8ba0bf;
          color:#506887;
          font-size:28px;
        }

        .support-copy strong{
          color:#15264b;
          font-size:16px;
          font-weight:900;
        }

        .support-copy span{
          color:#607392;
          font-size:14px;
          line-height:1.4;
        }

        .support-arrow{
          color:#6f819f;
          font-size:28px;
        }

        .login-footer{
          display:none !important;
        }
      }

      @media (max-width: 430px){
        .mobile-hero{
          height:336px;
          min-height:336px;
        }

        .mobile-hero-copy{
          left:24px;
          top:110px;
          width:166px;
        }

        .mobile-logo svg{
          width:31px;
          height:31px;
          flex-basis:31px;
        }

        .mobile-logo-text{
          font-size:31px;
        }

        .mobile-hero-copy p{
          width:166px;
          max-width:166px;
          font-size:14px;
        }

        .mobile-hero-art{
          right:16px;
          top:92px;
          width:128px;
        }

        .login-card{
          width:calc(100% - 24px);
          padding:30px 20px 22px;
        }

        .login-card h1{
          font-size:31px;
        }

        .login-card .subtitle{
          font-size:14px;
          margin-bottom:24px;
        }

        .remember,
        .forgot-link{
          font-size:14px;
        }
      }

      /* PIXEL-MATCH MOBILE OVERRIDES */
      @media (max-width: 980px){
        body,
        .login-page,
        .login-main{
          background:#f4f7fb !important;
        }

        .mobile-hero{
          display:block !important;
          height:352px !important;
          min-height:352px !important;
          background:
            radial-gradient(260px 100px at 18% 14%, rgba(222,232,247,.90), transparent 72%),
            linear-gradient(180deg, #f8fbff 0%, #eef5fe 100%) !important;
        }

        .mobile-hero-copy{
          left:32px !important;
          top:110px !important;
          width:180px !important;
        }

        .mobile-logo,
        .mobile-logo-text,
        .mobile-hero-copy p,
        .login-card h1,
        .login-card .subtitle,
        .field label,
        .login-input,
        .login-input::placeholder,
        .input-note,
        .remember,
        .forgot-link,
        .login-btn span,
        .secure-title,
        .secure-box p,
        .support-copy strong,
        .support-copy span{
          font-family:Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif !important;
        }

        .mobile-logo svg{
          width:34px !important;
          height:34px !important;
          flex:0 0 34px !important;
        }

        .mobile-logo-text{
          font-size:33px !important;
          font-weight:900 !important;
          letter-spacing:-.06em !important;
        }

        .mobile-hero-copy p{
          margin-top:22px !important;
          width:196px !important;
          max-width:196px !important;
          color:#556982 !important;
          font-size:15px !important;
          line-height:1.55 !important;
          font-weight:500 !important;
        }

        .mobile-hero-art{
          right:20px !important;
          top:82px !important;
          width:168px !important;
        }

        .login-card{
          width:calc(100% - 38px) !important;
          margin:-6px auto 0 !important;
          border-radius:24px !important;
          border:1px solid #dfe8f2 !important;
          padding:30px 22px 24px !important;
          box-shadow:0 14px 38px rgba(12,31,88,.08) !important;
        }

        .login-card h1{
          color:#081844 !important;
          font-size:33px !important;
          line-height:1.05 !important;
          font-weight:800 !important;
          letter-spacing:-.04em !important;
        }

        .login-card .subtitle{
          margin:14px 0 28px !important;
          color:#6c7e9b !important;
          font-size:15px !important;
          line-height:1.45 !important;
          font-weight:500 !important;
        }

        .field label{
          color:#17284e !important;
          font-size:12.5px !important;
          font-weight:800 !important;
        }

        .login-input{
          height:58px !important;
          border:1px solid #dce5f0 !important;
          border-radius:14px !important;
          box-shadow:0 1px 3px rgba(10,24,51,.03) !important;
          padding-left:52px !important;
          color:#223555 !important;
          font-size:15px !important;
          font-weight:500 !important;
        }

        .login-input::placeholder{
          color:#96a3b8 !important;
          font-weight:500 !important;
        }

        .toggle-pass{
          border:1px solid #dce5f0 !important;
          border-radius:12px !important;
        }

        .remember{
          font-size:14px !important;
          font-weight:600 !important;
        }

        .forgot-link{
          font-size:14px !important;
          font-weight:500 !important;
        }

        .remember input{
          appearance:none !important;
          -webkit-appearance:none !important;
          width:18px !important;
          height:18px !important;
          border-radius:4px !important;
          border:1.5px solid #9cb0ca !important;
          background:#fff !important;
          display:inline-grid !important;
          place-items:center !important;
          margin:0 !important;
          position:relative !important;
        }

        .remember input:checked{
          background:#0b63ff !important;
          border-color:#0b63ff !important;
        }

        .remember input:checked::after{
          content:"" !important;
          width:8px !important;
          height:4px !important;
          border-left:2px solid #fff !important;
          border-bottom:2px solid #fff !important;
          transform:rotate(-45deg) translate(1px,-1px) !important;
        }

        .login-btn{
          height:60px !important;
          border-radius:14px !important;
          margin-top:4px !important;
          padding:0 18px 0 22px !important;
          background:linear-gradient(90deg, #177cff 0%, #0b63ff 100%) !important;
          box-shadow:0 14px 28px rgba(11,99,255,.22) !important;
        }

        .login-btn span{
          font-size:18px !important;
          font-weight:700 !important;
          margin-left:24px !important;
        }

        .secure-box{
          margin-top:32px !important;
        }

        .secure-title{
          font-size:16px !important;
          font-weight:700 !important;
        }

        .secure-box p{
          max-width:305px !important;
          color:#7b89a0 !important;
          font-size:14px !important;
        }

        .support-box{
          margin-top:28px !important;
          border:1px solid #dde5f0 !important;
          border-radius:18px !important;
          padding:16px 18px !important;
          box-shadow:none !important;
        }

        .support-copy strong{
          font-size:16px !important;
          font-weight:700 !important;
        }

        .support-copy span{
          font-size:14px !important;
          line-height:1.45 !important;
        }
      }

      @media (max-width: 430px){
        .mobile-hero{height:336px !important; min-height:336px !important;}
        .mobile-hero-copy{left:28px !important; top:108px !important; width:174px !important;}
        .mobile-hero-copy p{width:176px !important; max-width:176px !important;}
        .mobile-hero-art{right:14px !important; top:82px !important; width:150px !important;}
        .login-card{width:calc(100% - 40px) !important; padding:30px 20px 24px !important;}
      }

      /* SURGICAL MATCH FIX: shield + checkbox only. Keep this last. */
      @media (max-width: 980px){
        .mobile-hero-art{
          right:16px !important;
          top:78px !important;
          width:176px !important;
        }

        .mobile-hero-art svg{
          overflow:visible !important;
        }

        .remember > input[type="checkbox"]{
          appearance:none !important;
          -webkit-appearance:none !important;
          box-sizing:border-box !important;
          display:inline-grid !important;
          place-items:center !important;
          flex:0 0 18px !important;
          width:18px !important;
          min-width:18px !important;
          max-width:18px !important;
          height:18px !important;
          min-height:18px !important;
          max-height:18px !important;
          line-height:18px !important;
          padding:0 !important;
          margin:0 !important;
          border:0 !important;
          border-radius:4px !important;
          background:#0b63ff !important;
          position:relative !important;
          vertical-align:middle !important;
        }

        .remember > input[type="checkbox"]::after{
          content:"" !important;
          width:8px !important;
          height:4px !important;
          border-left:2px solid #fff !important;
          border-bottom:2px solid #fff !important;
          transform:rotate(-45deg) translate(1px,-1px) !important;
        }
      }

      @media (max-width: 430px){
        .mobile-hero-art{
          right:10px !important;
          top:80px !important;
          width:164px !important;
        }
      }
      /* FINAL MOBILE SHIELD + CHECKBOX CORRECTION */
@media (max-width: 980px){
  /* FINAL SHIELD POSITION MATCH */
@media (max-width: 980px){
  .mobile-hero-art{
    right:28px !important;
    top:88px !important;
    width:150px !important;
    height:150px !important;
    z-index:2 !important;
  }

  .mobile-shield-svg{
    display:block !important;
    width:100% !important;
    height:auto !important;
    overflow:visible !important;
  }
}

@media (max-width: 430px){
  .mobile-hero-art{
    right:20px !important;
    top:90px !important;
    width:138px !important;
    height:138px !important;
  }
}

  .mobile-shield-svg{
    display:block !important;
    width:100% !important;
    height:auto !important;
    overflow:visible !important;
  }

  .remember input{
    appearance:none !important;
    -webkit-appearance:none !important;
    width:18px !important;
    height:18px !important;
    min-width:18px !important;
    max-width:18px !important;
    min-height:18px !important;
    max-height:18px !important;
    padding:0 !important;
    margin:0 !important;
    border-radius:4px !important;
    border:1.5px solid #0b63ff !important;
    background:#0b63ff !important;
    display:inline-grid !important;
    place-items:center !important;
    position:relative !important;
    flex:0 0 18px !important;
  }

  .remember input::after{
    content:"" !important;
    width:8px !important;
    height:4px !important;
    border-left:2px solid #fff !important;
    border-bottom:2px solid #fff !important;
    transform:rotate(-45deg) translate(1px,-1px) !important;
  }
}

@media (max-width: 430px){
  .mobile-hero-art{
    right:8px !important;
    top:76px !important;
    width:164px !important;
    height:164px !important;
  }
}
/* FINAL MOBILE SHIELD DESIGN + POSITION */
@media (max-width: 980px){
  .mobile-hero-art{
    position:absolute !important;
    right:22px !important;
    top:82px !important;
    width:155px !important;
    height:155px !important;
    z-index:2 !important;
  }

  .mobile-shield-svg{
    display:block !important;
    width:100% !important;
    height:auto !important;
    overflow:visible !important;
  }
}

@media (max-width: 430px){
  .mobile-hero-art{
    right:14px !important;
    top:84px !important;
    width:145px !important;
    height:145px !important;
  }
}
/* FINAL MOBILE SHIELD SHAPE + PLATFORM MATCH */
@media (max-width: 980px){
  .mobile-hero-art{
    position:absolute !important;
    right:16px !important;
    top:74px !important;
    width:170px !important;
    height:170px !important;
    z-index:2 !important;
  }

  .mobile-shield-svg{
    display:block !important;
    width:100% !important;
    height:auto !important;
    overflow:visible !important;
  }
}

@media (max-width: 430px){
  .mobile-hero-art{
    right:10px !important;
    top:76px !important;
    width:160px !important;
    height:160px !important;
  }
}
/* FIX: remove mobile auto zoom + fix Remember me checkbox */
@media (max-width: 980px){
  html,
  body{
    -webkit-text-size-adjust:100% !important;
    text-size-adjust:100% !important;
    touch-action:manipulation !important;
  }

  input,
  textarea,
  select,
  button{
    font-size:16px !important;
  }

  .login-input{
    font-size:16px !important;
  }

  .remember{
    cursor:pointer !important;
    -webkit-tap-highlight-color:transparent !important;
  }

  .remember > input[type="checkbox"]{
    appearance:none !important;
    -webkit-appearance:none !important;
    box-sizing:border-box !important;
    display:inline-grid !important;
    place-items:center !important;
    width:18px !important;
    height:18px !important;
    min-width:18px !important;
    min-height:18px !important;
    max-width:18px !important;
    max-height:18px !important;
    flex:0 0 18px !important;
    padding:0 !important;
    margin:0 !important;
    border-radius:4px !important;
    border:1.5px solid #9cb0ca !important;
    background:#fff !important;
    position:relative !important;
    cursor:pointer !important;
  }

  .remember > input[type="checkbox"]::after{
    content:"" !important;
    width:8px !important;
    height:4px !important;
    border-left:2px solid #fff !important;
    border-bottom:2px solid #fff !important;
    transform:rotate(-45deg) translate(1px,-1px) !important;
    opacity:0 !important;
  }

  .remember > input[type="checkbox"]:checked{
    border-color:#0b63ff !important;
    background:#0b63ff !important;
  }

  .remember > input[type="checkbox"]:checked::after{
    opacity:1 !important;
  }
}
    </style>
    """

    login_viewport = '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">'

    html = f"""
    <div class="login-page">

      <section class="login-hero">
        <div class="hero-inner">
          <div class="hero-logo" aria-label="TimIQ">
            <svg viewBox="0 0 64 64" fill="none" aria-hidden="true">
              <path d="M7 25H26" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
              <path d="M10 34H24" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
              <path d="M16 43H22" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
              <rect x="31" y="8" width="11" height="6" rx="2" fill="#7FC7EE"/>
              <rect x="47.5" y="14" width="6" height="6" rx="1.5" transform="rotate(45 47.5 14)" fill="#7FC7EE"/>
              <circle cx="36" cy="32" r="18" stroke="#7FC7EE" stroke-width="5.5"/>
              <path d="M36 32V18A14 14 0 0 1 50 32H36Z" fill="#4B83C6"/>
            </svg>
            <div class="hero-logo-text"><span class="tim">Tim</span><span class="iq">IQ</span></div>
          </div>

          <div class="hero-dots" aria-hidden="true"></div>

          <div class="hero-copy">
  <h1>
    One workspace.<br>
    Every worker.<br>
    <span class="accent">Total visibility.</span>
  </h1>
  <div class="hero-rule"></div>
  <p>TimIQ brings together clock-in, attendance and payroll in one secure platform—so your projects run on time and on budget.</p>
</div>

          <div class="hero-features">
            <div class="hero-feature">
              <div class="hero-feature-icon">
                <svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"/><circle cx="9.5" cy="7" r="4"/><path d="M19 8v6"/><path d="M22 11h-6"/></svg>
              </div>
              <div>
                <strong>Workforce in sync</strong>
                <span>Accurate attendance across sites and teams.</span>
              </div>
            </div>

            <div class="hero-feature">
              <div class="hero-feature-icon">
                <svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-5"/></svg>
              </div>
              <div>
                <strong>Built for security</strong>
                <span>Enterprise-grade protection for your data.</span>
              </div>
            </div>

            <div class="hero-feature">
              <div class="hero-feature-icon">
                <svg viewBox="0 0 24 24"><path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 16v-5"/><path d="M12 16V8"/><path d="M16 16v-9"/></svg>
              </div>
              <div>
                <strong>Actionable insights</strong>
                <span>Real-time reporting that keeps projects moving.</span>
              </div>
            </div>
          </div>
        </div>

        <div class="hero-scene" aria-hidden="true">
  <svg viewBox="0 0 900 520" preserveAspectRatio="none">
    <defs>
      <linearGradient id="siteGlow" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#77d3ff" stop-opacity="0"/>
        <stop offset="1" stop-color="#77d3ff" stop-opacity=".28"/>
      </linearGradient>

      <linearGradient id="siteFill" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#6ecbff" stop-opacity=".30"/>
        <stop offset="1" stop-color="#6ecbff" stop-opacity=".04"/>
      </linearGradient>

      <linearGradient id="darkFade" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#0d2f89" stop-opacity=".00"/>
        <stop offset=".35" stop-color="#0d2f89" stop-opacity=".10"/>
        <stop offset="1" stop-color="#071a4a" stop-opacity=".78"/>
      </linearGradient>
    </defs>

    <!-- background site glow -->
    <path d="M0 518V360C120 330 205 318 300 326C410 334 515 360 620 349C717 339 805 301 900 250V518Z"
          fill="url(#darkFade)"/>

    <!-- big soft construction glow -->
    <ellipse cx="620" cy="350" rx="210" ry="130" fill="url(#siteGlow)" opacity=".55"/>
    <ellipse cx="670" cy="338" rx="150" ry="90" fill="url(#siteGlow)" opacity=".40"/>

    <!-- arc line like the reference -->
    <path d="M355 515C372 430 402 360 456 304C522 236 623 207 900 155"
          stroke="#7fd8ff" stroke-opacity=".22" stroke-width="2" fill="none"/>

    <!-- crane -->
    <g opacity=".52" stroke="#7fd8ff" stroke-width="3" fill="none">
      <path d="M722 130V392"/>
      <path d="M722 150L556 282"/>
      <path d="M556 282H796"/>
      <path d="M620 282l14-22h122"/>
      <path d="M650 282v48"/>
      <path d="M749 282v88"/>
      <path d="M737 370c0 10-7 18-18 18"/>
    </g>

    <!-- buildings / scaffolding -->
    <g opacity=".45">
      <rect x="472" y="278" width="30" height="152" fill="url(#siteFill)"/>
      <rect x="512" y="236" width="26" height="194" fill="url(#siteFill)"/>
      <rect x="546" y="200" width="22" height="230" fill="url(#siteFill)"/>
      <rect x="578" y="250" width="28" height="180" fill="url(#siteFill)"/>
      <rect x="616" y="178" width="20" height="252" fill="url(#siteFill)"/>
      <rect x="646" y="220" width="24" height="210" fill="url(#siteFill)"/>
      <rect x="680" y="160" width="18" height="270" fill="url(#siteFill)"/>
      <rect x="706" y="138" width="24" height="292" fill="url(#siteFill)"/>
    </g>

    <g opacity=".28" stroke="#8adfff" stroke-width="2">
      <path d="M585 216H735"/>
      <path d="M585 248H735"/>
      <path d="M585 280H735"/>
      <path d="M585 312H735"/>
      <path d="M585 344H735"/>
      <path d="M585 376H735"/>
    </g>

    <!-- silhouetted workers -->
    <g fill="#081a4a" opacity=".88">
      <circle cx="640" cy="338" r="23"/>
      <path d="M584 500c0-71 44-124 99-124c55 0 99 53 99 124z"/>
      <rect x="627" y="358" width="28" height="92" rx="10"/>

      <circle cx="575" cy="364" r="20"/>
      <path d="M520 502c0-61 39-108 87-108s87 47 87 108z"/>
      <rect x="565" y="382" width="24" height="80" rx="10"/>
      <rect x="555" y="390" width="12" height="82" rx="8" transform="rotate(15 555 390)"/>
    </g>

    <!-- small foreground silhouettes -->
    <g fill="#081a4a" opacity=".70">
      <rect x="95" y="314" width="38" height="128"/>
      <rect x="158" y="248" width="42" height="194"/>
      <rect x="228" y="286" width="34" height="156"/>
      <rect x="292" y="194" width="46" height="248"/>
      <rect x="364" y="270" width="38" height="172"/>
    </g>

    <!-- subtle circles -->
    <g opacity=".35">
      <circle cx="210" cy="380" r="19" fill="#72c7f6"/>
      <circle cx="690" cy="370" r="21" fill="#72c7f6"/>
    </g>

    <!-- ground -->
    <path d="M0 500C220 470 385 468 562 476C665 481 781 486 900 470V520H0Z"
          fill="#08235f" opacity=".80"/>
  </svg>
</div>
      </section>

      <section class="login-main">
        <div class="login-main-center">

          <div class="mobile-hero">
            <svg class="mobile-wave" viewBox="0 0 430 340" preserveAspectRatio="none" aria-hidden="true">
              <path d="M0 32C60 12 116 16 180 42C247 69 311 65 430 30V340H0Z" fill="#e7f1ff"/>
              <path d="M0 106C77 89 145 97 218 126C292 155 352 146 430 118V340H0Z" fill="#f1f7ff"/>
              <path d="M0 188C79 178 146 188 220 220C291 250 355 244 430 216V340H0Z" fill="#fbfdff"/>
            </svg>

            <div class="mobile-hero-copy">
              <div class="mobile-logo" aria-label="TimIQ">
                <svg viewBox="0 0 64 64" fill="none" aria-hidden="true">
                  <path d="M7 25H26" stroke="#0B63FF" stroke-width="5.5" stroke-linecap="round"/>
                  <path d="M10 34H24" stroke="#0B63FF" stroke-width="5.5" stroke-linecap="round"/>
                  <path d="M16 43H22" stroke="#0B63FF" stroke-width="5.5" stroke-linecap="round"/>
                  <rect x="31" y="8" width="11" height="6" rx="2" fill="#0B63FF"/>
                  <rect x="47.5" y="14" width="6" height="6" rx="1.5" transform="rotate(45 47.5 14)" fill="#0B63FF"/>
                  <circle cx="36" cy="32" r="18" stroke="#0B63FF" stroke-width="5.5"/>
                  <path d="M36 32V18A14 14 0 0 1 50 32H36Z" fill="#72C7F6"/>
                </svg>
                <div class="mobile-logo-text"><span class="tim">Tim</span><span class="iq">IQ</span></div>
              </div>
              <p>Check-in, attendance and payroll in one secure workspace.</p>
            </div>

            <div class="mobile-hero-art" aria-hidden="true">
  <svg class="mobile-shield-svg" viewBox="0 0 280 240" fill="none" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <filter id="shieldSoftShadow" x="70" y="18" width="150" height="185" filterUnits="userSpaceOnUse">
        <feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#0B63FF" flood-opacity=".18"/>
      </filter>

      <radialGradient id="platformGlow" cx="50%" cy="50%" r="60%">
        <stop offset="0" stop-color="#6FD8FF" stop-opacity=".78"/>
        <stop offset=".55" stop-color="#6FD8FF" stop-opacity=".18"/>
        <stop offset="1" stop-color="#6FD8FF" stop-opacity="0"/>
      </radialGradient>

      <linearGradient id="ringStrokeOuter" x1="50" y1="188" x2="238" y2="188" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#CDEEFF" stop-opacity=".88"/>
        <stop offset="1" stop-color="#8CD8FF" stop-opacity=".70"/>
      </linearGradient>

      <linearGradient id="ringStrokeInner" x1="78" y1="188" x2="210" y2="188" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#F0FBFF" stop-opacity=".92"/>
        <stop offset="1" stop-color="#B4E7FF" stop-opacity=".82"/>
      </linearGradient>

      <linearGradient id="shieldOuter" x1="106" y1="28" x2="190" y2="178" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#71D0FF"/>
        <stop offset=".42" stop-color="#1585FF"/>
        <stop offset="1" stop-color="#095FF1"/>
      </linearGradient>

      <linearGradient id="shieldFront" x1="116" y1="42" x2="171" y2="150" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#BDEEFF"/>
        <stop offset=".42" stop-color="#6CC1FF"/>
        <stop offset="1" stop-color="#2A8DFF"/>
      </linearGradient>

      <linearGradient id="shieldRightSide" x1="176" y1="36" x2="214" y2="156" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#A3E7FF" stop-opacity=".95"/>
        <stop offset=".42" stop-color="#43A5FF" stop-opacity=".82"/>
        <stop offset="1" stop-color="#0B63FF" stop-opacity=".95"/>
      </linearGradient>

      <linearGradient id="shieldGloss" x1="109" y1="40" x2="143" y2="126" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#FFFFFF" stop-opacity=".42"/>
        <stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
      </linearGradient>

      <linearGradient id="lockBody" x1="121" y1="94" x2="163" y2="140" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#FFFFFF"/>
        <stop offset="1" stop-color="#DCEEFF"/>
      </linearGradient>
    </defs>

    <!-- platform / circles -->
    <ellipse cx="150" cy="192" rx="88" ry="24" fill="url(#platformGlow)"/>
    <ellipse cx="150" cy="192" rx="100" ry="29" stroke="url(#ringStrokeOuter)" stroke-width="2.8" opacity=".75"/>
    <ellipse cx="150" cy="192" rx="80" ry="23" stroke="#DFF5FF" stroke-width="2.2" opacity=".88"/>
    <ellipse cx="150" cy="192" rx="61" ry="17" stroke="url(#ringStrokeInner)" stroke-width="1.8" opacity=".98"/>
    <ellipse cx="150" cy="192" rx="42" ry="12" stroke="#FFFFFF" stroke-width="1.5" opacity=".88"/>

    <!-- subtle sweep lines like template -->
    <path d="M74 183C98 172 199 171 226 184" stroke="#FFFFFF" stroke-width="2" opacity=".52"/>
    <path d="M95 201C118 209 181 209 204 201" stroke="#8AD9FF" stroke-width="2" opacity=".42"/>

    <!-- shield -->
    <g filter="url(#shieldSoftShadow)">
      <!-- main outer body -->
      <path
        d="M150 24L206 44V92C206 136 184 171 150 194C116 171 94 136 94 92V44L150 24Z"
        fill="url(#shieldOuter)"
      />

      <!-- right 3D side -->
      <path
        d="M150 24L206 44L218 49V95C218 136 198 167 167 189L150 194V24Z"
        fill="url(#shieldRightSide)"
        opacity=".72"
      />

      <!-- front inset face -->
      <path
        d="M150 40L189 54V92C189 123 174 148 150 164C126 148 111 123 111 92V54L150 40Z"
        fill="url(#shieldFront)"
      />

      <!-- glossy left highlight -->
      <path
        d="M150 40L111 54V92C111 123 126 148 150 164V40Z"
        fill="url(#shieldGloss)"
      />

      <!-- top edge shine -->
      <path
        d="M94 44L150 24L206 44"
        stroke="#9AE8FF"
        stroke-width="5"
        stroke-linejoin="round"
        opacity=".82"
      />

      <!-- right face glossy strip -->
      <path
        d="M189 54L198 58V94C198 121 186 145 167 161L161 156C177 141 186 120 186 94V60Z"
        fill="#D7F5FF"
        opacity=".34"
      />

      <!-- lock shackle -->
      <path
        d="M129 105V91C129 79.4 138.4 70 150 70C161.6 70 171 79.4 171 91V105"
        stroke="#F9FDFF"
        stroke-width="9"
        stroke-linecap="round"
      />

      <!-- lock body -->
      <rect x="123" y="101" width="54" height="42" rx="10" fill="url(#lockBody)"/>

      <!-- keyhole -->
      <circle cx="150" cy="119" r="5.2" fill="#0B63FF"/>
      <rect x="147.8" y="124" width="4.4" height="12.5" rx="2.2" fill="#0B63FF"/>
    </g>
  </svg>
</div>
          </div>

          <div class="login-card">
            <h1>Welcome back</h1>
            <p class="subtitle">Sign in to continue to your workspace.</p>

            <form method="POST" class="login-form">
              <input type="hidden" name="csrf" value="{escape(csrf)}">

              <div class="field">
                <label for="login-username">Username</label>
                <div class="input-wrap">
                  <span class="input-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                  </span>
                  <input
                    id="login-username"
                    class="login-input"
                    name="username"
                    value="{escape(entered_username)}"
                    autocomplete="username"
                    autocapitalize="none"
                    spellcheck="false"
                    placeholder="Enter your username"
                    required>
                </div>
              </div>

              <div class="field">
                <label for="login-workplace">Workplace ID</label>
                <div class="input-wrap">
                  <span class="input-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24"><path d="M4 21V5a2 2 0 0 1 2-2h9l5 5v13"/><path d="M14 3v6h6"/><path d="M8 13h2"/><path d="M8 17h2"/><path d="M14 13h2"/><path d="M14 17h2"/></svg>
                  </span>
                  <input
                    id="login-workplace"
                    class="login-input"
                    name="workplace_id"
                    value="{escape(entered_workplace_id)}"
                    autocomplete="off"
                    autocapitalize="none"
                    autocorrect="off"
                    spellcheck="false"
                    inputmode="text"
                    placeholder="e.g. north01">
                </div>
                <div class="input-note">Required for workplace users.</div>
              </div>

              <div class="field">
                <label for="login-password">Password</label>
                <div class="input-wrap">
                  <span class="input-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>
                  </span>
                  <input
                    id="login-password"
                    class="login-input password-input"
                    type="password"
                    name="password"
                    autocomplete="current-password"
                    placeholder="Enter your password"
                    required>

                  <button
                    class="toggle-pass"
                    type="button"
                    data-password-toggle="login-password"
                    aria-label="Show password"
                    aria-pressed="false">
                    <svg class="eye-open" viewBox="0 0 24 24">
                      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"></path>
                      <circle cx="12" cy="12" r="3"></circle>
                    </svg>
                    <svg class="eye-closed" viewBox="0 0 24 24">
                      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"></path>
                      <circle cx="12" cy="12" r="3"></circle>
                      <path d="M4 20L20 4"></path>
                    </svg>
                  </button>
                </div>
              </div>

              <div class="login-row">
                <label class="remember">
                  <input id="remember-login" type="checkbox" name="remember" value="1" checked>
                  <span>Remember me</span>
                </label>

                <a class="forgot-link" href="#" onclick="alert('Please contact your administrator to reset your password.'); return false;">Forgot password?</a>
              </div>

              <button class="login-btn" type="submit">
                <span>Sign in</span>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12h14"></path>
                  <path d="m13 6 6 6-6 6"></path>
                </svg>
              </button>
            </form>

            {("<div class='message error'>" + escape(msg) + "</div>") if msg else ""}

            <div class="secure-box">
              <div class="secure-title">
                <span>
                  <svg viewBox="0 0 24 24">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                    <path d="M9 12l2 2 4-5"></path>
                  </svg>
                  Secure sign-in
                </span>
              </div>
              <p>Your data is protected with enterprise-grade encryption and secure authentication.</p>
            </div>

            <a class="support-box" href="#" onclick="alert('Contact your administrator for assistance.'); return false;">
              <div class="support-icon">?</div>
              <div class="support-copy">
                <strong>Need help signing in?</strong>
                <span>Contact your administrator for assistance.</span>
              </div>
              <div class="support-arrow">›</div>
            </a>
          </div>
        </div>

        <div class="login-footer">
          <div>© 2024 TimIQ. All rights reserved.</div>
          <div class="login-footer-links">
            <a href="#" onclick="return false;">Privacy Policy</a>
            <a href="#" onclick="return false;">Terms of Service</a>
            <a href="#" onclick="return false;">Need help? Contact support</a>
          </div>
        </div>
      </section>

      <script>
  (function(){{
    document.querySelectorAll("[data-password-toggle]").forEach(function(btn){{
      btn.addEventListener("click", function(){{
        var inputId = btn.getAttribute("data-password-toggle");
        var input = document.getElementById(inputId);
        if (!input) return;

        var hidden = input.type === "password";
        input.type = hidden ? "text" : "password";
        btn.classList.toggle("is-visible", hidden);
        btn.setAttribute("aria-pressed", hidden ? "true" : "false");
        btn.setAttribute("aria-label", hidden ? "Hide password" : "Show password");
      }});
    }});

    var remember = document.getElementById("remember-login");
    var username = document.getElementById("login-username");
    var workplace = document.getElementById("login-workplace");
    var form = document.querySelector(".login-form");

    try {{
      var savedRemember = localStorage.getItem("timiq_remember_login") === "1";

      if (remember && savedRemember) {{
        remember.checked = true;

        if (username && !username.value) {{
          username.value = localStorage.getItem("timiq_saved_username") || "";
        }}

        if (workplace && !workplace.value) {{
          workplace.value = localStorage.getItem("timiq_saved_workplace") || "";
        }}
      }}

      if (remember) {{
        remember.addEventListener("change", function(){{
          if (!remember.checked) {{
            localStorage.removeItem("timiq_remember_login");
            localStorage.removeItem("timiq_saved_username");
            localStorage.removeItem("timiq_saved_workplace");
          }}
        }});
      }}

      if (form && remember) {{
        form.addEventListener("submit", function(){{
          if (remember.checked) {{
            localStorage.setItem("timiq_remember_login", "1");

            if (username) {{
              localStorage.setItem("timiq_saved_username", username.value || "");
            }}

            if (workplace) {{
              localStorage.setItem("timiq_saved_workplace", workplace.value || "");
            }}
          }} else {{
            localStorage.removeItem("timiq_remember_login");
            localStorage.removeItem("timiq_saved_username");
            localStorage.removeItem("timiq_saved_workplace");
          }}
        }});
      }}
    }} catch(e) {{}}
  }})();
</script>

    </div>
    """

    return render_template_string(f"{login_viewport}{PWA_TAGS}{login_page_style}{html}")