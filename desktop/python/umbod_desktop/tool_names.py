"""Repair desktop-generated namespaces through the shared administration API."""

import logging
import re

import httpx
from umbod.core.capabilities.tools.names import mangle_public_tool_name
from umbod.core.connectors.downstream_mcp.models import default_tool_name_prefix

_LOGGER = logging.getLogger(__name__)
_GENERATED_PREFIX = re.compile(
    r"(?:desktop_[0-9a-f]{8}(?:_[0-9a-f]{4}){3}_[0-9a-f]{12}|import_[0-9a-f]{24})"
)


class DesktopToolNames:
    def __init__(self, request):
        self.request = request

    async def inventory(self):
        listed = await self.request("GET", "/connectors/mcp")
        return [
            await self.request("GET", f"/connectors/mcp/{item['connector_id']}")
            for item in listed["connectors"]
        ]

    @staticmethod
    def available_prefix(display_name, definitions):
        # Use the backend's naming policy, not a second desktop normalizer.
        base = default_tool_name_prefix(display_name)
        reserved = {
            mangle_public_tool_name(item["tool_name_prefix"], "")
            for item in definitions
        }
        candidate, suffix = base, 2
        while mangle_public_tool_name(candidate, "") in reserved:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    async def repair(self, state):
        """Retry safely on startup; never recreate connectors or rewrite grants."""
        managed_ids = {
            item.get("id") for item in state.data.get("servers", {}).values()
        }
        if not managed_ids:
            return
        try:
            definitions = await self.inventory()
            for definition in sorted(definitions, key=lambda item: item["connector_id"]):
                prefix = definition["tool_name_prefix"]
                if (
                    definition["connector_id"] not in managed_ids
                    or not _GENERATED_PREFIX.fullmatch(prefix)
                    or definition["public_path"].removeprefix("/mcp/proxies/")
                    .replace("-", "_") != prefix
                ):
                    continue
                candidate = self.available_prefix(definition["display_name"], definitions)
                try:
                    await self.request(
                        "PATCH", f"/connectors/mcp/{definition['connector_id']}",
                        {"tool_name_prefix": candidate},
                    )
                except httpx.HTTPStatusError:
                    # The shared API also checks cross-kind/operation collisions.
                    # Preserve the working name if it rejects this candidate.
                    _LOGGER.warning(
                        "Desktop tool namespace repair deferred for connector %s",
                        definition["connector_id"],
                    )
                    continue
                definition["tool_name_prefix"] = candidate
        except httpx.HTTPError:
            # A failed metadata repair must not prevent existing tools from working.
            _LOGGER.warning("Desktop tool namespace repair deferred; retry on restart")
