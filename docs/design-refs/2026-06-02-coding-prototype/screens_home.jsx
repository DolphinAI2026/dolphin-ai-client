/* screens_home.jsx — 首页 / 定位概览 (positioning narrative) */
const { useState: useStateH } = React;

function ModuleDefCard({ mod, onEnter }) {
  const isB = mod === 'builder';
  const [hov, setHov] = useStateH(false);
  return (
    <div onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{
        position: 'relative', flex: 1, padding: 28, borderRadius: 20, background: 'var(--surface)',
        border: '1px solid var(--line)', boxShadow: hov ? 'var(--sh-4)' : 'var(--sh-2)',
        transform: hov ? 'translateY(-3px)' : 'none', transition: 'all .2s var(--ease)', overflow: 'hidden',
      }}>
      {/* texture cue — builder: block grid; coding: code lines */}
      <div style={{ position: 'absolute', top: 0, right: 0, width: 160, height: 160, opacity: 0.05, pointerEvents: 'none' }}>
        {isB ? (
          <svg width="160" height="160" viewBox="0 0 160 160" fill="var(--brand)">
            {[0,1,2,3].map(r => [0,1,2,3].map(c => <rect key={r+'-'+c} x={20+c*34} y={20+r*34} width="26" height="26" rx="5" />))}
          </svg>
        ) : (
          <svg width="160" height="160" viewBox="0 0 160 160" stroke="var(--brand)" strokeWidth="3" fill="none" strokeLinecap="round">
            {[0,1,2,3,4,5].map(i => <line key={i} x1="24" y1={26+i*22} x2={120 - (i%3)*30} y2={26+i*22} />)}
          </svg>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 13, marginBottom: 18 }}>
        <div style={{ width: 50, height: 50, display: 'grid', placeItems: 'center', borderRadius: isB ? 14 : 13,
          background: isB ? 'linear-gradient(145deg, var(--blue-600), var(--blue-800))' : 'linear-gradient(145deg, var(--blue-800), var(--blue-950))',
          color: '#fff', boxShadow: 'var(--sh-brand)' }}>
          <Icon name={isB ? 'builder' : 'coding'} size={26} stroke={2} />
        </div>
        <div>
          <div style={{ fontSize: 21, fontWeight: 700, letterSpacing: '-0.02em', fontFamily: isB ? 'var(--font-sans)' : 'var(--font-mono)' }}>AI {isB ? 'Builder' : 'Coding'}</div>
          <div style={{ fontSize: 12.5, color: 'var(--text-3)', fontWeight: 500, marginTop: 2, whiteSpace: 'nowrap' }}>{isB ? '智能搭建 · 从想法到应用' : '智能开发 · 从应用到能力'}</div>
        </div>
      </div>

      <p style={{ fontSize: 14.5, lineHeight: 1.7, color: 'var(--text-2)', margin: '0 0 18px' }}>
        {isB
          ? <>业务人员用<b style={{ color: 'var(--text)' }}>对话</b>把需求说清楚，睿鲸直接搭出<b style={{ color: 'var(--text)' }}>整个应用</b> —— 数据模型、表单、流程、权限一次成型。</>
          : <>实施顾问在<b style={{ color: 'var(--text)' }}>已有应用</b>上做标准配置装不下的部分 —— <b style={{ color: 'var(--text)' }}>定制页面、可复用组件、复杂接口</b>，对话即写代码。</>}
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 9, marginBottom: 22 }}>
        {(isB
          ? [['layers', '广度与结构'], ['grid2', '搭出可运行的完整应用'], ['box', '产物进「应用资产库」']]
          : [['bolt', '深度与定制'], ['terminal', '生成可复用资产 + 在线 IDE'], ['store', '产物进「自开发资产库」']]
        ).map(([ic, t]) => (
          <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: 'var(--text-2)', fontWeight: 500 }}>
            <span style={{ width: 24, height: 24, display: 'grid', placeItems: 'center', borderRadius: 7, background: 'var(--brand-soft)', color: 'var(--brand)' }}><Icon name={ic} size={14} stroke={2} /></span>
            {t}
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5, color: 'var(--text-3)', marginBottom: 16 }}>
        <span>核心用户</span>
        <span style={{ height: 12, width: 1, background: 'var(--line-strong)' }} />
        <b style={{ color: 'var(--text-2)', fontWeight: 600 }}>{isB ? '业务人员 + 实施顾问' : '低代码实施顾问（会改代码）'}</b>
      </div>

      <Btn kind={isB ? 'primary' : 'dark'} mono={!isB} iconR="arrowR" onClick={onEnter} style={{ width: '100%' }}>
        {isB ? '进入 AI Builder' : '进入 AI Coding'}
      </Btn>
    </div>
  );
}

