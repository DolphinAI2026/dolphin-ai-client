/* screens_builder.jsx — AI Builder: entry → dialogue + live preview → generate */
const { useState: useStateB, useEffect: useEffectB, useRef: useRefB } = React;

// ── Right preview: 4 config tabs ────────────────────────────────
function PreviewTabs({ phase }) {
  const [tab, setTab] = useStateB('model');
  const updated = phase >= 4; // 商机阶段 + 金额分支 已加入
  const TABS = [
    { id: 'model', label: '数据模型', icon: 'layers', n: 4 },
    { id: 'form', label: '表单', icon: 'doc', n: null },
    { id: 'flow', label: '流程', icon: 'branch', n: updated ? 5 : 4 },
    { id: 'perm', label: '权限', icon: 'lock', n: 4 },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <span style={{ width: 28, height: 28, borderRadius: 8, display: 'grid', placeItems: 'center', background: 'var(--brand-soft)', color: 'var(--brand)' }}><Icon name="grid2" size={16} stroke={2} /></span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, letterSpacing: '-0.01em', whiteSpace: 'nowrap' }}>销售 CRM · 结构预览</div>
            <div style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>app_code: sales_crm</div>
          </div>
        </div>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: 'var(--ok)', padding: '4px 9px', borderRadius: 999, background: 'var(--ok-soft)', whiteSpace: 'nowrap', flexShrink: 0 }}>
          <span style={{ width: 6, height: 6, borderRadius: 999, background: 'var(--ok)', animation: 'rj-pulse 1.6s infinite' }} /> 实时同步
        </span>
      </div>

      <div style={{ display: 'flex', gap: 4, padding: '14px 18px 0' }}>
        {TABS.map(t => {
          const on = tab === t.id;
          return (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              display: 'flex', alignItems: 'center', gap: 7, height: 34, padding: '0 13px', borderRadius: 9, cursor: 'pointer', fontFamily: 'inherit',
              fontSize: 12.5, fontWeight: on ? 600 : 500, border: '1px solid', borderColor: on ? 'var(--brand-soft-2)' : 'transparent',
              color: on ? 'var(--brand)' : 'var(--text-3)', background: on ? 'var(--brand-soft)' : 'transparent', transition: 'all .14s', whiteSpace: 'nowrap', flexShrink: 0,
            }}>
              <Icon name={t.icon} size={14} stroke={on ? 2 : 1.7} />{t.label}
              {t.n != null && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, padding: '1px 5px', borderRadius: 999, background: on ? 'var(--brand-soft-2)' : 'var(--surface-3)', color: on ? 'var(--brand)' : 'var(--text-4)' }}>{t.n}</span>}
            </button>
          );
        })}
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 18 }}>
        {tab === 'model' && <ModelView updated={updated} />}
        {tab === 'form' && <FormView updated={updated} />}
        {tab === 'flow' && <FlowView updated={updated} />}
        {tab === 'perm' && <PermView />}
      </div>
    </div>
  );
}

