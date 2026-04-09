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
5. Once logged in, run the Python setup script via Bash to extract and save the token:
   ```
   cd "${CLAUDE_PLUGIN_ROOT}/servers" && bash -c 'source .venv/bin/activate 2>/dev/null || true; python auth.py'
   ```
   The auth.py script will use Playwright to open Sparkplug, extract the token, and save it to config/sparkplug.json.
6. Verify setup by calling the sparkplug_setup_check MCP tool.
7. Report back: confirm the number of retailers found and that auth is working.

If Playwright is not yet installed, run:
```
bash "${CLAUDE_PLUGIN_ROOT}/servers/start.sh" --version 2>&1 || true
```
which will trigger first-time dependency installation.
