VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
PWA_TAGS = """
<title>TimIQ</title>
<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png?v=1">
<link rel="icon" type="image/png" sizes="16x16" href="/static/favicon-16.png?v=1">
<link rel="apple-touch-icon" href="/static/icon-192.png?v=3">
<meta name="theme-color" content="#1f2d63">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<script>
(function(){
  function syncBottomNav(){
    var vv = window.visualViewport;
    var gap = 0;

    if (vv) {
      gap = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    }

    document.documentElement.style.setProperty('--bottom-nav-offset', gap + 'px');
  }

  function initMobileRail(){
    var shell = document.querySelector('.shell');
    var sidebar = shell ? shell.querySelector('.sidebar') : null;
    var oldBtn = document.getElementById('mobileRailToggle');

    if (window.innerWidth > 979 || !shell || !sidebar) {
      document.body.classList.remove('mobileRailClosed');
      if (oldBtn) oldBtn.remove();
      return;
    }

    var btn = oldBtn;
    if (!btn) {
      btn = document.createElement('button');
      btn.type = 'button';
      btn.id = 'mobileRailToggle';
      btn.setAttribute('aria-label', 'Toggle menu');
      document.body.appendChild(btn);
    }

    var storageKey = 'mobileRailClosed';

    function syncRail(){
      var closed = localStorage.getItem(storageKey) === '1';
      document.body.classList.toggle('mobileRailClosed', closed);
    }

    if (btn.dataset.bound !== '1') {
      btn.dataset.bound = '1';
      btn.addEventListener('click', function(e){
        e.preventDefault();
        e.stopPropagation();
        var closed = localStorage.getItem(storageKey) === '1';
        localStorage.setItem(storageKey, closed ? '0' : '1');
        syncRail();
      });
    }

    syncRail();
  }

  if (!window.__mobileRailSwipeBound) {
    window.__mobileRailSwipeBound = true;

    var touchStartX = 0;
    var touchStartY = 0;
    var touchLastX = 0;
    var trackingSwipe = false;
    var swipeMode = '';

    document.addEventListener('touchstart', function(e){
      if (window.innerWidth > 979) return;

      var shell = document.querySelector('.shell');
      var sidebar = shell ? shell.querySelector('.sidebar') : null;
      if (!shell || !sidebar) return;

      var t = e.touches && e.touches[0];
      if (!t) return;

      var target = e.target;
      if (target && target.closest('input, select, textarea, button, a, .tablewrap')) return;

      var closed = document.body.classList.contains('mobileRailClosed');

      trackingSwipe = false;
      swipeMode = '';
      touchStartX = t.clientX;
      touchStartY = t.clientY;
      touchLastX = t.clientX;

      if (closed) {
        if (t.clientX <= 18) {
          trackingSwipe = true;
          swipeMode = 'open';
        }
        return;
      }

      if (sidebar.contains(target) || t.clientX <= 90) {
        trackingSwipe = true;
        swipeMode = 'close';
      }
    }, { passive: true });

    document.addEventListener('touchmove', function(e){
      if (!trackingSwipe || window.innerWidth > 979) return;

      var t = e.touches && e.touches[0];
      if (!t) return;

      var dx = t.clientX - touchStartX;
      var dy = t.clientY - touchStartY;

      if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 8) {
        e.preventDefault();
      }

      touchLastX = t.clientX;
    }, { passive: false });

    document.addEventListener('touchend', function(){
      if (!trackingSwipe || window.innerWidth > 979) return;

      var dx = touchLastX - touchStartX;

      if (swipeMode === 'open' && dx > 45) {
        localStorage.setItem('mobileRailClosed', '0');
        document.body.classList.remove('mobileRailClosed');
      } else if (swipeMode === 'close' && dx < -45) {
        localStorage.setItem('mobileRailClosed', '1');
        document.body.classList.add('mobileRailClosed');
      }

      trackingSwipe = false;
      swipeMode = '';
      touchStartX = 0;
      touchStartY = 0;
      touchLastX = 0;
    }, { passive: true });
  }

  window.addEventListener('load', function(){
    syncBottomNav();
    initMobileRail();
  });

  window.addEventListener('resize', function(){
    syncBottomNav();
    initMobileRail();
  });

  window.addEventListener('pageshow', function(){
    syncBottomNav();
    initMobileRail();
    setTimeout(syncBottomNav, 120);
    setTimeout(syncBottomNav, 320);
  });

  window.addEventListener('orientationchange', function(){
    setTimeout(function(){
      syncBottomNav();
      initMobileRail();
    }, 250);
  });

  document.addEventListener('focusout', function(){
    setTimeout(syncBottomNav, 180);
  });

  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', syncBottomNav);
    window.visualViewport.addEventListener('scroll', syncBottomNav);
  }

  syncBottomNav();
  initMobileRail();
})();
</script>
"""
# ================= PREMIUM UI (CLEAN + STABLE) =================
STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root{
  --bg:#f7f9fc;
  --card:#ffffff;
  --text:#0f172a;
  --muted:#64748b;
  --border:rgba(15,23,42,.10);
  --shadow: 0 10px 28px rgba(15,23,42,.06);
  --shadow2: 0 16px 46px rgba(15,23,42,.10);
  --radius: 0px;

  /* Brand (finance blue) */
  --navy:#1e40af;
  --navy2:#1e3a8a;
  --navySoft:rgba(30,64,175,.08);

  --green:#16a34a;
  --red:#dc2626;
  --amber:#f59e0b;

  --h1: clamp(26px, 5vw, 38px);
  --h2: clamp(16px, 3vw, 20px);
  --small: clamp(12px, 2vw, 14px);
}

*{ box-sizing:border-box; }
html,body{ height:100%; }

body{
  margin:0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  background:
    radial-gradient(900px 520px at 18% 0%, rgba(10,42,94,.08) 0%, rgba(10,42,94,0) 60%),
    linear-gradient(180deg, rgba(255,255,255,.90), rgba(255,255,255,0) 45%),
    var(--bg);
  color: var(--text);
  padding: 16px 14px calc(90px + env(safe-area-inset-bottom)) 14px;
}

a{ color:inherit; text-decoration:none; }

h1{ font-size:var(--h1); margin:0; font-weight:700; letter-spacing:.2px; }
h2{ font-size:var(--h2); margin:0 0 8px 0; font-weight:600; }
.sub{ color:var(--muted); margin:6px 0 0 0; font-size:var(--small); line-height:1.35; font-weight:400; }

.card{
  min-width: 0;
  max-width: 100%;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 0 !important;
  box-shadow: var(--shadow);
  transition: transform .16s ease, box-shadow .16s ease, background .16s ease, border-color .16s ease;
}

/* Small badge */
.badge{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  padding:6px 12px;
  border-radius: 0 !important;
  font-size:12px;
  font-weight:800;
  letter-spacing:.02em;
  background: rgba(239,246,255,.96);
  color: var(--navy);
  border:1px solid rgba(30,64,175,.16);
  box-shadow: 0 2px 8px rgba(15,23,42,.05);
}
.badge.admin{
  background: rgba(239,246,255,.96);
  color: #1d4ed8;
  border:1px solid rgba(59,130,246,.18);
}

/* Shell */
.shell{ max-width: 560px; margin: 0 auto; }
.sidebar{ display:none; }
.main{
  width: 100%;
  min-width: 0;   /* IMPORTANT: allows wide content to scroll instead of overflowing */
}

.topBrandBadge{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-height:38px;
  padding:8px 18px;
  border-radius: 0 !important;
  font-size:13px;
  font-weight:800;
  letter-spacing:.04em;
  text-transform:uppercase;
  color:#dbeafe;
  border:1px solid rgba(147,197,253,.34);
  background:linear-gradient(180deg, rgba(29,78,216,.26), rgba(15,23,42,.78));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.12), 0 10px 24px rgba(2,6,23,.22);
  backdrop-filter:blur(10px);
  -webkit-backdrop-filter:blur(10px);
}
.topBrandBadge:hover{
  border-color:rgba(147,197,253,.42);
}

.topBarFixed{
  display:flex;
  align-items:center;
  justify-content:flex-end;
  gap:10px;
  margin-bottom:10px;
}

.mobileTopLogo{
  display:none;
  align-items:center;
  justify-content:center;
  text-decoration:none;
  margin-right:auto;
}

.mobileTopLogo img{
  width:88px;
  height:auto;
  display:block;
}


.topAccountWrap{
  position:relative;
}

.topAccountTrigger{
  width:40px;
  height:40px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  border-radius: 0 !important;
  border:1px solid rgba(68,130,195,.10);
  background:rgba(255,255,255,.92);
  color:#3b74ad;
  cursor:pointer;
  box-shadow:0 8px 18px rgba(15,23,42,.08);
}

.topAccountTrigger svg{
  width:18px;
  height:18px;
}

.topAccountMenu{
  position:absolute;
  top:calc(100% + 8px);
  right:0;
  min-width:190px;
  padding:8px;
  border-radius: 0 !important;
  border:1px solid rgba(68,130,195,.10);
  background:linear-gradient(180deg, rgba(255,255,255,.98), rgba(246,250,253,.98));
  box-shadow:0 18px 36px rgba(15,23,42,.14);
  display:none;
  z-index:700;
}

.topAccountWrap.open .topAccountMenu{
  display:block;
}

.topAccountMenuItem{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding:12px 14px;
  border-radius: 0 !important;
  text-decoration:none;
  color:#1f2547;
  font-size:14px;
  font-weight:600;
}

.topAccountMenuItem:hover{
  background:rgba(68,130,195,.06);
}

.topAccountMenuItem.danger{
  color:#dc2626;
}

.topAccountMenuMark{
  color:#8b84a8;
  font-size:16px;
  line-height:1;
}

/* Header top */
.headerTop{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:12px;
  margin-bottom:14px;
}

/* KPI cards */
.kpiRow{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 12px;
}
.kpi{ padding:14px; }
.kpi .label{ font-size:var(--small); color:var(--muted); margin:0; font-weight:400; }
.kpi .value{ font-size: 28px; font-weight:700; margin: 6px 0 0 0; font-variant-numeric: tabular-nums; }

/* Graph */
.graphCard{
  margin-top: 12px;
  padding: 18px;
  border-radius: 0 !important;
  border: 1px solid rgba(56,189,248,.14);
  background:
    linear-gradient(180deg, #06142b 0%, #0a2342 55%, #0d2f52 100%);
  box-shadow:
    0 18px 40px rgba(2,6,23,.22),
    inset 0 1px 0 rgba(255,255,255,.04);
}

.graphTop{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:12px;
}

.graphTitle{
  font-weight:800;
  font-size: 20px;
  color: #f8fafc;
}

.graphCard .sub{
  color: rgba(191,219,254,.78);
}

.graphRange{
  color: #93c5fd;
  font-size: 13px;
  font-weight:700;
}

.graphShell{
  margin-top: 14px;
  padding: 14px 14px 10px 14px;
  border-radius: 0 !important;
  border: 1px solid rgba(56,189,248,.12);
  background:
    linear-gradient(180deg, rgba(3,14,33,.72), rgba(5,23,48,.62)),
    radial-gradient(circle at top right, rgba(34,211,238,.12), transparent 38%),
    radial-gradient(circle at top left, rgba(59,130,246,.12), transparent 42%);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.05),
    inset 0 -20px 60px rgba(2,132,199,.05);
}

.bars{
  height: 240px;
  display:flex;
  align-items:flex-end;
  justify-content:space-between;
  gap: 14px;
  padding: 8px 6px 0 6px;
  position: relative;
}

.barCol{
  flex: 1 1 0;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:flex-end;
  gap:8px;
  min-width: 0;
}

.barValue{
  font-size: 12px;
  font-weight: 800;
  color: #67e8f9;
  min-height: 16px;
  white-space: nowrap;
  text-shadow: 0 0 10px rgba(34,211,238,.18);
}

.barTrack{
  width: 100%;
  height: 180px;
  display:flex;
  align-items:flex-end;
  justify-content:center;
  border-radius: 0 !important;
  background:
    linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.01)),
    linear-gradient(180deg, rgba(14,165,233,.06), rgba(14,165,233,0));
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.02);
  position: relative;
}

.bar{
  width: 72%;
  min-width: 24px;
  border-radius: 0 !important;
  background: linear-gradient(180deg, #155eef 0%, #22d3ee 100%);
  box-shadow:
    0 14px 26px rgba(8,145,178,.22),
    0 0 18px rgba(34,211,238,.10);
}

.barLabels{
  display:flex;
  justify-content:space-between;
  gap:14px;
  margin-top: 8px;
  color: rgba(191,219,254,.88);
  font-weight:700;
  font-size: 13px;
}

.barLabels div{
  flex:1 1 0;
  text-align:center;
}

.graphMeta{
  margin-top: 14px;
  display:grid;
  grid-template-columns: repeat(3, 1fr);
  gap:10px;
}

@media (max-width: 900px){
  .graphMeta{
    grid-template-columns: 1fr;
  }
}

.graphStat{
  padding: 10px 12px;
  border-radius: 0 !important;
  border: 1px solid rgba(11,18,32,.08);
  background: rgba(255,255,255,.82);
}

.graphStat .k{
  font-size: 12px;
  color: var(--muted);
  font-weight:700;
}

.graphStat .v{
  margin-top: 4px;
  font-size: 18px;
  font-weight:800;
  color: rgba(15,23,42,.95);
}

.grossChartCard{
  margin-top: 12px;
  padding: 16px;
  border-radius: 0 !important;
  border: 1px solid rgba(68,130,195,.12);
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(246,243,255,.98));
  box-shadow: 0 16px 36px rgba(15,23,42,.08);
}

.grossChartSummaryRow{
  display:grid;
  grid-template-columns: repeat(2, minmax(0,1fr));
  gap:10px;
}

.grossSummaryBox{
  min-width:0;
  padding:14px 16px;
  border-radius: 0 !important;
  border:1px solid rgba(68,130,195,.10);
  background: rgba(255,255,255,.92);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.9);
}

.grossSummaryLabel{
  font-size:12px;
  color:#6f6c85;
  font-weight:700;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}

.grossSummaryValue{
  margin-top:4px;
  font-size:18px;
  line-height:1.1;
  color:#1f2547;
  font-weight:800;
  font-variant-numeric: tabular-nums;
}

.grossSummaryDelta{
  margin-top:4px;
  font-size:12px;
  font-weight:800;
}

