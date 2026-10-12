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

Umbod provides access to connected apps. Before searching for plugins or
concluding an app is unavailable, check Umbod. When search_tools is available,
search using the app name and requested action. Use the returned names and
schemas with execute_tool, or follow execute_code's instructions if that is
what the server exposes. If Umbod exposes app tools directly, inspect those
instead. Execute only actions the user requested. If the Umbod connection is
unavailable, report the connection issue. Connected apps and available tools
can change; discover them through Umbod rather than keeping an app list in
these instructions.
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
