// ChatPage — three-column build workspace:
//   left: conversations list
//   center: chat thread (with mock interactive send)
//   right: live blueprint panel (CONSOLIDATED — replaces 5 disconnected tabs)
//
// The blueprint panel is the key UX fix: instead of 5 separate tabs (模型/表单/流程/角色/字典)
// users have to click through, everything is in ONE scrollable panel with sticky section nav
// and live "what just changed" highlights.

function ChatPage() {
  const { navigate } = useContext(RouteCtx);
  const { openDeploy } = useContext(RoleCtx) || { openDeploy: () => {} };
  const { conversations, chatThread, blueprint } = window.MOCK;

  const [activeConv, setActiveConv] = useState(201);
  const [thread, setThread] = useState(chatThread);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [activeSection, setActiveSection] = useState('models');
  const [collapsedSections, setCollapsedSections] = useState({});
  const [expandedItem, setExpandedItem] = useState('asset_main'); // which sub-item is open
  const [convListCollapsed, setConvListCollapsed] = useState(false);
  const [bpCollapsed, setBpCollapsed] = useState(false);
  const threadRef = useRef(null);

  // Auto-scroll thread to bottom on new messages
  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [thread, sending]);

  const send = () => {
    if (!draft.trim() || sending) return;
    setThread(t => [...t, { role: 'user', text: draft, time: 'now' }]);
    setDraft('');
    setSending(true);
    setTimeout(() => {
      setThread(t => [...t, {
        role: 'ai',
        text: '收到 ✓ 已根据你的最新需求更新了右侧蓝图。请检查"资产主档"模型的新字段。',
        time: 'now',
        extras: ['更新 数据模型 · 字典'],
      }]);
      setSending(false);
    }, 1100);
  };

  const sections = [
    { key: 'summary',   label: '概览',     icon: 'layers', count: null },
    { key: 'models',    label: '数据模型', icon: 'model',  count: blueprint.models.length },
    { key: 'forms',     label: '表单',     icon: 'form',   count: blueprint.forms.length },
    { key: 'workflows', label: '流程',     icon: 'flow',   count: blueprint.workflows.length },
    { key: 'roles',     label: '角色权限', icon: 'role',   count: blueprint.roles.length },
    { key: 'dicts',     label: '字典',     icon: 'dict',   count: blueprint.dicts.length },
  ];

  const toggleSec = (key) => setCollapsedSections(s => ({ ...s, [key]: !s[key] }));
  const scrollToSection = (key) => {
    setActiveSection(key);
    const el = document.getElementById('bp-section-' + key);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="chat-page">
      {/* ──── Left: Conversations rail ──── */}
      <aside className={`chat-convs ${convListCollapsed ? 'collapsed' : ''}`}>
        <div className="chat-convs-head">
          {!convListCollapsed && <div className="chat-convs-title">对话</div>}
          <div style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
            <button className="icon-btn" style={{ width: 26, height: 26 }} title="新建对话" onClick={() => setThread([])}>
              <I.plus size={14} />
            </button>
            <button className="icon-btn" style={{ width: 26, height: 26 }} title="折叠" onClick={() => setConvListCollapsed(c => !c)}>
              {convListCollapsed ? <I.chevronR size={13} /> : <I.chevronL size={13} />}
            </button>
          </div>
        </div>

        {!convListCollapsed && (
          <>
            <div className="chat-convs-search">
              <I.search size={12} />
              <input placeholder="搜索对话..." />
            </div>

            <div className="chat-convs-list">
              <div className="chat-convs-group-label">置顶</div>
              {conversations.filter(c => c.pinned).map(c => (
                <ConvItem key={c.id} c={c} active={c.id === activeConv} onClick={() => setActiveConv(c.id)} />
              ))}
              <div className="chat-convs-group-label">最近</div>
              {conversations.filter(c => !c.pinned).map(c => (
                <ConvItem key={c.id} c={c} active={c.id === activeConv} onClick={() => setActiveConv(c.id)} />
              ))}
            </div>
          </>
        )}
      </aside>

      {/* ──── Center: Chat thread ──── */}
      <main className="chat-main">
        <div className="chat-main-head">
          <div className="chat-main-head-l">
            <div className="landing-app-icon tone-indigo" style={{ width: 30, height: 30, borderRadius: 8, fontSize: 12 }}>资</div>
                <div>
                  <div className="chat-main-title">资产管理系统 — 新增报废流程</div>
                  <div className="chat-main-meta">
                    <span className="badge badge-emerald"><span className="badge-dot" /> 设计中</span>
                    <span className="chat-main-meta-sep">·</span>
                    <span>18 条消息</span>
                    <span className="chat-main-meta-sep">·</span>
                    <span>SPEC v3 草稿</span>
                    <span className="chat-main-meta-sep">·</span>
                    <span>睿鲸 Builder · Claude Haiku 4.5</span>
                  </div>
                </div>
          </div>
          <div className="chat-main-head-r">
            <button className="btn btn-secondary btn-sm" title="导出 SPEC"><I.download size={13} /> 导出 SPEC</button>
            <button className="btn btn-secondary btn-sm" title="切换模型"><I.switchH size={13} /> 切换模型</button>
            <button className="btn btn-primary btn-sm" onClick={openDeploy}><I.rocket size={13} /> 部署到平台</button>
          </div>
        </div>

        <div ref={threadRef} className="chat-thread">
          {/* Knowledge sources strip — wires Industry pack to AI Builder visibly */}
          <div className="chat-knowledge-strip">
            <I.sparkle size={11} />
            <span>本会话由 <b style={{ color: 'var(--text)' }}>睿鲸 AI Builder</b> 处理 · 引用</span>
            <span className="chat-knowledge-pack"><I.industry size={9} /> 制造装备 v2.1</span>
            <span style={{ color: 'var(--text-3)' }}>12 业务对象</span>
            <button className="chat-knowledge-link" onClick={() => navigate('/agents')}>
              查看 Agent 配置 →
            </button>
          </div>
          <div className="chat-thread-day">今天 · 5 月 17 日</div>

          {thread.map((m, i) => <Message key={i} m={m} />)}

          {sending && (
            <div className="chat-msg chat-msg-ai">
              <div className="chat-msg-avatar chat-msg-avatar-ai"><I.sparkle size={14} /></div>
              <div className="chat-msg-body">
                <div className="chat-msg-bubble chat-msg-bubble-ai">
                  <div className="typing-dots"><span /><span /><span /></div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="chat-composer">
          <div className="chat-composer-suggest">
            <span className="chat-composer-suggest-label">追问建议</span>
            {['完善资产主档字段', '增加报废审批节点', '加一个盘点看板'].map(s => (
              <button key={s} className="landing-pill" onClick={() => setDraft(s)}>{s}</button>
            ))}
          </div>
          <div className="chat-composer-box">
            <textarea
              className="chat-composer-input"
              placeholder="继续描述你的需求，比如：报废流程需要财务和资产管理员双重审批..."
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send(); }}
              rows={2}
            />
            <div className="chat-composer-actions">
              <div style={{ display: 'flex', gap: 4 }}>
                <button className="icon-btn" title="附件"><I.paperclip size={15} /></button>
                <button className="icon-btn" title="切换模型"><I.switchH size={15} /></button>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>⌘ + Enter 发送</span>
                <button className="btn btn-primary btn-sm" onClick={send} disabled={!draft.trim() || sending}>
                  发送 <I.send size={12} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* ──── Right: Blueprint panel ──── */}
      <aside className={`chat-bp ${bpCollapsed ? 'collapsed' : ''}`}>
        {bpCollapsed ? (
          <button className="chat-bp-collapsed-tab" onClick={() => setBpCollapsed(false)}>
            <I.chevronL size={14} />
            <span>应用蓝图</span>
          </button>
        ) : (
          <>
            <div className="chat-bp-head">
              <div>
                <div className="chat-bp-title">应用蓝图 <span className="badge badge-brand" style={{ marginLeft: 6 }}>实时</span></div>
                <div className="chat-bp-sub">{blueprint.summary.appName} · 完成度 {blueprint.summary.progress}%</div>
              </div>
              <div style={{ display: 'flex', gap: 4 }}>
                <button className="icon-btn" style={{ width: 28, height: 28 }} title="导出文档"><I.download size={14} /></button>
                <button className="icon-btn" style={{ width: 28, height: 28 }} title="折叠" onClick={() => setBpCollapsed(true)}>
                  <I.chevronR size={14} />
                </button>
              </div>
            </div>

            {/* Section mini-nav (replaces 5 tabs — but lets users jump quickly) */}
            <div className="chat-bp-nav">
              {sections.map(s => {
                const Ic = I[s.icon];
                return (
                  <button key={s.key} className={`chat-bp-nav-item ${activeSection === s.key ? 'active' : ''}`} onClick={() => scrollToSection(s.key)}>
                    <Ic size={13} />
                    <span>{s.label}</span>
                    {s.count != null && <span className="chat-bp-nav-count">{s.count}</span>}
                  </button>
                );
              })}
            </div>

            <div className="chat-bp-scroll">
              {/* ── Summary section ── */}
              <BpSection id="summary" title="概览" icon="layers" collapsed={collapsedSections.summary} onToggle={() => toggleSec('summary')}>
                <div className="chat-bp-summary">
                  <div className="chat-bp-progress">
                    <div className="chat-bp-progress-bar"><div className="chat-bp-progress-fill" style={{ width: `${blueprint.summary.progress}%` }} /></div>
                    <div className="chat-bp-progress-label">{blueprint.summary.progress}% · 设计中</div>
                  </div>
                  <div className="chat-bp-stages">
                    {blueprint.summary.stages.map((s, i) => (
                      <div key={i} className={`chat-bp-stage chat-bp-stage-${s.status}`}>
                        <div className="chat-bp-stage-dot">
                          {s.status === 'done' ? <I.check size={11} /> : s.status === 'active' ? <I.dot size={8} /> : <span style={{ width: 4, height: 4, borderRadius: '50%', background: 'currentColor', display: 'block' }} />}
                        </div>
                        <div className="chat-bp-stage-label">{s.name}</div>
                      </div>
                    ))}
                  </div>
                  <div className="chat-bp-quick-stats">
                    <div className="chat-bp-quick-stat">
                      <I.model size={13} />
                      <div><b>{blueprint.models.length}</b> 数据模型</div>
                    </div>
                    <div className="chat-bp-quick-stat">
                      <I.form size={13} />
                      <div><b>{blueprint.forms.length}</b> 表单</div>
                    </div>
                    <div className="chat-bp-quick-stat">
                      <I.flow size={13} />
                      <div><b>{blueprint.workflows.length}</b> 流程</div>
                    </div>
                    <div className="chat-bp-quick-stat">
                      <I.role size={13} />
                      <div><b>{blueprint.roles.length}</b> 角色</div>
                    </div>
                    <div className="chat-bp-quick-stat">
                      <I.dict size={13} />
                      <div><b>{blueprint.dicts.length}</b> 字典</div>
                    </div>
                    <div className="chat-bp-quick-stat">
                      <I.layers size={13} />
                      <div><b>{blueprint.models.reduce((s, m) => s + m.fields.length, 0)}</b> 字段</div>
                    </div>
                  </div>
                </div>
              </BpSection>

              {/* ── Models — expand each to see full field table ── */}
              <BpSection id="models" title="数据模型" icon="model" count={blueprint.models.length} collapsed={collapsedSections.models} onToggle={() => toggleSec('models')}>
                {blueprint.models.map(m => {
                  const isOpen = expandedItem === m.code;
                  return (
                    <div key={m.code} className={`bp-model ${m.hot ? 'is-hot' : ''} ${isOpen ? 'is-open' : ''}`}>
                      <button className="bp-model-head" onClick={() => setExpandedItem(isOpen ? null : m.code)}>
                        <I.chevronD size={11} style={{ transform: isOpen ? 'rotate(0)' : 'rotate(-90deg)', transition: 'transform 0.15s', color: 'var(--text-3)' }} />
                        <div className="bp-model-name">
                          {m.name}
                          {m.hot && <span className="bp-item-pulse" />}
                        </div>
                        <span className="bp-model-code mono">{m.code}</span>
                        <span className="bp-model-fieldcount">{m.fields.length} 字段</span>
                        {m.confirmed
                          ? <span className="badge badge-emerald"><I.check size={10} /></span>
                          : <span className="badge badge-amber">待确认</span>}
                      </button>
                      <div className="bp-model-desc">{m.desc}</div>

                      {isOpen && (
                        <div className="bp-model-body">
                          {/* Field table */}
                          <table className="bp-fields">
                            <thead>
                              <tr>
                                <th style={{ width: '40%' }}>字段</th>
                                <th>类型</th>
                                <th style={{ width: 38, textAlign: 'center' }}>必填</th>
                                <th style={{ width: 36, textAlign: 'center' }}>唯一</th>
                              </tr>
                            </thead>
                            <tbody>
                              {m.fields.map(f => (
                                <tr key={f.code} className={f.recent ? 'is-recent' : ''}>
                                  <td>
                                    <div className="bp-field-name">
                                      {f.pk && <span className="bp-field-pk" title="主键">PK</span>}
                                      <span>{f.name}</span>
                                      {f.recent && <span className="bp-field-recent" title="本次新增">NEW</span>}
                                    </div>
                                    <div className="bp-field-code mono">{f.code}{f.comment ? ` · ${f.comment}` : ''}</div>
                                  </td>
                                  <td className="bp-field-type mono">
                                    {f.type}{f.size ? `(${f.size})` : ''}
                                    {f.fk && <div className="bp-field-fk">→ {f.fk}</div>}
                                    {f.dict && <div className="bp-field-fk">字典: {f.dict}</div>}
                                    {f.default && <div className="bp-field-fk">默认: {f.default}</div>}
                                  </td>
                                  <td style={{ textAlign: 'center' }}>{f.required ? <I.check size={11} style={{ color: 'var(--brand)' }} /> : <span className="bp-field-dash">—</span>}</td>
                                  <td style={{ textAlign: 'center' }}>{f.unique ? <I.check size={11} style={{ color: 'var(--brand)' }} /> : <span className="bp-field-dash">—</span>}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>

                          {/* Indexes */}
                          {m.indexes?.length > 0 && (
                            <div className="bp-meta-block">
                              <div className="bp-meta-label">索引</div>
                              <div className="bp-meta-chips">
                                {m.indexes.map((ix, i) => (
                                  <span key={i} className="bp-meta-chip mono">
                                    {ix.type === 'unique' && <span className="bp-meta-tag">UQ</span>}
                                    {ix.type === 'composite' && <span className="bp-meta-tag">CX</span>}
                                    {ix.type === 'index' && <span className="bp-meta-tag">IX</span>}
                                    {ix.fields}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Relations */}
                          {m.relations?.length > 0 && (
                            <div className="bp-meta-block">
                              <div className="bp-meta-label">关系</div>
                              <div className="bp-rel-list">
                                {m.relations.map((r, i) => (
                                  <div key={i} className="bp-rel-row">
                                    <span className={`bp-rel-tag bp-rel-${r.type.replace('-', '_')}`}>
                                      {r.type === 'belongs-to' ? 'belongs to' : r.type === 'has-many' ? 'has many' : r.type === 'self-ref' ? 'self ref' : r.type}
                                    </span>
                                    <span className="mono" style={{ fontSize: 11 }}>{r.target}</span>
                                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>on {r.on}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </BpSection>

              {/* ── Forms — expand to see layout + rules ── */}
              <BpSection id="forms" title="表单" icon="form" count={blueprint.forms.length} collapsed={collapsedSections.forms} onToggle={() => toggleSec('forms')}>
                {blueprint.forms.map(f => {
                  const isOpen = expandedItem === f.code;
                  return (
                    <div key={f.code} className={`bp-form ${isOpen ? 'is-open' : ''}`}>
                      <button className="bp-form-head" onClick={() => setExpandedItem(isOpen ? null : f.code)}>
                        <I.chevronD size={11} style={{ transform: isOpen ? 'rotate(0)' : 'rotate(-90deg)', transition: 'transform 0.15s', color: 'var(--text-3)' }} />
                        <I.form size={13} style={{ color: 'var(--brand-text)' }} />
                        <span className="bp-form-name">{f.name}</span>
                        <span className="badge">{f.type}</span>
                        <span className="bp-form-model mono">← {f.model}</span>
                        {f.confirmed
                          ? <span className="badge badge-emerald" style={{ marginLeft: 'auto' }}><I.check size={10} /></span>
                          : <span className="badge badge-amber" style={{ marginLeft: 'auto' }}>待确认</span>}
                      </button>
                      {isOpen && (
                        <div className="bp-form-body">
                          {f.sections.map((s, i) => (
                            <div key={i} className="bp-form-section">
                              <div className="bp-form-section-title">{s.title}</div>
                              <div className="bp-form-section-fields">
                                {s.fields.map(field => (
                                  <div key={field.code} className="bp-form-field">
                                    <span className="mono bp-form-field-code">{field.code}</span>
                                    {field.widget && <span className="bp-form-field-widget">{field.widget}</span>}
                                    {field.col && <span className="bp-form-field-col">{field.col}/24</span>}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))}
                          {f.actions?.length > 0 && (
                            <div className="bp-meta-block">
                              <div className="bp-meta-label">动作</div>
                              <div className="bp-meta-chips">
                                {f.actions.map(a => <span key={a} className="bp-meta-chip">{a}</span>)}
                              </div>
                            </div>
                          )}
                          {f.rules?.length > 0 && (
                            <div className="bp-meta-block">
                              <div className="bp-meta-label">校验规则</div>
                              <ul className="bp-rules">
                                {f.rules.map((r, i) => <li key={i}>{r}</li>)}
                              </ul>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </BpSection>

              {/* ── Workflows (NEW) — node chain visualization ── */}
              <BpSection id="workflows" title="流程" icon="flow" count={blueprint.workflows.length} collapsed={collapsedSections.workflows} onToggle={() => toggleSec('workflows')}>
                {blueprint.workflows.map(w => {
                  const isOpen = expandedItem === w.code;
                  return (
                    <div key={w.code} className={`bp-flow ${isOpen ? 'is-open' : ''}`}>
                      <button className="bp-flow-head" onClick={() => setExpandedItem(isOpen ? null : w.code)}>
                        <I.chevronD size={11} style={{ transform: isOpen ? 'rotate(0)' : 'rotate(-90deg)', transition: 'transform 0.15s', color: 'var(--text-3)' }} />
                        <I.flow size={13} style={{ color: 'var(--brand-text)' }} />
                        <span className="bp-flow-name">{w.name}</span>
                        <span className="bp-flow-nodes">{w.nodes.length} 节点</span>
                        {w.confirmed
                          ? <span className="badge badge-emerald" style={{ marginLeft: 'auto' }}><I.check size={10} /></span>
                          : <span className="badge badge-amber" style={{ marginLeft: 'auto' }}>待确认</span>}
                      </button>
                      <div className="bp-flow-trigger"><I.zap size={11} /> {w.trigger}</div>

                      {isOpen && (
                        <div className="bp-flow-body">
                          <div className="bp-flow-chain">
                            {w.nodes.map((n, i) => (
                              <React.Fragment key={i}>
                                <div className={`bp-flow-node ${n.condition ? 'is-conditional' : ''}`}>
                                  <div className="bp-flow-node-num">{i + 1}</div>
                                  <div className="bp-flow-node-body">
                                    <div className="bp-flow-node-name">{n.name}</div>
                                    <div className="bp-flow-node-role">
                                      <I.role size={10} /> {n.role}
                                    </div>
                                    <div className="bp-flow-node-action">{n.action}</div>
                                    <div className="bp-flow-node-foot">
                                      {n.sla !== '—' && <span className="bp-flow-node-sla">SLA {n.sla}</span>}
                                      {n.condition && <span className="bp-flow-node-cond"><I.zap size={9} /> {n.condition}</span>}
                                    </div>
                                  </div>
                                </div>
                                {i < w.nodes.length - 1 && <div className="bp-flow-arrow"><I.chevronD size={12} /></div>}
                              </React.Fragment>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </BpSection>

              {/* ── Roles — expand to see permission matrix ── */}
              <BpSection id="roles" title="角色权限" icon="role" count={blueprint.roles.length} collapsed={collapsedSections.roles} onToggle={() => toggleSec('roles')}>
                {blueprint.roles.map(r => {
                  const isOpen = expandedItem === r.code;
                  return (
                    <div key={r.code} className={`bp-role ${isOpen ? 'is-open' : ''}`}>
                      <button className="bp-role-head" onClick={() => setExpandedItem(isOpen ? null : r.code)}>
                        <I.chevronD size={11} style={{ transform: isOpen ? 'rotate(0)' : 'rotate(-90deg)', transition: 'transform 0.15s', color: 'var(--text-3)' }} />
                        <I.role size={13} style={{ color: 'var(--brand-text)' }} />
                        <span className="bp-role-name">{r.name}</span>
                        <span className="bp-role-scope">{r.scope}</span>
                      </button>
                      <div className="bp-role-users"><I.user size={10} /> {r.users}</div>
                      {isOpen && (
                        <div className="bp-role-body">
                          <table className="bp-perms">
                            <thead>
                              <tr>
                                <th>模块</th>
                                <th>权限</th>
                              </tr>
                            </thead>
                            <tbody>
                              {r.matrix.map((m, i) => (
                                <tr key={i}>
                                  <td className="bp-perms-mod">{m.module}</td>
                                  <td>
                                    <div className="bp-perms-chips">
                                      {m.perms.map(p => <span key={p} className="bp-perms-chip">{p}</span>)}
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  );
                })}
              </BpSection>

              {/* ── Dicts — expand to see actual items ── */}
              <BpSection id="dicts" title="字典" icon="dict" count={blueprint.dicts.length} collapsed={collapsedSections.dicts} onToggle={() => toggleSec('dicts')}>
                {blueprint.dicts.map(d => {
                  const isOpen = expandedItem === d.code;
                  const flatCount = d.hierarchical
                    ? d.items.reduce((s, i) => s + 1 + (i.children?.length || 0), 0)
                    : d.items.length;
                  return (
                    <div key={d.code} className={`bp-dict ${isOpen ? 'is-open' : ''}`}>
                      <button className="bp-dict-head" onClick={() => setExpandedItem(isOpen ? null : d.code)}>
                        <I.chevronD size={11} style={{ transform: isOpen ? 'rotate(0)' : 'rotate(-90deg)', transition: 'transform 0.15s', color: 'var(--text-3)' }} />
                        <I.dict size={13} style={{ color: 'var(--brand-text)' }} />
                        <span className="bp-dict-name">{d.name}</span>
                        <span className="bp-dict-code mono">{d.code}</span>
                        <span className="bp-dict-count">{flatCount} 项{d.hierarchical ? ' · 两级' : ''}</span>
                        {d.recent && <span className="bp-field-recent">NEW</span>}
                      </button>
                      {isOpen && (
                        <div className="bp-dict-body">
                          {d.hierarchical ? (
                            d.items.map(p => (
                              <div key={p.code} className="bp-dict-group">
                                <div className="bp-dict-parent">
                                  <span className="mono bp-dict-code-inline">{p.code}</span>
                                  {p.label}
                                </div>
                                <div className="bp-dict-children">
                                  {p.children?.map(c => (
                                    <span key={c.code} className="bp-dict-child">
                                      <span className="mono bp-dict-code-inline">{c.code}</span>
                                      {c.label}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            ))
                          ) : (
                            <div className="bp-dict-flat">
                              {d.items.map(it => (
                                <span key={it.code} className={`bp-dict-item ${it.tone ? 'tone-' + it.tone : ''}`}>
                                  <span className="bp-dict-dot" />
                                  <span>{it.label}</span>
                                  <span className="mono bp-dict-code-inline">{it.code}</span>
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </BpSection>

              <div className="chat-bp-foot">
                <button className="btn btn-primary" style={{ width: '100%' }} onClick={openDeploy}>
                  <I.rocket size={14} /> 一键部署到平台
                </button>
                <div className="chat-bp-foot-meta">蓝图最后更新：14:23 · 由 marshub 触发</div>
              </div>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}

function ConvItem({ c, active, onClick }) {
  return (
    <button className={`chat-conv-item ${active ? 'active' : ''}`} onClick={onClick}>
      <div className="chat-conv-icon">
        {c.pinned ? <I.pin size={11} /> : <I.chat size={11} />}
      </div>
      <div className="chat-conv-body">
        <div className="chat-conv-title truncate">{c.title}</div>
        <div className="chat-conv-meta">
          <span>{c.updatedAt}</span>
          <span>·</span>
          <span>{c.messages} 条</span>
        </div>
      </div>
    </button>
  );
}

function Message({ m }) {
  const isUser = m.role === 'user';
  const linesToHtml = (txt) => {
    return txt.split('\n').map((line, i) => {
      // simple bold + code
      const html = line
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
        .replace(/`(.+?)`/g, '<code>$1</code>');
      return <div key={i} style={{ minHeight: line ? undefined : 6 }} dangerouslySetInnerHTML={{ __html: html }} />;
    });
  };
  return (
    <div className={`chat-msg chat-msg-${m.role}`}>
      <div className={`chat-msg-avatar chat-msg-avatar-${m.role}`}>
        {isUser ? 'M' : <I.sparkle size={14} />}
      </div>
      <div className="chat-msg-body">
        <div className="chat-msg-meta">
          <span className="chat-msg-name">{isUser ? 'marshub' : 'aPaaS Builder AI'}</span>
          {m.time && <span className="chat-msg-time">{m.time}</span>}
        </div>
        <div className={`chat-msg-bubble chat-msg-bubble-${m.role}`}>
          {linesToHtml(m.text)}
        </div>
        {m.extras?.length > 0 && (
          <div className="chat-msg-extras">
            {m.extras.map((e, i) => (
              <span key={i} className="chat-msg-extra"><I.zap size={10} /> {e}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function BpSection({ id, title, icon, count, collapsed, onToggle, children }) {
  const Ic = I[icon];
  return (
    <section id={'bp-section-' + id} className={`bp-section ${collapsed ? 'is-collapsed' : ''}`}>
      <button className="bp-section-head" onClick={onToggle}>
        <I.chevronD size={12} style={{ transform: collapsed ? 'rotate(-90deg)' : 'rotate(0)', transition: 'transform 0.15s', color: 'var(--text-3)' }} />
        <Ic size={14} />
        <span className="bp-section-title">{title}</span>
        {count != null && <span className="bp-section-count">{count}</span>}
      </button>
      {!collapsed && <div className="bp-section-body">{children}</div>}
    </section>
  );
}

window.ChatPage = ChatPage;
