#!/usr/bin/env python3
"""Render the customer overview to PDF through the already running Chrome.

Uses Page.printToPDF over CDP, so what lands in the PDF is exactly what the browser
renders, backgrounds and all. It opens its own tab and closes only that tab.

    python3 build_pdf.py
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

import websocket

HERE = Path(__file__).resolve().parent
SRC = HERE / "pvms_overview.html"
OUT = HERE / "Port Canaveral - Preferred Vendor Management System.pdf"


def main() -> int:
    if not SRC.is_file():
        print(f"missing {SRC}")
        return 1

    req = urllib.request.Request("http://127.0.0.1:9222/json/new?about:blank", method="PUT")
    tgt = json.loads(urllib.request.urlopen(req, timeout=10).read())
    ws = websocket.create_connection(tgt["webSocketDebuggerUrl"], timeout=90,
                                     suppress_origin=True)
    n = 0

    def send(method, params=None):
        nonlocal n
        n += 1
        mid = n
        ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    try:
        send("Page.enable")
        send("Runtime.enable")
        send("Page.navigate", {"url": SRC.as_uri()})
        for _ in range(60):
            time.sleep(0.3)
            r = send("Runtime.evaluate",
                     {"expression": "document.readyState", "returnByValue": True})
            if r.get("result", {}).get("value") == "complete":
                break
        time.sleep(0.6)   # let fonts settle before printing

        res = send("Page.printToPDF", {
            "printBackground": True,
            "preferCSSPageSize": True,
            "displayHeaderFooter": False,
            "scale": 1,
        })
        OUT.write_bytes(base64.b64decode(res["data"]))
        pages = send("Runtime.evaluate", {
            "expression": "Math.ceil(document.body.scrollHeight/1056)",
            "returnByValue": True}).get("result", {}).get("value")
        print(f"written {OUT}")
        print(f"        {OUT.stat().st_size:,} bytes, about {pages} page(s)")
    finally:
        try:
            ws.close()
        except Exception:
            pass
        try:
            urllib.request.urlopen(f"http://127.0.0.1:9222/json/close/{tgt['id']}",
                                   timeout=10).read()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
