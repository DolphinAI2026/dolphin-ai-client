// Shared shell: Sidebar, TopBar, CmdK, icons, layout primitives.
// Globals exported at bottom of file.

const { useState, useEffect, useRef, useMemo, useCallback, createContext, useContext } = React;

/* ─── Icons (inline SVG, 1.5px stroke, 16/18px viewport) ─── */
const Icon = ({ d, size = 16, fill = false, stroke = 1.6 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill ? 'currentColor' : 'none'}
       stroke={fill ? 'none' : 'currentColor'} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round">
    {Array.isArray(d) ? d.map((p, i) => <path key={i} d={p} />) : <path d={d} />}
  </svg>
);

const I = {
  home:        (p) => <Icon {...p} d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" />,
  apps:        (p) => <Icon {...p} d={['M3 5h7v7H3z', 'M14 5h7v7h-7z', 'M3 16h7v5H3z', 'M14 16h7v5h-7z']} />,
  chat:        (p) => <Icon {...p} d="M21 12a8 8 0 0 1-11.9 7L4 21l1.6-4.4A8 8 0 1 1 21 12z" />,
  doc:         (p) => <Icon {...p} d={['M7 3h8l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z','M14 3v5h5','M9 13h6','M9 17h4']} />,
  code:        (p) => <Icon {...p} d={['m9 17-5-5 5-5','m15 7 5 5-5 5','m13 5-2 14']} />,
  store:       (p) => <Icon {...p} d={['M3 9 5 4h14l2 5','M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9','M3 9h18']} />,
  template:    (p) => <Icon {...p} d={['M4 4h16v6H4z','M4 14h7v6H4z','M14 14h6v6h-6z']} />,
  admin:       (p) => <Icon {...p} d={['M12 2 4 5v7c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V5z','M9 12l2 2 4-4']} />,
  search:      (p) => <Icon {...p} d={['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z','m21 21-4.3-4.3']} />,
  cmd:         (p) => <Icon {...p} d={['M7 9a2 2 0 1 1 2-2v10a2 2 0 1 1-2-2zM17 9a2 2 0 1 0-2-2v10a2 2 0 1 0 2-2zM7 9h10v6H7z']} />,
  bell:        (p) => <Icon {...p} d={['M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9','M10 21a2 2 0 0 0 4 0']} />,
  sun:         (p) => <Icon {...p} d={['M12 4V2M12 22v-2M4 12H2M22 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4']} />,
  sunCircle:   (p) => <Icon {...p} d="M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z" />,
  moon:        (p) => <Icon {...p} d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10z" />,
  gear:        (p) => <Icon {...p} d={['M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z','M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z']} />,
  plus:        (p) => <Icon {...p} d={['M12 5v14','M5 12h14']} />,
  arrowRight:  (p) => <Icon {...p} d={['M5 12h14','m13 5 7 7-7 7']} />,
  chevronR:    (p) => <Icon {...p} d="m9 6 6 6-6 6" />,
  chevronD:    (p) => <Icon {...p} d="m6 9 6 6 6-6" />,
  chevronL:    (p) => <Icon {...p} d="m15 6-6 6 6 6" />,
  check:       (p) => <Icon {...p} d="m5 13 4 4 10-10" />,
  upload:      (p) => <Icon {...p} d={['M12 4v12','m7 9 5-5 5 5','M5 20h14']} />,
  download:    (p) => <Icon {...p} d={['M12 4v12','m7 11 5 5 5-5','M5 20h14']} />,
  sparkle:     (p) => <Icon {...p} d={['M12 3 14 9l6 2-6 2-2 6-2-6-6-2 6-2z','M19 17l1 3 3 1-3 1-1 3-1-3-3-1 3-1z']} />,
  zap:         (p) => <Icon {...p} d="M13 2 4 14h7l-1 8 9-12h-7z" />,
  layers:      (p) => <Icon {...p} d={['m12 3 9 5-9 5-9-5z','m3 14 9 5 9-5','m3 19 9 5 9-5']} />,
  shield:      (p) => <Icon {...p} d="M12 2 4 5v7c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V5z" />,
  book:        (p) => <Icon {...p} d={['M4 5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1 0-4h13','M9 7h6']} />,
  flow:        (p) => <Icon {...p} d={['M5 8h6v3H5z','M13 13h6v3h-6z','M8 11v2h8']} />,
  model:       (p) => <Icon {...p} d={['M5 7c0-1.5 3-3 7-3s7 1.5 7 3-3 3-7 3-7-1.5-7-3z','M5 7v10c0 1.5 3 3 7 3s7-1.5 7-3V7','M5 12c0 1.5 3 3 7 3s7-1.5 7-3']} />,
  form:        (p) => <Icon {...p} d={['M4 4h16v16H4z','M8 9h8','M8 13h8','M8 17h5']} />,
  dict:        (p) => <Icon {...p} d={['M4 5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1 0-4h12','M8 7h6']} />,
  role:        (p) => <Icon {...p} d={['M16 18v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1','M9 9a4 4 0 1 0 0-8 4 4 0 0 0 0 8z','M22 18v-1a4 4 0 0 0-3-3.9','M16 1.1A4 4 0 0 1 16 9']} />,
  filter:      (p) => <Icon {...p} d="M3 5h18l-7 8v6l-4-2v-4z" />,
  grid:        (p) => <Icon {...p} d={['M3 3h8v8H3z','M13 3h8v8h-8z','M3 13h8v8H3z','M13 13h8v8h-8z']} />,
  list:        (p) => <Icon {...p} d={['M8 6h13','M8 12h13','M8 18h13','M3 6h.01','M3 12h.01','M3 18h.01']} />,
  rocket:      (p) => <Icon {...p} d={['M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2 0-2.8a2 2 0 0 0-3 .3z','M12 15l-3-3a22 22 0 0 1 8-13 8 8 0 0 1 5 5 22 22 0 0 1-13 8z','M16 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4z']} />,
  build:       (p) => <Icon {...p} d={['M14.7 6.3a4 4 0 0 1-5.6 5.6L3 18l3 3 6.1-6.1a4 4 0 0 1 5.6-5.6l-2.4 2.4-2-2z']} />,
  refresh:     (p) => <Icon {...p} d={['M21 12a9 9 0 1 1-3-6.7L21 8','M21 3v5h-5']} />,
  play:        (p) => <Icon {...p} d="M6 4v16l14-8z" fill stroke={0} />,
  paperclip:   (p) => <Icon {...p} d="M21 11.5 12.5 20a5.5 5.5 0 1 1-7.8-7.8L13 4a4 4 0 1 1 5.7 5.7l-8.3 8.3a2.5 2.5 0 0 1-3.6-3.6L14 7" />,
  send:        (p) => <Icon {...p} d={['m22 2-7 20-4-9-9-4z','M22 2 11 13']} />,
  external:    (p) => <Icon {...p} d={['M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6','M15 3h6v6','M10 14 21 3']} />,
  github:      (p) => <Icon {...p} d="M9 19c-4 1.5-4-2.5-6-3M15 21v-3.5a3 3 0 0 0-.8-2.2c2.7-.3 5.5-1.3 5.5-6a4.7 4.7 0 0 0-1.3-3.2 4.4 4.4 0 0 0-.1-3.2s-1.1-.3-3.4 1.3a11.7 11.7 0 0 0-6 0c-2.3-1.6-3.4-1.3-3.4-1.3a4.4 4.4 0 0 0-.1 3.2A4.7 4.7 0 0 0 4 9.3c0 4.6 2.8 5.7 5.5 6A3 3 0 0 0 8.7 18V21" />,
  copy:        (p) => <Icon {...p} d={['M8 5h11v14H8z','M5 8H4v13h13v-1']} />,
  trash:       (p) => <Icon {...p} d={['M4 7h16','M9 7V4h6v3','M6 7v13h12V7','M10 11v6','M14 11v6']} />,
  pin:         (p) => <Icon {...p} d="m12 2 3 6 6 1-4.5 4 1 6L12 16l-5.5 3 1-6L3 9l6-1z" />,
  star:        (p) => <Icon {...p} d="m12 3 2.6 6 6.4.6-4.9 4.3 1.5 6.3L12 17l-5.6 3.2 1.5-6.3L3 9.6 9.4 9z" />,
  dot:         (p) => <Icon {...p} fill d="M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z" stroke={0} />,
  user:        (p) => <Icon {...p} d={['M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2','M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z']} />,
  switchH:     (p) => <Icon {...p} d={['M16 3 21 8l-5 5','M21 8H7','M8 21l-5-5 5-5','M3 16h14']} />,
  bldg:        (p) => <Icon {...p} d={['M4 21V5l8-3 8 3v16','M9 9h.01M9 13h.01M9 17h.01M15 9h.01M15 13h.01M15 17h.01','M4 21h16']} />,
  logout:      (p) => <Icon {...p} d={['M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4','m16 17 5-5-5-5','M21 12H9']} />,
  more:        (p) => <Icon {...p} d={['M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z','M5 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z','M19 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z']} fill stroke={0} />,
  mcp:         (p) => <Icon {...p} d={['M12 3 4 7v5c0 4 3.4 7.4 8 9 4.6-1.6 8-5 8-9V7z','M8.5 11l2.5 2.5L15.5 9']} />,
  whale:       (p) => <Icon {...p} d={['M5 3c-1.5 0-2.2 1.2-2.2 2.4v3l-1.4 1 1.4 1v3.2c0 1.2.7 2.4 2.2 2.4','M19 3c1.5 0 2.2 1.2 2.2 2.4v3l1.4 1-1.4 1v3.2c0 1.2-.7 2.4-2.2 2.4']} />,
  industry:    (p) => <Icon {...p} d={['M3 21V11l6-4v4l6-4v4l6-4v14H3z','M7 17h2','M11 17h2','M15 17h2']} />,
  network:     (p) => <Icon {...p} d={['M6 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4z','M18 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4z','M12 14a2 2 0 1 0 0 4 2 2 0 0 0 0-4z','M6 8l5 6','M18 8l-5 6']} />,
  team:        (p) => <Icon {...p} d={['M17 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z','M3 21v-1a5 5 0 0 1 5-5h6a5 5 0 0 1 5 5v1','M9 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z']} />,
  cloud:       (p) => <Icon {...p} d={['M18 18a4 4 0 0 0 0-8 6 6 0 0 0-12 1 4 4 0 0 0 0 8z']} />,
};

