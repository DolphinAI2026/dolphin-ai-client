/* components.jsx — shared UI for 睿鲸AI prototype */
const { useState, useEffect, useRef } = React;

// ─────────────────────────────────────────── Icons (stroke, 24 grid)
const ICON_PATHS = {
  home: '<path d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  apps: '<rect x="3" y="3" width="7" height="7" rx="1.6"/><rect x="14" y="3" width="7" height="7" rx="1.6"/><rect x="3" y="14" width="7" height="7" rx="1.6"/><rect x="14" y="14" width="7" height="7" rx="1.6"/>',
  builder: '<rect x="3" y="3" width="8" height="8" rx="1.8"/><rect x="13" y="3" width="8" height="5" rx="1.8"/><rect x="13" y="10" width="8" height="11" rx="1.8"/><rect x="3" y="13" width="8" height="8" rx="1.8"/>',
  coding: '<path d="m8 17-5-5 5-5"/><path d="m16 7 5 5-5 5"/><path d="m13 4-2 16"/>',
  store: '<path d="M3 9 5 4h14l2 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M3 9h18"/>',
  shield: '<path d="M12 2 4 5v7c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V5z"/><path d="M9 12l2 2 4-4"/>',
  send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
  attach: '<path d="M21.4 11.05 12.25 20.2a5 5 0 0 1-7.07-7.07l9.19-9.19a3 3 0 0 1 4.24 4.24l-9.2 9.19a1 1 0 0 1-1.41-1.41l8.49-8.49"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><polyline points="16 9.5 11 14.5 8.5 12"/>',
  chevR: '<polyline points="9 6 15 12 9 18"/>',
  chevD: '<polyline points="6 9 12 15 18 9"/>',
  arrowR: '<line x1="4" y1="12" x2="19" y2="12"/><polyline points="13 6 19 12 13 18"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.6" fill="currentColor"/>',
  building: '<path d="M5 21V4a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v17"/><path d="M15 9h3a1 1 0 0 1 1 1v11"/><path d="M8 7h2M8 11h2M8 15h2"/><path d="M3 21h18"/>',
  user: '<circle cx="12" cy="8" r="3.4"/><path d="M5.5 20a6.5 6.5 0 0 1 13 0"/>',
  note: '<path d="M5 3h11l3 3v15a0 0 0 0 1 0 0H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M8 9h7M8 13h7M8 17h4"/>',
  box: '<path d="M12 2 3 7v10l9 5 9-5V7z"/><path d="M3 7l9 5 9-5"/><path d="M12 12v10"/>',
  steps: '<path d="M4 20h4v-5h4V9h4V4h4"/>',
  flow: '<circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="6" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M7.4 11 16.6 6.8M7.4 13l9.2 4.2"/>',
  sparkle: '<path d="M12 3 13.6 8.4 19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6z"/>',
  layers: '<path d="M12 2 3 7l9 5 9-5z"/><path d="M3 12l9 5 9-5"/><path d="M3 17l9 5 9-5"/>',
  branch: '<circle cx="6" cy="6" r="2.4"/><circle cx="6" cy="18" r="2.4"/><circle cx="18" cy="9" r="2.4"/><path d="M6 8.4V18M6 15c0-4 2-6 9.6-6.2"/>',
  lock: '<rect x="4.5" y="10" width="15" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  play: '<polygon points="7 4 20 12 7 20"/>',
  grid2: '<rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="8" rx="1.5"/><rect x="3" y="13" width="8" height="8" rx="1.5"/><rect x="13" y="13" width="8" height="8" rx="1.5"/>',
  bolt: '<polygon points="13 2 4 14 11 14 10 22 20 9 13 9"/>',
  search: '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.5" y2="16.5"/>',
  star: '<polygon points="12 3 14.6 9 21 9.6 16 14 17.5 20.5 12 17 6.5 20.5 8 14 3 9.6 9.4 9"/>',
  dots: '<circle cx="5" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="19" cy="12" r="1.4" fill="currentColor"/>',
  swap: '<path d="M4 8h13M4 8l4-4M4 8l4 4"/><path d="M20 16H7M20 16l-4-4M20 16l-4 4"/>',
  drag: '<circle cx="9" cy="6" r="1.3" fill="currentColor"/><circle cx="15" cy="6" r="1.3" fill="currentColor"/><circle cx="9" cy="12" r="1.3" fill="currentColor"/><circle cx="15" cy="12" r="1.3" fill="currentColor"/><circle cx="9" cy="18" r="1.3" fill="currentColor"/><circle cx="15" cy="18" r="1.3" fill="currentColor"/>',
  doc: '<path d="M6 2h8l4 4v16H6z"/><path d="M14 2v4h4"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>',
};

