/* screens_assets.jsx — 应用资产库 + 自开发资产库 */
const { useState: useStateA } = React;

function AppAssetCard({ a, go }) {
  const [hov, setHov] = useStateA(false);
  return (
    <div onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)} onClick={() => go('builder')}
      style={{ background: 'var(--surface)', border: a.star ? '1.5px solid var(--brand)' : '1px solid var(--line)', borderRadius: 16, padding: 18, cursor: 'pointer',
        boxShadow: hov ? 'var(--sh-4)' : 'var(--sh-1)', transform: hov ? 'translateY(-2px)' : 'none', transition: 'all .18s var(--ease)', position: 'relative' }}>
      {a.star && <span style={{ position: 'absolute', top: -9, left: 16, fontSize: 10, fontWeight: 700, color: '#fff', background: 'var(--brand)', padding: '2px 8px', borderRadius: 999, fontFamily: 'var(--font-mono)' }}>刚生成</span>}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
        <div style={{ width: 44, height: 44, borderRadius: 12, display: 'grid', placeItems: 'center', flexShrink: 0, background: 'linear-gradient(145deg, var(--blue-600), var(--blue-800))', color: '#fff', boxShadow: 'var(--sh-2)' }}><Icon name="building" size={22} stroke={1.9} /></div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 15.5, fontWeight: 700, letterSpacing: '-0.01em' }}>{a.name}</span>
            {a.status === 'live' ? <Badge tone="live">运行中</Badge> : <Badge tone="warn">草稿</Badge>}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-4)', fontFamily: 'var(--font-mono)', marginTop: 3 }}>{a.code}</div>
        </div>
      </div>
      <p style={{ fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.55, margin: '0 0 14px', minHeight: 38 }}>{a.desc}</p>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, paddingTop: 12, borderTop: '1px solid var(--line-2)', fontSize: 11.5, color: 'var(--text-3)' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><Icon name="layers" size={13} /> {a.models} 模型</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><Icon name="builder" size={13} /> {a.by}</span>
        <span style={{ marginLeft: 'auto' }}>{a.when}</span>
      </div>
    </div>
  );
}

function CodeAssetCard({ a, go }) {
  const [hov, setHov] = useStateA(false);
  const isPage = a.kind === '定制页面';
  return (
    <div className="code-scope" onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)} onClick={() => go('coding')}
      style={{ background: 'var(--surface)', border: a.star ? '1.5px solid var(--brand)' : '1px solid var(--line)', borderRadius: 16, padding: 18, cursor: 'pointer',
        boxShadow: hov ? 'var(--sh-4)' : 'var(--sh-1)', transform: hov ? 'translateY(-2px)' : 'none', transition: 'all .18s var(--ease)', position: 'relative' }}>
      {a.star && <span style={{ position: 'absolute', top: -9, left: 16, fontSize: 10, fontWeight: 700, color: '#fff', background: 'var(--brand)', padding: '2px 8px', borderRadius: 999, fontFamily: 'var(--font-mono)' }}>刚生成</span>}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 12 }}>
        <div style={{ width: 44, height: 44, borderRadius: 12, display: 'grid', placeItems: 'center', flexShrink: 0, background: 'var(--blue-950)', color: '#fff', boxShadow: 'var(--sh-2)' }}><Icon name={isPage ? 'grid2' : 'box'} size={21} stroke={1.9} /></div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)', letterSpacing: '-0.01em' }}>{a.name}</span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-4)', fontFamily: 'var(--font-mono)', marginTop: 3 }}>{'<'}{a.code}{' />'}</div>
        </div>
        <Badge tone={isPage ? 'brand' : 'neutral'} mono>{a.kind}</Badge>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
        {a.tags.map(t => <span key={t} style={{ fontSize: 10.5, color: 'var(--text-3)', padding: '3px 8px', borderRadius: 6, background: 'var(--surface-3)', fontFamily: 'var(--font-mono)' }}>{t}</span>)}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, paddingTop: 12, borderTop: '1px solid var(--line-2)', fontSize: 11.5, color: 'var(--text-3)' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><Icon name="building" size={13} /> {a.host}</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><Icon name="swap" size={13} /> 复用 ×{a.reuse}</span>
        <span style={{ marginLeft: 'auto' }}>{a.when}</span>
      </div>
    </div>
  );
}

function AssetLibrary({ kind, go }) {
  const isApps = kind === 'apps';
  const list = isApps ? window.APP_ASSETS : window.CODE_ASSETS;
  const [q, setQ] = useStateA('');
  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'var(--bg-app)' }}>
      <div style={{ width: 'min(100%, 1080px)', margin: '0 auto', padding: '38px 36px 60px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginBottom: 26 }}>
          <div style={{ width: 48, height: 48, borderRadius: 13, display: 'grid', placeItems: 'center', flexShrink: 0,
            background: isApps ? 'linear-gradient(145deg, var(--blue-600), var(--blue-800))' : 'var(--blue-950)', color: '#fff', boxShadow: 'var(--sh-brand)' }}>
            <Icon name={isApps ? 'apps' : 'store'} size={24} stroke={1.9} />
          </div>
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em', margin: '0 0 5px', fontFamily: isApps ? 'var(--font-sans)' : 'var(--font-mono)' }}>{isApps ? '应用资产库' : '自开发资产库'}</h1>
            <p style={{ fontSize: 13.5, color: 'var(--text-2)', margin: 0 }}>{isApps ? 'AI Builder 搭出的完整应用 —— 可运行、可继续扩展。' : 'AI Coding 产出的定制页面与可复用组件 —— 可装回应用、跨应用复用。'}</p>
          </div>
          <Btn kind={isApps ? 'primary' : 'dark'} mono={!isApps} icon="plus" onClick={() => go(isApps ? 'builder' : 'coding')}>{isApps ? '搭新应用' : '写新组件'}</Btn>
        </div>

        {/* toolbar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, maxWidth: 320, height: 38, padding: '0 12px', borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--line-strong)' }}>
            <Icon name="search" size={15} style={{ color: 'var(--text-4)' }} />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder={isApps ? '搜索应用…' : '搜索组件 / 页面…'} style={{ border: 'none', outline: 'none', background: 'transparent', fontFamily: 'inherit', fontSize: 13, flex: 1, color: 'var(--text)' }} />
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {(isApps ? ['全部', '运行中', '草稿'] : ['全部', '定制页面', '通用组件']).map((f, i) => (
              <button key={f} style={{ fontSize: 12, fontWeight: i === 0 ? 600 : 500, padding: '7px 13px', borderRadius: 999, cursor: 'pointer', fontFamily: isApps ? 'inherit' : 'var(--font-mono)',
                border: '1px solid', borderColor: i === 0 ? 'var(--brand-soft-2)' : 'var(--line)', color: i === 0 ? 'var(--brand)' : 'var(--text-3)', background: i === 0 ? 'var(--brand-soft)' : 'var(--surface)' }}>{f}</button>
            ))}
          </div>
          <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>{list.length} 项</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16 }}>
          {list.filter(a => !q || a.name.includes(q) || a.code.toLowerCase().includes(q.toLowerCase())).map(a => isApps ? <AppAssetCard key={a.code} a={a} go={go} /> : <CodeAssetCard key={a.code} a={a} go={go} />)}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { AssetLibrary });
