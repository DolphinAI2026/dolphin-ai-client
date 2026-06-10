export interface TreeNode {
  name: string
  path: string
  isDir: boolean
  children?: TreeNode[]
}

export function buildFileTree(paths: string[]): TreeNode[] {
  const root: TreeNode[] = []
  for (const full of paths) {
    const parts = full.split('/').filter(Boolean)
    let level = root
    let acc = ''
    parts.forEach((part, i) => {
      acc = acc ? `${acc}/${part}` : part
      const isDir = i < parts.length - 1
      let node = level.find(n => n.name === part && n.isDir === isDir)
      if (!node) {
        node = { name: part, path: acc, isDir }
        if (isDir) node.children = []
        level.push(node)
      }
      if (isDir) level = node.children!
    })
  }
  sortTree(root)
  return root
}

function sortTree(nodes: TreeNode[]): void {
  nodes.sort((a, b) => {
    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1
    return a.name.localeCompare(b.name)
  })
  for (const n of nodes) if (n.children) sortTree(n.children)
}
