# Port Canaveral PVMS preview

Three prototype screens behind one username and password, for Canaveral Port Authority
to click through before signing.

| Entry point | Screen | Source mockup |
|---|---|---|
| `/new-application` | New Vendor Application | `pvms-new-application.html` |
| `/vendor-portal` | Vendor Portal | `pvms-vendor-portal.html` |
| `/netsuite` | PVMS inside NetSuite | `pvms-netsuite_1.html` |
| `/` | Landing page linking all three | hand written |
| `/healthz` | Health check, no auth | |

Short aliases also resolve, so a pasted or half remembered URL still lands:
`/apply`, `/application`, `/new`, `/portal`, `/vendor`, `/pvms`, and any of the
`.html` forms.

## Why a web service and not a Render Static Site

Render Static Sites cannot do HTTP Basic Auth, and this preview has to be private.
`server.py` is a standard library HTTP server that serves the same static files with
one credential in front. No dependencies, no database, no state.

## Run locally

```bash
PVMS_USER=portcanaveral PVMS_PASSWORD=<password> python3 server.py
open http://localhost:8000
```

The service refuses to start without both variables, and refuses a password under
eight characters, so an unprotected deploy is not possible by accident.

## Rebuild the pages

`static/` is generated. The three mockups have no links between them, so `build.py`
copies each one and injects a small fixed switcher before `</body>` giving the
reviewer Overview plus the other two screens on every page. It uses a `pvmsnav__`
class prefix and sets no styles on any existing element, so it cannot disturb the
mockup's own layout.

```bash
python3 build.py            # rebuild from ~/Downloads
python3 build.py --check    # assert the switcher is present in all three
```

Re-running is safe. An existing switcher is stripped before the new one goes in, so
the output is stable no matter how many times it runs. When a mockup is updated,
drop the new file in `~/Downloads` under the same name and rebuild.

`static/index.html` is the landing page. It is hand written and is not regenerated.

## Deploy

The blueprint is `render.yaml`. Push this directory to a Git repository, point a new
Render Blueprint at it, and set `PVMS_USER` and `PVMS_PASSWORD` when prompted. They
are `sync: false`, so they are never committed.

## Tests

```bash
python3 test_site.py
```

Starts the server on a spare port and checks every route: 401 without credentials,
401 with the wrong password, 200 with the right ones, all three pages served with
their switcher, aliases redirected, health check open, and no path traversal.

---

Prepared for Canaveral Port Authority by Cumula 3 Group, LLC. The screens are fully
clickable and the data is illustrative sample data, not live Port records.
