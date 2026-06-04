import request from '@/utils/request'

export interface EditorUrlResp { ok: boolean; url?: string; message?: string; error_code?: string }

export function getEditorUrl(
  appId: number,
  params: { menu_type?: string; menu_id?: string; form_id?: string } = {},
): Promise<EditorUrlResp> {
  return request({ url: `/applications/${appId}/editor-url`, method: 'get', params }) as unknown as Promise<EditorUrlResp>
}
