#!/usr/bin/env bash
# `make new-app-check` (trước release — không nằm trong `make ci` vì chậm): đi đúng đường người dùng (D27, D29) — repo
# template giả (cây làm việc hiện tại) ở thư mục tạm → `git clone` sang `qaapp` → `new_app.py --in-place` (app `QA App`,
# slug qaapp, tiền tố qa) → không còn tên template, remote origin → template, cây git sạch → template có bản sửa mới →
# `make template-sync` (dòng sửa + file mới mang tên app) → skill khớp → lint + typecheck + test không cần hạ tầng.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
TPL="$TMP/BizWithAgents"
APP="$TMP/qaapp"
mkdir -p "$TPL"
# file đã track + file mới chưa ignore (gồm thay đổi chưa commit), bỏ file đã xoá khỏi cây làm việc
(cd "$ROOT" && git ls-files -co --exclude-standard | while IFS= read -r f; do [ -e "$f" ] && printf '%s\n' "$f"; done \
  | tar -cf - -T -) | tar -xf - -C "$TPL"
(
  cd "$TPL"
  git init -q -b main
  git config user.email qa@test.local
  git config user.name "QA"
  git add -A
  git commit -q -m "template"
)
git clone -q "$TPL" "$APP"
git -C "$APP" config user.email qa@test.local
git -C "$APP" config user.name "QA"
"$ROOT/backend/.venv/bin/python" "$APP/scripts/scaffold/new_app.py" --in-place --src "$APP" --name "QA App" \
  --slug qaapp --prefix qa --ports 85 --redis-dbs 4,5,6
cd "$APP"
[ "$(git remote)" = "template" ] || { echo "✗ remote phải là template"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "✗ cây git chưa sạch sau init-app"; git status --short | head; exit 1; }
[ ! -e scripts/scaffold/new_app.py ] && [ ! -e scripts/scaffold/template_sync.py ] && [ ! -e .agents/skills/new-app ] \
  || { echo "✗ còn công cụ chỉ của template"; exit 1; }
# phụ thuộc mượn của template (symlink — loại khỏi git để cây vẫn sạch)
ln -s "$ROOT/backend/.venv" backend/.venv
ln -s "$ROOT/frontend/node_modules" frontend/node_modules
ln -s "$ROOT/realtime/node_modules" realtime/node_modules
printf '/backend/.venv\n/frontend/node_modules\n/realtime/node_modules\n' >> .git/info/exclude
# template có bản sửa mới: một dòng mang tên template + một file mới → make template-sync phải đổi sang tên app
(
  cd "$TPL"
  sed -i '1s/lệnh dev\./lệnh dev (bản sửa thử của template)./' Makefile
  printf 'Redis bw:probe · DB bizwithagents_test · /bizwithagents/api · BizWithAgents\n' > deploy/bizwithagents-probe.txt
  git add -A
  git commit -q -m "template: bản sửa thử"
)
make -s template-sync
[[ "$(head -1 Makefile)" == "# QA App — lệnh dev (bản sửa thử của template)."* ]] \
  || { echo "✗ template-sync: dòng sửa của template chưa mang tên app"; head -1 Makefile; exit 1; }
[ "$(cat deploy/qaapp-probe.txt)" = "Redis qa:probe · DB qaapp_test · /qaapp/api · QA App" ] \
  || { echo "✗ template-sync: file mới của template chưa mang tên app"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "✗ cây git chưa sạch sau template-sync"; git status --short | head; exit 1; }
if grep -rIl --exclude-dir=node_modules -e 'bizwithagents' -e 'BizWithAgents' . | grep -v '^./.git/'; then
  echo "✗ còn tên template ở các file trên"; exit 1
fi
if grep -rIlE --exclude-dir=node_modules --exclude-dir=.git '(^|[^A-Za-z0-9])bw[_.:`"/ -]' .; then
  echo "✗ còn tiền tố bw ở các file trên"; exit 1
fi
python3 scripts/skills_sync.py --check
cd backend
export PYTHONPATH="$APP/backend"
.venv/bin/ruff check . ../scripts
.venv/bin/ruff format --check . ../scripts
.venv/bin/python -m app.cli dump-openapi --check
.venv/bin/pytest -q -p no:cacheprovider -m "not integration"
cd ../realtime && npx tsc --noEmit
cd ../frontend && npx tsc --noEmit -p . && npx vitest run
echo "✓ new-app-check: clone + init-app tại chỗ sạch tên template, remote template, template-sync đổi tên bản sửa, lint + test không hạ tầng xanh"
