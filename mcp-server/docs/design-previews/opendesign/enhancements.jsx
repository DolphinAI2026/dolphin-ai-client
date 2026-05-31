// Cross-cutting enhancements addressing the P0/P1 feedback:
//   A. Role-aware UI (业务顾问 / 平台管理员)
//   B. Deploy confirmation modal — fires before pushing to aPaaS
//   D. First-time onboarding tour (3 steps + relationship diagram)
//   E. Tooltip primitive for unfamiliar terms (Ontology / SPEC / MCP / UMD ...)

const RoleCtx = createContext(null);

const ROLE_NAV_FILTERS = {
  // 业务顾问 — implementation / business analyst, no code
  consultant: {
    show: ['home', 'apps', 'chat', 'specs', 'industry', 'marketplace'],
    label: '业务顾问',
    short: '业务',
    tone: 'ai',
    hint: '实施顾问 / 业务用户。只用对话搭建，不写代码。',
    recommend: '睿鲸 AI Builder',
  },
  // 开发人员 — frontend/full-stack engineer, focus on component & code
  developer: {
    show: ['home', 'apps', 'chat', 'coding', 'vibe', 'marketplace', 'mcp'],
    label: '开发人员',
    short: '开发',
    tone: 'emerald',
    hint: '前端 / 全栈工程师。开发自研组件，写代码，挂 MCP。',
    recommend: '睿鲸 AI Coding · Vibe Coding',
  },
  // 双栖 (hybrid) — knows business AND tech; sees almost everything
  hybrid: {
    show: ['home', 'apps', 'chat', 'specs', 'industry', 'coding', 'vibe', 'marketplace', 'mcp'],
    label: '双栖（业务+开发）',
    short: '双栖',
    tone: 'brand',
    hint: '既懂业务又懂技术。能从对话搭建到组件开发全链路自己跑通。',
    recommend: '全链路',
  },
  // 平台管理员 — sees everything including ops
  admin: {
    show: ['home', 'apps', 'chat', 'specs', 'industry', 'marketplace', 'coding', 'vibe', 'mcp', 'runtime', 'admin'],
    label: '平台管理员',
    short: '管理',
    tone: 'rose',
    hint: '运维 / IT 负责人。包含沙箱、流水线、租户、模型配置。',
    recommend: '运行与发布 + 平台管理',
  },
};

/* ─── Tooltip — minimal, hover & focus, escapes the iframe constraints ─── */
function Tooltip({ children, content }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="tip-wrap"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}>
      {children}
      {open && <span className="tip-body">{content}</span>}
    </span>
  );
}

/* ─── Glossary chip — wraps a term with a "?" affordance ─── */
function Term({ children, def }) {
  return (
    <Tooltip content={def}>
      <span className="term">
        {children}
        <span className="term-mark">?</span>
      </span>
    </Tooltip>
  );
}

