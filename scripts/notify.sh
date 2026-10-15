#!/usr/bin/env bash
# Báo chủ dự án qua Discord khi Claude thật sự cần người (R28).
# Cấu hình: .secrets/discord.env (không commit) gồm DISCORD_WEBHOOK_URL; hoặc đặt sẵn biến môi trường đó.
# Dùng: scripts/notify.sh "nội dung"   ·   echo "nội dung" | scripts/notify.sh
#       make notify MSG="nội dung"
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${DISCORD_ENV_FILE:-$ROOT/.secrets/discord.env}"
if [ -z "${DISCORD_WEBHOOK_URL:-}" ] && [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi
: "${DISCORD_WEBHOOK_URL:?thiếu DISCORD_WEBHOOK_URL (.secrets/discord.env)}"

MSG="${*:-$(cat)}"
[ -n "$MSG" ] || { echo "notify: nội dung rỗng" >&2; exit 1; }
BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo '?')"

# Discord giới hạn 2000 ký tự / tin — cắt bớt, giữ phần đầu.
BODY="$(MSG="$MSG" BRANCH="$BRANCH" COMMIT="$COMMIT" python3 -c '
import json, os
text = f"**BizWithAgents** · `{os.environ["BRANCH"]}@{os.environ["COMMIT"]}`\n{os.environ["MSG"]}"
print(json.dumps({"username": "BizWithAgents · Claude", "content": text[:1990]}))
')"
curl -fsS -X POST -H "Content-Type: application/json" -d "$BODY" "$DISCORD_WEBHOOK_URL" >/dev/null
echo "notify: đã gửi"
