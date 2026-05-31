// Vibe Coding — VS Code Web (code-server) + MiniMax Chat assistant.
//
// PRODUCT INTENT:
//   Full-code workspace. Real file editing, real terminal, real git.
//   The AI chat is a SIDE PANEL, not the main driver — user is in control.
//
// LAYOUT:
//   Activity bar (left, slim)  →  File tree  →  Editor with tabs  →  AI side panel
//   Status bar (bottom)        +  Terminal panel (bottom, toggleable)

function VibePage() {
  const { navigate } = useContext(RouteCtx);
  const [activeFile, setActiveFile] = useState('Apps.vue');
  const [openTabs, setOpenTabs] = useState(['Apps.vue', 'useTravelForm.ts', 'tokens.css']);
  const [activeActivity, setActiveActivity] = useState('explorer');
  const [termOpen, setTermOpen] = useState(true);
  const [aiOpen, setAiOpen] = useState(true);
  const [aiInput, setAiInput] = useState('');

  // Real-ish project tree (matches the imported repo structure)
  const tree = [
    { name: 'frontend/', type: 'dir', open: true, depth: 0, children: [
      { name: 'src/', type: 'dir', open: true, depth: 1, children: [
        { name: 'views/', type: 'dir', open: true, depth: 2, children: [
          { name: 'Apps.vue', type: 'vue', depth: 3, modified: true },
          { name: 'ChatPage.vue', type: 'vue', depth: 3 },
          { name: 'CodingPage.vue', type: 'vue', depth: 3 },
          { name: 'Landing.vue', type: 'vue', depth: 3 },
          { name: 'MarketplacePage.vue', type: 'vue', depth: 3 },
        ]},
        { name: 'components/', type: 'dir', open: false, depth: 2 },
        { name: 'composables/', type: 'dir', open: true, depth: 2, children: [
          { name: 'useTravelForm.ts', type: 'ts', depth: 3, modified: true },
        ]},
        { name: 'styles/', type: 'dir', open: true, depth: 2, children: [
          { name: 'tokens.css', type: 'css', depth: 3 },
          { name: 'theme-vars.css', type: 'css', depth: 3 },
        ]},
        { name: 'router/', type: 'dir', open: false, depth: 2 },
        { name: 'stores/', type: 'dir', open: false, depth: 2 },
      ]},
      { name: 'package.json', type: 'json', depth: 1 },
      { name: 'vite.config.ts', type: 'ts', depth: 1 },
    ]},
    { name: 'backend/', type: 'dir', open: false, depth: 0 },
    { name: 'README.md', type: 'md', depth: 0 },
  ];

  // Mock code for Apps.vue showing diff markers
  const codeLines = [
    { n: 1,  t: '<template>', cls: '' },
    { n: 2,  t: '  <WorkbenchShell>', cls: '' },
    { n: 3,  t: '    <div class="apps-main">', cls: '' },
    { n: 4,  t: '      <!-- Filter tabs + view toggle -->', cls: 'cmt' },
    { n: 5,  t: '      <div class="filter-bar">', cls: '' },
    { n: 6,  t: '        <div class="filter-tabs">', cls: '' },
    { n: 7,  t: '          <button', cls: '' },
    { n: 8,  t: '            v-for="tab in tabs"', cls: '' },
    { n: 9,  t: '            :key="tab.value"', cls: '' },
    { n: 10, t: '            :class="[', cls: '' },
    { n: 11, t: "              'filter-tab',", cls: 'mod', mark: '~' },
    { n: 12, t: '              { active: activeTab.includes(tab.value) }', cls: 'add', mark: '+' },
    { n: 13, t: '            ]"', cls: '' },
    { n: 14, t: '            @click="toggleTab(tab.value)"', cls: 'add', mark: '+' },
    { n: 15, t: '          >', cls: '' },
    { n: 16, t: '            {{ tab.label }}', cls: '' },
    { n: 17, t: '            <span class="tab-count">{{ tabCounts[tab.value] }}</span>', cls: '' },
    { n: 18, t: '          </button>', cls: '' },
    { n: 19, t: '        </div>', cls: '' },
    { n: 20, t: '        <!-- 新增：已部署筛选 -->', cls: 'cmt add', mark: '+' },
    { n: 21, t: '        <el-checkbox v-model="onlyDeployed">仅看已部署</el-checkbox>', cls: 'add', mark: '+' },
    { n: 22, t: '      </div>', cls: '' },
    { n: 23, t: '', cls: '' },
    { n: 24, t: '      <!-- Content area -->', cls: 'cmt' },
    { n: 25, t: '      <div class="app-content" :class="viewMode">', cls: '' },
    { n: 26, t: '        <div v-if="loading" class="empty-state">加载中...</div>', cls: '' },
  ];

  const ACTIVITY = [
    { key: 'explorer', icon: 'apps',   tip: '资源管理器' },
    { key: 'search',   icon: 'search', tip: '搜索' },
    { key: 'git',      icon: 'github', tip: '源代码管理', badge: 3 },
    { key: 'ext',      icon: 'store',  tip: '扩展' },
    { key: 'ai',       icon: 'sparkle',tip: 'MiniMax Chat', special: true },
  ];

  return (
    <div className="vibe-page">
      {/* ── Activity bar (slim left) ── */}
      <div className="vibe-activity">
        {ACTIVITY.map(a => {
          const Ic = I[a.icon];
          return (
            <button
              key={a.key}
              className={`vibe-activity-btn ${activeActivity === a.key ? 'active' : ''} ${a.special ? 'is-ai' : ''}`}
              onClick={() => { setActiveActivity(a.key); if (a.key === 'ai') setAiOpen(true); }}
              title={a.tip}
            >
              <Ic size={18} />
              {a.badge && <span className="vibe-activity-badge">{a.badge}</span>}
            </button>
          );
        })}
        <div style={{ flex: 1 }} />
        <button className="vibe-activity-btn" title="账户"><I.user size={18} /></button>
        <button className="vibe-activity-btn" title="设置"><I.gear size={18} /></button>
      </div>

      {/* ── File tree ── */}
      <aside className="vibe-tree">
        <div className="vibe-tree-head">
          <span className="vibe-tree-title">资源管理器</span>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>
            <button className="icon-btn" style={{ width: 22, height: 22 }} title="新建文件"><I.plus size={12} /></button>
            <button className="icon-btn" style={{ width: 22, height: 22 }} title="刷新"><I.refresh size={12} /></button>
          </div>
        </div>
        <div className="vibe-tree-project">
          <I.chevronD size={11} />
          <span>APAAS-BUILDER-AI</span>
        </div>
        <div className="vibe-tree-list">
          {tree.flatMap(function expand(n) {
            const Ic = n.type === 'dir' ? (n.open ? I.chevronD : I.chevronR) : null;
            const rows = [(
              <div key={n.name + n.depth}
                   className={`vibe-tree-row ${activeFile === n.name ? 'active' : ''} ${n.modified ? 'modified' : ''}`}
                   style={{ paddingLeft: 6 + n.depth * 12 }}
                   onClick={() => n.type !== 'dir' && (setActiveFile(n.name), setOpenTabs(t => t.includes(n.name) ? t : [...t, n.name]))}>
                {Ic ? <Ic size={11} style={{ color: 'var(--text-3)' }} /> : <span style={{ width: 11 }} />}
                <span className={`coding-file-icon coding-file-${n.type}`}>{n.type === 'dir' ? '' : n.type === 'vue' ? 'V' : n.type === 'ts' ? 'TS' : n.type === 'css' ? '#' : n.type === 'md' ? 'M' : '{}'}</span>
                <span className="vibe-tree-name">{n.name}</span>
                {n.modified && <span className="vibe-tree-dot" title="已修改">M</span>}
              </div>
            )];
            if (n.open && n.children) {
              for (const c of n.children) rows.push(...expand(c));
            }
            return rows;
          })}
        </div>
        <div className="vibe-tree-foot">
          <div className="vibe-outline">
            <div className="vibe-outline-head">大纲</div>
            {['template', 'script setup', '  tabs', '  activeTab', '  toggleTab', 'style scoped'].map(o => (
              <div key={o} className="vibe-outline-item">
                <I.code size={10} />
                <span>{o.trim()}</span>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* ── Editor + Terminal + AI side panel ── */}
      <div className="vibe-main">
        {/* Tabs */}
        <div className="vibe-tabs">
          {openTabs.map(t => (
            <button key={t} className={`vibe-tab ${activeFile === t ? 'active' : ''}`} onClick={() => setActiveFile(t)}>
              <span className={`coding-file-icon coding-file-${t.endsWith('.vue') ? 'vue' : t.endsWith('.ts') ? 'ts' : t.endsWith('.css') ? 'css' : 'json'}`}>
                {t.endsWith('.vue') ? 'V' : t.endsWith('.ts') ? 'TS' : t.endsWith('.css') ? '#' : '{}'}
              </span>
              <span>{t}</span>
              {t === 'Apps.vue' && <span className="vibe-tab-dot">●</span>}
              <button className="vibe-tab-close" onClick={(e) => { e.stopPropagation(); setOpenTabs(ts => ts.filter(x => x !== t)); if (activeFile === t) setActiveFile(openTabs[0] || ''); }}>×</button>
            </button>
          ))}
          <div style={{ flex: 1 }} />
          <button className="icon-btn" style={{ width: 26, height: 26 }} title="拆分编辑器"><I.copy size={13} /></button>
        </div>

        {/* Breadcrumb */}
        <div className="vibe-breadcrumb">
          <span>frontend</span><I.chevronR size={10} />
          <span>src</span><I.chevronR size={10} />
          <span>views</span><I.chevronR size={10} />
          <span style={{ color: 'var(--text)' }}>{activeFile}</span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
            <button className="vibe-sbx-chip" onClick={() => navigate('/runtime')} title="查看沙箱详情">
              <I.cloud size={11} />
              <span><b>sbx-2b1c</b> · 4C/8G · 剩余 47m</span>
            </button>
            <span style={{ color: 'var(--text-3)', fontSize: 11 }}>
              <span className="badge badge-amber" style={{ marginRight: 4 }}><span className="badge-dot" />未保存</span>
              UTF-8 · LF · Vue
            </span>
          </div>
        </div>

        {/* Editor */}
        <div className="vibe-editor">
          <pre className="vibe-code">
            {codeLines.map(l => (
              <div key={l.n} className={`vibe-code-line ${l.cls}`}>
                <span className="vibe-gutter">{l.n}</span>
                <span className="vibe-mark">{l.mark || ''}</span>
                <span className="vibe-line-text" dangerouslySetInnerHTML={{ __html: highlightLine(l.t) }} />
              </div>
            ))}
            {/* Cursor with selection */}
            <div className="vibe-cursor-line">
              <span className="vibe-gutter">27</span>
              <span className="vibe-mark"></span>
              <span className="vibe-line-text" style={{ position: 'relative' }}>
                <span className="vibe-cursor" />
              </span>
            </div>
          </pre>

          {/* Minimap (decorative) */}
          <div className="vibe-minimap" aria-hidden="true">
            {codeLines.map((l, i) => (
              <div key={i} className="vibe-minimap-line" style={{ width: Math.min(96, Math.max(8, l.t.length * 1.4)) }} />
            ))}
          </div>
        </div>

        {/* Terminal */}
        {termOpen && (
          <div className="vibe-term">
            <div className="vibe-term-head">
              <div className="vibe-term-tabs">
                <button className="vibe-term-tab active">npm run dev</button>
                <button className="vibe-term-tab">git</button>
                <button className="vibe-term-tab">+</button>
              </div>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>
                <button className="icon-btn" style={{ width: 24, height: 24 }} title="清空"><I.trash size={12} /></button>
                <button className="icon-btn" style={{ width: 24, height: 24 }} onClick={() => setTermOpen(false)} title="关闭"><I.chevronD size={12} /></button>
              </div>
            </div>
            <div className="vibe-term-body">
              <div className="vibe-term-line"><span className="vibe-term-prompt mono">~/apaas-builder-ai/frontend</span> <span className="mono">$ npm run dev</span></div>
              <div className="vibe-term-line mono" style={{ color: 'var(--text-3)' }}>{'  '}VITE v5.4.2  ready in 412 ms</div>
              <div className="vibe-term-line mono"><span style={{ color: 'var(--brand-text)' }}>{'  '}➜ </span><span> Local:   </span><span style={{ color: 'var(--ai-text)' }}>http://localhost:5173/</span></div>
              <div className="vibe-term-line mono"><span style={{ color: 'var(--brand-text)' }}>{'  '}➜ </span><span> Network: use --host to expose</span></div>
              <div className="vibe-term-line mono" style={{ color: 'var(--emerald)' }}>{'  '}[HMR] update Apps.vue · 12:48:22</div>
              <div className="vibe-term-line"><span className="vibe-term-prompt mono">~/apaas-builder-ai/frontend</span> <span className="mono">$ </span><span className="vibe-term-cursor" /></div>
            </div>
          </div>
        )}

        {/* Status bar */}
        <div className="vibe-statusbar">
          <span className="vibe-statusbar-item vibe-statusbar-brand"><I.github size={11} /> main ↑1</span>
          <span className="vibe-statusbar-item"><I.check size={11} /> 0 错误 · 2 警告</span>
          <span className="vibe-statusbar-item">↓ 8 KB · ↑ 1.2 KB</span>
          <div style={{ flex: 1 }} />
          <span className="vibe-statusbar-item">第 27 行，第 1 列</span>
          <span className="vibe-statusbar-item">空格 · 2</span>
          <span className="vibe-statusbar-item">UTF-8</span>
          <span className="vibe-statusbar-item">LF</span>
          <span className="vibe-statusbar-item vibe-statusbar-ai" onClick={() => setAiOpen(o => !o)}>
            <I.sparkle size={11} /> MiniMax Chat 已就绪
          </span>
        </div>
      </div>

      {/* ── AI side panel (MiniMax Chat) ── */}
      {aiOpen && (
        <aside className="vibe-ai">
          <div className="vibe-ai-head">
            <I.sparkle size={14} style={{ color: 'var(--ai-text)' }} />
            <span style={{ fontSize: 13, fontWeight: 600 }}>MiniMax Chat</span>
            <span className="badge badge-outline" style={{ marginLeft: 4 }}>本工程</span>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>
              <button className="icon-btn" style={{ width: 24, height: 24 }} title="历史"><I.book size={12} /></button>
              <button className="icon-btn" style={{ width: 24, height: 24 }} title="新会话"><I.plus size={12} /></button>
              <button className="icon-btn" style={{ width: 24, height: 24 }} onClick={() => setAiOpen(false)} title="关闭"><I.chevronR size={12} /></button>
            </div>
          </div>

          <div className="vibe-ai-thread">
            <div className="vibe-ai-msg vibe-ai-msg-user">
              <div className="vibe-ai-bubble">
                把 Apps.vue 的筛选 tab 改成多选，加一个"已部署"筛项。
                <div className="vibe-ai-attach">
                  <I.code size={10} /> <span className="mono">Apps.vue · 12-26 行</span>
                </div>
              </div>
            </div>
            <div className="vibe-ai-msg vibe-ai-msg-ai">
              <div className="vibe-ai-bubble">
                好。改动分三步：<br />
                <b>1.</b> 把 <code className="mono">activeTab</code> 从 <code className="mono">String</code> 改成 <code className="mono">String[]</code><br />
                <b>2.</b> tab 点击逻辑改成 toggle<br />
                <b>3.</b> 新增 <code className="mono">onlyDeployed</code> 状态 + 复选框<br />
                我已经把变更写到编辑器里了，你可以审阅一下：
              </div>
              <div className="vibe-ai-applied">
                <I.check size={11} />
                <span>已修改 <code className="mono">Apps.vue</code> · +4 / -2</span>
                <button className="vibe-ai-apply-btn">查看 diff</button>
              </div>
              <div className="vibe-ai-applied">
                <I.check size={11} />
                <span>已修改 <code className="mono">useAppsFilter.ts</code> · +12 / -3</span>
                <button className="vibe-ai-apply-btn">查看 diff</button>
              </div>
            </div>
            <div className="vibe-ai-msg vibe-ai-msg-user">
              <div className="vibe-ai-bubble">tab-count 还是旧的，能同步过滤吗？</div>
            </div>
            <div className="vibe-ai-msg vibe-ai-msg-ai">
              <div className="vibe-ai-bubble">
                <div className="typing-dots"><span /><span /><span /></div>
              </div>
            </div>
          </div>

          <div className="vibe-ai-context">
            <span className="vibe-ai-context-label">上下文</span>
            <span className="vibe-ai-context-chip"><I.code size={10} /> Apps.vue</span>
            <span className="vibe-ai-context-chip"><I.code size={10} /> useAppsFilter.ts</span>
            <button className="vibe-ai-context-add">+ 添加文件</button>
          </div>

          <div className="vibe-ai-composer">
            <textarea
              className="vibe-ai-input"
              placeholder="选中代码后按 ⌘L 唤起对话；或在这里继续提问…"
              value={aiInput}
              onChange={(e) => setAiInput(e.target.value)}
              rows={2}
            />
            <div className="vibe-ai-foot">
              <div style={{ display: 'flex', gap: 4 }}>
                <button className="vibe-ai-mode active">代理模式</button>
                <button className="vibe-ai-mode">询问模式</button>
              </div>
              <button className="btn btn-primary btn-sm" disabled={!aiInput.trim()}>
                发送 <I.send size={11} />
              </button>
            </div>
          </div>
        </aside>
      )}
    </div>
  );
}

// Token-based highlighter — avoids recursive replacements by building
// the output from non-overlapping tokens, so html-to-image can serialize.
function highlightLine(t) {
  if (!t) return '';
  const out = [];
  let i = 0;
  const push = (cls, txt) => out.push(`<span class="hl-${cls}">${esc(txt)}</span>`);
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  // Comment first — covers everything else
  const cmt = t.match(/^(\s*)(<!--.+?-->)(.*)$/);
  if (cmt) return esc(cmt[1]) + `<span class="hl-cmt">${esc(cmt[2])}</span>` + esc(cmt[3]);

  while (i < t.length) {
    const rest = t.slice(i);

    // String literal
    const str = rest.match(/^("[^"]*"|'[^']*')/);
    if (str) { push('str', str[0]); i += str[0].length; continue; }

    // Opening or closing tag head: <tag, </tag
    const tag = rest.match(/^(<\/?)([A-Za-z][\w-]*)/);
    if (tag) {
      out.push(`<span class="hl-punct">${esc(tag[1])}</span><span class="hl-tag">${esc(tag[2])}</span>`);
      i += tag[0].length; continue;
    }

    // Attribute (after space, before =)
    const attr = rest.match(/^(\s+)([:@v]?[\w-]+)(?==)/);
    if (attr) {
      out.push(esc(attr[1]) + `<span class="hl-attr">${esc(attr[2])}</span>`);
      i += attr[0].length; continue;
    }

    // Vue directive keyword bare
    const kw = rest.match(/^(v-for|v-if|v-model|v-show)\b/);
    if (kw) { push('key', kw[0]); i += kw[0].length; continue; }

    out.push(esc(t[i]));
    i++;
  }
  return out.join('');
}

window.VibePage = VibePage;
