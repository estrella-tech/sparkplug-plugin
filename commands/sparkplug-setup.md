---
description: Authenticate with Sparkplug by extracting your JWT token from the browser
allowed-tools: mcp__Claude_in_Chrome__tabs_context_mcp, mcp__Claude_in_Chrome__navigate, mcp__Claude_in_Chrome__javascript_tool, Write, Bash
---

Set up Sparkplug authentication for the Atomic Fungi Sparkplug plugin.

Steps:
1. Use mcp__Claude_in_Chrome__tabs_context_mcp to get the current browser tab ID.
2. Navigate to https://my.sparkplug.app using mcp__Claude_in_Chrome__navigate.
3. Wait for the page to load, then use mcp__Claude_in_Chrome__javascript_tool to check login status:
   ```
   ({ loggedIn: !!localStorage.getItem('sparkplug::jwtToken'), groupId: localStorage.getItem('sparkplug::accountId') })
   ```
4. If not logged in, ask Giovanni to log in to Sparkplug in the browser, then retry.
5. Once logged in, extract the token via JavaScript:
   ```
   ({ token: localStorage.getItem('sparkplug::jwtToken'), groupId: localStorage.getItem('sparkplug::accountId'), userId: localStorage.getItem('sparkplug::userId') })
   ```
6. Save the extracted config to `~/.sparkplug/sparkplug.json` using the Write tool:
   ```json
   {"jwt_token": "<token>", "group_id": "<groupId>", "user_id": "<userId>"}
   ```
7. Verify setup by calling the sparkplug_setup_check MCP tool.
8. Report back: confirm the number of retailers found and that auth is working.