function ModelView({ updated }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
      {window.CRM_MODELS.map(m => (
        <div key={m.code} style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 12, overflow: 'hidden', boxShadow: 'var(--sh-1)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '11px 13px', borderBottom: '1px solid var(--line-2)', background: m.primary ? 'var(--brand-soft)' : 'var(--surface-2)' }}>
            <span style={{ width: 24, height: 24, borderRadius: 7, display: 'grid', placeItems: 'center', background: m.primary ? 'var(--brand)' : 'var(--surface)', color: m.primary ? '#fff' : 'var(--brand)', border: m.primary ? 'none' : '1px solid var(--line)' }}><Icon name={m.icon} size={14} stroke={2} /></span>
            <span style={{ fontSize: 13, fontWeight: 700 }}>{m.name}</span>
            <span style={{ marginLeft: 'auto', fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--text-4)', whiteSpace: 'nowrap', flexShrink: 0 }}>{m.count} 字段</span>
          </div>
          <div style={{ padding: '6px 8px' }}>
            {m.fields.map(f => {
              const hot = f.hl && updated;
              return (
                <div key={f.code} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 7px', borderRadius: 7, background: hot ? 'var(--brand-soft)' : 'transparent', transition: 'background .3s' }}>
                  <span style={{ fontSize: 12, fontWeight: 500, color: hot ? 'var(--brand)' : 'var(--text)' }}>{f.name}</span>
                  {f.req && <span style={{ fontSize: 9, color: 'var(--err)' }}>*</span>}
                  {hot && <span style={{ fontSize: 9, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--brand)', padding: '0 5px', borderRadius: 999, background: 'var(--surface)', border: '1px solid var(--brand-soft-2)' }}>NEW</span>}
                  <span style={{ marginLeft: 'auto', fontSize: 10.5, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', flexShrink: 0 }}>{f.type}</span>
                </div>
              );
            })}
            {m.fields.length < m.count && <div style={{ fontSize: 10.5, color: 'var(--text-4)', padding: '5px 7px' }}>+{m.count - m.fields.length} 个字段…</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

function FormView({ updated }) {
  const fld = (label, el, hot) => (
    <div style={{ marginBottom: 14, padding: hot ? 8 : 0, borderRadius: 9, background: hot ? 'var(--brand-soft)' : 'transparent', transition: 'background .3s' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: hot ? 'var(--brand)' : 'var(--text-2)', marginBottom: 6 }}>{label}{hot && <span style={{ fontSize: 9, fontWeight: 700, fontFamily: 'var(--font-mono)', padding: '0 5px', borderRadius: 999, background: 'var(--surface)', border: '1px solid var(--brand-soft-2)' }}>NEW</span>}</div>
      {el}
    </div>
  );
  const input = (ph) => <div style={{ height: 38, borderRadius: 9, border: '1px solid var(--line-strong)', background: 'var(--surface)', display: 'flex', alignItems: 'center', padding: '0 12px', fontSize: 12.5, color: 'var(--text-4)' }}>{ph}</div>;
  return (
    <div style={{ maxWidth: 480, margin: '0 auto' }}>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 14, padding: 22, boxShadow: 'var(--sh-2)' }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>新建商机</div>
        <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginBottom: 18, fontFamily: 'var(--font-mono)' }}>表单由「商机」模型自动装配</div>
        {fld('商机名称 *', input('请输入商机名称'))}
        {fld('关联客户 *', <div style={{ height: 38, borderRadius: 9, border: '1px solid var(--line-strong)', background: 'var(--surface)', display: 'flex', alignItems: 'center', padding: '0 12px', fontSize: 12.5, color: 'var(--text-4)', justifyContent: 'space-between' }}>选择客户<Icon name="search" size={14} /></div>)}
        {fld('阶段 *', (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {window.CRM_STAGES.map((s, i) => <span key={s} style={{ fontSize: 11.5, fontWeight: 500, padding: '6px 11px', borderRadius: 999, border: '1px solid', borderColor: i === 0 ? 'var(--brand)' : 'var(--line-strong)', background: i === 0 ? 'var(--brand-soft)' : 'var(--surface)', color: i === 0 ? 'var(--brand)' : 'var(--text-2)' }}>{s}</span>)}
          </div>
        ), updated)}
        {fld('预计金额 *', input('¥ 0.00'), updated)}
        <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
          <Btn kind="primary" size="sm" style={{ flex: 1 }}>提交</Btn>
          <Btn kind="ghost" size="sm">取消</Btn>
        </div>
      </div>
    </div>
  );
}

function FlowView({ updated }) {
  const steps = window.CRM_PROCESS.filter(s => updated || (s.n !== 3 && s.n !== 4) || s.n === 5).map((s, i, arr) => s);
  const list = updated ? window.CRM_PROCESS : window.CRM_PROCESS.filter(s => s.n !== 3 && s.n !== 4);
  const kindColor = { start: 'var(--ok)', approve: 'var(--brand)', branch: 'var(--warn)', end: 'var(--text-3)' };
  const kindBg = { start: 'var(--ok-soft)', approve: 'var(--brand-soft)', branch: 'var(--warn-soft)', end: 'var(--surface-3)' };
  return (
    <div style={{ maxWidth: 440, margin: '0 auto' }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>商机审批流 {updated && <Badge tone="brand" mono>+ 金额分支</Badge>}</div>
      <div style={{ position: 'relative' }}>
        {list.map((s, i) => {
          const hot = s.hl && updated;
          return (
            <div key={s.n} style={{ display: 'flex', gap: 14, marginBottom: i < list.length - 1 ? 8 : 0 }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <div style={{ width: 38, height: 38, borderRadius: s.kind === 'branch' ? 11 : 999, display: 'grid', placeItems: 'center', flexShrink: 0,
                  background: kindBg[s.kind], color: kindColor[s.kind], border: hot ? '2px solid var(--brand)' : '1px solid var(--line)', fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: 13,
                  boxShadow: hot ? '0 0 0 4px var(--brand-ring)' : 'none', transition: 'all .3s' }}>
                  {s.kind === 'branch' ? <Icon name="branch" size={17} stroke={2} /> : s.kind === 'end' ? <Icon name="check" size={16} stroke={2.4} /> : s.n}
                </div>
                {i < list.length - 1 && <div style={{ width: 2, flex: 1, minHeight: 18, background: 'var(--line-strong)', margin: '4px 0' }} />}
              </div>
              <div style={{ flex: 1, paddingTop: 3, paddingBottom: 8 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, color: hot ? 'var(--brand)' : 'var(--text)', display: 'flex', alignItems: 'center', gap: 7 }}>
                  {s.title}{hot && <span style={{ fontSize: 9, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--brand)', padding: '1px 5px', borderRadius: 999, background: 'var(--brand-soft)' }}>NEW</span>}
                </div>
                <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 2 }}>{s.role}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PermView() {
  const cell = (v) => v === true ? <Icon name="check" size={15} stroke={2.6} style={{ color: 'var(--ok)' }} /> : v === false ? <span style={{ color: 'var(--text-4)' }}>—</span> : <span style={{ fontSize: 11.5, color: 'var(--text-2)' }}>{v}</span>;
  const cols = ['角色', '数据范围', '新建', '编辑', '删除', '审批'];
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 12, overflow: 'hidden', boxShadow: 'var(--sh-1)' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1.2fr 0.7fr 0.9fr 0.7fr 0.7fr', padding: '11px 14px', background: 'var(--surface-2)', borderBottom: '1px solid var(--line)', fontSize: 11, fontWeight: 700, color: 'var(--text-3)', letterSpacing: '0.03em' }}>
        {cols.map(c => <div key={c} style={{ textAlign: c === '角色' || c === '数据范围' ? 'left' : 'center' }}>{c}</div>)}
      </div>
      {window.CRM_PERMS.map((p, i) => (
        <div key={p.role} style={{ display: 'grid', gridTemplateColumns: '1.1fr 1.2fr 0.7fr 0.9fr 0.7fr 0.7fr', padding: '12px 14px', borderBottom: i < 3 ? '1px solid var(--line-2)' : 'none', alignItems: 'center', fontSize: 12.5 }}>
          <div style={{ fontWeight: 600 }}>{p.role}</div>
          <div><span style={{ fontSize: 11, fontWeight: 600, color: 'var(--brand)', padding: '3px 8px', borderRadius: 999, background: 'var(--brand-soft)' }}>{p.scope}</span></div>
          <div style={{ textAlign: 'center' }}>{cell(p.create)}</div>
          <div style={{ textAlign: 'center' }}>{cell(p.edit)}</div>
          <div style={{ textAlign: 'center' }}>{cell(p.del)}</div>
          <div style={{ textAlign: 'center' }}>{cell(p.approve)}</div>
        </div>
      ))}
    </div>
  );
}

// ── Chat side ───────────────────────────────────────────────────
function ChatMessage({ m }) {
  if (m.who === 'user') {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 18 }}>
        <div style={{ maxWidth: '82%', background: 'var(--brand)', color: '#fff', padding: '11px 15px', borderRadius: '14px 14px 4px 14px', fontSize: 13.5, lineHeight: 1.6, boxShadow: 'var(--sh-brand)' }}>{m.text}</div>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', gap: 11, marginBottom: 18 }}>
      <div style={{ width: 30, height: 30, borderRadius: 9, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, var(--blue-600), var(--blue-800))', boxShadow: 'var(--sh-2)' }}><WhaleMark size={17} /></div>
      <div style={{ maxWidth: '86%' }}>
        <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', padding: '12px 15px', borderRadius: '14px 14px 14px 4px', fontSize: 13.5, lineHeight: 1.65, color: 'var(--text)', boxShadow: 'var(--sh-1)' }}>
          {m.kind === 'update' && <div style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10.5, fontWeight: 700, color: 'var(--brand)', marginBottom: 7, fontFamily: 'var(--font-mono)' }}><Icon name="bolt" size={12} stroke={2.2} />已更新预览</div>}
          <div>{m.text}</div>
          {m.chips && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 11 }}>
              {m.chips.map(c => <span key={c} style={{ fontSize: 11, fontWeight: 500, color: 'var(--brand)', padding: '4px 9px', borderRadius: 999, background: 'var(--brand-soft)', border: '1px solid var(--brand-soft-2)', whiteSpace: 'nowrap' }}>{c}</span>)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Typing() {
  return (
    <div style={{ display: 'flex', gap: 11, marginBottom: 18 }}>
      <div style={{ width: 30, height: 30, borderRadius: 9, flexShrink: 0, display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, var(--blue-600), var(--blue-800))' }}><WhaleMark size={17} /></div>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', padding: '14px 16px', borderRadius: '14px 14px 14px 4px', display: 'flex', gap: 5 }}>
        {[0, 1, 2].map(i => <span key={i} style={{ width: 7, height: 7, borderRadius: 999, background: 'var(--brand)', opacity: 0.5, animation: `rj-bounce 1.2s ${i * 0.15}s infinite` }} />)}
      </div>
    </div>
  );
}

function BuilderScreen({ go, onGenerated, startHandoff }) {
  const [phase, setPhase] = useStateB('entry'); // entry | chat | gen | done
  const [count, setCount] = useStateB(0);
  const [typing, setTyping] = useStateB(false);
  const [genStep, setGenStep] = useStateB(0);
  const [input, setInput] = useStateB('');
  const scrollRef = useRefB(null);
  const chat = window.BUILDER_CHAT;

  useEffectB(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [count, typing]);

  function advance() {
    // reveal next user msg, then AI reply if any
    const next = count;
    if (next >= chat.length) return;
    const item = chat[next];
    if (item.who === 'user' && item.text.includes('生成')) {
      setCount(next + 1);
      setTimeout(() => startGenerate(), 500);
      return;
    }
    setCount(next + 1);
    // if following is AI, show typing then reveal
    if (chat[next + 1] && chat[next + 1].who === 'ai') {
      setTyping(true);
      setTimeout(() => { setTyping(false); setCount(next + 2); }, 1100);
    }
  }

  function startGenerate() {
    setPhase('gen'); setGenStep(0);
    const iv = setInterval(() => {
      setGenStep(s => {
        if (s + 1 >= window.BUILD_STEPS.length) { clearInterval(iv); setTimeout(() => { setPhase('done'); onGenerated && onGenerated(); }, 700); return s + 1; }
        return s + 1;
      });
    }, 620);
  }

  function enterFromEntry() {
    setPhase('chat'); setCount(1);
    setTyping(true);
    setTimeout(() => { setTyping(false); setCount(2); }, 1200);
  }

  // pending next user message (ghost in composer)
  const pendingUser = phase === 'chat' && !typing && count < chat.length && chat[count] && chat[count].who === 'user' ? chat[count] : null;

  if (phase === 'entry') return <BuilderEntry go={go} input={input} setInput={setInput} onSubmit={enterFromEntry} />;

  if (phase === 'gen') return <GenerateView step={genStep} />;

  if (phase === 'done') return <BuilderDone go={go} startHandoff={startHandoff} />;

  // chat phase
  return (
    <div style={{ display: 'flex', height: '100%', minHeight: 0, background: 'var(--bg)' }}>
      {/* left chat */}
      <div style={{ width: '42%', minWidth: 380, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--line)', background: 'var(--surface-2)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 20px', borderBottom: '1px solid var(--line)' }}>
          <ModuleTag mod="builder" />
          <span style={{ fontSize: 12.5, color: 'var(--text-3)' }}>需求对话 · 搭 CRM</span>
          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text-4)', fontFamily: 'var(--font-mono)' }}>会话 #1042</span>
        </div>
        <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '20px 20px 8px' }}>
          {chat.slice(0, count).map((m, i) => <ChatMessage key={i} m={m} />)}
          {typing && <Typing />}
        </div>
        {/* composer */}
        <div style={{ padding: '12px 20px 18px', borderTop: '1px solid var(--line)', background: 'var(--surface-2)' }}>
          {pendingUser && pendingUser.text.includes('生成') ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontSize: 12, color: 'var(--text-3)', textAlign: 'center' }}>结构已就绪，确认无误后生成应用</div>
              <Btn kind="primary" size="lg" icon="bolt" onClick={advance} style={{ width: '100%' }}>生成「销售 CRM」应用</Btn>
            </div>
          ) : (
            <div style={{ background: 'var(--surface)', border: '1px solid var(--line-strong)', borderRadius: 14, padding: 12, boxShadow: 'var(--sh-2)' }}>
              <div style={{ fontSize: 13.5, lineHeight: 1.55, color: pendingUser ? 'var(--text-2)' : 'var(--text-4)', minHeight: 40, padding: '2px 4px' }}>
                {pendingUser ? pendingUser.text : (typing ? '睿鲸正在整理结构…' : '继续补充需求…')}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--text-3)' }}><Icon name="attach" size={14} /> 上传材料</div>
                <Btn kind="primary" size="sm" iconR="send" disabled={!pendingUser} onClick={advance}>发送</Btn>
              </div>
            </div>
          )}
        </div>
      </div>
      {/* right preview */}
      <div style={{ flex: 1, minWidth: 0, background: 'var(--bg-app)' }}>
        <PreviewTabs phase={count} />
      </div>
    </div>
  );
}

function BuilderEntry({ go, input, setInput, onSubmit }) {
  const examples = ['给销售团队搭一个含审批和分级权限的 CRM', '质量部 QMS 整改闭环：登记 → 派发 → 整改 → 验证', '设备台账：档案 / 点检 / 维修工单'];
  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'var(--bg-app)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 40 }}>
      <div style={{ width: 'min(100%, 760px)' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{ width: 60, height: 60, borderRadius: 17, margin: '0 auto 18px', display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, var(--blue-600), var(--blue-800))', boxShadow: 'var(--sh-brand-lg)' }}><Icon name="builder" size={30} stroke={2} style={{ color: '#fff' }} /></div>
          <div style={{ display: 'inline-flex', marginBottom: 14 }}><ModuleTag mod="builder" /></div>
          <h1 style={{ fontSize: 34, fontWeight: 700, letterSpacing: '-0.02em', margin: '6px 0 10px' }}>把业务说清楚，直接搭出应用</h1>
          <p style={{ fontSize: 15, color: 'var(--text-2)', lineHeight: 1.6, maxWidth: 540, margin: '0 auto' }}>描述要管什么、谁来用、走什么流程。睿鲸会整理出数据模型、表单、流程和权限，边聊边在右侧预览。</p>
        </div>

        <div style={{ background: 'var(--surface)', border: '1px solid var(--line-strong)', borderRadius: 18, padding: 18, boxShadow: 'var(--sh-4)' }}>
          <textarea value={input} onChange={e => setInput(e.target.value)} placeholder="例如：给销售团队搭一个 CRM，要能管客户、联系人、商机和跟进记录，商机要走审批，销售只能看自己的客户，主管能看全部。"
            style={{ width: '100%', minHeight: 96, border: 'none', outline: 'none', resize: 'none', fontFamily: 'inherit', fontSize: 15, lineHeight: 1.65, color: 'var(--text)', background: 'transparent' }} />
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12.5, color: 'var(--text-3)', fontWeight: 500 }}><Icon name="attach" size={15} /> 上传 PRD / 表格 / 截图</div>
            <Btn kind="primary" iconR="send" onClick={onSubmit}>开始搭建</Btn>
          </div>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center', marginTop: 18 }}>
          {examples.map(ex => <button key={ex} onClick={onSubmit} style={{ fontSize: 12.5, color: 'var(--text-2)', padding: '8px 13px', borderRadius: 999, background: 'var(--surface)', border: '1px solid var(--line)', cursor: 'pointer', fontFamily: 'inherit', fontWeight: 500 }}>{ex}</button>)}
        </div>
      </div>
    </div>
  );
}

function GenerateView({ step }) {
  return (
    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-app)', padding: 40 }}>
      <div style={{ width: 'min(100%, 520px)' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{ width: 64, height: 64, borderRadius: 18, margin: '0 auto 18px', display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, var(--blue-600), var(--blue-800))', boxShadow: 'var(--sh-brand-lg)', animation: 'rj-float 2s ease-in-out infinite' }}><WhaleMark size={34} /></div>
          <h2 style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em', margin: '0 0 8px' }}>正在生成「销售 CRM」</h2>
          <p style={{ fontSize: 13.5, color: 'var(--text-3)', margin: 0, fontFamily: 'var(--font-mono)' }}>md → app · 确定性装配，无 LLM 干预</p>
        </div>
        <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 16, padding: 10, boxShadow: 'var(--sh-3)' }}>
          {window.BUILD_STEPS.map((s, i) => {
            const done = i < step, active = i === step;
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px', borderRadius: 10, background: active ? 'var(--brand-soft)' : 'transparent', transition: 'background .3s' }}>
                <span style={{ width: 24, height: 24, borderRadius: 999, display: 'grid', placeItems: 'center', flexShrink: 0, background: done ? 'var(--ok)' : active ? 'var(--brand)' : 'var(--surface-3)', color: done || active ? '#fff' : 'var(--text-4)' }}>
                  {done ? <Icon name="check" size={14} stroke={3} /> : active ? <span style={{ width: 9, height: 9, borderRadius: 999, background: '#fff', animation: 'rj-pulse 1s infinite' }} /> : <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)' }}>{i + 1}</span>}
                </span>
                <span style={{ fontSize: 13.5, fontWeight: active ? 600 : 500, color: done ? 'var(--text-3)' : active ? 'var(--brand)' : 'var(--text-4)' }}>{s}</span>
                {active && <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--brand)', fontFamily: 'var(--font-mono)' }}>进行中</span>}
                {done && <Icon name="check" size={14} style={{ marginLeft: 'auto', color: 'var(--ok)' }} />}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function BuilderDone({ go, startHandoff }) {
  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'var(--bg-app)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 40 }}>
      <div style={{ width: 'min(100%, 680px)' }}>
        <div style={{ textAlign: 'center', marginBottom: 26 }}>
          <div style={{ width: 64, height: 64, borderRadius: 999, margin: '0 auto 18px', display: 'grid', placeItems: 'center', background: 'var(--ok-soft)', color: 'var(--ok)' }}><Icon name="checkCircle" size={38} stroke={2} /></div>
          <h2 style={{ fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', margin: '0 0 8px' }}>「销售 CRM」已上线</h2>
          <p style={{ fontSize: 14.5, color: 'var(--text-2)', margin: 0 }}>4 个模型 · 1 条审批流 · 4 个角色已部署，<b style={{ color: 'var(--text)' }}>app_id 843747</b> 已分配。</p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 22 }}>
          {[['layers', '4', '数据模型'], ['doc', '4', '表单页面'], ['branch', '1', '审批流程'], ['lock', '4', '角色权限']].map(([ic, n, l]) => (
            <div key={l} style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 12, padding: '14px 12px', textAlign: 'center', boxShadow: 'var(--sh-1)' }}>
              <Icon name={ic} size={18} style={{ color: 'var(--brand)', margin: '0 auto 7px' }} />
              <div style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-mono)', letterSpacing: '-0.02em' }}>{n}</div>
              <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 2 }}>{l}</div>
            </div>
          ))}
        </div>

        {/* handoff prompt — the spectrum moment */}
        <div style={{ borderRadius: 16, padding: 20, background: 'linear-gradient(135deg, var(--blue-950), var(--blue-800))', color: '#fff', marginBottom: 18, position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', right: -10, bottom: -20, opacity: 0.1 }}><Icon name="coding" size={120} stroke={1.5} style={{ color: '#fff' }} /></div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}><Icon name="swap" size={16} style={{ color: 'var(--blue-300)' }} /><span style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: '0.04em', color: 'var(--blue-200)' }}>需要标准配置装不下的功能？</span></div>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6, maxWidth: 460, lineHeight: 1.5 }}>比如一个能拖拽换阶段的「商机看板」—— 这超出了配置能力，交给 AI Coding。</div>
          <div style={{ fontSize: 12.5, color: 'rgba(255,255,255,0.72)', marginBottom: 16 }}>应用上下文（模型 / 接口 / 枚举）会自动带过去，无需重新描述。</div>
          <Btn kind="soft" iconR="arrowR" onClick={startHandoff} mono style={{ background: '#fff', color: 'var(--blue-800)', borderColor: 'transparent' }}>带上下文转 AI Coding</Btn>
        </div>

        <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
          <Btn kind="primary" icon="play" onClick={() => go('apps')}>打开应用</Btn>
          <Btn kind="ghost" icon="apps" onClick={() => go('apps')}>进入应用资产库</Btn>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { BuilderScreen });
