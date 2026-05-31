// 行业知识库 — 客户沉淀行业 Palantir Ontology 的答案
//
// 解决的问题：
//   客户问"如果我想沉淀我们行业（制造 / 零售 / 物流…）的最佳实践，
//   像 Palantir 那样有自己的 Ontology + 共用业务对象图谱，怎么办？"
//
// 这个页面的设计回答：
//   * 行业知识包 = 业务对象（含字段）+ 关系图 + 流程模板 + 行业字典 + 表单 + 角色
//   * 一键安装到当前租户 → 所有新建应用可基于包内对象起步
//   * AI Builder 在生成 SPEC 时优先复用已安装包的对象
//   * 客户可基于已有包派生「企业专属包」并发布回平台

function Industry() {
  const { navigate } = useContext(RouteCtx);
  const { industryPacks, industryOntology } = window.MOCK;
  const [selected, setSelected] = useState(industryPacks[0].id);
  const cur = industryPacks.find(p => p.id === selected) || industryPacks[0];
  const ont = industryOntology;

  return (
    <div className="page">
      <div className="page-pad" style={{ maxWidth: 1320 }}>
        <div className="page-head">
          <div>
            <h1 className="page-title">
              行业知识库
              <span className="badge badge-brand" style={{ marginLeft: 10, verticalAlign: 'middle' }}><Tooltip content="Ontology = 行业模型 / 业务对象图谱。把业务里的实体、关系、流程沉淀成标准包，新建应用一键复用。">行业模型 · Beta</Tooltip></span>
            </h1>
            <div className="page-subtitle">
              <b style={{ color: 'var(--text)' }}>把行业最佳实践沉淀成可复用的"行业包"。</b>
              包含<b>业务对象</b>、<b>对象关系</b>、<b>标准流程</b>、<b>行业字典</b>，
              在新建应用时一键复用。客户可基于已有包派生企业专属包。
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary"><I.upload size={13} /> 导入企业包 (.zip)</button>
            <button className="btn btn-primary"><I.plus size={13} /> 派生新包</button>
          </div>
        </div>

        {/* Top concept strip */}
        <div className="industry-concept">
          <div className="industry-concept-pill"><span className="industry-concept-num">01</span><div><b>业务对象</b><span>带字段的标准实体</span></div></div>
          <I.chevronR size={14} style={{ color: 'var(--text-4)' }} />
          <div className="industry-concept-pill"><span className="industry-concept-num">02</span><div><b>对象关系</b><span>1:n · n:m · 自引用</span></div></div>
          <I.chevronR size={14} style={{ color: 'var(--text-4)' }} />
          <div className="industry-concept-pill"><span className="industry-concept-num">03</span><div><b>标准流程</b><span>含 SLA 与角色</span></div></div>
          <I.chevronR size={14} style={{ color: 'var(--text-4)' }} />
          <div className="industry-concept-pill"><span className="industry-concept-num">04</span><div><b>行业字典</b><span>标准状态码 / 行业代码</span></div></div>
          <I.chevronR size={14} style={{ color: 'var(--text-4)' }} />
          <div className="industry-concept-pill industry-concept-pill-final"><span className="industry-concept-num">→</span><div><b>新应用秒级起步</b><span>AI Builder 自动复用</span></div></div>
        </div>

        {/* Pack list */}
        <div className="section-head" style={{ marginTop: 22 }}>
          <div className="section-title">行业包 <span className="section-title-count">{industryPacks.length}</span></div>
          <div style={{ display: 'flex', gap: 8 }}>
            <span className="badge badge-emerald"><span className="badge-dot" />已安装 {industryPacks.filter(p => p.installed).length}</span>
            <button className="section-action">浏览社区包 →</button>
          </div>
        </div>

        <div className="industry-pack-grid">
          {industryPacks.map(p => (
            <button key={p.id}
              className={`industry-pack-card industry-pack-${p.tone} ${selected === p.id ? 'is-selected' : ''}`}
              onClick={() => setSelected(p.id)}>
              <div className="industry-pack-head">
                <div className={`industry-pack-icon tone-${p.tone}`}><I.industry size={18} /></div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="industry-pack-name">{p.name} {p.default && <span className="badge badge-brand" style={{ marginLeft: 4 }}>默认</span>}</div>
                  <div className="industry-pack-meta">
                    <span className="mono">{p.code}</span>
                    <span>·</span>
                    <span className="mono">{p.version}</span>
                    <span>·</span>
                    <span>更新 {p.updated}</span>
                  </div>
                </div>
                {p.installed
                  ? <span className="badge badge-emerald"><I.check size={10} /> 已安装</span>
                  : <span className="badge">未安装</span>}
              </div>
              <div className="industry-pack-summary">{p.summary}</div>
              <div className="industry-pack-stats">
                <div><b>{p.stats.entities}</b> 业务对象</div>
                <div><b>{p.stats.relations}</b> 关系</div>
                <div><b>{p.stats.workflows}</b> 流程</div>
                <div><b>{p.stats.dicts}</b> 字典</div>
                <div><b>{p.stats.forms}</b> 表单</div>
                <div><b>{p.stats.roles}</b> 角色</div>
              </div>
              <div className="industry-pack-foot">
                <span className="industry-pack-by">{p.maintainer}</span>
                {p.adopted.length > 0 && (
                  <span className="industry-pack-adopt">已被 {p.adopted.length} 个客户 / 应用采用</span>
                )}
              </div>
            </button>
          ))}
        </div>

        {/* Selected pack detail — Ontology view */}
        <div className="industry-detail">
          <div className="industry-detail-head">
            <div>
              <div className="industry-detail-title">
                <span className={`industry-pack-icon tone-${cur.tone}`} style={{ width: 28, height: 28, borderRadius: 8 }}><I.industry size={14} /></span>
                {cur.name} · Ontology
                <span className="mono" style={{ fontSize: 12, color: 'var(--text-3)', fontWeight: 500, marginLeft: 6 }}>{cur.code} {cur.version}</span>
              </div>
              <div style={{ fontSize: 12.5, color: 'var(--text-2)', marginTop: 4 }}>{cur.summary}</div>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="btn btn-secondary btn-sm"><I.download size={12} /> 导出 .zip</button>
              <button className="btn btn-secondary btn-sm"><I.copy size={12} /> 派生企业包</button>
              <button className="btn btn-primary btn-sm" disabled={cur.installed}>
                {cur.installed ? <><I.check size={12} /> 已安装到当前租户</> : <><I.download size={12} /> 安装到当前租户</>}
              </button>
            </div>
          </div>

          <div className="industry-onto-grid">
            {/* Left: Graph */}
            <div className="industry-onto-graph card">
              <div className="industry-onto-graph-head">
                <I.network size={13} /> <b>业务对象关系图</b>
                <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-3)' }}>{ont.entities.length} 对象 · {ont.relations.length} 关系</span>
              </div>
              <svg className="industry-onto-svg" viewBox="0 0 620 480" preserveAspectRatio="xMidYMid meet">
                <defs>
                  <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                    <path d="M0 0 L10 5 L0 10 z" fill="var(--text-3)" />
                  </marker>
                </defs>
                {/* Relations as curves */}
                {ont.relations.map((r, i) => {
                  const f = ont.entities.find(e => e.code === r.from);
                  const t = ont.entities.find(e => e.code === r.to);
                  if (!f || !t) return null;
                  const x1 = f.x + 60, y1 = f.y + 26;
                  const x2 = t.x + 60, y2 = t.y + 26;
                  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
                  return (
                    <g key={i} className="industry-onto-edge">
                      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--border-strong)" strokeWidth="1" strokeDasharray={r.from === 'work_order' ? '0' : '3 3'} markerEnd="url(#arr)" />
                      <text x={mx} y={my} fill="var(--text-3)" fontSize="9" textAnchor="middle" className="mono">{r.label}</text>
                    </g>
                  );
                })}
                {/* Entities */}
                {ont.entities.map(e => (
                  <g key={e.code} className={`industry-onto-node industry-onto-node-${e.tone} ${e.hot ? 'is-hot' : ''}`}>
                    <rect x={e.x} y={e.y} width="120" height="52" rx="10" />
                    <text x={e.x + 60} y={e.y + 20} textAnchor="middle" fontSize="12" fontWeight="600" fill="currentColor">{e.name}</text>
                    <text x={e.x + 60} y={e.y + 36} textAnchor="middle" fontSize="10" fill="var(--text-3)" className="mono">{e.code} · {e.fields}f</text>
                  </g>
                ))}
              </svg>
              <div className="industry-onto-graph-foot">
                <span>提示：点击节点可查看字段定义 · 关系标签为语义动词</span>
              </div>
            </div>

            {/* Right: lists */}
            <div className="industry-onto-side">
              <div className="card card-pad" style={{ padding: 16 }}>
                <div className="industry-onto-side-head">标准流程 · {ont.workflows.length}</div>
                <div className="industry-onto-list">
                  {ont.workflows.map((w, i) => (
                    <div key={i} className="industry-onto-row">
                      <I.flow size={12} style={{ color: 'var(--brand-text)' }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 500 }}>{w.name}</div>
                        <div style={{ fontSize: 10.5, color: 'var(--text-3)' }}>{w.nodes} 节点 · SLA {w.sla}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card card-pad" style={{ padding: 16 }}>
                <div className="industry-onto-side-head">关键字典 · {ont.dictHighlight.length} <span style={{ fontWeight: 500, color: 'var(--text-3)' }}>/ 共 {cur.stats.dicts}</span></div>
                <div className="industry-onto-list">
                  {ont.dictHighlight.map((d, i) => (
                    <div key={i} className="industry-onto-row">
                      <I.dict size={12} style={{ color: 'var(--brand-text)' }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 500 }}>{d.name}</div>
                        <div style={{ fontSize: 10.5, color: 'var(--text-3)' }} className="mono">{d.code} · {d.items} 项</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="industry-howto">
                <div className="industry-howto-head"><I.sparkle size={13} /> 客户如何沉淀自己的行业</div>
                <ol className="industry-howto-list">
                  <li><b>派生</b> 基于「{cur.name}」一键派生「企业专属包」</li>
                  <li><b>扩展</b> 在派生包里增减对象、字段、关系、字典、流程</li>
                  <li><b>验证</b> 用 1-2 个真实应用试用 → SPEC 自动注释为复用</li>
                  <li><b>发布</b> 发布回平台，租户内 / 跨租户均可订阅升级</li>
                </ol>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}

window.Industry = Industry;
