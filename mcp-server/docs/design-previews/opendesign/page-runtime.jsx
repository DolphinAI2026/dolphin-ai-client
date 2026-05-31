// 运行与发布 (Runtime & Release)
// One page, four tabs:
//   1. 沙箱   — code-server / 睿鲸 containers per workspace
//   2. 流水线 — CI/CD runs (睿鲸 组件 + Vibe push + 应用增量部署)
//   3. 平台环境 — dev / test / prod aPaaS connections
//   4. 部署历史 — every deployment with rollback

function Runtime() {
  const { navigate } = useContext(RouteCtx);
  const { sandboxes, pipelines, environments, deployments } = window.MOCK;
  const [tab, setTab] = useState('sandboxes');
  const [selectedRun, setSelectedRun] = useState(pipelines[0].id);

  const cur = pipelines.find(p => p.id === selectedRun) || pipelines[0];

  const stats = [
    { label: '运行中沙箱', v: sandboxes.filter(s => s.status === 'active').length, sub: `共 ${sandboxes.length} 个 · 平均空闲 18 min`, tone: 'ok' },
    { label: '今日构建',   v: pipelines.length, sub: `${pipelines.filter(p => p.status === 'failed').length} 失败 · ${pipelines.filter(p => p.status === 'running').length} 进行中`, tone: 'brand' },
    { label: '今日部署',   v: deployments.filter(d => !d.time.includes('/') && !d.time.includes('昨天')).length, sub: '生产 1 · 测试 2', tone: 'info' },
    { label: '生产健康度', v: '99.8%', sub: '过去 7 天', tone: 'warn' },
  ];

  return (
    <div className="page">
      <div className="page-pad" style={{ maxWidth: 1320 }}>
        <div className="page-head">
          <div>
            <h1 className="page-title">运行与发布</h1>
            <div className="page-subtitle">
              统一查看：睿鲸 / Vibe 沙箱、CI/CD 流水线、得帆云 dev / test / prod 三套环境、所有应用与组件的部署历史。
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary"><I.book size={13} /> 配置策略</button>
            <button className="btn btn-secondary"><I.refresh size={13} /> 强制刷新</button>
          </div>
        </div>

        {/* Top summary */}
        <div className="mcp-summary">
          {stats.map(s => (
            <div key={s.label} className="mcp-summary-card">
              <div className={`mcp-summary-icon mcp-tone-${s.tone}`}>
                {s.tone === 'ok'    && <I.check size={16} />}
                {s.tone === 'brand' && <I.zap size={16} />}
                {s.tone === 'info'  && <I.cloud size={16} />}
                {s.tone === 'warn'  && <I.shield size={16} />}
              </div>
              <div>
                <div className="mcp-summary-v">{s.v}</div>
                <div className="mcp-summary-l">{s.label}</div>
                <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>{s.sub}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div className="apps-tabs" style={{ marginTop: 20 }}>
          {[
            { k: 'sandboxes', l: '沙箱',     c: sandboxes.length, ic: 'cloud' },
            { k: 'pipelines', l: '流水线',   c: pipelines.length, ic: 'zap' },
            { k: 'envs',      l: '平台环境', c: environments.length, ic: 'admin' },
            { k: 'history',   l: '部署历史', c: deployments.length, ic: 'book' },
          ].map(t => {
            const Ic = I[t.ic];
            return (
              <button key={t.k} className={`apps-tab ${tab === t.k ? 'active' : ''}`} onClick={() => setTab(t.k)}>
                <Ic size={13} /> {t.l}
                <span className="apps-tab-count">{t.c}</span>
              </button>
            );
          })}
        </div>

        {/* ── Tab: Sandboxes ── */}
        {tab === 'sandboxes' && (
          <div style={{ marginTop: 14 }}>
            <div className="rt-banner">
              <I.cloud size={14} />
              <div>
                <b>沙箱托管在阿里云 ECS 集群。</b>
                睿鲸沙箱用于组件构建（2C/4G 默认），Vibe 沙箱用于 code-server 编辑（4C/8G 默认）。
                空闲 2 小时后自动回收，活动时 TTL 自动续期。
              </div>
              <button className="btn btn-secondary btn-sm"><I.gear size={12} /> 配置策略</button>
            </div>

            <div className="card" style={{ padding: 0, overflow: 'hidden', marginTop: 14 }}>
              <div className="rt-table-head">
                <div style={{ flex: 1.6 }}>沙箱</div>
                <div style={{ width: 90 }}>类型</div>
                <div style={{ width: 220 }}>CPU / 内存 / 磁盘</div>
                <div style={{ width: 100 }}>空闲</div>
                <div style={{ width: 120 }}>TTL</div>
                <div style={{ width: 100 }}>状态</div>
                <div style={{ width: 110, textAlign: 'right' }}>操作</div>
              </div>
              {sandboxes.map(s => (
                <div key={s.id} className="rt-table-row">
                  <div style={{ flex: 1.6, minWidth: 0 }}>
                    <div className="rt-row-name">
                      <span className={`rt-dot rt-dot-${s.status}`} />
                      <span style={{ fontWeight: 500 }}>{s.name}</span>
                    </div>
                    <div className="rt-row-meta">
                      <span className="mono">{s.id}</span>
                      <span>·</span>
                      <span>{s.user}</span>
                      <span>·</span>
                      <span className="mono" style={{ color: 'var(--text-3)' }}>{s.image}</span>
                    </div>
                  </div>
                  <div style={{ width: 90 }}>
                    <span className={`badge ${s.flavor === '睿鲸' ? 'badge-brand' : 'badge-emerald'}`}>{s.flavor}</span>
                  </div>
                  <div style={{ width: 220 }}>
                    <ResourceBar label={`${s.cpu.toFixed(1)} / ${s.cpuMax} vCPU`} value={s.cpu / s.cpuMax} />
                    <ResourceBar label={`${s.mem.toFixed(1)} / ${s.memMax} GB`}  value={s.mem / s.memMax} small />
                    <ResourceBar label={`${s.disk.toFixed(1)} GB 磁盘`}            value={s.disk / 10}    small dim />
                  </div>
                  <div style={{ width: 100, fontSize: 12.5, color: s.idle === '0 min' ? 'var(--emerald)' : 'var(--text-3)' }}>
                    {s.idle === '0 min' ? '● 活动中' : s.idle}
                  </div>
                  <div style={{ width: 120, fontSize: 12, color: s.status === 'recycling' ? 'var(--rose)' : 'var(--text-2)' }} className="mono">
                    {s.ttl}
                  </div>
                  <div style={{ width: 100 }}>
                    <StatusChip status={s.status} />
                  </div>
                  <div style={{ width: 110, display: 'flex', justifyContent: 'flex-end', gap: 4 }}>
                    {s.flavor === 'Vibe' ? (
                      <button className="btn btn-secondary btn-sm" onClick={() => navigate('/vibe')}>打开</button>
                    ) : (
                      <button className="btn btn-secondary btn-sm" onClick={() => navigate('/coding')}>打开</button>
                    )}
                    <button className="icon-btn" style={{ width: 26, height: 26 }} title="重启"><I.refresh size={12} /></button>
                    <button className="icon-btn" style={{ width: 26, height: 26, color: 'var(--rose)' }} title="终止"><I.trash size={12} /></button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Tab: Pipelines ── */}
        {tab === 'pipelines' && (
          <div className="rt-pipeline-layout">
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div className="rt-table-head">
                <div style={{ width: 12 }} />
                <div style={{ flex: 1 }}>流水线</div>
                <div style={{ width: 72 }}>来源</div>
                <div style={{ width: 64, textAlign: 'right' }}>耗时</div>
                <div style={{ width: 80 }}>状态</div>
              </div>
              {pipelines.map(p => (
                <button key={p.id} className={`rt-table-row rt-pipe-row ${selectedRun === p.id ? 'active' : ''}`} onClick={() => setSelectedRun(p.id)}>
                  <div style={{ width: 12, color: 'var(--text-4)' }}>
                    {selectedRun === p.id ? <I.chevronR size={11} /> : ''}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="rt-row-name">
                      <span style={{ fontWeight: 500 }} className="truncate">{p.name}</span>
                      <span className={`badge ${p.trigger === '自动' ? 'badge-brand' : ''}`} style={{ flexShrink: 0 }}>{p.trigger}</span>
                    </div>
                    <div className="rt-row-meta">
                      <span className="mono">#{p.id.replace('run-', '')}</span>
                      {p.commit && <><span>·</span><span className="mono">{p.commit}</span></>}
                      {p.branch && <><span>·</span><span className="truncate">{p.branch}</span></>}
                      {p.env && <><span>·</span><span>{envLabel(p.env)}</span></>}
                      <span>·</span>
                      <span>{p.time}</span>
                    </div>
                  </div>
                  <div style={{ width: 72, fontSize: 11, color: 'var(--text-3)' }} className="truncate">{p.source}</div>
                  <div style={{ width: 64, fontSize: 12, color: 'var(--text-2)', textAlign: 'right' }} className="mono">
                    {p.durationS > 0 ? formatDuration(p.durationS) : '—'}
                  </div>
                  <div style={{ width: 80 }}>
                    <PipelineStatus status={p.status} />
                  </div>
                </button>
              ))}
            </div>

            {/* Run detail */}
            <div className="card card-pad rt-run-detail">
              <div className="rt-run-head">
                <div>
                  <div className="rt-run-title">
                    {cur.name}
                    <span className="mono rt-run-id">#{cur.id.replace('run-', '')}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                    <PipelineStatus status={cur.status} />
                    <span>·</span>
                    <span>{cur.source}</span>
                    <span>·</span>
                    <span>由 <b>{cur.user}</b> {cur.trigger === '自动' ? '自动触发' : '手动触发'}</span>
                    <span>·</span>
                    <span>{cur.time}</span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="btn btn-secondary btn-sm"><I.book size={12} /> 查看日志</button>
                  {cur.status === 'failed' && <button className="btn btn-primary btn-sm"><I.refresh size={12} /> 重试</button>}
                </div>
              </div>

              {/* Stage chain */}
              <div className="rt-stages">
                {cur.stages.map((s, i) => (
                  <React.Fragment key={i}>
                    <div className={`rt-stage rt-stage-${s.status}`}>
                      <div className="rt-stage-dot">
                        {s.status === 'done'    && <I.check size={11} />}
                        {s.status === 'running' && <span className="coding-tab-spinner" />}
                        {s.status === 'failed'  && <span style={{ fontWeight: 700, fontSize: 12 }}>!</span>}
                        {s.status === 'skip'    && <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'currentColor', display: 'block' }} />}
                        {s.status === 'pending' && <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'currentColor', display: 'block' }} />}
                      </div>
                      <div className="rt-stage-body">
                        <div className="rt-stage-name">{s.name}</div>
                        <div className="rt-stage-dur mono">
                          {s.status === 'done' && formatDuration(s.durationS)}
                          {s.status === 'running' && formatDuration(s.durationS) + ' …'}
                          {s.status === 'failed' && formatDuration(s.durationS)}
                          {s.status === 'skip' && '已跳过'}
                          {s.status === 'pending' && '—'}
                        </div>
                        {s.error && <div className="rt-stage-error mono">{s.error}</div>}
                      </div>
                    </div>
                    {i < cur.stages.length - 1 && <div className="rt-stage-conn" />}
                  </React.Fragment>
                ))}
              </div>

              {cur.status === 'failed' && (
                <div className="rt-log">
                  <div className="rt-log-head">
                    <I.bell size={12} style={{ color: 'var(--rose)' }} />
                    <span>构建失败 · 关键日志</span>
                    <button className="section-action" style={{ marginLeft: 'auto' }}>查看完整日志 →</button>
                  </div>
                  <pre className="rt-log-body mono">{`  ▸ npm run build:component --name=客户工单看板
  ▸ vite v5.4.2 building...
  × form-list/index.vue:48:14
       SyntaxError: Unexpected token "}" in template
       46 |   :data="list"
       47 |   :sla-threshold="threshold"
    ▶ 48 |   @sort="onSort}    ← 缺少右引号
       49 | />`}</pre>
                  <div className="rt-log-foot">
                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>提示：你可以在</span>
                    <button className="landing-pill" onClick={() => navigate('/coding')}>睿鲸 ws-2 工作区</button>
                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>里让 AI 修复并重新生成</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Tab: Environments ── */}
        {tab === 'envs' && (
          <div style={{ marginTop: 14 }}>
            <div className="rt-banner">
              <I.cloud size={14} />
              <div>
                <b>本租户固定对接 1 套得帆云租户。</b>
                同一租户下配置 3 个环境（dev / test / prod），用于隔离开发、测试、生产。
                默认部署到「测试环境」，确认无误后晋级到生产。
              </div>
              <button className="btn btn-secondary btn-sm"><I.plus size={12} /> 添加环境</button>
            </div>

            <div className="rt-env-grid">
              {environments.map(e => (
                <div key={e.id} className={`rt-env-card rt-env-${e.id}`}>
                  <div className="rt-env-head">
                    <div className="rt-env-stripe" />
                    <div className="rt-env-titles">
                      <div className="rt-env-name">
                        {e.name}
                        {e.default && <span className="badge badge-brand" style={{ marginLeft: 6 }}>默认</span>}
                      </div>
                      <div className="rt-env-host">
                        <span className={`rt-env-status rt-env-status-${e.health}`}>
                          <span className="rt-env-status-dot" /> {e.health === 'ok' ? '健康' : '需关注'}
                        </span>
                        <span>·</span>
                        <span>心跳 {e.heartbeat}</span>
                      </div>
                    </div>
                    <button className="icon-btn" style={{ width: 28, height: 28 }} title="测试连接"><I.refresh size={14} /></button>
                  </div>

                  <div className="rt-env-grid-meta">
                    <div>
                      <div className="rt-env-label">Endpoint</div>
                      <div className="rt-env-val mono truncate">{e.endpoint}</div>
                    </div>
                    <div>
                      <div className="rt-env-label">租户</div>
                      <div className="rt-env-val truncate">{e.tenantName}</div>
                      <div className="mono" style={{ fontSize: 10.5, color: 'var(--text-3)' }}>{e.tenant}</div>
                    </div>
                    <div>
                      <div className="rt-env-label">已部署应用</div>
                      <div className="rt-env-val">{e.deployedApps} 个</div>
                    </div>
                    <div>
                      <div className="rt-env-label">API Key 到期</div>
                      <div className="rt-env-val" style={{ color: e.keyWarn ? 'var(--amber)' : undefined }}>
                        {e.keyWarn && <I.bell size={11} style={{ verticalAlign: '-1px', marginRight: 4 }} />}
                        {e.keyExpiry}
                      </div>
                    </div>
                  </div>

                  <div className="rt-env-actions">
                    <button className="btn btn-secondary btn-sm"><I.external size={12} /> 打开 aPaaS</button>
                    <button className="btn btn-secondary btn-sm"><I.gear size={12} /> 配置</button>
                    <button className="btn btn-primary btn-sm" disabled={e.id === 'prod'}>
                      晋级从 {e.id === 'dev' ? 'dev' : 'test'} →
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Tab: Deployment history ── */}
        {tab === 'history' && (
          <div style={{ marginTop: 14 }}>
            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div className="rt-table-head">
                <div style={{ flex: 1.3 }}>应用 / 组件</div>
                <div style={{ width: 70 }}>环境</div>
                <div style={{ width: 80 }}>版本</div>
                <div style={{ flex: 1.4 }}>变更</div>
                <div style={{ width: 70 }}>触发者</div>
                <div style={{ width: 70 }}>耗时</div>
                <div style={{ width: 70 }}>状态</div>
                <div style={{ width: 100, textAlign: 'right' }}>操作</div>
              </div>
              {deployments.map(d => (
                <div key={d.id} className="rt-table-row">
                  <div style={{ flex: 1.3, minWidth: 0 }}>
                    <div className="rt-row-name" style={{ fontWeight: 500 }}>{d.app}</div>
                    <div className="rt-row-meta">
                      <span className="mono">{d.appCode}</span>
                      <span>·</span>
                      <span className="mono">{d.id}</span>
                      <span>·</span>
                      <span>{d.time}</span>
                    </div>
                  </div>
                  <div style={{ width: 70 }}>
                    <span className={`rt-env-chip rt-env-chip-${d.env}`}>{envLabel(d.env)}</span>
                  </div>
                  <div style={{ width: 80 }} className="mono">{d.version}</div>
                  <div style={{ flex: 1.4, fontSize: 12, color: d.status === 'failed' ? 'var(--rose)' : 'var(--text-2)' }} className="truncate">
                    {d.changes}{d.error && <span className="mono" style={{ color: 'var(--rose)', marginLeft: 6 }}>· {d.error}</span>}
                  </div>
                  <div style={{ width: 70, fontSize: 12, color: 'var(--text-2)' }} className="truncate">{d.user}</div>
                  <div style={{ width: 70, fontSize: 12, color: 'var(--text-3)' }} className="mono">{d.duration}</div>
                  <div style={{ width: 70 }}><PipelineStatus status={d.status} /></div>
                  <div style={{ width: 100, display: 'flex', justifyContent: 'flex-end', gap: 4 }}>
                    {d.status === 'success' && d.env !== 'dev' && (
                      <button className="btn btn-secondary btn-sm" title="回滚至上一版本"><I.refresh size={11} /> 回滚</button>
                    )}
                    <button className="icon-btn" style={{ width: 26, height: 26 }}><I.more size={14} /></button>
                  </div>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'center', marginTop: 14 }}>
              <button className="btn btn-secondary btn-sm">加载更早历史</button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}

/* helpers */
function envLabel(e) {
  return e === 'dev' ? '开发' : e === 'test' ? '测试' : e === 'prod' ? '生产' : e;
}
function formatDuration(s) {
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60), r = s - m * 60;
  return `${m}m ${r}s`;
}

function ResourceBar({ label, value, small, dim }) {
  const v = Math.max(0, Math.min(1, value));
  const tone = v > 0.85 ? 'rose' : v > 0.6 ? 'amber' : 'brand';
  return (
    <div className={`rt-resbar ${small ? 'is-small' : ''} ${dim ? 'is-dim' : ''}`}>
      <div className="rt-resbar-track">
        <div className={`rt-resbar-fill rt-resbar-${tone}`} style={{ width: (v * 100) + '%' }} />
      </div>
      <div className="rt-resbar-label">{label}</div>
    </div>
  );
}

function StatusChip({ status }) {
  const m = {
    active:    { label: '运行中', cls: 'badge-emerald' },
    idle:      { label: '空闲',   cls: 'badge-amber' },
    recycling: { label: '回收中', cls: 'badge-rose' },
  }[status] || { label: status, cls: '' };
  return <span className={`badge ${m.cls}`}><span className="badge-dot" />{m.label}</span>;
}

function PipelineStatus({ status }) {
  const m = {
    running: { label: '进行中', cls: 'badge-brand' },
    success: { label: '成功',   cls: 'badge-emerald' },
    failed:  { label: '失败',   cls: 'badge-rose' },
    pending: { label: '排队中', cls: 'badge-amber' },
    skip:    { label: '跳过',   cls: '' },
  }[status] || { label: status, cls: '' };
  return <span className={`badge ${m.cls}`}><span className="badge-dot" />{m.label}</span>;
}

window.Runtime = Runtime;
