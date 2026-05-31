// Agents 智能体配置中心
// Each of 3 agents has: model, system prompt, skills, MCP bindings, knowledge sources.
// Answers: 「3 个智能体的 Skills / MCP 怎么接入？」 visibly.

function Agents() {
  const { navigate } = useContext(RouteCtx);
  const { agents, skillCatalog, mcpServers, industryPacks } = window.MOCK;
  const [selected, setSelected] = useState('builder');
  const cur = agents.find(a => a.id === selected) || agents[0];
  const curMcps = (cur.mcps || []).map(id => mcpServers.find(m => m.id === id)).filter(Boolean);
  const curPacks = (cur.knowledge.industryPacks || []).map(id => industryPacks.find(p => p.id === id)).filter(Boolean);

  return (
    <div className="page">
      <div className="page-pad" style={{ maxWidth: 1320 }}>
        <div className="page-head">
          <div>
            <h1 className="page-title">智能体配置</h1>
            <div className="page-subtitle">
              3 个智能体 = 3 套"脑"，每个有自己的<b style={{ color: 'var(--text)' }}>模型 + System Prompt + Skills + MCP + 知识源</b>。
              所有 AI 行为都从这里发起。
            </div>
          </div>
          <button className="btn btn-secondary"><I.book size={13} /> Agent 调试历史</button>
        </div>

        <div className="agent-layout">
          {/* Left: 3 agents list */}
          <div className="agent-list">
            {agents.map(a => {
              const Ic = I[a.icon];
              return (
                <button key={a.id} className={`agent-pick ${selected === a.id ? 'active' : ''} agent-tone-${a.tone}`} onClick={() => setSelected(a.id)}>
                  <div className={`agent-pick-icon agent-pick-icon-${a.tone}`}><Ic size={18} /></div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="agent-pick-name">{a.name}</div>
                    <div className="agent-pick-role">{a.role}</div>
                    <div className="agent-pick-meta">
                      <span><b>{a.skills.length}</b> Skill</span>
                      <span>·</span>
                      <span><b>{a.mcps.length}</b> MCP</span>
                      <span>·</span>
                      <span>{a.todayCalls} 今日调用</span>
                    </div>
                  </div>
                  {selected === a.id && <I.chevronR size={14} style={{ color: 'var(--text-3)' }} />}
                </button>
              );
            })}

            <div className="agent-help">
              <div className="agent-help-head"><I.sparkle size={13} /> Agent 工作流程</div>
              <div className="agent-help-body">
                <div><b>1. 接收</b> 用户输入 + Project 上下文</div>
                <div><b>2. 加载</b> System Prompt + Skills 描述</div>
                <div><b>3. 调用</b> Tool（来自 MCP）+ Knowledge 检索</div>
                <div><b>4. 返回</b> 流式响应 + 调用日志</div>
              </div>
            </div>
          </div>

          {/* Right: agent detail */}
          <div className="agent-detail">
            <div className="card card-pad">
              <div className="agent-head">
                <div className={`agent-pick-icon agent-pick-icon-${cur.tone}`} style={{ width: 44, height: 44, borderRadius: 12 }}>
                  {(() => { const Ic = I[cur.icon]; return <Ic size={22} />; })()}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.015em' }}>{cur.name}</div>
                  <div style={{ fontSize: 13, color: 'var(--text-2)', marginTop: 2 }}>{cur.desc}</div>
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  <button className="btn btn-secondary btn-sm"><I.refresh size={12} /> 重置</button>
                  <button className="btn btn-primary btn-sm"><I.check size={12} /> 保存</button>
                </div>
              </div>

              {/* Model + basic */}
              <div className="agent-grid">
                <div className="agent-field">
                  <div className="agent-field-label">模型</div>
                  <select className="input" defaultValue={cur.model} key={cur.id}>
                    {cur.modelOptions.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
                <div className="agent-field">
                  <div className="agent-field-label">上下文窗口</div>
                  <div className="agent-field-value mono">{(cur.contextWindow / 1000).toFixed(0)}k tokens</div>
                </div>
                <div className="agent-field">
                  <div className="agent-field-label">最大输出</div>
                  <div className="agent-field-value mono">{cur.maxOutput} tokens</div>
                </div>
              </div>

              <div className="agent-field" style={{ marginTop: 14 }}>
                <div className="agent-field-label">System Prompt</div>
                <textarea className="textarea" rows={3} defaultValue={cur.systemPrompt} />
              </div>
            </div>

            {/* Skills */}
            <div className="card card-pad">
              <div className="agent-section-head">
                <span>Skills <span style={{ color: 'var(--text-3)', fontWeight: 500 }}>{cur.skills.length} 已挂载</span></span>
                <span title="说明">
                  <span className="term-mark" style={{ width: 14, height: 14 }}>?</span>
                </span>
                <button className="section-action" style={{ marginLeft: 'auto' }}>从 Skill 库添加 →</button>
              </div>
              <div className="agent-skills">
                {cur.skills.map(s => (
                  <div key={s.code} className="agent-skill">
                    <div className="agent-skill-head">
                      <code className="mono agent-skill-code">{s.code}</code>
                      <span className="agent-skill-name">{s.name}</span>
                      <button className="icon-btn" style={{ width: 24, height: 24, marginLeft: 'auto' }} title="移除"><I.trash size={11} /></button>
                    </div>
                    <div className="agent-skill-desc">{s.desc}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* MCPs */}
            <div className="card card-pad">
              <div className="agent-section-head">
                <span>挂载的 MCP <span style={{ color: 'var(--text-3)', fontWeight: 500 }}>{curMcps.length}</span></span>
                <span title="Skill / MCP / 知识源说明，详见配置文档">
                  <span className="term-mark" style={{ width: 14, height: 14 }}>?</span>
                </span>
                <button className="section-action" style={{ marginLeft: 'auto' }} onClick={() => navigate('/mcp')}>MCP 管理 →</button>
              </div>
              <div className="agent-mcps">
                {curMcps.map(m => (
                  <div key={m.id} className="agent-mcp">
                    <div className={`mcp-list-status mcp-status-${m.status}`} style={{ marginTop: 4 }}>
                      {m.status === 'connected' && <span className="mcp-list-pulse" />}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontSize: 13, fontWeight: 600 }}>{m.name}</span>
                        {m.official && <span className="badge badge-brand">官方</span>}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-3)' }}>
                        <span className="mono">{m.code}</span> · {m.tools} 工具 · v{m.version}
                      </div>
                    </div>
                    <button className="icon-btn" style={{ width: 24, height: 24 }} title="解绑"><I.trash size={11} /></button>
                  </div>
                ))}
                {curMcps.length === 0 && <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 12, textAlign: 'center' }}>此 Agent 暂未挂载任何 MCP</div>}
              </div>
            </div>

            {/* Knowledge */}
            <div className="card card-pad">
              <div className="agent-section-head">
                <span>知识源 <span style={{ color: 'var(--text-3)', fontWeight: 500 }}>{curPacks.length} 行业包 + {cur.knowledge.specTemplates.length} 文档模板</span></span>
                <span title="Skill / MCP / 知识源说明，详见配置文档">
                  <span className="term-mark" style={{ width: 14, height: 14 }}>?</span>
                </span>
                <button className="section-action" style={{ marginLeft: 'auto' }} onClick={() => navigate('/industry')}>行业知识库 →</button>
              </div>
              {curPacks.length > 0 || cur.knowledge.specTemplates.length > 0 ? (
                <div className="agent-knowledge">
                  {curPacks.map(pk => (
                    <div key={pk.id} className="agent-know-row">
                      <div className={`industry-pack-icon tone-${pk.tone}`} style={{ width: 28, height: 28, borderRadius: 7 }}><I.industry size={13} /></div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 600 }}>{pk.name} <span className="mono" style={{ fontSize: 10.5, color: 'var(--text-3)', fontWeight: 500, marginLeft: 4 }}>{pk.version}</span></div>
                        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>{pk.stats.entities} 业务对象 · {pk.stats.workflows} 流程 · {pk.stats.dicts} 字典</div>
                      </div>
                      <button className="icon-btn" style={{ width: 24, height: 24 }}><I.trash size={11} /></button>
                    </div>
                  ))}
                  {cur.knowledge.specTemplates.map(t => (
                    <div key={t} className="agent-know-row">
                      <div style={{ width: 28, height: 28, borderRadius: 7, background: 'var(--surface-3)', display: 'grid', placeItems: 'center' }}><I.doc size={13} style={{ color: 'var(--text-2)' }} /></div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 600 }} className="mono">{t}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-3)' }}>SPEC 模板</div>
                      </div>
                      <button className="icon-btn" style={{ width: 24, height: 24 }}><I.trash size={11} /></button>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 12, textAlign: 'center' }}>
                  此 Agent 不使用知识源（{cur.id === 'whale' ? '组件代码生成基于规范' : 'IDE 内 Agent 基于工程上下文'}）
                </div>
              )}
            </div>

            {/* How it composes */}
            <div className="card card-pad agent-compose">
              <div className="agent-section-head"><span>合成流程</span></div>
              <div className="agent-compose-row">
                <span className="agent-compose-chip">用户输入</span>
                <I.arrowRight size={11} />
                <span className="agent-compose-chip">+ Project 上下文</span>
                <I.arrowRight size={11} />
                <span className="agent-compose-chip">+ System Prompt</span>
                <I.arrowRight size={11} />
                <span className="agent-compose-chip">+ {cur.skills.length} Skills 描述</span>
                <I.arrowRight size={11} />
                <span className="agent-compose-chip">→ {cur.model}</span>
                <I.arrowRight size={11} />
                <span className="agent-compose-chip">调用 {curMcps.reduce((s,m) => s+m.tools, 0)} 工具</span>
                <I.arrowRight size={11} />
                <span className="agent-compose-chip" style={{ background: 'var(--brand-soft)', color: 'var(--brand-text)' }}>流式返回</span>
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  );
}

window.Agents = Agents;
