// AI Coding — pure chat-led low-code component generation.
//
// PRODUCT INTENT:
//   - User does NOT write code, NOT edit files manually
//   - Pure conversational: describe → AI plans → AI generates → review artifacts → publish
//   - Output: UMD bundle for aPaaS form designer (no live preview)
//
// LAYOUT:
//   Left:  workspaces (each = one component being generated)
//   Center: pipeline + chat thread + composer
//   Right: generated artifacts (file list + integration steps)

function CodingPage() {
  const { navigate } = useContext(RouteCtx);
  const { workspaces, codingSteps, codingChat } = window.MOCK;
  const [activeWs, setActiveWs] = useState('ws-1');
  const [outputTab, setOutputTab] = useState('files');
  const [draft, setDraft] = useState('');

  const ws = workspaces.find(w => w.id === activeWs) || workspaces[0];

  const statusMeta = ws.status === 'building' ? { label: '生成中', cls: 'badge-brand' }
                  : ws.status === 'ready'    ? { label: '可发布', cls: 'badge-emerald' }
                  :                            { label: '空闲',   cls: '' };

  // What the agent has done in the active run — replaces the fake "code editor + file tree".
  // Tells the user exactly what artifacts exist and what's still in progress.
  const activity = [
    { icon: 'check',  state: 'done',    text: '读取目标应用结构（资产管理系统）', meta: '14 文件' },
    { icon: 'check',  state: 'done',    text: '规划组件拆分', meta: '5 个 Vue · 1 个 store' },
    { icon: 'check',  state: 'done',    text: '并行写入 TravelForm.vue', meta: '6.4 KB' },
    { icon: 'check',  state: 'done',    text: '并行写入 TravelDetailTable.vue', meta: '4.1 KB' },
    { icon: 'zap',    state: 'active',  text: '写入 AttachmentUploader.vue', meta: '3/8 块' },
    { icon: 'dot',    state: 'pending', text: '注入 useTravelForm.ts 依赖', meta: '—' },
    { icon: 'dot',    state: 'pending', text: '本地编译验证（生成 UMD 包）', meta: '—' },
    { icon: 'dot',    state: 'pending', text: '发布到组件市场', meta: '—' },
  ];

  return (
    <div className="whale-page">
      {/* ── Left: workspaces ── */}
      <aside className="whale-left">
        <div className="whale-left-head">
          <div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>组件生成工作区</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>每个工作区生成 1 个低代码组件</div>
          </div>
          <button className="btn btn-primary btn-sm">
            <I.plus size={12} /> 新建
          </button>
        </div>

        <div className="whale-left-list">
          {workspaces.map(w => (
            <button key={w.id} className={`whale-ws ${activeWs === w.id ? 'active' : ''}`} onClick={() => setActiveWs(w.id)}>
              <div className="whale-ws-head">
                <span className={`whale-ws-icon whale-ws-${w.status}`}>
                  {w.status === 'building' ? <I.zap size={12} /> : w.status === 'ready' ? <I.check size={12} /> : <I.dot size={8} />}
                </span>
                <span className="whale-ws-name truncate">{w.name}</span>
              </div>
              <div className="whale-ws-meta">
                <span className="badge">{w.typeLabel}</span>
                <span style={{ marginLeft: 'auto', fontSize: 10.5, color: 'var(--text-3)' }}>{w.time}</span>
              </div>
              {w.status === 'building' && (
                <div className="whale-ws-progress">
                  <div className="whale-ws-progress-bar"><div className="whale-ws-progress-fill" style={{ width: w.progress + '%' }} /></div>
                  <span className="whale-ws-progress-label">{w.progress}% · {w.filesWritten}/{w.filesPlanned} 文件</span>
                </div>
              )}
              <div className="whale-ws-activity truncate">{w.lastActivity}</div>
            </button>
          ))}
        </div>

        <div className="whale-left-foot">
          <div className="whale-tip">
            <I.book size={13} />
            <div>
              <b>AI Coding：</b>这里你只用聊天，AI 生成 UMD 包并发布到组件市场；平台连接、模型和 MCP 在平台管理后台统一配置。
            </div>
          </div>
        </div>
      </aside>

      {/* ── Center: pipeline + chat ── */}
      <main className="whale-main">

        {/* Status bar with steps */}
        <div className="whale-status">
          <div className="whale-status-head">
            <div className="whale-status-l">
              <span className="landing-app-icon tone-indigo" style={{ width: 30, height: 30, borderRadius: 7, fontSize: 12 }}>差</span>
              <div>
                <div className="whale-status-name">{ws.name}</div>
                <div className="whale-status-meta">
                  <span className={`badge ${statusMeta.cls}`}><span className="badge-dot" />{statusMeta.label}</span>
                  <span>·</span>
                  <span>{ws.typeLabel}</span>
                  <span>·</span>
                  <span>token {ws.tokensUsed.toLocaleString()}</span>
                  <span>·</span>
                  <button className="vibe-sbx-chip" onClick={() => navigate('/admin')} title="平台管理中查看运行配置">
                    <I.cloud size={10} />
                    <span><b>构建环境</b> · 2C/4G · 平台托管</span>
                  </button>
                  <span>·</span>
                  <span>挂载 MCP: <b style={{ color: 'var(--text-2)' }}>aPaaS Tools · 组件市场检索</b></span>
                </div>
              </div>
            </div>
            <div className="whale-status-r">
              <button className="btn btn-secondary btn-sm"><I.book size={12} /> Agent 日志</button>
              <button className="btn btn-secondary btn-sm"><I.refresh size={12} /> 重新生成</button>
              <button className="btn btn-primary btn-sm" disabled={ws.status !== 'ready'}>
                <I.store size={12} /> 发布到组件市场
              </button>
            </div>
          </div>

          <div className="whale-steps">
            {codingSteps.map((s, i) => (
              <div key={i} className={`whale-step whale-step-${s.status}`}>
                <div className="whale-step-dot">
                  {s.status === 'done' && <I.check size={11} />}
                  {s.status === 'active' && <span className="whale-step-pulse" />}
                  {s.status === 'pending' && <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'currentColor', display: 'block' }} />}
                </div>
                <div className="whale-step-body">
                  <div className="whale-step-name">{s.name}</div>
                  <div className="whale-step-detail truncate">{s.detail}</div>
                </div>
                {i < codingSteps.length - 1 && <div className="whale-step-conn" />}
              </div>
            ))}
          </div>
        </div>

        {/* Chat thread */}
        <div className="whale-chat">
          {codingChat.map((m, i) => (
            m.isToolStatus ? (
              <div key={i} className="whale-msg is-tool">
                <div className="whale-tool">
                  <I.check size={11} /> {m.text}
                </div>
              </div>
            ) : (
              <div key={i} className={`whale-msg ${m.role === 'user' ? 'whale-msg-user' : ''}`}>
                <div className={`chat-msg-avatar chat-msg-avatar-${m.role}`} style={{ width: 26, height: 26 }}>
                  {m.role === 'user' ? 'M' : <I.sparkle size={12} />}
                </div>
                <div className="whale-msg-body">
                  <div className="whale-msg-name">{m.role === 'user' ? 'marshub' : '睿鲸AI · AI Coding'}</div>
                  <div className={`whale-msg-bubble ${m.role === 'user' ? 'whale-msg-bubble-user' : ''}`}>
                    {m.text}
                  </div>
                  {m.toolCalls && (
                    <div className="whale-msg-tools">
                      {m.toolCalls.map(t => (
                        <span key={t} className="whale-tool-call mono">
                          <I.zap size={9} /> {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )
          ))}

          {/* Live activity card — replaces the fake editor */}
          <div className={`whale-msg`}>
            <div className="chat-msg-avatar chat-msg-avatar-ai" style={{ width: 26, height: 26 }}><I.sparkle size={12} /></div>
            <div className="whale-msg-body">
              <div className="whale-msg-name">睿鲸AI · AI Coding</div>
              <div className="whale-activity">
                {activity.map((a, i) => (
                  <div key={i} className={`whale-activity-row whale-activity-${a.state}`}>
                    {a.state === 'done' && <I.check size={12} style={{ color: 'var(--emerald)' }} />}
                    {a.state === 'active' && <span className="whale-step-pulse" />}
                    {a.state === 'pending' && <I.dot size={8} />}
                    <span dangerouslySetInnerHTML={{ __html: a.text.replace(/(\w+\.\w+)/g, '<code>$1</code>') }} />
                    <span className="whale-activity-meta">{a.meta}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Composer */}
        <div className="whale-composer">
          <div className="whale-composer-suggest">
            <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 500 }}>追问建议</span>
            {['表单加上字段校验', '改成横向布局', '附件支持批量上传', '生成 README'].map(s => (
              <button key={s} className="landing-pill" onClick={() => setDraft(s)}>{s}</button>
            ))}
          </div>
          <div className="whale-composer-box">
            <textarea
              className="whale-composer-input"
              placeholder="跟睿鲸继续聊：修改字段、加校验、改布局…（不会让你写代码）"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={2}
            />
            <div className="whale-composer-foot">
              <div style={{ display: 'flex', gap: 4 }}>
                <button className="icon-btn" title="附加附件"><I.paperclip size={14} /></button>
                <button className="icon-btn" title="切换模型"><I.switchH size={14} /></button>
                <button className="icon-btn" title="平台管理中配置 MCP"><I.mcp size={14} /></button>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--text-3)' }}>⌘+Enter 发送</span>
                <button className="btn btn-primary btn-sm" disabled={!draft.trim()}>
                  发送 <I.send size={12} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* ── Right: generated artifacts ── */}
      <aside className="whale-right">
        <div className="whale-right-head">
          <span style={{ fontSize: 13, fontWeight: 600 }}>生成产物</span>
          <div className="coding-preview-tabs">
            <button className={outputTab === 'files' ? 'active' : ''} onClick={() => setOutputTab('files')}>文件清单</button>
            <button className={outputTab === 'integrate' ? 'active' : ''} onClick={() => setOutputTab('integrate')}>接入说明</button>
          </div>
          <button className="icon-btn" style={{ width: 26, height: 26 }} title="下载产物"><I.download size={13} /></button>
        </div>

        {outputTab === 'files' ? (
          <div className="whale-right-body">
            <div className="whale-output-summary">
              <div className="whale-output-summary-row">
                <span className="badge badge-emerald"><I.check size={10} /> 6 个新增</span>
                <span className="badge badge-amber">2 个修改</span>
                <span className="badge">14 个文件参与</span>
              </div>
              <div className="whale-output-summary-meta">体积 23.4 KB · 编译耗时 1.8 s · UMD ready</div>
            </div>

            <div className="whale-output-section">
              <div className="whale-output-section-head">
                <span>新增 · 6</span>
                <button className="section-action">展开全部</button>
              </div>
              {[
                { name: 'TravelForm.vue', path: 'src/components/', size: '6.4 KB', kind: 'vue', diff: '+212' },
                { name: 'TravelDetailTable.vue', path: 'src/components/', size: '4.1 KB', kind: 'vue', diff: '+148' },
                { name: 'AttachmentUploader.vue', path: 'src/components/', size: '3.8 KB', kind: 'vue', diff: '+126', writing: true },
                { name: 'useTravelForm.ts', path: 'src/composables/', size: '2.6 KB', kind: 'ts', diff: '+98' },
                { name: 'travelFormSchema.ts', path: 'src/composables/', size: '1.9 KB', kind: 'ts', diff: '+72' },
                { name: 'index.ts', path: 'src/', size: '0.4 KB', kind: 'ts', diff: '+14' },
              ].map(f => (
                <div key={f.name} className="whale-output-file">
                  <span className={`coding-file-icon coding-file-${f.kind}`}>{f.kind === 'vue' ? 'V' : 'TS'}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="whale-output-file-name truncate">{f.name}</div>
                    <div className="whale-output-file-meta truncate"><span className="mono">{f.path}</span> · {f.size}</div>
                  </div>
                  {f.writing ? (
                    <span className="whale-output-file-writing"><span className="coding-tab-spinner" /> 写入</span>
                  ) : (
                    <span className="whale-output-file-diff mono">{f.diff}</span>
                  )}
                </div>
              ))}
            </div>

            <div className="whale-output-section">
              <div className="whale-output-section-head"><span>修改 · 2</span></div>
              {[
                { name: 'router.ts',    path: 'src/', size: '+1 行',  kind: 'ts' },
                { name: 'package.json', path: '/',   size: '+1 依赖', kind: 'json' },
              ].map(f => (
                <div key={f.name} className="whale-output-file">
                  <span className={`coding-file-icon coding-file-${f.kind}`}>{f.kind === 'json' ? '{}' : 'TS'}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="whale-output-file-name truncate">{f.name}</div>
                    <div className="whale-output-file-meta truncate"><span className="mono">{f.path}</span> · {f.size}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="whale-right-body">
            <div className="coding-output-callout">
              <I.book size={14} />
              <div>
                <b>低代码自开发组件不支持平台内实时预览。</b>
                生成完成后按下面步骤上线，在表单设计器拖拽即可使用。
              </div>
            </div>

            <div className="coding-output-step">
              <div className="coding-output-step-num">1</div>
              <div style={{ flex: 1 }}>
                <div className="coding-output-step-title">睿鲸自动打包为 UMD</div>
                <pre className="coding-output-snippet"><code>{`npm run build:component \\
  --name=TravelForm \\
  --target=apaas-form-component`}</code></pre>
              </div>
            </div>

            <div className="coding-output-step">
              <div className="coding-output-step-num">2</div>
              <div style={{ flex: 1 }}>
                <div className="coding-output-step-title">发布到组件市场</div>
                <div className="coding-output-step-desc">
                  发布后绑定到当前应用的「自开发组件库」。当前租户内任意应用均可引用。
                </div>
                <button className="btn btn-primary btn-sm" style={{ marginTop: 8 }}>
                  <I.store size={12} /> 发布 v0.1.0
                </button>
              </div>
            </div>

            <div className="coding-output-step">
              <div className="coding-output-step-num">3</div>
              <div style={{ flex: 1 }}>
                <div className="coding-output-step-title">在表单设计器中引用</div>
                <div className="coding-output-step-desc">
                  打开目标表单 → 拖入「TravelForm」组件 → 在右侧属性面板配置数据源绑定即可。
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 6, paddingTop: 12, borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}>
              <span className="badge badge-emerald"><I.check size={10} /> 兼容 Element UI 2.x · Vue 2.7</span>
              <span className="badge badge-outline">睿鲸AI ≥ 4.2</span>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

window.CodingPage = CodingPage;