function BoundaryExplore() {
  const [pick, setPick] = useStateH('C');
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 20, padding: 28, boxShadow: 'var(--sh-2)' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 6 }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.02em', margin: 0 }}>边界怎么划？</h2>
        <span style={{ fontSize: 12.5, color: 'var(--text-3)' }}>探索了 3 种，推荐 C 的综合版</span>
      </div>
      <p style={{ fontSize: 13.5, color: 'var(--text-2)', margin: '0 0 20px', lineHeight: 1.65, maxWidth: 720 }}>
        现状最大的痛点是<b style={{ color: 'var(--text)' }}>边界不清</b>：同一个「应用里的定制页面」既像 Builder 又像 Coding。下面三种划法各有取舍 —— 点开看差异。
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 22 }}>
        {window.BOUNDARY_MODELS.map(m => {
          const on = pick === m.id;
          return (
            <button key={m.id} onClick={() => setPick(m.id)} style={{
              textAlign: 'left', cursor: 'pointer', padding: 18, borderRadius: 14,
              background: on ? 'var(--brand-soft)' : 'var(--surface-2)',
              border: on ? '1.5px solid var(--brand)' : '1px solid var(--line)',
              transition: 'all .16s var(--ease)', fontFamily: 'inherit',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 12 }}>
                <span style={{ width: 30, height: 30, display: 'grid', placeItems: 'center', borderRadius: 8,
                  background: on ? 'var(--brand)' : 'var(--surface)', color: on ? '#fff' : 'var(--brand)', border: on ? 'none' : '1px solid var(--line)' }}>
                  <Icon name={m.icon} size={16} stroke={2} />
                </span>
                <span style={{ fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)', color: on ? 'var(--brand)' : 'var(--text-4)' }}>模型 {m.id}</span>
              </div>
              <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12, color: on ? 'var(--brand)' : 'var(--text)' }}>{m.label}</div>
              <div style={{ fontSize: 12, color: 'var(--text-2)', lineHeight: 1.55 }}>
                <div style={{ display: 'flex', gap: 6, marginBottom: 4 }}><b style={{ color: 'var(--text-3)', fontWeight: 600, minWidth: 44 }}>Builder</b><span>{m.builder}</span></div>
                <div style={{ display: 'flex', gap: 6 }}><b style={{ color: 'var(--text-3)', fontWeight: 600, minWidth: 44, fontFamily: 'var(--font-mono)' }}>Coding</b><span>{m.coding}</span></div>
              </div>
            </button>
          );
        })}
      </div>

      <div style={{ display: 'flex', gap: 14, padding: 16, borderRadius: 12, background: 'var(--surface-2)', border: '1px dashed var(--line-strong)', marginBottom: 24 }}>
        <Icon name="branch" size={18} style={{ color: 'var(--warn)', marginTop: 1 }} />
        <div style={{ fontSize: 13, color: 'var(--text-2)', lineHeight: 1.6 }}>
          <b style={{ color: 'var(--text)' }}>取舍 · 模型 {pick}：</b>{window.BOUNDARY_MODELS.find(m => m.id === pick).note}
        </div>
      </div>

      {/* The commit */}
      <div style={{ borderRadius: 16, padding: '22px 24px', background: 'linear-gradient(135deg, var(--blue-950), var(--blue-800))', color: '#fff', position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', right: -20, top: -20, opacity: 0.12 }}><WhaleMark size={150} /></div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <Icon name="check" size={16} stroke={2.4} style={{ color: 'var(--blue-300)' }} />
          <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.04em', color: 'var(--blue-200)' }}>睿鲸采用 · 综合定位</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 18, alignItems: 'center', maxWidth: 760 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>Builder = 广度</div>
            <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.78)', lineHeight: 1.55 }}>对话搭出<b style={{ color: '#fff' }}>整个应用</b>的结构。从 0→1。</div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, color: 'var(--blue-300)' }}>
            <Icon name="swap" size={20} stroke={2} />
            <span style={{ fontSize: 10, fontWeight: 600, fontFamily: 'var(--font-mono)' }}>一键转换</span>
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4, fontFamily: 'var(--font-mono)' }}>Coding = 深度</div>
            <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.78)', lineHeight: 1.55 }}>对话写出<b style={{ color: '#fff' }}>装不进配置</b>的定制与组件。</div>
          </div>
        </div>
        <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid rgba(255,255,255,0.14)', fontSize: 13, color: 'rgba(255,255,255,0.8)', lineHeight: 1.6 }}>
          <b style={{ color: '#fff' }}>衔接是一条连续光谱：</b>不强迫用户预先选模块。Builder 搭好后遇到配置满足不了的需求，<b style={{ color: 'var(--blue-200)' }}>一键带上下文转 Coding</b>；Coding 产出的资产能<b style={{ color: 'var(--blue-200)' }}>装回应用</b>。两个模块一套外壳、统一管理 —— 不再割裂。
        </div>
      </div>
    </div>
  );
}

