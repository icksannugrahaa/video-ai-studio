#!/usr/bin/env bash
#
# Apply "soft" branch protection to `main` (Option A) via the GitHub REST API.
#
# Policy applied:
#   - Require a pull request before merging (0 required approvals)
#   - Require these status checks: "Backend (Python 3.10)", "UI (React + Vite)"
#   - Require branches to be up to date before merging
#   - Require linear history
#   - Require conversation resolution
#   - Admin bypass stays ENABLED (soft) — the owner can still push directly.
#
# Requirements:
#   - A GitHub Personal Access Token with `repo` (classic) or
#     `Administration: Read and write` (fine-grained) scope.
#   - `curl` and `jq` (or Python 3 as a fallback for JSON parsing).
#
# Usage:
#   export GITHUB_TOKEN=ghp_xxx            # do NOT commit this
#   ./scripts/setup-branch-protection.sh
#
#   # or override targets:
#   REPO=owner/name BRANCH=main ./scripts/setup-branch-protection.sh

set -euo pipefail

REPO="${REPO:-icksannugrahaa/video-ai-studio}"
BRANCH="${BRANCH:-main}"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "error: GITHUB_TOKEN is not set. Export a token with repo/admin scope first." >&2
  exit 1
fi

# Status check contexts must match the job "name:" values in .github/workflows/ci.yml
REQUIRED_CHECKS_JSON='[
  {"context": "Backend (Python 3.10)"},
  {"context": "UI (React + Vite)"}
]'

PAYLOAD_FILE="$(mktemp)"
trap 'rm -f "$PAYLOAD_FILE"' EXIT

cat >"$PAYLOAD_FILE" <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Backend (Python 3.10)", "UI (React + Vite)"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 0
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

echo "Applying branch protection to ${REPO}@${BRANCH} ..."

HTTP_CODE="$(curl -sS -o /tmp/gh_bp_response.json -w '%{http_code}' \
  -X PUT \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/${REPO}/branches/${BRANCH}/protection" \
  --data-binary "@${PAYLOAD_FILE}")"

if [[ "$HTTP_CODE" == "200" ]]; then
  echo "✅ Branch protection applied successfully."
  echo "   Required checks: Backend (Python 3.10), UI (React + Vite)"
  echo "   Admin bypass: enabled (soft mode — owner can still push to ${BRANCH})"
else
  echo "❌ Failed (HTTP ${HTTP_CODE}). Response:" >&2
  cat /tmp/gh_bp_response.json >&2
  echo >&2
  echo "Hint: ensure the token has admin scope and CI has run at least once so" >&2
  echo "      the status check contexts are known to GitHub." >&2
  exit 1
fi
