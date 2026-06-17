# MCP Servers

iTE supports the Model Context Protocol (MCP) for extending capabilities with external tools.

## What MCP Does

MCP servers provide specialized capabilities:
- Database access
- API integrations
- Custom tools
- External services

## Configuration

Configure MCP servers in `.ite/config.toml`:

```toml
[mcp_servers.sqlite]
command = "uvx"
args = ["mcp-server-sqlite", "--db-path", "data.db"]
auto_connect = true

[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/files"]
```

## Commands

```
# Show MCP server status
/mcp

# Connect a server
/mcp start <name>

# Disconnect a server
/mcp stop <name>
```

## Security

MCP servers run as separate processes. Review configurations before connecting to new servers.

---

[Back to usage →](usage.md)
