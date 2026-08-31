#!/usr/bin/env python3
"""Click every control in the three apps and report what breaks.

The mockups drive almost everything from inline onclick handlers rather than hrefs,
so a static href scan proves nothing. This clicks each control in a real browser and
records three failure modes:

    error        the handler threw a JS exception
    jump         an href="#" scrolled the page to the top instead of doing something
    inert        nothing happened at all, no DOM change, no navigation, no error

inert is not automatically a bug: a disabled control or one whose panel is already
open looks the same. It is a list to eyeball, not a list of defects.

    BASE_URL=... PVMS_PASSWORD=... python3 link_audit.py
"""
from __future__ import annotations

import json
import os
import sys
import time

import browser_test as B

PAGES = ["/new-application", "/vendor-portal", "/netsuite"]
MAX_PER_PAGE = int(os.environ.get("MAX_CONTROLS", "400"))

COLLECT = """
(() => {
  window.__err = [];
  window.onerror = (m,s,l,c,e) => { window.__err.push(String(m)); return false; };
  window.addEventListener('unhandledrejection', e => window.__err.push('promise: '+e.reason));
  const sel = 'a, button, [onclick], [role="tab"], [role="button"]';
  const all = [...document.querySelectorAll(sel)]
    .filter(e => !e.closest('.pvmsnav'));
  window.__ctl = all;
  return all.map((e,i) => ({
    i,
    tag: e.tagName.toLowerCase(),
    href: e.getAttribute('href'),
    label: (e.innerText || e.getAttribute('aria-label') || e.title || '').trim().slice(0,44),
    disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true',
    hasOnclick: !!e.getAttribute('onclick')
  }));
})()
"""

# Length alone misses a tab switch that only swaps a class, which is how most of
# these mockups navigate. Hash the markup and also fingerprint what is visible.
CLICK = """
(() => {
  const e = window.__ctl[%d];
  if (!e) return {gone:true};
  const h = s => { let x = 5381; for (let i=0;i<s.length;i++) x = ((x*33) ^ s.charCodeAt(i)) >>> 0; return x; };
  const fp = () => h(document.body.innerHTML) + ':' +
    h([...document.querySelectorAll('[class*=active],[class*=selected],[aria-selected],[aria-current]')]
        .map(n => n.className + n.getAttribute('aria-selected') + n.getAttribute('aria-current')).join('|')) + ':' +
    h([...document.querySelectorAll('div,section,dialog')]
        .filter(n => n.offsetParent !== null).length + '');
  const before = fp();
  const beforeY = window.scrollY;
  const beforeUrl = location.href;
  const errsBefore = window.__err.length;
  try { e.click(); } catch (ex) { window.__err.push(String(ex)); }
  return {
    errs: window.__err.slice(errsBefore),
    changed: fp() !== before,
    scrolled: window.scrollY !== beforeY,
    navigated: location.href !== beforeUrl,
    url: location.href
  };
})()
"""


def main() -> int:
    if not B.PASSWORD:
        print("set PVMS_PASSWORD")
        return 1
    tab = B.Tab()
    totals = {"clicked": 0, "error": 0, "jump": 0, "inert": 0}
    findings: list[str] = []
    try:
        for page in PAGES:
            tab.goto(B.BASE + page)
            time.sleep(0.8)
            controls = tab.js(COLLECT) or []
            print(f"\n=== {page}: {len(controls)} controls")
            live = [c for c in controls if not c["disabled"]][:MAX_PER_PAGE]
            for c in live:
                r = tab.js(CLICK % c["i"]) or {}
                totals["clicked"] += 1
                label = c["label"].replace("\n", " ") or f'<{c["tag"]}>'
                if r.get("navigated") and not r.get("url", "").endswith(page):
                    # a real navigation, go back and carry on
                    tab.goto(B.BASE + page)
                    time.sleep(0.6)
                    tab.js(COLLECT)
                    continue
                if r.get("errs"):
                    totals["error"] += 1
                    findings.append(f"ERROR  {page}  {label!r}  {r['errs'][0][:90]}")
                elif c["href"] == "#" and r.get("scrolled") and not r.get("changed"):
                    totals["jump"] += 1
                    findings.append(f"JUMP   {page}  {label!r}  href=# scrolled to top")
                elif not r.get("changed") and not r.get("scrolled"):
                    totals["inert"] += 1
                    findings.append(f"inert  {page}  {label!r}")
            print(f"    clicked {len(live)}")
    finally:
        tab.close()

    print("\n--- findings")
    for f in findings[:60]:
        print("  " + f)
    if len(findings) > 60:
        print(f"  ... {len(findings)-60} more")
    print(f"\nclicked {totals['clicked']}   errors {totals['error']}   "
          f"href=# jumps {totals['jump']}   inert {totals['inert']}")
    return 1 if (totals["error"] or totals["jump"]) else 0


if __name__ == "__main__":
    sys.exit(main())
