/**
 * 共享图标系统 —— feather / lucide 风格的描边 SVG，单一来源。
 *
 * 背景：代码库原本散落两套用法 —— 各面板内联 `<svg>`，以及 coding 几个文件本地各自的
 * `ICON_PATHS + iconSvg()`。2026-06-05 把全站 emoji 图标统一换成 SVG 时，抽出本模块作为
 * 唯一图标词表，配合 `<AppIcon>` 组件（模板里用）和 `iconSvg()`（注册表 icon 字段 / v-html 用）。
 *
 * 约定：所有 path 都基于 24×24 viewBox、`fill="none" stroke="currentColor"`、圆角端点。
 * 新增图标 → 往 ICON_PATHS 里加一条 `name: '<path.../>'` 即可，全站自动可用。
 */

export const ICON_PATHS: Record<string, string> = {
  // ── 通用文件 / 文档 ──
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h6"/>',
  doc: '<path d="M6 2h8l4 4v16H6z"/><path d="M14 2v4h4"/>',
  files: '<path d="M15 2H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V6z"/><path d="M15 2v4h4"/><path d="M4 7v13a2 2 0 0 0 2 2h9"/>',
  clipboard: '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>',
  'book-open': '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  scroll: '<path d="M19 17V5a2 2 0 0 0-2-2H4"/><path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3"/>',
  folder: '<path d="M4 20a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2z"/>',

  // ── 数据 / 存储 ──
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6a8 3 0 0 0 16 0V5"/><path d="M4 11v6a8 3 0 0 0 16 0v-6"/>',
  save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
  package: '<path d="m7.5 4.3 9 5.1"/><path d="M21 8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
  box: '<path d="M12 2 3 7v10l9 5 9-5V7z"/><path d="M3 7l9 5 9-5"/><path d="M12 12v10"/>',
  archive: '<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/><path d="M10 12h4"/>',

  // ── 图表 / 设计 ──
  'bar-chart': '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>',
  palette: '<circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="8.5" cy="7.5" r="1.5"/><circle cx="6.5" cy="12.5" r="1.5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c1 0 1.8-.8 1.8-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-1 .8-1.8 1.8-1.8H16c3.3 0 6-2.7 6-6 0-4.9-4.5-8.2-10-8.2z"/>',
  ruler: '<path d="M16 2 22 8 8 22 2 16z"/><path d="m7.5 10.5 2 2M11 7l2 2M14.5 3.5l2 2M4 13.5l2 2"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-4.5-4.5L5 21"/>',
  camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3.5"/>',

  // ── 设备 ──
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  laptop: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M2 20h20"/>',
  smartphone: '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>',
  globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20z"/>',
  broadcast: '<circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.5M7.8 16.3a6 6 0 0 1 0-8.5M19 5a10 10 0 0 1 0 14M5 19A10 10 0 0 1 5 5"/>',

  // ── 人 / 角色 ──
  user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  briefcase: '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
  handshake: '<path d="m11 17 2 2a1 1 0 1 0 3-3"/><path d="m14 14 2.5 2.5a1 1 0 1 0 3-3l-3.9-3.9a2 2 0 0 1 0-2.8l.8-.8a2 2 0 0 1 2.8 0L21 8"/><path d="M3 8l1.8-1.8a2 2 0 0 1 2.8 0L13 11l-2 2"/><path d="m5 13 1.5 1.5a1 1 0 1 0 3-3"/>',
  'thumbs-down': '<path d="M17 14V2"/><path d="M9 18.1c1 .2 1.6 1.2 1.3 2.2l-.3 1c-.2.7-.9 1.2-1.6 1-.5-.1-1-.6-1.1-1.2L7 18H4a2 2 0 0 1-2-2.3l.9-6A2 2 0 0 1 4.9 8H16v8l-4.5 5.2a1.5 1.5 0 0 1-2.5-.6z"/>',
  wave: '<path d="M12 11V4.5a1.5 1.5 0 0 1 3 0V11"/><path d="M15 11V3.5a1.5 1.5 0 0 1 3 0V13"/><path d="M9 11.5V6a1.5 1.5 0 0 0-3 0v8"/><path d="M18 9a1.5 1.5 0 0 1 3 0c0 6-3.5 11-8 11-3 0-5-1.5-6.5-3.5L4 13a1.7 1.7 0 0 1 2.5-2.2L9 13"/>',

  // ── 状态 / 反馈 ──
  check: '<polyline points="20 6 9 17 4 12"/>',
  'check-circle': '<circle cx="12" cy="12" r="10"/><polyline points="16 9.5 11 15 8 12"/>',
  x: '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
  'x-circle': '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/>',
  warning: '<path d="M10.3 3.5 1.8 18a2 2 0 0 0 1.7 3h16.9a2 2 0 0 0 1.7-3L13.7 3.5a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
  'help-circle': '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
  hourglass: '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.2a2 2 0 0 0-.6-1.4L12 12l-4.4 4.4a2 2 0 0 0-.6 1.4V22"/><path d="M7 2v4.2a2 2 0 0 0 .6 1.4L12 12l4.4-4.4a2 2 0 0 0 .6-1.4V2"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>',
  dot: '<circle cx="12" cy="12" r="5" fill="currentColor" stroke="none"/>',
  star: '<path d="m12 2 2.9 6.3 6.8.8-5 4.7 1.3 6.8L12 18.5 5.9 21.4 7.2 14.6l-5-4.7 6.8-.8z" fill="currentColor"/>',

  // ── 动作 / 工具 ──
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  edit: '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4z"/>',
  pencil: '<path d="M17 3a2.8 2.8 0 0 1 4 4L7.5 20.5 2 22l1.5-5.5z"/><path d="m15 5 4 4"/>',
  wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
  tool: '<path d="M3 21l3-3"/><path d="m13 8 3.5-3.5a3.5 3.5 0 0 0-5-5L8 3"/><path d="M14.5 12.5 21 19a1.5 1.5 0 0 1-2 2l-6.5-6.5"/><path d="m5.5 7.5 11 11"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>',
  link: '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1.5 1.5"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1.5-1.5"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z"/>',
  paperclip: '<path d="M21.4 11 12.2 20.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/>',
  pin: '<path d="M12 17v5"/><path d="M9 10.8V4h6v6.8a2 2 0 0 0 .6 1.4l1.9 1.9a1 1 0 0 1-.7 1.7H7.2a1 1 0 0 1-.7-1.7l1.9-1.9a2 2 0 0 0 .6-1.4z"/>',
  'map-pin': '<path d="M20 10c0 5.5-8 12-8 12s-8-6.5-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
  key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.5 12.5 8-8"/><path d="m16 6 2 2M19 3l2 2"/>',
  menu: '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>',
  more: '<circle cx="5" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.6" fill="currentColor" stroke="none"/>',
  square: '<rect x="4" y="4" width="16" height="16" rx="2"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  'arrow-right': '<line x1="4" y1="12" x2="19" y2="12"/><polyline points="13 6 19 12 13 18"/>',

  // ── 概念 / 装饰 ──
  zap: '<path d="M13 2 3 14h8l-1 8 11-13h-8z"/>',
  puzzle: '<path d="M9 3a2 2 0 0 1 4 0v.5a1.5 1.5 0 0 0 3 0V3h3a2 2 0 0 1 2 2v3h-.5a1.5 1.5 0 0 0 0 3H21v6a2 2 0 0 1-2 2h-3v-.5a1.5 1.5 0 0 0-3 0V19H8a2 2 0 0 1-2-2v-3h.5a1.5 1.5 0 0 0 0-3H6V5a2 2 0 0 1 2-2z"/>',
  rocket: '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M15 9a1 1 0 1 0 0-2 1 1 0 0 0 0 2z"/>',
  bot: '<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4M9 4h6"/><circle cx="9" cy="14" r="1.2"/><circle cx="15" cy="14" r="1.2"/><path d="M2 13v3M22 13v3"/>',
  bulb: '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.2 1 2v.5h6v-.5c0-.8.3-1.3 1-2A6 6 0 0 0 12 3z"/>',
  message: '<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  calendar: '<rect x="3" y="4.5" width="18" height="17" rx="2"/><path d="M3 9h18M8 2.5v4M16 2.5v4"/>',
  shield: '<path d="M12 2 4 5v6c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V5z"/>',
  shuffle: '<path d="M16 3h5v5"/><path d="M4 20 21 3"/><path d="M21 16v5h-5"/><path d="m15 15 6 6"/><path d="M4 4l5 5"/>',
  'point-left': '<path d="M14 9V5a2 2 0 0 0-4 0v8"/><path d="M10 13V8a1.5 1.5 0 0 0-3 0v6.5l-1.4-1.4a1.5 1.5 0 0 0-2.2 2L6 19a6 6 0 0 0 5 3h2.5a4.5 4.5 0 0 0 4.5-4.5V11a1.5 1.5 0 0 0-3 0"/>',
  megaphone: '<path d="M3 11v2a1 1 0 0 0 1 1h2l9 5V5L6 10H4a1 1 0 0 0-1 1z"/><path d="M18 8a4 4 0 0 1 0 8"/>',
  wand: '<path d="M15 4V2M15 10V8M11 6H9M21 6h-2"/><path d="m17 8 1.5-1.5"/><path d="M3 21 16 8l2 2L5 23z"/>',
  sparkles: '<path d="M12 3 13.6 8.4 19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6z"/><path d="M19 14l.7 2.3L22 17l-2.3.7L19 20l-.7-2.3L16 17l2.3-.7z"/>',
  party: '<path d="M3 21 9 9l6 6z"/><path d="M14 7a3 3 0 0 1 3-3M19 4a3 3 0 0 1 3 3M14 12l1 1M18 9l1 1M20 14l1 1"/>',

  // ── coding（沿用旧 key）──
  coding: '<path d="m8 17-5-5 5-5"/><path d="m16 7 5 5-5 5"/><path d="m13 4-2 16"/>',
  building: '<path d="M5 21V4a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v17"/><path d="M15 9h3a1 1 0 0 1 1 1v11"/><path d="M8 7h2M8 11h2M8 15h2"/><path d="M3 21h18"/>',
  store: '<path d="M3 9 5 4h14l2 5"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9"/><path d="M3 9h18"/>',
  flow: '<circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="6" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M7.4 11 16.6 6.8M7.4 13l9.2 4.2"/>',
  lock: '<rect x="4.5" y="10" width="15" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
}

/** 返回完整 `<svg>` 字符串 —— 给 v-html / 注册表 icon 字段用。未知 name 返回空 svg。 */
export function iconSvg(name: string, size = 16, stroke = 2): string {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round">${ICON_PATHS[name] || ''}</svg>`
}

/** 该 name 是否有对应图标。 */
export function hasIcon(name: string): boolean {
  return name in ICON_PATHS
}
