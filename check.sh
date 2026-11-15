#!/usr/bin/env bash
# The checks that prove Kahani Tak works. The Stop hook runs this file.
#  1. scoring rules, real speech model on synthetic clips with planted mistakes, and the web API
#  2. the parent demo path and the teacher check in a real browser with a fake microphone
#     playing a real clip; Playwright records a video of each run (e2e/results/*/video.webm)
#  3. AgentFoundry eval suite for the class-planner agent (scripts/af_eval.py)
#  4. the live app answers (when LIVE_URL is set in .env.local or the environment)
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env.local ] && { set -a; . ./.env.local; set +a; }

.venv/bin/python -m pytest -q tests/
# AgentFoundry Agent Studio eval suite for the class planner (same scoring as AF's Eval tab)
.venv/bin/python scripts/af_eval.py
(cd e2e && npx playwright test)
if [ -n "${LIVE_URL:-}" ]; then
  curl -fsS --max-time 120 "$LIVE_URL/healthz" | grep -q '"model_loaded":true' || { echo "live app not healthy: $LIVE_URL"; exit 1; }
  # live: the demo path only (parent loop + teacher confirm); the ?state= previews ran locally above
  (cd e2e && BASE_URL="$LIVE_URL" npx playwright test demo-path.spec.ts)
  # the agent answers the way AgentFoundry invokes it (manifest invocationUrl + header auth)
  .venv/bin/python scripts/af_invoke.py
  echo "live app OK: $LIVE_URL"
fi
echo "check.sh: all checks passed"
