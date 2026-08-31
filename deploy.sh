#!/usr/bin/env bash
# Create the Render web service for the PVMS preview.
#
# Prerequisite, one click and only needed once: the Render GitHub App has access to
# "selected repositories" on the ncanoCumula3 account, and this repo is new, so it is
# not on that list yet. Add it at
#     https://github.com/settings/installations  ->  Render  ->  Configure
#     ->  Repository access  ->  add ncanoCumula3/portcanaveral-vendorportal-demo  ->  Save
#
# Then:
#     PVMS_PASSWORD=... ./deploy.sh
#
# Re-running is safe. If the service already exists Render returns a 409 and this
# stops rather than creating a duplicate.
set -euo pipefail
cd "$(dirname "$0")"

: "${RENDER_API_KEY:?RENDER_API_KEY is not set}"
: "${PVMS_PASSWORD:?set PVMS_PASSWORD to the password reviewers will be given}"
PVMS_USER="${PVMS_USER:-portcanaveral}"
OWNER="${RENDER_OWNER:-tea-commfvsf7o1s73f757og}"   # Oakmorelabs
REPO="https://github.com/ncanoCumula3/portcanaveral-vendorportal-demo"

payload=$(python3 - "$OWNER" "$REPO" "$PVMS_USER" "$PVMS_PASSWORD" <<'PY'
import json, sys
owner, repo, user, password = sys.argv[1:5]
print(json.dumps({
    "type": "web_service", "name": "portcanaveral-vendorportal-demo", "ownerId": owner,
    "repo": repo, "branch": "main", "autoDeploy": "yes",
    "serviceDetails": {
        "env": "python", "region": "ohio", "plan": "starter",
        "envSpecificDetails": {
            "buildCommand": "python -m compileall -q server.py build.py",
            "startCommand": "python server.py",
        },
    },
    "envVars": [
        {"key": "PYTHON_VERSION", "value": "3.12.6"},
        {"key": "PVMS_USER", "value": user},
        {"key": "PVMS_PASSWORD", "value": password},
    ],
}))
PY
)

echo "creating service..."
resp=$(curl -sS -X POST "https://api.render.com/v1/services" \
    -H "Authorization: Bearer $RENDER_API_KEY" \
    -H "Content-Type: application/json" -H "Accept: application/json" \
    -d "$payload")

url=$(python3 - "$resp" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
if "service" in d:
    s = d["service"]
    print(s["id"], s.get("serviceDetails", {}).get("url", ""))
else:
    print("ERROR", json.dumps(d)[:400], file=sys.stderr)
    raise SystemExit(1)
PY
)
sid=${url%% *}; live=${url##* }
echo "service $sid"
echo "url     $live"

echo "waiting for the first deploy..."
for _ in $(seq 1 90); do
    st=$(curl -sS "https://api.render.com/v1/services/$sid/deploys?limit=1" \
         -H "Authorization: Bearer $RENDER_API_KEY" -H "Accept: application/json" \
         | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['deploy']['status'])")
    echo "  $st"
    case "$st" in
        live) break ;;
        build_failed|update_failed|canceled|deactivated)
            echo "deploy $st, check the Render dashboard"; exit 1 ;;
    esac
    sleep 10
done

echo
echo "verifying the live site"
for p in / /new-application /vendor-portal /netsuite /healthz; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -u "$PVMS_USER:$PVMS_PASSWORD" "$live$p")
    noauth=$(curl -s -o /dev/null -w '%{http_code}' "$live$p")
    printf '  %-18s authed %s   unauthed %s\n' "$p" "$code" "$noauth"
done
echo
echo "done. $live"
