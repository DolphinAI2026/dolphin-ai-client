// Landing — AI hub centered layout (matches the user's reference).
// Current-product picker (AI Builder / AI Coding) + unified composer.
// Below the hero: condensed stats + recent apps.

function Landing() {
  const { navigate } = useContext(RouteCtx);

  const MODES = [
    {
      key: 'chat',
      icon: 'chat',
      label: 'AI Builder',
      tagline: '需求到应用',
      placeholder: '描述你想做的应用，或把材料拖进来…\n比如：搭建一个客户工单系统，工单流转 + SLA 看板 + 客户回访。',
      cta: '开始构建',
      target: '/chat?mode=requirements',
      tone: 'brand',
      tip: '从需求识别、结构梳理到应用搭建，一次完成。',
    },
    {
      key: 'whale',
      icon: 'whale',
      label: 'AI Coding',
      tagline: '低代码扩展',
      placeholder: '描述你需要的低代码组件 / 页面 / 后端接口，AI 会按 aPaaS 规范并行生成并发布…\n比如：生成一个差旅报销表单，包含申请人、目的地、明细子表、附件上传。',
      cta: '开始生成',
      target: '/coding',
      tone: 'brand',
      tip: '不写代码：聊→生成 UMD 包→发布到组件市场→在表单设计器拖拽即可用。',
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

          <div className="landing-v2-eyebrow">RUIJING&nbsp; AI&nbsp; · &nbsp; BUILDER&nbsp;+&nbsp; CODING</div>

          <h1 className="landing-v2-title">
            <span className="landing-v2-title-em">把想法交给睿鲸AI</span><br />
            自动构建可上线应用
          </h1>
          <p className="landing-v2-sub">
            支持&nbsp;PDF / Word / Excel / 截图 / .md，单&nbsp;.md 直接走 AI Builder 秒级生成。
          </p>

          {/* Mode picker pills — hidden when role has only one mode */}
          {!singleMode && (
            <div className="landing-v2-modes" role="tablist">
              {visibleModes.map(m => {
                const Ic = m.icon === 'whale' ? WhaleGlyph : m.icon === 'doc' ? I.doc : ChatGlyph;
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
                <button className="landing-v2-tool" title="引用项目" onClick={() => navigate('/apps')}>
                  <I.apps size={13} />
                  <span>引用项目</span>
                </button>
                <button className="landing-v2-tool" title="文档模板" onClick={() => navigate('/templates')}>
                  <I.doc size={13} />
                  <span>文档模板</span>
                </button>
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
            { icon: 'chat',     b: '描述需求',    s: '业务目标与材料', tone: 'brand' },
            { icon: 'doc',      b: '构建应用',    s: '页面 / 表单 / 流程', tone: 'brand' },
            { icon: 'mcp',      b: '调用 MCP',    s: '后端工具补齐配置', tone: 'amber' },
            { icon: 'rocket',   b: '部署上线',    s: '使用平台管理中的环境', tone: 'emerald' },
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
