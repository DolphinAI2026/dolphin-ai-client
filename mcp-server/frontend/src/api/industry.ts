import request from '@/utils/request'

export interface IndustryStats {
  entities: number
  relations: number
  workflows: number
  dicts: number
  forms: number
  roles: number
}

export interface IndustryPack {
  id: string
  name: string
  code: string
  tone: string
  version: string
  installed: boolean
  default: boolean
  summary: string
  stats: IndustryStats
  adopted: string[]
  maintainer: string
  updated: string
}

export interface IndustryPackListResponse {
  packs: IndustryPack[]
}

export interface OntologyEntity {
  code: string
  name: string
  fields: number
  x: number
  y: number
  tone: string
  hot?: boolean
}

export interface OntologyRelation {
  from: string
  to: string
  label: string
}

export interface OntologyWorkflow {
  name: string
  nodes: number
  sla: string
}

export interface OntologyDict {
  code: string
  name: string
  items: number
}

export interface OntologyResponse {
  pack: string
  entities: OntologyEntity[]
  relations: OntologyRelation[]
  workflows: OntologyWorkflow[]
  dictHighlight: OntologyDict[]
}

export interface InstallResponse {
  ok: boolean
  installed: boolean
}

export const industryApi = {
  listPacks(): Promise<IndustryPackListResponse> {
    return request({ url: '/industry/packs', method: 'get' }) as unknown as Promise<IndustryPackListResponse>
  },
  getOntology(packId: string): Promise<OntologyResponse> {
    return request({
      url: `/industry/packs/${packId}/ontology`,
      method: 'get',
    }) as unknown as Promise<OntologyResponse>
  },
  install(packId: string): Promise<InstallResponse> {
    return request({
      url: `/industry/packs/${packId}/install`,
      method: 'post',
    }) as unknown as Promise<InstallResponse>
  },
}
