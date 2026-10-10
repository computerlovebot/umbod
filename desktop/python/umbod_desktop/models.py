"""Validated host requests contain credential references, never secret values."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from umbod.core.connectors.downstream_mcp.models import EndpointUrl


class DesktopServer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = ""
    host_id: str = ""
    name: str = Field(min_length=1, max_length=200)
    transport: Literal["stdio", "http"]
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    oauth: bool = False
    headers: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transport(self):
        if self.transport == "stdio" and not self.command.strip():
            raise ValueError("A local executable is required")
        if self.transport == "http":
            TypeAdapter(EndpointUrl).validate_python(self.url)
        if any(
            not reference.startswith("upstream:")
            for reference in (*self.headers.values(), *self.env.values())
        ):
            raise ValueError("Credentials must be upstream Keychain references")
        return self


def loopback_origin(address: str) -> str:
    parsed = urlsplit("http://" + address)
    if (
        parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.port is None
    ):
        raise ValueError("Invalid loopback endpoint")
    return f"http://127.0.0.1:{parsed.port}"
