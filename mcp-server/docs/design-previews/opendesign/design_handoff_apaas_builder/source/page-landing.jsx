// Landing — AI hub centered layout (matches the user's reference).
// Three-mode picker (AI 对话 / 睿鲸 AI Coding / Vibe Coding 全代码) + unified composer.
// Below the hero: condensed stats + recent apps.

function Landing() {
  const { navigate } = useContext(RouteCtx);
  const { apps } = window.MOCK;
  const recent = apps.slice(0, 4);

  const MODES = [
    {
      key: 'chat',
      icon: 'chat',
      label: 'AI 对话',
      tagline: '需求梳理 / 文档整合',
      placeholder: '描述你想做的应用，或把材料拖进来…\n比如：搭建一个客户工单系统，工单流转 + SLA 看板 + 客户回访。',
      cta: '开始聊需求',
      target: '/chat?mode=requirements',
      tone: 'ai',
      tip: '把零碎想法和现有材料给 AI，自动整理成标准设计文档，然后进 Builder。',
    },
    {
      key: 'whale',
      icon: 'whale',
      label: '睿鲸 AI Coding',
      tagline: '生成低代码组件',
      placeholder: '描述你需要的低代码组件 / 页面 / 后端接口，AI 会按 aPaaS 规范并行生成并发布…\n比如：生成一个差旅报销表单，包含申请人、目的地、明细子表、附件上传。',
      cta: '开始生成',
      target: '/coding',
      tone: 'brand',
      tip: '不写代码：聊→生成 UMD 包→发布到组件市场→在表单设计器拖拽即可用。',
    },
    {
      key: 'vibe',
      icon: 'code',
      label: 'Vibe Coding',
      tagline: '全代码 · VS Code Web',
      placeholder: '在浏览器 IDE 里直接改你的工程…\n比如：把 src/views/Apps.vue 的筛选条改成多选，并加上"已部署"筛项。',
      cta: '打开工作区',
      target: '/vibe',
      tone: 'emerald',
      tip: 'Cursor 风格：code-server + MiniMax Chat 扩展。真编辑、真终端、真 commit。',
    },
  ];

  const initialMode = 'chat';
  const [mode, setMode] = useState(initialMode);
  const [draft, setDraft] = useState('');
  const cur = MODES.find(m => m.key === mode) || MODES[0];
  const visibleModes = MODES;
  const singleMode = false;

  const send = () => {
    if (!draft.trim()) return;
    navigate(cur.target);
  };

  return (
    <div className="page page-landing-v2">
      <div className="landing-v2-pad">

        {/* ─── Hero / AI hub ─── */}
        <div className="landing-v2-hero">
          <div className="landing-v2-aibadge">
            <span className="landing-v2-aibadge-text">AI</span>
            <span className="landing-v2-aibadge-glow" aria-hidden="true" />
          </div>

          <div className="landing-v2-eyebrow">APAAS&nbsp; CHAT&nbsp; AI&nbsp; · &nbsp; DESIGN&nbsp;+&nbsp;BUILD</div>

          <h1 className="landing-v2-title">
            <span className="landing-v2-title-em">把想法 / 材料给 AI</span><br />
            整理成设计文档，直进 Builder
          </h1>
          <p className="landing-v2-sub">
            支持&nbsp;PDF / Word / Excel / 截图 / .md，单&nbsp;.md 直接走 Builder 秒级生成。
          </p>

          {/* Mode picker pills — hidden when role has only one mode */}
          {!singleMode && (
            <div className="landing-v2-modes" role="tablist">
              {visibleModes.map(m => {
                const Ic = m.icon === 'whale' ? WhaleGlyph : m.icon === 'code' ? CodeGlyph : ChatGlyph;
                return (
                  <button
                    key={m.key}
                    role="tab"
                    aria-selected={mode === m.key}
                    className={`landing-v2-mode landing-v2-mode-${m.tone} ${mode === m.key ? 'is-active' : ''}`}
                    onClick={() => setMode(m.key)}
                  >
                    <span className="landing-v2-mode-icon"><Ic /></span>
                    <span className="landing-v2-mode-label">{m.label}</span>
                    <span className="landing-v2-mode-tagline">{m.tagline}</span>
                    {mode === m.key && <span className="landing-v2-mode-dot" aria-hidden="true" />}
                  </button>
                );
              })}
            </div>
          )}

          {/* Composer card — content swaps with selected mode */}
          <div className={`landing-v2-composer landing-v2-composer-${cur.tone}`}>
            <div className="landing-v2-composer-head">
              <span className="landing-v2-composer-head-icon">
                {cur.key === 'chat' ? <ChatGlyph /> : cur.key === 'whale' ? <WhaleGlyph /> : <CodeGlyph />}
              </span>
              <span className="landing-v2-composer-head-label">{cur.label}</span>
              <span className="landing-v2-composer-head-sep">·</span>
              <span className="landing-v2-composer-head-tagline">{cur.tagline}</span>
              <span className="landing-v2-composer-head-tip">{cur.tip}</span>
            </div>

            <textarea
              className="landing-v2-composer-input"
              placeholder={cur.placeholder}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send(); }}
              rows={4}
            />

            <div className="landing-v2-composer-foot">
              <div className="landing-v2-composer-tools">
                <button className="landing-v2-tool" title="附加附件">
                  <I.paperclip size={13} />
                  <span>附加附件</span>
                </button>
                <button className="landing-v2-tool" title="上传文档" onClick={() => navigate('/chat')}>
                  <I.upload size={13} />
                  <span>上传文档</span>
                </button>
                {cur.key !== 'vibe' && (
                  <button className="landing-v2-tool" title="引用项目" onClick={() => navigate('/apps')}>
                    <I.apps size={13} />
                    <span>引用项目</span>
                  </button>
                )}
                <button className="landing-v2-tool" title="文档模板" onClick={() => navigate('/templates')}>
                  <I.doc size={13} />
                  <span>文档模板</span>
                </button>
                {cur.key === 'whale' && (
                  <button className="landing-v2-tool" title="选择 MCP" onClick={() => navigate('/mcp')}>
                    <I.layers size={13} />
                    <span>选择 MCP</span>
                  </button>
                )}
              </div>
              <button className={`landing-v2-go landing-v2-go-${cur.tone}`} onClick={send}>
                <I.arrowRight size={12} />
                <span>{cur.cta}</span>
                <span className="landing-v2-go-kbd">⌘↵</span>
              </button>
            </div>
          </div>
        </div>

        {/* ─── Hero relationship diagram (full-flow story) ─── */}
        <div className="landing-flow-diagram">
          {[
            { icon: 'chat',     b: '描述需求',    s: '睿鲸 AI Builder 对话', tone: 'ai' },
            { icon: 'doc',      b: '生成 SPEC',   s: '设计文档自动累积版本', tone: 'brand' },
            { icon: 'industry', b: '复用行业沉淀', s: '可选 · 一键采用最佳实践', tone: 'amber' },
            { icon: 'rocket',   b: '部署上线',    s: '到 dev / test / prod', tone: 'emerald' },
          ].map((s, i, arr) => {
            const Ic = window.I[s.icon];
            return (
              <React.Fragment key={i}>
                <div className={`landing-flow-step ${s.tone}`}>
                  <div className="landing-flow-step-icon"><Ic size={12} /></div>
                  <b>{s.b}</b>
                  <span>{s.s}</span>
                </div>
                {i < arr.length - 1 && <div className="landing-flow-arrow"><I.arrowRight size={14} /></div>}
              </React.Fragment>
            );
          })}
        </div>

        {/* ─── Below the fold: condensed strip ─── */}
        <div className="landing-v2-strip">
          <div className="landing-v2-strip-stats">
            {[
              { label: '已搭建应用', v: 12, sub: '+2 本周' },
              { label: '本月对话', v: 84, sub: '+18%' },
              { label: '已生成模块', v: 263, sub: '模型 / 表单 / 流程' },
              { label: 'AI Coding', v: 4, sub: '1 个进行中' },
            ].map(s => (
              <div key={s.label} className="landing-v2-stat">
                <div className="landing-v2-stat-label">{s.label}</div>
                <div className="landing-v2-stat-row">
                  <div className="landing-v2-stat-v">{s.v}</div>
                  <div className="landing-v2-stat-sub">{s.sub}</div>
                </div>
              </div>
            ))}
          </div>

          <div className="landing-v2-recent">
            <div className="landing-v2-recent-head">
              <span className="landing-v2-recent-title">最近的应用</span>
              <button className="landing-v2-recent-all" onClick={() => navigate('/apps')}>
                查看全部 <I.arrowRight size={11} />
              </button>
            </div>
            <div className="landing-v2-recent-list">
              {recent.map(a => (
                <button key={a.id} className="landing-v2-recent-item" onClick={() => navigate('/chat?app=' + a.id)}>
                  <div className={`landing-app-icon tone-${a.color}`} style={{ width: 28, height: 28, borderRadius: 7, fontSize: 12 }}>{a.name.slice(0, 1)}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="landing-v2-recent-name truncate">{a.name}</div>
                    <div className="landing-v2-recent-meta">
                      <span className="mono">{a.code}</span>
                      <span>·</span>
                      <span>{a.updatedAt.slice(5)}</span>
                    </div>
                  </div>
                  <StatusBadge status={a.status} />
                </button>
              ))}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}

/* ─── Mode glyphs (custom small icons that match the reference) ─── */
function ChatGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <path d="M14 8a6 6 0 0 1-9 5.2L2 14l1-3A6 6 0 1 1 14 8z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}
function WhaleGlyph() {
  // Stylized braces — matches the {} icon in reference
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
      <path d="M5 2c-1.5 0-2 1-2 2v3l-1.2 1L3 9v3c0 1 .5 2 2 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M11 2c1.5 0 2 1 2 2v3l1.2 1L13 9v3c0 1-.5 2-2 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function CodeGlyph() {
  // Stylized </>
  return (
    <svg width="15" height="14" viewBox="0 0 16 16" fill="none">
      <path d="m6 4-4 4 4 4M10 4l4 4-4 4M8.5 3l-1 10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

window.Landing = Landing;
