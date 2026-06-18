import type { Component } from 'vue'
import type { Binding } from './binding'

export interface Panel {
  id: string
  label: string
  icon: string                 // AppIcon name 字符串
  shortcut?: string
  group: 'common' | 'context'  // common 永远在; context 按绑定亮/灰
  availableWhen: (binding: Binding) => boolean
  component: Component | (() => Promise<Component>)
}

export interface ToolMenuItem {
  id: string
  label: string
  icon: string
  shortcut?: string
  group: 'common' | 'context'
  enabled: boolean
}

const _panels: Panel[] = []

export function registerPanel(p: Panel): void {
  if (_panels.some(x => x.id === p.id)) return // 幂等, 防 HMR 重复注册
  _panels.push(p)
}

export function listPanels(): Panel[] {
  return [..._panels]
}

export function isAvailable(p: Panel, binding: Binding): boolean {
  try {
    return !!p.availableWhen(binding)
  } catch {
    return false // 谓词异常/未知绑定 → 禁用, 不崩菜单
  }
}

export function buildToolMenuItems(binding: Binding): ToolMenuItem[] {
  return _panels.map(p => ({
    id: p.id, label: p.label, icon: p.icon, shortcut: p.shortcut,
    group: p.group, enabled: isAvailable(p, binding),
  }))
}

export function getPanel(id: string): Panel | undefined {
  return _panels.find(p => p.id === id)
}

export function resetRegistryForTest(): void {
  _panels.length = 0
}