function JourneyStrip({ go }) {
  const steps = [
    { mod: 'builder', t: '描述需求', d: '“给销售搭个 CRM”', icon: 'home' },
    { mod: 'builder', t: '对话搭结构', d: '模型 / 表单 / 流程 / 权限', icon: 'builder' },
    { mod: 'builder', t: '生成应用', d: '销售 CRM 上线', icon: 'checkCircle' },
    { mod: 'coding', t: '一键转 Coding', d: '“要个拖拽看板”', icon: 'swap' },
    { mod: 'coding', t: '对话写代码', d: '在线 IDE + 实时预览', icon: 'coding' },
    { mod: 'coding', t: '装回应用', d: '商机看板进资产库', icon: 'store' },
  ];
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 20, padding: '24px 28px', boxShadow: 'var(--sh-2)' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 20 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, letterSpacing: '-0.01em', margin: 0 }}>一条贯穿全程的路径 · 复杂 CRM</h2>
        <span style={{ fontSize: 12, color: 'var(--text-3)' }}>0→1 搭建 → 持续扩展</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 0, position: 'relative' }}>
        {steps.map((s, i) => {
          const isB = s.mod === 'builder';
          return (
            <div key={i} style={{ position: 'relative', padding: '0 6px' }}>
              {i < 5 && <div style={{ position: 'absolute', top: 19, right: -8, width: 16, color: 'var(--text-4)', zIndex: 2 }}><Icon name="chevR" size={14} /></div>}
              <div style={{ width: 40, height: 40, borderRadius: 11, display: 'grid', placeItems: 'center', marginBottom: 10,
                background: isB ? 'var(--brand-soft)' : 'var(--blue-950)', color: isB ? 'var(--brand)' : '#fff',
                border: isB ? '1px solid var(--brand-soft-2)' : 'none' }}>
                <Icon name={s.icon} size={19} stroke={2} />
              </div>
              <div style={{ fontSize: 9.5, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-4)', marginBottom: 3 }}>{isB ? 'BUILDER' : 'CODING'}</div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>{s.t}</div>
              <div style={{ fontSize: 11.5, color: 'var(--text-3)', lineHeight: 1.4 }}>{s.d}</div>
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 22, display: 'flex', gap: 10 }}>
        <Btn kind="primary" icon="builder" onClick={() => go('builder')}>从 Builder 开始搭 CRM</Btn>
        <Btn kind="ghost" iconR="arrowR" onClick={() => go('apps')}>查看应用资产库</Btn>
      </div>
    </div>
  );
}

function HomeScreen({ go }) {
  return (
    <div style={{ height: '100%', overflowY: 'auto', background: 'var(--bg-app)' }}>
      <div style={{ width: 'min(100%, 1100px)', margin: '0 auto', padding: '46px 36px 72px' }}>
        {/* hero */}
        <div style={{ marginBottom: 34 }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, height: 30, padding: '0 12px', borderRadius: 999,
            background: 'var(--surface)', border: '1px solid var(--line)', fontSize: 11.5, fontWeight: 600, color: 'var(--text-3)', marginBottom: 18, boxShadow: 'var(--sh-1)', whiteSpace: 'nowrap' }}>
            <WhaleMark size={14} color="var(--brand)" /> 睿鲸AI · 统一搭建工作台
          </div>
          <h1 style={{ fontSize: 'var(--t-display)', fontWeight: 700, letterSpacing: '-0.03em', lineHeight: 1.1, margin: '0 0 14px', maxWidth: 820 }}>
            把业务说清楚，<br />睿鲸从<span style={{ color: 'var(--brand)' }}>搭应用</span>到<span style={{ color: 'var(--brand)', fontFamily: 'var(--font-mono)' }}>写代码</span>一气呵成。
          </h1>
          <p style={{ fontSize: 16, color: 'var(--text-2)', lineHeight: 1.65, maxWidth: 680, margin: 0 }}>
            两个智能体，一套工作台。Builder 负责<b style={{ color: 'var(--text)' }}>广度</b>——把整个应用搭出来；Coding 负责<b style={{ color: 'var(--text)' }}>深度</b>——把配置装不下的定制写出来。中间用一键转换无缝衔接。
          </p>
        </div>

        {/* two modules */}
        <div style={{ display: 'flex', gap: 18, marginBottom: 22 }}>
          <ModuleDefCard mod="builder" onEnter={() => go('builder')} />
          <ModuleDefCard mod="coding" onEnter={() => go('coding')} />
        </div>

        {/* boundary exploration */}
        <div style={{ marginBottom: 22 }}><BoundaryExplore /></div>

        {/* journey */}
        <JourneyStrip go={go} />
      </div>
    </div>
  );
}

Object.assign(window, { HomeScreen });
