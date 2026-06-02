/* data.jsx — 睿鲸AI prototype scenario data.
 * Through-line: 从 0→1 搭一个复杂 CRM（Builder），再持续扩展它（Coding）。 */

// ─────────────────────────────────────────── Brand whale mark
function WhaleMark({ size = 18, color = '#fff' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M2.6 13.4c2.1.3 3.2-.5 3.9-1.6.7 2.2 2.8 3.8 6 3.8 4.4 0 7.3-3.1 8.4-7.2.2-.7-.5-1.2-1.1-.8-1.3.9-2.6 1.1-3.6.9C18.4 5.3 16 3.7 13 3.7c-3.8 0-6.7 2.9-6.9 6.7-.6.7-1.6 1.1-3 .8-.7-.1-1 .8-.5 1.2.2.1.4.2.6.2Z" fill={color}/>
      <circle cx="14.4" cy="8.4" r="1.05" fill="var(--brand)"/>
      <path d="M3.4 16.6c3.4 1.9 6.2 2.5 9 2.5s5.6-.6 9-2.5" stroke={color} strokeWidth="1.5" strokeLinecap="round" opacity="0.55"/>
    </svg>
  );
}

// ─────────────────────────────────────────── Builder conversation (0→1 CRM)
const BUILDER_CHAT = [
  { who: 'user', text: '帮销售团队搭一个 CRM。要能管客户、联系人、商机和跟进记录，商机要走审批，销售只能看自己的客户，主管能看全部。' },
  { who: 'ai', kind: 'plan', text: '明白了，这是一个含权限分层的销售管理系统。我先把它拆成 4 个数据模型和 1 条审批流，右侧是实时结构预览 —— 你可以边看边改。',
    chips: ['客户 Customer', '联系人 Contact', '商机 Opportunity', '跟进记录 Activity', '商机审批流'] },
  { who: 'user', text: '商机要分阶段：初步接洽 / 方案报价 / 谈判 / 赢单 / 丢单。金额超过 50 万要走总监审批。' },
  { who: 'ai', kind: 'update', text: '已把「阶段」加成单选字段，并给审批流加了一条金额分支：≥ 50 万自动多加一级总监审批。预览里第 3 步已经更新。',
    chips: ['商机.阶段 ← 5 个选项', '审批流 +1 条金额分支'] },
  { who: 'user', text: '看起来对了。生成吧。' },
];

// Right-panel config preview for Builder — 4 tabs
const CRM_MODELS = [
  { code: 'customer', name: '客户', icon: 'building', count: 9, primary: true,
    fields: [
      { name: '客户名称', code: 'name', type: '单行文本', req: true },
      { name: '客户编号', code: 'no', type: '自动编号', req: true },
      { name: '行业', code: 'industry', type: '单选', req: false },
      { name: '客户等级', code: 'level', type: '单选 · A/B/C', req: false },
      { name: '负责销售', code: 'owner', type: '成员', req: true },
      { name: '地区', code: 'region', type: '级联', req: false },
    ] },
  { code: 'contact', name: '联系人', icon: 'user', count: 6,
    fields: [
      { name: '姓名', code: 'name', type: '单行文本', req: true },
      { name: '所属客户', code: 'customer', type: '关联 · 客户', req: true },
      { name: '职位', code: 'title', type: '单行文本', req: false },
      { name: '手机', code: 'phone', type: '电话', req: true },
    ] },
  { code: 'opportunity', name: '商机', icon: 'target', count: 11,
    fields: [
      { name: '商机名称', code: 'name', type: '单行文本', req: true },
      { name: '关联客户', code: 'customer', type: '关联 · 客户', req: true },
      { name: '阶段', code: 'stage', type: '单选 · 5 阶段', req: true, hl: true },
      { name: '预计金额', code: 'amount', type: '金额', req: true, hl: true },
      { name: '预计成交日', code: 'closeDate', type: '日期', req: false },
    ] },
  { code: 'activity', name: '跟进记录', icon: 'note', count: 5,
    fields: [
      { name: '跟进内容', code: 'content', type: '多行文本', req: true },
      { name: '关联商机', code: 'opp', type: '关联 · 商机', req: false },
      { name: '跟进方式', code: 'channel', type: '单选', req: false },
      { name: '跟进时间', code: 'time', type: '日期时间', req: true },
    ] },
];

const CRM_STAGES = ['初步接洽', '方案报价', '谈判', '赢单', '丢单'];

const CRM_PROCESS = [
  { n: 1, title: '销售提交商机', role: '销售', kind: 'start' },
  { n: 2, title: '销售主管审批', role: '销售主管', kind: 'approve' },
  { n: 3, title: '金额 ≥ 50 万', role: '条件分支', kind: 'branch', hl: true },
  { n: 4, title: '销售总监审批', role: '销售总监', kind: 'approve', hl: true },
  { n: 5, title: '商机生效', role: '系统', kind: 'end' },
];

const CRM_PERMS = [
  { role: '销售', scope: '仅本人客户', create: true, edit: '本人', del: false, approve: false },
  { role: '销售主管', scope: '本部门全部', create: true, edit: '部门', del: true, approve: true },
  { role: '销售总监', scope: '全公司', create: true, edit: '全部', del: true, approve: true },
  { role: '只读访客', scope: '全公司', create: false, edit: '—', del: false, approve: false },
];

const BUILD_STEPS = [
  '校验数据模型与字段编码',
  '生成 4 张业务表 + 关联关系',
  '装配表单、列表与详情页',
  '部署商机审批流',
  '应用角色权限与数据范围',
  '初始化应用，分配 app_id',
];

