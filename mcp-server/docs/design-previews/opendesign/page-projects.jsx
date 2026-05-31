// 项目 (Projects) — first-class container for a customer engagement.
// Replaces the implicit "everything belongs to the tenant" model.
// Houses: applications, members (with per-project roles), bound industry pack,
// target environments, milestones, recent activity.

function Projects() {
  const { navigate } = useContext(RouteCtx);
  const { projects } = window.MOCK;
  return (
    <div className="page">
      <div className="page-pad" style={{ maxWidth: 1320 }}>
        <div className="page-head">
          <div>
            <h1 className="page-title">项目</h1>
            <div className="page-subtitle">
              每个客户的实施 / 数字化交付 = 一个项目。项目包含应用、成员、绑定的行业包、目标环境与里程碑。
              <b style={{ color: 'var(--text)' }}>"我做的所有事" 都归属于某个项目。</b>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary"><I.download size={13} /> 从平台导入</button>
            <button className="btn btn-primary"><I.plus size={13} /> 新建项目</button>
          </div>
        </div>

        <div className="proj-grid">
          {projects.map(p => (
            <button key={p.id} className="proj-card card card-interactive" onClick={() => navigate('/projects/' + p.id)}>
              <div className="proj-card-head">
                <div className={`proj-stripe proj-stripe-${p.stageTone}`} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="proj-card-name">{p.name}</div>
                  <div className="proj-card-customer">{p.customer}</div>
                </div>
                <span className={`badge ${p.stageTone === 'gray' ? '' : 'badge-' + p.stageTone}`}>
                  <span className="badge-dot" /> {p.stage}
                </span>
              </div>

              <div className="proj-card-progress">
                <div className="proj-card-progress-bar"><div className="proj-card-progress-fill" style={{ width: p.progress + '%' }} /></div>
                <span className="proj-card-progress-label">{p.progress}%</span>
              </div>

              <p className="proj-card-summary">{p.summary}</p>

              <div className="proj-card-stats">
                <div><b>{p.appCount}</b> 应用</div>
                <div><b>{p.deployedCount}</b> 已部署</div>
                <div><b>{p.memberCount}</b> 成员</div>
                <div><b>{p.envs.length}</b> 环境</div>
              </div>

              <div className="proj-card-foot">
                <div className="proj-card-members">
                  {p.members.slice(0, 5).map((m, i) => (
                    <span key={i} className={`proj-avatar proj-avatar-${m.tone}`} style={{ zIndex: 10 - i }} title={`${m.name} · ${m.role}`}>{m.avatar}</span>
                  ))}
                  {p.members.length > 5 && <span className="proj-avatar proj-avatar-more">+{p.members.length - 5}</span>}
                </div>
                <div className="proj-card-pack">
                  <I.industry size={11} /> {p.industryName} {p.industryVersion}
                </div>
                <div className="proj-card-time">{p.updatedAt}</div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function ProjectDetail() {
  const { route, navigate } = useContext(RouteCtx);
  const { projects, apps } = window.MOCK;
  const id = parseInt(route.split('/').pop());
  const p = projects.find(x => x.id === id) || projects[0];
  const projectApps = apps.filter(a => p.apps.includes(a.id));
  const [tab, setTab] = useState('overview');

  return (
    <div className="page">
      <div className="page-pad" style={{ maxWidth: 1320 }}>
        {/* Header */}
        <div className="proj-detail-head">
          <button className="btn btn-ghost btn-sm" onClick={() => navigate('/projects')}>
            <I.chevronL size={13} /> 全部项目
          </button>
          <div className="proj-detail-titlerow">
            <div className={`proj-stripe proj-stripe-${p.stageTone}`} style={{ height: 36 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <h1 className="proj-detail-title">{p.name}</h1>
              <div className="proj-detail-sub">
                <span>{p.customer}</span>
                <span>·</span>
                <span className="mono">{p.code}</span>
                <span>·</span>
                <span>负责人 <b style={{ color: 'var(--text-2)' }}>{p.lead}</b></span>
                <span>·</span>
                <span>更新 {p.updatedAt}</span>
              </div>
            </div>
            <span className={`badge ${p.stageTone === 'gray' ? '' : 'badge-' + p.stageTone}`}><span className="badge-dot" /> {p.stage}</span>
            <button className="btn btn-secondary btn-sm"><I.gear size={12} /> 项目设置</button>
            <button className="btn btn-primary btn-sm" onClick={() => navigate('/chat')}>
              <I.plus size={12} /> 新建应用
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="apps-tabs" style={{ marginTop: 18 }}>
          {[
            { k: 'overview', l: '概览',  ic: 'home' },
            { k: 'apps',     l: '应用',  ic: 'apps', c: p.appCount },
            { k: 'members',  l: '成员与角色', ic: 'role',  c: p.memberCount },
            { k: 'industry', l: '行业包绑定', ic: 'industry' },
            { k: 'envs',     l: '环境与部署', ic: 'cloud',  c: p.envs.length },
          ].map(t => {
            const Ic = I[t.ic];
            return (
              <button key={t.k} className={`apps-tab ${tab === t.k ? 'active' : ''}`} onClick={() => setTab(t.k)}>
                <Ic size={13} /> {t.l}{t.c && <span className="apps-tab-count">{t.c}</span>}
              </button>
            );
          })}
        </div>

        {/* Overview */}
        {tab === 'overview' && (
          <div className="proj-overview">
            <div className="proj-overview-l">
              <div className="card card-pad">
                <div className="section-title" style={{ marginBottom: 12 }}>项目里程碑</div>
                <div className="proj-milestones">
                  {p.milestones.map((m, i) => (
                    <div key={i} className={`proj-milestone ${m.done ? 'done' : ''}`}>
                      <div className="proj-milestone-dot">{m.done && <I.check size={10} />}</div>
                      <div className="proj-milestone-time mono">{m.time}</div>
                      <div className="proj-milestone-text">{m.text}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card card-pad">
                <div className="section-title" style={{ marginBottom: 12 }}>最近活动</div>
                {[
                  { who: 'marshub', what: '部署「资产管理系统」SPEC v3 到测试',  time: '14:24' },
                  { who: '李宁',    what: '新增对话「客户工单中心 — SLA 字段调整」', time: '09:08' },
                  { who: '周航',    what: '在睿鲸 AI Coding 生成「差旅报销表单」', time: '昨天' },
                  { who: 'marshub', what: '采用制造装备行业包 v2.1',               time: '5/14' },
                ].map((a, i) => (
                  <div key={i} className="proj-activity-row">
                    <span className={`proj-avatar proj-avatar-brand`} style={{ width: 22, height: 22, fontSize: 10 }}>{a.who.slice(0,1)}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12.5, color: 'var(--text)' }}>
                        <b style={{ color: 'var(--text-2)' }}>{a.who}</b> {a.what}
                      </div>
                    </div>
                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{a.time}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="proj-overview-r">
              <div className="card card-pad proj-bind-card">
                <div className="proj-bind-label">绑定的行业包</div>
                <div className="proj-bind-pack">
                  <div className="industry-pack-icon tone-amber" style={{ width: 32, height: 32, borderRadius: 8 }}><I.industry size={14} /></div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13.5, fontWeight: 600 }}>{p.industryName}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-3)' }} className="mono">{p.industryVersion} · 已应用于 AI Builder</div>
                  </div>
                </div>
                <button className="btn btn-secondary btn-sm" style={{ width: '100%' }} onClick={() => navigate('/industry')}>
                  查看 / 更换
                </button>
              </div>

              <div className="card card-pad proj-bind-card">
                <div className="proj-bind-label">默认部署环境</div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {p.envs.map(e => (
                    <span key={e} className={`rt-env-chip rt-env-chip-${e}`} style={{ fontSize: 12, padding: '4px 10px' }}>
                      {e === 'dev' ? '开发' : e === 'test' ? '测试' : '生产'}
                      {p.defaultEnv === e && <span style={{ marginLeft: 4 }}>·默认</span>}
                    </span>
                  ))}
                </div>
              </div>

              <div className="card card-pad proj-bind-card">
                <div className="proj-bind-label">团队 ({p.memberCount})</div>
                <div className="proj-members-list">
                  {p.members.slice(0, 4).map((m, i) => (
                    <div key={i} className="proj-member-row">
                      <span className={`proj-avatar proj-avatar-${m.tone}`}>{m.avatar}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 500 }}>{m.name}</div>
                        <div style={{ fontSize: 10.5, color: 'var(--text-3)' }}>{m.role}</div>
                      </div>
                    </div>
                  ))}
                  {p.members.length > 4 && (
                    <button className="section-action" onClick={() => setTab('members')}>查看全部 →</button>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Apps */}
        {tab === 'apps' && (
          <div style={{ marginTop: 16 }}>
            <div className="landing-apps" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
              {projectApps.map(a => (
                <button key={a.id} className="landing-app-card card card-interactive" onClick={() => navigate('/chat?app=' + a.id)}>
                  <div className="landing-app-card-head">
                    <div className={`landing-app-icon tone-${a.color}`}>{a.name.slice(0, 1)}</div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="landing-app-name truncate">{a.name}</div>
                      <div className="landing-app-meta">
                        <span className="mono">{a.code}</span>
                      </div>
                    </div>
                    <StatusBadge status={a.status} />
                  </div>
                  <div className="landing-app-desc truncate">{a.desc}</div>
                  <div className="landing-app-stats">
                    <span><I.model size={12} /> {a.models}</span>
                    <span><I.form size={12} /> {a.forms}</span>
                    <span><I.role size={12} /> {a.roles}</span>
                    <span><I.dict size={12} /> {a.dicts}</span>
                  </div>
                </button>
              ))}
              {projectApps.length === 0 && (
                <div className="empty" style={{ gridColumn: '1 / -1' }}>
                  <I.apps size={32} />
                  <div className="empty-title">这个项目还没有应用</div>
                  <div className="empty-sub">通过对话或上传设计文档创建第一个应用。</div>
                  <button className="btn btn-primary" onClick={() => navigate('/chat')}>
                    <I.plus size={13} /> 开始第一个应用
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Members */}
        {tab === 'members' && (
          <div className="card" style={{ padding: 0, overflow: 'hidden', marginTop: 16 }}>
            <div className="apps-row apps-row-head">
              <div style={{ flex: 1.4 }}>成员</div>
              <div style={{ flex: 1 }}>本项目角色</div>
              <div style={{ flex: 1.4 }}>权限范围</div>
              <div style={{ width: 100 }}>状态</div>
              <div style={{ width: 80, textAlign: 'right' }} />
            </div>
            {p.members.map((m, i) => {
              const perms = {
                '项目负责人': '全部 · 含成员管理 · 含生产部署',
                '项目负责人 + 实施': '全部 · 含成员管理 · 含生产部署',
                '实施顾问': '编辑 SPEC · 部署到 test',
                '前端开发': '编辑代码 · 发布组件',
                '后端开发': '编辑代码 · 配置 MCP',
                '客户业务': '只读 · 可评论 · 可审批 SPEC',
                '客户业务方': '只读 · 可评论 · 可审批 SPEC',
                '客户 IT': '只读 · 接入环境配置',
                '架构顾问': '只读 + 评审',
                '观察员': '只读',
              }[m.role] || '只读';
              return (
                <div key={i} className="apps-row apps-row-item" style={{ cursor: 'default' }}>
                  <div style={{ flex: 1.4, display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span className={`proj-avatar proj-avatar-${m.tone}`}>{m.avatar}</span>
                    <div>
                      <div className="apps-row-name">{m.name}</div>
                      <div className="apps-row-sub">marshub@definesys.cn</div>
                    </div>
                  </div>
                  <div style={{ flex: 1 }}>
                    <span className="badge badge-brand">{m.role}</span>
                  </div>
                  <div style={{ flex: 1.4, fontSize: 12, color: 'var(--text-2)' }}>{perms}</div>
                  <div style={{ width: 100 }}>
                    <span className="badge badge-emerald"><span className="badge-dot" /> 已加入</span>
                  </div>
                  <div style={{ width: 80, textAlign: 'right' }}>
                    <button className="icon-btn" style={{ width: 26, height: 26 }}><I.more size={14} /></button>
                  </div>
                </div>
              );
            })}
            <div style={{ padding: 14, borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: 'var(--text-3)' }}>项目角色仅作用于本项目内的权限与通知，不影响导航。</span>
              <button className="btn btn-primary btn-sm"><I.plus size={12} /> 邀请成员</button>
            </div>
          </div>
        )}

        {/* Industry pack binding */}
        {tab === 'industry' && (
          <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div className="card card-pad" style={{ padding: 22 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div className="industry-pack-icon tone-amber" style={{ width: 44, height: 44, borderRadius: 11 }}><I.industry size={20} /></div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 17, fontWeight: 600 }}>{p.industryName} <span className="mono" style={{ fontSize: 12, color: 'var(--text-3)', fontWeight: 500 }}>{p.industryVersion}</span></div>
                  <div style={{ fontSize: 12.5, color: 'var(--text-2)', marginTop: 4 }}>已应用于本项目内所有 AI Builder 会话和生成的 SPEC。</div>
                </div>
                <button className="btn btn-secondary btn-sm" onClick={() => navigate('/industry')}>查看 Ontology →</button>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginTop: 16 }}>
                {[
                  { l: '业务对象',  v: 12, ic: 'model' },
                  { l: '标准流程',  v: 8,  ic: 'flow' },
                  { l: '行业字典',  v: 24, ic: 'dict' },
                ].map(s => {
                  const Ic = I[s.ic];
                  return (
                    <div key={s.l} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 12, background: 'var(--surface-2)', borderRadius: 8 }}>
                      <Ic size={14} style={{ color: 'var(--brand-text)' }} />
                      <div>
                        <div style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.1 }}>{s.v}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{s.l}</div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div style={{ marginTop: 16, padding: 14, background: 'var(--ai-soft)', border: '1px solid var(--ai-soft-2)', borderRadius: 10, display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <I.sparkle size={14} style={{ color: 'var(--ai-text)', flexShrink: 0, marginTop: 1 }} />
                <div style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--text-2)' }}>
                  <b style={{ color: 'var(--text)' }}>AI Builder 如何使用：</b>
                  本项目内的 SPEC 生成会**优先复用**包内对象。例如要求"加一个工单"时，AI 会先匹配 <code className="mono">work_order</code> 对象（已有 18 字段），而不是从零生成。
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-secondary btn-sm"><I.refresh size={12} /> 升级到 v2.2</button>
              <button className="btn btn-secondary btn-sm"><I.copy size={12} /> 派生企业专属包</button>
              <button className="btn btn-ghost btn-sm" style={{ color: 'var(--rose)' }}>解绑</button>
            </div>
          </div>
        )}

        {/* Environments */}
        {tab === 'envs' && (
          <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
            {['dev', 'test', 'prod'].map(env => {
              const enabled = p.envs.includes(env);
              const isDefault = p.defaultEnv === env;
              return (
                <div key={env} className={`card card-pad rt-env-card rt-env-${env}`} style={{ opacity: enabled ? 1 : 0.5 }}>
                  <div className="rt-env-head">
                    <div className={`rt-env-stripe rt-env-stripe-${env}`} />
                    <div className="rt-env-titles">
                      <div className="rt-env-name">
                        {env === 'dev' ? '开发' : env === 'test' ? '测试' : '生产'}环境
                        {isDefault && <span className="badge badge-brand" style={{ marginLeft: 6 }}>默认</span>}
                      </div>
                      <div className="rt-env-host">
                        {enabled ? <span className="rt-env-status rt-env-status-ok"><span className="rt-env-status-dot" /> 已启用</span>
                                 : <span className="rt-env-status rt-env-status-warn"><span className="rt-env-status-dot" /> 未启用</span>}
                      </div>
                    </div>
                  </div>
                  <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 8 }}>
                    {enabled ? '已部署 ' + Math.floor(p.deployedCount * (env === 'prod' ? 0.4 : env === 'test' ? 0.4 : 0.2)) + ' 个应用' : '点击启用'}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { Projects, ProjectDetail });
