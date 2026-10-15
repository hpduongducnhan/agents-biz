#!/usr/bin/env bash
# Kích deploy BizWithAgents trên Coolify, chờ xong, rồi smoke qua domain thật.
# Cấu hình: .secrets/coolify.env (không commit) gồm COOLIFY_URL, COOLIFY_TOKEN, COOLIFY_APP_UUID, PUBLIC_URL.
# Chờ tối đa DEPLOY_POLLS × DEPLOY_POLL_SEC giây (mặc định 90 × 10); smoke kiểm api chạy đúng commit vừa push.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${COOLIFY_ENV_FILE:-$ROOT/.secrets/coolify.env}"
[ -f "$ENV_FILE" ] || { echo "Thiếu $ENV_FILE (COOLIFY_URL, COOLIFY_TOKEN, COOLIFY_APP_UUID, PUBLIC_URL)"; exit 1; }
set -a; . "$ENV_FILE"; set +a
: "${COOLIFY_URL:?}" "${COOLIFY_TOKEN:?}" "${COOLIFY_APP_UUID:?}" "${PUBLIC_URL:?}"

if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
  echo "Còn thay đổi chưa commit — commit + push trước khi deploy"; exit 1
fi
git -C "$ROOT" fetch -q origin main
LOCAL="$(git -C "$ROOT" rev-parse HEAD)"; REMOTE="$(git -C "$ROOT" rev-parse origin/main)"
[ "$LOCAL" = "$REMOTE" ] || { echo "HEAD ($LOCAL) khác origin/main ($REMOTE) — git push trước"; exit 1; }

AUTH=(-H "Authorization: Bearer $COOLIFY_TOKEN" -H "Accept: application/json")
RESP="$(curl -fsS -X POST "$COOLIFY_URL/api/v1/deploy" "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "{\"uuid\":\"$COOLIFY_APP_UUID\"}")"
echo "Coolify: $RESP"
DEPLOY_ID="$(printf '%s' "$RESP" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(((d.get("deployments") or [{}])[0]).get("deployment_uuid",""))')"

POLLS="${DEPLOY_POLLS:-90}"
PAUSE="${DEPLOY_POLL_SEC:-10}"
if [ -n "$DEPLOY_ID" ]; then
  finished=""
  for i in $(seq 1 "$POLLS"); do
    STATUS="$(curl -fsS "$COOLIFY_URL/api/v1/deployments/$DEPLOY_ID" "${AUTH[@]}" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
    echo "[$i] deployment $DEPLOY_ID: $STATUS"
    case "$STATUS" in
      finished) finished=1; break ;;
      failed|cancelled*) echo "Deploy hỏng — xem log trên Coolify"; exit 1 ;;
    esac
    sleep "$PAUSE"
  done
  if [ -z "$finished" ]; then
    echo "Deploy $DEPLOY_ID quá $((POLLS * PAUSE)) giây chưa finished — xem trên Coolify (không smoke bản cũ)"; exit 1
  fi
else
  echo "Không đọc được deployment_uuid từ phản hồi — chỉ chờ smoke"
fi

# Smoke kiểm api đang chạy đúng commit vừa deploy; `SMOKE_EXPECT_VERSION= make deploy` để bỏ kiểm (runbook coolify §7).
export SMOKE_EXPECT_VERSION="${SMOKE_EXPECT_VERSION-$LOCAL}"
EXPECT_VERSION="$LOCAL" "$ROOT/scripts/smoke_prod.sh" "$PUBLIC_URL"
