def public_preview_impl(core):
    render_template_string = core["render_template_string"]

    return render_template_string("""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>TimIQ Workforce Management</title>
  <link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png?v=1">
  <link rel="apple-touch-icon" href="/static/icon-192.png?v=3">

  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

    :root{
      --navy:#061b3d;
      --navy2:#082b5b;
      --blue:#0b63ff;
      --blue2:#0057e7;
      --text:#07152f;
      --muted:#52627d;
      --line:#e3ebf6;
      --bg:#f5f8fd;
      --card:#fff;
      --shadow:0 18px 44px rgba(15,23,42,.10);
      --soft:0 10px 26px rgba(15,23,42,.07);
    }

    *{ box-sizing:border-box; }

    html{
      scroll-behavior:smooth;
    }

    body{
      margin:0;
      font-family:Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      color:var(--text);
      background:
        radial-gradient(900px 520px at 90% 0%, rgba(11,99,255,.12), transparent 56%),
        linear-gradient(180deg,#fbfdff 0%,#f5f8fd 100%);
    }

    a{
      color:inherit;
      text-decoration:none;
    }

    .page{
      min-height:100vh;
      overflow:hidden;
    }

    .nav{
      position:sticky;
      top:0;
      z-index:20;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:18px;
      padding:18px clamp(18px,4vw,56px);
      background:rgba(251,253,255,.82);
      backdrop-filter:blur(14px);
      -webkit-backdrop-filter:blur(14px);
      border-bottom:1px solid rgba(227,235,246,.72);
    }

    .brand{
      display:flex;
      align-items:center;
      gap:12px;
      font-weight:900;
      letter-spacing:-.03em;
      font-size:22px;
    }

    .brandLogoCustom{
  display:inline-flex;
  align-items:center;
  gap:5px;
  text-decoration:none;
  background:transparent;
  padding:0;
}

.brandClockSvg{
  width:50px;
  height:50px;
  flex:0 0 50px;
  display:block;
}

.brandWord{
  display:inline-flex;
  align-items:center;
  font-family:Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  font-size:42px;
  line-height:1;
  letter-spacing:-.075em;
  font-weight:900;
}

.brandWordTim{
  color:#06152f;
}

.brandWordIQ{
  color:#0b63ff;
}

    .navLinks{
      display:flex;
      align-items:center;
      gap:22px;
      color:#344762;
      font-size:14px;
      font-weight:800;
    }

    .navLinks a:hover{
      color:var(--blue);
    }

    .navCtas{
      display:flex;
      align-items:center;
      gap:10px;
    }

    .btn{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      min-height:44px;
      padding:0 18px;
      border-radius:12px;
      border:1px solid var(--line);
      background:#fff;
      color:#10213f;
      font-weight:900;
      box-shadow:0 10px 24px rgba(15,23,42,.06);
      white-space:nowrap;
    }

    .btn.primary{
      color:#fff;
      border:0;
      background:linear-gradient(135deg,var(--blue),var(--blue2));
      box-shadow:0 16px 34px rgba(37,99,235,.26);
    }

    .hero{
  position:relative;
  display:grid;
  grid-template-columns:minmax(400px,.8fr) minmax(620px,1.2fr);
  gap:44px;
  align-items:center;
  padding:64px clamp(18px,4vw,56px) 44px;
}

    .hero:before{
      content:"";
      position:absolute;
      inset:0;
      pointer-events:none;
      background:
        linear-gradient(rgba(11,99,255,.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(11,99,255,.045) 1px, transparent 1px);
      background-size:34px 34px;
      mask-image:linear-gradient(90deg,#000 0%,rgba(0,0,0,.72) 34%,transparent 78%);
      -webkit-mask-image:linear-gradient(90deg,#000 0%,rgba(0,0,0,.72) 34%,transparent 78%);
    }

    .heroText{
      position:relative;
      z-index:1;
    }

    .eyebrow{
      display:inline-flex;
      align-items:center;
      gap:8px;
      min-height:34px;
      padding:0 12px;
      border-radius:999px;
      background:#eaf2ff;
      color:var(--blue);
      font-size:13px;
      font-weight:900;
      margin-bottom:22px;
    }

    .hero h1{
      margin:0;
      font-size:clamp(44px,6vw,82px);
      line-height:.92;
      letter-spacing:-.07em;
      font-weight:900;
      color:#06152f;
    }

    .hero h1 span{
      color:var(--blue);
    }

    .hero p{
      margin:26px 0 0;
      max-width:560px;
      color:#40516d;
      font-size:clamp(17px,2vw,22px);
      line-height:1.45;
      font-weight:600;
    }

    .heroActions{
      display:flex;
      flex-wrap:wrap;
      gap:12px;
      margin-top:30px;
    }

    .trustRow{
      display:flex;
      flex-wrap:wrap;
      gap:10px;
      margin-top:26px;
    }

    .trustPill{
      display:inline-flex;
      align-items:center;
      gap:8px;
      padding:10px 13px;
      border-radius:999px;
      background:#fff;
      border:1px solid var(--line);
      box-shadow:0 10px 24px rgba(15,23,42,.05);
      color:#344762;
      font-size:13px;
      font-weight:800;
    }

    .mockDevice{
      position:relative;
      z-index:1;
      padding:16px;
      border-radius:28px;
      background:#fff;
      border:1px solid #dce6f4;
      box-shadow:0 28px 70px rgba(15,23,42,.16);
    }

    .mockApp{
      display:grid;
      grid-template-columns:154px minmax(0,1fr);
      min-height:620px;
      border-radius:22px;
      overflow:hidden;
      background:#f6f9fd;
      border:1px solid #edf2f8;
    }

    .mockSidebar{
      padding:22px 14px;
      background:
        radial-gradient(420px 280px at 100% 0%, rgba(37,99,235,.22), transparent 48%),
        linear-gradient(180deg,#061b3d,#082b5b);
      color:#fff;
    }

    .mockSidebarLogo{
  margin:0 0 22px;
}

.mockLogoCustom{
  display:inline-flex;
  align-items:center;
  gap:3px;
}

.mockClockSvg{
  width:22px;
  height:22px;
  flex:0 0 22px;
  display:block;
  margin-right:-1px;
}

.mockWord{
  display:inline-flex;
  align-items:center;
  font-size:22px;
  line-height:1;
  letter-spacing:-.065em;
  font-weight:900;
}

.mockWordTim{
  color:#fff;
}

.mockWordIQ{
  color:#7fc7ee;
}

    .mockMenu{
      display:flex;
      flex-direction:column;
      gap:8px;
    }

    .mockMenu div{
      display:flex;
      align-items:center;
      gap:10px;
      min-height:38px;
      padding:0 10px;
      border-radius:10px;
      color:rgba(255,255,255,.78);
      font-size:12px;
      font-weight:800;
    }

    .mockMenu div.active{
      color:#fff;
      background:linear-gradient(135deg,var(--blue),var(--blue2));
      box-shadow:0 12px 24px rgba(0,87,231,.26);
    }

    .miniIcon{
      width:15px;
      height:15px;
      display:inline-block;
      border:2px solid currentColor;
      border-radius:4px;
      opacity:.95;
    }

    .mockMain{
      padding:24px;
      background:
        radial-gradient(700px 320px at 86% 0%,rgba(11,99,255,.08),transparent 56%),
        #fbfdff;
    }

    .mockTop{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:14px;
      padding-bottom:16px;
      border-bottom:1px solid var(--line);
      margin-bottom:18px;
    }

    .mockTitle h2{
      margin:0;
      font-size:22px;
      letter-spacing:-.04em;
    }

    .mockTitle p{
      margin:5px 0 0;
      color:#64748b;
      font-size:12px;
      font-weight:700;
    }

    .mockUser{
      display:flex;
      align-items:center;
      gap:8px;
      color:#10213f;
      font-size:12px;
      font-weight:900;
    }

    .avatar{
      width:32px;
      height:32px;
      border-radius:999px;
      background:linear-gradient(135deg,var(--blue),var(--blue2));
      color:#fff;
      display:flex;
      align-items:center;
      justify-content:center;
      font-weight:900;
    }

    .metricGrid{
      display:grid;
      grid-template-columns:repeat(4,minmax(0,1fr));
      gap:12px;
      margin-bottom:16px;
    }

    .metric{
      min-height:96px;
      padding:15px;
      border-radius:14px;
      background:#fff;
      border:1px solid var(--line);
      box-shadow:var(--soft);
    }

    .metricLabel{
      color:#10213f;
      font-size:11px;
      font-weight:900;
      line-height:1.15;
    }

    .metricValue{
      margin-top:12px;
      font-size:28px;
      line-height:1;
      letter-spacing:-.04em;
      font-weight:900;
    }

    .metricSub{
      margin-top:7px;
      color:#64748b;
      font-size:10px;
      font-weight:700;
    }

    .mockTwo{
      display:grid;
      grid-template-columns:1.1fr .9fr;
      gap:14px;
      margin-bottom:14px;
    }

    .mockPanel{
      padding:16px;
      border-radius:14px;
      background:#fff;
      border:1px solid var(--line);
      box-shadow:var(--soft);
    }

    .mockPanel h3{
      margin:0;
      font-size:15px;
      font-weight:900;
      letter-spacing:-.02em;
    }

    .mockPanel p{
      margin:5px 0 12px;
      color:#64748b;
      font-size:11px;
      font-weight:700;
    }

    .fakeTable{
      display:flex;
      flex-direction:column;
      gap:10px;
      margin-top:12px;
    }

    .fakeRow{
      display:grid;
      grid-template-columns:1fr 64px 42px;
      align-items:center;
      gap:10px;
      padding-bottom:10px;
      border-bottom:1px solid #edf2f8;
      font-size:11px;
      font-weight:800;
    }

    .fakeWorker{
      display:flex;
      align-items:center;
      gap:9px;
    }

    .smallAvatar{
      width:26px;
      height:26px;
      border-radius:999px;
      background:#dbeafe;
      color:var(--blue);
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:10px;
      font-weight:900;
    }

    .progressList{
      display:flex;
      flex-direction:column;
      gap:13px;
      margin-top:15px;
    }

    .progressTop{
      display:flex;
      justify-content:space-between;
      font-size:11px;
      font-weight:900;
    }

    .track{
      height:7px;
      margin-top:6px;
      border-radius:999px;
      background:#e9eef6;
      overflow:hidden;
    }

    .track span{
      display:block;
      height:100%;
      border-radius:999px;
      background:linear-gradient(90deg,var(--blue),var(--blue2));
    }

    .onboardingMock{
      display:grid;
      grid-template-columns:auto 1fr auto;
      align-items:center;
      gap:14px;
      padding:15px;
      border-radius:14px;
      background:#fff;
      border:1px solid var(--line);
      box-shadow:var(--soft);
    }

    .docBox{
      width:54px;
      height:54px;
      border-radius:14px;
      background:#f1f6ff;
      color:var(--blue);
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:26px;
      font-weight:900;
    }

    .smallBtn{
      min-height:36px;
      padding:0 14px;
      border-radius:10px;
      background:linear-gradient(135deg,var(--blue),var(--blue2));
      color:#fff;
      font-size:11px;
      font-weight:900;
      display:flex;
      align-items:center;
      justify-content:center;
    }

    .section{
      padding:72px clamp(18px,4vw,56px);
    }

    .sectionHead{
      max-width:860px;
      margin:0 auto 34px;
      text-align:center;
    }

    .sectionHead h2{
      margin:0;
      font-size:clamp(34px,4vw,54px);
      line-height:1;
      letter-spacing:-.06em;
      font-weight:900;
    }

    .sectionHead p{
      margin:18px auto 0;
      max-width:720px;
      color:#52627d;
      font-size:18px;
      line-height:1.5;
      font-weight:600;
    }

    .featureGrid{
      display:grid;
      grid-template-columns:repeat(4,minmax(0,1fr));
      gap:18px;
      max-width:1180px;
      margin:0 auto;
    }

    .feature{
      padding:22px;
      border-radius:18px;
      background:#fff;
      border:1px solid var(--line);
      box-shadow:var(--soft);
    }

    .featureIcon{
      width:46px;
      height:46px;
      border-radius:13px;
      background:#eaf2ff;
      color:var(--blue);
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:22px;
      font-weight:900;
      margin-bottom:18px;
    }

    .feature h3{
      margin:0;
      font-size:17px;
      font-weight:900;
      letter-spacing:-.02em;
    }

    .feature p{
      margin:9px 0 0;
      color:#64748b;
      line-height:1.45;
      font-size:14px;
      font-weight:600;
    }

    .screens{
      max-width:1180px;
      margin:0 auto;
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:22px;
    }

    .screenCard{
      min-height:360px;
      border-radius:22px;
      background:#fff;
      border:1px solid var(--line);
      box-shadow:var(--shadow);
      overflow:hidden;
    }

    .screenTop{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      padding:18px 20px;
      border-bottom:1px solid var(--line);
    }

    .screenTop h3{
      margin:0;
      font-size:19px;
      font-weight:900;
      letter-spacing:-.03em;
    }

    .screenPill{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      min-height:28px;
      padding:0 10px;
      border-radius:999px;
      background:#f1f6ff;
      color:var(--blue);
      font-size:12px;
      font-weight:900;
    }

    .screenBody{
      padding:20px;
    }

    .formMock{
      display:grid;
      grid-template-columns:1fr 1fr;
      gap:12px;
    }

    .inputMock{
      height:48px;
      border-radius:10px;
      border:1px solid #dce6f4;
      background:linear-gradient(90deg,#f8fbff,#fff);
    }

    .mapMock{
      height:170px;
      border-radius:16px;
      background:
        linear-gradient(45deg, rgba(11,99,255,.08) 25%, transparent 25%, transparent 75%, rgba(11,99,255,.08) 75%),
        linear-gradient(45deg, rgba(11,99,255,.08) 25%, transparent 25%, transparent 75%, rgba(11,99,255,.08) 75%),
        #eff6ff;
      background-position:0 0, 18px 18px;
      background-size:36px 36px;
      border:1px solid #dce6f4;
      position:relative;
    }

    .mapPin{
      position:absolute;
      left:48%;
      top:42%;
      width:28px;
      height:28px;
      border-radius:999px 999px 999px 0;
      transform:rotate(-45deg);
      background:var(--blue);
      box-shadow:0 8px 16px rgba(37,99,235,.26);
    }

    .photoGrid{
      display:grid;
      grid-template-columns:repeat(3,1fr);
      gap:12px;
    }

    .photoMock{
      height:108px;
      border-radius:14px;
      border:1px solid #dce6f4;
      background:
        linear-gradient(135deg, rgba(6,27,61,.12), rgba(11,99,255,.08)),
        repeating-linear-gradient(90deg, #f1f5f9 0 12px, #e2e8f0 12px 24px);
      position:relative;
      overflow:hidden;
    }

    .photoMock:after{
      content:"Site photo";
      position:absolute;
      left:10px;
      bottom:10px;
      min-height:24px;
      padding:0 8px;
      display:flex;
      align-items:center;
      border-radius:999px;
      background:rgba(255,255,255,.88);
      color:#344762;
      font-size:11px;
      font-weight:900;
    }

    .pricing{
      max-width:1020px;
      margin:0 auto;
      display:grid;
      grid-template-columns:.85fr 1.15fr;
      gap:22px;
      align-items:stretch;
    }

    .priceCard{
      border-radius:24px;
      padding:30px;
      color:#fff;
      background:
        radial-gradient(500px 260px at 100% 0%, rgba(255,255,255,.18), transparent 56%),
        linear-gradient(135deg,#073b91,#0057e7);
      box-shadow:0 22px 60px rgba(0,87,231,.24);
    }

    .priceCard h3{
      margin:0;
      font-size:26px;
      font-weight:900;
      letter-spacing:.02em;
      text-transform:uppercase;
    }

    .price{
      margin-top:22px;
      display:flex;
      align-items:flex-end;
      gap:10px;
    }

    .price strong{
  font-size:58px;
  line-height:.92;
  letter-spacing:-.06em;
  font-weight:900;
}

    .price span{
      font-size:22px;
      font-weight:700;
      opacity:.9;
    }
    
    .priceIntro{
  margin:18px 0 0;
  color:rgba(255,255,255,.86);
  font-size:17px;
  line-height:1.45;
  font-weight:700;
}

    .priceList{
      margin-top:26px;
      display:flex;
      flex-direction:column;
      gap:14px;
    }

    .priceItem{
      display:flex;
      align-items:center;
      gap:12px;
      padding-top:14px;
      border-top:1px solid rgba(255,255,255,.22);
      font-weight:800;
      line-height:1.3;
    }

    .priceDot{
      width:38px;
      height:38px;
      border-radius:999px;
      display:flex;
      align-items:center;
      justify-content:center;
      background:#fff;
      color:var(--blue);
      font-weight:900;
      flex:0 0 auto;
    }

    .ctaCard{
      border-radius:24px;
      padding:32px;
      background:#fff;
      border:1px solid var(--line);
      box-shadow:var(--shadow);
      display:flex;
      flex-direction:column;
      justify-content:center;
    }

    .ctaCard h2{
      margin:0;
      font-size:44px;
      line-height:1;
      letter-spacing:-.06em;
      font-weight:900;
    }

    .ctaCard p{
      margin:18px 0 0;
      color:#52627d;
      font-size:18px;
      line-height:1.5;
      font-weight:600;
    }

    .footer{
      padding:34px clamp(18px,4vw,56px);
      background:#061b3d;
      color:#dbeafe;
    }

    .footerInner{
      max-width:1180px;
      margin:0 auto;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:20px;
      flex-wrap:wrap;
    }

    .footer strong{
      color:#fff;
    }

    .safeNote{
      margin-top:18px;
      padding:14px 16px;
      border-radius:16px;
      background:#f8fbff;
      border:1px solid var(--line);
      color:#52627d;
      font-size:13px;
      line-height:1.45;
      font-weight:700;
    }

    @media (max-width:1100px){
      .hero{
        grid-template-columns:1fr;
      }

      .mockDevice{
        max-width:760px;
        margin:0 auto;
      }

      .featureGrid{
        grid-template-columns:repeat(2,minmax(0,1fr));
      }

      .screens{
        grid-template-columns:1fr;
      }

      .pricing{
        grid-template-columns:1fr;
      }
    }

    @media (max-width:720px){
      .nav{
        align-items:flex-start;
      }

      .navLinks{
        display:none;
      }

      .brandLogoCustom{
  gap:8px;
}

.brandClockSvg{
  width:38px;
  height:38px;
  flex-basis:38px;
}

.brandWord{
  font-size:34px;
}

      .hero{
        padding-top:44px;
      }

      .mockApp{
  display:grid;
  grid-template-columns:170px minmax(0,1fr);

      .mockSidebar{
  padding:26px 18px;

      .metricGrid{
        grid-template-columns:repeat(2,minmax(0,1fr));
      }

      .mockTwo{
        grid-template-columns:1fr;
      }

      .featureGrid{
        grid-template-columns:1fr;
      }

      .photoGrid{
        grid-template-columns:1fr 1fr;
      }

      .formMock{
        grid-template-columns:1fr;
      }

      .onboardingMock{
        grid-template-columns:1fr;
      }

      .price strong{
        font-size:58px;
      }

      .ctaCard h2{
        font-size:36px;
      }
    }
  </style>
</head>

<body>
  <div class="page">

    <header class="nav">
      <a class="brand brandLogoCustom" href="/preview" aria-label="TimIQ preview">
  <svg class="brandClockSvg" viewBox="0 0 64 64" fill="none" aria-hidden="true">
    <path d="M7 25H26" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
    <path d="M10 34H24" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
    <path d="M16 43H22" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>

    <rect x="31" y="8" width="11" height="6" rx="2" fill="#7FC7EE"/>
    <rect x="47.5" y="14" width="6" height="6" rx="1.5" transform="rotate(45 47.5 14)" fill="#7FC7EE"/>

    <circle cx="36" cy="32" r="18" stroke="#7FC7EE" stroke-width="5.5"/>
    <path d="M36 32V18A14 14 0 0 1 50 32H36Z" fill="#4B83C6"/>
  </svg>

  <span class="brandWord">
    <span class="brandWordTim">Tim</span><span class="brandWordIQ">IQ</span>
  </span>
</a>

      <nav class="navLinks">
        <a href="#features">Features</a>
        <a href="#inside">Inside the app</a>
        <a href="#pricing">Launch offer</a>
      </nav>

      <div class="navCtas">
        <a class="btn" href="/login">Login</a>
        <a class="btn primary" href="#pricing">View offer</a>
      </div>
    </header>

    <section class="hero">
      <div class="heroText">
        <div class="eyebrow">Built for construction teams</div>
        <h1>Workforce management made <span>simple</span></h1>
        <p>
          TimIQ helps construction companies manage clock-ins, timesheets,
          onboarding documents, payroll support and work progress from one clean system.
        </p>

        <div class="heroActions">
          <a class="btn primary" href="#inside">See inside the app</a>
          <a class="btn" href="/login">Open login</a>
        </div>

        <div class="trustRow">
          <div class="trustPill">Secure data handling</div>
          <div class="trustPill">UK construction focused</div>
          <div class="trustPill">Mobile friendly</div>
        </div>

        <div class="safeNote">
          This preview uses generic demonstration data only. No real employee names,
          documents, payroll details, worksite photos or personal information are shown.
        </div>
      </div>

      <div class="mockDevice" aria-label="TimIQ app preview mockup">
        <div class="mockApp">
          <aside class="mockSidebar">
            <div class="mockSidebarLogo mockLogoCustom" aria-label="TimIQ">
  <svg class="mockClockSvg" viewBox="0 0 64 64" fill="none" aria-hidden="true">
    <path d="M7 25H26" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
    <path d="M10 34H24" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>
    <path d="M16 43H22" stroke="#7FC7EE" stroke-width="5.5" stroke-linecap="round"/>

    <rect x="31" y="8" width="11" height="6" rx="2" fill="#7FC7EE"/>
    <rect x="47.5" y="14" width="6" height="6" rx="1.5" transform="rotate(45 47.5 14)" fill="#7FC7EE"/>

    <circle cx="36" cy="32" r="18" stroke="#7FC7EE" stroke-width="5.5"/>
    <path d="M36 32V18A14 14 0 0 1 50 32H36Z" fill="#4B83C6"/>
  </svg>

  <span class="mockWord">
    <span class="mockWordTim">Tim</span><span class="mockWordIQ">IQ</span>
  </span>
</div>
            <div class="mockMenu">
              <div class="active"><span class="miniIcon"></span> Dashboard</div>
              <div><span class="miniIcon"></span> Clock In & Out</div>
              <div><span class="miniIcon"></span> Timesheets</div>
              <div><span class="miniIcon"></span> Payroll</div>
              <div><span class="miniIcon"></span> Documents</div>
              <div><span class="miniIcon"></span> Work Progress</div>
              <div><span class="miniIcon"></span> Settings</div>
            </div>
          </aside>

          <main class="mockMain">
            <div class="mockTop">
              <div class="mockTitle">
                <h2>Dashboard</h2>
                <p>Live workforce overview</p>
              </div>
              <div class="mockUser">
                <div class="avatar">AA</div>
                Admin
              </div>
            </div>

            <div class="metricGrid">
              <div class="metric">
                <div class="metricLabel">Active Workers</div>
                <div class="metricValue">28</div>
                <div class="metricSub">On site today</div>
              </div>
              <div class="metric">
                <div class="metricLabel">Hours This Week</div>
                <div class="metricValue">624</div>
                <div class="metricSub">Total hours</div>
              </div>
              <div class="metric">
                <div class="metricLabel">Sites</div>
                <div class="metricValue">7</div>
                <div class="metricSub">Active workplaces</div>
              </div>
              <div class="metric">
                <div class="metricLabel">Forms</div>
                <div class="metricValue">12</div>
                <div class="metricSub">Pending</div>
              </div>
            </div>

            <div class="mockTwo">
              <div class="mockPanel">
                <h3>Recent Timesheets</h3>
                <p>Generic example rows</p>
                <div class="fakeTable">
                  <div class="fakeRow">
                    <div class="fakeWorker"><span class="smallAvatar">JW</span> Worker A</div>
                    <div>Site 1</div>
                    <div>8.0</div>
                  </div>
                  <div class="fakeRow">
                    <div class="fakeWorker"><span class="smallAvatar">SC</span> Worker B</div>
                    <div>Site 2</div>
                    <div>7.5</div>
                  </div>
                  <div class="fakeRow">
                    <div class="fakeWorker"><span class="smallAvatar">MB</span> Worker C</div>
                    <div>Site 3</div>
                    <div>8.0</div>
                  </div>
                </div>
              </div>

              <div class="mockPanel">
                <h3>Work Progress</h3>
                <p>Project overview</p>
                <div class="progressList">
                  <div>
                    <div class="progressTop"><span>Riverside Project</span><span>75%</span></div>
                    <div class="track"><span style="width:75%"></span></div>
                  </div>
                  <div>
                    <div class="progressTop"><span>Mill Lane Site</span><span>40%</span></div>
                    <div class="track"><span style="width:40%"></span></div>
                  </div>
                  <div>
                    <div class="progressTop"><span>City Centre Build</span><span>60%</span></div>
                    <div class="track"><span style="width:60%"></span></div>
                  </div>
                </div>
              </div>
            </div>

            <div class="onboardingMock">
              <div class="docBox">▤</div>
              <div>
                <strong>Onboarding</strong>
                <p style="margin:5px 0 0;color:#64748b;font-size:11px;font-weight:700;">
                  New starters complete forms and upload required documents.
                </p>
              </div>
              <a class="smallBtn" href="#inside">View</a>
            </div>
          </main>
        </div>
      </div>
    </section>

    <section class="section" id="features">
      <div class="sectionHead">
        <h2>Everything in one place</h2>
        <p>
          Replace scattered messages, paper timesheets and manual chasing with
          one simple workforce system.
        </p>
      </div>

      <div class="featureGrid">
        <div class="feature">
          <div class="featureIcon">◷</div>
          <h3>Clock In & Out</h3>
          <p>Selfie and site checks help keep attendance records organised.</p>
        </div>

        <div class="feature">
          <div class="featureIcon">£</div>
          <h3>Payroll Support</h3>
          <p>Track hours, gross pay, deductions and paid status more clearly.</p>
        </div>

        <div class="feature">
          <div class="featureIcon">▤</div>
          <h3>Starter Forms</h3>
          <p>Collect onboarding information and required documents digitally.</p>
        </div>

        <div class="feature">
          <div class="featureIcon">▥</div>
          <h3>Timesheets</h3>
          <p>Weekly views help workers and admins understand hours worked.</p>
        </div>

        <div class="feature">
          <div class="featureIcon">▧</div>
          <h3>Work Progress</h3>
          <p>Upload site progress photos and keep a simple project record.</p>
        </div>

        <div class="feature">
          <div class="featureIcon">◫</div>
          <h3>Admin Dashboard</h3>
          <p>Manage employees, workplaces, onboarding and admin controls.</p>
        </div>

        <div class="feature">
          <div class="featureIcon">⌂</div>
          <h3>Workplaces</h3>
          <p>Support multiple company locations and workforce groups.</p>
        </div>

        <div class="feature">
          <div class="featureIcon">✓</div>
          <h3>Secure Handling</h3>
          <p>Designed with controlled access and safer data handling in mind.</p>
        </div>
      </div>
    </section>

    <section class="section" id="inside">
      <div class="sectionHead">
        <h2>See the app experience</h2>
        <p>
          These are generic preview screens based on the real TimIQ interface.
          Personal data and real worksite photos are not displayed.
        </p>
      </div>

      <div class="screens">
        <div class="screenCard">
          <div class="screenTop">
            <h3>Clock In & Out</h3>
            <span class="screenPill">Selfie + site check</span>
          </div>
          <div class="screenBody">
            <div style="text-align:center;padding:22px;border-radius:18px;background:#f8fbff;border:1px solid #e3ebf6;">
              <div style="font-size:40px;margin-bottom:12px;">📷</div>
              <strong>Take a selfie to continue</strong>
              <p style="color:#64748b;font-weight:700;">Location and site access can be checked before clock-in.</p>
              <div class="mapMock"><span class="mapPin"></span></div>
            </div>
          </div>
        </div>

        <div class="screenCard">
          <div class="screenTop">
            <h3>Timesheets & Payments</h3>
            <span class="screenPill">Generic values</span>
          </div>
          <div class="screenBody">
            <div class="fakeTable">
              <div class="fakeRow"><div>Week 17</div><div>40 hrs</div><div>View</div></div>
              <div class="fakeRow"><div>Week 16</div><div>38 hrs</div><div>View</div></div>
              <div class="fakeRow"><div>Week 15</div><div>42 hrs</div><div>View</div></div>
              <div class="fakeRow"><div>Week 14</div><div>36 hrs</div><div>View</div></div>
            </div>
            <div style="margin-top:18px;padding:18px;border-radius:16px;background:#f8fbff;border:1px solid #e3ebf6;">
              <strong>Payroll support</strong>
              <p style="margin:6px 0 0;color:#64748b;font-weight:700;">Gross, deductions and take-home style summaries.</p>
            </div>
          </div>
        </div>

        <div class="screenCard">
          <div class="screenTop">
            <h3>Onboarding</h3>
            <span class="screenPill">Document upload</span>
          </div>
          <div class="screenBody">
            <div class="formMock">
              <div class="inputMock"></div>
              <div class="inputMock"></div>
              <div class="inputMock"></div>
              <div class="inputMock"></div>
              <div class="inputMock"></div>
              <div class="inputMock"></div>
            </div>
            <div style="margin-top:16px;padding:18px;border-radius:16px;background:#f8fbff;border:1px solid #e3ebf6;">
              <strong>Starter form preview</strong>
              <p style="margin:6px 0 0;color:#64748b;font-weight:700;">Collect key worker details without showing real data publicly.</p>
            </div>
          </div>
        </div>

        <div class="screenCard">
          <div class="screenTop">
            <h3>Work Progress</h3>
            <span class="screenPill">Photos hidden</span>
          </div>
          <div class="screenBody">
            <div class="photoGrid">
              <div class="photoMock"></div>
              <div class="photoMock"></div>
              <div class="photoMock"></div>
              <div class="photoMock"></div>
              <div class="photoMock"></div>
              <div class="photoMock"></div>
            </div>
            <div class="safeNote">
              Public preview uses generic photo placeholders instead of real site images.
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="section" id="pricing">
      <div class="pricing">
        <div class="priceCard">
          <h3>Early Access Offer</h3>
<div class="price">
  <strong>From £99</strong>
  <span>/ month</span>
</div>
<p class="priceIntro">
  Simple launch pricing for small construction teams.
</p>

          <div class="priceList">
            <div class="priceItem">
  <span class="priceDot">✓</span>
  <span>Up to 20 active workers included</span>
</div>
<div class="priceItem">
  <span class="priceDot">✓</span>
  <span>Clock-in, timesheets, onboarding and payroll support</span>
</div>
<div class="priceItem">
  <span class="priceDot">✓</span>
  <span>Work progress photos and admin dashboard included</span>
</div>
<div class="priceItem">
  <span class="priceDot">+</span>
  <span>Extra active workers from £3/month</span>
</div>
<div class="priceItem">
  <span class="priceDot">★</span>
  <span>Free setup for the first 3 companies</span>
</div>
          </div>
        </div>

        <div class="ctaCard">
          <h2>Book a free demo</h2>
<p>
  See how TimIQ can help your company manage workers, clock-ins,
  onboarding, timesheets, payroll support and site progress photos.
</p>

          <div class="heroActions">
            <a class="btn primary" href="mailto:hello@timiq.co.uk?subject=TimIQ%20demo%20request">Request a demo</a>
            <a class="btn" href="/login">Existing customer login</a>
          </div>

          
        </div>
      </div>
    </section>

    <footer class="footer">
      <div class="footerInner">
        <div><strong>TimIQ</strong> — Workforce management made simple.</div>
        <div>Secure data handling • Built for construction • Mobile friendly</div>
      </div>
    </footer>

  </div>
</body>
</html>
    """)