"""Loopback-only OAuth/MCP fixture and agent oracle for packaged UI acceptance.

Never bundled in Umbod. OAuth automatically consents to a synthetic account, but
only a browser executing the consent page can complete the redirect. Token
exchange still verifies registration, redirect URI, one-use code and S256 PKCE.
"""

import base64
import hashlib
import json
import secrets
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


class Fixture:
    def __init__(self, root, app, kit, directories):
        self.root, self.app, self.kit = map(Path, (root, app, kit))
        self.directories = directories
        self.capability = secrets.token_urlsafe(32)
        self.clients, self.consents, self.codes = {}, {}, {}
        self.access, self.refresh = set(), set()
        self.audit = {
            "browser_visits": 0,
            "exchanges": 0,
            "refreshes": 0,
            "rejected": 0,
            "calls": 0,
        }
        self.requests = []
        self.lock = threading.RLock()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                # Negotiate in the worker thread: an idle/preconnected socket
                # must not block the listener from accepting OAuth connections.
                self.request.settimeout(10)
                if isinstance(self.request, ssl.SSLSocket):
                    self.request.do_handshake()
                super().setup()

            def log_message(self, *_args):
                pass

            def do_GET(self):
                fixture.handle(self)

            def do_POST(self):
                fixture.handle(self)

            def do_DELETE(self):
                self.send_response(204)
                self.end_headers()

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.https = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.http.server_port}"
        self.issuer = f"https://127.0.0.1:{self.https.server_port}"
        self.endpoint = self.issuer + "/mcp"
        self.cert = self.root / "fixture-ca.pem"
        key = self.root / "fixture-key.pem"
        config = self.root / "openssl.cnf"
        config.write_text(
            "[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ext\n[dn]\nCN=Umbod isolated UI fixture\n[ext]\nsubjectAltName=IP:127.0.0.1\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n"
        )
        subprocess.run(
            [
                "/usr/bin/openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-config",
                str(config),
                "-keyout",
                str(key),
                "-out",
                str(self.cert),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, key)
        self.https.socket = context.wrap_socket(
            self.https.socket, server_side=True, do_handshake_on_connect=False
        )
        for server in (self.http, self.https):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def close(self):
        for server in (self.http, self.https):
            server.shutdown()
            server.server_close()

    def respond(self, request, status, body=None, headers=None):
        if not request.path.startswith("/test/"):
            self.requests.append(
                {
                    "method": request.command,
                    "path": urlsplit(request.path).path,
                    "status": status,
                }
            )
        data = json.dumps(body or {}).encode()
        request.send_response(status)
        request.send_header("Content-Type", "application/json")
        request.send_header("Content-Length", str(len(data)))
        request.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            request.send_header(name, value)
        request.end_headers()
        request.wfile.write(data)

    def token(self):
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.access.add(access)
        self.refresh.add(refresh)
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "mcp",
        }

    def handle(self, request):
        path = urlsplit(request.path).path
        raw = request.rfile.read(int(request.headers.get("Content-Length", "0")))
        if path.startswith("/test/"):
            if request.headers.get("Authorization") != "Bearer " + self.capability:
                return self.respond(request, 403)
            if path == "/test/agent/stdio" or path == "/test/agent/oauth":
                directory = self.directories[path.rsplit("/", 1)[1]]
                profile = (
                    (self.app / "Contents/Resources/umbod-profile").read_text().strip()
                )
                result = subprocess.run(
                    [
                        str(self.app / "Contents/Resources/python/bin/python3"),
                        "-I",
                        "-B",
                        str(self.kit / "scripts/fixture_agent.py"),
                        str(self.app / "Contents/MacOS/umbod-desktop"),
                        str(directory),
                        profile,
                    ],
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
                if result.returncode:
                    print(
                        result.stderr.decode(errors="replace")[-8000:],
                        file=sys.stderr,
                        flush=True,
                    )
                return self.respond(
                    request,
                    200 if result.returncode == 0 else 500,
                    {"passed": result.returncode == 0},
                )
            if path == "/test/oauth-ready":
                directory = self.directories["oauth"]
                try:
                    record = json.loads((directory / "python-runtime.json").read_text())
                    vault = json.loads(
                        (directory / "fixture-credentials.json").read_text()
                    )
                    address = record["management"]
                    assert urlsplit("http://" + address).hostname == "127.0.0.1"
                    with urlopen(
                        Request(
                            "http://" + address + "/desktop/state",
                            headers={
                                "Authorization": "Bearer " + vault["python:admin-token"]
                            },
                        ),
                        timeout=2,
                    ) as response:
                        state = json.load(response)
                    ready = "signed_in" in state.get("oauth_status", {}).values()
                    failed = "failed" in state.get("oauth_status", {}).values()
                except (OSError, ValueError, KeyError):
                    ready = False
                    failed = False
                return self.respond(
                    request, 200, {"ready": ready, "failed": failed, **self.audit}
                )
            return self.respond(request, 404)
        with self.lock:
            try:
                return self.oauth_request(request, path, raw)
            except (ValueError, KeyError, AssertionError) as error:
                self.audit["last_error"] = type(error).__name__ + " at " + path
                self.audit["rejected"] += 1
                return self.respond(request, 400, {"error": "invalid_request"})

    def oauth_request(self, request, path, raw):
        if path.startswith("/.well-known/oauth-protected-resource"):
            return self.respond(
                request,
                200,
                {
                    "resource": self.endpoint,
                    "authorization_servers": [self.issuer],
                    "scopes_supported": ["mcp"],
                    "bearer_methods_supported": ["header"],
                },
            )
        if path == "/.well-known/oauth-authorization-server":
            return self.respond(
                request,
                200,
                {
                    "issuer": self.issuer,
                    "authorization_endpoint": self.origin + "/authorize",
                    "token_endpoint": self.issuer + "/token",
                    "registration_endpoint": self.issuer + "/register",
                    "response_types_supported": ["code"],
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"],
                    "scopes_supported": ["mcp"],
                },
            )
        if path == "/register" and request.command == "POST":
            metadata = json.loads(raw)
            for uri in metadata["redirect_uris"]:
                parsed = urlsplit(uri)
                assert (
                    parsed.scheme == "http"
                    and parsed.hostname == "127.0.0.1"
                    and parsed.path.startswith("/desktop/oauth/callback/")
                )
            client = secrets.token_urlsafe(16)
            self.clients[client] = metadata
            return self.respond(
                request,
                201,
                {**metadata, "client_id": client, "token_endpoint_auth_method": "none"},
            )
        if path == "/authorize" and request.command == "GET":
            values = {
                key: value[0]
                for key, value in parse_qs(urlsplit(request.path).query).items()
            }
            assert (
                values["redirect_uri"]
                in self.clients[values["client_id"]]["redirect_uris"]
            )
            assert (
                values["response_type"] == "code"
                and values["code_challenge_method"] == "S256"
                and values["state"]
            )
            assert values.get("resource", self.endpoint) == self.endpoint
            nonce = secrets.token_urlsafe(32)
            self.consents[nonce] = values
            self.audit["browser_visits"] += 1
            # Synthetic account: no real password/account, no browser certificate exception.
            # JavaScript completion proves this step actually passed through a browser.
            html = f'<!doctype html><title>Umbod test sign-in</title><p>Signing in to the local Umbod test fixture…</p><form method="post" action="/approve"><input type="hidden" name="nonce" value="{nonce}"><button>Allow test connector</button></form><script>document.forms[0].requestSubmit()</script>'.encode()
            request.send_response(200)
            request.send_header("Content-Type", "text/html; charset=utf-8")
            request.send_header("Content-Length", str(len(html)))
            request.send_header("Cache-Control", "no-store")
            request.end_headers()
            request.wfile.write(html)
            return
        if path == "/approve" and request.command == "POST":
            values = self.consents.pop(parse_qs(raw.decode())["nonce"][0])
            code = secrets.token_urlsafe(32)
            self.codes[code] = (values, time.monotonic())
            return self.respond(
                request,
                302,
                headers={
                    "Location": values["redirect_uri"]
                    + "?"
                    + urlencode(
                        {"code": code, "state": values["state"], "iss": self.issuer}
                    )
                },
            )
        if path == "/token" and request.command == "POST":
            values = {key: value[0] for key, value in parse_qs(raw.decode()).items()}
            if values["grant_type"] == "refresh_token":
                self.refresh.remove(values["refresh_token"])
                self.audit["refreshes"] += 1
                return self.respond(request, 200, self.token())
            assert values["grant_type"] == "authorization_code"
            grant, created = self.codes.pop(values["code"])
            assert time.monotonic() - created < 60
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(values["code_verifier"].encode()).digest()
                )
                .decode()
                .rstrip("=")
            )
            assert challenge == grant["code_challenge"]
            assert (
                values["client_id"] == grant["client_id"]
                and values["redirect_uri"] == grant["redirect_uri"]
            )
            self.audit["exchanges"] += 1
            return self.respond(request, 200, self.token())
        if path == "/mcp":
            if (
                request.headers.get("Authorization", "").removeprefix("Bearer ")
                not in self.access
            ):
                self.audit["rejected"] += 1
                return self.respond(
                    request,
                    401,
                    headers={
                        "WWW-Authenticate": f'Bearer resource_metadata="{self.issuer}/.well-known/oauth-protected-resource"'
                    },
                )
            if request.command != "POST":
                return self.respond(request, 405)
            message = json.loads(raw)
            if "id" not in message:
                return self.respond(request, 202)
            method = message["method"]
            if method == "initialize":
                result = {
                    "protocolVersion": message["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "umbod-oauth-fixture", "version": "1"},
                }
            elif method == "tools/list":
                # Real providers can take longer than HTTPX's default five seconds.
                # Exercise that boundary in the exact-DMG OAuth release journey.
                time.sleep(6)
                result = {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "OAuth fixture echo",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        }
                    ]
                }
            elif method == "tools/call":
                self.audit["calls"] += 1
                result = {
                    "content": [
                        {"type": "text", "text": message["params"]["arguments"]["text"]}
                    ]
                }
            elif method == "ping":
                result = {}
            else:
                return self.respond(
                    request,
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {
                            "code": -32601,
                            "message": "Unsupported fixture method",
                        },
                    },
                )
            return self.respond(
                request, 200, {"jsonrpc": "2.0", "id": message["id"], "result": result}
            )
        return self.respond(request, 404)
