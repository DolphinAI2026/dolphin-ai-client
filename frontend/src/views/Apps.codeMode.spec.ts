import { describe, expect, it } from 'vitest'
import actionsSource from '@/components/code/CodeApplicationActions.vue?raw'
import appsSource from './Apps.vue?raw'

describe('Apps Code mode entry', () => {
  it('starts a Code session from a d-ai-code application id', () => {
    expect(appsSource).toContain("from '@/stores/mode'")
    expect(appsSource).toContain("from '@/api/codeRuntime'")
    expect(appsSource).toContain('isCodeRoutePath(route.path)')
    expect(appsSource).toContain('codeRuntimeApi.createSessionFromExternalApp')
    expect(appsSource).toContain('`/code/${created.public_id}`')
  })

  it('refreshes the outer rail after opening a Code application', () => {
    expect(appsSource).toContain("new CustomEvent('code-rail-refresh')")
    expect(appsSource).toContain('window.dispatchEvent')
  })

  it('loads Code applications through the unified tenant-scoped composable', () => {
    expect(appsSource).toContain("from '@/composables/useUnifiedCodeApplications'")
    expect(appsSource).toContain('useUnifiedCodeApplications')
    expect(appsSource).toContain('tenantId: user.tenantId')
    expect(appsSource).not.toContain('codeMode ? codeRuntimeApi.listApplications')
  })

  it('uses one unified application list with location filtering', () => {
    expect(appsSource).toContain("from '@/composables/useUnifiedCodeApplications'")
    expect(appsSource).toContain('useUnifiedCodeApplications')
    expect(appsSource).toContain('codeLocationFilter')
    expect(appsSource).toContain('全部')
    expect(appsSource).toContain('本机可用')
    expect(appsSource).toContain('远程可用')
    expect(appsSource).not.toContain('codeApplicationSource')
    expect(appsSource).not.toContain('storeCodeApplicationSource')
  })

  it('uses one add menu and one local dialog for both directory modes', () => {
    expect(appsSource).toContain('LocalCodeApplicationDialog')
    expect(appsSource).toContain('AddCodeApplicationMenu')
    expect(appsSource).toContain(':initial-directory-mode="localApplicationDirectoryMode"')
    expect(appsSource).not.toContain('ElMessageBox.prompt')
  })

  it('delegates location-aware opening and stages preference after shell creation', () => {
    expect(appsSource).toContain('CodeApplicationActions')
    expect(appsSource).toContain('location.external_application_id')
    expect(appsSource).toContain('stageCodeApplicationLocationPreference')
    expect(appsSource).toContain('created.public_id')
  })

  it('opens a selected application location with the complete resumable session contract', () => {
    expect(appsSource).toContain('logical_application_id: unified.logical_application_id')
    expect(appsSource).toContain('external_application_id: location.external_application_id')
    expect(appsSource).toContain('execution_location: executionLocation')
    expect(appsSource).toContain("session_policy: 'resume_recent'")
    expect(appsSource).toContain("session_purpose: 'standard'")
  })

  it('shows location recovery instead of automatically falling back from an unavailable preference', () => {
    expect(appsSource).toContain('CodeApplicationRecoveryPanel')
    expect(appsSource).toContain('showCodeApplicationRecovery')
    expect(appsSource).toContain('@recover="location => showCodeApplicationRecovery(app, location)"')
    expect(appsSource).toContain('@open-other="openCodeApplicationRecoveryAlternative"')
    expect(appsSource).not.toContain('请主动选择其他位置')
  })

  it('disables every location action and rejects emits while opening', () => {
    expect(actionsSource).toContain(':disabled="actionOpening"')
    expect(actionsSource).toContain('if (!canOpenCodeApplicationLocation')
  })

  it('keeps location filters visible while application status remains a dropdown filter', () => {
    expect(appsSource).toContain('class="apps-location-switch"')
    expect(appsSource).toContain('class="apps-status-filter"')
    expect(appsSource).toContain('<el-select')
    expect(appsSource).toContain('v-model="activeTab"')
    expect(appsSource).not.toContain('class="apps-tabs"')
  })
})
