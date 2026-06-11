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

/**
 * VS Code 式 compact folders: 单子目录链(com→xdap→legacyquery)合并成一个
 * "com/xdap/legacyquery" 节点,省掉深包名的逐层缩进。返回新树,不改原树。
 */
export function compactTree(nodes: TreeNode[]): TreeNode[] {
  return nodes.map(n => {
    if (!n.isDir) return n
    let name = n.name
    let node = n
    while (node.children && node.children.length === 1 && node.children[0].isDir) {
      node = node.children[0]
      name = `${name}/${node.name}`
    }
    return { ...node, name, children: compactTree(node.children || []) }
  })
}

function sortTree(nodes: TreeNode[]): void {
  nodes.sort((a, b) => {
    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1
    return a.name.localeCompare(b.name)
  })
  for (const n of nodes) if (n.children) sortTree(n.children)
}

// 构建产物判定(与后端 git_changes._ARTIFACT_SUFFIXES 对齐): 树节点置灰/改动面板折叠用
const ARTIFACT_SUFFIXES = ['.umd.js', '.umd.min.js', '.common.js', '.min.js', '.zip', '.map', '.jar']

export function isBuildArtifact(path: string): boolean {
  const low = path.toLowerCase()
  return ARTIFACT_SUFFIXES.some(s => low.endsWith(s)) || low.startsWith('dist/') || low.includes('/dist/')
}
