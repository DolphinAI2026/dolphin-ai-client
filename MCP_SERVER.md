# MCP Server

This repository vendors the standalone aPaaS Builder MCP service under `mcp-server/`.

The layout is intentionally kept separate from the main app:

- `backend/` and `frontend/` are the main AI Builder app.
- `mcp-server/backend/` is the standalone MCP backend, default port `8004`.
- `mcp-server/frontend/` and `mcp-server/admin-spa/` are MCP-side UI assets.
- `start-mcp.sh` and `stop-mcp.sh` manage only the MCP service.

Local flow:

```bash
./start-mcp.sh --daemon
./start.sh --daemon
```

The main app proxies MCP calls to `http://127.0.0.1:8004` by default. Override with:

```env
MCP_V2_INTERNAL_BASE=http://your-mcp-host:8004
MCP_V2_HOST=your-mcp-host:8004
MCP_BRIDGE_BASE_URLS=http://your-mcp-host:8004/api/mcp/mcp
```

MCP endpoints:

- Main unified entry: `http://127.0.0.1:8004/api/mcp/mcp`
- Builder: `http://127.0.0.1:8004/api/mcp-builder/mcp`
- Coding: `http://127.0.0.1:8004/api/mcp-coding/mcp`
- Vibe: `http://127.0.0.1:8004/api/mcp-vibe/mcp`
- Design: `http://127.0.0.1:8004/api/mcp-design/mcp`

Use the main unified entry for new clients. The split Builder/Coding/Vibe/Design endpoints
are kept only for compatibility with older external MCP configurations.

Before running MCP for real environments, copy `mcp-server/backend/.env.example` to
`mcp-server/backend/.env` and fill in real aPaaS, database, LLM, JWT, and `MCP_API_KEYS`
values.