function Icon({ name, size = 18, stroke = 1.7, style, className }) {
  return (
    <span
      className={'icon ' + (className || '')}
      style={{ display: 'inline-grid', placeItems: 'center', width: size, height: size, flexShrink: 0, ...style }}
      dangerouslySetInnerHTML={{
        __html: `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[name] || ''}</svg>`,
      }}
    />
  );
}

// ─────────────────────────────────────────── Module chip / badge
function ModuleTag({ mod, size = 'md' }) {
  const isB = mod === 'builder';
  const label = isB ? 'AI Builder' : 'AI Coding';
  const icon = isB ? 'builder' : 'coding';
  const sm = size === 'sm';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: sm ? 5 : 7,
      height: sm ? 22 : 26, padding: sm ? '0 8px' : '0 10px', borderRadius: 'var(--r-full)',
      fontSize: sm ? 11.5 : 12.5, fontWeight: 600, letterSpacing: '-0.01em',
      color: 'var(--brand)', background: 'var(--brand-soft)', border: '1px solid var(--brand-soft-2)',
      fontFamily: isB ? 'var(--font-sans)' : 'var(--font-mono)', whiteSpace: 'nowrap',
    }}>
      <Icon name={icon} size={sm ? 12 : 13} stroke={1.9} />
      {label}
    </span>
  );
}

function Badge({ tone = 'neutral', children, mono }) {
  const map = {
    neutral: ['var(--text-3)', 'var(--surface-3)', 'transparent'],
    brand:   ['var(--brand)', 'var(--brand-soft)', 'var(--brand-soft-2)'],
    ok:      ['var(--ok)', 'var(--ok-soft)', 'transparent'],
    warn:    ['var(--warn)', 'var(--warn-soft)', 'transparent'],
    live:    ['var(--ok)', 'var(--ok-soft)', 'transparent'],
  };
  const [c, bg, bd] = map[tone] || map.neutral;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5, height: 20, padding: '0 8px',
      borderRadius: 'var(--r-full)', fontSize: 11, fontWeight: 600, color: c, background: bg,
      border: `1px solid ${bd}`, fontFamily: mono ? 'var(--font-mono)' : 'inherit', whiteSpace: 'nowrap',
    }}>
      {tone === 'live' && <span style={{ width: 6, height: 6, borderRadius: 999, background: 'var(--ok)' }} />}
      {children}
    </span>
  );
}

