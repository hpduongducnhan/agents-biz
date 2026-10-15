"""`make setup [MODE=local|shared] [SUPERADMIN=email] [VERIFY=1]` — dựng môi trường dev cho bản clone (D28).

Bước: công cụ → phụ thuộc (backend / realtime / frontend) → `.env` → `CREDENTIAL_KEYS` → khoá JWT → hạ tầng
(local: Docker `deploy/compose.infra.yml`; shared: hạ tầng chung — D19) → kiểm cấu hình → migrate → (VERIFY) stack
thử có user test + smoke. Chạy lại vô hại; chỉ thư viện chuẩn (chạy được trước khi có `.venv`); không in giá trị
secret (R21) — log đầy đủ ở `debug/setup.log`.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "debug" / "setup.log"
MIN_NODE = (22, 18)  # chạy thẳng file .ts (type stripping); khuyến nghị 24 theo realtime/package.json
INFRA_PORTS = {"Postgres": 15432, "Redis": 16379, "RabbitMQ": 5673, "Mongo": 27018}  # deploy/compose.infra.yml
INFRA = ["docker", "compose", "-f", "deploy/compose.infra.yml"]
PLACEHOLDER = re.compile(r"<[^<>\s][^<>]*>")

Runner = Callable[[Sequence[str], str], int]


# ── công cụ ─────────────────────────────────────────────────────────────────
def version(text: str) -> tuple[int, ...]:
    """`v22.21.1` / `Poetry (version 2.3.2)` → (22, 21, 1) / (2, 3, 2); không thấy số → ()."""
    found = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    return tuple(int(x) for x in found.groups() if x is not None) if found else ()


def _output(cmd: Sequence[str]) -> str:
    try:
        res = subprocess.run(list(cmd), capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (res.stdout or res.stderr) if res.returncode == 0 else ""


def tool_problems(mode: str, which: Callable[[str], str | None] = shutil.which, output=_output) -> list[str]:
    """Thiếu công cụ → một dòng mỗi thứ, kèm cách cài."""
    problems = []
    for name, hint in (
        ("git", "cài git"),
        ("python3.13", "cài Python 3.13 (pyenv / uv python install 3.13 / gói hệ điều hành)"),
        ("poetry", "cài Poetry 2: pipx install poetry"),
        ("node", f"cài Node ≥ {MIN_NODE[0]}.{MIN_NODE[1]} (khuyến nghị 24 — nvm install 24)"),
        ("npm", "đi kèm Node"),
    ):
        if not which(name):
            problems.append(f"thiếu {name} — {hint}")
    if which("node"):
        node = version(output(["node", "--version"]))
        if node[:2] < MIN_NODE:
            problems.append(f"Node {'.'.join(map(str, node)) or '?'} quá cũ — cần ≥ {MIN_NODE[0]}.{MIN_NODE[1]}")
    if mode == "local" and not (which("docker") and output(["docker", "compose", "version"])):
        problems.append("thiếu Docker + compose (MODE=local) — cài Docker, hoặc dùng MODE=shared với hạ tầng chung")
    return problems


# ── .env ────────────────────────────────────────────────────────────────────
def build_env(example: str, mode: str) -> str:
    """`.env` mới từ `.env.example`; MODE=local thay dòng `KEY=` bằng dòng `# compose: KEY=…` ngay dưới nó."""
    lines = example.splitlines()
    if mode == "local":
        for i, line in enumerate(lines):
            found = re.match(r"#\s*compose:\s*([A-Z0-9_]+)=(.*)$", line.strip())
            if not found:
                continue
            key = found.group(1)
            for j in range(i - 1, -1, -1):
                if lines[j].startswith(f"{key}="):
                    lines[j] = f"{key}={found.group(2)}"
                    break
    return "\n".join(lines) + "\n"


def env_value(text: str, key: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def set_env(text: str, key: str, value: str) -> str:
    """Đặt `KEY=value` (thay dòng có sẵn, không thì thêm cuối file)."""
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
    if pattern.search(text):
        return pattern.sub(lambda _: f"{key}={value}", text, count=1)
    return text.rstrip("\n") + f"\n{key}={value}\n"


def fernet_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def ensure_env(path: Path, example: Path, mode: str, superadmin: str | None) -> list[str]:
    """Tạo / bổ sung `.env`; trả các việc đã làm (chỉ tên biến, không giá trị)."""
    done = []
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = build_env(example.read_text(encoding="utf-8"), mode)
        done.append(f"tạo .env từ .env.example (MODE={mode})")
    if not (env_value(text, "CREDENTIAL_KEYS") or ""):
        text = set_env(text, "CREDENTIAL_KEYS", fernet_key())
        done.append("sinh CREDENTIAL_KEYS")
    if superadmin:
        emails = [e.strip() for e in (env_value(text, "SUPERADMIN_EMAILS") or "").split(",") if e.strip()]
        if superadmin.lower() not in (e.lower() for e in emails):
            text = set_env(text, "SUPERADMIN_EMAILS", ",".join([*emails, superadmin]))
            done.append("thêm SUPERADMIN_EMAILS")
    if done:
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
    return done


def placeholders(text: str) -> list[str]:
    """Biến còn chỗ phải điền (`<mật khẩu>`, `<user>`…) ở dòng đang có hiệu lực."""
    return [
        line.split("=", 1)[0]
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#") and PLACEHOLDER.search(line.split("=", 1)[1])
    ]


# ── hạ tầng local ───────────────────────────────────────────────────────────
def busy_ports(ports: dict[str, int], connect: Callable[[int], bool] | None = None) -> list[str]:
    def _open(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0

    probe = connect or _open
    return [f"{name} {port}" for name, port in ports.items() if probe(port)]


def infra_running(output=_output) -> bool:
    return bool(output([*INFRA, "ps", "--status", "running", "-q"]).strip())


# ── chạy ────────────────────────────────────────────────────────────────────
def shell(cmd: Sequence[str], label: str) -> int:
    """Chạy lệnh ở gốc repo, ghi toàn bộ output vào debug/setup.log; lỗi thì in 25 dòng cuối."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n=== {label}: {' '.join(cmd)}\n")
        log.flush()
        res = subprocess.run(list(cmd), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log.write(res.stdout)
    if res.returncode != 0:
        tail = "\n".join(res.stdout.splitlines()[-25:])
        print(f"    … 25 dòng cuối (đủ ở {LOG.relative_to(ROOT)}):\n{tail}")
    return res.returncode


class Setup:
    def __init__(self, mode: str, superadmin: str | None, verify: bool, install: bool, run: Runner = shell) -> None:
        self.mode, self.superadmin, self.verify, self.install, self.run = mode, superadmin, verify, install, run

    def step(self, label: str, cmd: Sequence[str]) -> bool:
        started = time.monotonic()
        ok = self.run(cmd, label) == 0
        print(f"{'✓' if ok else '✗'} {label} ({time.monotonic() - started:.0f}s)")
        return ok

    def main(
        self, *, tools: Callable[[str], list[str]] = tool_problems, ports=busy_ports, running=infra_running
    ) -> int:
        problems = tools(self.mode)
        for p in problems:
            print(f"✗ {p}")
        if problems:
            return 1
        print("✓ công cụ: git · Python 3.13 · Poetry · Node · npm" + (" · Docker" if self.mode == "local" else ""))
        if self.install:
            for target, label in (("be-install", "backend"), ("rt-install", "realtime"), ("fe-install", "frontend")):
                if not self.step(f"cài phụ thuộc {label}", ["make", target]):
                    return 1
        env = ROOT / ".env"
        for note in ensure_env(env, ROOT / ".env.example", self.mode, self.superadmin) or ["giữ .env có sẵn"]:
            print(f"✓ {note}")
        if not self.step("khoá JWT (.secrets/)", ["make", "keys"]):
            return 1
        missing = placeholders(env.read_text(encoding="utf-8"))
        if missing:
            print(
                f"✗ .env còn chỗ phải điền: {', '.join(missing)} — hạ tầng chung (D19): chủ dự án tạo DB / vhost"
                " rồi điền mật khẩu vào .env (agent không đọc / ghi hộ — R21), sau đó chạy lại"
                " `make setup MODE=shared`; hoặc xoá .env rồi `make setup` (MODE=local, Docker)"
            )
            return 1
        if self.mode == "local":
            if not running():
                taken = ports(INFRA_PORTS)
                if taken:
                    print(
                        f"✗ cổng đang bận: {', '.join(taken)} — hạ tầng local của app khác đang chạy? "
                        "`make infra-down` ở app đó, hoặc dùng MODE=shared trỏ vào hạ tầng có sẵn"
                    )
                    return 1
            if not self.step("hạ tầng local (Docker: Postgres · Redis · RabbitMQ · Mongo)", ["make", "infra-up"]):
                return 1
        for label, cmd in (
            ("kiểm cấu hình", ["make", "check-config"]),
            ("migrate + quyền + superadmin + seed trợ lý", ["make", "migrate"]),
        ):
            if not self.step(label, cmd):
                return 1
        if self.verify:
            for label, cmd in (
                ("stack thử chạy nền, có user test (make dev-up)", ["make", "dev-up", "MONGO=on"]),
                ("smoke đầu-cuối (make smoke-local)", ["make", "smoke-local", "MONGO=on"]),
            ):
                if not self.step(label, cmd):
                    return 1
        print(NEXT)
        return 0


NEXT = """
Xong. Chạy app khi phát triển (mỗi lệnh một terminal): make api · make consume · make work · make schedule ·
make realtime · make fe-dev → http://localhost:<FRONTEND_PORT trong .env>; đăng ký bằng email trong SUPERADMIN_EMAILS
(SUPERADMIN=… khi chạy setup) → tài khoản superadmin. Thư xác thực / mời nằm ở /sa/mail (MAIL_TRANSPORT=console).
Hoặc cả stack chạy nền có sẵn user test: make dev-up (superadmin@test.local · mật khẩu SEED_PASSWORD),
dừng: make dev-down.
Key LLM thật: /studio → "Gắn model + key cho mọi agent"."""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("local", "shared"), default="local")
    ap.add_argument("--superadmin", default=None, help="email thêm vào SUPERADMIN_EMAILS")
    ap.add_argument("--verify", action="store_true", help="dựng stack thử + smoke sau cùng")
    ap.add_argument("--no-install", action="store_true", help="bỏ bước cài phụ thuộc")
    ap.add_argument("--tools-only", action="store_true", help="chỉ kiểm công cụ")
    a = ap.parse_args(argv)
    if a.tools_only:
        problems = tool_problems(a.mode)
        for p in problems:
            print(f"✗ {p}")
        return 1 if problems else 0
    return Setup(a.mode, a.superadmin, a.verify, not a.no_install).main()


if __name__ == "__main__":
    sys.exit(main())
