#!/usr/bin/env python3
"""Real browser pass over the preview, driven through CDP.

Attaches to the Chrome already running with --remote-debugging-port=9222, opens its
own tab, walks every page, clicks the switcher links, and screenshots each screen.
It closes only the tab it opened. It never closes the browser.

Basic Auth is supplied through Network.setExtraHTTPHeaders rather than credentials in
the URL, because Chrome strips user:pass from navigations.

    python3 browser_test.py            server must already be running on :8000
    PORT=8123 python3 browser_test.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import websocket  # websocket-client

PORT = int(os.environ.get("PORT", "8000"))
BASE = f"http://127.0.0.1:{PORT}"
USER = os.environ.get("PVMS_USER", "portcanaveral")
PASSWORD = os.environ.get("PVMS_PASSWORD", "")
SHOTS = Path(__file__).resolve().parent / "shots"

PAGES = [
    ("/", "Overview", "Preferred Vendor Management System"),
    ("/new-application", "New Application", "New Vendor Application"),
    ("/vendor-portal", "Vendor Portal", "Vendor Portal"),
    ("/netsuite", "NetSuite View", "Preferred Vendor Management System"),
]

passed = failed = 0


def check(label, got, want=True):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  ok    {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}: got {got!r}, want {want!r}")


class Tab:
    def __init__(self):
        # Chrome 111+ requires PUT on /json/new. A GET or POST returns 405.
        req = urllib.request.Request("http://127.0.0.1:9222/json/new?about:blank",
                                     method="PUT")
        raw = urllib.request.urlopen(req, timeout=10).read()
        self.t = json.loads(raw)
        self.id = self.t["id"]
        self.ws = websocket.create_connection(self.t["webSocketDebuggerUrl"],
                                              timeout=60, suppress_origin=True)
        self.n = 0
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("Network.enable")
        token = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
        self.send("Network.setExtraHTTPHeaders",
                  {"headers": {"Authorization": "Basic " + token}})
        self.send("Emulation.setDeviceMetricsOverride",
                  {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})

    def send(self, method, params=None, timeout=60):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            self.ws.settimeout(max(1, end - time.time()))
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})
        raise TimeoutError(method)

    def js(self, expr):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return r.get("result", {}).get("value")

    def status(self, path: str):
        """HTTP status the browser itself sees for a same origin request with no
        credentials. awaitPromise is required, otherwise the promise comes back as an
        empty object rather than the resolved status."""
        r = self.send("Runtime.evaluate", {
            "expression": f"fetch({json.dumps(path)},"
                          f"{{credentials:'omit',cache:'no-store'}}).then(r=>r.status)",
            "awaitPromise": True,
            "returnByValue": True,
        })
        return r.get("result", {}).get("value")

    def goto(self, url, timeout=40):
        self.send("Page.navigate", {"url": url})
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(0.35)
            if self.js("document.readyState") == "complete":
                time.sleep(0.5)
                return True
        return False

    def shot(self, name):
        SHOTS.mkdir(exist_ok=True)
        r = self.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        p = SHOTS / f"{name}.png"
        p.write_bytes(base64.b64decode(r["data"]))
        return p

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            urllib.request.urlopen(f"http://127.0.0.1:9222/json/close/{self.id}",
                                   timeout=10).read()
        except Exception:
            pass


def main() -> int:
    if not PASSWORD:
        print("set PVMS_PASSWORD to the password the server is running with")
        return 1
    tab = Tab()
    try:
        print(f"\nloading each page at {BASE}")
        for path, label, needle in PAGES:
            tab.goto(BASE + path)
            title = tab.js("document.title") or ""
            body_len = tab.js("document.body.innerText.length") or 0
            has = tab.js(f"document.body.innerText.includes({json.dumps(needle)})"
                         f" || document.title.includes({json.dumps(needle)})")
            check(f"{path} renders, title {title[:46]!r}", bool(title))
            check(f"{path} has real content, {body_len} chars", body_len > 400)
            check(f"{path} shows {needle!r}", bool(has))
            errs = tab.js("(window.__err||[]).length") or 0
            check(f"{path} no page errors", errs, 0)
            shot = tab.shot(path.strip('/') or 'overview')
            print(f"        screenshot {shot.name}")

        print("\nswitcher visible and clickable on each mockup")
        for path, _, _ in PAGES[1:]:
            tab.goto(BASE + path)
            n = tab.js("document.querySelectorAll('.pvmsnav .pvmsnav__link,"
                       " .pvmsnav .pvmsnav__home').length")
            check(f"{path} switcher has 4 controls", n, 4)
            vis = tab.js("(()=>{const e=document.querySelector('.pvmsnav');"
                         "if(!e)return false;const r=e.getBoundingClientRect();"
                         "return r.width>0&&r.height>0&&r.bottom<=window.innerHeight+2})()")
            check(f"{path} switcher is on screen", bool(vis))
            on = tab.js("(document.querySelector('.pvmsnav__link--on')||{}).textContent")
            check(f"{path} marks the current page, {on!r}", bool(on))

        print("\nclicking through the switcher")
        tab.goto(BASE + "/new-application")
        tab.js("document.querySelector('.pvmsnav__link[href=\"/vendor-portal\"]').click()")
        time.sleep(1.6)
        check("New Application to Vendor Portal",
              tab.js("location.pathname"), "/vendor-portal")
        tab.js("document.querySelector('.pvmsnav__link[href=\"/netsuite\"]').click()")
        time.sleep(1.8)
        check("Vendor Portal to NetSuite View", tab.js("location.pathname"), "/netsuite")
        tab.js("document.querySelector('.pvmsnav__home').click()")
        time.sleep(1.4)
        check("NetSuite View back to Overview", tab.js("location.pathname"), "/")

        print("\nclicking through the landing cards")
        for href in ("/new-application", "/vendor-portal", "/netsuite"):
            tab.goto(BASE + "/")
            tab.js(f"document.querySelector('a.card[href=\"{href}\"]').click()")
            time.sleep(1.6)
            check(f"card opens {href}", tab.js("location.pathname"), href)

        print("\nauth actually bites in a browser")
        # Clearing the injected header is not enough: Chrome caches Basic Auth per
        # origin for the session, so a plain navigation still succeeds. credentials
        # 'omit' on a real fetch from the page is the honest test.
        # Land the page first, then drop the header. Clearing it and navigating in the
        # other order destroys the execution context mid call and Runtime.evaluate comes
        # back with an unresolved promise instead of the status.
        tab.goto(BASE + "/")
        tab.send("Network.setExtraHTTPHeaders", {"headers": {}})
        for path in ("/netsuite", "/new-application", "/vendor-portal", "/"):
            check(f"{path} is 401 to an unauthenticated request", tab.status(path), 401)
        check("/healthz stays open for the health check", tab.status("/healthz"), 200)

    finally:
        tab.close()

    print(f"\n{passed} passed, {failed} failed")
    print(f"screenshots in {SHOTS}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