// ─────────────────────────────────────────── Button
function Btn({ kind = 'primary', size = 'md', icon, iconR, children, onClick, style, disabled, mono }) {
  const base = {
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
    height: size === 'lg' ? 46 : size === 'sm' ? 32 : 40,
    padding: size === 'lg' ? '0 22px' : size === 'sm' ? '0 12px' : '0 16px',
    borderRadius: size === 'lg' ? 'var(--r-4)' : 'var(--r-3)',
    fontSize: size === 'lg' ? 15 : size === 'sm' ? 12.5 : 13.5, fontWeight: 600,
    fontFamily: mono ? 'var(--font-mono)' : 'inherit',
    cursor: disabled ? 'not-allowed' : 'pointer', border: '1px solid transparent',
    transition: 'all .15s var(--ease)', whiteSpace: 'nowrap', letterSpacing: '-0.01em',
    opacity: disabled ? 0.5 : 1, ...style,
  };
  const kinds = {
    primary: { background: 'var(--brand)', color: '#fff', boxShadow: 'var(--sh-brand)' },
    dark:    { background: 'var(--blue-950)', color: '#fff', boxShadow: 'var(--sh-3)' },
    soft:    { background: 'var(--brand-soft)', color: 'var(--brand)', borderColor: 'var(--brand-soft-2)' },
    ghost:   { background: 'var(--surface)', color: 'var(--text-2)', borderColor: 'var(--line-strong)' },
    quiet:   { background: 'transparent', color: 'var(--text-2)', borderColor: 'transparent' },
  };
  const [hov, setHov] = useState(false);
  const hovStyle = !disabled && hov ? {
    primary: { background: 'var(--brand-hover)', transform: 'translateY(-1px)', boxShadow: 'var(--sh-brand-lg)' },
    dark:    { transform: 'translateY(-1px)' },
    soft:    { background: 'var(--brand-soft-2)' },
    ghost:   { borderColor: 'var(--brand-ring)', color: 'var(--brand)' },
    quiet:   { background: 'var(--surface-3)', color: 'var(--text)' },
  }[kind] : {};
  return (
    <button onClick={disabled ? undefined : onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ ...base, ...kinds[kind], ...hovStyle }}>
      {icon && <Icon name={icon} size={size === 'lg' ? 18 : 16} stroke={2} />}
      {children}
      {iconR && <Icon name={iconR} size={size === 'lg' ? 18 : 16} stroke={2} />}
    </button>
  );
}

// ─────────────────────────────────────────── App shell: Rail + TabStrip
const NAV = [
  { key: 'home', label: '首页', icon: 'home' },
  { key: 'apps', label: '应用资产库', icon: 'apps' },
  { key: 'builder', label: 'AI Builder', icon: 'builder', mono: false },
  { key: 'catalog', label: '自开发资产库', icon: 'store' },
  { key: 'coding', label: 'AI Coding', icon: 'coding', mono: true },
];

function Rail({ route, go }) {
  const activeKey = route.startsWith('builder') ? 'builder'
    : route.startsWith('coding') ? 'coding'
    : route === 'apps' ? 'apps' : route === 'catalog' ? 'catalog' : 'home';
  return (
    <aside style={{
      width: 220, flexShrink: 0, height: '100%', display: 'flex', flexDirection: 'column',
      background: 'var(--surface-2)', borderRight: '1px solid var(--line)',
    }}>
      <div style={{ minHeight: 62, display: 'flex', alignItems: 'center', gap: 11, padding: '16px 16px 12px' }}>
        <div style={{ width: 32, height: 32, display: 'grid', placeItems: 'center', borderRadius: 9,
          background: 'linear-gradient(145deg, var(--blue-600), var(--blue-800))', boxShadow: 'var(--sh-brand)' }}>
          <WhaleMark size={19} />
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: '-0.01em', lineHeight: 1.05 }}>睿鲸AI</div>
          <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 500, marginTop: 2, fontFamily: 'var(--font-mono)' }}>AI · 低代码工作台</div>
        </div>
      </div>

      <nav style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 2, padding: '8px 10px', overflowY: 'auto' }}>
        {NAV.map(n => {
          const on = activeKey === n.key;
          const isMod = n.key === 'builder' || n.key === 'coding';
          return (
            <button key={n.key} onClick={() => go(n.key)} style={{
              position: 'relative', display: 'flex', alignItems: 'center', gap: 10, minHeight: 38, padding: '0 10px',
              borderRadius: 8, border: 'none', cursor: 'pointer', textAlign: 'left', width: '100%',
              fontFamily: n.mono ? 'var(--font-mono)' : 'inherit',
              fontSize: 13, fontWeight: on ? 600 : 500,
              color: on ? 'var(--brand)' : 'var(--text-2)', background: on ? 'var(--brand-soft)' : 'transparent',
              transition: 'all .14s var(--ease)',
            }}
              onMouseEnter={e => { if (!on) { e.currentTarget.style.background = 'var(--surface)'; e.currentTarget.style.color = 'var(--text)'; } }}
              onMouseLeave={e => { if (!on) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-2)'; } }}>
              {on && <span style={{ position: 'absolute', left: -2, top: 7, bottom: 7, width: 3, borderRadius: 4, background: 'var(--brand)' }} />}
              <Icon name={n.icon} size={18} stroke={on ? 2 : 1.7} />
              <span style={{ flex: 1 }}>{n.label}</span>
              {isMod && <span style={{ fontSize: 9.5, fontFamily: 'var(--font-mono)', color: on ? 'var(--brand)' : 'var(--text-4)', opacity: 0.8 }}>{n.key === 'builder' ? '搭建' : '开发'}</span>}
            </button>
          );
        })}
        <div style={{ height: 1, background: 'var(--line)', margin: '8px 4px' }} />
        <button onClick={() => go('home')} style={{
          display: 'flex', alignItems: 'center', gap: 10, minHeight: 34, padding: '0 10px', borderRadius: 8,
          border: 'none', cursor: 'pointer', background: 'transparent', color: 'var(--text-3)', fontSize: 12.5, fontWeight: 500, fontFamily: 'inherit',
        }}>
          <Icon name="shield" size={16} /> 平台管理
        </button>
      </nav>

      <div style={{ padding: '10px 12px 14px', borderTop: '1px solid var(--line)' }}>
        <div style={{ fontSize: 10, color: 'var(--text-3)', fontWeight: 600, letterSpacing: '0.08em', margin: '2px 2px 6px' }}>当前租户</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', borderRadius: 8, background: 'var(--surface)', border: '1px solid var(--line)', fontSize: 12.5, fontWeight: 500 }}>
          <span style={{ width: 18, height: 18, display: 'grid', placeItems: 'center', borderRadius: 4, background: 'var(--brand-soft)', color: 'var(--brand)' }}><Icon name="building" size={12} /></span>
          得帆体验
          <Icon name="chevD" size={13} style={{ marginLeft: 'auto', color: 'var(--text-4)' }} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, padding: '0 2px' }}>
          <div style={{ width: 26, height: 26, borderRadius: 999, background: 'var(--brand)', color: '#fff', display: 'grid', placeItems: 'center', fontSize: 12, fontWeight: 600 }}>李</div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>李实施</div>
            <div style={{ fontSize: 10.5, color: 'var(--text-3)', display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ width: 6, height: 6, borderRadius: 999, background: 'var(--ok)' }} />在线</div>
          </div>
        </div>
      </div>
    </aside>
  );
}

