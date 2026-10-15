"""Chuyên gia seed + route mặc định của orchestrator "Assistant" — registry: module gọi `register_specialist` lúc nạp
(`app/<module>/agent.py`), bước sau migrate `agent.seed` tạo agent còn thiếu. Superadmin sửa ở Studio; seed chỉ nâng
nội dung còn đúng một bản seed cũ (`previous_*`), đã sửa tay thì giữ."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


@dataclass(frozen=True)
class SpecialistSeed:
    slug: str
    name: str
    description: str
    toolsets: tuple[str, ...]
    intent: str  # ý định cho bảng route của router
    examples: tuple[str, ...]  # câu mẫu (vi + en) cho router
    prompt_dir: Path = PROMPTS  # thư mục chứa `<slug>.md`
    # bản seed cũ — DB còn đúng bản cũ (superadmin chưa sửa) thì seed nâng lên bản mới
    previous_toolsets: tuple[frozenset[str], ...] = ()
    previous_instructions: frozenset[str] = frozenset()  # sha256 của hướng dẫn đã ghép `_common`
    previous_routes: tuple[tuple[str, tuple[str, ...]], ...] = field(default=())


# Persona chung của các bản seed cũ (sha256 nội dung đã strip) — DB còn đúng bản cũ thì seed nâng.
PREVIOUS_PERSONA: frozenset[str] = frozenset()

_SEEDS: dict[str, SpecialistSeed] = {}


def register_specialist(seed: SpecialistSeed) -> None:
    """Thêm chuyên gia vào bộ seed. Trùng slug với nội dung khác = lỗi cấu hình."""
    if seed.slug in _SEEDS and _SEEDS[seed.slug] != seed:
        raise ValueError(f"chuyên gia '{seed.slug}' đã đăng ký")
    if not (seed.prompt_dir / f"{seed.slug}.md").is_file():
        raise ValueError(f"chuyên gia '{seed.slug}' thiếu prompt {seed.prompt_dir / (seed.slug + '.md')}")
    _SEEDS[seed.slug] = seed


def specialists() -> tuple[SpecialistSeed, ...]:
    """Theo thứ tự đăng ký — cũng là thứ tự route mặc định; `general` luôn cuối (dự phòng của router)."""
    seeds = [s for s in _SEEDS.values() if s.slug != "general"]
    return (*seeds, *([_SEEDS["general"]] if "general" in _SEEDS else []))


register_specialist(
    SpecialistSeed(
        "general",
        "Hỏi đáp",
        "Chào hỏi, hướng dẫn dùng app, tra cứu nhanh",
        ("lookup",),
        "Greetings, how to use the app, out-of-scope questions, quick lookups no other specialist owns",
        ("chào bạn", "app này dùng thế nào", "tôi có thông báo nào mới không", "hello", "how do I use this app"),
    )
)
