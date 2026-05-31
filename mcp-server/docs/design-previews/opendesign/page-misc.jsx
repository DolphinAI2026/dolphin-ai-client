// Marketplace, Login, Admin pages

function Marketplace() {
  const { navigate } = useContext(RouteCtx);
  const { marketplace } = window.MOCK;
  const [cat, setCat] = useState('all');
  const [sort, setSort] = useState('latest');
  const [q, setQ] = useState('');

  const categories = [
    { key: 'all', label: '全部', count: marketplace.length },
    { key: 'form-component', label: '表单组件', count: marketplace.filter(m => m.category === 'form-component').length },
    { key: 'form-page', label: '页面', count: marketplace.filter(m => m.category === 'form-page').length },
    { key: 'backend-api', label: '后端接口', count: marketplace.filter(m => m.category === 'backend-api').length },
  ];

  let items = marketplace.filter(m => cat === 'all' || m.category === cat);
  items = items.filter(m => !q || (m.name + m.desc + m.tags.join(' ')).toLowerCase().includes(q.toLowerCase()));
  if (sort === 'popular') items = [...items].sort((a, b) => b.downloads - a.downloads);

  return (
    <div className="page">
      <div className="page-pad">
        <div className="page-head">
          <div>
            <h1 className="page-title">组件市场 <span className="badge badge-amber" style={{ verticalAlign: 'middle', marginLeft: 8 }}>Beta</span></h1>
            <div className="page-subtitle">复用团队沉淀的组件、页面、后端接口。AI Coding 生成的组件可一键发布到这里。</div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary" onClick={() => navigate('/coding')}>
              <I.code size={13} /> AI Coding
            </button>
            <button className="btn btn-primary">
              <I.upload size={13} /> 发布组件
            </button>
          </div>
        </div>

        <div className="mp-toolbar">
          <div className="apps-tabs">
            {categories.map(c => (
              <button key={c.key} className={`apps-tab ${cat === c.key ? 'active' : ''}`} onClick={() => setCat(c.key)}>
                {c.label}
                <span className="apps-tab-count">{c.count}</span>
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <div className="apps-search" style={{ width: 280 }}>
              <I.search size={13} />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索组件名称、标签..." />
            </div>
            <div className="mp-sort">
              <button className={sort === 'latest' ? 'active' : ''} onClick={() => setSort('latest')}>最新</button>
              <button className={sort === 'popular' ? 'active' : ''} onClick={() => setSort('popular')}>最多下载</button>
            </div>
          </div>
        </div>

        <div className="mp-grid">
          {items.map(m => (
            <article key={m.id} className="mp-card card card-interactive">
              <div className="mp-card-head">
                <div className={`mp-card-icon tone-${m.color}`}>
                  {m.category === 'form-component' ? <I.form size={18} /> : m.category === 'form-page' ? <I.layers size={18} /> : <I.code size={18} />}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="mp-card-name truncate">{m.name}</div>
                  <div className="mp-card-meta">
                    <span className="badge">{m.categoryLabel}</span>
                    <span className="mono mp-card-version">v{m.version}</span>
                  </div>
                </div>
              </div>
              <p className="mp-card-desc">{m.desc}</p>
              <div className="mp-card-tags">
                {m.tags.map(t => <span key={t} className="mp-tag">{t}</span>)}
              </div>
              <div className="mp-card-foot">
                <div className="mp-card-author">
                  <div className="mp-author-avatar">{m.author.slice(-1)}</div>
                  <span>{m.author}</span>
                </div>
                <div className="mp-card-downloads">
                  <I.download size={11} /> {m.downloads}
                </div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}

function Login() {
  const { navigate } = useContext(RouteCtx);
  return (
    <div className="login-page">
      <div className="login-bg" />
      <div className="login-card">
        <div className="login-brand">
          <div className="rail-logo" style={{ width: 40, height: 40 }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="3" width="8" height="8" rx="2" fill="white" />
              <rect x="13" y="3" width="8" height="8" rx="2" fill="rgba(255,255,255,0.6)" />
              <rect x="3" y="13" width="8" height="8" rx="2" fill="rgba(255,255,255,0.6)" />
              <rect x="13" y="13" width="8" height="8" rx="2" fill="white" />
            </svg>
          </div>
          <div className="login-title">睿鲸AI</div>
          <div className="login-subtitle">AI Builder + AI Coding 智能工作台</div>
        </div>

        <div className="login-form">
          <div className="login-tabs">
            <button className="active">账号密码登录</button>
            <button>SSO 登录</button>
          </div>

          <label className="login-label">用户名 / 手机号</label>
          <input className="input" defaultValue="marshub" placeholder="请输入用户名" />

          <label className="login-label" style={{ marginTop: 12 }}>密码</label>
          <input className="input" type="password" defaultValue="········" placeholder="请输入密码" />

          <div className="login-row">
            <label className="login-check"><input type="checkbox" defaultChecked /> 记住登录状态</label>
            <a className="login-link" href="#">忘记密码？</a>
          </div>

          <button className="btn btn-primary btn-lg" style={{ width: '100%', marginTop: 4 }} onClick={() => navigate('/')}>
            登录
          </button>

          <div className="login-divider"><span>或</span></div>

          <button className="btn btn-secondary btn-lg" style={{ width: '100%' }}>
            <I.bldg size={14} /> 通过得帆云平台账号登录
          </button>

          <div className="login-foot">
            还没有账号？<a href="#">立即注册</a>
          </div>
        </div>
      </div>

      <div className="login-features">
        <div className="login-feature">
          <I.sparkle size={16} />
          <div>
            <div className="login-feature-title">AI Builder</div>
            <div className="login-feature-desc">从一句话开始，到完整应用部署</div>
          </div>
        </div>
        <div className="login-feature">
          <I.code size={16} />
          <div>
            <div className="login-feature-title">AI Coding 工作区</div>
            <div className="login-feature-desc">流式生成 Vue / 表单 / 页面组件</div>
          </div>
        </div>
        <div className="login-feature">
          <I.store size={16} />
          <div>
            <div className="login-feature-title">平台管理统一配置</div>
            <div className="login-feature-desc">环境、模型、成员和 MCP 服务集中维护</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Admin() {
  const { mcpServers } = window.MOCK;
  const [tab, setTab] = useState('overview');

  const modules = [
    { key: 'status', label: '系统状态', icon: 'cloud', tone: 'emerald', desc: '后端、数据库、MCP 服务健康检查', count: '正常' },
    { key: 'mcp-services', label: 'MCP 服务', icon: 'mcp', tone: 'brand', desc: 'aPaaS 工具、Vibe 服务、接入地址和启停', count: `${mcpServers.length} 个` },
    { key: 'mcp-tester', label: 'MCP 测试', icon: 'zap', tone: 'sky', desc: '按服务调试工具调用，查看输入输出', count: '可用' },
    { key: 'envs', label: '平台环境', icon: 'cloud', tone: 'emerald', desc: '得帆云环境连接、默认环境和登录状态', count: '2 个' },
    { key: 'llm', label: 'LLM 配置', icon: 'model', tone: 'brand', desc: '供应商、模型、API Key、默认模型', count: '1 个' },
    { key: 'users', label: '用户与租户', icon: 'team', tone: 'amber', desc: '成员、角色、租户和启停状态', count: '24 人' },
  ];

  return (
    <div className="page">
      <div className="page-pad">
        <div className="page-head">
          <div>
            <h1 className="page-title">平台管理</h1>
            <div className="page-subtitle">复用当前管理后台：MCP 服务、平台环境、模型、成员和租户都在这里配置，Builder 前台只消费配置结果。</div>
          </div>
          <button className="btn btn-primary"><I.external size={13} /> 打开真实 /admin</button>
        </div>

        <div className="apps-tabs" style={{ marginBottom: 16, alignSelf: 'flex-start' }}>
          {[
            { k: 'overview', l: '总览', c: null },
            { k: 'mcp', l: 'MCP', c: mcpServers.length },
            { k: 'envs', l: '环境', c: 2 },
            { k: 'llm', l: '模型', c: 1 },
            { k: 'users', l: '成员', c: 24 },
          ].map(t => (
            <button key={t.k} className={`apps-tab ${tab === t.k ? 'active' : ''}`} onClick={() => setTab(t.k)}>
              {t.l}{t.c != null && <span className="apps-tab-count">{t.c}</span>}
            </button>
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 14, marginBottom: 18 }}>
          {modules.map(m => {
            const Ic = I[m.icon];
            return (
              <button key={m.key} className="card card-interactive" style={{ padding: 16, textAlign: 'left' }} onClick={() => setTab(m.key.startsWith('mcp') ? 'mcp' : m.key)}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div className={`app-stat-icon tone-${m.tone}`} style={{ width: 36, height: 36 }}><Ic size={15} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: 14 }}>{m.label}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>{m.desc}</div>
                  </div>
                  <span className="badge badge-outline">{m.count}</span>
                </div>
              </button>
            );
          })}
        </div>

        <div className="card" style={{ padding: 0, overflow: 'hidden', marginBottom: 18 }}>
          <div className="apps-row apps-row-head">
            <div style={{ flex: 2 }}>MCP 服务</div>
            <div style={{ width: 120 }}>状态</div>
            <div style={{ width: 120 }}>工具数</div>
            <div style={{ width: 180 }}>接入地址</div>
            <div style={{ width: 80 }} />
          </div>
          {mcpServers.map(s => (
            <div key={s.id} className="apps-row apps-row-item" style={{ cursor: 'default' }}>
              <div style={{ flex: 2, minWidth: 0 }}>
                <div className="apps-row-name">{s.name}</div>
                <div className="apps-row-sub">{s.desc}</div>
              </div>
              <div style={{ width: 120 }}>
                <span className={`badge ${s.status === 'connected' ? 'badge-emerald' : s.status === 'error' ? 'badge-rose' : 'badge-amber'}`}>
                  <span className="badge-dot" /> {s.status === 'connected' ? '已连接' : s.status === 'error' ? '异常' : '已停用'}
                </span>
              </div>
              <div style={{ width: 120, fontSize: 12.5, color: 'var(--text-2)' }}>{s.tools} 工具</div>
              <div style={{ width: 180, fontSize: 12.5, color: 'var(--text-3)' }} className="mono truncate">{s.endpoint}</div>
              <div style={{ width: 80, display: 'flex', justifyContent: 'flex-end', gap: 2 }}>
                <button className="icon-btn" title="测试" style={{ width: 26, height: 26 }}><I.play size={12} /></button>
                <button className="icon-btn" title="设置" style={{ width: 26, height: 26 }}><I.gear size={13} /></button>
              </div>
            </div>
          ))}
        </div>

        <div className="section-head">
          <div className="section-title">最近活动 <span className="section-title-count">实时</span></div>
        </div>
        <div className="card card-pad">
          {[
            { time: '14:23', who: 'Default Tenant · admin', what: 'MCP 服务「aPaaS Tools」测试通过', tone: 'emerald' },
            { time: '13:50', who: '平台管理 · admin', what: '设置内置通用模型 gpt-5.5 为默认模型', tone: 'brand' },
            { time: '11:02', who: 'Builder · AI', what: '应用「客户工单管理」生成到测试环境', tone: 'sky' },
            { time: '10:14', who: 'AI Coding · admin', what: '发布组件「工单 SLA 看板」到组件市场', tone: 'amber' },
          ].map((a, i) => (
            <div key={i} style={{ display: 'flex', gap: 12, padding: '10px 0', borderTop: i > 0 ? '1px solid var(--border)' : 'none' }}>
              <div className={`tone-${a.tone}`} style={{ width: 4, alignSelf: 'stretch', borderRadius: 2, background: 'currentColor' }} />
              <div className="mono" style={{ width: 50, fontSize: 12, color: 'var(--text-3)', flexShrink: 0 }}>{a.time}</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, color: 'var(--text)' }}>{a.what}</div>
                <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 2 }}>{a.who}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Templates() {
  const { templates } = window.MOCK;
  return (
    <div className="page">
      <div className="page-pad">
        <div className="page-head">
          <div>
            <h1 className="page-title">设计模板</h1>
            <div className="page-subtitle">沉淀的功能设计文档模板。上传应用时可基于模板生成。</div>
          </div>
          <button className="btn btn-primary"><I.upload size={13} /> 上传新模板</button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 12 }}>
          {templates.map(t => (
            <div key={t.code} className="card card-pad card-interactive">
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <div className="landing-path-icon-doc landing-path-icon" style={{ width: 38, height: 38 }}>
                  <I.doc size={18} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{t.name}</div>
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
      </div>
    </div>
  );
}

Object.assign(window, { Marketplace, Login, Admin, Templates, MCP });

/* ─── MCP Servers management ─── */
function MCP() {
  const { navigate } = useContext(RouteCtx);
  const { mcpServers } = window.MOCK;
  const [filter, setFilter] = useState('all');
  const [selected, setSelected] = useState(mcpServers[0]?.id);
  const [q, setQ] = useState('');

  const filters = [
    { k: 'all',       l: '全部',     c: mcpServers.length },
    { k: 'connected', l: '已连接',   c: mcpServers.filter(s => s.status === 'connected').length },
    { k: 'error',     l: '异常',     c: mcpServers.filter(s => s.status === 'error').length },
    { k: 'disabled',  l: '已停用',   c: mcpServers.filter(s => s.status === 'disabled').length },
    { k: 'official',  l: '官方',     c: mcpServers.filter(s => s.official).length },
    { k: 'custom',    l: '自定义',   c: mcpServers.filter(s => !s.official).length },
  ];

  let list = mcpServers;
  if (filter === 'official') list = list.filter(s => s.official);
  else if (filter === 'custom') list = list.filter(s => !s.official);
  else if (filter !== 'all') list = list.filter(s => s.status === filter);
  if (q) list = list.filter(s => (s.name + s.code + s.desc).toLowerCase().includes(q.toLowerCase()));

  const cur = mcpServers.find(s => s.id === selected) || list[0];

  return (
    <div className="page">
      <div className="page-pad" style={{ maxWidth: 1320 }}>
        <div className="page-head">
          <div>
            <h1 className="page-title">MCP 管理 <span className="badge badge-brand" style={{ marginLeft: 8 }}>{mcpServers.length} 个</span></h1>
            <div className="page-subtitle">
              Model Context Protocol 服务器接入。挂载后可在「AI Builder」「AI Coding」中被 AI 调用。
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary"><I.book size={13} /> 接入指南</button>
            <button className="btn btn-primary"><I.plus size={13} /> 添加 MCP 服务器</button>
          </div>
        </div>

        {/* Summary cards */}
        <div className="mcp-summary">
          <div className="mcp-summary-card">
            <div className="mcp-summary-icon mcp-tone-ok"><I.check size={16} /></div>
            <div>
              <div className="mcp-summary-v">{mcpServers.filter(s => s.status === 'connected').length}</div>
              <div className="mcp-summary-l">已连接</div>
            </div>
          </div>
          <div className="mcp-summary-card">
            <div className="mcp-summary-icon mcp-tone-warn"><I.bell size={16} /></div>
            <div>
              <div className="mcp-summary-v">{mcpServers.filter(s => s.status === 'error').length}</div>
              <div className="mcp-summary-l">异常 · 需处理</div>
            </div>
          </div>
          <div className="mcp-summary-card">
            <div className="mcp-summary-icon mcp-tone-brand"><I.zap size={16} /></div>
            <div>
              <div className="mcp-summary-v">{mcpServers.reduce((s, m) => s + m.tools, 0)}</div>
              <div className="mcp-summary-l">可用工具</div>
            </div>
          </div>
          <div className="mcp-summary-card">
            <div className="mcp-summary-icon mcp-tone-info"><I.layers size={16} /></div>
            <div>
              <div className="mcp-summary-v">{mcpServers.reduce((s, m) => s + m.usage, 0).toLocaleString()}</div>
              <div className="mcp-summary-l">本月调用</div>
            </div>
          </div>
        </div>

        {/* Filter + search */}
        <div className="apps-bar" style={{ marginTop: 20 }}>
          <div className="apps-tabs">
            {filters.map(f => (
              <button key={f.k} className={`apps-tab ${filter === f.k ? 'active' : ''}`} onClick={() => setFilter(f.k)}>
                {f.l}<span className="apps-tab-count">{f.c}</span>
              </button>
            ))}
          </div>
          <div className="apps-search">
            <I.search size={13} />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索名称、代号、描述…" />
          </div>
        </div>

        {/* Two-column: list + detail */}
        <div className="mcp-layout">
          <div className="mcp-list card" style={{ padding: 0, overflow: 'hidden' }}>
            {list.map(m => (
              <button
                key={m.id}
                className={`mcp-list-item ${selected === m.id ? 'active' : ''}`}
                onClick={() => setSelected(m.id)}
              >
                <div className="mcp-list-item-head">
                  <div className={`mcp-list-status mcp-status-${m.status}`}>
                    {m.status === 'connected' && <span className="mcp-list-pulse" />}
                  </div>
                  <div className="mcp-list-name">{m.name}</div>
                  {m.official && <span className="badge badge-brand" style={{ marginLeft: 'auto' }}>官方</span>}
                </div>
                <div className="mcp-list-meta">
                  <span className="mono">{m.code}</span>
                  <span>·</span>
                  <span>{m.tools} 工具</span>
                  <span>·</span>
                  <span>v{m.version}</span>
                </div>
                {m.status === 'error' && (
                  <div className="mcp-list-error"><I.bell size={11} /> {m.error}</div>
                )}
                <div className="mcp-list-foot">
                  <span className="badge badge-outline mono" style={{ textTransform: 'uppercase', fontSize: 10 }}>{m.transport}</span>
                  <span className="mcp-list-time">最近 {m.lastUsed}</span>
                </div>
              </button>
            ))}
          </div>

          {cur && (
            <div className="mcp-detail card">
              <div className="mcp-detail-head">
                <div className={`mcp-detail-status mcp-status-${cur.status}`}>
                  {cur.status === 'connected' && <span className="mcp-list-pulse" />}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="mcp-detail-title">
                    {cur.name}
                    {cur.official && <span className="badge badge-brand" style={{ marginLeft: 8 }}>官方</span>}
                    <span className={`badge ${cur.status === 'connected' ? 'badge-emerald' : cur.status === 'error' ? 'badge-rose' : 'badge-amber'}`} style={{ marginLeft: 6 }}>
                      <span className="badge-dot" />
                      {cur.status === 'connected' ? '已连接' : cur.status === 'error' ? '异常' : '已停用'}
                    </span>
                  </div>
                  <div className="mcp-detail-sub">
                    <span className="mono">{cur.code}</span>
                    <span>·</span>
                    <span>v{cur.version}</span>
                    <span>·</span>
                    <span>本月调用 {cur.usage}</span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="btn btn-secondary btn-sm"><I.refresh size={12} /> 重连</button>
                  <button className="btn btn-secondary btn-sm"><I.book size={12} /> 调用日志</button>
                  <button className="icon-btn" style={{ width: 28, height: 28 }}><I.more size={14} /></button>
                </div>
              </div>

              <div className="mcp-detail-desc">{cur.desc}</div>

              {cur.status === 'error' && (
                <div className="mcp-detail-alert">
                  <I.bell size={14} />
                  <div>
                    <div style={{ fontWeight: 600 }}>{cur.error}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 2 }}>建议：检查本地 bridge 进程，或切换至备用 endpoint。</div>
                  </div>
                </div>
              )}

              <div className="mcp-detail-grid">
                <div>
                  <div className="mcp-detail-label">连接方式</div>
                  <div className="mcp-detail-val mono" style={{ textTransform: 'uppercase' }}>{cur.transport}</div>
                </div>
                <div>
                  <div className="mcp-detail-label">Endpoint</div>
                  <div className="mcp-detail-val mono truncate">{cur.endpoint}</div>
                </div>
                <div>
                  <div className="mcp-detail-label">工具数</div>
                  <div className="mcp-detail-val">{cur.tools}</div>
                </div>
                <div>
                  <div className="mcp-detail-label">最近调用</div>
                  <div className="mcp-detail-val">{cur.lastUsed}</div>
                </div>
              </div>

              {/* Tool list */}
              <div className="mcp-detail-section">
                <div className="mcp-detail-section-head">
                  <span className="mcp-detail-section-title">暴露的工具 <span style={{ color: 'var(--text-3)', fontWeight: 500 }}>{cur.tools}</span></span>
                  <button className="section-action">查看全部 →</button>
                </div>
                <div className="mcp-tools-grid">
                  {[
                    { name: 'create_model', desc: '创建数据模型', params: 3 },
                    { name: 'create_form_config', desc: '生成表单配置', params: 5 },
                    { name: 'save_form_config', desc: '保存表单配置', params: 2 },
                    { name: 'create_role', desc: '创建角色', params: 4 },
                    { name: 'list_models', desc: '列出当前应用模型', params: 1 },
                    { name: 'add_subtable_field', desc: '增加子表字段', params: 3 },
                  ].slice(0, cur.tools >= 6 ? 6 : cur.tools).map(t => (
                    <div key={t.name} className="mcp-tool">
                      <div className="mcp-tool-head">
                        <code className="mono mcp-tool-name">{t.name}</code>
                        <span className="mcp-tool-params">{t.params} 参数</span>
                      </div>
                      <div className="mcp-tool-desc">{t.desc}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Scope */}
              <div className="mcp-detail-section">
                <div className="mcp-detail-section-head">
                  <span className="mcp-detail-section-title">允许的调用方</span>
                </div>
                <div className="mcp-scope-row">
                  <span className="mcp-scope-chip mcp-scope-on"><I.check size={11} /> AI Builder</span>
                  <span className="mcp-scope-chip mcp-scope-on"><I.check size={11} /> AI Coding</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Tip strip */}
        <div className="mcp-tip">
          <I.book size={14} />
          <div>
            <b>什么是 MCP？</b>&nbsp;Model Context Protocol，让大模型按统一协议调用本地 / 远端工具与数据。
            得帆云 aPaaS Tools 是默认挂载的官方 MCP，提供应用配置全套能力。
            自定义 MCP 可以挂入你自己的飞书、ERP、私有知识库等。
          </div>
          <button className="btn btn-secondary btn-sm"><I.external size={12} /> 阅读文档</button>
        </div>

      </div>
    </div>
  );
}
