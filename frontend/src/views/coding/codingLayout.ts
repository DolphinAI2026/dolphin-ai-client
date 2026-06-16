export type CodingMainPaneStyle = {
  flex: string
  width: string
} | null

export function getCodingMainPaneStyle(
  codeFirst: boolean,
  chatExpanded: boolean,
  chatPaneWidth: number,
): CodingMainPaneStyle {
  if (!codeFirst || chatExpanded) return null
  return {
    flex: `0 0 ${chatPaneWidth}px`,
    width: `${chatPaneWidth}px`,
  }
}

export function shouldShowWorkspacePane(
  workspaceId: string | null | undefined,
  embeddedAppId: number | string | null | undefined,
  chatExpanded: boolean,
): boolean {
  return !!workspaceId && !embeddedAppId && !chatExpanded
}
