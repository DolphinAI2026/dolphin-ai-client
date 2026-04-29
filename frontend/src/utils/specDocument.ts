import type { PermissionData, PermissionOp, Spec } from '@/types/spec'

export function specTitle(spec: Spec | null | undefined): string {
  return spec?.goal?.title || '应用设计文档'
}

export function specUpdatedText(spec: Spec | null | undefined): string {
  const raw = spec?.updated_at
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function scopeLabel(scope: string): string {
  return ({ ALL: '全部数据', DEPT: '本部门', DEPT_LOW: '部门及下级', SELF: '仅本人' } as Record<string, string>)[scope] || scope
}

export function opLabel(op: PermissionOp): string {
  return ({ all: '全部', add: '新增', edit: '编辑', delete: '删除', view: '查看' } as Record<PermissionOp, string>)[op] || op
}

export function dataLabel(data: PermissionData): string {
  return ({ ALL: '全部数据', SELF: '仅本人', DEPT: '本部门', DEPT_LOW: '部门及下级' } as Record<PermissionData, string>)[data] || data
}

export function roleName(spec: Spec | null | undefined, roleCode: string): string {
  const role = spec?.roles.find((item) => item.code === roleCode)
  return role ? role.name : roleCode
}

export function fieldMeta(field: { type: string; required: boolean; dict_code?: string | null; ref_model?: string | null }) {
  const parts = [field.type]
  if (field.required) parts.push('必填')
  if (field.dict_code) parts.push(`字典：${field.dict_code}`)
  if (field.ref_model) parts.push(`关联：${field.ref_model}`)
  return parts.join(' / ')
}

function mdCell(value: unknown): string {
  return String(value ?? '').replace(/\|/g, '\\|').replace(/\n+/g, '<br>').trim() || '-'
}

function mdCode(value: unknown): string {
  const text = String(value ?? '').trim()
  return text ? `\`${text}\`` : '-'
}

export function specToMarkdown(spec: Spec | null | undefined): string {
  if (!spec) return ''
  const lines: string[] = []
  const updated = specUpdatedText(spec)

  lines.push(`# ${specTitle(spec)}`, '')
  if (updated) lines.push(`更新时间：${updated} · 当前为 AI 设计文档草案，可继续通过对话调整。`, '')

  lines.push('## 1. 业务目标', '')
  if (spec.goal) {
    lines.push(`**业务问题：** ${spec.goal.business_problem || '-'}`, '')
    lines.push(`**系统简介：** ${spec.goal.summary || '-'}`, '')
  } else {
    lines.push('暂未形成业务目标。', '')
  }

  lines.push('## 2. 角色与使用范围', '')
  if (spec.roles.length) {
    lines.push('| 角色 | 角色编码 | 数据范围 | 职责说明 |')
    lines.push('|------|----------|----------|----------|')
    spec.roles.forEach((role) => {
      lines.push(`| ${mdCell(role.name)} | ${mdCode(role.code)} | ${mdCell(scopeLabel(role.scope))} | ${mdCell(role.description || '待补充')} |`)
    })
    lines.push('')
  } else {
    lines.push('暂未定义角色。', '')
  }

  lines.push('## 3. 数据对象与字段', '')
  if (spec.objects.length) {
    spec.objects.forEach((object) => {
      lines.push(`### ${object.name} ${mdCode(object.code)}`, '')
      if (object.description) lines.push(object.description, '')
      if (object.fields.length) {
        lines.push('| 字段 | 字段编码 | 说明 |')
        lines.push('|------|----------|------|')
        object.fields.forEach((field) => {
          lines.push(`| ${mdCell(field.name)} | ${mdCode(field.code)} | ${mdCell(fieldMeta(field))} |`)
        })
        lines.push('')
      } else {
        lines.push('字段待补充。', '')
      }
    })
  } else {
    lines.push('暂未生成数据对象。', '')
  }

  lines.push('## 4. 字典与选项', '')
  if (spec.dicts.length) {
    spec.dicts.forEach((dict) => {
      lines.push(`### ${dict.name} ${mdCode(dict.code)}`, '')
      if (dict.options.length) {
        lines.push(dict.options.map((option) => `- ${option.name} ${mdCode(option.code)}`).join('\n'), '')
      } else {
        lines.push('暂无选项。', '')
      }
    })
  } else {
    lines.push('暂未生成数据字典。', '')
  }

  lines.push('## 5. 权限策略', '')
  if (spec.permissions.length) {
    lines.push('| 对象 | 角色 | 操作 | 数据范围 |')
    lines.push('|------|------|------|----------|')
    spec.permissions.forEach((permission) => {
      permission.rules.forEach((rule) => {
        lines.push(`| ${mdCode(permission.object_code)} | ${mdCell(roleName(spec, rule.role))} | ${mdCell(opLabel(rule.op))} | ${mdCell(dataLabel(rule.data))} |`)
      })
    })
    lines.push('')
  } else {
    lines.push('暂未生成权限策略。', '')
  }

  const pending = spec.decisions_pending.filter((decision) => !decision.resolved)
  if (pending.length) {
    lines.push('## 待确认问题', '')
    pending.forEach((decision, index) => {
      lines.push(`${index + 1}. **${decision.topic}**`)
      if (decision.why_blocking) lines.push(`   - ${decision.why_blocking}`)
    })
    lines.push('')
  }

  return lines.join('\n').trim()
}
