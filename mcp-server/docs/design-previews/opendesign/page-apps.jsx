// Apps list page — filter bar + dense cards with stat counts and quick actions.

function Apps() {
  const { navigate } = useContext(RouteCtx);
  const { apps } = window.MOCK;
  const [tab, setTab] = useState('all');
  const [view, setView] = useState('grid');
  const [q, setQ] = useState('');

  const tabs = [
    { key: 'all',        label: '全部',   count: apps.length },
    { key: 'completed',  label: '已生成', count: apps.filter(a => a.status === 'completed').length },
    { key: 'updating',   label: '更新中', count: apps.filter(a => a.status === 'updating').length },
    { key: 'generating', label: '生成中', count: apps.filter(a => a.status === 'generating').length },
    { key: 'draft',      label: '草稿',   count: apps.filter(a => a.status === 'draft').length },
  ];

  const filtered = apps
    .filter(a => tab === 'all' ? true : a.status === tab)
    .filter(a => q ? (a.name + a.code + a.desc).toLowerCase().includes(q.toLowerCase()) : true);

  return (
    <div className="page">
      <div className="page-pad">
        <div className="page-head">
          <div>
            <h1 className="page-title">我的应用</h1>
            <div className="page-subtitle">当前租户下的 Builder 应用。这里承接继续对话、AI 调整、生成到平台和打开 aPaaS。</div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary" onClick={() => navigate('/admin')}>
              <I.download size={14} /> 从平台导入
            </button>
            <button className="btn btn-primary" onClick={() => navigate('/')}>
              <I.plus size={14} /> 首页新建
            </button>
          </div>
        </div>

        {/* Filter bar */}
        <div className="apps-bar">
          <div className="apps-tabs">
            {tabs.map(t => (
              <button key={t.key} className={`apps-tab ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
                {t.label}
                <span className="apps-tab-count">{t.count}</span>
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <div className="apps-search">
              <I.search size={13} />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索应用名称、编码、描述..." />
            </div>
            <div className="apps-view-toggle">
              <button className={view === 'grid' ? 'active' : ''} onClick={() => setView('grid')} title="卡片视图"><I.grid size={14} /></button>
              <button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')} title="列表视图"><I.list size={14} /></button>
            </div>
          </div>
        </div>

        {view === 'grid' ? (
          <div className="apps-grid">
            {filtered.map(a => (
              <article key={a.id} className="app-card card card-interactive" onClick={() => navigate('/chat?app=' + a.id)}>
                <div className="app-card-head">
                  <div className={`landing-app-icon tone-${a.color}`}>{a.name.slice(0, 1)}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="landing-app-name truncate">{a.name}</div>
                    <div className="landing-app-meta">
                      <span className="mono">{a.code}</span>
                      {a.apaasAppId && <><span>·</span><span className="mono">{a.apaasAppId}</span></>}
                    </div>
                  </div>
                  <button className="icon-btn" onClick={(e) => { e.stopPropagation(); navigate('/chat?app=' + a.id); }} title="AI 调整" style={{ width: 28, height: 28 }}>
                    <I.sparkle size={14} />
                  </button>
                </div>

                <p className="app-card-desc">{a.desc}</p>

                <div className="app-card-tags">
                  <StatusBadge status={a.status} />
                  {a.env !== '—' && <span className="badge badge-outline">{a.env}</span>}
                  {a.source === 'imported' && <span className="badge"><I.download size={10} /> 平台导入</span>}
                </div>

                <div className="app-card-stats">
                  <div className="app-stat">
                    <div className="app-stat-icon tone-indigo"><I.model size={11} /></div>
                    <div className="app-stat-val">{a.models}</div>
                    <div className="app-stat-label">模型</div>
                  </div>
                  <div className="app-stat">
                    <div className="app-stat-icon tone-sky"><I.form size={11} /></div>
                    <div className="app-stat-val">{a.forms}</div>
                    <div className="app-stat-label">表单</div>
                  </div>
                  <div className="app-stat">
                    <div className="app-stat-icon tone-amber"><I.role size={11} /></div>
                    <div className="app-stat-val">{a.roles}</div>
                    <div className="app-stat-label">角色</div>
                  </div>
                  <div className="app-stat">
                    <div className="app-stat-icon tone-emerald"><I.dict size={11} /></div>
                    <div className="app-stat-val">{a.dicts}</div>
                    <div className="app-stat-label">字典</div>
                  </div>
                </div>

                {a.conversations.length > 0 && (
                  <div className="app-card-history">
                    <div className="app-card-history-label">最近对话</div>
                    {a.conversations.slice(0, 2).map(c => (
                      <button key={c.id} className="app-card-history-item" onClick={(e) => { e.stopPropagation(); navigate('/chat?conv=' + c.id); }}>
                        <I.chat size={11} />
                        <span className="truncate" style={{ flex: 1 }}>{c.title}</span>
                        <span style={{ color: 'var(--text-3)', fontSize: 11, flexShrink: 0 }}>{c.time}</span>
                      </button>
                    ))}
                  </div>
                )}

                <div className="app-card-foot">
                  <span className="app-card-foot-time">{a.updatedAt}</span>
                  <div style={{ display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                    {a.apaasAppId && (
                      <button className="icon-btn" title="在平台打开"><I.external size={14} /></button>
                    )}
                    <button className="icon-btn" title="生成到平台"><I.upload size={13} /></button>
                    <button className="icon-btn" title="删除" style={{ color: 'var(--text-3)' }}><I.trash size={14} /></button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="apps-table card" style={{ padding: 0 }}>
            <div className="apps-row apps-row-head">
              <div style={{ flex: 2 }}>应用</div>
              <div style={{ width: 120 }}>状态</div>
              <div style={{ width: 100 }}>环境</div>
              <div style={{ width: 220, textAlign: 'right' }}>模型 / 表单 / 角色 / 字典</div>
              <div style={{ width: 140 }}>更新时间</div>
              <div style={{ width: 80 }} />
            </div>
            {filtered.map(a => (
              <button key={a.id} className="apps-row apps-row-item" onClick={() => navigate('/chat?app=' + a.id)}>
                <div style={{ flex: 2, display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                  <div className={`landing-app-icon tone-${a.color}`} style={{ width: 28, height: 28, borderRadius: 7, fontSize: 12 }}>{a.name.slice(0, 1)}</div>
                  <div style={{ minWidth: 0 }}>
                    <div className="apps-row-name truncate">{a.name}</div>
                    <div className="apps-row-sub truncate">{a.desc}</div>
                  </div>
                </div>
                <div style={{ width: 120 }}><StatusBadge status={a.status} /></div>
                <div style={{ width: 100, color: 'var(--text-2)', fontSize: 12.5 }}>{a.env}</div>
                <div style={{ width: 220, textAlign: 'right', color: 'var(--text-2)', fontSize: 12.5 }} className="mono">
                  {a.models} / {a.forms} / {a.roles} / {a.dicts}
                </div>
                <div style={{ width: 140, color: 'var(--text-3)', fontSize: 12.5 }}>{a.updatedAt}</div>
                <div style={{ width: 80, display: 'flex', justifyContent: 'flex-end', gap: 2 }} onClick={(e) => e.stopPropagation()}>
                  {a.apaasAppId && <button className="icon-btn" title="平台打开" style={{ width: 26, height: 26 }}><I.external size={13} /></button>}
                  <button className="icon-btn" title="AI 调整" style={{ width: 26, height: 26 }}><I.sparkle size={13} /></button>
                </div>
              </button>
            ))}
          </div>
        )}

        {filtered.length === 0 && (
          <div className="empty">
            <I.apps size={32} />
            <div className="empty-title">没有匹配的应用</div>
            <div className="empty-sub">试试调整筛选条件，或新建一个应用。</div>
            <button className="btn btn-primary" onClick={() => navigate('/chat')}>
              <I.plus size={13} /> 回首页新建
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

window.Apps = Apps;
