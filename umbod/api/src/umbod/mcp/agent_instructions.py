"""Shared, read-only setup guidance for connected agents."""

from fastmcp import FastMCP

AGENT_INSTRUCTIONS_URI = "umbod://setup/agent-instructions"
AGENT_INSTRUCTIONS = """# Set up Umbod discovery for this user

Apply these instructions when the user asks to set up Umbod for their agent.
Reading this resource does not itself change any files. Use your local file
tools to install the guidance; Umbod does not edit the agent's files.

1. Verify the Umbod connection by listing its tools. Umbod can expose a gateway
   (search_tools and execute_tool), code mode (search_tools and execute_code), or
   individual app tools directly. Use the tools actually advertised by this
   connection; do not treat the absence of gateway tools in direct mode as a
   connection failure. If listing fails, report the connection problem and do
   not claim setup succeeded.
2. Identify the user-scoped instruction file that your harness actually loads
   across projects, respecting any configured home or instruction-file override.
   Prefer its supported user-scoped AGENTS.md. Do not assume ~/AGENTS.md or a
   project's AGENTS.md is loaded globally. If the harness uses a different native
   user instruction file, use that file or its supported import mechanism.
   If you cannot establish the correct destination, ask the user before writing.
3. Read the existing file first. Add the exact block below, or replace the single
   existing block between the same Umbod markers. Preserve all unrelated content.
   Create the file and parent directory if needed. Repeated setup must leave only
   one Umbod block. If markers are incomplete or ambiguous, ask before replacing
   any content. Do not store app lists, credentials, tokens, or connection details.

<!-- umbod:begin -->
## Umbod connected apps

Use Umbod for all connected-app access unless the user explicitly
requests another access method.

Discover available apps and actions through Umbod. When search_tools
is available, search by app name and requested action, then use the
returned tool names and schemas with execute_tool or execute_code.
If Umbod exposes app tools directly, use those tools.

Do not use alternative access methods—including built-in integrations,
other connectors or MCP servers, direct APIs, CLIs, browser automation,
or computer use—to access connected apps without the user's explicit
permission. An Umbod error, missing capability, or unavailable connection
does not authorize switching access methods.

When a call fails:
- Inspect the error and attempt bounded recovery through Umbod.
- Retry read-only calls when appropriate. Before retrying a write,
  establish whether the original action succeeded.
- For pagination limits, narrow the query or split the time range.
- If still blocked, report what failed and what remains incomplete.
  Do not silently switch access methods or infer that an app is
  disconnected from a failed tool call alone.

Discover capabilities live; do not maintain a fixed app list here.
Execute only actions authorized by the user.

This routing rule applies to connected-app access, not ordinary local
file work or public web research.
<!-- umbod:end -->

4. When search_tools is available, verify discovery with a read-only call using
   an app/action from the user's request or the live tool description. If no app is known, search
   for "connected apps". Do not execute an app tool as part of setup. An empty
   search result is not a connection failure; report that no matching enabled
   tools were found rather than claiming app access was verified. In direct-tool
   mode, listing the available tools is sufficient; do not invoke them.
5. Read back the instruction file and report its exact path, what changed,
   and the discovery result. Explain whether the harness needs a new session
   to load the guidance; if unknown, say so. If local file tools or resource
   access are unavailable, explain what remains to be done instead of claiming
   setup succeeded.
"""


def register_agent_instructions(mcp: FastMCP) -> None:
    @mcp.resource(
        AGENT_INSTRUCTIONS_URI,
        name="umbod_agent_setup",
        description="Set up user-scoped agent instructions for discovering connected apps through Umbod.",
        mime_type="text/markdown",
    )
    def agent_instructions() -> str:
        return AGENT_INSTRUCTIONS