/* ─── Theme context ─── */
const ThemeCtx = createContext(null);
const RouteCtx = createContext(null);

/* ─── Sidebar nav ─── */
const NAV = [
  { group: '搭建', items: [
    { key: 'home',     label: '新建',           icon: 'home',   path: '/' },
    { key: 'projects', label: '项目',           icon: 'bldg',   path: '/projects', badge: 4 },
    { key: 'apps',     label: '应用',           icon: 'apps',   path: '/apps', badge: 6 },
    { key: 'chat',     label: '睿鲸 AI Builder', icon: 'chat',  path: '/chat' },
  ]},
  { group: '开发', items: [
    { key: 'coding',     label: '睿鲸 AI Coding', icon: 'whale', path: '/coding', badge: 1 },
    { key: 'vibe',       label: 'Vibe Coding',    icon: 'code',  path: '/vibe' },
  ]},
  { group: '知识 & 智能体', items: [
    { key: 'agents',     label: '智能体配置', icon: 'sparkle',  path: '/agents' },
    { key: 'specs',      label: '设计文档',   icon: 'doc',      path: '/specs' },
    { key: 'industry',   label: '行业知识库', icon: 'industry', path: '/industry' },
    { key: 'marketplace',label: '组件市场',   icon: 'store',    path: '/marketplace' },
    { key: 'mcp',        label: 'MCP 管理',   icon: 'mcp',      path: '/mcp', badge: 8 },
  ]},
  { group: '管理', items: [
    { key: 'runtime', label: '运行与发布', icon: 'cloud', path: '/runtime', badge: 3 },
    { key: 'admin',   label: '平台管理',   icon: 'admin', path: '/admin' },
  ]},
];

