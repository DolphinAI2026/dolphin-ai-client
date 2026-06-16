"""account-service 管理后台单页 (self-contained, Vue 3 + Element Plus CDN)。

设计语言对齐「账号管理端 Design System」(Claude Design, 2026-06-16):
克制的企业级控制台 —— 冷调 slate 中性色承载九成画面, 单一 console blue (#2566e8) 作唯一强调色,
语义色只用于状态, 发丝边框 + 极轻阴影, 表格为核心载体, tabular 数字。系统字体栈 (PingFang SC /
Segoe UI), 不引入 webfont。Element Plus 主题变量被改写到设计 token 上, 外壳/卡片/图表手写。

信息架构: 概览 / 账号管理 / 租户管理 / 登录日志 / 操作审计 / 设置。
后端当前只有账号 CRUD(开号/停用/改密/列表) —— 概览只展示可由账号列表真实推导的指标,
活跃度/登录健康/安全信号等依赖 login_events / admin_audit 埋点(spec §7)的指标显示「待埋点」占位;
租户/审计/设置为 P3「规划中」空状态。绝不造假数据。

页面经 ingress 挂在 /account-api 下, API 走相对前缀 const API='/account-api'。GET /admin-ui 返回。
"""

ADMIN_UI_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>桌面账号管理端</title>
<link rel="stylesheet" href="https://unpkg.com/element-plus/dist/index.css">
<style>
/* ============================================================
   DESIGN TOKENS — 账号管理端 (Account Console)
   ============================================================ */
:root{
  /* Neutrals (cool slate) */
  --gray-0:#ffffff; --gray-25:#fbfcfd; --gray-50:#f6f8fa; --gray-100:#eef1f5;
  --gray-150:#e6eaef; --gray-200:#dde2e9; --gray-300:#cdd4dd; --gray-400:#a7afba;
  --gray-500:#7b838f; --gray-600:#5a626d; --gray-700:#3c434d; --gray-800:#252a31; --gray-900:#14171c;
  /* Primary (console blue) */
  --blue-50:#eef3fe; --blue-100:#dbe6fd; --blue-200:#b6cdfb; --blue-300:#85a9f6;
  --blue-400:#5285ef; --blue-500:#2566e8; --blue-600:#1b54cc; --blue-700:#1745a6;
  /* Semantic */
  --green-50:#e8f6ed; --green-100:#cdebd7; --green-500:#18a058; --green-600:#128048; --green-700:#0d6638;
  --amber-50:#fdf4e3; --amber-100:#fae6c2; --amber-500:#d98a14; --amber-600:#b8710d; --amber-700:#93590a;
  --red-50:#fdecea; --red-100:#fad5d1; --red-500:#d92d20; --red-600:#ba241a; --red-700:#971c14;
  --cyan-50:#e7f5f8; --cyan-100:#c7e8ef; --cyan-500:#0d8aa8; --cyan-600:#0a6f88;
  /* Semantic aliases */
  --text-primary:var(--gray-900); --text-secondary:var(--gray-600); --text-muted:var(--gray-500);
  --text-disabled:var(--gray-400); --text-inverse:var(--gray-0); --text-link:var(--blue-500);
  --surface-page:var(--gray-50); --surface-card:var(--gray-0); --surface-sunken:var(--gray-50);
  --surface-hover:var(--gray-100); --surface-active:var(--blue-50);
  --border-subtle:var(--gray-150); --border-default:var(--gray-200); --border-strong:var(--gray-300); --border-focus:var(--blue-500);
  --accent:var(--blue-500); --accent-hover:var(--blue-600); --accent-active:var(--blue-700);
  --accent-subtle:var(--blue-50); --accent-border:var(--blue-200);
  --status-success-fg:var(--green-600); --status-success-bg:var(--green-50); --status-success-border:var(--green-100); --status-success-dot:var(--green-500);
  --status-warning-fg:var(--amber-600); --status-warning-bg:var(--amber-50); --status-warning-border:var(--amber-100); --status-warning-dot:var(--amber-500);
  --status-danger-fg:var(--red-600); --status-danger-bg:var(--red-50); --status-danger-border:var(--red-100); --status-danger-dot:var(--red-500);
  --status-neutral-fg:var(--gray-600); --status-neutral-bg:var(--gray-100); --status-neutral-border:var(--gray-200); --status-neutral-dot:var(--gray-400);
  --status-info-fg:var(--cyan-600); --status-info-bg:var(--cyan-50); --status-info-border:var(--cyan-100); --status-info-dot:var(--cyan-500);
  /* Type */
  --font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Helvetica Neue",Helvetica,Arial,sans-serif;
  --font-mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono","Courier New",monospace;
  /* Spacing / radius / layout */
  --radius-xs:3px; --radius-sm:4px; --radius-md:6px; --radius-lg:8px; --radius-full:999px;
  --sidebar-width:224px; --topbar-height:56px; --page-max:1440px;
  --row-height:48px; --cell-pad-x:16px;
  --focus-ring:0 0 0 3px rgba(37,102,232,.18);
  /* Elevation */
  --shadow-xs:0 1px 2px rgba(20,23,28,.04),0 0 0 1px rgba(20,23,28,.04);
  --shadow-sm:0 1px 3px rgba(20,23,28,.06),0 1px 2px rgba(20,23,28,.04);
  --shadow-md:0 4px 12px rgba(20,23,28,.10),0 2px 4px rgba(20,23,28,.05);
  --shadow-lg:0 16px 40px rgba(20,23,28,.16),0 4px 12px rgba(20,23,28,.08);
}

/* ============================================================
   ELEMENT PLUS THEME OVERRIDES → design tokens
   ============================================================ */
:root{
  --el-color-primary:#2566e8;
  --el-color-primary-light-3:#5285ef; --el-color-primary-light-5:#85a9f6;
  --el-color-primary-light-7:#b6cdfb; --el-color-primary-light-8:#dbe6fd; --el-color-primary-light-9:#eef3fe;
  --el-color-primary-dark-2:#1b54cc;
  --el-color-success:#18a058; --el-color-warning:#d98a14; --el-color-danger:#d92d20; --el-color-error:#d92d20; --el-color-info:#5a626d;
  --el-border-radius-base:4px; --el-border-radius-small:3px; --el-border-radius-round:6px;
  --el-font-family:var(--font-sans); --el-font-size-base:14px;
  --el-text-color-primary:var(--gray-900); --el-text-color-regular:var(--gray-700); --el-text-color-secondary:var(--gray-600); --el-text-color-placeholder:var(--gray-500);
  --el-border-color:var(--gray-200); --el-border-color-light:var(--gray-150); --el-border-color-lighter:var(--gray-150); --el-border-color-extra-light:var(--gray-100);
  --el-fill-color-light:var(--gray-50); --el-fill-color-lighter:var(--gray-50); --el-fill-color-blank:#fff;
  --el-bg-color:#fff; --el-bg-color-overlay:#fff;
  --el-table-header-bg-color:var(--gray-50); --el-table-header-text-color:var(--gray-600);
  --el-table-border-color:var(--gray-150); --el-table-row-hover-bg-color:var(--gray-100);
  --el-table-text-color:var(--gray-900);
  --el-component-size:34px; --el-component-size-small:28px; --el-component-size-large:40px;
  --el-box-shadow-light:var(--shadow-md);
}

