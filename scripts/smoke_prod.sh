#!/usr/bin/env bash
# Smoke qua domain thật — KHÔNG ghi dữ liệu. (1) 4 kiểm nền (web, api ready, pipeline, realtime), thử lại ~2,5 phút
# để chờ bản deploy lên; (2) smoke đầu-cuối profile prod (realtime/scripts/smoke_e2e.ts): cache bundle, phiên bản,
# websocket qua Cloudflare, không có /devtools/*, đăng nhập nếu có .secrets/smoke.env (SMOKE_EMAIL / SMOKE_PASSWORD).
# SMOKE_EXPECT_VERSION=<sha> (deploy.sh đặt) → api phải chạy đúng commit đó.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COOLIFY_ENV="${COOLIFY_ENV_FILE:-$ROOT/.secrets/coolify.env}"
if [ -z "${1:-}" ] && [ -z "${PUBLIC_URL:-}" ] && [ -f "$COOLIFY_ENV" ]; then
  PUBLIC_URL="$(sed -n 's/^PUBLIC_URL=//p' "$COOLIFY_ENV" | tail -n1 | tr -d '"\047')"
fi
BASE="${1:-${PUBLIC_URL:-}}"
: "${BASE:?URL công khai: make smoke-prod URL=https://<slug>.<domain> hoặc PUBLIC_URL trong .secrets/coolify.env}"
BASE="${BASE%/}"
SP="${SERVICE_PATH:-bizwithagents}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
fail=0

check() { # tên · url · chuỗi bắt buộc có trong body
  local name="$1" url="$2" want="$3" code=""
  for _ in $(seq 1 "${SMOKE_TRIES:-30}"); do
    code=$(curl -s -o "$TMP" -w '%{http_code}' "$url" || true)
    if [ "$code" = "200" ] && grep -q -- "$want" "$TMP"; then echo "✓ $name"; return 0; fi
    sleep "${SMOKE_SLEEP:-5}"
  done
  echo "✗ $name → HTTP $code: $(head -c 300 "$TMP")"
  fail=1
}

check "web" "$BASE/" 'id="root"'
check "api ready" "$BASE/$SP/api/health/ready" '"success":true'
check "pipeline" "$BASE/$SP/api/health/pipeline" '"success":true'
check "realtime" "$BASE/$SP/ws/health" '"status":"ok"'
[ "$fail" -eq 0 ] || exit 1

if [ -f "$ROOT/.secrets/smoke.env" ]; then
  set -a
  . "$ROOT/.secrets/smoke.env"
  set +a
fi
if [ ! -d "$ROOT/realtime/node_modules/socket.io-client" ]; then
  (cd "$ROOT/realtime" && npm ci --no-audit --no-fund >/dev/null)
fi
cd "$ROOT/realtime"
exec node scripts/smoke_e2e.ts "$BASE" --profile prod