.grossSummaryDelta.up{ color:#15803d; }
.grossSummaryDelta.down{ color:#e11d48; }

.grossChartNav{
  margin-top:14px;
  display:flex;
  align-items:center;
  justify-content:center;
  gap:18px;
}

.grossChartArrow{
  width:24px;
  text-align:center;
  color:#5f5b7a;
  font-size:24px;
  line-height:1;
  user-select:none;
}

.grossChartRangeTitle{
  color:#1f172f;
  font-size:18px;
  font-weight:800;
  letter-spacing:-.01em;
}

.grossChartPlot{
  margin-top:10px;
  display:grid;
  grid-template-columns: 48px minmax(0,1fr);
  gap:10px;
  align-items:end;
}

.grossChartYAxis{
  height:230px;
  display:grid;
  grid-template-rows: repeat(6, 1fr);
}

.grossChartTick{
  display:flex;
  align-items:flex-end;
  justify-content:flex-end;
  padding-right:2px;
  color:#6b6f88;
  font-size:11px;
  font-weight:700;
  font-variant-numeric: tabular-nums;
}

.grossChartCanvas{
  position:relative;
  height:230px;
  border-bottom:1px solid rgba(68,130,195,.16);
}

.grossChartGridLine{
  position:absolute;
  left:0;
  right:0;
  border-top:1px dashed rgba(68,130,195,.18);
}

.grossChartBars{
  position:absolute;
  inset:0;
  display:flex;
  align-items:flex-end;
  justify-content:space-around;
  gap:12px;
  padding:0 8px 0 8px;
}

.grossChartBarCol{
  flex:1 1 0;
  min-width:0;
  height:100%;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:flex-end;
}

.grossChartBarWrap{
  width:min(52px, 100%);
  height:100%;
  display:flex;
  align-items:flex-end;
  justify-content:center;
}

.grossChartBar{
  width:100%;
  max-width:52px;
  background:#000;
  border-radius: 0 !important;
}

.grossChartBarLabel{
  margin-top:8px;
  color:#656b86;
  font-size:12px;
  font-weight:800;
}

@media (max-width: 700px){
  .grossChartCard{
    padding: 14px 12px 12px;
  }

  .grossSummaryBox{
    padding:12px 14px;
  }

  .grossSummaryLabel{
    font-size:11px;
  }

  .grossSummaryValue{
    font-size:16px;
  }

  .grossChartNav{
    gap:14px;
  }

  .grossChartRangeTitle{
    font-size:16px;
  }

  .grossChartPlot{
    grid-template-columns: 40px minmax(0,1fr);
    gap:8px;
  }

  .grossChartYAxis,
  .grossChartCanvas{
    height:200px;
  }

  .grossChartBars{
    gap:10px;
    padding:0 2px;
  }

  .grossChartBarWrap{
    width:min(38px, 100%);
  }

  .grossChartBar{
    max-width:38px;
  }

  .grossChartBarLabel{
    font-size:11px;
  }
}

.dashboardLower{
  margin-top: 12px;
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}

@media (max-width: 1100px){
  .dashboardLower{
    grid-template-columns: 1fr;
  }
}

.quickCard,
.activityCard,
.sideInfoCard{
  padding: 14px;
}

.quickCard{
  background:
    linear-gradient(180deg, rgba(239,246,255,.96), rgba(255,255,255,.96));
  border: 1px solid rgba(59,130,246,.14);
}

.activityCard{
  background:
    linear-gradient(180deg, rgba(242,247,251,.96), rgba(255,255,255,.96));
  border: 1px solid rgba(68,130,195,.14);
}

.sideInfoCard{
  background:
    linear-gradient(180deg, rgba(236,253,245,.96), rgba(255,255,255,.96));
  border: 1px solid rgba(34,197,94,.14);
}

.quickCard h2{
  color: #1d4ed8;
}

.activityCard h2{
  color: #4482c3;
}

.sideInfoCard h2{
  color: #15803d;
}

.quickGrid{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap:10px;
  margin-top:10px;
}

.quickMini{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  padding:12px 12px;
  border-radius: 0 !important;
  border:1px solid rgba(59,130,246,.12);
  background: rgba(255,255,255,.88);
  transition: transform .16s ease, box-shadow .16s ease;
}
.dashboardProgressRow{
  margin-top: 12px;
  padding: 12px;
  border-radius: 0 !important;
  border: 1px solid rgba(68,130,195,.10);
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,246,255,.96));
}

.dashboardProgressMeta{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  margin-bottom:8px;
  font-size:13px;
  font-weight:700;
  color:#5b5573;
}

.dashboardProgressMeta strong{
  color:#2a2540;
  font-weight:800;
}

.dashboardProgressBar{
  width:100%;
  height:10px;
  border-radius: 0 !important;
  background: rgba(68,130,195,.10);
  overflow:hidden;
}

