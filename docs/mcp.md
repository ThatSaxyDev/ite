# MCP Servers

iTE supports the Model Context Protocol (MCP) for extending capabilities with external tools.

Open **Settings → Connections (MCP) → Manage connections** to add and manage servers. This page is available even when you are signed out of iTE Cloud.

Choose GitHub, Notion, a custom URL, a local server, or import JSON/TOML. Save the definition, enter credentials if needed, then choose Connect or Sign in. Existing TOML definitions appear automatically, including disabled connections and definitions that need repair. Advanced settings remain available in the form.

Use the connection detail page to disconnect, reconnect, enable or disable, choose which tools the agent can use, troubleshoot, sign out, or remove a connection. “All projects” and “This project” are separate scopes; a project definition with the same name takes precedence.

New saved credentials use the operating system keyring. If you do not want to save a credential, uncheck Remember in the credentials form to use it for the current session. Local servers require approval of the executable and arguments before startup. Changing that launch definition requires another review.

GitHub uses a bearer token at its official remote endpoint. Notion uses browser sign-in. These recipes have fixture coverage; live authentication and provider tasks still need verification in your own test accounts.

Existing TOML keys, server names, names such as `server__tool`, and CLI/slash commands remain supported. `/mcp` opens Connections and `/mcp add` opens the add form; command forms with arguments retain their existing behavior. Local auto-start waits for launch approval, and browser authorization begins from an explicit Sign in action.

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
