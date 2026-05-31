// 设计文档 (SPEC management)
// Replaces the old /templates page. Three things in one place:
//   1. SPEC docs per app (versioned, diffable, exportable)
//   2. Standard markdown templates (legacy)
//   3. Origin tracking — every SPEC knows whether it was bootstrapped
//      from a template, from an industry pack, or hand-written.

function Specs() {
  const { navigate } = useContext(RouteCtx);
  const { specs, templates } = window.MOCK;
  const [tab, setTab] = useState('app');
  const [selected, setSelected] = useState(specs[0].id);
  const cur = specs.find(s => s.id === selected) || specs[0];
  const [versionPick, setVersionPick] = useState(cur.versions[0].v);

  return (
    <div className="page">
      <div className="page-pad" style={{ maxWidth: 1320 }}>
        <div className="page-head">
          <div>
            <h1 className="page-title">设计文档 <span style={{ color: 'var(--text-3)', fontSize: 13, fontWeight: 500, marginLeft: 8 }}>· SPEC 管理</span></h1>
            <div className="page-subtitle">
              对话过程中产出的 SPEC 都汇聚在这里：每个应用一份、多版本、可对比、可导出。
              SPEC 是 AI / 实施 / 客户之间的**共同语言**，所有部署都基于某个 SPEC 版本。
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary"><I.upload size={13} /> 上传文档</button>
            <button className="btn btn-primary"><I.plus size={13} /> 新建 SPEC</button>
          </div>
        </div>

        {/* Origin breakdown banner */}
        <div className="spec-origin">
          <div className="spec-origin-card">
            <div className="spec-origin-icon spec-origin-template"><I.doc size={14} /></div>
            <div>
              <div className="spec-origin-l">来自标准模板</div>
              <div className="spec-origin-v">{templates.length} 个模板 · 1 个 SPEC</div>
            </div>
          </div>
          <div className="spec-origin-arrow"><I.arrowRight size={14} /></div>
          <div className="spec-origin-card">
            <div className="spec-origin-icon spec-origin-industry"><I.industry size={14} /></div>
            <div>
              <div className="spec-origin-l">来自行业知识库</div>
              <div className="spec-origin-v">2 个行业包 · {specs.filter(s => s.origin.startsWith('行业')).length} 个 SPEC</div>
            </div>
          </div>
          <div className="spec-origin-arrow"><I.arrowRight size={14} /></div>
          <div className="spec-origin-card">
            <div className="spec-origin-icon spec-origin-chat"><I.chat size={14} /></div>
            <div>
              <div className="spec-origin-l">睿鲸 AI Builder 对话产出</div>
              <div className="spec-origin-v">{specs.length} 份 SPEC · 累计 11 版本</div>
            </div>
          </div>
          <div className="spec-origin-arrow"><I.arrowRight size={14} /></div>
          <div className="spec-origin-card spec-origin-deployed">
            <div className="spec-origin-icon spec-origin-deploy"><I.rocket size={14} /></div>
            <div>
              <div className="spec-origin-l">部署到 aPaaS 平台</div>
              <div className="spec-origin-v">{specs.filter(s => s.versions.some(v => v.status.startsWith('deployed'))).length} 应用上线</div>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="apps-tabs" style={{ marginTop: 18 }}>
          <button className={`apps-tab ${tab === 'app' ? 'active' : ''}`} onClick={() => setTab('app')}>
            <I.doc size={13} /> 应用 SPEC<span className="apps-tab-count">{specs.length}</span>
          </button>
          <button className={`apps-tab ${tab === 'tpl' ? 'active' : ''}`} onClick={() => setTab('tpl')}>
            <I.template size={13} /> 标准模板<span className="apps-tab-count">{templates.length}</span>
          </button>
        </div>

        {tab === 'app' && (
          <div className="spec-layout">
            {/* Left: list */}
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
              {specs.map(s => (
                <button key={s.id}
                  className={`spec-item ${selected === s.id ? 'active' : ''}`}
                  onClick={() => { setSelected(s.id); setVersionPick(s.versions[0].v); }}>
                  <div className={`landing-app-icon tone-${s.color}`} style={{ width: 28, height: 28, borderRadius: 7, fontSize: 12 }}>{s.app.slice(0,1)}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="spec-item-name">{s.app}</div>
                    <div className="spec-item-meta">
                      <span className="mono">{s.appCode}</span>
                      <span>·</span>
                      <span className="mono">{s.currentVersion}</span>
                      <span>·</span>
                      <span>{s.updatedAt}</span>
                    </div>
                    <div className="spec-item-diff">
                      {s.diff.add > 0 &&    <span className="spec-diff-add">+{s.diff.add}</span>}
                      {s.diff.modify > 0 && <span className="spec-diff-mod">~{s.diff.modify}</span>}
                      {s.diff.remove > 0 && <span className="spec-diff-del">-{s.diff.remove}</span>}
                      <span className="spec-item-origin">由 {s.origin}</span>
                    </div>
                  </div>
                </button>
              ))}
            </div>

            {/* Right: SPEC viewer */}
            <div className="card card-pad spec-detail">
              <div className="spec-detail-head">
                <div>
                  <div className="spec-detail-title">{cur.app}</div>
                  <div className="spec-detail-sub">
                    <span className="mono">{cur.appCode}</span>
                    <span>·</span>
                    <span>由 {cur.origin}</span>
                    <span>·</span>
                    <span>最后编辑 {cur.updatedAt} · {cur.author}</span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="btn btn-secondary btn-sm"><I.download size={12} /> 导出 .md</button>
                  <button className="btn btn-secondary btn-sm"><I.external size={12} /> 在 Builder 打开</button>
                  <button className="btn btn-primary btn-sm"><I.rocket size={12} /> 基于此部署</button>
                </div>
              </div>

              {/* Version timeline */}
              <div className="spec-timeline">
                {cur.versions.map((v, i) => (
                  <button key={v.v} className={`spec-ver ${versionPick === v.v ? 'active' : ''}`} onClick={() => setVersionPick(v.v)}>
                    <div className="spec-ver-dot">{i === 0 && <span className="spec-ver-pulse" />}</div>
                    <div className="spec-ver-body">
                      <div className="spec-ver-row1">
                        <span className="mono spec-ver-tag">{v.v}</span>
                        <SpecStatusBadge status={v.status} />
                        <span className="spec-ver-time">{v.time}</span>
                      </div>
                      <div className="spec-ver-note">{v.note}</div>
                      <div className="spec-ver-author">— {v.author}</div>
                    </div>
                  </button>
                ))}
              </div>

              {/* Section preview */}
              <div className="spec-sections">
                <div className="spec-sections-head">
                  <span>SPEC v{versionPick.replace('v','')} · 章节</span>
                  <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                    <button className="section-action">对比 v2 →</button>
                    <button className="section-action">查看完整文档 →</button>
                  </div>
                </div>
                <div className="spec-sections-grid">
                  {cur.sections.map((s, i) => (
                    <div key={i} className="spec-section-card">
                      <div className="spec-section-num">{String(i+1).padStart(2,'0')}</div>
                      <div className="spec-section-name">{s}</div>
                      <I.chevronR size={12} style={{ color: 'var(--text-3)', marginLeft: 'auto' }} />
                    </div>
                  ))}
                </div>
              </div>

              {/* Inline excerpt */}
              <div className="spec-excerpt">
                <div className="spec-excerpt-head">摘录 · 数据模型 · 资产主档</div>
                <pre className="spec-excerpt-body mono">{`## 5.1 资产主档 (asset_main)

每台资产的台账主表。字段：
| 字段       | 类型     | 必填 | 唯一 | 说明                       |
|-----------|---------|-----|-----|---------------------------|
| asset_no  | String  | ✓   | ✓   | 资产编号 AST + 6 位流水    |
| asset_name| String  | ✓   |     |                            |
| category  | Ref     | ✓   |     | → asset_category.id        |
| serial_no | String  |     | ✓   | 序列号 / SN                |
| warranty_until  | Date  |  |   | 保修截止 (本版新增)         |
| purchase_source | Dict  |  |   | 采购来源 (本版新增)         |
…`}</pre>
              </div>
            </div>
          </div>
        )}

        {tab === 'tpl' && (
          <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 12 }}>
            {templates.map(t => (
              <div key={t.code} className="card card-pad card-interactive">
                <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                  <div className="landing-path-icon-doc landing-path-icon" style={{ width: 38, height: 38 }}><I.doc size={18} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>{t.name}</div>
                    <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 2, display: 'flex', gap: 6 }}>
                      <span className="badge">{t.category}</span>
                      <span className="mono">{t.filename}</span>
                    </div>
                  </div>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--text-2)', marginTop: 12, lineHeight: 1.55 }}>{t.summary}</div>
                <div style={{ display: 'flex', gap: 8, marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                  <button className="btn btn-secondary btn-sm" style={{ flex: 1 }}>预览</button>
                  <button className="btn btn-secondary btn-sm" style={{ flex: 1 }}>下载</button>
                  <button className="btn btn-primary btn-sm" style={{ flex: 1 }}>基于此搭建</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SpecStatusBadge({ status }) {
  const map = {
    'draft':           { l: '草稿',         c: 'badge-amber' },
    'deployed-test':   { l: '已部署测试',   c: 'badge-sky' },
    'deployed-prod':   { l: '已部署生产',   c: 'badge-emerald' },
    'archived':        { l: '归档',         c: '' },
  }[status] || { l: status, c: '' };
  return <span className={`badge ${map.c}`}><span className="badge-dot" />{map.l}</span>;
}

window.Specs = Specs;
