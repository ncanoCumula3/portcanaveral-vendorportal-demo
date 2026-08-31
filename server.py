#!/usr/bin/env python3
"""Port Canaveral PVMS demo site.

Serves the three prototype pages behind one HTTP Basic Auth credential. Standard
library only, so there is nothing to install and nothing to keep patched.

Render's Static Site product cannot do Basic Auth, which is why this is a small web
service instead. It still serves nothing but static files.

Routes
    /                     landing page, the three entry points
    /netsuite             Preferred Vendor Management System, NetSuite view
    /new-application      New Vendor Application
    /vendor-portal        Vendor Portal
    /healthz              unauthenticated, for the Render health check

Credentials come from PVMS_USER and PVMS_PASSWORD. The service refuses to start
without them, so an unprotected deploy is not possible by accident.

    PVMS_USER=... PVMS_PASSWORD=... python3 server.py
"""
from __future__ import annotations

import base64
import hmac
import logging
import os
import sys
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC = Path(__file__).resolve().parent / "static"
REALM = "Port Canaveral PVMS"

# route -> file in static/
ROUTES = {
    "/": "index.html",
    "/netsuite": "netsuite.html",
    "/new-application": "new-application.html",
    "/vendor-portal": "vendor-portal.html",
}
# Tolerate the shapes people actually type or paste.
ALIASES = {
    "/index.html": "/",
    "/home": "/",
    "/netsuite.html": "/netsuite",
    "/pvms": "/netsuite",
    "/pvms-netsuite": "/netsuite",
    "/new-application.html": "/new-application",
    "/application": "/new-application",
    "/apply": "/new-application",
    "/new": "/new-application",
    "/vendor-portal.html": "/vendor-portal",
    "/portal": "/vendor-portal",
    "/vendor": "/vendor-portal",
}

USER = os.environ.get("PVMS_USER", "").strip()
PASSWORD = os.environ.get("PVMS_PASSWORD", "").strip()

log = logging.getLogger("pvms")


def _expected_header() -> str:
    raw = f"{USER}:{PASSWORD}".encode()
    return "Basic " + base64.b64encode(raw).decode()


class Handler(BaseHTTPRequestHandler):
    server_version = "pvms"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------------ helpers
    def _send(self, status, body: bytes, ctype="text/html; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        # A demo that is being clicked through should never serve a stale page.
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _authorised(self) -> bool:
        got = self.headers.get("Authorization", "")
        # compare_digest on the whole header keeps the comparison constant time and
        # avoids leaking the username length separately from the password.
        return hmac.compare_digest(got, _expected_header())

    def _challenge(self):
        body = (b"<!doctype html><meta charset=utf-8>"
                b"<title>Sign in</title>"
                b"<body style=\"font:16px/1.6 system-ui;padding:3rem;color:#0d1f30\">"
                b"<h1 style=\"font-size:1.25rem\">Port Canaveral PVMS</h1>"
                b"<p>This preview is private. Sign in to continue.</p></body>")
        self._send(HTTPStatus.UNAUTHORIZED, body,
                   extra={"WWW-Authenticate": f'Basic realm="{REALM}", charset="UTF-8"'})

    # ------------------------------------------------------------------ verbs
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/") or "/"

        if path == "/healthz":
            self._send(HTTPStatus.OK, b"ok", "text/plain; charset=utf-8")
            return

        if not self._authorised():
            self._challenge()
            return

        path = ALIASES.get(path.lower(), path)
        name = ROUTES.get(path)
        if name is None:
            body = (b"<!doctype html><meta charset=utf-8><title>Not found</title>"
                    b"<body style=\"font:16px/1.6 system-ui;padding:3rem;color:#0d1f30\">"
                    b"<h1 style=\"font-size:1.25rem\">Page not found</h1>"
                    b"<p><a href=\"/\" style=\"color:#1a5fa8\">Back to the three entry "
                    b"points</a></p></body>")
            self._send(HTTPStatus.NOT_FOUND, body)
            return

        target = (STATIC / name).resolve()
        # Belt and braces: nothing outside static/ can ever be served.
        if not str(target).startswith(str(STATIC)) or not target.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
            return

        self._send(HTTPStatus.OK, target.read_bytes())

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)


def preflight() -> None:
    problems = []
    if not USER or not PASSWORD:
        problems.append("PVMS_USER and PVMS_PASSWORD must both be set")
    if len(PASSWORD) < 8:
        problems.append("PVMS_PASSWORD must be at least 8 characters")
    for route, name in ROUTES.items():
        if not (STATIC / name).is_file():
            problems.append(f"missing static file for {route}: static/{name}")
    if problems:
        for p in problems:
            print(f"refusing to start: {p}", file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    preflight()
    port = int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log.info("pvms up on 0.0.0.0:%d, user %s, %d entry points, started %s",
             port, USER, len(ROUTES) - 1,
             datetime.now(timezone.utc).isoformat(timespec="seconds"))
    for route in ROUTES:
        log.info("  route %s -> static/%s", route, ROUTES[route])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("stopping")
        srv.server_close()


if __name__ == "__main__":
    main()
