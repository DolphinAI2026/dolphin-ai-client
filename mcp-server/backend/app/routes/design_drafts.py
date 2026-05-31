"""Design Drafts HTTP API — 给用户直接打开的预览页。

提供：
  GET  /design-preview/{draft_id}              直出 HTML（无鉴权，靠 draft_id 不可枚举）
  GET  /api/design-drafts/{draft_id}/spec      返回 spec_json（admin-spa 也可用）
  POST /api/design-drafts/{draft_id}/promote   触发部署

draft_id 是 12 字符随机 hex (48 bits 熵)，等同 google-doc / notion 的 "anyone with link"。
"""
from __future__ import annotations
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.draft_service import (
    get_draft_spec as _get_spec,
    promote_draft_to_app as _promote,
)

logger = logging.getLogger(__name__)

# API router（admin-spa / 其他客户端用）
router = APIRouter(prefix="/design-drafts", tags=["design-drafts"])
# HTML router（用户直接打开）
html_router = APIRouter(tags=["design-preview"])


class PromoteRequest(BaseModel):
    env: str


@router.get("/{draft_id}/spec")
async def get_draft_spec(
    draft_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """返回 draft 的完整 spec_json + 元信息（无鉴权）。"""
    res = await _get_spec(db, draft_id)
    if not res.get("ok"):
        raise HTTPException(status_code=404, detail=res)
    return res


@router.post("/{draft_id}/promote")
async def promote_draft(
    draft_id: str,
    body: PromoteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """触发 promote：创建应用 + 部署到 aPaaS。"""
    res = await _promote(db, draft_id=draft_id, env=body.env)
    return res


@html_router.get("/design-preview/{draft_id}", response_class=HTMLResponse)
async def render_preview_html(
    draft_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    """直出 HTML 预览页（无鉴权）。"""
    res = await _get_spec(db, draft_id)
    if not res.get("ok"):
        return HTMLResponse(_render_not_found(draft_id), status_code=404)
    return HTMLResponse(_render_preview(res))


# ───────────────────────────── HTML 渲染 ─────────────────────────────

def _render_not_found(draft_id: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>设计文档不存在</title>
<style>body{{font-family:-apple-system,sans-serif;padding:60px;text-align:center;color:#606266}}
h1{{color:#f56c6c}}code{{background:#f4f4f5;padding:2px 8px;border-radius:3px}}</style></head>
<body><h1>设计文档不存在</h1><p>设计文档 <code>{draft_id}</code> 找不到，可能已被覆盖或链接错误。</p></body></html>"""


def _safe(s: str) -> str:
    return (s or "").replace("<", "&lt;").replace(">", "&gt;")


def _render_preview(data: dict) -> str:
    """渲染整页 HTML。spec_json 嵌入 <script> 标签，浏览器端 JS 渲染三个预览页。"""
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    title = _safe(data.get("summary") or "设计文档预览")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
<div id="root">加载中…</div>
<script id="data" type="application/json">{payload}</script>
<script>{_JS}</script>
</body>
</html>"""


_CSS = """
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f7fa; color: #303133; }
.header { background: #fff; padding: 20px 40px; border-bottom: 1px solid #e4e7ed; display: flex; justify-content: space-between; align-items: flex-start; }
.header h1 { margin: 0 0 6px; font-size: 22px; }
.header .meta { color: #909399; font-size: 13px; }
.header .meta span { margin-right: 24px; }
.header .meta code { background: #f4f4f5; padding: 1px 6px; border-radius: 3px; font-size: 12px; color: #5e6d82; }
.status { font-size: 12px; padding: 2px 10px; border-radius: 10px; display: inline-block; }
.status.active { background: #fdf6ec; color: #e6a23c; }
.status.promoted { background: #f0f9eb; color: #67c23a; }
.status.applied { background: #f0f9eb; color: #67c23a; }
.status.superseded { background: #e9e9eb; color: #909399; }
.status.failed { background: #fef0f0; color: #f56c6c; }
.actions a { display: inline-block; padding: 6px 16px; background: #409eff; color: #fff; text-decoration: none; border-radius: 4px; font-size: 13px; }
.tabs { background: #fff; padding: 0 40px; border-bottom: 1px solid #e4e7ed; display: flex; gap: 4px; }
.tab { padding: 14px 20px; cursor: pointer; border-bottom: 2px solid transparent; color: #606266; font-size: 14px; user-select: none; }
.tab.active { color: #409eff; border-bottom-color: #409eff; font-weight: 500; }
.container { padding: 24px 40px; }
.view { display: none; } .view.active { display: block; }
.stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 20px; }
.stat { background: #fff; padding: 18px 20px; border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
.stat .label { color: #909399; font-size: 12px; }
.stat .value { font-size: 28px; font-weight: 600; margin-top: 4px; }
.card { background: #fff; border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,.04); margin-bottom: 16px; overflow: hidden; }
.card-h { padding: 14px 20px; border-bottom: 1px solid #ebeef5; font-weight: 600; font-size: 15px; display: flex; align-items: center; gap: 8px; }
.card-h .badge { background: #ecf5ff; color: #409eff; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 500; }
.card-b { padding: 16px 20px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #f0f2f5; vertical-align: top; }
th { background: #fafafa; color: #606266; font-weight: 500; }
tr:last-child td { border-bottom: 0; }
code { font-family: SFMono-Regular, Consolas, monospace; color: #5e6d82; font-size: 12px; background: #f4f4f5; padding: 1px 6px; border-radius: 3px; }
.tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; margin-right: 4px; margin-bottom: 2px; }
.tag-grey { background: #e9e9eb; color: #909399; }
.tag-blue { background: #d9ecff; color: #409eff; }
.tag-orange { background: #faecd8; color: #e6a23c; }
.perm-cell { text-align: center; font-size: 12px; }
.perm-cell .ops { color: #67c23a; font-weight: 500; }
.perm-cell .scope { color: #909399; font-size: 11px; margin-top: 2px; }
.perm-cell.empty { color: #c0c4cc; }
.wf-layout { display: grid; grid-template-columns: 220px 1fr; gap: 16px; }
.wf-list { background: #fff; border-radius: 6px; padding: 8px 0; box-shadow: 0 1px 2px rgba(0,0,0,.04); min-height: 600px; }
.wf-item { padding: 12px 16px; cursor: pointer; border-left: 3px solid transparent; }
.wf-item:hover { background: #f5f7fa; }
.wf-item.active { background: #ecf5ff; border-left-color: #409eff; }
.wf-item.active .name { color: #409eff; }
.wf-item .name { font-size: 14px; font-weight: 500; }
.wf-item .desc { font-size: 11px; color: #909399; margin-top: 4px; }
.wf-canvas { background: #fff; border-radius: 6px; padding: 24px; box-shadow: 0 1px 2px rgba(0,0,0,.04); min-height: 600px; }
.wf-title { font-size: 18px; font-weight: 600; margin: 0 0 6px; }
.wf-desc { color: #909399; font-size: 13px; margin-bottom: 16px; }
.wf-meta { display: flex; gap: 18px; padding: 12px 16px; background: #f0f9eb; border-left: 3px solid #67c23a; border-radius: 3px; margin-bottom: 16px; font-size: 12px; color: #606266; }
.wf-meta b { color: #303133; }
.wf-section-title { font-size: 13px; color: #909399; padding: 12px 0 8px; border-bottom: 1px dashed #dcdfe6; margin-bottom: 14px; letter-spacing: 1px; }
.wf-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 20px; margin-bottom: 20px; }
.field { background: #fafafa; border: 1px solid #ebeef5; border-radius: 4px; padding: 10px 14px; }
.field.full { grid-column: 1 / -1; }
.field-label { font-size: 12px; color: #606266; margin-bottom: 6px; display: flex; align-items: center; }
.field-label .req { color: #f56c6c; }
.field-flags { margin-left: auto; display: flex; gap: 4px; }
.flag { padding: 1px 6px; border-radius: 8px; font-size: 10px; }
.flag.flag-grey { background: #e9e9eb; color: #909399; }
.flag.flag-blue { background: #d9ecff; color: #409eff; }
.flag.flag-orange { background: #faecd8; color: #e6a23c; }
.comp { background: #fff; border: 1px solid #dcdfe6; border-radius: 3px; padding: 8px 12px; min-height: 32px; color: #c0c4cc; font-size: 13px; display: flex; align-items: center; }
.comp .comp-text { flex: 1; }
.comp .comp-icon { margin-left: auto; color: #909399; }
.comp.upload { border-style: dashed; justify-content: center; color: #909399; padding: 16px; min-height: 60px; }
.comp.textarea { min-height: 60px; align-items: flex-start; }
.comp.reflink { border-style: dashed; color: #409eff; background: #fafcff; }
.subtable { background: #fafafa; border: 1px solid #ebeef5; border-radius: 4px; padding: 12px; margin-bottom: 16px; }
.subtable th { background: #f0f2f5; padding: 8px 10px; font-size: 12px; border: 1px solid #dcdfe6; }
.subtable td { padding: 8px 10px; border: 1px solid #ebeef5; background: #fff; color: #c0c4cc; font-size: 12px; }
.relation-canvas { display: grid; grid-template-columns: .8fr 1.2fr; gap: 16px; margin-bottom: 14px; }
.relation-group { border: 1px solid #ebeef5; border-radius: 6px; padding: 14px; background: #fafafa; display: grid; gap: 10px; align-content: start; }
.relation-title { color: #909399; font-size: 12px; font-weight: 600; }
.relation-node { border: 1px solid #dcdfe6; border-radius: 6px; padding: 12px; background: #fff; min-height: 62px; }
.relation-node.participant { border-color: #d9ecff; background: #f5faff; }
.relation-node .title { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.relation-node .desc { color: #909399; font-size: 12px; line-height: 1.5; }
.relation-list { display: flex; flex-wrap: wrap; gap: 8px; }
.relation-line { display: inline-flex; align-items: center; gap: 8px; padding: 7px 10px; border: 1px solid #ebeef5; border-radius: 6px; background: #fff; color: #606266; font-size: 12px; }
.relation-line b { color: #409eff; font-weight: 600; }
.biz-grid { display: grid; grid-template-columns: 1.2fr .8fr; gap: 16px; align-items: start; }
.object-list { display: grid; gap: 10px; }
.object-row { display: grid; grid-template-columns: 170px 1fr; gap: 12px; padding: 12px; border: 1px solid #ebeef5; border-radius: 6px; background: #fafafa; }
.object-name { font-weight: 600; }
.object-code { margin-top: 4px; }
.cap-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 14px; }
.cap { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 10px; font-size: 11px; background: #e9e9eb; color: #606266; }
.cap.on { background: #f0f9eb; color: #67c23a; }
.cap.import { background: #faecd8; color: #e6a23c; }
.process-list { display: grid; gap: 16px; }
.process-card { background: #fff; border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,.04); padding: 18px 20px; }
.process-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 14px; }
.process-title { font-size: 16px; font-weight: 600; }
.process-meta { color: #909399; font-size: 12px; margin-top: 4px; }
.process-nodes { display: flex; flex-wrap: wrap; align-items: stretch; gap: 10px; }
.process-node { min-width: 128px; max-width: 190px; border: 1px solid #dcdfe6; border-radius: 6px; padding: 10px 12px; background: #fafafa; position: relative; }
.process-node:not(:last-child)::after { content: "→"; position: absolute; right: -13px; top: 26px; color: #c0c4cc; font-weight: 600; }
.process-node.start { border-color: #b3e19d; background: #f0f9eb; }
.process-node.end { border-color: #fab6b6; background: #fef0f0; }
.process-node .name { font-weight: 600; font-size: 13px; }
.process-node .role { color: #909399; font-size: 11px; margin-top: 4px; }
.empty-state { padding: 56px 20px; text-align: center; color: #909399; background: #fff; border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
@media (max-width: 900px) { .stats { grid-template-columns: 1fr 1fr; } .relation-canvas, .biz-grid, .wf-layout { grid-template-columns: 1fr; } .process-node:not(:last-child)::after { display: none; } }
"""


_JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const S = D.spec || {};
const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const isTrue = (v) => v === true || v === 1 || ['是','true','1','yes'].includes(String(v||'').toLowerCase());
const roles = S.roles || [];
const dicts = S.dicts || [];
const models = S.models || S.dataModels || [];
const forms = S.forms || [];
const perms = S.permissions || [];
const workflows = S.workflows || S.flows || S.processes || [];
const appName = S.appName || S.app_name || '未命名应用';
const appCode = S.appCode || S.app_code || '';
const appDesc = S.appDesc || S.app_desc || '';
const adminUrl = D.admin_url ? `<div class="actions"><a href="${esc(D.admin_url)}" target="_blank">打开 aPaaS 后台 →</a></div>` : '';
const permRulesCount = perms.reduce((s, p) => s + ((p.rules || p.permissionRules || []).length), 0);
let activeFormIdx = 0;
let activeProcessIdx = 0;

document.getElementById('root').innerHTML = `
<div class="header"><div>
  <h1>${esc(appName)}</h1>
  <div class="meta">
    <span>应用编码 <code>${esc(appCode || '—')}</code></span>
    ${appDesc ? `<span>说明 ${esc(appDesc)}</span>` : ''}
    <span>设计文档 <code>${esc(D.draft_id)}</code></span>
    <span class="status ${esc(D.status)}">${esc(D.status)}</span>
  </div>
</div>${adminUrl}</div>
<div class="tabs"><div class="tab active" data-v="1">业务流程</div><div class="tab" data-v="2">表单线框图</div><div class="tab" data-v="3">流程图/审批流</div></div>
<div class="container"><div class="view active" id="v1"></div><div class="view" id="v2"></div><div class="view" id="v3"></div></div>`;

document.getElementById('v1').innerHTML = renderBusinessFlow();
document.getElementById('v2').innerHTML = renderWireframes();
document.getElementById('v3').innerHTML = renderProcessFlow();

document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.view').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  document.getElementById('v' + t.dataset.v).classList.add('active');
});

function renderBusinessFlow() {
  return `<div class="stats">
    <div class="stat"><div class="label">角色</div><div class="value">${roles.length}</div></div>
    <div class="stat"><div class="label">字典</div><div class="value">${dicts.length}</div></div>
    <div class="stat"><div class="label">数据模型</div><div class="value">${models.length}</div></div>
    <div class="stat"><div class="label">表单</div><div class="value">${forms.length}</div></div>
    <div class="stat"><div class="label">流程</div><div class="value">${workflows.length}</div></div>
  </div>
  ${businessJourney()}
  <div class="biz-grid">
    <div>${formsCard()}${modelsCard()}</div>
    <div>${rolesCard()}${dictsCard()}</div>
  </div>
  ${permMatrix()}`;
}

function businessJourney() {
  const map = businessRelationMap();
  return `<div class="card"><div class="card-h">主体业务关系 <span class="badge">平台人员/部门引用</span></div>
    <div class="card-b">
      <div class="relation-canvas">
        <div class="relation-group">
          <div class="relation-title">平台参与方</div>
          ${map.participants.map(item => `<div class="relation-node participant"><div class="title">${esc(item.name)}</div><div class="desc">${esc(item.desc || '')}</div></div>`).join('')}
        </div>
        <div class="relation-group objects">
          <div class="relation-title">核心业务对象</div>
          ${map.objects.map(item => `<div class="relation-node"><div class="title">${esc(item.name)}</div>${item.code ? `<code>${esc(item.code)}</code>` : ''}</div>`).join('')}
        </div>
      </div>
      <div class="relation-list">${map.relations.map(rel => `
        <div class="relation-line"><span>${esc(rel.from)}</span><b>${esc(rel.label)}</b><span>${esc(rel.to)}</span></div>
      `).join('')}</div>
    </div></div>`;
}

function businessRelationMap() {
  const objects = businessObjects();
  const primary = primaryObject(objects);
  const participants = [
    {key:'all_people', name:'全体人员', desc:'平台用户'},
    {key:'department', name:'所属部门', desc:'平台部门'},
  ];
  const relations = [];
  if (primary) {
    relations.push({from:'全体人员', label:'提交/维护', to:primary.name});
    relations.push({from:'所属部门', label:'归属', to:primary.name});
    for (const item of objects) {
      if (item.key === primary.key) continue;
      relations.push({from:primary.name, label:relationLabel(item.name), to:item.name});
    }
  }
  return {participants, objects: objects.length ? objects : [{key:'empty', name:'业务对象待补充'}], relations};
}
function businessObjects() {
  const source = forms.length ? forms : models;
  const seen = new Set();
  return (source || []).map(item => ({
    key: String((item && (item.code || item.formCode || item.modelCode || item.name || item.formName || item.modelName)) || ''),
    name: String((item && (item.name || item.formName || item.modelName || item.code || item.formCode || item.modelCode)) || '').replace(/表单$/, ''),
    code: item && (item.code || item.formCode || item.modelCode || ''),
  })).filter(item => {
    if (!item.key || !item.name || seen.has(item.name)) return false;
    seen.add(item.name);
    return true;
  }).slice(0, 6);
}
function primaryObject(objects) {
  return objects.find(item => /预约|申请|订单|工单|任务|计划|单据|记录/.test(item.name)) || objects[0] || null;
}
function relationLabel(name) {
  if (/会议室|房间|场地/.test(name)) return '预订';
  if (/通知|消息/.test(name)) return '生成';
  if (/参会|参与|成员/.test(name)) return '邀请';
  if (/明细|详情|清单/.test(name)) return '包含';
  if (/审批|审核/.test(name)) return '触发';
  return '关联';
}

function rolesCard() {
  if (!roles.length) return '';
  return `<div class="card"><div class="card-h">📋 角色清单 <span class="badge">${roles.length}</span></div>
    <div class="card-b"><table><tr><th>角色编码</th><th>角色名称</th></tr>
    ${roles.map(r => `<tr><td><code>${esc(r.code||r.roleCode)}</code></td><td>${esc(r.name||r.roleName)}</td></tr>`).join('')}
    </table></div></div>`;
}
function dictsCard() {
  if (!dicts.length) return '';
  return `<div class="card"><div class="card-h">📚 数据字典 <span class="badge">${dicts.length}</span></div>
    <div class="card-b"><table><tr><th width="200">字典编码</th><th width="160">字典名称</th><th>选项</th></tr>
    ${dicts.map(d => `<tr>
      <td><code>${esc(d.code || d.dictCode)}</code></td>
      <td>${esc(d.name || d.dictName)}</td>
      <td>${(d.options || d.items || []).map(o => `<span class="tag tag-grey">${esc(o.code||o.value)} ${esc(o.name||o.label)}</span>`).join('')}</td>
    </tr>`).join('')}
    </table></div></div>`;
}
function modelsCard() {
  if (!models.length) return '';
  // 标识哪些是子表模型（被某个 form 当作子表绑定）
  const subModelCodes = new Set();
  for (const f of forms) {
    for (const c of (f.fields||f.components||[])) {
      if (c.sectionType === 'sub' && c.modelCode) subModelCodes.add(c.modelCode);
    }
    for (const s of (f.subForms||[])) {
      if (s.modelCode || s.bindModel) subModelCodes.add(s.modelCode || s.bindModel);
    }
  }
  return `<div class="card"><div class="card-h">🗄 数据模型 <span class="badge">${models.length}</span></div>
    <div class="card-b"><table><tr><th width="220">模型编码</th><th width="160">名称</th><th>字段</th></tr>
    ${models.map(m => {
      const code = m.code || m.modelCode;
      const isSub = subModelCodes.has(code);
      return `<tr>
        <td><code>${esc(code)}</code>${isSub ? ' <span class="tag tag-orange" style="font-size:10px">子表</span>' : ''}</td>
        <td>${esc(m.name||m.modelName)}</td>
        <td>${(m.fields||[]).map(f => `<span class="tag tag-blue">${esc(f.code||f.fieldCode)} ${esc(fieldType(f))}</span>`).join('')}</td>
      </tr>`;
    }).join('')}
    </table></div></div>`;
}
function formsCard() {
  if (!forms.length) return '';
  return `<div class="card"><div class="card-h">📝 表单清单 <span class="badge">${forms.length}</span></div>
    <div class="card-b"><table>
    <tr><th>表单编码</th><th>表单名称</th><th>绑定主表</th><th>主表字段</th><th>子表</th><th>说明</th></tr>
    ${forms.map(f => {
      const c = countMainSub(f);
      // 子表名跟数量一起列在 cell 里：3 主 字段 + (订单明细) 子表
      const subLabels = [];
      for (const cc of (f.fields||f.components||[])) {
        if (cc.sectionType === 'sub') {
          const lab = cc.subTableLabel || cc.subFormName || '子表';
          if (!subLabels.includes(lab)) subLabels.push(lab);
        }
      }
      for (const s of (f.subForms||[])) subLabels.push(s.name||s.subFormName||'子表');
      const subCell = subLabels.length
        ? `<span title="${esc(subLabels.join('、'))}">${c.sub}</span>`
        : '—';
      return `<tr>
        <td><code>${esc(f.code||f.formCode)}</code></td>
        <td>${esc(f.name||f.formName)}</td>
        <td>${getMain(f) ? `<code>${esc(getMain(f))}</code>` : '—'}</td>
        <td>${c.main}</td>
        <td>${subCell}</td>
        <td>${esc(f.description||f.formDesc||'')}</td>
      </tr>`;
    }).join('')}
    </table></div></div>`;
}

function permMatrix() {
  if (!perms.length) return '';
  const rolesSet = new Set();
  const byForm = {};
  perms.forEach(p => {
    const formKey = p.formCode || p.form_code || p.form || '?';
    const formObj = forms.find(f => (f.code||f.formCode)===formKey || (f.name||f.formName)===formKey);
    const formName = (formObj && (formObj.name || formObj.formName)) || formKey;
    if (!byForm[formName]) byForm[formName] = { form: formName };
    (p.rules || p.permissionRules || []).forEach(r => {
      const roleCode = r.role || r.roleCode || 'all';
      const roleObj = roles.find(x => (x.code||x.roleCode) === roleCode);
      const roleName = (roleObj && (roleObj.name||roleObj.roleName)) || (roleCode === 'all' ? '全员' : roleCode);
      rolesSet.add(roleName);
      byForm[formName][roleName] = { ops: fmtOps(r), scope: fmtScope(r.data || r.scope || 'ALL') };
    });
  });
  const rolesList = Array.from(rolesSet);
  return `<div class="card"><div class="card-h">🔒 权限矩阵 <span class="badge">${permRulesCount} 条规则</span></div>
    <div class="card-b"><table>
    <tr><th>表单</th>${rolesList.map(r => `<th style="text-align:center">${esc(r)}</th>`).join('')}</tr>
    ${Object.values(byForm).map(row => `<tr>
      <td><b>${esc(row.form)}</b></td>
      ${rolesList.map(role => row[role]
        ? `<td class="perm-cell"><div class="ops">${esc(row[role].ops)}</div><div class="scope">${esc(row[role].scope)}</div></td>`
        : `<td class="perm-cell empty">—</td>`).join('')}
    </tr>`).join('')}
    </table></div></div>`;
}

function fmtScope(s) {
  const m = {ALL:'全部数据', SELF:'本人数据', CURRENT_USER_DEPT:'本部门数据', CURRENT_USER_DEPT_LOW_LEVEL:'本部门及下级'};
  return m[s] || s;
}

function countMainSub(form) {
  const all = form.fields || form.components || [];
  let main = 0, subLabels = new Set();
  for (const c of all) {
    if (c.sectionType === 'sub') subLabels.add(c.subTableLabel || c.subFormName || '子表');
    else main++;
  }
  // 兼容 form.subForms 显式给的
  for (const s of (form.subForms || [])) subLabels.add(s.name || s.subFormName || '子表');
  return { main, sub: subLabels.size };
}

function renderWireframes() {
  if (!forms.length) return '<div style="padding:60px;text-align:center;color:#c0c4cc">暂无表单</div>';
  const list = forms.map((f, i) => {
    const c = countMainSub(f);
    return `<div class="wf-item ${i === activeFormIdx ? 'active' : ''}" data-i="${i}">
      <div class="name">${esc(f.name||f.formName)}</div>
      <div class="desc">${c.main} 字段 · ${c.sub} 子表</div>
    </div>`;
  }).join('');
  setTimeout(() => {
    document.querySelectorAll('.wf-item').forEach(el => el.onclick = () => {
      activeFormIdx = Number(el.dataset.i);
      document.getElementById('v2').innerHTML = renderWireframes();
    });
  }, 0);
  return `<div class="wf-layout">
    <div class="wf-list">${list}</div>
    <div class="wf-canvas">${renderForm(forms[activeFormIdx])}</div>
  </div>`;
}

function renderForm(form) {
  const all = form.fields || form.components || [];
  // 把 components 按 sectionType 拆 main / sub —— 解析器把子表字段也塞 components
  // 用 subTableLabel 分组形成多个子表区域
  const mainFields = all.filter(c => (c.sectionType || 'main') !== 'sub');
  const subGroups = {};
  for (const c of all) {
    if (c.sectionType === 'sub') {
      const label = c.subTableLabel || c.subFormName || '子表';
      (subGroups[label] = subGroups[label] || []).push(c);
    }
  }
  // 兼容老格式：form.subForms 直接给的话也支持
  const legacySubs = (form.subForms || []).map(s => ({
    label: s.name || s.subFormName || '子表',
    model: s.modelCode || s.bindModel || '',
    fields: s.fields || s.components || [],
  }));
  const subList = [
    ...Object.entries(subGroups).map(([label, fields]) => ({
      label,
      // 从子表 components 里抓 modelCode（同 label 下应该都一致）
      model: (fields[0] && (fields[0].modelCode || fields[0].tableModelCode)) || '',
      fields,
    })),
    ...legacySubs,
  ];

  const required = mainFields.filter(f => isTrue(f.required)).length;
  const caps = capabilitiesForForm(form);
  return `
    <div class="wf-title">${esc(form.name||form.formName)}</div>
    <div class="wf-desc">${esc(form.description||form.formDesc||'')} · 绑定主表 <code>${esc(getMain(form)||'—')}</code></div>
    <div class="wf-meta"><span>主表字段 <b>${mainFields.length}</b></span><span>子表 <b>${subList.length}</b></span><span>必填字段 <b>${required}</b></span></div>
    <div class="cap-row">${caps.map(c => `<span class="cap ${c.on ? 'on' : ''} ${c.key === 'import' && c.on ? 'import' : ''}">${esc(c.label)}</span>`).join('')}</div>
    <div class="wf-section-title">主表字段</div>
    <div class="wf-grid">${mainFields.map(renderFieldCard).join('')}</div>
    ${subList.map(sub => `
      <div class="wf-section-title">子表区域：${esc(sub.label)} <span style="color:#909399;font-weight:normal">${sub.model ? `· 绑定 <code>${esc(sub.model)}</code>` : ''} · ${sub.fields.length} 字段</span></div>
      <div class="subtable"><table>
        <thead><tr>${sub.fields.map(f =>
          `<th>${esc(f.name||f.fieldName||f.label)}${isTrue(f.required)?' <span style="color:#f56c6c">*</span>':''}${isTrue(f.readonly)?' <span class="flag flag-grey" style="font-size:10px;margin-left:4px">只读</span>':''}</th>`).join('')}</tr></thead>
        <tbody><tr>${sub.fields.map(() => '<td>—</td>').join('')}</tr>
        <tr>${sub.fields.map(() => '<td>—</td>').join('')}</tr></tbody>
      </table></div>
    `).join('')}`;
}

function capabilitiesForForm(form) {
  const code = form.code || form.formCode;
  const name = form.name || form.formName;
  const rules = [];
  for (const p of perms) {
    const key = p.formCode || p.form_code || p.form;
    if (key === code || key === name) rules.push(...(p.rules || p.permissionRules || []));
  }
  const hasOp = (ops) => rules.some(r => {
    if (r.op === 'all') return true;
    const arr = Array.isArray(r.op) ? r.op : String(r.op || '').split(/[,+]/).map(x => x.trim());
    return ops.some(o => arr.includes(o));
  });
  return [
    {key:'view', label:'查看', on: hasOp(['view']) || rules.some(r => r.canView)},
    {key:'add', label:'新增', on: hasOp(['add','create']) || rules.some(r => r.canAdd || r.canCreate)},
    {key:'edit', label:'编辑', on: hasOp(['edit']) || rules.some(r => r.canEdit)},
    {key:'delete', label:'删除', on: hasOp(['delete']) || rules.some(r => r.canDelete)},
    {key:'import', label:'可导入', on: rules.some(r => r.canImport)},
    {key:'export', label:'可导出', on: rules.some(r => r.canExport) || hasOp(['export'])},
  ];
}

function renderProcessFlow() {
  if (!workflows.length) {
    return `<div class="empty-state">暂无显式流程/审批流。当前设计文档会按表单权限完成基础操作流转，导入能力仍跟随权限规则开启。</div>`;
  }
  return `<div class="process-list">${workflows.map(renderWorkflow).join('')}</div>`;
}

function renderWorkflow(wf, idx) {
  const formKey = wf.form || wf.formName || wf.formCode || wf.bindForm || '';
  const nodes = normalizeWorkflowNodes(wf);
  return `<div class="process-card">
    <div class="process-head">
      <div><div class="process-title">${esc(wf.name || wf.processName || `流程 ${idx + 1}`)}</div>
      <div class="process-meta">${formKey ? `关联表单：${esc(formKey)}` : '未指定关联表单'}${wf.description ? ` · ${esc(wf.description)}` : ''}</div></div>
      <span class="tag tag-blue">${nodes.length} 节点</span>
    </div>
    <div class="process-nodes">${nodes.map(n => `
      <div class="process-node ${esc(n.kind)}"><div class="name">${esc(n.name)}</div>${n.role ? `<div class="role">${esc(n.role)}</div>` : ''}</div>
    `).join('')}</div>
  </div>`;
}

function normalizeWorkflowNodes(wf) {
  const raw = wf.nodes || wf.steps || wf.approvers || [];
  const nodes = raw.map((n, i) => ({
    name: n.name || n.nodeName || n.title || n.role || n.roleName || `审批节点 ${i + 1}`,
    role: n.role || n.roleName || n.assignee || n.approver || '',
    kind: /start|开始/i.test(String(n.type || n.nodeType || n.name || '')) ? 'start'
      : /end|结束/i.test(String(n.type || n.nodeType || n.name || '')) ? 'end'
      : '',
  }));
  const hasStart = nodes.some(n => n.kind === 'start');
  const hasEnd = nodes.some(n => n.kind === 'end');
  return [
    ...(hasStart ? [] : [{name:'提交', role:'发起人', kind:'start'}]),
    ...nodes,
    ...(hasEnd ? [] : [{name:'结束', role:'', kind:'end'}]),
  ];
}

function renderFieldCard(f) {
  const name = f.name || f.fieldName || f.label || '—';
  const t = String(f.type || f.componentType || '').trim();
  const full = ['关联表单','附件上传','富文本','多行输入','签名','地理位置','子表'].some(k => t.includes(k));
  let compCls = '', icon = '', text = t || '请输入';
  if (/(下拉|单选|选择|部门|人员)/.test(t)) { compCls = 'select'; icon = '▾'; }
  else if (/日期|时间/.test(t)) { compCls = 'date'; icon = '📅'; }
  else if (/(附件|上传)/.test(t)) { compCls = 'upload'; text = '📎 点击上传 / 拖拽文件'; }
  else if (/关联表单/.test(t)) { compCls = 'reflink'; }
  else if (/(多行|富文本)/.test(t)) { compCls = 'textarea'; text = ''; }
  if (f.dictCode) text = `${f.dictCode} 字典`;
  else if (f.refModel || f.targetModel) {
    const refM = f.refModel || f.targetModel;
    const refF = f.refField || f.targetField;
    text = `${t} → ${refM}${refF ? '.' + refF : ''}`;
  }
  else if (/金额/.test(t)) text = '¥ 0.00';
  else if (/单据号/.test(t)) text = '自动生成';
  const flags = [];
  if (isTrue(f.readonly)) flags.push('<span class="flag flag-grey">只读</span>');
  if (isTrue(f.hidden))   flags.push('<span class="flag flag-grey">隐藏</span>');
  if (isTrue(f.listShow)) flags.push('<span class="flag flag-blue">列表</span>');
  if (isTrue(f.searchable)||isTrue(f.queryable)) flags.push('<span class="flag flag-orange">查询</span>');
  return `<div class="field${full?' full':''}">
    <div class="field-label">${esc(name)}${isTrue(f.required)?'<span class="req"> *</span>':''}
      <div class="field-flags">${flags.join('')}</div>
    </div>
    <div class="comp ${compCls}"><span class="comp-text">${esc(text)}</span>${icon?`<span class="comp-icon">${icon}</span>`:''}</div>
  </div>`;
}

function fmtOps(r) {
  // 用完整中文词。规则数据结构：
  //   op 字符串: "all" / "add,view,edit" / 单个 op → 列基础权限
  //   canDraft / canImport / canExport: 独立 bool → 附加权限
  const opMap = {view:'查看', add:'新增', create:'新增', edit:'编辑', delete:'删除'};
  const flagMap = {canDraft:'暂存', canImport:'导入', canExport:'导出'};
  const labels = [];

  // 1) 处理 op 字段
  if (r.op === 'all' || (Array.isArray(r.op) && r.op.includes('all'))) {
    labels.push('查看', '新增', '编辑', '删除');
  } else if (typeof r.op === 'string' && r.op) {
    for (const o of r.op.split(/[,+]/).map(s => s.trim())) {
      if (opMap[o] && !labels.includes(opMap[o])) labels.push(opMap[o]);
    }
  } else if (Array.isArray(r.op)) {
    for (const o of r.op) {
      if (opMap[o] && !labels.includes(opMap[o])) labels.push(opMap[o]);
    }
  }
  // 2) 处理 canX 独立 flag
  for (const k in flagMap) {
    if (r[k] && !labels.includes(flagMap[k])) labels.push(flagMap[k]);
  }

  if (!labels.length) return '—';
  // 全部 7 项齐 → 简写"全权限"
  if (labels.length >= 7) return '全权限';
  return labels.join('·');
}
function getMain(f) { return f.mainModel || f.modelCode || f.bindModel || ''; }
function fieldType(f) {
  const t = f.databaseFieldType || f.dbType || f.type || '';
  const len = f.maxLength || f.length || f.precision;
  return len ? `${t}(${len})` : t;
}
"""