// ─────────────────────────────────────────── Coding conversation (extend existing CRM)
const CODING_CHAT = [
  { who: 'sys', text: '已载入应用上下文：销售 CRM · 4 模型 / 1 审批流 / 4 角色' },
  { who: 'user', text: '标准列表满足不了。我要一个「商机看板」页面：按阶段分列、卡片能拖拽换阶段，拖到「赢单」时弹个确认框。' },
  { who: 'ai', kind: 'plan', text: '这是标准配置装不下的定制页面 —— 交给我写代码。我会基于「商机」模型生成一个看板组件，复用已有的阶段枚举和金额字段。右侧可以实时预览。',
    chips: ['新页面 OpportunityBoard.vue', '复用 商机.阶段 枚举', '拖拽 → 调 updateStage 接口'] },
  { who: 'user', text: '卡片上把客户名和金额显示出来，金额大于 50 万标个红。' },
  { who: 'ai', kind: 'update', text: '已加上客户名与金额，并对 ≥ 50 万的卡片加了醒目标记。看右侧预览第二列那张卡。',
    chips: ['Card 显示 customer.name / amount', '≥50万 高亮角标'] },
];

const CODING_FILES = [
  { path: 'pages/OpportunityBoard.vue', active: true, badge: 'new' },
  { path: 'components/OppCard.vue', badge: 'new' },
  { path: 'api/opportunity.ts', badge: 'edit' },
  { path: 'composables/useDragStage.ts', badge: 'new' },
];

const CODING_CODE = `<script setup lang="ts">
import { ref, computed } from 'vue'
import { listOpps, updateStage } from '@/api/opportunity'
import OppCard from '@/components/OppCard.vue'
import { STAGES } from '@/enums/oppStage'   // 复用 Builder 定义的枚举

const opps = ref(await listOpps())
const byStage = (s: string) =>
  opps.value.filter(o => o.stage === s)

async function onDrop(opp, stage) {
  if (stage === '赢单') {
    if (!await confirm('确认标记为赢单？')) return
  }
  await updateStage(opp.id, stage)   // 调应用已有接口
  opp.stage = stage
}
<\/script>`;

const KANBAN_CARDS = {
  '初步接洽': [{ name: '华东制造数字化', cust: '华东智造', amt: '¥32万' }],
  '方案报价': [{ name: '集团 SaaS 采购', cust: '远景集团', amt: '¥68万', hot: true }, { name: '门店系统升级', cust: '优鲜便利', amt: '¥15万' }],
  '谈判': [{ name: '全国渠道平台', cust: '中谷物流', amt: '¥120万', hot: true }],
  '赢单': [{ name: '区域 CRM 试点', cust: '蓝海科技', amt: '¥24万' }],
};

// ─────────────────────────────────────────── Asset libraries
const APP_ASSETS = [
  { name: '销售 CRM', code: 'sales_crm', status: 'live', models: 4, by: 'AI Builder', when: '刚刚', star: true, desc: '客户 / 联系人 / 商机 / 跟进 + 审批 + 分级权限' },
  { name: 'QMS 整改闭环', code: 'qms', status: 'live', models: 5, by: 'AI Builder', when: '3 天前', desc: '问题登记 → 派发 → 整改 → 验证 → 超期提醒' },
  { name: '设备台账', code: 'assets', status: 'live', models: 3, by: 'AI Builder', when: '上周', desc: '设备档案 / 点检 / 维修工单' },
  { name: '售后服务系统', code: 'aftersale', status: 'draft', models: 6, by: 'AI Builder', when: '2 周前', desc: '工单 / SLA / 备件 / 回访' },
];

const CODE_ASSETS = [
  { name: '商机看板', code: 'OpportunityBoard', kind: '定制页面', host: '销售 CRM', reuse: 1, when: '刚刚', star: true, tags: ['拖拽', '看板'] },
  { name: '客户树选择器', code: 'CustomerTree', kind: '通用组件', host: '可复用', reuse: 7, when: '5 天前', tags: ['多选', '异步加载'] },
  { name: 'OCR 上传卡', code: 'OcrUploader', kind: '通用组件', host: '可复用', reuse: 4, when: '上周', tags: ['OCR', '上传'] },
  { name: 'SLA 倒计时条', code: 'SlaCountdown', kind: '通用组件', host: '售后服务系统', reuse: 3, when: '2 周前', tags: ['计时'] },
];

// Three boundary models explored on the home screen
const BOUNDARY_MODELS = [
  { id: 'A', label: '按产物分', icon: 'box',
    builder: '产出整个应用', coding: '产出可复用组件 / 页面 / 接口',
    note: '清楚，但「应用里的一个定制页面」该算谁的？边界仍会打架。' },
  { id: 'B', label: '按阶段分', icon: 'steps',
    builder: '从 0→1 把应用搭出来', coding: '在已有应用上做增量自开发',
    note: '贴合真实路径，但「0→1 时就要写代码」的需求无处安放。' },
  { id: 'C', label: '一条连续光谱', icon: 'flow',
    builder: '对话搭结构（广度）', coding: '对话写代码（深度）',
    note: '体验最顺，但要靠产品把「什么时候该转」讲清楚，否则用户会迷路。' },
];

Object.assign(window, {
  WhaleMark,
  BUILDER_CHAT, CRM_MODELS, CRM_STAGES, CRM_PROCESS, CRM_PERMS, BUILD_STEPS,
  CODING_CHAT, CODING_FILES, CODING_CODE, KANBAN_CARDS,
  APP_ASSETS, CODE_ASSETS, BOUNDARY_MODELS,
});
