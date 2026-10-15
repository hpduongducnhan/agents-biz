#!/usr/bin/env bash
# Quét trước khi push (repo public): (1) gitleaks — lịch sử git mọi nhánh / tag + thay đổi chưa commit, luật ở
# .gitleaks.toml; (2) tên riêng trong .secrets/private-terms.txt (không commit; mỗi dòng một chuỗi, # là chú thích) —
# file đang track + lịch sử; (3) trufflehog nếu có cài — chỉ báo key còn sống / chưa kiểm được.
# Dùng: make secrets-scan · không có gitleaks thì chạy bằng Docker. Thoát 1 khi có phát hiện.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
GITLEAKS_VERSION="${GITLEAKS_VERSION:-8.30.1}"
TERMS="${PRIVATE_TERMS_FILE:-$ROOT/.secrets/private-terms.txt}"
TMP="$(mktemp)"
trap 'rm -f "$TMP" "$TMP.log"' EXIT
fail=0

if command -v gitleaks >/dev/null; then
  gl() { gitleaks "$@"; }
elif command -v docker >/dev/null; then
  echo "secrets-scan: không có gitleaks trong PATH → Docker ghcr.io/gitleaks/gitleaks:v$GITLEAKS_VERSION (DEFAULTS_APPLIED=[gitleaks_docker])" >&2
  gl() { docker run --rm -v "$ROOT:/repo" -w /repo "ghcr.io/gitleaks/gitleaks:v$GITLEAKS_VERSION" "$@"; }
else
  echo "secrets-scan: cần gitleaks (https://github.com/gitleaks/gitleaks/releases) hoặc Docker" >&2
  exit 2
fi

echo "== gitleaks: lịch sử git (mọi nhánh / tag) =="
gl git --log-opts="--all" --redact --no-banner . || fail=1
if git rev-parse -q --verify HEAD >/dev/null; then
  echo "== gitleaks: thay đổi chưa commit (staged + chưa staged) =="
  gl git --pre-commit --staged --redact --no-banner . || fail=1
  gl git --pre-commit --redact --no-banner . || fail=1
fi

if [ -f "$TERMS" ]; then
  grep -vE '^[[:space:]]*(#|$)' "$TERMS" >"$TMP" || true
fi
if [ -s "$TMP" ]; then
  echo "== tên riêng ($(grep -c '' "$TMP") mục ở ${TERMS#"$ROOT"/}): file đang track + lịch sử =="
  hits="$(git grep -nIioF -f "$TMP" -- . || true)" # file:dòng:chuỗi khớp — không in cả dòng
  if [ -n "$hits" ]; then
    echo "file đang track (số lần · file:dòng:chuỗi):"; echo "$hits" | sort | uniq -ci | sort -rn | head -n 30; fail=1
  fi
  hist="$(git log --all -p --format='@@commit %h' \
    | awk '/^@@commit /{c=$2; f=""; next} /^(--- a|\+\+\+ b)\//{f=substr($0, 7); next} /^(---|\+\+\+) \/dev\/null/{next}
           {print c " " f "\t" $0}' \
    | grep -iF -f "$TMP" | cut -f1 | sort | uniq -c | sort -rn || true)" # số dòng khớp theo commit + file
  if [ -n "$hist" ]; then echo "lịch sử git (số dòng · commit · file):"; echo "$hist" | head -n 20; fail=1; fi
else
  echo "secrets-scan: không có / rỗng ${TERMS#"$ROOT"/} → bỏ kiểm tên riêng (DEFAULTS_APPLIED=[private_terms])" >&2
fi

if command -v trufflehog >/dev/null; then
  echo "== trufflehog: lịch sử git, key còn sống / chưa kiểm được =="
  rc=0
  trufflehog git "file://$ROOT" --no-update --results=verified,unknown --fail 2>"$TMP.log" || rc=$?
  if [ "$rc" -eq 183 ]; then fail=1; elif [ "$rc" -ne 0 ]; then cat "$TMP.log" >&2; fail=1; else echo "trufflehog: 0 phát hiện"; fi
else
  echo "secrets-scan: không có trufflehog → bỏ bước kiểm key còn sống (tuỳ chọn)" >&2
fi

if [ "$fail" -ne 0 ]; then
  echo "secrets-scan: CÓ PHÁT HIỆN — xem ở trên; sai báo thì thêm ngoại lệ hẹp vào .gitleaks.toml" >&2
  exit 1
fi
echo "secrets-scan: sạch ✓"
