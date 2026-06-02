/* app.jsx — 睿鲸AI shell: routing, tabs, Builder↔Coding handoff */
const { useState: useStateApp, useEffect: useEffectApp } = React;

const TAB_META = {
  home:    { label: '首页', icon: 'home', closable: false },
  apps:    { label: '应用资产库', icon: 'apps' },
  builder: { label: 'AI Builder', icon: 'builder' },
  catalog: { label: '自开发资产库', icon: 'store' },
  coding:  { label: 'AI Coding', icon: 'coding', mono: true },
};

function HandoffOverlay({ onDone }) {
  const [step, setStep] = useStateApp(0);
  useEffectApp(() => {
    const t1 = setTimeout(() => setStep(1), 500);
    const t2 = setTimeout(() => setStep(2), 1150);
    const t3 = setTimeout(() => onDone(), 1900);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
  }, []);
  const items = ['数据模型 · 客户 / 联系人 / 商机 / 跟进', '阶段枚举 · 5 个选项', '接口 · updateStage / listOpps', '角色权限 · 4 个角色'];
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(8,16,36,0.62)', backdropFilter: 'blur(8px)', display: 'grid', placeItems: 'center', animation: 'rj-fade .2s' }}>
      <div style={{ width: 'min(92%, 520px)', background: 'var(--surface)', borderRadius: 20, padding: 30, boxShadow: 'var(--sh-5)', animation: 'rj-pop .3s var(--ease-spring)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 18, marginBottom: 24 }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ width: 52, height: 52, borderRadius: 14, display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, var(--blue-600), var(--blue-800))', color: '#fff', boxShadow: 'var(--sh-brand)', opacity: step >= 1 ? 0.45 : 1, transition: 'opacity .4s' }}><Icon name="builder" size={26} stroke={2} /></div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-3)', marginTop: 7 }}>Builder</div>
          </div>
          <div style={{ flex: '0 0 80px', position: 'relative', height: 2, background: 'var(--line-strong)' }}>
            <div style={{ position: 'absolute', inset: 0, background: 'var(--brand)', width: step >= 1 ? '100%' : '0%', transition: 'width .7s var(--ease)' }} />
            <div style={{ position: 'absolute', top: -9, left: step >= 1 ? 'calc(100% - 10px)' : '0', transition: 'left .7s var(--ease)', color: 'var(--brand)' }}><Icon name="swap" size={20} stroke={2} /></div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ width: 52, height: 52, borderRadius: 13, display: 'grid', placeItems: 'center', background: 'var(--blue-950)', color: '#fff', boxShadow: 'var(--sh-3)', transform: step >= 2 ? 'scale(1.06)' : 'scale(1)', transition: 'transform .3s var(--ease-spring)' }}><Icon name="coding" size={26} stroke={2.2} /></div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-3)', marginTop: 7, fontFamily: 'var(--font-mono)' }}>Coding</div>
          </div>
        </div>
        <div style={{ textAlign: 'center', fontSize: 16, fontWeight: 700, marginBottom: 4 }}>正在转交应用上下文</div>
        <div style={{ textAlign: 'center', fontSize: 12.5, color: 'var(--text-3)', marginBottom: 18 }}>无需重新描述，Coding 直接复用 Builder 的成果</div>
        <div style={{ background: 'var(--surface-2)', borderRadius: 12, border: '1px solid var(--line)', padding: 12 }}>
          {items.map((it, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '6px 6px', fontSize: 12, color: 'var(--text-2)', fontFamily: 'var(--font-mono)', opacity: step >= 1 ? 1 : 0.3, transition: `opacity .4s ${i * 0.08}s` }}>
              <Icon name="check" size={13} stroke={2.6} style={{ color: 'var(--ok)' }} /> {it}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function App() {
  const [route, setRoute] = useStateApp('home');
  const [tabs, setTabs] = useStateApp(['home']);
  const [generated, setGenerated] = useStateApp(false);
  const [fromHandoff, setFromHandoff] = useStateApp(false);
  const [overlay, setOverlay] = useStateApp(false);
  const [codingKey, setCodingKey] = useStateApp(0);
  const [builderKey, setBuilderKey] = useStateApp(0);

  function go(key) {
    setRoute(key);
    if (key === 'builder') setFromHandoff(false);
    setTabs(t => t.includes(key) ? t : [...t, key]);
  }
  function closeTab(key) {
    setTabs(t => {
      const nt = t.filter(k => k !== key);
      if (route === key) setRoute(nt[nt.length - 1] || 'home');
      return nt.length ? nt : ['home'];
    });
  }
  function startHandoff() {
    setOverlay(true);
  }
  function finishHandoff() {
    setOverlay(false);
    setFromHandoff(true);
    setCodingKey(k => k + 1);
    setRoute('coding');
    setTabs(t => t.includes('coding') ? t : [...t, 'coding']);
  }

  const tabObjs = tabs.map(k => ({ key: k, ...TAB_META[k] }));

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100%', overflow: 'hidden' }}>
      <Rail route={route} go={go} />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <TabStrip tabs={tabObjs} active={route} onPick={setRoute} onClose={closeTab} />
        <div style={{ flex: 1, minHeight: 0 }}>
          {route === 'home' && <HomeScreen go={go} />}
          {route === 'apps' && <AssetLibrary kind="apps" go={go} />}
          {route === 'catalog' && <AssetLibrary kind="catalog" go={go} />}
          {route === 'builder' && <BuilderScreen key={builderKey} go={go} onGenerated={() => setGenerated(true)} startHandoff={startHandoff} />}
          {route === 'coding' && <CodingScreen key={codingKey} go={go} fromHandoff={fromHandoff} />}
        </div>
      </div>
      {overlay && <HandoffOverlay onDone={finishHandoff} />}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
