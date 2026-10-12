from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from umbod_desktop.tool_names import DesktopToolNames

LEGACY = "desktop_46b824c3_b082_4a1a_8177_c2c096eec4ce"


def definition(identifier, name, prefix=LEGACY, path=None):
    return {
        "connector_id": identifier,
        "display_name": name,
        "tool_name_prefix": prefix,
        "public_path": path or "/mcp/proxies/" + prefix.replace("_", "-"),
    }


class Administration:
    def __init__(self, *definitions, rejected=()):
        self.definitions = {item["connector_id"]: item for item in definitions}
        self.patches = []
        self.rejected = rejected

    async def request(self, method, path, body=None):
        if path == "/connectors/mcp":
            return {"connectors": list(self.definitions.values())}
        identifier = path.rsplit("/", 1)[1]
        if method == "PATCH":
            self.patches.append((identifier, body))
            if identifier in self.rejected:
                response = httpx.Response(409, request=httpx.Request(method, "http://test"))
                response.raise_for_status()
            self.definitions[identifier].update(body)
        return deepcopy(self.definitions[identifier])


def managed(*identifiers):
    return SimpleNamespace(data={"servers": {key: {"id": key} for key in identifiers}})


@pytest.mark.asyncio
async def test_repairs_only_managed_generated_prefixes_and_is_idempotent():
    admin = Administration(
        definition("dinero", "Dinero"),
        definition("imported", "Cloudflare", "import_" + "a" * 24),
        definition("custom", "Dinero", "my_finance"),
        definition("unmanaged", "External"),
        definition("different_path", "Deliberate", path="/mcp/proxies/custom"),
    )
    state = managed("dinero", "imported", "custom", "different_path")
    names = DesktopToolNames(admin.request)
    await names.repair(state)
    assert admin.patches == [
        ("dinero", {"tool_name_prefix": "Dinero"}),
        ("imported", {"tool_name_prefix": "Cloudflare"}),
    ]
    assert admin.definitions["dinero"]["public_path"] == "/mcp/proxies/" + LEGACY.replace("_", "-")
    await names.repair(state)
    assert len(admin.patches) == 2


@pytest.mark.asyncio
async def test_duplicate_names_receive_readable_stable_suffixes():
    admin = Administration(
        definition("a", "Finance API"),
        definition("b", "Finance API"),
        definition("custom", "Other", "Finance-API"),
    )
    names = DesktopToolNames(admin.request)
    await names.repair(managed("a", "b"))
    assert admin.patches == [
        ("a", {"tool_name_prefix": "Finance_API_2"}),
        ("b", {"tool_name_prefix": "Finance_API_3"}),
    ]
    await names.repair(managed("a", "b"))
    assert len(admin.patches) == 2


@pytest.mark.asyncio
async def test_rejected_repair_preserves_working_prefix_and_continues(caplog):
    admin = Administration(
        definition("a", "Dinero"), definition("b", "Cloudflare"), rejected={"a"}
    )
    await DesktopToolNames(admin.request).repair(managed("a", "b"))
    assert admin.definitions["a"]["tool_name_prefix"] == LEGACY
    assert admin.definitions["b"]["tool_name_prefix"] == "Cloudflare"
    assert "repair deferred for connector a" in caplog.text
