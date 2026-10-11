"""The OAuth fixture must reject invalid grants rather than mask product bugs."""

import base64
import hashlib
import importlib.util
import io
import json
import re
import socket
import ssl
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ui_fixture.py"
spec = importlib.util.spec_from_file_location("ui_fixture", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Request:
    def __init__(self, path, method="GET", body=b"", headers=None):
        self.path, self.command = path, method
        self.headers = {"Content-Length": str(len(body)), **(headers or {})}
        self.rfile, self.wfile = io.BytesIO(body), io.BytesIO()
        self.response_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.response_headers[key] = value

    def end_headers(self):
        pass


class OAuthFixtureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="umbod-test-oauth-fixture-")
        root = Path(self.directory.name)
        self.fixture = module.Fixture(root, root, root, {})
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.fixture.close)

    def send(self, path, method="GET", body=b"", headers=None):
        request = Request(path, method, body, headers)
        self.fixture.handle(request)
        return request

    def test_idle_tls_connection_does_not_block_discovery(self):
        with (
            socket.create_connection(("127.0.0.1", self.fixture.https.server_port)),
            urlopen(
                self.fixture.issuer + "/.well-known/oauth-authorization-server",
                context=ssl.create_default_context(cafile=self.fixture.cert),
                timeout=2,
            ) as response,
        ):
            self.assertEqual(json.load(response)["issuer"], self.fixture.issuer)

    def grant(self):
        redirect = "http://127.0.0.1:9/desktop/oauth/callback/fixture"
        registration = self.send(
            "/register", "POST", json.dumps({"redirect_uris": [redirect]}).encode()
        )
        client = json.loads(registration.wfile.getvalue())["client_id"]
        verifier = "fixture-verifier-" * 4
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        page = self.send(
            "/authorize?"
            + urlencode(
                {
                    "client_id": client,
                    "redirect_uri": redirect,
                    "response_type": "code",
                    "code_challenge_method": "S256",
                    "code_challenge": challenge,
                    "state": "state-fixture",
                    "resource": self.fixture.endpoint,
                }
            )
        )
        self.assertEqual(page.status, 200)
        html = page.wfile.getvalue().decode()
        self.assertIn("document.forms[0].requestSubmit()", html)
        nonce = re.search(r'name="nonce" value="([^"]+)"', html)[1]
        approved = self.send("/approve", "POST", urlencode({"nonce": nonce}).encode())
        response = parse_qs(urlsplit(approved.response_headers["Location"]).query)
        self.assertEqual(response["state"], ["state-fixture"])
        self.assertEqual(response["iss"], [self.fixture.issuer])
        return {
            "grant_type": "authorization_code",
            "code": response["code"][0],
            "code_verifier": verifier,
            "client_id": client,
            "redirect_uri": redirect,
        }

    def test_pkce_one_use_codes_refresh_rotation_and_protected_mcp(self):
        self.assertEqual(self.send("/mcp", "POST").status, 401)
        grant = self.grant()
        wrong = {**grant, "code_verifier": "wrong"}
        self.assertEqual(
            self.send("/token", "POST", urlencode(wrong).encode()).status, 400
        )
        self.assertEqual(
            self.send("/token", "POST", urlencode(grant).encode()).status, 400
        )
        grant = self.grant()
        exchange = self.send("/token", "POST", urlencode(grant).encode())
        self.assertEqual(exchange.status, 200)
        tokens = json.loads(exchange.wfile.getvalue())
        self.assertEqual(
            self.send("/token", "POST", urlencode(grant).encode()).status, 400
        )
        refresh = urlencode(
            {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
        ).encode()
        self.assertEqual(self.send("/token", "POST", refresh).status, 200)
        self.assertEqual(self.send("/token", "POST", refresh).status, 400)
        message = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "fixture"}},
            }
        ).encode()
        self.assertEqual(
            self.send(
                "/mcp",
                "POST",
                message,
                {"Authorization": "Bearer " + tokens["access_token"]},
            ).status,
            200,
        )
        self.assertEqual(self.fixture.audit["calls"], 1)

    def test_rejects_unregistered_redirects_and_unauthorized_test_controls(self):
        bad = self.send(
            "/register",
            "POST",
            json.dumps({"redirect_uris": ["https://example.com/callback"]}).encode(),
        )
        self.assertEqual(bad.status, 400)
        self.assertEqual(self.send("/authorize?client_id=unknown").status, 400)
        self.assertEqual(self.send("/test/agent/stdio", "POST").status, 403)
        self.assertEqual(self.send("/test/oauth-ready").status, 403)
