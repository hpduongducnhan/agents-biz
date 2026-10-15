#!/usr/bin/env bash
# Stack local chạy nền cho smoke-local và E2E: api · consume · work · schedule · realtime · web (vite preview 127.0.0.1:8201).
#   scripts/dev_stack.sh up [on|off]   Mongo bật (mặc định) / tắt — tắt thì MONGO_RW_URL trỏ host không tồn tại
#   scripts/dev_stack.sh down | status
# Pid + log + khoá JWT riêng ở .dev-stack/ (bị ignore). Cần trước: make be-install rt-install fe-install, .env có sẵn.
# Tách khỏi dữ liệu thật: DB / vhost / Mongo `bizwithagents_e2e`, Redis db 12, khoá JWT riêng — scripts/stack_env.py.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/.dev-stack"
SP="${SERVICE_PATH:-bizwithagents}"
PORT_WEB="${FRONTEND_PORT:-8201}"
WEB="http://127.0.0.1:$PORT_WEB"
MP="$ROOT/backend/.venv/bin/bw"
SERVICES=(fakellm api consume work schedule realtime web)
PORT_LLM="${FAKE_LLM_PORT:-8799}"

start() { # tên · thư mục · lệnh...
  local name="$1" dir="$2"
  shift 2
  ( cd "$ROOT/$dir" && exec "$@" ) >"$RUN/$name.log" 2>&1 &
  echo $! >"$RUN/$name.pid"
}

wait_ok() { # tên · url · số giây
  local name="$1" url="$2" secs="$3"
  for _ in $(seq 1 "$secs"); do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then echo "✓ $name"; return 0; fi
    sleep 1
  done
  echo "✗ $name không lên sau ${secs}s — xem $RUN/*.log"
  return 1
}

down() {
  for name in "${SERVICES[@]}"; do
    local f="$RUN/$name.pid"
    [ -f "$f" ] || continue
    local pid
    pid="$(cat "$f")"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$f"
  done
  rm -f "$RUN/mongo"
  echo "stack local đã dừng"
}

status() {
  for name in "${SERVICES[@]}"; do
    local f="$RUN/$name.pid"
    if [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null; then echo "$name chạy (pid $(cat "$f"))"; else echo "$name dừng"; fi
  done
  echo "Mongo: $(cat "$RUN/mongo" 2>/dev/null || echo -)"
}

up() {
  local mode="${1:-on}"
  case "$mode" in on | off) ;; *) echo "chế độ Mongo phải là on | off"; exit 2 ;; esac
  [ -x "$MP" ] || { echo "thiếu backend/.venv — chạy make be-install"; exit 1; }
  [ -d "$ROOT/realtime/node_modules" ] || { echo "thiếu realtime/node_modules — chạy make rt-install"; exit 1; }
  [ -d "$ROOT/frontend/node_modules" ] || { echo "thiếu frontend/node_modules — chạy make fe-install"; exit 1; }
  mkdir -p "$RUN/keys"
  down >/dev/null
  local envs
  envs="$(PYTHONPATH="$ROOT/backend" "$ROOT/backend/.venv/bin/python" "$ROOT/scripts/stack_env.py" "$RUN/keys")" \
    || { echo "✗ không dựng được môi trường stack thử (scripts/stack_env.py)"; exit 1; }
  eval "$envs"
  if [ "$mode" = off ]; then
    export MONGO_ENABLED=false MONGO_RW_URL="mongodb://mongo-disabled.invalid:27017"
  else
    export MONGO_ENABLED=true
  fi
  export FORWARDED_ALLOW_IPS=127.0.0.1 # uvicorn tin X-Forwarded-For do proxy Vite chuyển (IP thật cho rate limit)
  (cd "$ROOT/backend" && "$MP" keys && "$MP" migrate && "$MP" seed-test-users \
    && .venv/bin/python ../scripts/seed_agent.py --provider openai_compatible --name "LLM giả" \
      --base-url "http://127.0.0.1:$PORT_LLM/v1" --model fake-model --key fake-key) >"$RUN/migrate.log" 2>&1 \
    || { echo "✗ keys / migrate / seed lỗi — xem $RUN/migrate.log"; exit 1; }
  (cd "$ROOT/frontend" && npm run build) >"$RUN/build.log" 2>&1 \
    || { echo "✗ build frontend lỗi — xem $RUN/build.log"; exit 1; }
  echo "$mode" >"$RUN/mongo"
  start fakellm backend .venv/bin/python -m app.agent.testing.fake_llm --port "$PORT_LLM"
  start api backend "$MP" api
  start consume backend "$MP" consume
  start work backend "$MP" work
  start schedule backend "$MP" schedule
  start realtime realtime node --env-file-if-exists=../.env src/main.ts
  start web frontend ./node_modules/.bin/vite preview --host 127.0.0.1 --port "$PORT_WEB" --strictPort
  wait_ok "api ready" "$WEB/$SP/api/health/ready" 60
  wait_ok "realtime" "$WEB/$SP/ws/health" 30
  wait_ok "pipeline (nhịp tim)" "$WEB/$SP/api/health/pipeline" 90
  echo "stack local chạy — Mongo $mode — $WEB"
}

case "${1:-}" in
  up) up "${2:-on}" ;;
  down) down ;;
  status) status ;;
  *) echo "dùng: scripts/dev_stack.sh up [on|off] | down | status"; exit 2 ;;
esac