/* ─── Deploy confirmation modal ─── */
function DeployModal({ open, onClose }) {
  const [env, setEnv] = useState('test');
  const [stage, setStage] = useState('review'); // review | running | done
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (!open) { setStage('review'); setProgress(0); setEnv('test'); }
  }, [open]);

  const startDeploy = () => {
    setStage('running');
    setProgress(0);
    const t = setInterval(() => {
      setProgress(p => {
        if (p >= 100) { clearInterval(t); setStage('done'); return 100; }
        return p + 7;
      });
    }, 220);
  };

  if (!open) return null;

  const diff = {
    add:    [{ kind: '模型',   name: '资产主档 · 字段',  detail: '+ warranty_until · + purchase_source' },
             { kind: '流程',   name: '资产报废审批',     detail: '+ 5 节点（申请 → 部门 → 资产管理员 → 财务 → 归档）' }],
    modify: [{ kind: '字典',   name: '资产状态',         detail: '~ 新增 "已报废" 项' }],
    remove: [],
  };
  const totalChanges = diff.add.length + diff.modify.length + diff.remove.length;

  return (
    <div className="deploy-overlay" onClick={onClose}>
      <div className="deploy-modal" onClick={e => e.stopPropagation()}>
        {stage === 'review' && (
          <>
            <div className="deploy-head">
              <div className="deploy-head-icon"><I.rocket size={18} /></div>
              <div style={{ flex: 1 }}>
                <div className="deploy-head-title">部署 SPEC v3 到平台</div>
                <div className="deploy-head-sub">资产管理系统 · 由 marshub 发起</div>
              </div>
              <button className="icon-btn" onClick={onClose}><I.plus size={14} style={{ transform: 'rotate(45deg)' }} /></button>
            </div>

            <div className="deploy-body">
              {/* 1. Env picker */}
              <div className="deploy-section">
                <div className="deploy-section-title"><b>1. 选择目标环境</b></div>
                <div className="deploy-env-row">
                  {[
                    { k: 'dev',  l: '开发环境',  ip: 'apaas-dev', warn: false, desc: '随便部署，影响最小' },
                    { k: 'test', l: '测试环境',  ip: 'apaas-test', warn: false, desc: '默认环境，建议先到这' },
                    { k: 'prod', l: '生产环境',  ip: 'apaas-poc',  warn: true,  desc: '真实业务，谨慎' },
                  ].map(e => (
                    <button key={e.k} className={`deploy-env deploy-env-${e.k} ${env === e.k ? 'active' : ''}`} onClick={() => setEnv(e.k)}>
                      <div className="deploy-env-head">
                        <div className={`deploy-env-stripe deploy-env-stripe-${e.k}`} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div className="deploy-env-name">{e.l}</div>
                          <div className="deploy-env-host mono">{e.ip}.definesys.cn</div>
                        </div>
                        {env === e.k && <I.check size={14} style={{ color: 'var(--brand)' }} />}
                      </div>
                      <div className="deploy-env-desc">{e.desc}</div>
                    </button>
                  ))}
                </div>
                {env === 'prod' && (
                  <div className="deploy-warn">
                    <I.bell size={13} />
                    <div>
                      <b>这是生产环境。</b>建议先在测试环境验证 SPEC v3，再晋级到生产。
                      仍要继续？请输入应用 code <code className="mono">asset_mgr</code> 以确认。
                      <input className="input deploy-warn-input" placeholder="输入 asset_mgr 以确认" />
                    </div>
                  </div>
                )}
              </div>

              {/* 2. Diff preview */}
              <div className="deploy-section">
                <div className="deploy-section-title">
                  <b>2. 本次变更预览</b>
                  <span className="deploy-section-meta">SPEC v2 → v3 · {totalChanges} 处变更</span>
                </div>
                <div className="deploy-diff">
                  {diff.add.map((d, i) => (
                    <div key={'a'+i} className="deploy-diff-row deploy-diff-add">
                      <span className="deploy-diff-mark">+</span>
                      <span className="deploy-diff-kind">{d.kind}</span>
                      <div style={{ flex: 1 }}>
                        <div className="deploy-diff-name">{d.name}</div>
                        <div className="deploy-diff-detail">{d.detail}</div>
                      </div>
                    </div>
                  ))}
                  {diff.modify.map((d, i) => (
                    <div key={'m'+i} className="deploy-diff-row deploy-diff-mod">
                      <span className="deploy-diff-mark">~</span>
                      <span className="deploy-diff-kind">{d.kind}</span>
                      <div style={{ flex: 1 }}>
                        <div className="deploy-diff-name">{d.name}</div>
                        <div className="deploy-diff-detail">{d.detail}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* 3. Impact */}
              <div className="deploy-section">
                <div className="deploy-section-title"><b>3. 影响范围</b></div>
                <div className="deploy-impact-grid">
                  <div className="deploy-impact-card">
                    <I.user size={14} />
                    <div><b>0</b> 用户受影响</div>
                    <span>新增功能，不影响现有用户</span>
                  </div>
                  <div className="deploy-impact-card">
                    <I.flow size={14} />
                    <div><b>1</b> 流程新增</div>
                    <span>资产报废审批</span>
                  </div>
                  <div className="deploy-impact-card">
                    <I.form size={14} />
                    <div><b>0</b> 数据迁移</div>
                    <span>无破坏性字段变更</span>
                  </div>
                  <div className="deploy-impact-card">
                    <I.refresh size={14} />
                    <div><b>2 分钟</b> 预计耗时</div>
                    <span>不需要停机</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="deploy-foot">
              <div className="deploy-foot-l">
                <I.shield size={12} />
                <span>部署前自动备份 · 失败可一键回滚</span>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-secondary" onClick={onClose}>取消</button>
                <button className={`btn ${env === 'prod' ? 'btn-primary deploy-btn-prod' : 'btn-primary'}`} onClick={startDeploy}>
                  <I.rocket size={13} /> 确认部署到{env === 'dev' ? '开发' : env === 'test' ? '测试' : '生产'}
                </button>
              </div>
            </div>
          </>
        )}

        {stage === 'running' && (
          <div className="deploy-running">
            <div className="deploy-running-spinner"><span className="coding-tab-spinner" style={{ width: 36, height: 36, borderWidth: 3 }} /></div>
            <div className="deploy-running-title">正在部署到{env === 'dev' ? '开发' : env === 'test' ? '测试' : '生产'}环境…</div>
            <div className="deploy-running-bar">
              <div className="deploy-running-fill" style={{ width: progress + '%' }} />
            </div>
            <div className="deploy-running-step">
              {progress < 25 && '解析配置 diff · 校验字段类型…'}
              {progress >= 25 && progress < 60 && '调用 aPaaS API 创建模型与表单…'}
              {progress >= 60 && progress < 90 && '配置流程节点与权限…'}
              {progress >= 90 && '回归校验 · 即将完成…'}
            </div>
            <button className="btn btn-secondary btn-sm" style={{ marginTop: 24 }}>查看实时日志</button>
          </div>
        )}

        {stage === 'done' && (
          <div className="deploy-done">
            <div className="deploy-done-icon"><I.check size={28} /></div>
            <div className="deploy-done-title">部署成功</div>
            <div className="deploy-done-sub">资产管理系统 · SPEC v3 · 已上线到{env === 'dev' ? '开发' : env === 'test' ? '测试' : '生产'}环境</div>
            <div className="deploy-done-meta">
              <span className="badge badge-emerald"><I.check size={10} /> 2 分 18 秒</span>
              <span className="badge">3 处变更已生效</span>
              <span className="badge">已自动备份 v2</span>
            </div>
            <div className="deploy-done-actions">
              <button className="btn btn-secondary"><I.external size={13} /> 在 aPaaS 打开</button>
              {env === 'test' && <button className="btn btn-primary"><I.arrowRight size={13} /> 晋级到生产</button>}
              <button className="btn btn-secondary" onClick={onClose}>关闭</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Onboarding overlay (3 steps + relationship diagram) ─── */
function Onboarding({ open, onClose }) {
  const [step, setStep] = useState(0);
  useEffect(() => { if (open) setStep(0); }, [open]);

  if (!open) return null;

  const steps = [
    {
      title: '欢迎使用 aPaaS Builder AI',
      sub: '从一句话开始，10 分钟搭出一个完整应用。',
      body: <OnboardingFlow active={0} />,
    },
    {
      title: '关键概念',
      sub: '只需要记住这四个词，其它都可以忽略。',
      body: <OnboardingTerms />,
    },
    {
      title: '准备好了，从哪开始？',
      sub: '业务顾问 / 平台管理员的推荐路径不同。',
      body: <OnboardingRoles />,
    },
  ];

  const s = steps[step];

  return (
    <div className="onb-overlay">
      <div className="onb-modal">
        <div className="onb-head">
          <div className="onb-progress">
            {steps.map((_, i) => (
              <span key={i} className={`onb-dot ${i === step ? 'active' : ''} ${i < step ? 'done' : ''}`} />
            ))}
          </div>
          <button className="onb-skip" onClick={onClose}>跳过</button>
        </div>
        <div className="onb-body">
          <div className="onb-title">{s.title}</div>
          <div className="onb-sub">{s.sub}</div>
          <div className="onb-content">{s.body}</div>
        </div>
        <div className="onb-foot">
          {step > 0 ? <button className="btn btn-secondary btn-sm" onClick={() => setStep(step - 1)}><I.chevronL size={12} /> 上一步</button> : <span />}
          {step < steps.length - 1
            ? <button className="btn btn-primary btn-sm" onClick={() => setStep(step + 1)}>下一步 <I.chevronR size={12} /></button>
            : <button className="btn btn-primary btn-sm" onClick={onClose}>开始使用 <I.arrowRight size={12} /></button>}
        </div>
      </div>
    </div>
  );
}

function OnboardingFlow({ active }) {
  const steps = [
    { icon: 'chat',     name: '描述需求',   sub: '和睿鲸 AI Builder 对话', tone: 'ai' },
    { icon: 'doc',      name: '生成 SPEC',  sub: '设计文档自动累积版本',  tone: 'brand' },
    { icon: 'industry', name: '复用行业沉淀', sub: '可选 · 一键采用最佳实践',  tone: 'amber' },
    { icon: 'rocket',   name: '部署上线',   sub: '到 dev / test / prod', tone: 'emerald' },
  ];
  return (
    <div className="onb-flow">
      {steps.map((s, i) => {
        const Ic = I[s.icon];
        return (
          <React.Fragment key={i}>
            <div className={`onb-flow-step onb-flow-${s.tone} ${i === active ? 'is-active' : ''}`}>
              <div className="onb-flow-icon"><Ic size={20} /></div>
              <div className="onb-flow-num">{String(i + 1).padStart(2, '0')}</div>
              <div className="onb-flow-name">{s.name}</div>
              <div className="onb-flow-sub">{s.sub}</div>
            </div>
            {i < steps.length - 1 && <div className="onb-flow-arrow"><I.arrowRight size={16} /></div>}
          </React.Fragment>
        );
      })}
    </div>
  );
}

function OnboardingTerms() {
  const terms = [
    { name: '应用',     def: '部署在得帆云 aPaaS 平台上的一个完整业务系统（如：资产管理系统）。', count: '6 个' },
    { name: 'SPEC',     def: '设计文档。AI 对话产出，描述应用包含的数据模型、表单、流程、权限。每次部署都基于某个 SPEC 版本。', count: '4 份 / 11 版本' },
    { name: '行业知识库', def: '类 Palantir 的行业模型沉淀。包含业务对象、关系、流程、字典，新建应用可一键复用。', count: '4 个行业包' },
    { name: '组件市场', def: '团队沉淀的可复用组件、页面、后端接口。AI Coding 生成的组件可一键发布到这里。', count: '6 个组件' },
  ];
  return (
    <div className="onb-terms">
      {terms.map(t => (
        <div key={t.name} className="onb-term">
          <div className="onb-term-name">{t.name}</div>
          <div className="onb-term-def">{t.def}</div>
          <div className="onb-term-count">{t.count}</div>
        </div>
      ))}
    </div>
  );
}

function OnboardingRoles() {
  const { role, setRole } = useContext(RoleCtx) || { role: 'consultant', setRole: () => {} };
  const cards = [
    {
      key: 'consultant',
      who: '只懂业务',
      example: '实施顾问 / 业务用户 / 产品经理',
      from: '描述需求 → SPEC → 部署',
      tools: ['睿鲸 AI Builder', '设计文档', '行业知识库'],
    },
    {
      key: 'developer',
      who: '只动技术',
      example: '前端 / 全栈工程师',
      from: '组件需求 → AI 生成 / 手写 → 发布',
      tools: ['睿鲸 AI Coding', 'Vibe Coding', '组件市场', 'MCP'],
    },
    {
      key: 'hybrid',
      who: '双栖 · 业务 + 开发',
      example: '产品技术负责人 / 资深实施',
      from: '业务搭建 ↔ 自研组件 全链路',
      tools: ['以上全部（除运维）'],
      highlight: true,
    },
    {
      key: 'admin',
      who: '平台管理',
      example: '运维 / IT 负责人',
      from: '行业沉淀 + 沙箱 + 流水线 + 租户',
      tools: ['运行与发布', '平台管理', '+ 全部'],
    },
  ];
  return (
    <div className="onb-roles-v2">
      <div className="onb-roles-hint">
        <I.sparkle size={13} />
        <span>视图随时可切，先选个起点。<b>"双栖"是我们最推荐的</b>——既能聊需求也能动代码，能力上限最高。</span>
      </div>
      <div className="onb-roles-grid">
        {cards.map(c => {
          const r = ROLE_NAV_FILTERS[c.key];
          return (
            <button key={c.key}
              className={`onb-role-v2 ${role === c.key ? 'active' : ''} ${c.highlight ? 'highlight' : ''} role-tone-${r.tone}`}
              onClick={() => setRole(c.key)}>
              <div className="onb-role-v2-head">
                <span className={`role-picker-dot role-tone-${r.tone}`} />
                <span className="onb-role-v2-tag">{r.label}</span>
                {c.highlight && <span className="onb-role-v2-best">推荐</span>}
                {role === c.key && <I.check size={13} style={{ color: 'var(--brand)', marginLeft: 'auto' }} />}
              </div>
              <div className="onb-role-v2-who">{c.who}</div>
              <div className="onb-role-v2-eg">{c.example}</div>
              <div className="onb-role-v2-from"><b>路径</b> {c.from}</div>
              <div className="onb-role-v2-tools">
                {c.tools.map(t => <span key={t} className="onb-role-v2-tool">{t}</span>)}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ─── Role picker popover — replaces the simple toggle ─── */
function RolePicker({ collapsed }) {
  const { role, setRole } = useContext(RoleCtx) || { role: 'consultant', setRole: () => {} };
  const [open, setOpen] = useState(false);
  const cur = ROLE_NAV_FILTERS[role] || ROLE_NAV_FILTERS.consultant;

  return (
    <div className="role-picker-wrap">
      <button className="rail-user" onClick={() => setOpen(o => !o)} title={cur.hint}>
        <div className="rail-avatar">M</div>
        <div className="rail-user-info">
          <div className="rail-user-name">marshub</div>
          <div className="rail-user-tenant">
            <span className={`role-switch-pill role-tone-${cur.tone}`}>{cur.label}</span>
          </div>
        </div>
        <I.chevronD size={13} style={{ color: 'var(--text-3)', transform: open ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 0.15s' }} />
      </button>

      {open && (
        <>
          <div className="role-picker-backdrop" onClick={() => setOpen(false)} />
          <div className="role-picker-popover">
            <div className="role-picker-head">
              <span>选择视图</span>
              <Tooltip content="切换视图只影响左侧导航与首页推荐路径，不影响数据权限。">
                <span className="term-mark" style={{ width: 14, height: 14 }}>?</span>
              </Tooltip>
            </div>
            {Object.entries(ROLE_NAV_FILTERS).map(([key, r]) => (
              <button
                key={key}
                className={`role-picker-item ${role === key ? 'active' : ''}`}
                onClick={() => { setRole(key); setOpen(false); }}
              >
                <div className={`role-picker-dot role-tone-${r.tone}`} />
                <div className="role-picker-body">
                  <div className="role-picker-name">
                    {r.label}
                    {role === key && <I.check size={12} style={{ color: 'var(--brand)', marginLeft: 4 }} />}
                  </div>
                  <div className="role-picker-hint">{r.hint}</div>
                  <div className="role-picker-recommend">
                    <span>推荐入口：</span><b>{r.recommend}</b>
                    <span style={{ marginLeft: 'auto', color: 'var(--text-3)' }}>{r.show.length} 个导航</span>
                  </div>
                </div>
              </button>
            ))}
            <div className="role-picker-foot">
              所有视图都可访问相同数据，只是<b>看到的菜单不同</b>。需要时随时切。
            </div>
          </div>
        </>
      )}
    </div>
  );
}

Object.assign(window, { RoleCtx, ROLE_NAV_FILTERS, Tooltip, Term, DeployModal, Onboarding, RolePicker });