function TabStrip({ tabs, active, onPick, onClose }) {
  return (
    <div style={{ height: 44, flexShrink: 0, display: 'flex', alignItems: 'flex-end', gap: 2, padding: '0 12px',
      background: 'var(--surface-2)', borderBottom: '1px solid var(--line)' }}>
      {tabs.map(t => {
        const on = t.key === active;
        return (
          <div key={t.key} onClick={() => onPick(t.key)} style={{
            display: 'flex', alignItems: 'center', gap: 8, height: 34, padding: '0 12px', cursor: 'pointer',
            borderRadius: '8px 8px 0 0', fontSize: 12.5, fontWeight: on ? 600 : 500,
            color: on ? 'var(--text)' : 'var(--text-3)', background: on ? 'var(--bg)' : 'transparent',
            borderTop: on ? '1px solid var(--line)' : '1px solid transparent',
            borderLeft: on ? '1px solid var(--line)' : '1px solid transparent',
            borderRight: on ? '1px solid var(--line)' : '1px solid transparent', borderBottom: 'none',
            fontFamily: t.mono ? 'var(--font-mono)' : 'inherit', position: 'relative', top: 1, whiteSpace: 'nowrap',
          }}>
            <Icon name={t.icon} size={14} stroke={on ? 2 : 1.6} style={{ color: on ? 'var(--brand)' : 'var(--text-4)' }} />
            {t.label}
            {t.closable !== false && (
              <span onClick={e => { e.stopPropagation(); onClose(t.key); }} style={{ marginLeft: 2, width: 16, height: 16, display: 'grid', placeItems: 'center', borderRadius: 4, color: 'var(--text-4)' }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--surface-3)'} onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></svg>
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

Object.assign(window, { Icon, ModuleTag, Badge, Btn, Rail, TabStrip, NAV });