.dashboardProgressBar span{
  display:block;
  height:100%;
  border-radius: 0 !important;
  background: linear-gradient(90deg, #4f89c7 0%, #3b74ad 100%);
  transition: width .25s ease;
}
.quickMini:hover{
  transform: translateY(-1px);
  box-shadow: var(--shadow2);
}

.quickMini .left{
  display:flex;
  align-items:center;
  gap:10px;
}

.quickMini .miniIcon{
  width:36px;
  height:36px;
  border-radius: 0 !important;
  display:grid;
  place-items:center;
  color: var(--navy);
  background: rgba(30,64,175,.10);
  border:1px solid rgba(30,64,175,.14);
}

.quickMini .miniText{
  font-weight:800;
  font-size:14px;
  color: rgba(15,23,42,.92);
}

.activityList{
  margin-top:10px;
  display:flex;
  flex-direction:column;
  gap:10px;
}

.activityRow{
  display:grid;
  grid-template-columns: 92px 54px 54px 48px 64px;
  gap:8px;
  align-items:center;
  padding:10px 10px;
  border-radius: 0 !important;
  border:1px solid rgba(68,130,195,.12);
  background: rgba(255,255,255,.88);
  font-size:12px;
  font-weight:700;
  color: rgba(15,23,42,.88);
  font-variant-numeric: tabular-nums;
}

.activityHead{
  color: var(--muted);
  font-size:11px;
  font-weight:800;
  background: transparent;
  border:none;
  padding:0 2px;
}

.activityEmpty{
  margin-top:10px;
  padding:14px;
  border-radius: 0 !important;
  border:1px dashed rgba(11,18,32,.14);
  color: var(--muted);
  font-weight:600;
  background: rgba(255,255,255,.60);
}
.dashboardBottom{
  margin-top: 12px;
  display: grid;
  grid-template-columns: 1.35fr .85fr;
  gap: 12px;
  align-items: start;
}

@media (max-width: 1100px){
  .dashboardBottom{
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px){
  .dashboardBottom .activityCard{
    display:none;
  }
}

.sideInfoCard{
  padding: 14px;
  border-radius: 0 !important;
  border: 1px solid rgba(11,18,32,.08);
  background: rgba(255,255,255,.82);
}

.sideInfoList{
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sideInfoRow{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  padding:10px 12px;
  border-radius: 0 !important;
  border:1px solid rgba(34,197,94,.12);
  background: rgba(255,255,255,.88);
}

.sideInfoLabel{
  font-size: 13px;
  font-weight: 700;
  color: rgba(15,23,42,.78);
}

.sideInfoValue{
  font-size: 18px;
  font-weight: 800;
  color: rgba(15,23,42,.96);
}
.weeklyEditTable{
  width:100%;
  min-width:100%;
  table-layout: fixed;
  border-collapse:separate;
  border-spacing:0;
  border-radius: 0 !important;
  background: rgba(255,255,255,.94);
  border:1px solid rgba(96,165,250,.14);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.92),
    0 8px 18px rgba(15,23,42,.06);
}
.payrollEmployeeCard{
  width:100%;
  box-sizing:border-box;
  border: 1px solid rgba(96,165,250,.16);
  background: linear-gradient(180deg, rgba(248,251,255,.99), rgba(242,247,255,.98));
  box-shadow:
    0 20px 40px rgba(2,6,23,.16),
    inset 0 1px 0 rgba(255,255,255,.88);
}

.payrollEmployeeCard .tablewrap{
  width:100%;
  box-sizing:border-box;
  overflow-x:auto;
}

.payrollEmployeeCard .weeklyEditTable{
  width:100%;
}
.payrollSummaryBar{
  margin-top:12px;
  display:grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap:10px;
}

@media (max-width: 1100px){
  .payrollSummaryBar{
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}

.payrollSummaryItem{
  padding:12px 14px;
  border-radius: 0 !important;
  border:1px solid rgba(11,18,32,.08);
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
  box-shadow: 0 4px 12px rgba(15,23,42,.05);
}

.payrollSummaryItem .k{
  font-size:12px;
  font-weight:800;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing:.04em;
}

.payrollSummaryItem .v{
  margin-top:4px;
  font-size:20px;
  font-weight:800;
  color: rgba(15,23,42,.96);
  line-height:1.15;
}

.payrollSummaryItem.net .v{
  color:#111827;
}

.payrollSummaryItem.paidat .v{
  font-size:16px;
}

.payrollEmployeeCard .payrollSummaryBar{
  margin-top: 10px;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
}

.payrollEmployeeCard .payrollSummaryItem{
  padding: 3px 5px;
  border-radius: 0 !important;
}

.payrollEmployeeCard .payrollSummaryItem .k{
  font-size: 8px;
}

.payrollEmployeeCard .payrollSummaryItem .v{
  font-size: 11px;
  line-height: 1;
}

.payrollEmployeeCard .payrollSummaryItem:nth-child(1),
.payrollEmployeeCard .payrollSummaryItem:nth-child(2),
.payrollEmployeeCard .payrollSummaryItem:nth-child(3),
.payrollEmployeeCard .payrollSummaryItem:nth-child(4),
.payrollEmployeeCard .payrollSummaryItem:nth-child(5){
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
  border-color: rgba(11,18,32,.08);
}

.payrollEmployeeCard .payrollSummaryItem:nth-child(1) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(2) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(3) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(4) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(5) .k{
  color: var(--muted);
}

.payrollEmployeeCard .payrollSummaryItem:nth-child(1) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(2) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(3) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(4) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(5) .v{
  color: rgba(15,23,42,.96);
}

.weeklyEditTable thead th{
  background: linear-gradient(180deg, rgba(231,240,255,.98), rgba(221,234,254,.98));
  color: rgba(15,23,42,.88);
  font-size:12px;
  font-weight:900;
  letter-spacing:.03em;
  text-transform:uppercase;
  padding:13px 10px;
  border-bottom:1px solid rgba(148,163,184,.18);
}

.weeklyEditTable tbody td{
  padding:14px 10px;
  border-bottom:1px solid rgba(191,219,254,.50);
  color: rgba(15,23,42,.92);
  font-size:14px;
  background: rgba(255,255,255,.92);
  vertical-align:middle;
}

.weeklyEditTable tbody tr:nth-child(even) td{
  background: rgba(248,251,255,.92);
}

.weeklyEditTable tbody tr:hover td{
  background: rgba(239,246,255,.86);
}

.weeklyEditTable td.num,
.weeklyEditTable th.num{
  text-align:center;
  font-variant-numeric: tabular-nums;
  font-feature-settings:"tnum";
}

.weeklyEditTable thead th:nth-child(3),
.weeklyEditTable thead th:nth-child(4),
.weeklyEditTable thead th:nth-child(5),
.weeklyEditTable thead th:nth-child(6),
.weeklyEditTable thead th:nth-child(7),
.weeklyEditTable tbody td:nth-child(3),
.weeklyEditTable tbody td:nth-child(4),
.weeklyEditTable tbody td:nth-child(5),
.weeklyEditTable tbody td:nth-child(6),
.weeklyEditTable tbody td:nth-child(7){
  text-align:center;
  font-variant-numeric: tabular-nums;
  font-feature-settings:"tnum";
}

.weeklyEditTable tbody td:first-child{
  font-weight:800;
  width:70px;
}

.weeklyEditTable tbody td:nth-child(2){
  color: var(--muted);
  width:120px;
}

.weeklyEditTable tbody td:empty::after{
  content:"";
}

.weeklyEditTable tbody tr:last-child td{
  border-bottom:none;
}
.sectionHead{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  margin-bottom:8px;
}

.sectionHeadLeft{
  display:flex;
  align-items:center;
  gap:10px;
}

.sectionIcon{
  width:36px;
  height:36px;
  border-radius: 0 !important;
  display:grid;
  place-items:center;
  border:1px solid rgba(11,18,32,.08);
}

.sectionIcon svg{
  width:18px;
  height:18px;
}

.sectionBadge{
  font-size:12px;
  font-weight:800;
  padding:6px 10px;
  border-radius: 0 !important;
  border:1px solid rgba(11,18,32,.08);
  background: rgba(255,255,255,.88);
  white-space:nowrap;
}

.activityCard .sectionIcon{
  background: rgba(68,130,195,.14);
  color: #4482c3;
  border-color: rgba(68,130,195,.18);
}

.activityCard .sectionBadge{
  color: #4482c3;
  border-color: rgba(68,130,195,.18);
  background: rgba(68,130,195,.08);
}

.sideInfoCard .sectionIcon{
  background: rgba(34,197,94,.14);
  color: #15803d;
  border-color: rgba(34,197,94,.18);
}

.sideInfoCard .sectionBadge{
  color: #15803d;
  border-color: rgba(34,197,94,.18);
  background: rgba(34,197,94,.08);
}

/* Menu */
.menu{ margin-top: 14px; padding: 12px; }

.adminGrid{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 6px;
}

.adminToolsShell{
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
  border: 1px solid rgba(15,23,42,.08);
  box-shadow: 0 18px 40px rgba(15,23,42,.08);
}

.adminToolsShell .adminGrid{
  margin-top: 0;
}

.adminGrid .menuItem{ margin-top: 0; height:100%; }
.adminToolCard{
  padding: 16px;
  border-radius: 0 !important;
  border: 1px solid rgba(15,23,42,.10);
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
  box-shadow: 0 10px 26px rgba(15,23,42,.08);
  display:flex;
  flex-direction:column;
  gap:12px;
  min-height: 132px;
  transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
}
.adminToolCard:hover{
  transform: translateY(-2px);
  box-shadow: 0 16px 34px rgba(15,23,42,.12);
}
.adminToolTop{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
}

.adminToolIcon{
  width: 50px;
  height: 50px;
  border-radius: 0 !important;
  display:flex;
  align-items:center;
  justify-content:center;
  border: 1px solid rgba(15,23,42,.08);
  overflow:hidden;
}
.adminToolIcon svg{
  width: 22px;
  height: 22px;
}
.adminToolIcon img{
  width: 26px;
  height: 26px;
  object-fit:contain;
  display:block;
}

.adminToolTitle{
  font-size: 16px;
  font-weight: 800;
  color: rgba(15,23,42,.94);
}
.adminToolSub{
  font-size: 13px;
  line-height: 1.4;
  color: var(--muted);
}

/* Different colors for admin cards */
.adminToolCard.payroll .adminToolIcon{
  background: linear-gradient(180deg, rgba(219,234,254,.95), rgba(191,219,254,.92));
  color: #1d4ed8;
  border-color: rgba(37,99,235,.16);
}
.adminToolCard.company .adminToolIcon{
  background: linear-gradient(180deg, rgba(220,252,231,.95), rgba(187,247,208,.92));
  color: #15803d;
  border-color: rgba(22,163,74,.18);
}
.adminToolCard.onboarding .adminToolIcon{
  background: linear-gradient(180deg, rgba(224,231,255,.95), rgba(199,210,254,.92));
  color: #4338ca;
  border-color: rgba(79,70,229,.18);
}
.adminToolCard.locations .adminToolIcon{
  background: linear-gradient(180deg, rgba(207,250,254,.95), rgba(165,243,252,.92));
  color: #0e7490;
  border-color: rgba(8,145,178,.18);
}
.adminToolCard.sites .adminToolIcon{
  background: linear-gradient(180deg, rgba(254,243,199,.95), rgba(253,230,138,.92));
  color: #b45309;
  border-color: rgba(217,119,6,.18);
}
.adminToolCard.employees .adminToolIcon{
  background: linear-gradient(180deg, rgba(252,231,243,.95), rgba(251,207,232,.92));
  color: #be185d;
  border-color: rgba(219,39,119,.16);
}
.adminToolCard.drive .adminToolIcon{
  background: linear-gradient(180deg, rgba(226,232,240,.95), rgba(203,213,225,.92));
  color: #0f172a;
  border-color: rgba(51,65,85,.18);
}
/* Admin lower section panels */
.adminSectionCard{
  padding: 14px;
  border-radius: 0 !important;
  border: 1px solid rgba(15,23,42,.10);
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,250,252,.96));
  box-shadow: 0 10px 26px rgba(15,23,42,.07);
}

.adminSectionHead{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:12px;
  flex-wrap:wrap;
  margin-bottom: 12px;
}

.adminSectionHeadLeft{
  display:flex;
  align-items:flex-start;
  gap:12px;
}

.adminSectionIcon{
  width: 46px;
  height: 46px;
  border-radius: 0 !important;
  display:grid;
  place-items:center;
  border: 1px solid rgba(15,23,42,.08);
  flex: 0 0 auto;
}
.adminSectionIcon svg{
  width: 22px;
  height: 22px;
}

.adminSectionIcon.clockin{
  background: linear-gradient(180deg, rgba(219,234,254,.95), rgba(191,219,254,.92));
  color: #1d4ed8;
  border-color: rgba(37,99,235,.16);
}
.adminSectionIcon.live{
  background: linear-gradient(180deg, rgba(220,252,231,.95), rgba(187,247,208,.92));
  color: #15803d;
  border-color: rgba(22,163,74,.18);
}

.adminSectionTitle{
  font-size: 16px;
  font-weight: 800;
  color: rgba(15,23,42,.95);
  margin: 0;
}

.adminSectionSub{
  font-size: 13px;
  line-height: 1.45;
  color: var(--muted);
  margin: 4px 0 0 0;
}

.adminFormRow{
  display:block;
  width:100%;
}
.adminFormRow .input{
  margin-top:0;
}
.adminActionBar{
  display:grid;
  grid-template-columns: 190px minmax(220px, 260px) 170px max-content;
  gap:10px;
  align-items:center;
  width: 100%;
  padding: 12px;
  border-radius: 0 !important;
  background: linear-gradient(180deg, rgba(248,250,252,.95), rgba(241,245,249,.92));
  border: 1px solid rgba(15,23,42,.08);
}

.adminActionBar .input{
  width: 100%;
  height: 44px;
  border-radius: 0 !important;
  background: rgba(255,255,255,.96);
}

@media (max-width: 1200px){
  .adminActionBar{
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 700px){
  .adminActionBar{
    grid-template-columns: 1fr;
  }
}

.adminPrimaryBtn{
  height: 44px;
  min-width: 150px;
  padding: 0 18px;
  justify-self: start;
  border: none;
  border-radius: 0 !important;
  font-weight: 800;
  font-size: 14px;
  cursor: pointer;
  background: linear-gradient(180deg, rgba(30,64,175,1), rgba(37,99,235,.96));
  color: #fff;
  box-shadow: 0 10px 22px rgba(30,64,175,.18);
  transition: transform .16s ease, box-shadow .16s ease, filter .16s ease;
}
.adminPrimaryBtn:hover{
  transform: translateY(-1px);
  box-shadow: 0 14px 26px rgba(30,64,175,.22);
}
.adminPrimaryBtn:active{
  transform: translateY(0);
  filter: brightness(.98);
}

.adminHintChip{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding: 7px 11px;
  border-radius: 0 !important;
  font-size: 12px;
  font-weight: 800;
  background: rgba(30,64,175,.08);
  border: 1px solid rgba(30,64,175,.14);
  color: var(--navy);
}
@media (max-width: 780px){
  .adminGrid{ grid-template-columns: 1fr; }
}

.menuItem{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  padding: 14px 14px;
  border-radius: 0 !important;
  background: rgba(255,255,255,.85);
  border: 1px solid rgba(11,18,32,.08);
  margin-top: 10px;
  transition: transform .16s ease, box-shadow .16s ease, background .16s ease, border-color .16s ease;
}
.menuItem:hover{ transform: translateY(-1px); box-shadow: var(--shadow2); }
.menuItem.active{
  background: var(--navySoft);
  border-color: rgba(30,64,175,.20);
}

.menuItem.nav-home .icoBox{
  background: linear-gradient(180deg, rgba(219,234,254,.95), rgba(191,219,254,.92));
  border-color: rgba(37,99,235,.16);
  color: #1d4ed8;
}

.menuItem.nav-clock .icoBox{
  background: linear-gradient(180deg, rgba(220,252,231,.95), rgba(187,247,208,.92));
  border-color: rgba(22,163,74,.18);
  color: #15803d;
}

.menuItem.nav-times .icoBox{
  background: linear-gradient(180deg, rgba(254,243,199,.95), rgba(253,230,138,.92));
  border-color: rgba(217,119,6,.18);
  color: #b45309;
}

.menuItem.nav-reports .icoBox{
  background: linear-gradient(180deg, rgba(224,231,255,.95), rgba(199,210,254,.92));
  border-color: rgba(79,70,229,.18);
  color: #4338ca;
}

.menuItem.nav-agreements .icoBox{
  background: linear-gradient(180deg, rgba(207,250,254,.95), rgba(165,243,252,.92));
  border-color: rgba(8,145,178,.18);
  color: #0e7490;
}

.menuItem.nav-profile .icoBox{
  background: linear-gradient(180deg, rgba(252,231,243,.95), rgba(251,207,232,.92));
  border-color: rgba(219,39,119,.16);
  color: #be185d;
}

.menuItem.nav-admin .icoBox{
  background: linear-gradient(180deg, rgba(226,232,240,.95), rgba(203,213,225,.92));
  border-color: rgba(51,65,85,.18);
  color: #0f172a;
}

.menuItem.nav-home.active{
  background: linear-gradient(180deg, rgba(37,99,235,.14), rgba(96,165,250,.08));
  border-color: rgba(37,99,235,.24);
}

.menuItem.nav-clock.active{
  background: linear-gradient(180deg, rgba(22,163,74,.14), rgba(74,222,128,.08));
  border-color: rgba(22,163,74,.24);
}

.menuItem.nav-times.active{
  background: linear-gradient(180deg, rgba(245,158,11,.14), rgba(251,191,36,.08));
  border-color: rgba(245,158,11,.24);
}

.menuItem.nav-reports.active{
  background: linear-gradient(180deg, rgba(79,70,229,.14), rgba(129,140,248,.08));
  border-color: rgba(79,70,229,.24);
}

.menuItem.nav-agreements.active{
  background: linear-gradient(180deg, rgba(8,145,178,.14), rgba(34,211,238,.08));
  border-color: rgba(8,145,178,.24);
}

.menuItem.nav-profile.active{
  background: linear-gradient(180deg, rgba(219,39,119,.14), rgba(244,114,182,.08));
  border-color: rgba(219,39,119,.22);
}

.menuItem.nav-admin.active{
  background: linear-gradient(180deg, rgba(51,65,85,.16), rgba(148,163,184,.08));
  border-color: rgba(51,65,85,.24);
}
.menuLeft{ display:flex; align-items:center; gap:12px; }
.icoBox{
  width: 44px; height: 44px;
  border-radius: 0 !important;
  background: rgba(255,255,255,.92);
  border: 1px solid rgba(11,18,32,.08);
  display:grid; place-items:center;
  color: var(--navy);
}
.icoBox svg{ width:22px; height:22px; }

.menuText{
  font-weight:700;
  font-size: 16px;
  letter-spacing:.1px;
  color: var(--navy);
}
.chev{
  font-size: 26px;
  color: rgba(30,64,175,.95);
  font-weight:700;
  opacity:.85;
}

/* Inputs */
.input{
  width:100%;
  padding: 12px 12px;
  border-radius: 0 !important;
  border: 1px solid rgba(11,18,32,.12);
  background: rgba(255,255,255,.92);
  font-size: 15px;
  outline:none;
  margin-top: 8px;
}
.input:focus{
  border-color: rgba(30,64,175,.45);
  box-shadow: 0 0 0 3px rgba(30,64,175,.10);
}

/* Buttons */
.btn{
  border:none;
  border-radius: 0 !important;
  padding: 14px 12px;
  font-weight:700;
  font-size: 15px;
  cursor:pointer;
  box-shadow: 0 10px 18px rgba(11,18,32,.08);
  transition: transform .16s ease, box-shadow .16s ease, filter .16s ease;
}
.btn:hover{ transform: translateY(-1px); filter: brightness(1.02); }
.btn:active{ transform: translateY(0px); filter: brightness(.98); }
.btnIn{ background: var(--green); color:#fff; }
.btnOut{ background: var(--red); color:#fff; }

.btnSoft{
  width:100%;
  border:none;
  border-radius: 0 !important;
  padding: 12px 12px;
  font-weight:700;
  font-size: 14px;
  cursor:pointer;
  background: rgba(30,64,175,.10);
  color: var(--navy);
  transition: transform .16s ease, box-shadow .16s ease;
}
.btnSoft:hover{ transform: translateY(-1px); box-shadow: var(--shadow2); }
/* Download CSV button styled like light export action */
.btnTiny.csvDownload{
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(244,248,255,.96));
  border-color: rgba(96,165,250,.18);
  color: rgba(29,78,216,.96);
  box-shadow:
    0 8px 16px rgba(15,23,42,.06),
    inset 0 1px 0 rgba(255,255,255,.85);
}
.btnTiny.csvDownload:hover{
  background: linear-gradient(180deg, rgba(255,255,255,.99), rgba(239,246,255,.98));
  border-color: rgba(59,130,246,.24);
}
.btnTiny{
  border: 1px solid rgba(15,23,42,.14);
  border-radius: 0 !important;
  padding: 6px 10px;
  font-weight:700;
  font-size: 12px;
  cursor:pointer;
  background: rgba(30,64,175,.08);
  color: rgba(30,64,175,1);
  white-space: nowrap;
}
.btnTiny:hover{
  background: rgba(30,64,175,.14);
  border-color: rgba(30,64,175,.35);
}
.btnTiny.paidDone{
  background: rgba(22,163,74,.15);
  border-color: rgba(22,163,74,.22);
  color: rgba(21,128,61,.95);
  cursor: default;
}
/* Payroll: unpaid "Paid" button = neutral */
.payrollSheet form .btnTiny:not(.paidDone),
.payrollSheet form .btnTiny.dark:not(.paidDone){
  background: transparent;
  border-color: rgba(15,23,42,.22);
  color: rgba(15,23,42,.72);
}

.payrollSheet form .btnTiny:not(.paidDone):hover,
.payrollSheet form .btnTiny.dark:not(.paidDone):hover{
  background: rgba(15,23,42,.06);
  border-color: rgba(15,23,42,.32);
  color: rgba(15,23,42,.86);
}
/* Messages */
.message{
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 0 !important;
  font-weight:700;
  text-align:center;
  background: rgba(22,163,74,.10);
  border: 1px solid rgba(22,163,74,.18);
}
.message.error{ background: rgba(220,38,38,.10); border-color: rgba(220,38,38,.20); }
#geoStatus{
  display:inline-flex;
  align-items:center;
  gap:8px;
  min-height:34px;
  padding:0 12px;
  background:#f8fafc;
  border:1px solid #e2e8f0;
  border-radius: 0 !important;
  color:#334155;
  font-size:13px;
  font-weight:700;
  width:auto;
  max-width:100%;
}
/* Clock */
.clockCard{ margin-top: 12px; padding: 14px; }
.timerBig{
  font-weight:800;
  font-size:44px !important;
  margin-top: 6px;
  font-variant-numeric: tabular-nums;
}
.timerSub{ color: var(--muted); font-weight:500; font-size: 13px; margin-top: 6px; }
.actionRow{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 14px;
}

.tablewrap{
  margin-top:14px;
  width: 100%;
  max-width: 100%;
  min-width: 0;                 /* IMPORTANT inside flex layouts */
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  border-radius: 0 !important;
  border:1px solid rgba(11,18,32,.10);
  background: rgba(255,255,255,.65);
  backdrop-filter: blur(8px);
}
/* Ensure the table scrolls inside .tablewrap instead of widening the page */
.tablewrap table{
  width: max-content;
  min-width: 100%;
}

.tablewrap table{
  width:100%;
  border-collapse: collapse;
  min-width: 720px;
  background:#fff;
}

.tablewrap th,
.tablewrap td{
  padding: 10px 12px;
  border-bottom: 1px solid rgba(11,18,32,.08);
  text-align:left;
  font-size: 14px;
  vertical-align: middle;
  color: rgba(11,18,32,.88);
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}

.tablewrap th{
  position: sticky;
  top:0;
  background: rgba(248,250,252,.96);
  font-weight: 700;
  color: rgba(11,18,32,.95);
  letter-spacing:.2px;
  z-index: 2;
}

.tablewrap table tbody tr:nth-child(even){ background: rgba(11,18,32,.02); }
.tablewrap table tbody tr:hover{ background: rgba(30,64,175,.05); }

/* Numeric cells helper */
.num{
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
  white-space: nowrap;
}

/* Make action buttons (Mark Paid / etc.) consistent inside ANY tablewrap */
.tablewrap td:last-child button{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:6px;
  padding: 6px 12px;
  border-radius: 0 !important;
  border: 1px solid rgba(15,23,42,.14);
  background: rgba(30,64,175,.08);
  color: rgba(30,64,175,1);
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: all .15s ease;
  white-space: nowrap;
}
/* Employee weekly tables (below): make ALL table inputs readable
   (Hours/Pay are <input class="input" ...> with NO type) */
.tablewrap input.input{
  font-weight: 800;
  color: rgba(2,6,23,.95);
  opacity: 1; /* prevent faded disabled text */
  -webkit-text-fill-color: rgba(2,6,23,.95); /* Safari/Chrome */
}
/* Employee weekly tables: center column headers (keep first column like Date left) */
.tablewrap table thead th:not(:first-child),
.tablewrap table thead td:not(:first-child){
  text-align: center;
}
/* Right-align numeric inputs inside numeric cells (Hours/Pay columns) */
.tablewrap td.num input.input{
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}
/* Numbers (hours/pay) easier to scan */
.tablewrap input[type="number"]{
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}
.tablewrap td:last-child button:hover,
.tablewrap td:last-child a:hover{
  background: rgba(30,64,175,.14);
  border-color: rgba(30,64,175,.35);
}
.workplacesTable{
  min-width: 860px;
}

@media (max-width: 700px){
  .workplacesTable{
    min-width: 100% !important;
    table-layout: auto !important;
  }

  .workplacesTable thead{
    display: none;
  }

  .workplacesTable,
  .workplacesTable tbody,
  .workplacesTable tr,
  .workplacesTable td{
    display: block;
    width: 100%;
  }

  .workplacesTable tr{
    padding: 12px;
    border-bottom: 1px solid rgba(11,18,32,.08);
    background: #fff;
  }

  .workplacesTable td{
    border: none;
    padding: 8px 0;
    text-align: left !important;
  }

  .workplacesTable td:last-child{
    padding-top: 10px;
  }
}

.employeesTable{
  width:100% !important;
  min-width:980px !important;
  table-layout:fixed !important;
  border-collapse:separate;
  border-spacing:0;
}

.employeesTable th,
.employeesTable td{
  padding:14px 16px !important;
  vertical-align:middle !important;
}

.employeesTable th{
  font-weight:800 !important;
}

.employeesTable th:nth-child(1),
.employeesTable td:nth-child(1){
  width:30% !important;
  text-align:left !important;
}

.employeesTable th:nth-child(2),
.employeesTable td:nth-child(2){
  width:20% !important;
  text-align:left !important;
}

.employeesTable th:nth-child(3),
.employeesTable td:nth-child(3){
  width:20% !important;
  text-align:left !important;
}

.employeesTable th:nth-child(4),
.employeesTable td:nth-child(4){
  width:15% !important;
  text-align:center !important;
}

.employeesTable th:nth-child(5),
.employeesTable td:nth-child(5){
  width:15% !important;
  text-align:right !important;
}

.employeesTable td:nth-child(2),
.employeesTable td:nth-child(3),
.employeesTable td:nth-child(4),
.employeesTable td:nth-child(5){
  white-space:nowrap;
}

@media (max-width: 700px){
  .employeesTable{
    min-width:100% !important;
    table-layout:auto !important;
  }

  .employeesTable thead{
    display:none;
  }

  .employeesTable,
  .employeesTable tbody,
  .employeesTable tr,
  .employeesTable td{
    display:block;
    width:100%;
  }

  .employeesTable tr{
    padding:12px;
    border-bottom:1px solid rgba(11,18,32,.08);
    background:#fff;
  }

  .employeesTable td{
    border:none;
    padding:8px 0 !important;
    text-align:left !important;
  }
}
.adminLiveTable{
  min-width: 1100px;
}

@media (max-width: 700px){
  .adminLiveTable{
    min-width: 100% !important;
    table-layout: auto !important;
  }

  .adminLiveTable thead{
    display: none;
  }

  .adminLiveTable,
  .adminLiveTable tbody,
  .adminLiveTable tr,
  .adminLiveTable td{
    display: block;
    width: 100%;
  }

  .adminLiveTable tr{
    padding: 12px;
    border-bottom: 1px solid rgba(11,18,32,.08);
    background: #fff;
  }

  .adminLiveTable td{
    border: none;
    padding: 8px 0;
    text-align: left !important;
  }

  .adminLiveTable td:last-child{
    padding-top: 10px;
  }

  .adminLiveTable form{
    width: 100%;
  }

  .adminLiveTable input.input{
    max-width: 100% !important;
    width: 100%;
  }
}

@media (max-width: 700px){
  .row2{
    display: grid !important;
    grid-template-columns: 1fr !important;
    gap: 10px !important;
  }

  .row2 .input,
  .row2 button,
  .row2 a{
    width: 100% !important;
    max-width: 100% !important;
  }

  .headerTop{
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .badge{
    max-width: 100%;
  }

  .adminGrid{
    grid-template-columns: 1fr !important;
  }

  .adminToolCard{
    min-height: auto;
  }

  .menuItem{
    align-items: center;
  }

  .tablewrap{
    border-radius: 0 !important;
  }
}
/* Status chips */
.chip{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding: 4px 10px;
  border-radius: 0 !important;
  font-size: 12px;
  font-weight:700;
  border: 1px solid rgba(11,18,32,.12);
  background: rgba(255,255,255,.85);
  color: rgba(11,18,32,.74);
  white-space: nowrap;
}
.chip.ok{
  background: rgba(22,163,74,.15);
  border-color: rgba(22,163,74,.22);
  color: rgba(21,128,61,.95);
}
.chip.warn{
  background: rgba(234,179,8,.16);
  border-color: rgba(234,179,8,.20);
  color: rgba(146,64,14,.95);
}
.chip.bad{
  background: rgba(220,38,38,.12);
  border-color: rgba(220,38,38,.20);
  color: rgba(185,28,28,.98);
}
.statusLink{
  display:inline-flex;
  text-decoration:none;
  cursor:pointer;
}

.statusLink:hover .chip,
.statusLink:focus .chip{
  filter: brightness(.98);
  transform: translateY(-1px);
}

.statusLink .chip{
  transition: transform .12s ease, filter .12s ease;
}

/* Avatar */
.avatar{
  width: 34px;
  height: 34px;
  border-radius: 0 !important;
  display:grid;
  place-items:center;
  font-weight:800;
  color: var(--navy);
  background: rgba(30,64,175,.08);
  border: 1px solid rgba(30,64,175,.14);
}

/* Week selector row */
.weekRow{
  margin-top: 10px;
  display:flex;
  flex-wrap: wrap;
  gap: 8px;
}
.weekPill{
  font-size: 12px;
  padding: 7px 10px;
  border-radius: 0 !important;
  font-weight:700;
  border: 1px solid rgba(11,18,32,.12);
  background: rgba(255,255,255,.75);
  color: rgba(11,18,32,.72);
}
.weekPill.active{
  background: var(--navySoft);
  border-color: rgba(30,64,175,.20);
  color: var(--navy);
}

/* KPI strip */
.kpiStrip{
  margin-top: 12px;
  display:grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.payrollTopGrid{
  margin-top: 12px;
  display: grid;
  grid-template-columns: 1.15fr .85fr;
  gap: 14px;
  align-items: stretch;
}

@media (max-width: 1100px){
  .payrollTopGrid{
    grid-template-columns: 1fr;
  }
}

.payrollFiltersCard,
.payrollChartCard{
  padding: 16px;
}

.payrollWeekBar{
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: 0 !important;
  border: 1px solid rgba(129,140,248,.32);
  background:
    radial-gradient(circle at top right, rgba(56,189,248,.16), transparent 34%),
    linear-gradient(135deg, rgba(19,31,58,.96), rgba(34,44,79,.96));
  box-shadow:
    0 18px 34px rgba(2,6,23,.18),
    inset 0 1px 0 rgba(255,255,255,.08);
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:14px;
  flex-wrap:wrap;
}

.payrollWeekLead{
  min-width: 0;
  display:grid;
  gap:6px;
}

.payrollWeekBadge{
  display:inline-flex;
  align-items:center;
  width:max-content;
  max-width:100%;
  padding:6px 10px;
  border-radius: 0 !important;
  border:1px solid rgba(125,211,252,.26);
  background: rgba(37,99,235,.18);
  color:#dbeafe;
  font-size:12px;
  font-weight:800;
  letter-spacing:.08em;
  text-transform:uppercase;
}

.payrollWeekHint{
  color: rgba(226,232,240,.84);
  font-size: 14px;
  line-height:1.45;
}

.payrollWeekControl{
  display:grid;
  gap:6px;
  min-width: 270px;
  max-width: 360px;
  flex:1 1 320px;
}

.payrollWeekLabel{
  color:#f8fafc;
  font-size:13px;
  font-weight:800;
  letter-spacing:.08em;
  text-transform:uppercase;
}

.payrollWeekBar .input{
  margin-top:0;
  background: rgba(255,255,255,.12);
  border: 1px solid rgba(191,219,254,.22);
  color:#f8fafc;
  font-weight:400;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.06);
}

.payrollWeekBar .input option{
  font-weight:400;
}

.payrollWeekBar .input:focus{
  border-color: rgba(96,165,250,.7);
  box-shadow: 0 0 0 4px rgba(37,99,235,.18);
}
.payrollWeekBar select,
.payrollWeekBar select option{
  font-weight:400 !important;
}


@media (max-width: 860px){
  .payrollWeekBar{
    padding: 14px;
  }

  .payrollWeekControl{
    min-width: 100%;
    max-width: 100%;
  }
}

.payrollFiltersCard{
  overflow: hidden;
}

.payrollFiltersCard .input,
.payrollFiltersCard .btnSoft,
.payrollFiltersCard input,
.payrollFiltersCard select{
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.payrollFiltersCard .row2{
  display:grid;
  grid-template-columns: 1fr 1fr;
  gap:10px;
}

.payrollFiltersCard .row2 > *{
  min-width:0;
}
.payrollDateRow > div{
  min-width: 0;
}

.payrollDateRow input[type="date"]{
  display: block;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
  -webkit-appearance: none;
  appearance: none;
}

@media (max-width: 600px){
  .payrollDateRow{
    grid-template-columns: 1fr !important;
  }
}

@media (max-width: 600px){
  .payrollFiltersCard{
    padding: 12px;
  }

  .payrollFiltersCard .row2{
    grid-template-columns: 1fr;
  }

  .payrollFiltersCard .input,
  .payrollFiltersCard input,
  .payrollFiltersCard select{
    font-size: 16px;
  }
}

.payrollFiltersCard{
  border: 1px solid rgba(96,165,250,.16);
  background:
    linear-gradient(180deg, rgba(248,251,255,.98) 0%, rgba(241,247,255,.98) 100%);
  box-shadow:
    0 18px 36px rgba(2,6,23,.16),
    inset 0 1px 0 rgba(255,255,255,.78);
}
.payrollFiltersCard .sub{
  color: rgba(71,85,105,.88);
}

.payrollFiltersCard .input,
.payrollFiltersCard input[type="date"],
.payrollFiltersCard select{
  margin-top:0;
  background: rgba(255,255,255,.12);
  border: 1px solid rgba(191,219,254,.22);
  color:#f8fafc;
  font-weight:700;
  box-shadow:none;
}

.payrollFiltersCard .input::placeholder,
.payrollFiltersCard input[type="date"]::placeholder{
  color: rgba(226,232,240,.72);
}

.payrollFiltersCard .input:focus,
.payrollFiltersCard input[type="date"]:focus,
.payrollFiltersCard select:focus{
  border-color: rgba(96,165,250,.7);
  box-shadow: 0 0 0 4px rgba(37,99,235,.18);
}

.payrollFiltersCard .input option,
.payrollFiltersCard select option,
.payrollWeekBar .input option{
  background:#0f172a;
  color:#f8fafc;
}

.payrollFiltersCard input[type="date"]::-webkit-calendar-picker-indicator{
  filter: invert(1) brightness(1.05);
  opacity:.92;
}

.payrollFiltersCard .btnSoft{
  background: linear-gradient(180deg, #3b82f6 0%, #2563eb 100%);
  border: 1px solid rgba(37,99,235,.24);
  color: #fff;
  box-shadow:
    0 12px 24px rgba(37,99,235,.20),
    inset 0 1px 0 rgba(255,255,255,.18);
}

.payrollFiltersCard .btnSoft:hover{
  filter: brightness(1.03);
  box-shadow:
    0 14px 28px rgba(37,99,235,.24),
    inset 0 1px 0 rgba(255,255,255,.20);
}

.payrollFiltersCard .kpiMini{
  border: 1px solid rgba(191,219,254,.95);
  background:
    linear-gradient(180deg, rgba(255,255,255,.98), rgba(244,248,255,.96));
  box-shadow:
    0 8px 18px rgba(15,23,42,.07),
    inset 0 1px 0 rgba(255,255,255,.88);
}

.payrollFiltersCard .kpiMini .k{
  color: rgba(71,85,105,.82);
}

.payrollFiltersCard .kpiMini .v{
  color: rgba(15,23,42,.96);
}

.payrollChartCard{
  background:
    linear-gradient(180deg, rgba(248,251,255,.98), rgba(242,247,255,.98));
  border: 1px solid rgba(96,165,250,.16);
  box-shadow:
    0 18px 36px rgba(2,6,23,.16),
    inset 0 1px 0 rgba(255,255,255,.78);
}

.payrollPieSection{
  margin-top: 10px;
  display:flex;
  justify-content:center;
  align-items:center;
  min-height: 360px;
}

.payrollPieWrap{
  position: relative;
  width: 330px;
  height: 330px;
}

.payrollPie{
  width: 330px;
  height: 330px;
  border-radius: 50% !important;
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.28),
    0 18px 34px rgba(37,99,235,.16);
  border: 1px solid rgba(148,163,184,.14);
}

.payrollPieLabel{
  position: absolute;
  transform: translate(-50%, -50%);
  width: 82px;
  text-align: center;
  color: #ffffff;
  text-shadow: 0 1px 2px rgba(15,23,42,.38);
  pointer-events: none;
  line-height: 1.05;
}

.payrollPieLabel .pct{
  font-size: 15px;
  font-weight: 800;
}

.payrollPieLabel .amt{
  margin-top: 3px;
  font-size: 13px;
  font-weight: 800;
}

.payrollPieLabel .name{
  margin-top: 3px;
  font-size: 10px;
  font-weight: 700;
}

@media (max-width: 900px){
  .payrollPieSection{
    min-height: 300px;
  }

  .payrollPieWrap{
    width: 280px;
    height: 280px;
  }

  .payrollPie{
    width: 280px;
    height: 280px;
  }

  .payrollPieLabel{
  width: 74px;
}

.payrollPieLabel .pct{
  font-size: 13px;
}

.payrollPieLabel .amt{
  font-size: 11px;
}

.payrollPieLabel .name{
  font-size: 9px;
}
}

@media (max-width: 600px){
  .payrollPieSection{
    min-height: 260px;
  }

  .payrollPieWrap{
    width: 240px;
    height: 240px;
  }

  .payrollPie{
    width: 240px;
    height: 240px;
  }

  .payrollPieLabel{
  width: 64px;
}

.payrollPieLabel .pct{
  font-size: 11px;
}

.payrollPieLabel .amt{
  font-size: 10px;
}

.payrollPieLabel .name{
  font-size: 8px;
}
}


@media (max-width: 800px){
  .kpiStrip{ grid-template-columns: 1fr 1fr; }
}

@media (max-width: 480px){
  .kpiStrip{ grid-template-columns: 1fr; }
}

.kpiMini{
  padding: 12px;
  border-radius: 0 !important;
  border: 1px solid rgba(11,18,32,.10);
  background: rgba(255,255,255,.80);
}
.kpiMini .k{ font-size: 12px; color: var(--muted); font-weight:600; }
.kpiMini .v{ margin-top:6px; font-size: 18px; font-weight:800; font-variant-numeric: tabular-nums; }

/* Admin summary cards - same theme as dashboard chart */
.adminStats .adminStatCard{
  border-radius: 0 !important;
  border: 1px solid rgba(56,189,248,.14);
  box-shadow:
    0 18px 40px rgba(2,6,23,.22),
    inset 0 1px 0 rgba(255,255,255,.04);
  background:
    linear-gradient(180deg, #06142b 0%, #0a2342 55%, #0d2f52 100%);
}

.adminStats .adminStatCard .k{
  font-size: 12px;
  font-weight: 700;
  color: rgba(191,219,254,.82);
}

.adminStats .adminStatCard .v{
  font-size: 18px;
  font-weight: 900;
  color: #67e8f9;
  text-shadow: 0 0 10px rgba(34,211,238,.18);
}

/* keep all 4 cards the same dark chart theme */
.adminStats .adminStatCard.employees,
.adminStats .adminStatCard.clocked,
.adminStats .adminStatCard.locations,
.adminStats .adminStatCard.onboarding{
  background:
    linear-gradient(180deg, #06142b 0%, #0a2342 55%, #0d2f52 100%);
  border-color: rgba(56,189,248,.14);
}

.adminStats .adminStatCard.employees .k,
.adminStats .adminStatCard.employees .v,
.adminStats .adminStatCard.clocked .k,
.adminStats .adminStatCard.clocked .v,
.adminStats .adminStatCard.locations .k,
.adminStats .adminStatCard.locations .v,
.adminStats .adminStatCard.onboarding .k,
.adminStats .adminStatCard.onboarding .v{
  color: #67e8f9;
}

/* Weekly net badge */
.netBadge{
  display:inline-flex;
  align-items:center;
  gap:8px;
  padding: 8px 12px;
  border-radius: 0 !important;
  border: 1px solid rgba(30,64,175,.18);
  background: rgba(30,64,175,.10);
  color: var(--navy);
  font-weight:800;
  font-variant-numeric: tabular-nums;
}

/* Row emphasis if gross > 0 */
.rowHasValue{ background: rgba(30,64,175,.035) !important; }

/* Overtime highlight (thin left marker, no ugly full-row fill) */
.overtimeRow{
  background: transparent !important;
  box-shadow: inset 4px 0 0 rgba(245,158,11,.75);
}
.overtimeChip{
  display:inline-flex;
  align-items:center;
  padding: 4px 10px;
  border-radius: 0 !important;
  font-size:12px;
  font-weight:800;
  background: rgba(245,158,11,.14);
  border: 1px solid rgba(245,158,11,.22);
  color: rgba(146,64,14,.95);
}

/* Contract box */
.contractBox{
  margin-top: 12px;
  padding: 12px;
  border-radius: 0 !important;
  border: 1px solid rgba(11,18,32,.10);
  background: rgba(248,250,252,.90);
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 13px;
  color: rgba(11,18,32,.88);
  line-height: 1.4;
}
.bad{ border: 1px solid rgba(220,38,38,.55) !important; box-shadow: 0 0 0 3px rgba(220,38,38,.10) !important; }
.badLabel{ color: rgba(220,38,38,.92) !important; font-weight:800 !important; }

/* Mobile layout: no left sidebar */
.bottomNav{
  display:block !important;
}

.safeBottom{
  display:block !important;
  height:0 !important;
}

#mobileRailToggle{
  display:none !important;
}

@media (max-width: 979px){
  body{
    padding:12px 12px 96px 12px !important;
  }

  .shell{
    width:100% !important;
    max-width:none !important;
    margin:0 !important;
    display:block !important;
  }

  .sidebar{
    display:none !important;
  }

  .main{
    min-width:0 !important;
    padding-right:0 !important;
  }

  .topBarFixed{
    position:sticky;
    top:0;
    z-index:120;
    padding:4px 0 10px;
    background:linear-gradient(180deg, rgba(245,247,252,.98), rgba(245,247,252,.85) 70%, rgba(245,247,252,0));
    backdrop-filter:blur(8px);
    -webkit-backdrop-filter:blur(8px);
  }
}

.navIcon.nav-home{ color:#1d4ed8; }
.navIcon.nav-clock{ color:#15803d; }
.navIcon.nav-times{ color:#b45309; }
.navIcon.nav-reports{ color:#4338ca; }
.navIcon.nav-admin{ color:#0f172a; }
.navIcon.nav-workplaces{ color:#0e7490; }
.navIcon.nav-logout{ color:rgba(220,38,38,.92); }

.navIcon.nav-home.active{
  background: linear-gradient(180deg, rgba(37,99,235,.14), rgba(96,165,250,.08));
}
.navIcon.nav-clock.active{
  background: linear-gradient(180deg, rgba(22,163,74,.14), rgba(74,222,128,.08));
}
.navIcon.nav-times.active{
  background: linear-gradient(180deg, rgba(245,158,11,.14), rgba(251,191,36,.08));
}
.navIcon.nav-reports.active{
  background: linear-gradient(180deg, rgba(79,70,229,.14), rgba(129,140,248,.08));
}
.navIcon.nav-admin.active{
  background: linear-gradient(180deg, rgba(51,65,85,.16), rgba(148,163,184,.08));
}
.navIcon.nav-workplaces.active{
  background: linear-gradient(180deg, rgba(8,145,178,.14), rgba(34,211,238,.08));
}
/* Desktop wide layout */
@media (min-width: 980px){
  body{ padding: 18px 18px 22px 18px; }
    .shell{
    max-width: none;
    width: calc(100vw - 36px);
    margin: 0 auto;
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr);
    gap: 16px;
    align-items: start;
  }
  .bottomNav{ display:none; }
    .sidebar{
    display:flex;
    flex-direction:column;
    gap: 8px;
    position: sticky;
    top: 18px;
    height: calc(100vh - 36px);
    overflow: hidden;
    padding: 12px;
    background: linear-gradient(180deg, rgba(255,255,255,.88), rgba(248,250,252,.92));
    border: 1px solid rgba(30,64,175,.10);
    border-radius: 0 !important;
    box-shadow: 0 10px 30px rgba(15,23,42,.08);
  }
  .sideScroll{
    overflow:auto;
    padding-right: 4px;
    flex: 1 1 auto;
  }
  .sideTitle{
    font-weight:800;
    font-size: 14px;
    color: rgba(11,18,32,.80);
    margin: 0 0 10px 2px;
  }
    .sideItem{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:10px;
    padding: 10px 11px;
    border-radius: 0 !important;
    background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(248,250,252,.96));
    border: 1px solid rgba(30,64,175,.08);
    margin-top: 8px;
    position: relative;
    overflow: hidden;
    transition: transform .16s ease, box-shadow .16s ease, background .16s ease, border-color .16s ease;
  }
    .sideItem:hover{
    transform: translateY(-1px);
    box-shadow: 0 12px 26px rgba(30,64,175,.14);
    border-color: rgba(30,64,175,.18);
  }

  .sideItem.active{
    background: linear-gradient(180deg, rgba(30,64,175,.16), rgba(59,130,246,.10));
    border-color: rgba(30,64,175,.26);
    box-shadow: 0 12px 30px rgba(30,64,175,.16);
  }
  .sideItem.active:before{
    content:"";
    position:absolute;
    left:0;
    top:10px;
    bottom:10px;
    width:4px;
    border-radius: 0 !important;
    background: linear-gradient(180deg, rgba(30,64,175,1), rgba(30,64,175,.55));
    box-shadow: 0 0 0 3px rgba(30,64,175,.10);
  }
  .sideLeft{ display:flex; align-items:center; gap:12px; }
    .sideText{ font-weight:800; font-size: 14px; letter-spacing:.1px; }

  .sideIcon{
  width: 40px;
  height: 40px;
  border-radius: 0 !important;
  background: linear-gradient(180deg, rgba(239,246,255,.95), rgba(219,234,254,.90));
  border: 1px solid rgba(30,64,175,.12);
  display:flex;
  align-items:center;
  justify-content:center;
  color: var(--navy);
  overflow:hidden;
}
.sideIcon svg{
  width: 20px;
  height: 20px;
}
.sideIcon img{
  width: 22px;
  height: 22px;
  object-fit:contain;
  display:block;
}

    /* Different colors for each sidebar item */
  .sideItem.nav-home .sideIcon{
    background: linear-gradient(180deg, rgba(219,234,254,.95), rgba(191,219,254,.92));
    border-color: rgba(37,99,235,.16);
    color: #1d4ed8;
  }

  .sideItem.nav-clock .sideIcon{
    background: linear-gradient(180deg, rgba(220,252,231,.95), rgba(187,247,208,.92));
    border-color: rgba(22,163,74,.18);
    color: #15803d;
  }

  .sideItem.nav-times .sideIcon{
    background: linear-gradient(180deg, rgba(254,243,199,.95), rgba(253,230,138,.92));
    border-color: rgba(217,119,6,.18);
    color: #b45309;
  }

  .sideItem.nav-reports .sideIcon{
    background: linear-gradient(180deg, rgba(224,231,255,.95), rgba(199,210,254,.92));
    border-color: rgba(79,70,229,.18);
    color: #4338ca;
  }

  .sideItem.nav-agreements .sideIcon{
    background: linear-gradient(180deg, rgba(207,250,254,.95), rgba(165,243,252,.92));
    border-color: rgba(8,145,178,.18);
    color: #0e7490;
  }

  .sideItem.nav-profile .sideIcon{
    background: linear-gradient(180deg, rgba(252,231,243,.95), rgba(251,207,232,.92));
    border-color: rgba(219,39,119,.16);
    color: #be185d;
  }

  .sideItem.nav-admin .sideIcon{
    background: linear-gradient(180deg, rgba(226,232,240,.95), rgba(203,213,225,.92));
    border-color: rgba(51,65,85,.18);
    color: #0f172a;
  }

  .sideItem.nav-home.active{
    background: linear-gradient(180deg, rgba(37,99,235,.14), rgba(96,165,250,.08));
    border-color: rgba(37,99,235,.24);
  }

  .sideItem.nav-clock.active{
    background: linear-gradient(180deg, rgba(22,163,74,.14), rgba(74,222,128,.08));
    border-color: rgba(22,163,74,.24);
  }

  .sideItem.nav-times.active{
    background: linear-gradient(180deg, rgba(245,158,11,.14), rgba(251,191,36,.08));
    border-color: rgba(245,158,11,.24);
  }

  .sideItem.nav-reports.active{
    background: linear-gradient(180deg, rgba(79,70,229,.14), rgba(129,140,248,.08));
    border-color: rgba(79,70,229,.24);
  }

  .sideItem.nav-agreements.active{
    background: linear-gradient(180deg, rgba(8,145,178,.14), rgba(34,211,238,.08));
    border-color: rgba(8,145,178,.24);
  }

  .sideItem.nav-profile.active{
    background: linear-gradient(180deg, rgba(219,39,119,.14), rgba(244,114,182,.08));
    border-color: rgba(219,39,119,.22);
  }

  .sideItem.nav-admin.active{
    background: linear-gradient(180deg, rgba(51,65,85,.16), rgba(148,163,184,.08));
    border-color: rgba(51,65,85,.24);
  }

  .sideDivider{
    height: 1px;
    background: rgba(11,18,32,.12);
    margin: 10px 0 6px 0;
  }

  .logoutBtn{
    margin-top: 2px;
    background: rgba(220,38,38,.08);
    border-color: rgba(220,38,38,.12);
  }
  .logoutBtn .sideIcon, .logoutBtn .chev{ color: rgba(220,38,38,.95); }
  .logoutBtn .sideText{ color: rgba(220,38,38,.95); }
}

/* ================= PAYROLL SHEET (condensed week design) ================= */
.payrollWrap{
  margin-top:16px;
  width:100%;
  max-width:100%;
  min-width:0;
  background: linear-gradient(180deg, rgba(248,251,255,.99), rgba(243,248,255,.99));
  border:1px solid rgba(96,165,250,.16);
  border-radius: 0 !important;
  overflow-x:auto;
  overflow-y:hidden;
  -webkit-overflow-scrolling:touch;
  box-shadow:
    0 20px 40px rgba(2,6,23,.18),
    inset 0 1px 0 rgba(255,255,255,.86);
  padding-right:18px;
  box-sizing:border-box;
}

.payrollSheet{
  width:100%;
  min-width:0;
  table-layout:fixed;
  border-collapse:separate;
  border-spacing:0;
  background:transparent;
}

.payrollSheet th,
.payrollSheet td{
  border:none;
  border-bottom:1px solid rgba(191,219,254,.56);
  font-variant-numeric:tabular-nums;
  font-feature-settings:"tnum" 1;
}

.payrollSheet thead th{
  position:sticky;
  top:0;
  z-index:5;
  background: linear-gradient(180deg, rgba(231,240,255,.98), rgba(221,234,254,.98));
  color:rgba(15,23,42,.86);
  font-size:13px;
  font-weight:900;
  letter-spacing:.02em;
  text-transform:uppercase;
  padding:16px 12px;
  white-space:nowrap;
  border-bottom:1px solid rgba(148,163,184,.22);
  text-align:left;
}

.payrollSheet thead th:not(:first-child){
  text-align:center;
}

.payrollSheet tbody td{
  padding:12px 10px;
  font-size:14px;
  line-height:1.35;
  vertical-align:top;
  background:rgba(255,255,255,.92);
  color:rgba(2,6,23,.92);
}

.payrollSheet tbody tr:nth-child(even) td{
  background:rgba(248,251,255,.92);
}

.payrollSheet tbody tr:hover td{
  background:rgba(239,246,255,.95);
}

.payrollSheet tbody tr.is-selected td{
  background:rgba(224,242,254,.92);
}

.payrollSheet tbody tr:hover td:first-child,
.payrollSheet tbody tr.is-selected td:first-child{
  box-shadow:inset 3px 0 0 rgba(37,99,235,.34);
}

/* employee */
.payrollEmpCell,
.payrollSheet thead th:first-child,
.payrollSheet tbody td:first-child{
  width:156px;
  min-width:156px;
  max-width:156px;
}

.payrollSheet thead th:first-child{
  position: sticky;
  left: 0;
  z-index: 9;
  background: linear-gradient(180deg, rgba(226,236,254,.99), rgba(216,230,252,.99));
  box-shadow: 10px 0 18px rgba(15,23,42,.08);
}

.payrollSheet tbody td:first-child{
  position: sticky;
  left: 0;
  z-index: 4;
  background: linear-gradient(180deg, rgba(247,250,255,.98), rgba(242,247,255,.98));
  box-shadow: 10px 0 18px rgba(15,23,42,.08);
}

.payrollSheet tbody tr:hover td:first-child{
  background: rgba(239,246,255,.98);
}

.payrollSheet tbody tr.is-selected td:first-child{
  background: rgba(224,242,254,.96);
}

.payrollEmpCell .emp{
  display:block;
  font-weight:800;
  line-height:1.2;
}

.payrollSheet .emp{
  display:block;
  width:100%;
  min-width:0;
  font-size:14px;
  font-weight:900;
  line-height:1.18;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
  color: rgba(15,23,42,.96);
}

.payrollSheet .empSub{
  display:block;
  margin-top:4px;
  font-size:12px;
  font-weight:700;
  color:rgba(71,85,105,.72);
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis;
}

/* condensed day cells */
.payrollDayCell{
  width:92px;
  min-width:92px;
  max-width:92px;
  text-align:left;
}
.payrollDayStack{
  display:flex;
  flex-direction:column;
  gap:4px;
  min-height:74px;
  justify-content:flex-start;
  padding:0;
  border-radius: 0 !important;
  background:transparent;
  border:none;
  box-shadow:none;
}

.payrollDayLine{
  min-height:20px;
  display:flex;
  align-items:center;
}

.payrollDayLine + .payrollDayLine{
  padding-top:0;
  border-top:none;
}

.payrollDayHours{
  min-height:20px;
  display:flex;
  align-items:center;
  margin-top:auto;
  padding-top:4px;
  font-size:13px;
  font-weight:900;
  color:#0f766e;
}

.payrollDayEmpty{
  min-height:74px;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:20px;
  font-weight:700;
  color:rgba(100,116,139,.55);
  border-radius: 0 !important;
  border:none;
  background:transparent;
}

.payrollDayCellOT{
  background:rgba(255,247,237,.92) !important;
  box-shadow:inset 0 0 0 1px rgba(251,191,36,.20);
  border-radius: 0 !important;
}

.payrollSheet tbody tr:hover td.payrollDayCellOT,
.payrollSheet tbody tr.is-selected td.payrollDayCellOT{
  background:rgba(245,158,11,.14) !important;
}

/* time inputs */
.payrollSheet input:disabled,
.payrollSheet select:disabled{
  background:transparent;
}

.payrollSheet input[type="time"]{
  font-weight:900;
  color:rgba(15,23,42,.98);
  letter-spacing:.01em;
}

.payrollSheet input[type="time"]:disabled{
  opacity:1;
  -webkit-text-fill-color:rgba(15,23,42,.98);
}

.payrollSheet input.payrollTimeInput,
.payrollTimeInput{
  width:100%;
  min-width:0;
  max-width:none;
  height:22px;
  line-height:22px;
  padding:0 2px 0 0;
  border:none;
  border-radius: 0 !important;
  background:transparent;
  box-shadow:none;
  font-size:13px;
  font-weight:900;
  text-align:left;
  color:rgba(15,23,42,.94);
  outline:none;
  appearance:none;
  -webkit-appearance:none;
}

.payrollSheet input.payrollTimeInput::-webkit-calendar-picker-indicator,
.payrollSheet input.payrollTimeInput::-webkit-clear-button,
.payrollSheet input.payrollTimeInput::-webkit-inner-spin-button,
.payrollSheet input.payrollTimeInput::-webkit-outer-spin-button{
  display:none !important;
  -webkit-appearance:none !important;
  opacity:0 !important;
}

.payrollSheet input.payrollTimeInput[value=""]{
  color:transparent !important;
}

.payrollSheet input.payrollTimeInput[value=""]::-webkit-datetime-edit,
.payrollSheet input.payrollTimeInput[value=""]::-webkit-date-and-time-value{
  color:transparent !important;
}

.payrollSheet input.payrollTimeInput:focus{
  color:rgba(15,23,42,.94) !important;
  background:rgba(30,64,175,.06) !important;
  box-shadow:inset 0 0 0 1px rgba(30,64,175,.18) !important;
}

.payrollSheet input.payrollTimeInput:focus::-webkit-datetime-edit,
.payrollSheet input.payrollTimeInput:focus::-webkit-date-and-time-value{
  color:rgba(15,23,42,.94) !important;
}

/* summary columns */
.payrollSummaryTotal{
  width:72px;
  min-width:72px;
  max-width:72px;
  text-align:center !important;
}

.payrollSummaryMoney{
  width:106px;
  min-width:106px;
  max-width:106px;
  text-align:right !important;
}

.payrollSheet td.payrollSummaryTotal,
.payrollSheet td.payrollSummaryMoney{
  vertical-align:middle;
  font-weight:900;
}

.payrollSheet thead th.payrollSummaryTotal,
.payrollSheet thead th.payrollSummaryMoney,
.payrollSheet td.payrollSummaryTotal,
.payrollSheet td.payrollSummaryMoney{
  background-image: linear-gradient(180deg, rgba(240,247,255,.96), rgba(233,243,255,.96));
}

.payrollSheet td.payrollSummaryMoney{
  color: rgba(15,23,42,.98);
}

/* states */
.payrollSheet td.net{
  background:transparent;
  color:rgba(2,6,23,.92);
  font-weight:900;
}

.payrollSheet tbody tr:hover td.net,
.payrollSheet tbody tr.is-selected td.net{
  background:transparent;
}

.payrollSheet td.net.paidNetCell{
  background:transparent !important;
  color:rgba(21,128,61,.98) !important;
  font-weight:900;
  text-align:center !important;
}

.payrollSheet td.net.zeroNetCell{
  background:transparent !important;
  color:rgba(2,6,23,.72) !important;
  font-weight:800;
  text-align:right !important;
}
.paidNetBadge{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:6px;
  min-height:34px;
  padding:0 12px;
  border-radius: 0 !important;
  background:linear-gradient(180deg, rgba(220,252,231,.96), rgba(209,250,229,.96));
  border:1px solid rgba(34,197,94,.18);
  color:rgba(21,128,61,.98);
  font-size:11px;
  font-weight:900;
  line-height:1;
  white-space:nowrap;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.78);
}
/* pay button */
.payCellForm{
  margin:0;
}

.payCellBtn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:8px;
  width:100%;
  min-height:38px;
  padding:7px 12px;
  border:1px solid rgba(251,191,36,.26);
  border-radius: 0 !important;
  background:linear-gradient(180deg, rgba(255,247,237,.98), rgba(254,243,199,.96));
  color:rgba(15,23,42,.96);
  font-size:12px;
  font-weight:900;
  line-height:1;
  white-space:nowrap;
  cursor:pointer;
  transition:transform .12s ease, filter .12s ease, box-shadow .12s ease;
  box-shadow:
    0 8px 16px rgba(245,158,11,.10),
    inset 0 1px 0 rgba(255,255,255,.78);
}

.payCellBtn:hover{
  filter:brightness(.99);
  box-shadow:
    0 10px 18px rgba(245,158,11,.14),
    inset 0 0 0 1px rgba(180,83,9,.12);
}

.payCellBtn:active{
  transform:scale(.99);
}

.payCellBtn .payLabel{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  margin:0;
  min-height:20px;
  padding:0 8px;
  border-radius: 0 !important;
  font-size:10px;
  font-weight:900;
  color:rgba(146,64,14,.95);
  background:rgba(251,191,36,.18);
}

/* mobile */
@media (max-width: 979px){
  .mobileTopLogo{
    display:flex;
  }

  .topBarFixed{
    justify-content:space-between;
    gap:8px;
    margin-bottom:12px;
  }

  .topBrandBadge{
    min-height:34px;
    padding:6px 12px;
    font-size:11px;
    letter-spacing:.03em;
  }
}

@media (max-width: 979px){
  .payrollSheet{
    min-width:1120px;
  }

  .payrollEmpCell,
  .payrollSheet thead th:first-child,
  .payrollSheet tbody td:first-child{
    width:112px;
    min-width:112px;
    max-width:112px;
  }

  .payrollDayCell{
    width:84px;
    min-width:84px;
    max-width:84px;
  }

  .payrollSummaryTotal{
    width:60px;
    min-width:60px;
    max-width:60px;
  }

  .payrollSummaryMoney{
    width:84px;
    min-width:84px;
    max-width:84px;
  }

  .payrollSheet thead th{
    font-size:12px;
    padding:10px 7px;
  }

  .payrollSheet tbody td{
    padding:10px 7px;
  }

  .payrollSheet .emp{
    font-size:12px;
  }

  .payrollSheet .empSub{
    font-size:10px;
  }

  .payrollSheet input.payrollTimeInput,
  .payrollTimeInput{
    font-size:12px;
  }

  .payrollDayHours{
    font-size:11px;
  }
}
/* Print tidy */
@media print{
  .sidebar, .bottomNav, button, input, select, .weekRow { display:none !important; }
  body{ padding:0 !important; background:#fff !important; }
  .shell{ width:100% !important; max-width:none !important; grid-template-columns: 1fr !important; }
  .card{ box-shadow:none !important; }
}

.kpiFancy{
  border: 1px solid rgba(56,189,248,.14);
  background:
    linear-gradient(180deg, #06142b 0%, #0a2342 55%, #0d2f52 100%);
  box-shadow:
    0 18px 40px rgba(2,6,23,.22),
    inset 0 1px 0 rgba(255,255,255,.04);
}

.kpiFancy .label{
  color: rgba(191,219,254,.78);
}

.kpiFancy .value{
  color: #f8fafc;
}

.kpiFancy .sub{
  color: rgba(191,219,254,.78);
}

.kpiFancy .chip{
  background: rgba(255,255,255,.08);
  border: 1px solid rgba(56,189,248,.18);
  color: #93c5fd;
}

/* Dashboard page menu card:
   keep on mobile, hide on desktop because sidebar already exists */
.dashboardMainMenu{
  display:block;
}

@media (min-width: 980px){
  .dashboardMainMenu{
    display:none;
  }
}
/* Payroll page docked sidebar */
@media (min-width: 980px){
  .payrollShell{
    grid-template-columns: 1fr !important;
    position: relative;
  }

  .payrollShell .sidebar{
    display: flex !important;
    position: fixed;
    left: 18px;
    top: 18px;
    bottom: 18px;
    width: 280px;
    z-index: 140;
    transform: translateX(-115%);
    opacity: 0;
    pointer-events: none;
    transition: transform .22s ease, opacity .22s ease;
  }

  .payrollShell.payrollMenuOpen .sidebar{
    transform: translateX(0);
    opacity: 1;
    pointer-events: auto;
  }

  .payrollShell .main{
    width: 100%;
    min-width: 0;
    transition: margin-left .22s ease, width .22s ease;
  }

  .payrollShell.payrollMenuOpen .main{
    margin-left: 298px;
    width: calc(100% - 298px);
  }

  /* no dark overlay for docked mode */
  .payrollMenuBackdrop{
    display: none !important;
  }

  .payrollMenuToggle{
  position: fixed;
  left: 5px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 160;
  width: 20px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(220,38,38,.22);
  border-radius: 0 !important;
  background: linear-gradient(180deg, rgba(254,242,242,.98), rgba(252,231,243,.96));
  color: transparent;
  font-size: 0;
  cursor: pointer;
  box-shadow: 0 10px 22px rgba(220,38,38,.14);
  transition: left .22s ease, box-shadow .18s ease, background .18s ease;
}

.payrollMenuToggle::before{
  content: "❯";
  color: rgba(220,38,38,.95);
  font-size: 15px;
  font-weight: 900;
  line-height: 1;
}

.payrollShell.payrollMenuOpen .payrollMenuToggle{
  left: 308px;
}

.payrollShell.payrollMenuOpen .payrollMenuToggle::before{
  content: "❮";
}

.payrollMenuToggle:hover{
  box-shadow: 0 14px 26px rgba(220,38,38,.18);
  background: linear-gradient(180deg, rgba(254,226,226,.98), rgba(252,231,243,.98));
}
}
/* Admin payroll weekly employee cards - mobile compact table */
.payrollEmployeeCard .weeklyEditTable{
  table-layout: fixed;
  width: 100%;
  min-width: 0;
}

.payrollEmployeeCard .weeklyEditTable thead th,
.payrollEmployeeCard .weeklyEditTable tbody td{
  padding: 8px 4px;
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.payrollEmployeeCard .weeklyEditTable thead th{
  letter-spacing: 0;
  font-size: 11px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(1),
.payrollEmployeeCard .weeklyEditTable td:nth-child(1){
  width: 38px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(2),
.payrollEmployeeCard .weeklyEditTable td:nth-child(2){
  width: 78px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(3),
.payrollEmployeeCard .weeklyEditTable td:nth-child(3),
.payrollEmployeeCard .weeklyEditTable th:nth-child(4),
.payrollEmployeeCard .weeklyEditTable td:nth-child(4){
  width: 56px;
  text-align: center;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(5),
.payrollEmployeeCard .weeklyEditTable td:nth-child(5){
  width: 46px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(6),
.payrollEmployeeCard .weeklyEditTable td:nth-child(6),
.payrollEmployeeCard .weeklyEditTable th:nth-child(7),
.payrollEmployeeCard .weeklyEditTable td:nth-child(7){
  width: 64px;
}

@media (max-width: 780px){
  .payrollEmployeeCard{
    padding: 10px !important;
  }

  .payrollEmployeeCard .weeklyEditTable thead th,
.payrollEmployeeCard .weeklyEditTable tbody td{
  padding: 6px 2px;
  font-size: 10px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(1),
.payrollEmployeeCard .weeklyEditTable td:nth-child(1){
  width: 30px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(2),
.payrollEmployeeCard .weeklyEditTable td:nth-child(2){
  width: 66px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(3),
.payrollEmployeeCard .weeklyEditTable td:nth-child(3),
.payrollEmployeeCard .weeklyEditTable th:nth-child(4),
.payrollEmployeeCard .weeklyEditTable td:nth-child(4){
  width: 46px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(5),
.payrollEmployeeCard .weeklyEditTable td:nth-child(5){
  width: 38px;
}

.payrollEmployeeCard .weeklyEditTable th:nth-child(6),
.payrollEmployeeCard .weeklyEditTable td:nth-child(6),
.payrollEmployeeCard .weeklyEditTable th:nth-child(7),
.payrollEmployeeCard .weeklyEditTable td:nth-child(7){
  width: 52px;
}

  .payrollEmployeeCard .payrollSummaryBar{
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .payrollEmployeeCard .payrollSummaryItem{
  padding: 3px 5px;
  border-radius: 0 !important;
}

.payrollEmployeeCard .payrollSummaryItem .k{
  font-size: 8px;
}

.payrollEmployeeCard .payrollSummaryItem .v{
  font-size: 11px;
  line-height: 1;
}
}
/* ===== dark sidebar + blue payroll toggle ===== */

/* left menu panel */
.sidebar{
  background: linear-gradient(150deg, #0f172a 50%, #111827 20%) !important;
  border: 1px solid rgba(148,163,184,.16) !important;
  box-shadow: 0 18px 40px rgba(2,6,23,.28) !important;
}

.sideTitle{
  color: #e5e7eb !important;
}

.sideDivider{
  background: rgba(148,163,184,.18) !important;
}

/* menu cards inside dark panel */
.sideItem{
  background: rgba(255,255,255,.04) !important;
  border: 1px solid rgba(148,163,184,.14) !important;
  box-shadow: none !important;
}

.sideItem:hover{
  background: rgba(255,255,255,.07) !important;
  border-color: rgba(96,165,250,.26) !important;
  box-shadow: 0 10px 24px rgba(2,6,23,.18) !important;
}

.sideItem.active{
  background: linear-gradient(180deg, rgba(37,99,235,.22), rgba(59,130,246,.12)) !important;
  border-color: rgba(96,165,250,.34) !important;
  box-shadow: 0 12px 28px rgba(30,64,175,.22) !important;
}

.sideItem.active:before{
  content:none !important;
  display:none !important;
}

.shell:has(.sidebar) .sideItem.active::after{
  content:"";
  position:absolute;
  left:10px;
  right:10px;
  bottom:6px;
  height:4px;
  border-radius: 0 !important;
  background:linear-gradient(90deg, #60a5fa, #2563eb);
  box-shadow:0 0 0 3px rgba(59,130,246,.12);
}

/* text + chevrons */
.sideText{
  color: #f8fafc !important;
}

.chev{
  color: #93c5fd !important;
  opacity: 1 !important;
}

/* icons - remove inner card look */
.sideIcon{
  background:transparent !important;
  border:0 !important;
  box-shadow:none !important;
  border-radius: 0 !important;
  padding:0 !important;
  display:flex !important;
  align-items:center !important;
  justify-content:center !important;
  color:#cfe1ff !important;
}

.sideIcon svg{
  width:32px !important;
  height:32px !important;
  display:block !important;
}

.sideIcon img{
  width:32px !important;
  height:32px !important;
  object-fit:contain !important;
  display:block !important;
}

/* logout row */
.logoutBtn{
  background: rgba(239,68,68,.08) !important;
  border-color: rgba(248,113,113,.18) !important;
}

.logoutBtn .sideText,
.logoutBtn .chev{
  color: #f87171 !important;
}

/* payroll sliding button */
.payrollMenuToggle{
  left: 10px !important;
  top: 50% !important;
  transform: translateY(-50%) !important;
  width: 32px !important;
  height: 32px !important;
  padding: 0 !important;
  border-radius: 0 !important;
  border: 1px solid rgba(148,163,184,.34) !important;
  background: rgba(255,255,255,.96) !important;
  color: transparent !important;
  font-size: 0 !important;
  box-shadow: 0 6px 16px rgba(15,23,42,.08), inset 0 1px 0 rgba(255,255,255,.82) !important;
}

.payrollMenuToggle::before{
  content: "›";
  color: #64748b !important;
  font-size: 20px !important;
  font-weight: 800 !important;
  line-height: 1 !important;
  transform: translateX(1px);
}

.payrollMenuToggle:hover{
  background: rgba(255,255,255,.99) !important;
  border-color: rgba(99,102,241,.28) !important;
  box-shadow: 0 10px 20px rgba(15,23,42,.12), inset 0 1px 0 rgba(255,255,255,.9) !important;
}

/* when sidebar is open, keep toggle aligned just outside panel */
.payrollShell.payrollMenuOpen .payrollMenuToggle{
  left: 286px !important;
}
.payrollShell.payrollMenuOpen .payrollMenuToggle::before{
  content: "‹";
  transform: translateX(-1px);
}
@media (max-width: 979px){
  .payrollMenuToggle{
    display: none !important;
  }
}


.timeLogsTable{
  width: 100% !important;
  min-width: 0 !important;
  table-layout: fixed;
}

.timeLogsTable th,
.timeLogsTable td{
  padding: 12px 14px;
  font-size: 16px;
  line-height: 1.25;
  vertical-align: middle;
  white-space: nowrap;
}

.timeLogsTable th{
  font-size: 17px;
  font-weight: 800;
}

.timeLogsTable th:nth-child(1),
.timeLogsTable td:nth-child(1){
  width: 24%;
  text-align: left;
}

.timeLogsTable th:nth-child(2),
.timeLogsTable td:nth-child(2),
.timeLogsTable th:nth-child(3),
.timeLogsTable td:nth-child(3){
  width: 18%;
  text-align: center;
}

.timeLogsTable th:nth-child(4),
.timeLogsTable td:nth-child(4){
  width: 14%;
  text-align: center;
}

.timeLogsTable th:nth-child(5),
.timeLogsTable td:nth-child(5){
  width: 18%;
  text-align: right;
  padding-right: 18px;
}

@media (max-width: 700px){
  .timeLogsTable th,
  .timeLogsTable td{
    padding: 7px 6px;
    font-size: 12px;
  }

  .timeLogsTable th{
    font-size: 13px;
  }

  .timeLogsTable th:nth-child(1),
  .timeLogsTable td:nth-child(1){
    width: 30%;
  }

  .timeLogsTable th:nth-child(2),
  .timeLogsTable td:nth-child(2),
  .timeLogsTable th:nth-child(3),
  .timeLogsTable td:nth-child(3){
    width: 18%;
    text-align: center;
  }

  .timeLogsTable th:nth-child(4),
  .timeLogsTable td:nth-child(4){
    width: 14%;
    text-align: center;
  }

  .timeLogsTable th:nth-child(5),
  .timeLogsTable td:nth-child(5){
    width: 20%;
    text-align: right;
    padding-right: 10px;
  }
}

/* ===== LIGHT BRAND THEME (PURPLE / BLUE / GREEN) ===== */
:root{
  --bg:#ffffff !important;
  --card:#ffffff !important;
  --text:#1f2a37 !important;
  --muted:#6b7280 !important;
  --border:rgba(15,23,42,.08) !important;
  --shadow:0 8px 20px rgba(15,23,42,.04) !important;
  --shadow2:0 12px 28px rgba(15,23,42,.06) !important;
  --radius:0px;

  /* Re-map existing theme vars without touching app logic */
  --navy:#3b74ad !important;
  --navy2:#3b74ad !important;
  --navySoft:rgba(59,116,173,.08) !important;
  --green:#16a34a !important;
  --red:#dc2626 !important;
  --amber:#d97706 !important;
}

/* page background */
body{
  background:#ffffff !important;
  background-image:none !important;
  color: var(--text) !important;
}

/* general cards / panels */
.card,
.kpiMini,
.kpi,
.payrollFiltersCard,
.payrollChartCard,
.adminToolCard,
.adminSectionCard,
.payrollSummaryItem,
.contractBox,
.tablewrap,
.payrollWrap,
.sectionIcon,
.adminToolIcon,
.adminSectionIcon,
.sideIcon,
.icoBox{
  background:#ffffff !important;
  background-image:none !important;
  border: 1px solid rgba(15,23,42,.08) !important;
  border-radius: 0 !important;
  box-shadow: 0 6px 16px rgba(15,23,42,.04) !important;
  color: var(--text) !important;
}

/* module tinting */
.quickCard{
  background:#ffffff !important;
  background-image:none !important;
  border: 1px solid rgba(15,23,42,.08) !important;
  color: var(--text) !important;
}
.activityCard{
  background:#ffffff !important;
  background-image:none !important;
  border: 1px solid rgba(15,23,42,.08) !important;
  color: var(--text) !important;
}
.sideInfoCard{
  background:#ffffff !important;
  background-image:none !important;
  border: 1px solid rgba(15,23,42,.08) !important;
  color: var(--text) !important;
}

/* corner radius */
.badge,
.badge.admin,
.chip,
.weekPill,
.btn,
.btnSoft,
.btnTiny,
.input,
.menuItem,
.sideItem,
.navIcon,
.payrollMenuToggle,
.adminPrimaryBtn,
.message,
.kpiMini,
.payrollSummaryItem,
.tablewrap,
.payrollWrap,
.contractBox{
  border-radius: 0 !important;
}

/* brand badges / pills */
.badge,
.badge.admin,
.weekPill{
  background:#ffffff !important;
  background-image:none !important;
  color: #315f8f !important;
  border: 1px solid rgba(59,116,173,.18) !important;
  box-shadow:none !important;
}

/* brand button system */
.btn,
.btnSoft,
.adminPrimaryBtn,
.payrollMenuToggle{
  background:#3b74ad !important;
  background-image:none !important;
  color: #ffffff !important;
  border: 1px solid #3b74ad !important;
  box-shadow:none !important;
}
.btnTiny{
  background:#ffffff !important;
  background-image:none !important;
  color: #315f8f !important;
  border: 1px solid rgba(59,116,173,.18) !important;
  box-shadow: none !important;
}
.btnTiny:hover,
.btnSoft:hover,
.btn:hover,
.adminPrimaryBtn:hover,
.payrollMenuToggle:hover{
  filter: brightness(.98) !important;
  box-shadow:none !important;
}

/* top badges / company pill */
.topBrandBadge{
  color: #315f8f !important;
  border: 1px solid rgba(15,23,42,.08) !important;
  background:#ffffff !important;
  background-image:none !important;
  box-shadow:none !important;
}
.topBrandBadge:hover{
  border-color: rgba(68,130,195,.20) !important;
}

/* inputs */
.input,
select.input,
input.input,
textarea.input{
  background: rgba(255,255,255,.98) !important;
  color: #27253a !important;
  border: 1px solid rgba(148,163,184,.34) !important;
  border-radius: 0 !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.75) !important;
}
.input::placeholder,
textarea.input::placeholder{
  color: #8a86a3 !important;
}
.input:focus,
select.input:focus,
input.input:focus,
textarea.input:focus{
  border-color: rgba(68,130,195,.40) !important;
  box-shadow: 0 0 0 4px rgba(68,130,195,.10) !important;
}

/* labels + values */
.kpiMini .k,
.kpi .label,
.graphStat .k,
.payrollSummaryItem .k,
.sectionBadge,
.sub,
.timerSub,
.sideInfoLabel,
.adminToolSub,
.adminSectionSub,
.activityHead{
  color: #6b7785 !important;
}
.kpiMini .v,
.kpi .value,
.graphStat .v,
.payrollSummaryItem .v,
.sideInfoValue,
.adminToolTitle,
.adminSectionTitle,
.quickMini .miniText,
h1,
h2{
  color: #1f2a37 !important;
}

/* graph / dashboard */
.graphCard{
  background:#ffffff !important;
  background-image:none !important;
  border: 1px solid rgba(15,23,42,.08) !important;
  box-shadow: 0 6px 16px rgba(15,23,42,.04) !important;
}
.graphTitle{
  color: #23364a !important;
}
.graphCard .sub{
  color: #6b7785 !important;
}
.graphRange{
  color: #315f8f !important;
}
.graphShell{
  background:#ffffff !important;
  background-image:none !important;
  border: 1px solid rgba(15,23,42,.08) !important;
  box-shadow:none !important;
}
.barValue{
  color: #3b74ad !important;
  text-shadow: none !important;
}
.barTrack{
  background:rgba(148,163,184,.14) !important;
  background-image:none !important;
  box-shadow: inset 0 0 0 1px rgba(15,23,42,.06) !important;
}
.bar{
  background:#3b74ad !important;
  background-image:none !important;
  box-shadow:none !important;
}
.barLabels{
  color: #6f6c85 !important;
}
.graphStat{
  background: rgba(255,255,255,.92) !important;
  border: 1px solid rgba(68,130,195,.08) !important;
}

/* tables */
.tablewrap table,
.weeklyEditTable,
.payrollSheet,
.timeLogsTable{
  background: rgba(255,255,255,.98) !important;
  color: #1f2a37 !important;
}
.tablewrap th,
.weeklyEditTable thead th,
.payrollSheet thead th,
.timeLogsTable th{
  background:#3b74ad !important;
  background-image:none !important;
  color:#ffffff !important;
  border-bottom: 1px solid #315f8f !important;
}
.tablewrap td,
.weeklyEditTable tbody td,
.payrollSheet td,
.timeLogsTable td{
  background: rgba(255,255,255,.96) !important;
  color: rgba(38,35,58,.95) !important;
  border-bottom: 1px solid rgba(226,232,240,.90) !important;
}
.tablewrap table tbody tr:nth-child(even),
.weeklyEditTable tbody tr:nth-child(even) td,
.payrollSheet tbody tr:nth-child(even) td,
.timeLogsTable tbody tr:nth-child(even) td{
  background: rgba(248,250,252,.90) !important;
}
.tablewrap table tbody tr:hover,
.weeklyEditTable tbody tr:hover td,
.payrollSheet tbody tr:hover td,
.timeLogsTable tbody tr:hover td{
  background: rgba(241,245,249,.96) !important;
}
.weeklyEditTable tbody td:nth-child(2){
  color: #6b7785 !important;
}


/* flat white override */
body, .card, .kpiMini, .kpi, .graphCard, .graphShell, .payrollFiltersCard, .payrollChartCard, .adminToolCard, .adminSectionCard, .payrollSummaryItem, .contractBox, .tablewrap, .payrollWrap, .quickCard, .activityCard, .sideInfoCard, .topBrandBadge, .menuItem, .sideItem, .btn, .btnSoft, .btnTiny, .adminPrimaryBtn, .payrollMenuToggle{ background-image:none !important; }
/* payroll-specific light treatment */
.payrollWrap,
.tablewrap{
  background:#ffffff !important;
  background-image:none !important;
  border-color: rgba(15,23,42,.08) !important;
}
.payrollSheet{
  background: transparent !important;
}
.payrollSheet tbody td:first-child,
.payrollSheet thead th:first-child{
  box-shadow: 10px 0 18px rgba(15,23,42,.06) !important;
}
.payrollSheet .emp{
  color: rgba(38,35,58,.98) !important;
}
.payrollSheet .empSub{
  color: rgba(111,108,133,.76) !important;
}
.payrollDayHours{
  color: #15803d !important;
}
.payrollDayEmpty{
  color: rgba(111,108,133,.54) !important;
}
.payrollSheet input[type="time"],
.payrollSheet input[type="time"]:disabled,
.payrollSheet input.payrollTimeInput,
.payrollTimeInput{
  color: rgba(38,35,58,.98) !important;
  -webkit-text-fill-color: rgba(38,35,58,.98) !important;
}
.payrollSummaryItem,
.payrollEmployeeCard .payrollSummaryItem:nth-child(1),
.payrollEmployeeCard .payrollSummaryItem:nth-child(2),
.payrollEmployeeCard .payrollSummaryItem:nth-child(3),
.payrollEmployeeCard .payrollSummaryItem:nth-child(4),
.payrollEmployeeCard .payrollSummaryItem:nth-child(5){
  background: linear-gradient(180deg, rgba(255,255,255,.99), rgba(248,246,255,.97)) !important;
  border: 1px solid rgba(68,130,195,.10) !important;
  box-shadow: 0 8px 18px rgba(15,23,42,.06), inset 0 1px 0 rgba(255,255,255,.90) !important;
}
.payrollSummaryItem .k,
.payrollEmployeeCard .payrollSummaryItem .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(1) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(2) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(3) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(4) .k,
.payrollEmployeeCard .payrollSummaryItem:nth-child(5) .k{
  color: rgba(111,108,133,.82) !important;
}
.payrollSummaryItem .v,
.payrollSummaryItem.net .v,
.payrollEmployeeCard .payrollSummaryItem .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(1) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(2) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(3) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(4) .v,
.payrollEmployeeCard .payrollSummaryItem:nth-child(5) .v{
  color: rgba(38,35,58,.96) !important;
}

/* employee detail cards */
.payrollEmployeeCard{
  background: linear-gradient(180deg, rgba(255,255,255,.99), rgba(242,247,251,.98)) !important;
  border: 1px solid rgba(68,130,195,.12) !important;
  box-shadow: 0 18px 34px rgba(15,23,42,.08), inset 0 1px 0 rgba(255,255,255,.90) !important;
  color: #1f2a37 !important;
}
.payrollEmployeeHead{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  margin-bottom:14px;
  padding-bottom:10px;
  border-bottom:1px solid rgba(148,163,184,.18);
}
.payrollEmployeeName{
  font-size: 18px;
  line-height: 1.2;
  font-weight: 700;
  letter-spacing: 0;
  color: #1f2a37 !important;
  text-shadow: none !important;
}

.payrollEmployeeMeta{
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.2;
  font-weight: 500;
  color: rgba(111,108,133,.92) !important;
}

/* sidebar */
.sidebar{
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(244,241,255,.96)) !important;
  border: 1px solid rgba(68,130,195,.10) !important;
  border-radius: 0 !important;
  box-shadow: 0 18px 40px rgba(15,23,42,.08) !important;
}
.sideTitle,
.sideText,
.menuText{
  color: #1f2a37 !important;
}
.sideItem,
.menuItem{
  background: rgba(255,255,255,.82) !important;
  border: 1px solid rgba(68,130,195,.08) !important;
  border-radius: 0 !important;
  box-shadow: none !important;
}
.sideItem:hover,
.menuItem:hover{
  background: rgba(68,130,195,.05) !important;
  border-color: rgba(68,130,195,.16) !important;
}
.sideItem.active,
.menuItem.active{
  background: linear-gradient(180deg, rgba(68,130,195,.10), rgba(59,116,173,.06)) !important;
  border-color: rgba(68,130,195,.20) !important;
  box-shadow: inset 0 -3px 0 rgba(37,99,235,.35) !important;
}
.chev{
  color: #315f8f !important;
}
.navIcon,
.sideIcon,
.icoBox,
.adminToolIcon,
.adminSectionIcon{
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(242,247,251,.98)) !important;
  color: #315f8f !important;
  border-color: rgba(68,130,195,.10) !important;
}

/* admin shells */
.adminToolsShell{
  background: linear-gradient(180deg, rgba(248,246,255,.98), rgba(255,255,255,.98)) !important;
  border: 1px solid rgba(68,130,195,.10) !important;
  box-shadow: 0 18px 40px rgba(15,23,42,.08) !important;
}
.adminToolCard:hover{
  transform: translateY(-2px);
  box-shadow: 0 18px 34px rgba(15,23,42,.12) !important;
}
.adminToolCard.payroll .adminToolIcon{
  background: linear-gradient(180deg, rgba(239,246,255,.98), rgba(219,234,254,.98)) !important;
  color: #2563eb !important;
  border-color: rgba(37,99,235,.16) !important;
}
.adminToolCard.company .adminToolIcon{
  background: linear-gradient(180deg, rgba(242,247,251,.98), rgba(231,239,247,.98)) !important;
  color: #3b74ad !important;
  border-color: rgba(68,130,195,.16) !important;
}
.adminToolCard.onboarding .adminToolIcon,
.adminToolCard.employees .adminToolIcon{
  background: linear-gradient(180deg, rgba(240,253,244,.98), rgba(220,252,231,.98)) !important;
  color: #15803d !important;
  border-color: rgba(34,197,94,.16) !important;
}

/* dashboard mini cards / rows */
.quickMini,
.activityRow,
.activityEmpty,
.dashboardMainMenu .menuItem,
.adminStats .adminStatCard,
.adminSectionCard{
  background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(248,246,255,.96)) !important;
  border: 1px solid rgba(68,130,195,.10) !important;
  box-shadow: 0 10px 22px rgba(15,23,42,.06) !important;
  border-radius: 0 !important;
}
.quickMini .miniIcon{
  color: #000000 !important;
  background: rgba(0,0,0,.06) !important;
  border-color: rgba(0,0,0,.12) !important;
}
.activityRow{
  color: rgba(38,35,58,.88) !important;
}
.activityEmpty{
  color: #6b7785 !important;
  background: rgba(255,255,255,.82) !important;
  border: 1px dashed rgba(68,130,195,.16) !important;
}
.sideInfoRow{
  background: rgba(255,255,255,.84) !important;
  border: 1px solid rgba(34,197,94,.12) !important;
}
.sideInfoLabel{
  color: #5e7a66 !important;
}
.sideInfoValue{
  color: #1f3b2c !important;
}

/* messages */
.message{
  background: rgba(68,130,195,.08) !important;
  border: 1px solid rgba(68,130,195,.14) !important;
  color: #312e81 !important;
}
.message.error{
  background: rgba(220,38,38,.08) !important;
  border-color: rgba(220,38,38,.16) !important;
  color: #991b1b !important;
}

/* MY REPORTS / PLAIN SECTION cards become light too */
.myReportsWeekTable.plainSection,
.payrollEmployeeCard.plainSection{
  background: linear-gradient(180deg, rgba(255,255,255,.99), rgba(248,246,255,.98)) !important;
  border: 1px solid rgba(68,130,195,.12) !important;
  box-shadow: 0 16px 32px rgba(15,23,42,.08) !important;
}
.myReportsWeekTable.plainSection .sub,
.payrollEmployeeCard.plainSection .sub,
.myReportsWeekTable.plainSection .payrollSummaryItem .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem .k,
.myReportsWeekTable.plainSection .payrollSummaryItem:nth-child(1) .k,
.myReportsWeekTable.plainSection .payrollSummaryItem:nth-child(2) .k,
.myReportsWeekTable.plainSection .payrollSummaryItem:nth-child(3) .k,
.myReportsWeekTable.plainSection .payrollSummaryItem:nth-child(4) .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(1) .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(2) .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(3) .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(4) .k,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(5) .k{
  color: rgba(111,108,133,.82) !important;
  -webkit-text-fill-color: rgba(111,108,133,.82) !important;
}
.myReportsWeekTable.plainSection .payrollSummaryItem .v,
.myReportsWeekTable.plainSection .payrollSummaryItem.net .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(1) .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(2) .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(3) .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(4) .v,
.payrollEmployeeCard.plainSection .payrollSummaryItem:nth-child(5) .v{
  color: #1f2a37 !important;
  -webkit-text-fill-color: #1f2a37 !important;
  text-shadow: none !important;
}

/* ===== FINAL TABLE READABILITY FIXES ===== */

/* 1) TIME LOGS: keep all rows bright and readable */
.timeLogsTable tbody tr,
.timeLogsTable tbody tr:nth-child(odd),
.timeLogsTable tbody tr:nth-child(even){
  background: transparent !important;
}

.timeLogsTable tbody tr td,
.timeLogsTable tbody tr:nth-child(odd) td,
.timeLogsTable tbody tr:nth-child(even) td{
  background: #ffffff !important;
  color: #1f2a37 !important;
  -webkit-text-fill-color: #1f2a37 !important;
  text-shadow: none !important;
  border-bottom: 1px solid rgba(226,232,240,.90) !important;
}

.timeLogsTable tbody tr:hover td{
  background: #f5f3ff !important;
  color: #1f2a37 !important;
  -webkit-text-fill-color: #1f2a37 !important;
}

/* 2) EMPLOYEE SITES + LOCATIONS: keep table form controls clean */
.tablewrap td form .input,
.tablewrap td form input,
.tablewrap td form input.input,
.tablewrap td form select,
.tablewrap td form select.input,
.tablewrap td form textarea,
.tablewrap td form textarea.input{
  background: #ffffff !important;
  color: #1f2a37 !important;
  -webkit-text-fill-color: #1f2a37 !important;
  caret-color: #1f2a37 !important;
  border: 1px solid rgba(148,163,184,.36) !important;
  box-shadow: none !important;
  font-weight: 600 !important;
}

.tablewrap td form .input::placeholder,
.tablewrap td form input::placeholder,
.tablewrap td form textarea::placeholder{
  color: #6b7785 !important;
  -webkit-text-fill-color: #6b7785 !important;
}

.tablewrap td form select option,
.tablewrap td form select optgroup{
  background: #ffffff !important;
  color: #1f2a37 !important;
}

/* keep plain numeric/location cells readable */
.tablewrap td.num{
  color: #1f2a37 !important;
  -webkit-text-fill-color: #1f2a37 !important;
}

/* 3) DISTINCT STATUS COLORS */
.chip.ok,
.tablewrap .chip.ok{
  background: #16a34a !important;
  color: #f0fdf4 !important;
  border: 1px solid #15803d !important;
  box-shadow: none !important;
}

.chip.warn,
.tablewrap .chip.warn{
  background: #dc2626 !important;
  color: #fff1f2 !important;
  border: 1px solid #b91c1c !important;
  box-shadow: none !important;
}

.chip.bad,
.tablewrap .chip.bad{
  background: #d97706 !important;
  color: #fffbeb !important;
  border: 1px solid #b45309 !important;
  box-shadow: none !important;
}

/* helper text inside white table sections */
.tablewrap td .sub,
.tablewrap td label.sub{
  color: #6f6c85 !important;
}

/* keep action links readable */
.tablewrap td a[href*="/admin/locations?site="]{
  color: #2563eb !important;
  font-weight: 700 !important;
}

/* reduce clipping on admin management tables */
.tablewrap > table[style*="min-width:980px"]{
  min-width: 860px !important;
  width: 100% !important;
  table-layout: auto !important;
}

.tablewrap > table[style*="min-width:980px"] th,
.tablewrap > table[style*="min-width:980px"] td{
  white-space: normal !important;
  vertical-align: top !important;
}

.tablewrap > table[style*="min-width:980px"] td:last-child,
.tablewrap > table[style*="min-width:980px"] th:last-child{
  min-width: 280px !important;
}



/* ===== softer typography v2 ===== */
body{
  font-size:13px !important;
  -webkit-font-smoothing:antialiased;
  text-rendering:optimizeLegibility;
}

h1,
.headerTop h1,
.dashboardTitle,
.timeLogsTitle,
.adminPageTitle,
.statementTitle{
  font-size:clamp(20px, 3.2vw, 28px) !important;
  font-weight:600 !important;
  line-height:1.08 !important;
  letter-spacing:-.02em !important;
}

h2,
.card h2,
.adminSectionTitle,
.adminToolTitle,
.timeLogsSectionTitle,
.graphTitle,
.sectionTitle{
  font-size:16px !important;
  font-weight:600 !important;
  line-height:1.18 !important;
  letter-spacing:-.01em !important;
}

h3,
.uploadTitle,
.contractTitle{
  font-size:14px !important;
  font-weight:600 !important;
}

strong,
b{
  font-weight:600 !important;
}

.sub,
.timerSub,
.sideInfoLabel,
.adminToolSub,
.adminSectionSub,
.activityHead,
label.sub,
.smallText,
.tableHint,
.muted,
.miniText{
  font-size:12.5px !important;
  font-weight:500 !important;
  line-height:1.45 !important;
  color:#6b7785 !important;
}

.badge,
.badge.admin,
.weekPill,
.chip,
.topBrandBadge,
.dashboardEyebrow,
.timeLogsEyebrow,
.sectionBadge,
.onboardMiniStat .k{
  font-size:11px !important;
  font-weight:600 !important;
  letter-spacing:.03em !important;
}

.sideText,
.menuText{
  font-size:18px !important;
  font-weight:600 !important;
}

.kpi .label,
.kpiFancy .label,
.kpiFancy .sub,
.kpiMini .k,
.graphStat .k,
.payrollSummaryItem .k,
.timeLogsSummaryCard .k,
.adminStatCard .k,
.statementSummaryRow .k,
.statementTotalCard .k{
  font-size:11.5px !important;
  font-weight:500 !important;
  letter-spacing:.01em !important;
  color:#6b7785 !important;
}

.kpi .value,
.kpiFancy .value,
.kpiMini .v,
.graphStat .v,
.payrollSummaryItem .v,
.timeLogsSummaryCard .v,
.adminStatCard .v,
.statementSummaryRow .v,
.statementTotalCard .v,
.netBadge,
.sideInfoValue{
  font-size:clamp(16px, 2.2vw, 22px) !important;
  font-weight:600 !important;
  line-height:1.08 !important;
  letter-spacing:-.02em !important;
}

.kpi .value,
.kpiFancy .value{
  margin-top:4px !important;
}

.tablewrap th,
.weeklyEditTable thead th,
.payrollSheet thead th,
table thead th{
  font-size:11.5px !important;
  font-weight:600 !important;
  letter-spacing:.01em !important;
  color:#6f6b87 !important;
}

.tablewrap td,
.weeklyEditTable tbody td,
.payrollSheet td,
table tbody td{
  font-size:12.5px !important;
  font-weight:500 !important;
  color:#302d43 !important;
}

.tablewrap input.input,
.weeklyEditTable input.input,
.payrollSheet input.input,
.input,
select.input,
input.input,
textarea.input{
  font-size:13px !important;
  font-weight:500 !important;
}

.btn,
.btnSoft,
.btnTiny,
.adminPrimaryBtn,
.payrollMenuToggle,
button{
  font-size:13px !important;
  font-weight:600 !important;
  letter-spacing:0 !important;
}

@media (min-width:980px){
  .kpi .value,
  .kpiFancy .value,
  .kpiMini .v,
  .graphStat .v,
  .payrollSummaryItem .v,
  .timeLogsSummaryCard .v,
  .adminStatCard .v,
  .statementSummaryRow .v,
  .statementTotalCard .v,
  .netBadge,
  .sideInfoValue{
    font-size:20px !important;
  }

  .tablewrap th,
  .weeklyEditTable thead th,
  .payrollSheet thead th,
  table thead th{
    font-size:11px !important;
  }

  .tablewrap td,
  .weeklyEditTable tbody td,
  .payrollSheet td,
  table tbody td{
    font-size:12px !important;
  }
}


/* ===== shared back buttons ===== */
.pageBackRow{
  display:flex;
  align-items:center;
  margin:0 0 12px;
}
.printToolbar .pageBackRow,
.toolbar .pageBackRow{
  margin:0;
}
.pageBackBtn,
.pageBackBtn:link,
.pageBackBtn:visited{
  display:inline-block;
  width:auto;
  height:auto;
  min-width:0;
  padding:0;
  border:0;
  border-radius:0 !important;
  background:none;
  color:#000;
  text-decoration:none;
  box-shadow:none;
  cursor:pointer;
  font-size:14px;
  font-weight:400;
  line-height:1.2;
}
.pageBackBtn:hover{
  transform:none;
  border:0;
  box-shadow:none;
  background:none;
}
.pageBackBtn span{
  display:inline;
  font-size:inherit;
  font-weight:inherit;
  line-height:inherit;
  transform:none;
}

.dashboardMiniStatus{
  display:block;
  margin:14px 0 16px;
}

.dashboardMiniStatusCard{
  background:#fff;
  border:1px solid rgba(148,163,184,.20);
  box-shadow:none;
  border-radius:0 !important;
  padding:16px 18px;
}

.dashboardMiniStatusSplit{
  display:grid;
  grid-template-columns:minmax(260px, 1fr) minmax(300px, 1.25fr);
  gap:18px;
  align-items:center;
}

.dashboardMiniStatusPane{
  min-width:0;
}

.dashboardMiniDivider{
  width:1px;
  align-self:stretch;
  background:rgba(148,163,184,.22);
}

.dashboardMiniStatusTop{
  display:flex;
  align-items:center;
  gap:12px;
  margin-bottom:10px;
}

.dashboardMiniStatusIcon{
  width:44px;
  height:44px;
  border-radius:0 !important;
  display:flex;
  align-items:center;
  justify-content:center;
  background:rgba(59,130,246,.08);
  border:1px solid rgba(59,130,246,.16);
  color:#0f172a;
  flex:0 0 44px;
}

.dashboardMiniStatusIcon svg{
  width:22px;
  height:22px;
  display:block;
}

.dashboardMiniStatusLabel{
  font-size:15px;
  font-weight:900;
  color:#0f172a;
  line-height:1.1;
}

.dashboardMiniStatusSub{
  margin-top:4px;
  font-size:13px;
  color:#64748b;
  line-height:1.25;
}

.dashboardMiniStatusValue{
  display:flex;
  align-items:center;
  min-height:38px;
}

.dashboardMiniTargetRow{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  margin:8px 0 8px;
  color:#0f172a;
  font-size:16px;
  font-weight:900;
}

.dashboardMiniTargetBar{
  width:100%;
  height:12px;
  border-radius:0 !important;
  background:#dbeafe;
  overflow:hidden;
}

.dashboardMiniTargetBar span{
  display:block;
  height:100%;
  border-radius:0 !important;
  background:#4f86c6;
  transition:width .25s ease;
}

@media (max-width: 700px){
  .dashboardMiniStatusCard{
    padding:14px;
  }

  .dashboardMiniStatusSplit{
    grid-template-columns:1fr;
    gap:14px;
  }

  .dashboardMiniDivider{
    display:none;
  }

  .dashboardMiniStatusIcon{
    width:40px;
    height:40px;
    flex-basis:40px;
  }

  .dashboardMiniStatusLabel{
    font-size:14px;
  }

  .dashboardMiniStatusSub{
    font-size:12px;
  }
}

.rangeDetailTable{
  width:100%;
  min-width:980px;
  table-layout:fixed;
  border-collapse:separate;
  border-spacing:0;
}

.rangeDetailTable th,
.rangeDetailTable td{
  padding:12px 10px;
  vertical-align:middle;
}

.rangeDetailTable th.num,
.rangeDetailTable td.num{
  text-align:right;
  font-variant-numeric: tabular-nums;
}

.rangeDetailTable th.center,
.rangeDetailTable td.center{
  text-align:center;
}

.rangeDetailTable th:nth-child(1),
.rangeDetailTable td:nth-child(1){
  width:18%;
}

.rangeDetailTable th:nth-child(2),
.rangeDetailTable td:nth-child(2){
  width:7%;
}

.rangeDetailTable th:nth-child(3),
.rangeDetailTable td:nth-child(3){
  width:12%;
}

.rangeDetailTable th:nth-child(4),
.rangeDetailTable td:nth-child(4),
.rangeDetailTable th:nth-child(5),
.rangeDetailTable td:nth-child(5){
  width:8%;
}

.rangeDetailTable th:nth-child(6),
.rangeDetailTable td:nth-child(6){
  width:7%;
}

.rangeDetailTable th:nth-child(7),
.rangeDetailTable td:nth-child(7),
.rangeDetailTable th:nth-child(8),
.rangeDetailTable td:nth-child(8),
.rangeDetailTable th:nth-child(9),
.rangeDetailTable td:nth-child(9){
  width:10%;
}
</style>

<style id="timiq-corporate-blue-override">
:root{
  --navy:#4482c3 !important;
  --navy2:#3b74ad !important;
  --navySoft:rgba(68,130,195,.10) !important;
  --text:#1f2a37 !important;
  --muted:#6b7785 !important;
  --shadow:0 10px 24px rgba(15,23,42,.06) !important;
  --shadow2:0 16px 34px rgba(15,23,42,.10) !important;
}
.btn,
.btnSoft,
.adminPrimaryBtn,
.payrollMenuToggle{
  background: linear-gradient(135deg, #4f89c7 0%, #3b74ad 100%) !important;
  border-color: rgba(68,130,195,.16) !important;
  box-shadow: 0 10px 18px rgba(15,23,42,.10) !important;
}
.btn:hover,
.btnSoft:hover,
.adminPrimaryBtn:hover,
.payrollMenuToggle:hover{
  transform: translateY(-1px);
  box-shadow: 0 12px 22px rgba(15,23,42,.12) !important;
}
.badge,
.badge.admin,
.weekPill{
  background: linear-gradient(180deg, rgba(68,130,195,.12), rgba(59,116,173,.08)) !important;
  color:#315f8f !important;
  border-color: rgba(68,130,195,.16) !important;
  box-shadow: 0 4px 10px rgba(15,23,42,.05) !important;
}
.graphCard,
.tablewrap,
.payrollWrap,
.card,
.kpiMini,
.kpi,
.adminToolCard,
.adminSectionCard,
.payrollSummaryItem,
.contractBox{
  box-shadow: 0 12px 26px rgba(15,23,42,.07) !important;
}
.bar{
  background: linear-gradient(180deg, #5d98cf 0%, #3b74ad 100%) !important;
  box-shadow: 0 10px 18px rgba(15,23,42,.08) !important;
}
.input:focus,
select.input:focus,
input.input:focus,
textarea.input:focus{
  border-color: rgba(68,130,195,.34) !important;
  box-shadow: 0 0 0 4px rgba(68,130,195,.10) !important;
}

/* readable solid-blue table headers */
.tablewrap th,
.weeklyEditTable thead th,
.payrollSheet thead th,
.timeLogsTable th,
.rangeDetailTable th{
  background:#4f89c7 !important;
  color:#ffffff !important;
  border-bottom:1px solid rgba(49,95,143,.30) !important;
  text-shadow:none !important;
}
.tablewrap th *,
.weeklyEditTable thead th *,
.payrollSheet thead th *,
.timeLogsTable th *,
.rangeDetailTable th *{
  color:#ffffff !important;
}

:root{
  --bottom-nav-height: 74px;
  --bottom-nav-offset: 0px;
}

@media (max-width: 979px){
  body{
    padding-bottom: calc(var(--bottom-nav-height) + var(--bottom-nav-offset) + env(safe-area-inset-bottom));
  }

  .sidebar{
    display:none !important;
  }

  .bottomNav{
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 1200;
    transform: translateY(calc(-1 * var(--bottom-nav-offset)));
    display: flex !important;
    align-items: stretch;
    justify-content: space-between;
    gap: 2px;
    padding: 8px 8px calc(8px + env(safe-area-inset-bottom));
    background: rgba(255,255,255,.98);
    border-top: 1px solid #d9e4f1;
    box-shadow: 0 -10px 30px rgba(15,23,42,.10);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
  }

  .bottomNav::-webkit-scrollbar{
    display:none;
  }

  .bottomNavItem{
    flex: 1 0 64px;
    min-width: 64px;
    min-height: 58px;
    display: flex !important;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    text-decoration: none !important;
    color: #64748b;
    font-size: 11px;
    font-weight: 700;
    line-height: 1.05;
    text-align: center;
    border-radius: 14px;
    padding: 4px 2px;
  }

  .bottomNavItem:hover,
  .bottomNavItem:active{
    background: rgba(59,116,173,.06);
  }

  .bottomNavItem.active{
    color: #1f2d63;
    background: rgba(59,116,173,.08);
  }

  .bottomNavIcon{
    width: 22px;
    height: 22px;
    display:flex;
    align-items:center;
    justify-content:center;
    flex: 0 0 auto;
  }

  .bottomNavIcon svg{
    width: 20px;
    height: 20px;
    display:block;
  }

  .bottomNavText{
    display:block;
    font-size: 11px;
    font-weight: 700;
    line-height: 1.05;
    white-space: nowrap;
  }
}

@media (min-width:980px){
  .shell:has(.sidebar){
    display:grid !important;
    grid-template-columns: 220px minmax(0, 1fr) !important;
    gap:14px !important;
    align-items:start !important;
    max-width:none !important;
  }

  .sidebar{
    display:block !important;
    width:220px !important;
    min-width:220px !important;
    padding:10px 8px !important;
  }

  .sideItem{
    padding:10px 12px !important;
    min-height:50px !important;
    margin-top:8px !important;
  }

  .sideLeft{
    gap:10px !important;
  }

  .sideIcon{
    width:24px !important;
    height:24px !important;
  }

  .sideIcon svg,
  .sideIcon img{
    width:24px !important;
    height:24px !important;
  }

  .sideText{
    font-size:14px !important;
    font-weight:500 !important;
  }

  .chev{
    font-size:20px !important;
  }
}

</style>

"""

CONTRACT_TEXT = """Contract

By signing this agreement, you confirm that while carrying out bricklaying services (and related works) for us, you are acting as a self-employed subcontractor and not as an employee.

You agree to:

Behave professionally at all times while on site

Use reasonable efforts to complete all work within agreed timeframes

Comply with all Health & Safety requirements, including rules on working hours, site conduct, and site security

Be responsible for the standard of your work and rectify any defects at your own cost and in your own time

Maintain valid public liability insurance

Supply your own hand tools

Manage and pay your own Tax and National Insurance contributions (CIS tax will be deducted by us and submitted to HMRC)

You are not required to:

Transfer to another site unless you choose to do so and agree a revised rate

Submit written quotations or tenders; all rates will be agreed verbally

Supply major equipment or materials

Carry out work you do not wish to accept; there is no obligation to accept work offered

Work set or fixed hours

Submit invoices; all payments will be processed under the CIS scheme and a payment statement will be provided

You have the right to:

Decide how the work is performed

Leave the site without seeking permission (subject to notifying us for Health & Safety reasons)

Provide a substitute with similar skills and experience, provided you inform us in advance. You will remain responsible for paying them

Terminate this agreement at any time without notice

Seek independent legal advice before signing and retain a copy of this agreement

You do not have the right to:

Receive sick pay or payment for work cancelled due to adverse weather

Use our internal grievance procedure

Describe yourself as an employee of our company

By signing this agreement, you accept these terms and acknowledge that they define the working relationship between you and us.

You also agree that this document represents the entire agreement between both parties, excluding any verbal discussions relating solely to pricing or work location.

Contractor Relationship

For the purposes of this agreement, you are the subcontractor, and we are the contractor.

We agree to:

Confirm payment rates verbally, either as a fixed price or an hourly rate, before work begins

We are not required to:

Guarantee or offer work at any time

We have the right to:

End this agreement without notice

Obtain legal advice prior to signing

We do not have the right to:

Direct or control how you carry out your work

Expect immediate availability or require you to prioritise our work over other commitments

By signing this agreement, we confirm our acceptance of its terms and that they govern the relationship between both parties.

This document represents the full agreement between us, excluding verbal discussions relating only to pricing or work location.

General Terms

This agreement is governed by the laws of England and Wales

If any part of this agreement is breached or found unenforceable, the remaining clauses will continue to apply
""".strip()