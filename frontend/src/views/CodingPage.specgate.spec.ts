import { describe, it, expect } from 'vitest'
import src from './CodingPage.vue?raw'
import styles from './CodingPage.styles.css?raw'
import pipeSrc from './coding/useCodingPipeline.ts?raw'

// 方案 B:SPEC 确认门去按钮、改对话式(对齐 Builder)。这些断言锁住实现,防回归
// (CodingPage.vue 太大无法在 jsdom 挂载,沿用本仓 ?raw 源码断言约定,运行时由真机验)。
describe('CodingPage SPEC 确认门 → 对话式(方案 B)', () => {
  it('删掉按钮确认门:awaitingSpecConfirm / confirmSpec / coding-confirm-bar 都不再存在', () => {
    expect(src).not.toContain('awaitingSpecConfirm')
    expect(src).not.toContain('confirmSpec')
    expect(src).not.toContain('coding-confirm-bar')
    expect(src).not.toContain('ccb-btn')
    // 确认门 CSS 也清干净
    expect(styles).not.toContain('coding-confirm-bar')
    expect(styles).not.toContain('.ccb-')
  })

  it('出 SPEC 改对话式引导:回复「开始」即写代码 / 补充需求即调整', () => {
    expect(src).toContain('确认无误回复「开始」')
    expect(src).toContain('要调整直接补充需求')
  })

  it('多版 SPEC 去重只留最新:lastSpecIdx 预扫 + 最新那条出可折叠 SPEC 卡', () => {
    expect(src).toContain('lastSpecIdx')
    expect(src).toContain('SPEC_RE')
    // 最新 SPEC → 对话折叠卡(custom + isSpec);CTA 仅审阅态(不流式 + 无 codegen 产物)
    expect(src).toMatch(/i === lastSpecIdx/)
    expect(src).toContain('isSpec: true')
    expect(src).toMatch(/!isStreaming\.value && !codingArtifactsHasAny\.value/)
  })

  it('早期版本 / 已进入 codegen 时,SPEC 收成一行里程碑(不堆叠、不误喊回复开始)', () => {
    expect(src).toContain('📋 已生成开发 SPEC')
  })
})

// 右侧产物面板(开发文档/产物清单/接入说明)整块删除:SPEC 进对话折叠卡,部署进输入区上方 deploy-bar。
describe('CodingPage 右侧产物面板已删除', () => {
  // 注:?raw 导入 .css 在 vitest 里返回空串,故 CSS 只能断言 .vue 模板里用到的 class 名(在 src 中)。
  it('面板模板 + 产物按钮 + 面板 state 全清', () => {
    expect(src).not.toContain('coding-artifact-panel')
    expect(src).not.toContain('showCodingArtifactPanel')
    expect(src).not.toContain('toggleCodingArtifactPanel')
    expect(src).not.toContain('codingArtifactTab')
    expect(src).not.toContain('specViewMode')
  })

  it('SPEC 改对话可折叠卡(复用思维链卡样式)+ 仍套 SPEC 文档 markdown 观感(cap-spec-doc)', () => {
    expect(src).toContain('msg-spec-card')
    expect(src).toContain('isSpec')
    expect(src).toContain('cap-spec-doc')  // SPEC 卡 body 仍套 cap-spec-doc 观感
  })

  it('部署栏(deploy-bar)已按用户要求去掉', () => {
    expect(src).not.toContain('coding-deploy-bar')
  })
})

describe('useCodingPipeline brainstorm 步骤标签(方案 B)', () => {
  it('出 SPEC 的步骤胶囊去掉「待确认」,只报里程碑「已生成开发 SPEC」', () => {
    expect(pipeSrc).toContain('已生成开发 SPEC')
    expect(pipeSrc).not.toContain('开发 SPEC 待确认')
  })

  it('澄清 / skip 分支标签保持不变', () => {
    expect(pipeSrc).toContain('澄清问题待回答')
    expect(pipeSrc).toContain('已分析需求')
  })
})
