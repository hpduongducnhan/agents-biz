#!/usr/bin/env bash
# `make scaffold-check` (trong `make ci`): sinh module `scaffoldcheck` vào BẢN SAO TẠM của repo rồi lint + test backend
# của module + test luật + typecheck / lint / test frontend của module — mẫu scaffold không được lỗi thời theo lõi.
# Bản sao dùng chung `.venv` / `node_modules` qua symlink; xoá khi xong. Test backend dùng DB *_test như `make be-test`.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
rsync -a --exclude node_modules --exclude .venv --exclude .git --exclude .e2e --exclude debug --exclude .dev-stack \
  --exclude __pycache__ --exclude .claude "$ROOT/" "$TMP/"
ln -s "$ROOT/backend/.venv" "$TMP/backend/.venv"
ln -s "$ROOT/frontend/node_modules" "$TMP/frontend/node_modules"
ln -s "$ROOT/frontend/tools/openapi-ts/node_modules" "$TMP/frontend/tools/openapi-ts/node_modules"
PY="$ROOT/backend/.venv/bin/python"

"$PY" "$ROOT/scripts/scaffold/new_module.py" scaffoldcheck --title "Kiểm scaffold" --title-en "Scaffold check" --root "$TMP"

cd "$TMP/backend"
export PYTHONPATH="$TMP/backend"
.venv/bin/ruff check . ../scripts
.venv/bin/ruff format --check . ../scripts
"$PY" -m app.cli dump-openapi
.venv/bin/pytest -q -p no:cacheprovider tests/scaffoldcheck tests/rules tests/agent/test_toolset_rule.py \
  tests/agent/test_toolsets.py tests/test_domains.py tests/test_migrate.py tests/agent/test_intents_file.py

cd "$TMP/frontend"
tools/openapi-ts/node_modules/.bin/openapi-typescript src/lib/api/openapi.json -o src/lib/api/schema.d.ts >/dev/null
npx tsc --noEmit -p .
npx oxlint src test --ignore-pattern src/lib/api/schema.d.ts
npx vitest run test/modules test/lib/contract.test.ts test/lib/i18n.test.ts test/features/api.test.ts
echo "✓ scaffold-check: module sinh ra qua lint + test backend / frontend"
