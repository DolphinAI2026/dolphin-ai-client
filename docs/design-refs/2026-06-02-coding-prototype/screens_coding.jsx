/* screens_coding.jsx — AI Coding: handoff → dialogue + live preview → online IDE */
const { useState: useStateC, useEffect: useEffectC, useRef: useRefC } = React;

// Kanban live preview (the artifact being built)
function KanbanPreview({ withCards, hot }) {
  const cols = ['初步接洽', '方案报价', '谈判', '赢单'];
  const data = window.KANBAN_CARDS;
  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-app)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px', borderBottom: '1px solid var(--line)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <span style={{ width: 28, height: 28, borderRadius: 8, display: 'grid', placeItems: 'center', background: 'var(--blue-950)', color: '#fff' }}><Icon name="grid2" size={15} stroke={2} /></span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, whiteSpace: 'nowrap' }}>商机看板 · 实时预览</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>OpportunityBoard.vue</div>
          </div>
        </div>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: 'var(--brand)', padding: '4px 9px', borderRadius: 999, background: 'var(--brand-soft)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', flexShrink: 0 }}><Icon name="bolt" size={12} stroke={2.2} /> hot-reload</span>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 16 }}>
        {!withCards ? (
          <div style={{ height: '100%', display: 'grid', placeItems: 'center', color: 'var(--text-4)', fontSize: 13 }}>
            <div style={{ textAlign: 'center', whiteSpace: 'nowrap' }}><Icon name="terminal" size={32} style={{ margin: '0 auto 10px', opacity: 0.5 }} />等待生成组件…</div>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, minWidth: 560 }}>
            {cols.map(col => (
              <div key={col} style={{ background: 'var(--surface-2)', borderRadius: 12, border: '1px solid var(--line)', display: 'flex', flexDirection: 'column' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 11px', borderBottom: '1px solid var(--line-2)' }}>
                  <span style={{ fontSize: 11.5, fontWeight: 700, color: col === '赢单' ? 'var(--ok)' : 'var(--text-2)' }}>{col}</span>
                  <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-4)' }}>{(data[col] || []).length}</span>
                </div>
                <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 8, minHeight: 60 }}>
                  {(data[col] || []).map((c, i) => {
                    const showHot = hot && c.hot;
                    return (
                      <div key={i} style={{ background: 'var(--surface)', borderRadius: 9, border: showHot ? '1.5px solid var(--brand)' : '1px solid var(--line)', padding: 10, boxShadow: 'var(--sh-1)', position: 'relative', cursor: 'grab' }}>
                        <div style={{ position: 'absolute', top: 7, right: 7, color: 'var(--text-4)' }}><Icon name="drag" size={12} /></div>
                        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, paddingRight: 14, lineHeight: 1.35 }}>{c.name}</div>
                        {hot && <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ fontSize: 10.5, color: 'var(--text-3)' }}>{c.cust}</span>
                          <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)', color: c.hot ? 'var(--err)' : 'var(--text-2)', whiteSpace: 'nowrap', flexShrink: 0 }}>{c.amt}</span>
                        </div>}
                        {showHot && <div style={{ position: 'absolute', top: -8, left: 8, fontSize: 9, fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#fff', background: 'var(--err)', padding: '1px 6px', borderRadius: 999 }}>≥50万</div>}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function CodingMsg({ m }) {
  if (m.who === 'sys') {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 18 }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 11.5, color: 'var(--brand)', padding: '7px 13px', borderRadius: 999, background: 'var(--brand-soft)', border: '1px solid var(--brand-soft-2)', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>
          <Icon name="layers" size={13} stroke={2} /> {m.text}
        </div>
      </div>
    );
  }
  if (m.who === 'user') {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 18 }}>
        <div style={{ maxWidth: '82%', background: 'var(--blue-950)', color: '#fff', padding: '11px 15px', borderRadius: '14px 14px 4px 14px', fontSize: 13.5, lineHeight: 1.6, boxShadow: 'var(--sh-3)' }}>{m.text}</div>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', gap: 11, marginBottom: 18 }}>
      <div style={{ width: 30, height: 30, borderRadius: 9, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'var(--blue-950)', color: '#fff' }}><Icon name="coding" size={16} stroke={2.2} /></div>
      <div style={{ maxWidth: '86%' }}>
        <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', padding: '12px 15px', borderRadius: '14px 14px 14px 4px', fontSize: 13.5, lineHeight: 1.65, boxShadow: 'var(--sh-1)' }}>
          {m.kind === 'update' && <div style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10.5, fontWeight: 700, color: 'var(--brand)', marginBottom: 7, fontFamily: 'var(--font-mono)' }}><Icon name="bolt" size={12} stroke={2.2} />已更新代码 + 预览</div>}
          <div>{m.text}</div>
          {m.chips && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 11 }}>
            {m.chips.map(c => <span key={c} style={{ fontSize: 11, fontWeight: 500, color: 'var(--brand)', padding: '4px 9px', borderRadius: 7, background: 'var(--brand-soft)', border: '1px solid var(--brand-soft-2)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>{c}</span>)}
          </div>}
        </div>
      </div>
    </div>
  );
}

function CodingScreen({ go, fromHandoff }) {
  const [phase, setPhase] = useStateC(fromHandoff ? 'chat' : 'entry'); // entry | chat | ide
  const [count, setCount] = useStateC(fromHandoff ? 2 : 0);
  const [typing, setTyping] = useStateC(false);
  const scrollRef = useRefC(null);
  const chat = window.CODING_CHAT;

  useEffectC(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [count, typing]);
  useEffectC(() => {
    if (fromHandoff) { setTyping(true); const t = setTimeout(() => { setTyping(false); setCount(3); }, 1200); return () => clearTimeout(t); }
  }, []);

  function advance() {
    const next = count;
    if (next >= chat.length) { setPhase('ide'); return; }
    setCount(next + 1);
    if (chat[next + 1] && chat[next + 1].who === 'ai') {
      setTyping(true);
      setTimeout(() => { setTyping(false); setCount(next + 2); }, 1100);
    }
  }

  const pendingUser = phase === 'chat' && !typing && count < chat.length && chat[count] && chat[count].who === 'user' ? chat[count] : null;
  const allDone = phase === 'chat' && count >= chat.length;

  if (phase === 'entry') return <CodingEntry go={go} onSubmit={() => { setPhase('chat'); setCount(2); setTyping(true); setTimeout(() => { setTyping(false); setCount(3); }, 1200); }} />;
  if (phase === 'ide') return <CodingIDE go={go} />;

  // chat
  const hot = count >= 5; // after the highlight reply
  const withCards = count >= 3;
  return (
    <div className="code-scope" style={{ display: 'flex', height: '100%', minHeight: 0, background: 'var(--bg)' }}>
      <div style={{ width: '42%', minWidth: 380, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--line)', background: 'var(--surface-2)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 20px', borderBottom: '1px solid var(--line)' }}>
          <ModuleTag mod="coding" />
          <span style={{ fontSize: 12.5, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>定制开发 · 商机看板</span>
        </div>
        {/* context banner */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '9px 20px', background: 'var(--brand-soft)', borderBottom: '1px solid var(--brand-soft-2)', fontSize: 11.5 }}>
          <Icon name="layers" size={14} style={{ color: 'var(--brand)', flexShrink: 0 }} />
          <span style={{ color: 'var(--brand)', fontWeight: 600, fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>上下文 · 销售 CRM</span>
          <span style={{ color: 'var(--text-3)', whiteSpace: 'nowrap' }}>4 模型 / 1 审批流 / 4 角色</span>
        </div>
        <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '20px 20px 8px' }}>
          {chat.slice(0, count).map((m, i) => <CodingMsg key={i} m={m} />)}
          {typing && <div style={{ display: 'flex', gap: 11, marginBottom: 18 }}><div style={{ width: 30, height: 30, borderRadius: 9, display: 'grid', placeItems: 'center', background: 'var(--blue-950)', color: '#fff', flexShrink: 0 }}><Icon name="coding" size={16} stroke={2.2} /></div><div style={{ background: 'var(--surface)', border: '1px solid var(--line)', padding: '14px 16px', borderRadius: '14px 14px 14px 4px', display: 'flex', gap: 5 }}>{[0, 1, 2].map(i => <span key={i} style={{ width: 7, height: 7, borderRadius: 999, background: 'var(--brand)', opacity: 0.5, animation: `rj-bounce 1.2s ${i * 0.15}s infinite` }} />)}</div></div>}
        </div>
        <div style={{ padding: '12px 20px 18px', borderTop: '1px solid var(--line)' }}>
          {allDone ? (
            <Btn kind="dark" mono size="lg" iconR="arrowR" onClick={() => setPhase('ide')} style={{ width: '100%' }}>在 IDE 中查看代码与预览</Btn>
          ) : (
            <div style={{ background: 'var(--surface)', border: '1px solid var(--line-strong)', borderRadius: 14, padding: 12, boxShadow: 'var(--sh-2)' }}>
              <div style={{ fontSize: 13.5, lineHeight: 1.55, color: pendingUser ? 'var(--text-2)' : 'var(--text-4)', minHeight: 40, padding: '2px 4px', fontFamily: pendingUser ? 'inherit' : 'var(--font-mono)' }}>
                {pendingUser ? pendingUser.text : (typing ? '睿鲸正在写代码…' : '继续描述定制需求…')}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}><Icon name="coding" size={14} /> 对话即写码</div>
                <Btn kind="dark" mono size="sm" iconR="send" disabled={!pendingUser} onClick={advance}>发送</Btn>
              </div>
            </div>
          )}
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}><KanbanPreview withCards={withCards} hot={hot} /></div>
    </div>
  );
}

function CodingEntry({ go, onSubmit }) {
  const [emode, setEmode] = useStateC('bound');
  const bound = emode === 'bound';
  const examples = bound
    ? ['给销售 CRM 加一个拖拽换阶段的商机看板', '商机详情页加一个回款计划子表', '客户列表加一个高级筛选侧栏']
    : ['多选 + 异步加载的客户树组件', 'OCR 识别的发票上传卡片', '带倒计时的 SLA 状态条'];
  return (
    <div className="code-scope" style={{ height: '100%', overflowY: 'auto', background: 'var(--bg-app)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 40 }}>
      <div style={{ width: 'min(100%, 760px)' }}>
        <div style={{ textAlign: 'center', marginBottom: 26 }}>
          <div style={{ width: 60, height: 60, borderRadius: 16, margin: '0 auto 18px', display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, var(--blue-800), var(--blue-950))', boxShadow: 'var(--sh-brand-lg)' }}><Icon name="coding" size={30} stroke={2.2} style={{ color: '#fff' }} /></div>
          <div style={{ display: 'inline-flex', marginBottom: 14 }}><ModuleTag mod="coding" /></div>
          <h1 style={{ fontSize: 34, fontWeight: 700, letterSpacing: '-0.02em', margin: '6px 0 10px', fontFamily: 'var(--font-mono)' }}>配置装不下的，写代码搞定</h1>
          <p style={{ fontSize: 15, color: 'var(--text-2)', lineHeight: 1.6, maxWidth: 560, margin: '0 auto' }}>在已有应用上做定制页面、可复用组件、复杂接口。对话即生成代码，配在线 IDE 实时预览，产物可装回应用、跨应用复用。</p>
        </div>

        {/* entry mode: app-bound customization vs standalone reusable component */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 12 }}>
          {[{ id: 'bound', ic: 'building', t: '在应用上定制', d: '绑定一个已有应用 · 复用其模型与接口' }, { id: 'lib', ic: 'box', t: '做通用组件', d: '不绑应用 · 进自开发资产库跨应用复用' }].map(o => {
            const on = emode === o.id;
            return (
              <button key={o.id} onClick={() => setEmode(o.id)} style={{ textAlign: 'left', cursor: 'pointer', padding: '12px 14px', borderRadius: 12, fontFamily: 'inherit',
                background: on ? 'var(--brand-soft)' : 'var(--surface)', border: '1.5px solid', borderColor: on ? 'var(--brand)' : 'var(--line-strong)', transition: 'all .15s var(--ease)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                  <span style={{ width: 26, height: 26, borderRadius: 7, display: 'grid', placeItems: 'center', background: on ? 'var(--blue-950)' : 'var(--surface-3)', color: on ? '#fff' : 'var(--text-3)' }}><Icon name={o.ic} size={14} stroke={2} /></span>
                  <span style={{ fontSize: 13.5, fontWeight: 700, color: on ? 'var(--brand)' : 'var(--text)' }}>{o.t}</span>
                  {on && <Icon name="check" size={14} stroke={2.6} style={{ marginLeft: 'auto', color: 'var(--brand)' }} />}
                </div>
                <div style={{ fontSize: 11.5, color: 'var(--text-3)', lineHeight: 1.45, paddingLeft: 34 }}>{o.d}</div>
              </button>
            );
          })}
        </div>

        {/* target row reactive */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, padding: '11px 14px', background: 'var(--surface)', border: '1px solid var(--line-strong)', borderRadius: 12, boxShadow: 'var(--sh-1)' }}>
          <span style={{ fontSize: 11.5, color: 'var(--text-3)', fontWeight: 600, fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>{bound ? '目标应用' : '产物去向'}</span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 12.5, fontWeight: 600, color: 'var(--brand)', padding: '5px 11px', borderRadius: 999, background: 'var(--brand-soft)', whiteSpace: 'nowrap' }}><Icon name={bound ? 'building' : 'store'} size={13} /> {bound ? '销售 CRM' : '自开发资产库'}</span>
          <span style={{ fontSize: 11.5, color: 'var(--text-4)', whiteSpace: 'nowrap' }}>{bound ? '复用其模型 / 接口 / 枚举' : '跨应用复用，可装进任意应用'}</span>
          <Icon name="chevD" size={14} style={{ marginLeft: 'auto', color: 'var(--text-4)' }} />
        </div>

        <div style={{ background: 'var(--surface)', border: '1px solid var(--line-strong)', borderRadius: 18, padding: 18, boxShadow: 'var(--sh-4)' }}>
          <textarea placeholder={bound ? '描述要做的定制页面或组件。例：给商机做一个按阶段分列、卡片可拖拽换阶段的看板，拖到「赢单」时弹确认框。' : '描述一个通用组件。例：一个支持多选 + 异步加载的客户树组件，可在任意应用里引用。'}
            style={{ width: '100%', minHeight: 90, border: 'none', outline: 'none', resize: 'none', fontFamily: 'var(--font-mono)', fontSize: 14, lineHeight: 1.65, color: 'var(--text)', background: 'transparent' }} />
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12.5, color: 'var(--text-3)', fontWeight: 500, fontFamily: 'var(--font-mono)' }}><Icon name="terminal" size={15} /> {bound ? '复用应用已有模型 / 接口' : '零依赖 · 可跨应用复用'}</div>
            <Btn kind="dark" mono iconR="send" onClick={onSubmit}>开始开发</Btn>
          </div>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center', marginTop: 18 }}>
          {examples.map(ex => <button key={ex} onClick={onSubmit} style={{ fontSize: 12, color: 'var(--text-2)', padding: '8px 13px', borderRadius: 999, background: 'var(--surface)', border: '1px solid var(--line)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{ex}</button>)}
        </div>
      </div>
    </div>
  );
}

// Online IDE workbench
function CodingIDE({ go }) {
  const [active, setActive] = useStateC('pages/OpportunityBoard.vue');
  const [install, setInstall] = useStateC(false);
  const code = window.CODING_CODE;
  const lines = code.split('\n');
  return (
    <div className="code-scope" style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg)' }}>
      {/* IDE topbar */}
      <div style={{ height: 46, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 12, padding: '0 18px', borderBottom: '1px solid var(--line)', background: 'var(--surface-2)' }}>
        <ModuleTag mod="coding" size="sm" />
        <span style={{ fontSize: 12.5, fontWeight: 600, fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>商机看板</span>
        <span style={{ fontSize: 11, color: 'var(--text-3)', display: 'inline-flex', alignItems: 'center', gap: 5, whiteSpace: 'nowrap' }}><Icon name="building" size={12} /> 销售 CRM</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <Btn kind="ghost" size="sm" icon="play" mono>预览</Btn>
          <Btn kind="primary" size="sm" icon="store" onClick={() => setInstall(true)}>装回应用</Btn>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {/* file tree */}
        <div style={{ width: 220, flexShrink: 0, borderRight: '1px solid var(--line)', background: 'var(--surface-2)', padding: '12px 8px', overflowY: 'auto' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.08em', padding: '4px 8px 8px', fontFamily: 'var(--font-mono)' }}>资源管理器</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', fontSize: 11.5, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}><Icon name="chevD" size={12} /> sales_crm/</div>
          {window.CODING_FILES.map(f => {
            const on = active === f.path;
            return (
              <button key={f.path} onClick={() => setActive(f.path)} style={{ display: 'flex', alignItems: 'center', gap: 7, width: '100%', padding: '6px 8px 6px 20px', borderRadius: 7, border: 'none', cursor: 'pointer', textAlign: 'left',
                background: on ? 'var(--brand-soft)' : 'transparent', color: on ? 'var(--brand)' : 'var(--text-2)', fontFamily: 'var(--font-mono)', fontSize: 11.5, fontWeight: on ? 600 : 400 }}>
                <Icon name="doc" size={13} />
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.path.split('/').pop()}</span>
                {f.badge && <span style={{ fontSize: 9, fontWeight: 700, padding: '0 4px', borderRadius: 4, background: f.badge === 'new' ? 'var(--ok-soft)' : 'var(--warn-soft)', color: f.badge === 'new' ? 'var(--ok)' : 'var(--warn)' }}>{f.badge === 'new' ? 'U' : 'M'}</span>}
              </button>
            );
          })}
        </div>

        {/* editor (dark code surface) */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--code-bg)' }}>
          <div style={{ display: 'flex', alignItems: 'center', height: 36, borderBottom: '1px solid var(--code-line)', padding: '0 4px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, height: 28, padding: '0 12px', borderRadius: 7, background: 'var(--code-bg-2)', color: 'var(--code-text)', fontSize: 11.5, fontFamily: 'var(--font-mono)', margin: '0 4px' }}>
              <Icon name="doc" size={12} style={{ color: 'var(--blue-400)' }} /> OpportunityBoard.vue
              <span style={{ width: 6, height: 6, borderRadius: 999, background: 'var(--blue-400)', marginLeft: 4 }} />
            </div>
          </div>
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '14px 0', fontFamily: 'var(--font-mono)', fontSize: 12.5, lineHeight: 1.7 }}>
            {lines.map((ln, i) => (
              <div key={i} style={{ display: 'flex', minHeight: 21 }}>
                <span style={{ width: 44, flexShrink: 0, textAlign: 'right', paddingRight: 14, color: 'var(--code-dim)', userSelect: 'none' }}>{i + 1}</span>
                <span style={{ color: 'var(--code-text)', whiteSpace: 'pre', paddingRight: 20 }} dangerouslySetInnerHTML={{ __html: hl(ln) }} />
              </div>
            ))}
          </div>
          {/* terminal strip */}
          <div style={{ height: 76, flexShrink: 0, borderTop: '1px solid var(--code-line)', background: 'var(--code-bg)', padding: '8px 14px', fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--code-dim)', overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, color: 'var(--code-text)' }}><Icon name="terminal" size={13} style={{ color: 'var(--blue-400)' }} /> 终端</div>
            <div style={{ color: 'var(--blue-300)' }}>$ vite build --watch</div>
            <div><span style={{ color: 'var(--ok)' }}>✓</span> 编译完成 · OpportunityBoard 已热更新 (212ms)</div>
          </div>
        </div>

        {/* live preview */}
        <div style={{ width: '38%', minWidth: 360, flexShrink: 0, borderLeft: '1px solid var(--line)' }}>
          <KanbanPreview withCards hot />
        </div>
      </div>
      {install && <InstallModal onClose={() => setInstall(false)} onConfirm={() => { setInstall(false); go('catalog'); }} />}
    </div>
  );
}

// 装回应用 confirmation — closes the Coding→app loop
function InstallModal({ onClose, onConfirm }) {
  const rows = [
    { ic: 'doc', t: '应用页面', d: 'OpportunityBoard.vue → 挂在「商机」模块菜单下' },
    { ic: 'flow', t: '路由', d: '/sales_crm/opportunity/board' },
    { ic: 'lock', t: '权限', d: '沿用应用现有 4 个角色的数据范围' },
    { ic: 'store', t: '资产登记', d: '同时登记到自开发资产库 · 可跨应用复用' },
  ];
  return (
    <div className="code-scope" onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 90, background: 'rgba(8,16,36,0.55)', backdropFilter: 'blur(6px)', display: 'grid', placeItems: 'center', animation: 'rj-fade .18s' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 'min(92%, 480px)', background: 'var(--surface)', borderRadius: 18, boxShadow: 'var(--sh-5)', overflow: 'hidden', animation: 'rj-pop .25s var(--ease-spring)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '18px 20px', borderBottom: '1px solid var(--line)' }}>
          <span style={{ width: 40, height: 40, borderRadius: 11, display: 'grid', placeItems: 'center', background: 'var(--blue-950)', color: '#fff', flexShrink: 0 }}><Icon name="store" size={20} stroke={2} /></span>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: '-0.01em' }}>装回应用</div>
            <div style={{ fontSize: 11.5, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', marginTop: 2 }}>商机看板 → 销售 CRM</div>
          </div>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 600, color: 'var(--ok)', padding: '4px 9px', borderRadius: 999, background: 'var(--ok-soft)', whiteSpace: 'nowrap', flexShrink: 0 }}><Icon name="check" size={12} stroke={2.6} /> 编译通过</span>
        </div>
        <div style={{ padding: 16 }}>
          {rows.map(r => (
            <div key={r.t} style={{ display: 'flex', alignItems: 'flex-start', gap: 11, padding: '9px 8px' }}>
              <span style={{ width: 26, height: 26, borderRadius: 7, display: 'grid', placeItems: 'center', flexShrink: 0, background: 'var(--brand-soft)', color: 'var(--brand)' }}><Icon name={r.ic} size={14} stroke={2} /></span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>{r.t}</div>
                <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 1, lineHeight: 1.45 }}>{r.d}</div>
              </div>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 10, padding: '0 20px 20px', justifyContent: 'flex-end' }}>
          <Btn kind="ghost" size="sm" onClick={onClose}>取消</Btn>
          <Btn kind="dark" mono size="sm" icon="check" onClick={onConfirm}>确认装回</Btn>
        </div>
      </div>
    </div>
  );
}

// tiny syntax highlighter for the mock code
function hl(line) {
  let s = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  s = s.replace(/(\/\/.*)$/g, '<span style="color:#6F80AC">$1</span>');
  s = s.replace(/\b(import|from|const|ref|async|await|function|return|if)\b/g, '<span style="color:#93C5FD">$1</span>');
  s = s.replace(/('[^']*')/g, '<span style="color:#7DD3A8">$1</span>');
  s = s.replace(/(@\/[\w\/]+)/g, '<span style="color:#7DD3A8">$1</span>');
  return s;
}

Object.assign(window, { CodingScreen });