/* ============================================================
   BASE
   ============================================================ */
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;padding:0;height:100%}
body{font-family:var(--font-sans);font-size:14px;color:var(--text-primary);background:var(--surface-page);
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
h1,h2,h3,h4{margin:0;font-weight:600;color:var(--text-primary);line-height:1.25}
p{margin:0}
a{color:var(--text-link);text-decoration:none}
.num,.tabular{font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1,"lnum" 1}
.mono{font-family:var(--font-mono)}
*{scrollbar-width:thin;scrollbar-color:var(--gray-300) transparent}
*::-webkit-scrollbar{width:10px;height:10px}
*::-webkit-scrollbar-track{background:transparent}
*::-webkit-scrollbar-thumb{background:var(--gray-300);border:3px solid transparent;background-clip:padding-box;border-radius:var(--radius-full)}
*::-webkit-scrollbar-thumb:hover{background:var(--gray-400);background-clip:padding-box}
.ico{display:inline-flex;align-items:center;justify-content:center;flex:none;line-height:0}
.ico svg{display:block}

/* ============================================================
   LOGIN
   ============================================================ */
.login-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;background:var(--surface-page);padding:24px}
.login-card{width:392px;max-width:100%;background:var(--surface-card);border:1px solid var(--border-default);
  border-radius:var(--radius-lg);padding:36px 34px;box-shadow:var(--shadow-sm)}
