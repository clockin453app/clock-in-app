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
        remember_me = request.form.get("remember") == "1"
        ip = _client_ip()

        login_usernames = [username]
        if username.lower() == "masteradmin":
            login_usernames = ["masteradmin", "master_admin"]
        elif username.lower() == "master_admin":
            login_usernames = ["master_admin", "masteradmin"]

        allowed, retry_after = _login_rate_limit_check(ip)
        if not allowed:
            log_audit("LOGIN_LOCKED", actor=ip, username=username, date_str="", details=f"RetryAfter={retry_after}s")
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
                        log_audit("LOGIN_INACTIVE", actor=ip, username=matched_global_username, date_str="", details="Inactive global master admin login attempt")
                        msg = "Invalid login"
                    else:
                        _login_rate_limit_clear(ip)
                        active_session_token = _issue_global_master_admin_session_token(matched_global_username)
                        if not active_session_token:
                            log_audit("LOGIN_SESSION_FAIL", actor=ip, username=matched_global_username, date_str="", details="Could not start global master admin session")
                            msg = "Could not start secure session. Please try again."
                        else:
                            selected_workplace = workplace_id or (session.get("workplace_id") or "").strip() or "default"
                            session.clear()
                            session.permanent = remember_me
                            session["remember_me"] = remember_me
                            session["csrf"] = csrf
                            session["username"] = matched_global_username
                            session["workplace_id"] = selected_workplace
                            session["role"] = "master_admin"
                            session["auth_scope"] = "global_master_admin"
                            session["rate"] = 0.0
                            session["early_access"] = True
                            session["active_session_token"] = active_session_token
                            log_audit("LOGIN_OK", actor=ip, username=matched_global_username, date_str="", details=f"global master admin workplace={selected_workplace}")
                            return redirect(url_for("home"))
                else:
                    _login_rate_limit_hit(ip)
                    log_audit("LOGIN_FAIL", actor=ip, username=username, date_str="", details="Invalid global master admin username or password")
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
                            log_audit("LOGIN_INACTIVE", actor=ip, username=username, date_str="", details="Inactive account login attempt")
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
                                log_audit("LOGIN_SESSION_FAIL", actor=ip, username=matched_username, date_str="", details=f"Could not start active session workplace={workplace_id}")
                                msg = "Could not start secure session. Please try again."
                            else:
                                session.clear()
                                session.permanent = remember_me
                                session["remember_me"] = remember_me
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
                        log_audit("LOGIN_FAIL", actor=ip, username=username, date_str="", details="Invalid username or password")
                        msg = "Invalid login"

    try:
        company_name = (get_company_settings().get("Company_Name") or "").strip() or "TimIQ"
    except Exception:
        company_name = "TimIQ"

    entered_username = (request.form.get("username", "") or "").strip() if request.method == "POST" else ""
    entered_workplace_id = (request.form.get("workplace_id", "") or "").strip() if request.method == "POST" else ""

    login_page_style = """
    <style>
      :root{
        --login-navy:#061a4d;
        --login-blue:#0b63ff;
        --login-blue2:#1586ff;
        --login-cyan:#77cdf8;
        --login-text:#091946;
        --login-muted:#6e7f9e;
        --login-line:#dce6f3;
        --login-soft:#f3f8fe;
      }

      *{box-sizing:border-box;}
      html,body{margin:0;width:100%;min-height:100%;overflow-x:hidden;}
      body{
        font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
        color:var(--login-text);
        background:#f5f9fd;
        -webkit-font-smoothing:antialiased;
        -moz-osx-font-smoothing:grayscale;
      }

      .authShell{
        min-height:100vh;
        width:100%;
        display:grid;
        grid-template-columns:minmax(520px,48%) minmax(620px,52%);
        background:
          radial-gradient(780px 360px at 91% 2%,rgba(153,215,247,.25),transparent 62%),
          linear-gradient(180deg,#fbfdff 0%,#f4f8fc 100%);
      }

      .authHero{
        position:relative;
        overflow:hidden;
        min-height:100vh;
        padding:76px 72px 56px;
        color:#fff;
        background:
          radial-gradient(900px 540px at 78% 72%,rgba(36,142,255,.44),transparent 55%),
          radial-gradient(520px 300px at 42% 50%,rgba(25,97,210,.35),transparent 65%),
          linear-gradient(135deg,#07194a 0%,#0a2c83 58%,#0a41bc 100%);
      }
      .authHero::before{
        content:"";
        position:absolute;
        inset:0;
        background:
          linear-gradient(105deg,rgba(255,255,255,.045),transparent 38%),
          radial-gradient(circle at 50% 84%,rgba(99,192,255,.18),transparent 22%);
        pointer-events:none;
      }
      .authHero::after{
        content:"";
        position:absolute;
        width:92%;height:74%;right:-28%;top:10%;
        border-radius:50%;
        border:1px solid rgba(126,211,255,.23);
        transform:rotate(-16deg);
        pointer-events:none;
      }
      .authDots{
        position:absolute;right:86px;top:100px;width:118px;height:72px;opacity:.22;
        background-image:radial-gradient(rgba(113,203,255,.9) 1.4px,transparent 1.4px);
        background-size:15px 15px;
      }
      .authCurve{position:absolute;inset:auto -7% 0 0;height:86%;pointer-events:none;opacity:.22;}
      .authCurve svg{width:100%;height:100%;display:block;}

      .brand{position:relative;z-index:3;display:inline-flex;align-items:center;gap:13px;}
      .brandIcon{width:43px;height:43px;flex:0 0 43px;display:block;}
      .brandWord{font-size:42px;line-height:1;font-weight:900;letter-spacing:-.07em;}
      .brandWord .tim{color:#fff}.brandWord .iq{color:#83d6ff;}

      .heroText{position:relative;z-index:3;margin-top:100px;max-width:500px;}
      .authHero .heroText h1{
        margin:0;
        color:#ffffff !important;
        -webkit-text-fill-color:#ffffff !important;
        background:none !important;
        background-image:none !important;
        font-size:62px;
        line-height:.98;
        letter-spacing:-.055em;
        font-weight:900;
        text-shadow:none !important;
      }
      .authHero .heroText h1 *{
        color:#ffffff !important;
        -webkit-text-fill-color:#ffffff !important;
        background:none !important;
        background-image:none !important;
        text-shadow:none !important;
      }
      .authHero .heroText h1 .accent{
        color:#7fd2fb !important;
        -webkit-text-fill-color:#7fd2fb !important;
      }
      .heroRule{width:58px;height:3px;border-radius:999px;background:#74cef9;margin:32px 0 28px;}
      .heroText p{margin:0;max-width:420px;color:rgba(255,255,255,.92);font-size:18px;line-height:1.58;font-weight:500;}

      .heroFeatures{position:relative;z-index:3;display:grid;gap:28px;margin-top:58px;max-width:405px;}
      .heroFeature{display:grid;grid-template-columns:56px 1fr;gap:18px;align-items:center;}
      .heroFeatureIcon{width:56px;height:56px;border-radius:999px;border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.11);display:flex;align-items:center;justify-content:center;box-shadow:inset 0 0 0 1px rgba(255,255,255,.04);}
      .heroFeatureIcon svg{width:25px;height:25px;stroke:#fff;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}
      .heroFeature strong{display:block;color:#fff;font-size:17px;line-height:1.25;font-weight:850;margin-bottom:4px;}
      .heroFeature span{display:block;color:rgba(255,255,255,.88);font-size:15px;line-height:1.45;font-weight:500;}

      .constructionArt{position:absolute;left:0;right:0;bottom:0;height:57%;z-index:1;pointer-events:none;opacity:.98;}
      .constructionArt svg{width:100%;height:100%;display:block;}

      .authMain{position:relative;min-height:100vh;display:flex;flex-direction:column;padding:54px 70px 32px;background:
        radial-gradient(620px 260px at 98% 0%,rgba(149,219,255,.22),transparent 62%),
        linear-gradient(180deg,#fbfdff 0%,#f5f9fd 100%);
      }
      .mainCenter{flex:1;display:flex;align-items:center;justify-content:center;}
      .loginCard{width:min(100%,555px);background:#fff;border:1px solid #dfe8f4;border-radius:18px;box-shadow:0 28px 70px rgba(10,25,70,.10);padding:52px 48px 42px;}
      .loginTitle{margin:0;color:#0d1d46;font-size:40px;line-height:1.05;font-weight:900;letter-spacing:-.045em;}
      .loginSubtitle{margin:12px 0 31px;color:#7d8daa;font-size:15px;line-height:1.5;font-weight:500;}
      .loginForm{display:grid;gap:18px;}
      .fieldLabel{display:block;margin:0 0 9px;color:#10214d;font-size:14px;font-weight:850;}
      .inputWrap{position:relative;}
      .inputIcon{position:absolute;left:18px;top:50%;transform:translateY(-50%);width:20px;height:20px;color:#a7b5cb;display:flex;align-items:center;justify-content:center;pointer-events:none;}
      .inputIcon svg,.eyeButton svg,.secureTitle svg{width:20px;height:20px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}
      .loginInput{width:100%;height:54px;border:1px solid #d9e3f1;border-radius:11px;background:#fff;color:#0d1d46;font-size:14px;font-weight:600;padding:0 16px 0 48px;outline:none;box-shadow:0 8px 20px rgba(15,23,42,.025);}
      .loginInput::placeholder{color:#95a3bb;font-weight:500;}
      .loginInput:focus{border-color:#9dc3ff;box-shadow:0 0 0 4px rgba(11,99,255,.075);}
      .passwordInput{padding-right:58px;}
      .eyeButton{position:absolute;right:9px;top:50%;transform:translateY(-50%);width:39px;height:39px;border-radius:11px;border:1px solid #dce6f3;background:#fff;color:#0b63ff;display:flex;align-items:center;justify-content:center;cursor:pointer;}
      .eyeButton .eyeOpen{display:none}.eyeButton.isVisible .eyeOpen{display:block}.eyeButton.isVisible .eyeClosed{display:none;}
      .fieldHint{margin-top:8px;color:#8190aa;font-size:13px;line-height:1.4;font-weight:600;}
      .mobileActions{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-top:2px;}
      .rememberLabel{display:inline-flex;align-items:center;gap:10px;color:#172653;font-size:15px;font-weight:700;}
      .rememberLabel input{width:18px;height:18px;accent-color:#0b63ff;}
      .forgotLink{font-size:15px;font-weight:800;color:#0b63ff;text-decoration:none;}
      .submitButton{width:100%;height:58px;border:0;border-radius:11px;background:linear-gradient(90deg,#167cff 0%,#0b63ff 100%);color:#fff;font-size:16px;font-weight:850;display:flex;align-items:center;justify-content:center;gap:12px;cursor:pointer;box-shadow:0 16px 32px rgba(11,99,255,.19);margin-top:2px;}
      .submitButton svg{display:none;width:22px;height:22px;stroke:#fff;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}
      .loginNote{display:flex;gap:11px;margin-top:20px;color:#7f8fa8;font-size:14px;line-height:1.55;font-weight:500;}
      .loginNote svg{width:18px;height:18px;flex:0 0 18px;color:#a5b2c8;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;margin-top:2px;}
      .message.error{margin-top:16px;border:1px solid #ffd4d1;background:#fff2f1;color:#b42318;border-radius:12px;padding:12px 14px;font-weight:800;font-size:14px;}
      .secureBlock,.helpBlock{display:none;}
      .authFooter{display:flex;align-items:center;justify-content:space-between;gap:20px;color:#8d9ab1;font-size:13px;font-weight:500;}
      .footerLinks{display:flex;align-items:center;gap:20px;flex-wrap:wrap;}
      .footerLinks a{color:#7e8ca5;text-decoration:none}.footerLinks a:last-child{color:#0b63ff;font-weight:700;}

      .mobileHero{display:none;}

      @media (max-width:1180px){.authShell{grid-template-columns:47% 53%;}.authHero{padding-left:56px;padding-right:48px}.heroText h1{font-size:54px}.authMain{padding-left:42px;padding-right:42px}.loginCard{width:min(100%,520px)}}

      @media (max-width:900px){
        body{background:linear-gradient(180deg,#edf6ff 0%,#fff 52%);}
        .authShell{display:block;min-height:100vh;background:#fff;}
        .authHero{display:none;}
        .authMain{min-height:100vh;padding:0;background:linear-gradient(180deg,#edf6ff 0%,#fff 48%);}
        .mobileHero{display:block;position:relative;overflow:hidden;min-height:284px;padding:54px 28px 88px;background:linear-gradient(180deg,#eef7ff 0%,#f8fbff 100%);}
        .mobileHero::before{content:"";position:absolute;inset:0;background:radial-gradient(240px 150px at 78% 34%,rgba(16,129,255,.16),transparent 62%),linear-gradient(160deg,rgba(255,255,255,.70),transparent 54%);}
        .mobileWave{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;}
        .mobileTop{position:relative;z-index:2;display:flex;align-items:flex-start;justify-content:space-between;gap:14px;}
        .mobileBrandBlock{padding-top:16px;max-width:210px;}
        .mobileBrandBlock .brandWord{font-size:36px}.mobileBrandBlock .brandIcon{width:42px;height:42px;flex-basis:42px;}
        .mobileLead{margin:20px 0 0;color:#536681;font-size:16px;line-height:1.55;font-weight:500;}
        .shieldArt{width:160px;flex:0 0 160px;margin-right:-8px;margin-top:-4px;filter:drop-shadow(0 18px 32px rgba(0,98,255,.18));}
        .shieldArt svg{display:block;width:100%;height:auto;}
        .mainCenter{display:block;flex:0;}
        .loginCard{position:relative;z-index:3;width:calc(100% - 32px);margin:-62px auto 0;border-radius:24px;padding:32px 28px 22px;box-shadow:0 16px 38px rgba(10,25,70,.09);}
        .loginTitle{font-size:36px;letter-spacing:-.045em;}
        .loginSubtitle{font-size:16px;margin:10px 0 28px;}
        .loginForm{gap:20px;}
        .fieldLabel{display:inline-block;background:#fff;padding:0 9px;margin:0 0 -9px 72px;position:relative;z-index:2;font-size:15px;}
        .loginInput{height:64px;border-radius:15px;font-size:18px;padding-left:64px;}
        .inputIcon{left:23px;width:27px;height:27px;color:#0874ff}.inputIcon svg{width:27px;height:27px;}
        .eyeButton{right:12px;width:46px;height:46px;border-radius:14px;}.passwordInput{padding-right:68px;}
        .fieldHint{font-size:15px;margin-top:12px;}
        .mobileActions{display:flex;}
        .submitButton{height:66px;border-radius:15px;justify-content:space-between;padding:0 22px;font-size:24px;margin-top:4px;}
        .submitButton::before{content:"";width:22px;height:22px;}.submitButton svg{display:block;}
        .loginNote{display:none;}
        .secureBlock{display:block;text-align:center;margin-top:30px;}
        .secureTitle{display:grid;grid-template-columns:1fr auto 1fr;gap:15px;align-items:center;color:#182954;font-size:20px;font-weight:850;}
        .secureTitle::before,.secureTitle::after{content:"";height:1px;background:#dbe5f2;}.secureTitle span{display:inline-flex;align-items:center;gap:12px;}.secureTitle svg{color:#0874ff;}
        .secureBlock p{margin:15px auto 0;max-width:390px;color:#71819d;font-size:16px;line-height:1.55;}
        .helpBlock{display:grid;grid-template-columns:58px 1fr auto;align-items:center;gap:16px;margin-top:26px;padding:17px 20px;border:1px solid #dbe5f2;border-radius:18px;background:#fff;text-decoration:none;}
        .helpIcon{width:58px;height:58px;border-radius:999px;border:3px solid #456b9d;color:#456b9d;display:flex;align-items:center;justify-content:center;font-size:32px;font-weight:900;}.helpText strong{display:block;color:#10214d;font-size:18px;font-weight:850;line-height:1.25}.helpText span{display:block;color:#5d7191;font-size:16px;line-height:1.4;margin-top:4px}.helpArrow{font-size:34px;color:#7c8da6;line-height:1;}
        .authFooter{display:none;}
      }

      @media (max-width:520px){
        .mobileHero{min-height:258px;padding:40px 20px 82px;}
        .mobileBrandBlock{max-width:178px;padding-top:22px}.mobileBrandBlock .brandWord{font-size:32px}.mobileBrandBlock .brandIcon{width:38px;height:38px;flex-basis:38px}.mobileLead{font-size:15px;margin-top:16px;}
        .shieldArt{width:140px;flex-basis:140px;}
        .loginCard{width:calc(100% - 24px);margin-top:-54px;padding:28px 22px 22px;}
        .loginTitle{font-size:32px}.loginSubtitle{font-size:15px;margin-bottom:24px}.fieldLabel{font-size:13px;margin-left:54px}.loginInput{height:58px;font-size:16px;padding-left:54px}.inputIcon{left:18px;width:24px;height:24px}.inputIcon svg{width:24px;height:24px}.submitButton{height:60px;font-size:20px}.rememberLabel,.forgotLink{font-size:15px}.secureTitle{font-size:17px}.secureBlock p{font-size:14px}.helpText strong{font-size:16px}.helpText span{font-size:14px}.helpIcon{width:50px;height:50px;font-size:28px}.helpBlock{grid-template-columns:50px 1fr auto;padding:15px 16px;}
      }
    </style>
    """

    brand_icon_desktop = """
      <svg class=\"brandIcon\" viewBox=\"0 0 64 64\" fill=\"none\" aria-hidden=\"true\">
        <path d=\"M7 25H26\" stroke=\"#7FC7EE\" stroke-width=\"5.5\" stroke-linecap=\"round\"/>
        <path d=\"M10 34H24\" stroke=\"#7FC7EE\" stroke-width=\"5.5\" stroke-linecap=\"round\"/>
        <path d=\"M16 43H22\" stroke=\"#7FC7EE\" stroke-width=\"5.5\" stroke-linecap=\"round\"/>
        <rect x=\"31\" y=\"8\" width=\"11\" height=\"6\" rx=\"2\" fill=\"#7FC7EE\"/>
        <rect x=\"47.5\" y=\"14\" width=\"6\" height=\"6\" rx=\"1.5\" transform=\"rotate(45 47.5 14)\" fill=\"#7FC7EE\"/>
        <circle cx=\"36\" cy=\"32\" r=\"18\" stroke=\"#7FC7EE\" stroke-width=\"5.5\"/>
        <path d=\"M36 32V18A14 14 0 0 1 50 32H36Z\" fill=\"#4B83C6\"/>
      </svg>
    """

    brand_icon_mobile = """
      <svg class=\"brandIcon\" viewBox=\"0 0 64 64\" fill=\"none\" aria-hidden=\"true\">
        <path d=\"M7 25H26\" stroke=\"#0B63FF\" stroke-width=\"5.5\" stroke-linecap=\"round\"/>
        <path d=\"M10 34H24\" stroke=\"#0B63FF\" stroke-width=\"5.5\" stroke-linecap=\"round\"/>
        <path d=\"M16 43H22\" stroke=\"#0B63FF\" stroke-width=\"5.5\" stroke-linecap=\"round\"/>
        <rect x=\"31\" y=\"8\" width=\"11\" height=\"6\" rx=\"2\" fill=\"#0B63FF\"/>
        <rect x=\"47.5\" y=\"14\" width=\"6\" height=\"6\" rx=\"1.5\" transform=\"rotate(45 47.5 14)\" fill=\"#0B63FF\"/>
        <circle cx=\"36\" cy=\"32\" r=\"18\" stroke=\"#0B63FF\" stroke-width=\"5.5\"/>
        <path d=\"M36 32V18A14 14 0 0 1 50 32H36Z\" fill=\"#76CCF8\"/>
      </svg>
    """

    construction_svg = """
      <svg viewBox=\"0 0 900 560\" preserveAspectRatio=\"none\" aria-hidden=\"true\">
        <defs>
          <linearGradient id=\"lgGround\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\"><stop offset=\"0\" stop-color=\"#0b3ca9\" stop-opacity=\"0\"/><stop offset=\"1\" stop-color=\"#06163f\" stop-opacity=\".96\"/></linearGradient>
          <linearGradient id=\"lgGlass\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\"><stop offset=\"0\" stop-color=\"#91e6ff\" stop-opacity=\".40\"/><stop offset=\"1\" stop-color=\"#91e6ff\" stop-opacity=\".02\"/></linearGradient>
          <linearGradient id=\"lgLine\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"0\"><stop offset=\"0\" stop-color=\"#86dfff\" stop-opacity=\".03\"/><stop offset=\"1\" stop-color=\"#86dfff\" stop-opacity=\".45\"/></linearGradient>
        </defs>
        <path d=\"M0 560V390C108 348 220 336 338 352C480 371 585 357 720 306C800 276 850 254 900 230V560Z\" fill=\"url(#lgGround)\"/>
        <ellipse cx=\"648\" cy=\"354\" rx=\"220\" ry=\"138\" fill=\"url(#lgGlass)\" opacity=\".58\"/>
        <path d=\"M380 560C402 430 465 320 565 272C654 230 765 232 900 200\" stroke=\"url(#lgLine)\" stroke-width=\"2\" fill=\"none\"/>
        <g opacity=\".38\" fill=\"#09276d\">
          <rect x=\"95\" y=\"345\" width=\"32\" height=\"136\"/><rect x=\"155\" y=\"292\" width=\"42\" height=\"189\"/><rect x=\"222\" y=\"336\" width=\"34\" height=\"145\"/><rect x=\"287\" y=\"250\" width=\"48\" height=\"231\"/><rect x=\"350\" y=\"315\" width=\"33\" height=\"166\"/><rect x=\"412\" y=\"285\" width=\"36\" height=\"196\"/>
        </g>
        <g opacity=\".20\" fill=\"#87dfff\"><circle cx=\"196\" cy=\"432\" r=\"20\"/><rect x=\"485\" y=\"305\" width=\"24\" height=\"176\"/><rect x=\"535\" y=\"260\" width=\"25\" height=\"221\"/><rect x=\"590\" y=\"223\" width=\"24\" height=\"258\"/><rect x=\"640\" y=\"277\" width=\"26\" height=\"204\"/></g>
        <g stroke=\"#82d9ff\" stroke-width=\"3\" fill=\"none\" opacity=\".42\"><path d=\"M650 480V156\"/><path d=\"M650 156h155\"/><path d=\"M795 156l34-63\"/><path d=\"M805 156l-62 26\"/><path d=\"M744 156h96\"/><path d=\"M744 156v70\"/><path d=\"M744 226l-10 13\"/><path d=\"M744 226l11 13\"/><path d=\"M565 310h190\"/><path d=\"M588 350h165\"/><path d=\"M610 390h138\"/></g>
        <g stroke=\"#8ce4ff\" stroke-width=\"4\" fill=\"none\" opacity=\".25\"><path d=\"M545 448l112-158 88 74h-210\"/><path d=\"M582 405h198\"/><path d=\"M618 360h126\"/><path d=\"M650 290v160\"/><path d=\"M705 334v116\"/></g>
        <g opacity=\".55\" fill=\"#05194a\"><circle cx=\"612\" cy=\"468\" r=\"26\"/><path d=\"M570 560c0-52 16-85 42-98 27 13 42 46 42 98Z\"/><circle cx=\"718\" cy=\"442\" r=\"30\"/><path d=\"M660 560c0-72 22-112 58-129 38 17 60 57 60 129Z\"/></g>
        <path d=\"M0 520C185 488 340 485 495 500C670 517 785 514 900 492V560H0Z\" fill=\"#061742\" opacity=\".72\"/>
      </svg>
    """

    shield_svg = """
      <svg viewBox=\"0 0 220 190\" aria-hidden=\"true\">
        <defs>
          <radialGradient id=\"shieldGlow\" cx=\"50%\" cy=\"62%\" r=\"56%\"><stop offset=\"0\" stop-color=\"#86dfff\" stop-opacity=\".62\"/><stop offset=\"1\" stop-color=\"#86dfff\" stop-opacity=\"0\"/></radialGradient>
          <linearGradient id=\"shieldA\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\"><stop offset=\"0\" stop-color=\"#7ed9ff\"/><stop offset=\".48\" stop-color=\"#168aff\"/><stop offset=\"1\" stop-color=\"#075de7\"/></linearGradient>
          <linearGradient id=\"shieldB\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\"><stop offset=\"0\" stop-color=\"#caf4ff\"/><stop offset=\"1\" stop-color=\"#2996ff\"/></linearGradient>
        </defs>
        <ellipse cx=\"118\" cy=\"144\" rx=\"82\" ry=\"28\" fill=\"url(#shieldGlow)\"/>
        <ellipse cx=\"118\" cy=\"145\" rx=\"72\" ry=\"22\" fill=\"none\" stroke=\"#c4ecff\" stroke-width=\"2\" opacity=\".80\"/>
        <ellipse cx=\"118\" cy=\"145\" rx=\"54\" ry=\"15\" fill=\"none\" stroke=\"#d9f4ff\" stroke-width=\"2\" opacity=\".70\"/>
        <path d=\"M118 16l58 20v48c0 41-24 70-58 88-34-18-58-47-58-88V36z\" fill=\"url(#shieldA)\"/>
        <path d=\"M118 30l43 14v38c0 31-17 54-43 69-26-15-43-38-43-69V44z\" fill=\"url(#shieldB)\" opacity=\".86\"/>
        <rect x=\"94\" y=\"78\" width=\"48\" height=\"38\" rx=\"9\" fill=\"#f6fbff\"/>
        <path d=\"M103 78V67a15 15 0 0 1 30 0v11\" stroke=\"#f6fbff\" stroke-width=\"9\" stroke-linecap=\"round\"/>
        <circle cx=\"118\" cy=\"96\" r=\"5\" fill=\"#0b63ff\"/><rect x=\"116\" y=\"101\" width=\"4\" height=\"11\" rx=\"2\" fill=\"#0b63ff\"/>
      </svg>
    """

    login_viewport = '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'

    html = f"""
    <div class="authShell">
      <section class="authHero" aria-label="TimIQ login introduction">
        <div class="authDots"></div>
        <div class="authCurve"><svg viewBox="0 0 900 700" preserveAspectRatio="none"><path d="M60 690C60 520 142 390 306 302C468 215 552 112 678 20" stroke="#79d7ff" stroke-width="2" fill="none"/><path d="M292 700C320 538 398 430 558 360C690 302 782 230 900 128" stroke="#79d7ff" stroke-width="2" fill="none"/></svg></div>
        <div class="brand">{brand_icon_desktop}<div class="brandWord"><span class="tim">Tim</span><span class="iq">IQ</span></div></div>
        <div class="heroText">
          <h1>One workspace.<br>Every worker.<br><span class="accent">Total visibility.</span></h1>
          <div class="heroRule"></div>
          <p>TimIQ brings together clock-in, attendance and payroll in one secure platform—so your projects run on time and on budget.</p>
        </div>
        <div class="heroFeatures">
          <div class="heroFeature"><div class="heroFeatureIcon"><svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2"/><circle cx="9.5" cy="7" r="4"/><path d="M19 8v6"/><path d="M22 11h-6"/></svg></div><div><strong>Workforce in sync</strong><span>Accurate attendance across sites and teams.</span></div></div>
          <div class="heroFeature"><div class="heroFeatureIcon"><svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-5"/></svg></div><div><strong>Built for security</strong><span>Enterprise-grade protection for your data.</span></div></div>
          <div class="heroFeature"><div class="heroFeatureIcon"><svg viewBox="0 0 24 24"><path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 16v-5"/><path d="M12 16V8"/><path d="M16 16v-9"/></svg></div><div><strong>Actionable insights</strong><span>Real-time reporting that keeps projects moving.</span></div></div>
        </div>
        <div class="constructionArt">{construction_svg}</div>
      </section>

      <section class="authMain">
        <div class="mobileHero">
          <svg class="mobileWave" viewBox="0 0 430 300" preserveAspectRatio="none"><path d="M0 42C62 10 124 20 190 42C260 66 312 34 430 24V300H0Z" fill="#e6f2ff"/><path d="M0 98C86 74 150 86 220 118C284 146 350 116 430 94V300H0Z" fill="#f2f8ff"/><path d="M0 154C84 138 138 148 210 178C278 207 350 184 430 160V300H0Z" fill="#fbfdff"/></svg>
          <div class="mobileTop">
            <div class="mobileBrandBlock"><div class="brand">{brand_icon_mobile}<div class="brandWord"><span class="tim" style="color:#0b1b4c">Tim</span><span class="iq" style="color:#0b63ff">IQ</span></div></div><p class="mobileLead">Check-in, attendance and payroll in one secure workspace.</p></div>
            <div class="shieldArt">{shield_svg}</div>
          </div>
        </div>

        <div class="mainCenter">
          <div class="loginCard">
            <h1 class="loginTitle">Welcome back</h1>
            <p class="loginSubtitle">Sign in to access your TimIQ workspace.</p>

            <form method="POST" class="loginForm">
              <input type="hidden" name="csrf" value="{escape(csrf)}">

              <div>
                <label class="fieldLabel" for="login-username">Username</label>
                <div class="inputWrap"><span class="inputIcon"><svg viewBox="0 0 24 24"><path d="M20 21a8 8 0 0 0-16 0"/><circle cx="12" cy="8" r="4"/></svg></span><input id="login-username" class="loginInput" name="username" value="{escape(entered_username)}" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="Enter your username" required></div>
              </div>

              <div>
                <label class="fieldLabel" for="login-workplace">Workplace ID</label>
                <div class="inputWrap"><span class="inputIcon"><svg viewBox="0 0 24 24"><path d="M4 21h16"/><path d="M7 21V6l10-3v18"/><path d="M10 9h1"/><path d="M10 13h1"/><path d="M10 17h1"/><path d="M14 13h1"/><path d="M14 17h1"/></svg></span><input id="login-workplace" class="loginInput" name="workplace_id" value="{escape(entered_workplace_id)}" autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck="false" inputmode="text" placeholder="e.g. north01"></div>
                <div class="fieldHint">Required for workplace users.</div>
              </div>

              <div>
                <label class="fieldLabel" for="login-password">Password</label>
                <div class="inputWrap"><span class="inputIcon"><svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg></span><input id="login-password" class="loginInput passwordInput" type="password" name="password" autocomplete="current-password" placeholder="Enter your password" required><button class="eyeButton" type="button" data-password-toggle="login-password" aria-label="Show password" aria-pressed="false"><svg class="eyeOpen" viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg><svg class="eyeClosed" viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/><path d="M4 20L20 4"/></svg></button></div>
              </div>

              <div class="mobileActions"><label class="rememberLabel"><input type="checkbox" name="remember" value="1" {"checked" if request.method == "POST" and request.form.get("remember") == "1" else ""}><span>Remember me</span></label><a class="forgotLink" href="#" onclick="alert('Please contact your administrator to reset your password.'); return false;">Forgot password?</a></div>
              <button class="submitButton" type="submit"><span>Sign in</span><svg viewBox="0 0 24 24"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg></button>
            </form>

            {("<div class='message error'>" + escape(msg) + "</div>") if msg else ""}

            <div class="loginNote"><svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg><div>Use the same credentials provided by your administrator. After sign-in you can access clock-in, timesheets and payroll tools based on your role.</div></div>
            <div class="secureBlock"><div class="secureTitle"><span><svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-5"/></svg>Secure sign-in</span></div><p>Your data is protected with enterprise-grade encryption and secure authentication.</p></div>
            <a class="helpBlock" href="#" onclick="alert('Contact your administrator for assistance.'); return false;"><div class="helpIcon">?</div><div class="helpText"><strong>Need help signing in?</strong><span>Contact your administrator for assistance.</span></div><div class="helpArrow">›</div></a>
          </div>
        </div>

        <footer class="authFooter"><div>© 2024 {escape(company_name)}. All rights reserved.</div><div class="footerLinks"><a href="#" onclick="return false;">Privacy Policy</a><a href="#" onclick="return false;">Terms of Service</a><a href="#" onclick="return false;">Need help? Contact support</a></div></footer>
      </section>

      <script>
        (function(){{
          document.querySelectorAll('[data-password-toggle]').forEach(function(btn){{
            btn.addEventListener('click', function(){{
              var input = document.getElementById(btn.getAttribute('data-password-toggle'));
              if (!input) return;
              var visible = input.type === 'password';
              input.type = visible ? 'text' : 'password';
              btn.classList.toggle('isVisible', visible);
              btn.setAttribute('aria-pressed', visible ? 'true' : 'false');
              btn.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
            }});
          }});
        }})();
      </script>
    </div>
    """

    return render_template_string(f"{login_viewport}{PWA_TAGS}{login_page_style}{html}")