function Sidebar({ collapsed, onToggle }) {
  const { route, navigate } = useContext(RouteCtx);
  // Show all menus to all users — role no longer filters navigation.
  // Project-level permissions handle "what you can do" inside each scope.
  return (
    <aside className="rail">
      <div className="rail-brand">
        <button className="rail-logo" onClick={() => navigate('/')} aria-label="aPaaS Builder">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <rect x="3" y="3" width="8" height="8" rx="2" fill="white" />
            <rect x="13" y="3" width="8" height="8" rx="2" fill="rgba(255,255,255,0.6)" />
            <rect x="3" y="13" width="8" height="8" rx="2" fill="rgba(255,255,255,0.6)" />
            <rect x="13" y="13" width="8" height="8" rx="2" fill="white" />
          </svg>
        </button>
        {!collapsed && (
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="rail-title">aPaaS Builder</div>
            <div className="rail-title-sub">AI · 设计 · 部署</div>
          </div>
        )}
        <button className="icon-btn" onClick={onToggle} aria-label="折叠侧边栏" style={{ width: 24, height: 24, color: 'var(--text-3)' }}>
          {collapsed ? <I.chevronR size={14} /> : <I.chevronL size={14} />}
        </button>
      </div>

      <div className="rail-scroll">
        {NAV.map(grp => (
          <div className="rail-group" key={grp.group}>
            {!collapsed && <div className="rail-group-label">{grp.group}</div>}
            {grp.items.map(item => {
              const I_ = I[item.icon];
              const active = route === item.path || (item.path !== '/' && route.startsWith(item.path));
              return (
                <button key={item.key} className={`rail-item ${active ? 'active' : ''}`} onClick={() => navigate(item.path)} title={item.label}>
                  <span className="rail-item-icon"><I_ size={17} /></span>
                  <span className="rail-item-label">{item.label}</span>
                  {item.badge && <span className="rail-item-badge">{item.badge}</span>}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      <div className="rail-foot">
        <button className="rail-user" title="账户与偏好">
          <div className="rail-avatar">M</div>
          <div className="rail-user-info">
            <div className="rail-user-name">marshub</div>
            <div className="rail-user-tenant" style={{ fontSize: 11, color: 'var(--text-3)' }}>marshub@definesys.cn</div>
          </div>
          <I.gear size={13} style={{ color: 'var(--text-3)' }} />
        </button>
      </div>
    </aside>
  );
}

function TopBar({ crumb, actions, onCmdK }) {
  const { theme, setTheme } = useContext(ThemeCtx);
  const { navigate } = useContext(RouteCtx);
  const { projects } = window.MOCK || {};
  const [currentProjectId, setCurrentProjectId] = useState(() => parseInt(localStorage.getItem('aPaaS:projectId') || '1'));
  const currentProject = projects ? (projects.find(p => p.id === currentProjectId) || projects[0]) : null;
  const [projOpen, setProjOpen] = useState(false);

  useEffect(() => { localStorage.setItem('aPaaS:projectId', String(currentProjectId)); }, [currentProjectId]);

  return (
    <div className="topbar">
      {currentProject && (
        <div style={{ position: 'relative' }}>
          <button className="topbar-proj" onClick={() => setProjOpen(o => !o)} title="切换项目">
            <span className={`topbar-proj-stripe proj-stripe-${currentProject.stageTone}`} />
            <span className="topbar-proj-name">{currentProject.name}</span>
            <I.chevronD size={12} style={{ color: 'var(--text-3)', transform: projOpen ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 0.15s' }} />
          </button>
          {projOpen && (
            <>
              <div className="role-picker-backdrop" onClick={() => setProjOpen(false)} />
              <div className="topbar-proj-popover">
                <div className="topbar-proj-popover-head">
                  <span>项目 ({projects.length})</span>
                  <button className="section-action" style={{ marginLeft: 'auto' }} onClick={() => { setProjOpen(false); navigate('/projects'); }}>
                    全部 →
                  </button>
                </div>
                {projects.map(p => (
                  <button key={p.id}
                    className={`topbar-proj-item ${p.id === currentProjectId ? 'active' : ''}`}
                    onClick={() => { setCurrentProjectId(p.id); setProjOpen(false); }}>
                    <span className={`topbar-proj-stripe proj-stripe-${p.stageTone}`} style={{ height: 28 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="topbar-proj-item-name truncate">{p.name}</div>
                      <div className="topbar-proj-item-sub">{p.appCount} 应用 · {p.stage} · 负责人 {p.lead}</div>
                    </div>
                    {p.id === currentProjectId && <I.check size={14} style={{ color: 'var(--brand)' }} />}
                  </button>
                ))}
                <button className="topbar-proj-item" style={{ borderTop: '1px solid var(--border)', marginTop: 4, paddingTop: 10 }} onClick={() => { setProjOpen(false); navigate('/projects'); }}>
                  <I.plus size={14} style={{ color: 'var(--text-3)' }} />
                  <span style={{ fontSize: 12.5, color: 'var(--text-2)' }}>新建项目</span>
                </button>
              </div>
            </>
          )}
        </div>
      )}
      <div className="topbar-crumb">
        {crumb.map((c, i) => (
          <React.Fragment key={i}>
            {i > 0 && <span className="topbar-crumb-sep"><I.chevronR size={12} /></span>}
            <span className={i === crumb.length - 1 ? 'topbar-crumb-current' : ''}>{c}</span>
          </React.Fragment>
        ))}
      </div>
      <button className="topbar-search" onClick={onCmdK}>
        <I.search size={14} />
        <span style={{ flex: 1, textAlign: 'left' }}>搜索应用、模型、对话…</span>
        <span className="topbar-search-kbd">⌘K</span>
      </button>
      <div className="topbar-actions">
        {actions}
        <button className="icon-btn" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')} title={theme === 'light' ? '切换深色' : '切换浅色'}>
          {theme === 'light' ? <I.moon size={16} /> : <I.sun size={16} />}
        </button>
        <button className="icon-btn" title="通知"><I.bell size={16} /></button>
      </div>
    </div>
  );
}

/* ─── Command palette ─── */
const CMDK = [
  { group: '导航', items: [
    { label: '新建 / 首页', icon: 'home', path: '/', meta: 'G H' },
    { label: '应用列表', icon: 'apps', path: '/apps', meta: 'G A' },
    { label: '智能对话', icon: 'chat', path: '/chat', meta: 'G C' },

    { label: '睿鲸 AI Coding', icon: 'whale', path: '/coding' },
    { label: 'Vibe Coding', icon: 'code', path: '/vibe' },
    { label: '组件市场', icon: 'store', path: '/marketplace' },
    { label: 'MCP 管理', icon: 'mcp', path: '/mcp' },
    { label: '运行与发布', icon: 'cloud', path: '/runtime' },
    { label: '平台管理', icon: 'admin', path: '/admin' },
  ]},
  { group: '快捷操作', items: [
    { label: '新建对话（需求梳理）', icon: 'plus', path: '/chat?mode=requirements', meta: 'N C' },
    { label: '上传设计文档', icon: 'upload', path: '/' },
    { label: '生成低代码组件（睿鲸）', icon: 'whale', path: '/coding' },
    { label: '打开 Vibe Coding 工作区', icon: 'code', path: '/vibe' },
    { label: '挂载 MCP 服务器', icon: 'mcp', path: '/mcp' },
    { label: '切换主题', icon: 'sun', action: 'theme' },
  ]},
  { group: '最近', items: [
    { label: '资产管理系统 — 新增报废流程', icon: 'chat', path: '/chat' },
    { label: '客户工单中心 — SLA 字段调整', icon: 'chat', path: '/chat' },
    { label: '差旅报销表单（AI Coding）', icon: 'code', path: '/coding' },
  ]},
];

function CmdK({ open, onClose }) {
  const { navigate } = useContext(RouteCtx);
  const { theme, setTheme } = useContext(ThemeCtx);
  const [q, setQ] = useState('');
  const [focused, setFocused] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => { if (open) { setQ(''); setFocused(0); setTimeout(() => inputRef.current?.focus(), 30); } }, [open]);

  const flat = useMemo(() => {
    const out = [];
    CMDK.forEach(grp => {
      const items = grp.items.filter(it => it.label.toLowerCase().includes(q.toLowerCase()));
      if (items.length) out.push({ group: grp.group, items });
    });
    return out;
  }, [q]);

  const allItems = flat.flatMap(g => g.items);

  const onKey = (e) => {
    if (e.key === 'Escape') onClose();
    if (e.key === 'ArrowDown') { e.preventDefault(); setFocused(f => Math.min(f + 1, allItems.length - 1)); }
    if (e.key === 'ArrowUp')   { e.preventDefault(); setFocused(f => Math.max(f - 1, 0)); }
    if (e.key === 'Enter')     { e.preventDefault(); pick(allItems[focused]); }
  };

  const pick = (it) => {
    if (!it) return;
    if (it.action === 'theme') setTheme(theme === 'light' ? 'dark' : 'light');
    else if (it.path) navigate(it.path);
    onClose();
  };

  if (!open) return null;
  let runningIdx = -1;
  return (
    <div className="cmdk-overlay" onClick={onClose}>
      <div className="cmdk-panel" onClick={(e) => e.stopPropagation()}>
        <div className="cmdk-input-row">
          <I.search size={16} />
          <input ref={inputRef} className="cmdk-input" placeholder="跳转、搜索、操作..."
                 value={q} onChange={(e) => { setQ(e.target.value); setFocused(0); }} onKeyDown={onKey} />
          <span className="topbar-search-kbd">ESC</span>
        </div>
        <div className="cmdk-list">
          {flat.length === 0 && (
            <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>没有匹配结果</div>
          )}
          {flat.map(grp => (
            <div key={grp.group} className="cmdk-group">
              <div className="cmdk-group-label">{grp.group}</div>
              {grp.items.map(it => {
                runningIdx++;
                const idx = runningIdx;
                const Ic = I[it.icon] || I.dot;
                return (
                  <div key={it.label} className={`cmdk-item ${focused === idx ? 'focused' : ''}`}
                       onMouseEnter={() => setFocused(idx)} onClick={() => pick(it)}>
                    <span className="cmdk-item-icon"><Ic size={15} /></span>
                    <span className="cmdk-item-label">{it.label}</span>
                    {it.meta && <span className="cmdk-item-meta mono">{it.meta}</span>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ─── Status badge helper ─── */
const STATUS_META = {
  completed:  { label: '已生成', cls: 'badge-emerald' },
  generating: { label: '生成中', cls: 'badge-brand' },
  updating:   { label: '更新中', cls: 'badge-sky' },
  draft:      { label: '草稿',   cls: 'badge-amber' },
  failed:     { label: '失败',   cls: 'badge-rose' },
};
function StatusBadge({ status }) {
  const m = STATUS_META[status] || { label: status, cls: '' };
  return <span className={`badge ${m.cls}`}><span className="badge-dot" />{m.label}</span>;
}

Object.assign(window, { I, Icon, Sidebar, TopBar, CmdK, StatusBadge, ThemeCtx, RouteCtx, STATUS_META });