.login-head{display:flex;flex-direction:column;align-items:center;gap:14px;margin-bottom:28px}
.wordmark{width:46px;height:46px;border-radius:var(--radius-md);display:flex;align-items:center;justify-content:center;
  background:var(--accent);color:#fff;font-weight:700;font-size:21px;flex:none}
.login-title{font-size:18px;font-weight:600}
.login-sub{font-size:13px;color:var(--text-muted);margin-top:-6px}
.login-field{margin-bottom:14px}
.login-field > span{display:block;font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px}

/* ============================================================
   APP SHELL
   ============================================================ */
.shell{display:flex;height:100vh;min-height:0;background:var(--surface-page)}
.sidebar{width:var(--sidebar-width);flex:none;background:var(--surface-card);border-right:1px solid var(--border-default);display:flex;flex-direction:column}
.side-head{height:var(--topbar-height);display:flex;align-items:center;gap:10px;padding:0 16px;border-bottom:1px solid var(--border-subtle)}
.side-head .wordmark{width:28px;height:28px;border-radius:var(--radius-sm);font-size:14px}
.side-head .st{line-height:1.2}
.side-head .st b{display:block;font-size:14px;font-weight:600}
.side-head .st small{font-size:12px;color:var(--text-muted)}
.side-nav{flex:1;padding:10px 8px;display:flex;flex-direction:column;gap:2px;overflow-y:auto}
.nav-item{display:flex;align-items:center;gap:10px;width:100%;height:38px;padding:0 10px;border:none;border-radius:var(--radius-sm);
  background:transparent;color:var(--text-secondary);font:500 14px/1 var(--font-sans);cursor:pointer;text-align:left;
  transition:background .12s,color .12s}
.nav-item .ico{color:var(--text-muted)}
.nav-item:hover{background:var(--surface-hover)}
.nav-item.active{background:var(--surface-active);color:var(--accent);font-weight:600}
.nav-item.active .ico{color:var(--accent)}
.nav-item .nl{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nav-count{min-width:20px;height:18px;padding:0 6px;display:inline-flex;align-items:center;justify-content:center;
  border-radius:var(--radius-full);background:var(--gray-150);color:var(--text-muted);font:500 12px/1 var(--font-sans)}
.nav-item.active .nav-count{background:var(--accent);color:#fff}
.side-foot{padding:10px 12px;border-top:1px solid var(--border-subtle);display:flex;align-items:center;gap:10px}
.side-foot .meta{flex:1;min-width:0;line-height:1.3}
.side-foot .meta b{display:block;font:500 13px/1.2 var(--font-sans);color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.side-foot .meta small{font-size:12px;color:var(--text-muted);font-family:var(--font-mono)}
.icon-btn{width:30px;height:30px;border:none;background:transparent;border-radius:var(--radius-sm);color:var(--text-muted);
  display:inline-flex;align-items:center;justify-content:center;cursor:pointer;transition:background .12s,color .12s;flex:none}
.icon-btn:hover{background:var(--surface-hover);color:var(--text-primary)}
.icon-btn.danger:hover{background:var(--red-50);color:var(--red-600)}

.main{flex:1;min-width:0;display:flex;flex-direction:column}
.topbar{height:var(--topbar-height);flex:none;display:flex;align-items:center;gap:16px;padding:0 24px;
  background:var(--surface-card);border-bottom:1px solid var(--border-default)}
.topbar-search{width:320px;max-width:42vw}
.topbar-right{margin-left:auto;display:flex;align-items:center;gap:8px}
.bell{position:relative;display:inline-flex}
.bell .dot{position:absolute;top:5px;right:5px;width:7px;height:7px;border-radius:999px;background:var(--red-500);border:1.5px solid var(--surface-card)}
.content{flex:1;min-height:0;overflow-y:auto}

/* avatar */
.avatar{display:inline-flex;align-items:center;justify-content:center;flex:none;border-radius:var(--radius-sm);
  font-weight:600;user-select:none;background:var(--blue-50);color:var(--blue-600);overflow:hidden}

/* ============================================================
   PAGE PRIMITIVES
   ============================================================ */
.page{padding:24px;max-width:var(--page-max);margin:0 auto}
.page-head{display:flex;align-items:flex-start;gap:16px;margin-bottom:20px}
.page-head .ph-main{flex:1;min-width:0}
.page-title{font-size:20px;font-weight:600;line-height:1.3}
.page-desc{margin-top:4px;font-size:14px;color:var(--text-muted)}
.page-head .ph-actions{display:flex;gap:8px;flex:none}

.card{background:var(--surface-card);border:1px solid var(--border-default);border-radius:var(--radius-md);margin-bottom:16px}
.card.pad{padding:16px 18px}
.card-head{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--border-subtle)}
.card-head .ct{font-size:15px;font-weight:600}
.card-head .cs{font-size:13px;color:var(--text-muted)}
.card-head .ca{margin-left:auto;display:flex;align-items:center;gap:8px}
.card-body{padding:16px 18px}

/* KPI / stat cards */
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px}
.stat-card{background:var(--surface-card);border:1px solid var(--border-default);border-radius:var(--radius-md);
  padding:16px 18px;display:flex;flex-direction:column;gap:10px;min-width:0}
.stat-card.muted{background:var(--gray-25);border-style:dashed}
.stat-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.stat-label{font:500 13px/1.2 var(--font-sans);color:var(--text-secondary)}
.stat-ic{color:var(--text-muted);display:inline-flex}
.stat-val{display:flex;align-items:baseline;gap:5px}
.stat-val .num{font:600 30px/1 var(--font-sans);color:var(--text-primary);letter-spacing:-.01em}
.stat-card.muted .stat-val .num{color:var(--text-disabled)}
.stat-unit{font-size:12px;color:var(--text-muted)}
.stat-hint{font-size:12px;color:var(--text-muted);min-height:16px}

/* distributions */
.dist-grid{display:grid;grid-template-columns:1fr 1fr 1.3fr;gap:16px;margin-bottom:16px}
.donut-wrap{display:flex;align-items:center;gap:20px;padding:6px 2px}
.donut{width:128px;height:128px;border-radius:50%;flex:none;position:relative;
  -webkit-mask:radial-gradient(transparent 56%,#000 57%);mask:radial-gradient(transparent 56%,#000 57%)}
.donut-hole{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
.donut-total{font:600 22px/1 var(--font-sans);color:var(--text-primary)}
.donut-legend{flex:1;min-width:0;display:flex;flex-direction:column;gap:8px}
.leg{display:flex;align-items:center;gap:8px;font-size:13px}
.leg-dot{width:9px;height:9px;border-radius:var(--radius-xs);flex:none}
.leg-label{color:var(--text-secondary)}
.leg-val{margin-left:auto;color:var(--text-primary);font-weight:500}
.bars{display:flex;flex-direction:column;gap:11px;padding:4px 2px}
.bar-row{display:flex;align-items:center;gap:10px;font-size:13px}
.bar-label{width:64px;flex:none;color:var(--text-secondary);font-family:var(--font-mono);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-track{flex:1;height:8px;background:var(--gray-100);border-radius:var(--radius-full);overflow:hidden}
.bar-fill{height:100%;background:var(--accent);border-radius:var(--radius-full)}
.bar-val{width:34px;flex:none;text-align:right;color:var(--text-primary);font-weight:500}

/* status badge */
.sbadge{display:inline-flex;align-items:center;gap:5px;height:22px;padding:0 8px;border-radius:var(--radius-xs);
  font:500 13px/1 var(--font-sans);white-space:nowrap;border:1px solid transparent}
.sbadge-dot{width:6px;height:6px;border-radius:var(--radius-full);flex:none}
.sbadge.t-success{color:var(--status-success-fg);background:var(--status-success-bg);border-color:var(--status-success-border)}
.sbadge.t-success .sbadge-dot{background:var(--status-success-dot)}
.sbadge.t-warning{color:var(--status-warning-fg);background:var(--status-warning-bg);border-color:var(--status-warning-border)}
.sbadge.t-warning .sbadge-dot{background:var(--status-warning-dot)}
.sbadge.t-danger{color:var(--status-danger-fg);background:var(--status-danger-bg);border-color:var(--status-danger-border)}
.sbadge.t-danger .sbadge-dot{background:var(--status-danger-dot)}
.sbadge.t-info{color:var(--status-info-fg);background:var(--status-info-bg);border-color:var(--status-info-border)}
.sbadge.t-info .sbadge-dot{background:var(--status-info-dot)}
.sbadge.t-accent{color:var(--accent);background:var(--accent-subtle);border-color:var(--accent-border)}
.sbadge.t-accent .sbadge-dot{background:var(--accent)}
.sbadge.t-neutral{color:var(--status-neutral-fg);background:var(--status-neutral-bg);border-color:var(--status-neutral-border)}
.sbadge.t-neutral .sbadge-dot{background:var(--status-neutral-dot)}

/* filter & bulk bars */
.filter-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.filter-bar .el-input{width:260px}
.filter-bar .el-select{width:140px}
.bulk-bar{display:flex;align-items:center;gap:12px;padding:9px 14px;margin-bottom:12px;
  background:var(--accent-subtle);border:1px solid var(--accent-border);border-radius:var(--radius-md)}
.bulk-bar .bx{font:500 13px/1 var(--font-sans);color:var(--text-primary)}
.bulk-bar .bx b{font-variant-numeric:tabular-nums}
.bulk-bar .ba{margin-left:auto;display:flex;gap:8px}

/* table cell helpers */
.cell-user{display:flex;align-items:center;gap:10px}
.cell-user .cu{line-height:1.3;min-width:0}
.cell-user .cu b{font-weight:500;color:var(--text-primary)}
.cell-user .cu small{display:block;font-size:12px;color:var(--text-muted);font-family:var(--font-mono)}
.row-actions{display:flex;justify-content:flex-end;gap:2px}
.muted{color:var(--text-muted)}

/* notice band */
.notice{display:flex;align-items:flex-start;gap:10px;padding:12px 14px;border-radius:var(--radius-md);
  background:var(--status-info-bg);border:1px solid var(--status-info-border);margin-bottom:16px}
.notice .ico{color:var(--status-info-fg);margin-top:1px}
.notice .nx{font:500 13px/1.55 var(--font-sans);color:var(--text-secondary)}
.notice code{font-family:var(--font-mono);color:var(--text-primary);font-size:12px;background:rgba(13,138,168,.08);padding:1px 4px;border-radius:3px}

/* empty / placeholder */
.empty{padding:48px 24px;text-align:center;display:flex;flex-direction:column;align-items:center;gap:10px}
.empty .ei{width:44px;height:44px;border-radius:var(--radius-md);background:var(--gray-100);color:var(--text-muted);display:flex;align-items:center;justify-content:center}
.empty .et{font-size:15px;font-weight:600;color:var(--text-primary)}
.empty .ed{font-size:13px;color:var(--text-muted);max-width:380px}

/* section eyebrow */
.eyebrow{display:flex;align-items:center;gap:8px;margin:4px 0 12px;font:600 13px/1 var(--font-sans);color:var(--text-secondary);letter-spacing:.02em}
.eyebrow .pill{font-weight:500;font-size:12px;color:var(--status-warning-fg);background:var(--status-warning-bg);border:1px solid var(--status-warning-border);border-radius:var(--radius-xs);padding:2px 6px;letter-spacing:0}

/* detail */
.detail-bc{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--text-muted);margin-bottom:16px}
.detail-bc a{color:var(--text-secondary);cursor:pointer}
.detail-bc a:hover{color:var(--accent)}
.detail-id{display:flex;align-items:center;gap:16px;margin-bottom:20px}
.detail-id .di{flex:1;min-width:0}
.detail-id .di .dn{display:flex;align-items:center;gap:10px}
.detail-id .di .dn h1{font-size:20px;font-weight:600}
.detail-id .di .du{margin-top:4px;font-size:14px;color:var(--text-muted);font-family:var(--font-mono)}
.detail-id .da{display:flex;gap:8px;flex:none}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--border-default);margin-bottom:20px}
.tab{height:38px;padding:0 14px;border:none;background:transparent;cursor:pointer;font:500 14px/1 var(--font-sans);
  color:var(--text-secondary);border-bottom:2px solid transparent;margin-bottom:-1px;display:inline-flex;align-items:center;gap:7px}
.tab:hover{color:var(--text-primary)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:600}
.tab .tb{min-width:18px;height:18px;padding:0 5px;border-radius:var(--radius-full);background:var(--gray-150);color:var(--text-muted);font:500 12px/1 var(--font-sans);display:inline-flex;align-items:center;justify-content:center}
.tab.active .tb{background:var(--accent);color:#fff}
.fields{display:grid;grid-template-columns:repeat(3,1fr);gap:20px 32px}
.field{display:flex;flex-direction:column;gap:4px}
.field .fl{font-size:12px;color:var(--text-muted)}
.field .fv{font:500 14px/1.4 var(--font-sans);color:var(--text-primary)}
.field .fv.wait{color:var(--text-disabled);font-weight:400}

/* element-plus dialog rounding */
.el-dialog{border-radius:var(--radius-lg)}
.dlg-body{display:flex;flex-direction:column;gap:14px;padding-top:2px}
.dlg-field > span{display:block;font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:6px}
.dlg-hint{font-size:12px;color:var(--text-muted);line-height:1.5}
@media (max-width:680px){
  .sidebar{display:none}
  .kpi-grid{grid-template-columns:repeat(2,1fr)}
  .dist-grid{grid-template-columns:1fr}
  .fields{grid-template-columns:1fr 1fr}
}
</style>
</head>
<body>
<div id="app">

  <!-- ===================== LOGIN ===================== -->
  <div v-if="!token" class="login-wrap">
    <div class="login-card">
      <div class="login-head">
        <div class="wordmark">账</div>
        <div class="login-title">桌面账号管理端</div>
        <div class="login-sub">account-service · 管理员登录</div>
      </div>
      <div class="login-field">
        <span>用户名</span>
        <el-input v-model="loginForm.username" placeholder="管理员用户名" size="large" clearable @keyup.enter="login"></el-input>
      </div>
      <div class="login-field">
        <span>密码</span>
        <el-input v-model="loginForm.password" type="password" placeholder="密码" size="large" show-password @keyup.enter="login"></el-input>
      </div>
      <el-button type="primary" size="large" style="width:100%;margin-top:6px" :loading="loggingIn" @click="login">登录</el-button>
    </div>
  </div>

  <!-- ===================== SHELL ===================== -->
  <div v-else class="shell">
    <!-- sidebar -->
    <aside class="sidebar">
      <div class="side-head">
        <div class="wordmark">账</div>
        <div class="st"><b>账号管理端</b><small>account-service</small></div>
      </div>
      <nav class="side-nav">
        <button v-for="n in NAV" :key="n.key" class="nav-item" :class="{active: page===n.key && !detail}" @click="go(n.key)">
          <ico :name="n.icon" :size="17"></ico>
          <span class="nl">{{ n.label }}</span>
          <span v-if="n.key==='accounts' && accounts.length" class="nav-count">{{ accounts.length }}</span>
        </button>
      </nav>
      <div class="side-foot">
        <span class="avatar" style="width:30px;height:30px;font-size:12px">{{ initials(me) }}</span>
        <div class="meta"><b>{{ me || '管理员' }}</b><small>platform admin</small></div>
        <button class="icon-btn danger" title="退出" @click="logout"><ico name="logout" :size="16"></ico></button>
      </div>
    </aside>

    <!-- main -->
    <div class="main">
      <header class="topbar">
        <div class="topbar-search">
          <el-input v-model="q" placeholder="搜索账号 / 用户名" clearable @focus="go('accounts')" @keyup.enter="go('accounts')">
            <template #prefix><ico name="search" :size="15"></ico></template>
          </el-input>
        </div>
        <div class="topbar-right">
          <button class="icon-btn bell" title="通知"><ico name="bell" :size="18"></ico><span class="dot"></span></button>
          <sbadge tone="info">P1 · 灰度</sbadge>
        </div>
      </header>

      <main class="content">

        <!-- ---------- DASHBOARD ---------- -->
        <div v-if="page==='dashboard' && !detail" class="page">
          <div class="page-head">
            <div class="ph-main">
              <div class="page-title">概览</div>
              <div class="page-desc">桌面账号的现状盘点 · 实时(基于账号库)</div>
            </div>
            <div class="ph-actions">
              <el-button :loading="loading" @click="loadAccounts">
                <ico name="refresh" :size="15" style="margin-right:6px"></ico>刷新
              </el-button>
            </div>
          </div>

          <!-- real KPIs derivable from the account list -->
          <div class="kpi-grid">
            <statcard label="总账号数" :value="fmt(total)" icon="users" :hint="'桌面账号(account_source=desktop)'"></statcard>
            <statcard label="启用账号" :value="fmt(activeCount)" :unit="'· ' + activeRate + '%'" icon="power" hint="占总账号比例"></statcard>
            <statcard label="停用账号" :value="fmt(disabledCount)" icon="ban" hint="已停用 / 离职回收"></statcard>
            <statcard label="管理员" :value="fmt(adminCount)" icon="shield" hint="is_platform_admin"></statcard>
          </div>

          <!-- distributions (real) -->
          <div class="dist-grid">
            <div class="card">
              <div class="card-head"><span class="ct">账号状态分布</span></div>
              <div class="card-body"><donut :data="statusDonut"></donut></div>
            </div>
            <div class="card">
              <div class="card-head"><span class="ct">角色分布</span></div>
              <div class="card-body"><donut :data="roleDonut"></donut></div>
            </div>
            <div class="card">
              <div class="card-head"><span class="ct">租户账号数</span><span class="cs">Top 6 · 按账号数</span></div>
              <div class="card-body">
                <div v-if="tenantBars.length" class="bars">
                  <div class="bar-row" v-for="b in tenantBars" :key="b.label">
                    <span class="bar-label">{{ b.label }}</span>
                    <div class="bar-track"><div class="bar-fill" :style="{width: pct(b.value, maxTenant)}"></div></div>
                    <span class="bar-val num">{{ b.value }}</span>
                  </div>
                </div>
                <div v-else class="muted" style="font-size:13px;padding:8px 0">暂无账号</div>
              </div>
            </div>
          </div>

          <!-- activity metrics: not yet instrumented -->
          <div class="eyebrow">活跃度 / 登录健康 / 安全信号 <span class="pill">待埋点</span></div>
          <div class="kpi-grid">
            <statcard label="今日登录" value="—" icon="activity" muted hint="待 login_events"></statcard>
            <statcard label="活跃 (WAU)" value="—" icon="trendup" muted hint="近 7 天登录去重"></statcard>
            <statcard label="登录成功率" value="—" icon="power" muted hint="成功 / 总登录"></statcard>
            <statcard label="联邦转发健康" value="—" icon="monitor" muted hint="federation 可达率"></statcard>
          </div>

          <div class="notice">
            <ico name="info" :size="16"></ico>
            <div class="nx">活跃度 / 登录健康 / 安全信号指标依赖 <code>login_events</code> 与 <code>admin_audit</code> 埋点(spec §7)。当前 account-service 尚未记录登录与操作日志,补齐两张表后这些指标方可接入真实聚合。</div>
          </div>
        </div>

        <!-- ---------- ACCOUNTS (list) ---------- -->
        <div v-else-if="page==='accounts' && !detail" class="page">
          <div class="page-head">
            <div class="ph-main">
              <div class="page-title">账号管理</div>
              <div class="page-desc">共 {{ total }} 个桌面账号 · 新账号自带独立租户并作为该租户管理员</div>
            </div>
            <div class="ph-actions">
              <el-button @click="comingSoon('批量开号(CSV 导入)', 'P2')">
                <ico name="upload" :size="15" style="margin-right:6px"></ico>批量开号
              </el-button>
              <el-button type="primary" @click="openCreate">
                <ico name="plus" :size="15" style="margin-right:6px"></ico>新建账号
              </el-button>
            </div>
          </div>

          <div class="filter-bar">
            <el-input v-model="q" placeholder="搜索用户名" clearable>
              <template #prefix><ico name="search" :size="15"></ico></template>
            </el-input>
            <el-select v-model="fStatus" placeholder="全部状态">
              <el-option label="全部状态" value=""></el-option>
              <el-option label="启用" value="active"></el-option>
              <el-option label="停用" value="disabled"></el-option>
            </el-select>
            <el-select v-model="fRole" placeholder="全部角色">
              <el-option label="全部角色" value=""></el-option>
              <el-option label="管理员" value="admin"></el-option>
              <el-option label="普通用户" value="user"></el-option>
            </el-select>
            <el-select v-model="fTenant" placeholder="全部租户">
              <el-option label="全部租户" value=""></el-option>
              <el-option v-for="t in tenants" :key="t" :label="'#'+t" :value="String(t)"></el-option>
            </el-select>
            <el-button text @click="resetFilters">重置</el-button>
          </div>

          <div v-if="selected.length" class="bulk-bar">
            <span class="bx">已选 <b>{{ selected.length }}</b> 项</span>
            <div class="ba">
              <el-button size="small" @click="bulkSet(true)">批量启用</el-button>
              <el-button size="small" type="danger" plain @click="bulkSet(false)">批量停用</el-button>
              <el-button size="small" text @click="clearSel">取消</el-button>
            </div>
          </div>

          <div class="card">
            <el-table :data="filtered" v-loading="loading" row-key="username" @selection-change="onSel"
              @row-click="openDetail" :row-style="{cursor:'pointer',height:'48px'}" style="width:100%">
              <el-table-column type="selection" width="44"></el-table-column>
              <el-table-column label="用户名" min-width="220">
                <template #default="s">
                  <div class="cell-user">
                    <span class="avatar" style="width:30px;height:30px;font-size:12px" :style="tint(s.row.username)">{{ initials(s.row.username) }}</span>
                    <div class="cu"><b>{{ s.row.username }}</b><small>#{{ s.row.id }}</small></div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="所属租户" min-width="120">
                <template #default="s"><span class="muted">{{ s.row.tenant_id==null ? '—' : '#'+s.row.tenant_id }}</span></template>
              </el-table-column>
              <el-table-column label="角色" min-width="110">
                <template #default="s">
                  <sbadge v-if="s.row.is_platform_admin" tone="accent">管理员</sbadge>
                  <sbadge v-else tone="neutral">普通</sbadge>
                </template>
              </el-table-column>
              <el-table-column label="状态" min-width="110">
                <template #default="s">
                  <sbadge v-if="s.row.is_active" tone="success" :dot="true">启用</sbadge>
                  <sbadge v-else tone="danger" :dot="true">停用</sbadge>
                </template>
              </el-table-column>
              <el-table-column label="" width="130" align="right">
                <template #default="s">
                  <div class="row-actions" @click.stop>
                    <el-tooltip content="重置密码" placement="top"><button class="icon-btn" @click="resetPwd(s.row)"><ico name="key" :size="15"></ico></button></el-tooltip>
                    <el-tooltip :content="s.row.is_active ? '停用' : '启用'" placement="top">
                      <button class="icon-btn" :class="{danger:s.row.is_active}" @click="setActive(s.row, !s.row.is_active)">
                        <ico :name="s.row.is_active ? 'ban' : 'power'" :size="15"></ico>
                      </button>
                    </el-tooltip>
                    <el-tooltip content="详情" placement="top"><button class="icon-btn" @click="openDetail(s.row)"><ico name="chevron" :size="15"></ico></button></el-tooltip>
                  </div>
                </template>
              </el-table-column>
              <template #empty>
                <div class="empty">
                  <span class="ei"><ico name="users" :size="22"></ico></span>
                  <span class="et">没有符合条件的账号</span>
                  <span class="ed">试试调整筛选条件,或清空搜索。</span>
                  <el-button size="small" @click="resetFilters" style="margin-top:4px">清空筛选</el-button>
                </div>
              </template>
            </el-table>
          </div>
        </div>

        <!-- ---------- ACCOUNT DETAIL ---------- -->
        <div v-else-if="detail" class="page">
          <div class="detail-bc">
            <a @click="closeDetail">账号管理</a><ico name="chevron" :size="13"></ico><span>{{ detail.username }}</span>
          </div>
          <div class="detail-id">
            <span class="avatar" style="width:56px;height:56px;font-size:22px" :style="tint(detail.username)">{{ initials(detail.username) }}</span>
            <div class="di">
              <div class="dn">
                <h1>{{ detail.username }}</h1>
                <sbadge v-if="detail.is_active" tone="success" :dot="true">启用</sbadge>
                <sbadge v-else tone="danger" :dot="true">停用</sbadge>
                <sbadge v-if="detail.is_platform_admin" tone="accent">管理员</sbadge>
              </div>
              <div class="du">{{ detail.username }} · #{{ detail.id }}</div>
            </div>
            <div class="da">
              <el-button @click="resetPwd(detail)"><ico name="key" :size="15" style="margin-right:6px"></ico>重置密码</el-button>
              <el-button v-if="detail.is_active" type="danger" @click="setActive(detail, false)"><ico name="ban" :size="15" style="margin-right:6px"></ico>停用</el-button>
              <el-button v-else type="primary" @click="setActive(detail, true)"><ico name="power" :size="15" style="margin-right:6px"></ico>启用</el-button>
            </div>
          </div>

          <div class="tabs">
            <button class="tab" :class="{active:detailTab==='info'}" @click="detailTab='info'">基本信息</button>
            <button class="tab" :class="{active:detailTab==='history'}" @click="detailTab='history'">登录历史</button>
            <button class="tab" :class="{active:detailTab==='sessions'}" @click="detailTab='sessions'">活跃会话</button>
          </div>

          <div v-if="detailTab==='info'" class="card">
            <div class="card-head"><span class="ct">基本信息</span></div>
            <div class="card-body">
              <div class="fields">
                <div class="field"><span class="fl">用户名</span><span class="fv mono">{{ detail.username }}</span></div>
                <div class="field"><span class="fl">所属租户</span><span class="fv">{{ detail.tenant_id==null ? '—' : '#'+detail.tenant_id }}</span></div>
                <div class="field"><span class="fl">角色</span><span class="fv">{{ detail.is_platform_admin ? '管理员' : '普通用户' }}</span></div>
                <div class="field"><span class="fl">状态</span><span class="fv">{{ detail.is_active ? '启用' : '停用' }}</span></div>
                <div class="field"><span class="fl">账号 ID</span><span class="fv mono">#{{ detail.id }}</span></div>
                <div class="field"><span class="fl">账号来源</span><span class="fv">desktop · federation</span></div>
                <div class="field"><span class="fl">注册时间</span><span class="fv wait">待埋点</span></div>
                <div class="field"><span class="fl">最后登录</span><span class="fv wait">待埋点</span></div>
                <div class="field"><span class="fl">登录设备数</span><span class="fv wait">待埋点</span></div>
              </div>
            </div>
          </div>

          <div v-else-if="detailTab==='history'" class="card">
            <div class="card-head"><span class="ct">登录历史</span><span class="cs">含 federation 转发</span></div>
            <div class="empty">
              <span class="ei"><ico name="file" :size="22"></ico></span>
              <span class="et">登录历史待埋点</span>
              <span class="ed">每次登录(authority + federation)写一条 <code style="font-family:var(--font-mono)">login_events</code>,补齐后在此展示时间 / IP / 设备 / 结果。</span>
            </div>
          </div>

          <div v-else class="card">
            <div class="card-head"><span class="ct">当前活跃会话</span><span class="cs">该账号正在登录的桌面端</span></div>
            <div class="empty">
              <span class="ei"><ico name="monitor" :size="22"></ico></span>
              <span class="et">活跃会话待上报</span>
              <span class="ed">由 login_events 的 device / instance_id 去重统计,补齐后可在此「强制下线」某台设备。</span>
            </div>
          </div>
        </div>

        <!-- ---------- LOGIN LOGS (P1, awaiting instrumentation) ---------- -->
        <div v-else-if="page==='logs'" class="page">
          <div class="page-head">
            <div class="ph-main">
              <div class="page-title">登录日志</div>
              <div class="page-desc">每次登录(含 federation 转发)记一条</div>
            </div>
          </div>
          <div class="eyebrow">登录健康 <span class="pill">待埋点</span></div>
          <div class="kpi-grid">
            <statcard label="今日登录" value="—" icon="activity" muted></statcard>
            <statcard label="登录成功率" value="—" icon="power" muted></statcard>
            <statcard label="失败次数" value="—" icon="ban" muted></statcard>
            <statcard label="联邦转发健康" value="—" icon="monitor" muted></statcard>
          </div>
          <div class="card">
            <div class="empty">
              <span class="ei"><ico name="file" :size="22"></ico></span>
              <span class="et">登录日志待埋点 (P1)</span>
              <span class="ed">需先补 <code style="font-family:var(--font-mono)">login_events</code> 表 + 在 /login(authority 与 federation)埋点。补齐后这里展示可按账号 / 时间 / 结果筛选的登录事件流。</span>
            </div>
          </div>
        </div>

        <!-- ---------- P3 placeholders ---------- -->
        <div v-else-if="page==='tenants'" class="page">
          <div class="page-head"><div class="ph-main"><div class="page-title">租户管理</div><div class="page-desc">列租户 / 租户详情(成员 · 配额 · 绑定 aPaaS 环境)</div></div></div>
          <div class="card"><div class="empty">
            <span class="ei"><ico name="building" :size="22"></ico></span>
            <span class="et">租户管理 — 规划中 (P3)</span>
            <span class="ed">桌面账号目前是「一人一私有租户」,租户管理优先级较低。后续支持列租户、查看成员与配额。</span>
          </div></div>
        </div>

        <div v-else-if="page==='audit'" class="page">
          <div class="page-head"><div class="ph-main"><div class="page-title">操作审计</div><div class="page-desc">管理员每个动作记一条 —— 谁在何时对谁做了什么</div></div></div>
          <div class="card"><div class="empty">
            <span class="ei"><ico name="shield" :size="22"></ico></span>
            <span class="et">操作审计 — 规划中 (P2)</span>
            <span class="ed">需补 <code style="font-family:var(--font-mono)">admin_audit</code> 表,每个管理 API(开号 / 停用 / 改密 / 改权限)写一条,用于合规与追责。</span>
          </div></div>
        </div>

        <div v-else class="page">
          <div class="page-head"><div class="ph-main"><div class="page-title">设置</div><div class="page-desc">密码策略 / 会话 TTL / 吊销策略 / SSO</div></div></div>
          <div class="card"><div class="empty">
            <span class="ei"><ico name="settings" :size="22"></ico></span>
            <span class="et">设置 — 规划中 (P3)</span>
            <span class="ed">将支持密码策略(最小长度 / 复杂度 / 有效期)、会话 token TTL 与停用吊销策略、SSO(钉钉 / 企微)接入。</span>
          </div></div>
        </div>

      </main>
    </div>
  </div>

  <!-- ===================== CREATE DIALOG ===================== -->
  <el-dialog v-model="createOpen" title="新建账号" width="460px" :close-on-click-modal="false" append-to-body>
    <div class="dlg-body">
      <div class="dlg-field"><span>用户名</span>
        <el-input v-model="createForm.username" placeholder="字母 / 数字,登录用" clearable></el-input></div>
      <div class="dlg-field"><span>初始密码</span>
        <el-input v-model="createForm.password" type="password" placeholder="至少 8 位" show-password @keyup.enter="createAccount"></el-input></div>
      <div class="dlg-hint">新账号将自动创建独立租户,并作为该租户管理员。可在创建后让用户首次登录修改密码。</div>
    </div>
    <template #footer>
      <el-button @click="createOpen=false">取消</el-button>
      <el-button type="primary" :loading="creating" @click="createAccount">创建</el-button>
    </template>
  </el-dialog>

</div>

<script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
<script src="https://unpkg.com/element-plus"></script>
<script src="https://unpkg.com/axios/dist/axios.min.js"></script>
<script>
const { createApp, ref, reactive, computed } = Vue
const { ElMessage, ElMessageBox } = ElementPlus
const API = location.pathname.includes('/account-api') ? '/account-api' : ''

/* Lucide-style stroke icons (inline; no CDN icon dependency) */
const ICONS = {
  grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
  users:'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  building:'<rect x="4" y="2" width="16" height="20" rx="1"/><path d="M9 22v-4h6v4M8 6h.01M12 6h.01M16 6h.01M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01"/>',
  file:'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M9 13h6M9 17h6"/>',
  shield:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  settings:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  search:'<circle cx="11" cy="11" r="7.5"/><path d="m20.5 20.5-3.8-3.8"/>',
  plus:'<path d="M12 5v14"/><path d="M5 12h14"/>',
  upload:'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/>',
  download:'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
  refresh:'<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>',
  key:'<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.5 12.5 21 2M16 7l3 3M14 9l2 2"/>',
  ban:'<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
  power:'<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>',
  logout:'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
  bell:'<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  info:'<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  monitor:'<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  activity:'<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  trendup:'<path d="M22 7 13.5 15.5 8.5 10.5 2 17"/><path d="M16 7h6v6"/>',
  chevron:'<path d="m9 18 6-6-6-6"/>',
}

const app = createApp({
  setup(){
    const NAV = [
      { key:'dashboard', label:'概览', icon:'grid' },
      { key:'accounts', label:'账号管理', icon:'users' },
      { key:'tenants', label:'租户管理', icon:'building' },
      { key:'logs', label:'登录日志', icon:'file' },
      { key:'audit', label:'操作审计', icon:'shield' },
      { key:'settings', label:'设置', icon:'settings' },
    ]

    const token = ref(''), me = ref('')
    const loginForm = reactive({ username:'', password:'' })
    const page = ref('dashboard')
    const accounts = ref([])
    const loading = ref(false), loggingIn = ref(false), creating = ref(false)
    const q = ref(''), fStatus = ref(''), fRole = ref(''), fTenant = ref('')
    const selected = ref([])
    const detail = ref(null), detailTab = ref('info')
    const createOpen = ref(false)
    const createForm = reactive({ username:'', password:'' })

    const auth = () => ({ headers:{ Authorization:'Bearer '+token.value } })
    const err = (e, fb) => ElMessage.error((e && e.response && e.response.data && e.response.data.detail) || fb)

    /* ---- helpers ---- */
    const fmt = (n) => (n==null ? '0' : Number(n).toLocaleString('en-US'))
    const initials = (s) => {
      s = (s||'').trim(); if(!s) return '?'
      if(/[一-鿿]/.test(s)) return s.slice(-2)
      return s.slice(0,2).toUpperCase()
    }
    const TINTS = [['--blue-50','--blue-600'],['--green-50','--green-600'],['--amber-50','--amber-600'],['--cyan-50','--cyan-600'],['#efeafd','#6b3fd1']]
    const tint = (name) => {
      let h=0; const s=name||''; for(let i=0;i<s.length;i++) h=(h*31+s.charCodeAt(i))>>>0
      const t=TINTS[h%TINTS.length]
      return { background: t[0].startsWith('--')?'var('+t[0]+')':t[0], color: t[1].startsWith('--')?'var('+t[1]+')':t[1] }
    }
    const pct = (v,max) => (max? Math.max(4, Math.round(v/max*100)) : 0)+'%'

    /* ---- derived (real) metrics ---- */
    const total = computed(() => accounts.value.length)
    const activeCount = computed(() => accounts.value.filter(a=>a.is_active).length)
    const disabledCount = computed(() => total.value - activeCount.value)
    const adminCount = computed(() => accounts.value.filter(a=>a.is_platform_admin).length)
    const activeRate = computed(() => total.value ? Math.round(activeCount.value/total.value*1000)/10 : 0)
    const tenants = computed(() => {
      const s=new Set(); accounts.value.forEach(a=>{ if(a.tenant_id!=null) s.add(a.tenant_id) })
      return [...s].sort((x,y)=>x-y)
    })
    const statusDonut = computed(() => [
      { label:'启用', value:activeCount.value, color:'var(--green-500)' },
      { label:'停用', value:disabledCount.value, color:'var(--red-500)' },
    ])
    const roleDonut = computed(() => [
      { label:'管理员', value:adminCount.value, color:'var(--blue-500)' },
      { label:'普通', value:Math.max(0,total.value-adminCount.value), color:'var(--gray-300)' },
    ])
    const tenantBars = computed(() => {
      const m={}; accounts.value.forEach(a=>{ const k = a.tenant_id==null ? '未分配' : ('#'+a.tenant_id); m[k]=(m[k]||0)+1 })
      return Object.entries(m).map(([label,value])=>({label,value})).sort((a,b)=>b.value-a.value).slice(0,6)
    })
    const maxTenant = computed(() => tenantBars.value.reduce((m,b)=>Math.max(m,b.value), 0))

    const filtered = computed(() => accounts.value.filter(a=>{
      if(q.value && !String(a.username).toLowerCase().includes(q.value.toLowerCase())) return false
      if(fStatus.value==='active' && !a.is_active) return false
      if(fStatus.value==='disabled' && a.is_active) return false
      if(fRole.value==='admin' && !a.is_platform_admin) return false
      if(fRole.value==='user' && a.is_platform_admin) return false
      if(fTenant.value!=='' && String(a.tenant_id)!==String(fTenant.value)) return false
      return true
    }))

    /* ---- nav ---- */
    const go = (key) => { detail.value=null; page.value=key }
    const resetFilters = () => { q.value=''; fStatus.value=''; fRole.value=''; fTenant.value='' }
    const onSel = (rows) => { selected.value = rows.map(r=>r.username) }
    const clearSel = () => { selected.value = [] }
    const openDetail = (row) => { detail.value=row; detailTab.value='info' }
    const closeDetail = () => { detail.value=null }
    const comingSoon = (what, phase) => ElMessage.info(what+' 规划中 ('+phase+')')

    /* ---- auth ---- */
    async function login(){
      if(!loginForm.username || !loginForm.password) return ElMessage.warning('请输入用户名和密码')
      loggingIn.value = true
      try{
        const { data } = await axios.post(API+'/api/desktop-auth/login', { username:loginForm.username, password:loginForm.password })
        token.value = data.access_token; me.value = data.username
        loginForm.password = ''
        await loadAccounts()
      }catch(e){ err(e,'登录失败') }
      finally{ loggingIn.value = false }
    }
    function logout(){ token.value=''; me.value=''; accounts.value=[]; selected.value=[]; detail.value=null; page.value='dashboard' }

    async function loadAccounts(){
      loading.value = true
      try{ const { data } = await axios.get(API+'/api/desktop-auth/admin/accounts', auth()); accounts.value = data }
      catch(e){ err(e,'加载失败') }
      finally{ loading.value = false }
    }

    function openCreate(){ createForm.username=''; createForm.password=''; createOpen.value=true }
    async function createAccount(){
      if(!createForm.username) return ElMessage.warning('请输入用户名')
      if((createForm.password||'').length < 8) return ElMessage.warning('密码至少 8 位')
      creating.value = true
      try{
        await axios.post(API+'/api/desktop-auth/admin/accounts', { username:createForm.username, password:createForm.password }, auth())
        ElMessage.success('账号已创建 · '+createForm.username)
        createOpen.value = false
        await loadAccounts()
      }catch(e){ err(e,'创建失败') }
      finally{ creating.value = false }
    }

    async function setActive(row, active){
      const title = active ? ('启用账号 '+row.username+' ?') : ('停用账号 '+row.username+' ?')
      const msg = active
        ? '启用后该账号可立即重新登录桌面端。'
        : '该账号已登录的桌面端将在 ≤5 分钟内失效(取决于吊销策略)。停用后可随时重新启用。'
      try{
        await ElMessageBox.confirm(msg, title, {
          type: active?'info':'warning', confirmButtonText: active?'确认启用':'确认停用', cancelButtonText:'取消',
          confirmButtonClass: active?'':'el-button--danger',
        })
      }catch(_){ return }
      try{
        await axios.patch(API+'/api/desktop-auth/admin/accounts/'+encodeURIComponent(row.username), { action: active?'enable':'disable' }, auth())
        ElMessage.success((active?'已启用 ':'已停用 ')+row.username)
        await loadAccounts()
        if(detail.value && detail.value.username===row.username) detail.value = accounts.value.find(a=>a.username===row.username) || null
      }catch(e){ err(e,'操作失败') }
    }

    async function resetPwd(row){
      let pwd
      try{
        const r = await ElMessageBox.prompt('给 '+row.username+' 设置新密码(至少 8 位)', '重置密码', {
          confirmButtonText:'确认重置', cancelButtonText:'取消', inputType:'password',
          inputValidator:(v)=> (v && v.length>=8) || '密码至少 8 位',
        })
        pwd = r.value
      }catch(_){ return }
      try{
        await axios.patch(API+'/api/desktop-auth/admin/accounts/'+encodeURIComponent(row.username), { action:'reset_password', password:pwd }, auth())
        ElMessage.success('已重置 '+row.username+' 的密码')
      }catch(e){ err(e,'改密失败') }
    }

    async function bulkSet(active){
      const names = selected.value.slice()
      if(!names.length) return
      try{
        await ElMessageBox.confirm(
          '将对已选 '+names.length+' 个账号执行「'+(active?'启用':'停用')+'」。'+(active?'':'已登录设备将在 ≤5 分钟内失效。'),
          (active?'批量启用':'批量停用')+' '+names.length+' 个账号',
          { type: active?'info':'warning', confirmButtonText:'确认', cancelButtonText:'取消' }
        )
      }catch(_){ return }
      let ok=0, fail=0
      for(const name of names){
        try{ await axios.patch(API+'/api/desktop-auth/admin/accounts/'+encodeURIComponent(name), { action: active?'enable':'disable' }, auth()); ok++ }
        catch(_){ fail++ }
      }
      ElMessage[fail?'warning':'success']('已'+(active?'启用':'停用')+' '+ok+' 个'+(fail?(' · '+fail+' 个失败'):''))
      selected.value = []
      await loadAccounts()
    }

    return {
      NAV, token, me, loginForm, page, accounts, loading, loggingIn, creating,
      q, fStatus, fRole, fTenant, selected, detail, detailTab, createOpen, createForm,
      total, activeCount, disabledCount, adminCount, activeRate, tenants,
      statusDonut, roleDonut, tenantBars, maxTenant, filtered,
      fmt, initials, tint, pct,
      go, resetFilters, onSel, clearSel, openDetail, closeDetail, comingSoon,
      login, logout, loadAccounts, openCreate, createAccount, setActive, resetPwd, bulkSet,
    }
  }
})

/* ---- presentational components ---- */
app.component('ico', {
  props: { name:String, size:{ default:18 } },
  computed: { html(){ return '<svg viewBox="0 0 24 24" width="100%" height="100%" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+(ICONS[this.name]||'')+'</svg>' } },
  template: '<span class="ico" :style="{width:size+\'px\',height:size+\'px\'}" v-html="html"></span>',
})
app.component('sbadge', {
  props: { tone:{ default:'neutral' }, dot:{ type:Boolean, default:false } },
  template: '<span class="sbadge" :class="\'t-\'+tone"><span v-if="dot" class="sbadge-dot"></span><slot></slot></span>',
})
app.component('statcard', {
  props: { label:String, value:[String,Number], unit:String, icon:String, hint:String, muted:{ type:Boolean, default:false } },
  template: '<div class="stat-card" :class="{muted:muted}"><div class="stat-top"><span class="stat-label">{{label}}</span><span v-if="icon" class="stat-ic"><ico :name="icon" :size="16"></ico></span></div><div class="stat-val"><span class="num">{{value}}</span><span v-if="unit" class="stat-unit">{{unit}}</span></div><div v-if="hint" class="stat-hint">{{hint}}</div></div>',
})
app.component('donut', {
  props: { data:Array },
  computed: {
    total(){ return (this.data||[]).reduce((s,d)=>s+(d.value||0),0) },
    gradient(){
      let acc=0; const t=this.total||1; const stops=[]
      ;(this.data||[]).forEach(d=>{ const a=acc/t*100; acc+=(d.value||0); const b=acc/t*100; stops.push(d.color+' '+a+'% '+b+'%') })
      return 'conic-gradient('+stops.join(',')+')'
    },
  },
  template: '<div class="donut-wrap"><div class="donut" :style="{background: total ? gradient : \'var(--gray-150)\'}"><div class="donut-hole"><div class="donut-total num">{{total}}</div></div></div><div class="donut-legend"><div class="leg" v-for="d in data" :key="d.label"><span class="leg-dot" :style="{background:d.color}"></span><span class="leg-label">{{d.label}}</span><span class="leg-val num">{{d.value}}</span></div></div></div>',
})

app.use(ElementPlus)
app.mount('#app')
</script>
</body>
</html>
"""
