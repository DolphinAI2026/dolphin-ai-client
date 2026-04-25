// Mirrors backend Pydantic models in app/spec/schema.py

export type Phase = 'gathering' | 'drafting' | 'generating' | 'ready'
export type RoleScope = 'SELF' | 'DEPT' | 'DEPT_LOW' | 'ALL'
export type PermissionOp = 'all' | 'add' | 'edit' | 'delete' | 'view'
export type PermissionData = 'ALL' | 'SELF' | 'DEPT' | 'DEPT_LOW'

export interface Decision {
  id: string
  topic: string
  why_blocking: string | null
  options: string[]
  blocking: boolean
  raised_in_phase: Phase
  resolved: boolean
  resolution: string | null
  created_at: string
  resolved_at: string | null
}

export interface Goal {
  title: string
  summary: string
  business_problem: string
  confirmed: boolean
}

export interface Role {
  code: string
  name: string
  scope: RoleScope
  description: string | null
  confirmed: boolean
}

export interface FieldSpec {
  code: string
  name: string
  type: string
  required: boolean
  dict_code: string | null
  ref_model: string | null
  ref_field: string | null
  description: string | null
  confirmed: boolean
}

export interface ObjectSpec {
  code: string
  name: string
  description: string | null
  fields: FieldSpec[]
  sub_objects: Record<string, FieldSpec[]>
  confirmed: boolean
}

export interface DictOption {
  code: string
  name: string
}

export interface DictSpec {
  code: string
  name: string
  options: DictOption[]
  confirmed: boolean
}

export interface PermissionRule {
  role: string
  op: PermissionOp
  data: PermissionData
}

export interface PermissionSpec {
  object_code: string
  rules: PermissionRule[]
  confirmed: boolean
}

export interface Completeness {
  confirmed: number
  total: number
  by_section: Record<string, [number, number]>
  pending_decisions: number
  blocking_decisions: number
}

export interface Spec {
  id: string
  application_id: number | null
  version: number
  parent_spec_id: string | null
  phase: Phase
  goal: Goal | null
  roles: Role[]
  objects: ObjectSpec[]
  dicts: DictSpec[]
  permissions: PermissionSpec[]
  decisions_pending: Decision[]
  decisions_resolved: Decision[]
  completeness: Completeness
  created_at: string
  updated_at: string
  created_by: number
}

export type ItemType = 'role' | 'object' | 'field' | 'dict' | 'permission'
export type ItemAction = 'confirm' | 'dismiss' | 'update'
