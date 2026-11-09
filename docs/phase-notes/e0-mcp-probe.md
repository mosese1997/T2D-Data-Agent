# E0 探测 1：MCP Python SDK — GO ✅

- SDK：官方 `mcp` 2.3.0（2026-07-28 spec，FastMCP→MCPServer 改名后的 2.x API）
- **streamable-http server**：`MCPServer.run(transport="streamable-http")` 起服务 ✅
- **工具往返**：`@server.tool()` 自动提取 JSON Schema，客户端 `call_tool` 往返 ✅
- **D1 身份传播验证（关键）**：客户端 `create_mcp_http_client(headers={...})` 注入
  `X-T2D-*` 头 → 工具内 `ctx.headers` 完整拿到（user=42/workspace=1/task=99）✅
  —— 演进计划 D1（身份走请求头、不进工具参数）在协议层可行
- 2.x API 与大量 v1 教材不同（FastMCP→MCPServer、3元组→2元组、headers 经
  http_client 注入）——E1 按本探测的 API 形态实施
- 探测脚本：var/e0-probes/mcp_probe_{server,client}.py
