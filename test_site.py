#!/usr/bin/env python3
"""End to end checks against a real running server.

Starts server.py on a spare port with known credentials, exercises every route, then
shuts it down. No mocks: this is the same code path Render runs.

    python3 test_site.py
"""
from __future__ import annotations

import base64
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
USER, PASSWORD = "testuser", "testpassword123"
BAD = base64.b64encode(b"testuser:wrong").decode()
GOOD = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()

passed, failed = 0, 0


def check(label: str, got, want) -> None:
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ok    {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}: got {got!r}, want {want!r}")


def get(base: str, path: str, auth: str | None = None):
    req = urllib.request.Request(base + path)
    if auth:
        req.add_header("Authorization", "Basic " + auth)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "PVMS_USER": USER, "PVMS_PASSWORD": PASSWORD, "PORT": str(port)}
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(60):
            try:
                req = urllib.request.Request(base + "/healthz")
                req.add_header("Authorization", "Basic " + GOOD)
                urllib.request.urlopen(req, timeout=1)
                break
            except Exception:
                if proc.poll() is not None:
                    print("server exited:\n" + (proc.stdout.read() if proc.stdout else ""))
                    return 1
                time.sleep(0.1)
        else:
            print("server did not come up")
            return 1

        print("\nauthentication")
        check("no credentials on / is 401", get(base, "/")[0], 401)
        check("wrong password is 401", get(base, "/", BAD)[0], 401)
        check("challenge sends WWW-Authenticate",
              "Basic" in get(base, "/")[2].get("WWW-Authenticate", ""), True)
        check("correct credentials on / is 200", get(base, "/", GOOD)[0], 200)
        for p in ("/netsuite", "/new-application", "/vendor-portal"):
            check(f"no credentials on {p} is 401", get(base, p)[0], 401)

        print("\nhealth check is protected too")
        check("/healthz is 401 without credentials", get(base, "/healthz")[0], 401)
        st, body, _ = get(base, "/healthz", GOOD)
        check("/healthz is 200 with credentials", st, 200)
        check("/healthz body", body.strip(), "ok")

        print("\nentry points")
        expect = {
            "/": "Preferred Vendor Management System",
            "/new-application": "New Vendor Application",
            "/vendor-portal": "Vendor Portal",
            "/netsuite": "Preferred Vendor Management System",
        }
        for path, needle in expect.items():
            st, body, _ = get(base, path, GOOD)
            check(f"{path} is 200", st, 200)
            check(f"{path} contains {needle!r}", needle in body, True)

        print("\nlanding page links to all three")
        _, home, _ = get(base, "/", GOOD)
        for p in ("/new-application", "/vendor-portal", "/netsuite"):
            check(f"landing links {p}", f'href="{p}"' in home, True)

        print("\nswitcher on every mockup")
        for p in ("/netsuite", "/new-application", "/vendor-portal"):
            _, body, _ = get(base, p, GOOD)
            check(f"{p} has the switcher", "pvms-switcher:start" in body, True)
            for link in ("/", "/netsuite", "/new-application", "/vendor-portal"):
                check(f"{p} switcher links {link}", f'href="{link}"' in body, True)

        print("\naliases")
        for alias, needle in [("/apply", "New Vendor Application"),
                              ("/portal", "Vendor Portal"),
                              ("/pvms", "Preferred Vendor Management System"),
                              ("/netsuite.html", "Preferred Vendor Management System"),
                              ("/index.html", "Preferred Vendor Management System"),
                              ("/new-application/", "New Vendor Application")]:
            st, body, _ = get(base, alias, GOOD)
            check(f"{alias} is 200", st, 200)
            check(f"{alias} serves the right page", needle in body, True)

        print("\nnot found and traversal")
        check("/nope is 404", get(base, "/nope", GOOD)[0], 404)
        for bad in ("/../server.py", "/static/../server.py", "/server.py", "/build.py"):
            check(f"{bad} is not served", get(base, bad, GOOD)[0], 404)

        print("\nheaders")
        _, _, h = get(base, "/", GOOD)
        check("nosniff", h.get("X-Content-Type-Options"), "nosniff")
        check("no-store", h.get("Cache-Control"), "no-store")
        check("content type", h.get("Content-Type"), "text/html; charset=utf-8")

        print("\nrefusal to start unprotected")
        r = subprocess.run([sys.executable, "server.py"], cwd=ROOT,
                           env={**os.environ, "PVMS_USER": "", "PVMS_PASSWORD": ""},
                           capture_output=True, text=True, timeout=20)
        check("no credentials means exit 1", r.returncode, 1)
        check("and says why", "PVMS_USER" in r.stderr, True)
        r = subprocess.run([sys.executable, "server.py"], cwd=ROOT,
                           env={**os.environ, "PVMS_USER": "u", "PVMS_PASSWORD": "short"},
                           capture_output=True, text=True, timeout=20)
        check("short password means exit 1", r.returncode, 1)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
