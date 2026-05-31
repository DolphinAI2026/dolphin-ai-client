# Legacy apaas-builder MCP Manifests

这里保存的是历史上部署在 `apaas-builder` namespace 里的 MCP Server manifests。

这些文件只用于盘点和短期回滚参考，不再作为 MCP 新功能或新配置的修改位置。
新的 MCP Server 资源应全部维护在 `apaas-mcp-server` namespace，并通过
`../20-mcp-server.yaml` 和 `../30-ingress.yaml` 部署。
