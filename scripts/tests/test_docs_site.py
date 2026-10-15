"""Trang review `.claude/`: mỗi .md → .html cạnh nó, index.html + assets/, `--check` bắt bản HTML cũ."""

from __future__ import annotations

from pathlib import Path

import pytest

import docsite as ds

ROOT = Path(__file__).resolve().parents[2]

ROOT_MD = """\
# CLAUDE.md — Demo

| Mục | Link |
|-----|------|
| **Platform** | [CLAUDE.md](.claude/platform/CLAUDE.md) |

## Project Context

**Demo** — template thử. Xem [roadmap](.claude/platform/design/roadmap.md)
và [kiến trúc](.claude/platform/architecture/).

## Self-Evolution Rules — áp dụng mọi session

### Rule 1 — Luôn cập nhật
Nội dung rule.
"""
PLATFORM_MD = """\
# CLAUDE.md — Platform (lõi)

> **Backlinks:** [CLAUDE.md](../../CLAUDE.md)

Platform = phần lõi mọi bản deploy đều có.

| File | Trạng thái | Nội dung |
|------|-----------|----------|
| [a.md](./architecture/a.md) | ĐÃ CHỐT | Mô tả **A** |
| [roadmap.md](./design/roadmap.md) | — | Lộ trình |
| [p1.md](./plans/p1.md) | **Xong** | Plan một |
"""
A_MD = """\
# Platform — Hệ thống A

> **Backlinks:** [CLAUDE.md](../../../CLAUDE.md) | [roadmap](../design/roadmap.md#1-sub-project)

**Trạng thái:** ĐỀ XUẤT (chờ duyệt).

## Môi trường local (dev)

- [ ] việc một
- [x] việc hai

| cột | giá trị |
|-----|---------|
| x | `1` |

```python
x = 1
```

```archify
../diagrams/flow.workflow.json
```

```archify
../diagrams/missing.workflow.json
```

<b>thô</b> [hỏng](./missing.md) [web](https://example.com)
[code](../../../backend/app.py) [đầu trang](#môi-trường-local-dev)

### Môi trường local (dev)

*Cập nhật: 2026-09-20*
"""
ROADMAP_MD = """\
# Platform — Lộ trình

## 1. Sub-project

| # | Sub-project | Phạm vi | Trạng thái |
|---|-------------|---------|-----------|
| **SP1** | Lõi | auth, org | **Xong** — [plan](../plans/p1.md) |
| SP2 | Ví | module ví | Tầm nhìn |
"""
DECISIONS_MD = """\
# Platform — Nhật ký quyết định

### D1 — Mỗi khách một bộ deploy · 2026-09-23
Lý do.

### D2 — Không registry trung tâm · 2026-09-24
Lý do.
"""
P1_MD = "# SP1 — Plan một\n\nNội dung plan.\n"
FLOW_SPEC = (
    '{"schema_version": 2, "diagram_type": "workflow", "meta": {"title": "Luồng A"}, "lanes": [], "nodes": [],'
    ' "edges": [], "cards": [{"dot": "cyan", "title": "Ý chính", "items": ["một <b>", "hai"]}]}'
)
SVG_HTML = '<html><body><svg viewBox="0 0 800 400" role="img"></svg></body></html>'


def fake_archify(calls: list | None = None):
    """Thay `node archify deliver`: ghi HTML có <svg viewBox> như bản thật."""

    def run(kind: str, spec: Path, out: Path) -> None:
        if calls is not None:
            calls.append((kind, spec.name))
        out.write_text(SVG_HTML, encoding="utf-8")

    return run


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    files = {
        "CLAUDE.md": ROOT_MD,
        ".claude/platform/CLAUDE.md": PLATFORM_MD,
        ".claude/platform/architecture/a.md": A_MD,
        ".claude/platform/design/roadmap.md": ROADMAP_MD,
        ".claude/platform/design/decisions.md": DECISIONS_MD,
        ".claude/platform/plans/p1.md": P1_MD,
        ".claude/platform/diagrams/flow.workflow.json": FLOW_SPEC,
        ".claude/assets/docs.css": "body{}",
        "backend/app.py": "x = 1\n",
    }
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def build(repo: Path) -> tuple[object, dict[str, str]]:
    site = ds.Site(repo)
    out = site.build()
    return site, {p.relative_to(repo / ".claude").as_posix(): text for p, text in out.items()}


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Môi trường local (dev)", "môi-trường-local-dev"),
        ("Self-Evolution Rules — áp dụng mọi session", "self-evolution-rules--áp-dụng-mọi-session"),
        ("📁 Menu tài liệu", "-menu-tài-liệu"),
        ("D1 — Mỗi khách một bộ deploy · 2026-09-23", "d1--mỗi-khách-một-bộ-deploy--2026-09-23"),
        ("`@operation` + REST", "operation--rest"),
    ],
)
def test_slugify_like_github(text: str, slug: str) -> None:
    assert ds.slugify(text) == slug


def test_every_md_gets_an_html_page_plus_index_and_generated_assets(repo: Path) -> None:
    _, out = build(repo)
    assert set(out) == {
        "index.html",
        "platform/CLAUDE.html",
        "platform/architecture/a.html",
        "platform/design/roadmap.html",
        "platform/design/decisions.html",
        "platform/plans/p1.html",
        "assets/search-index.js",
        "assets/highlight.css",
    }
    assert all(ds.MARK in text for name, text in out.items() if name.endswith(".html"))


def test_page_rewrites_links_and_renders_blocks(repo: Path) -> None:
    site, out = build(repo)
    page = out["platform/architecture/a.html"]
    assert 'href="../../index.html"' in page  # CLAUDE.md gốc → trang index
    assert 'href="../design/roadmap.html#1-sub-project"' in page  # .md → .html, giữ anchor
    assert 'href="https://example.com" target="_blank" rel="noopener"' in page
    assert 'href="../../../backend/app.py"' in page and "repo-link" in page  # file ngoài .claude
    assert 'href="#môi-trường-local-dev"' in page
    assert 'id="môi-trường-local-dev"' in page and 'id="môi-trường-local-dev-1"' in page  # heading trùng → hậu tố
    assert '<input type="checkbox" disabled> việc một' in page
    assert '<input type="checkbox" disabled checked> việc hai' in page
    assert '<div class="table-wrap"><table>' in page
    assert 'class="diagram-frame" src="../diagrams/flow.html?embed=1"' in page  # sơ đồ archify nhúng lazy
    assert 'href="../diagrams/flow.html" target="_blank"' in page and "Luồng A" in page
    assert "Ý chính" in page and "một &lt;b&gt;" in page  # thẻ kết luận của spec, đã escape
    assert 'style="aspect-ratio: 16 / 9; height: calc(100cqw * 9 / 16 + 1rem)"' in page  # chưa sinh HTML → 16:9
    assert "mermaid" not in page
    assert 'class="hl"' in page and "code-lang" in page  # python tô màu lúc sinh
    assert "&lt;b&gt;thô&lt;/b&gt;" in page  # HTML thô trong .md bị escape
    assert 'href="../../assets/docs.css"' in page and 'data-root="../../"' in page
    assert 'href="../../assets/favicon.svg"' in page  # không có favicon → trình duyệt gọi /favicon.ico → 404
    assert "ĐỀ XUẤT" in page and "2026-09-20" in page and ".claude/platform/architecture/a.md" in page
    assert 'href="../plans/p1.html"' in page  # nav bên trái có mọi trang
    assert site.broken == [
        ("platform/architecture/a.md", "../diagrams/missing.workflow.json"),
        ("platform/architecture/a.md", "./missing.md"),
    ]


def test_status_from_doc_first_then_domain_menu(repo: Path) -> None:
    site, _ = build(repo)
    docs = {d.rel.as_posix(): d for d in site.docs}
    assert docs["platform/architecture/a.md"].status == "ĐỀ XUẤT"  # doc tự ghi — ưu tiên hơn menu (ĐÃ CHỐT)
    assert docs["platform/plans/p1.md"].status == "Xong"  # doc không ghi → lấy từ menu domain
    assert docs["platform/design/roadmap.md"].status is None  # "—"
    assert docs["platform/architecture/a.md"].summary == "Mô tả <strong>A</strong>"


def test_index_is_a_review_hub(repo: Path) -> None:
    _, out = build(repo)
    index = out["index.html"]
    assert "template thử" in index  # Project Context của CLAUDE.md gốc
    assert 'href="platform/design/roadmap.html"' in index  # link gốc .claude/… → tương đối từ .claude/
    assert 'href="platform/CLAUDE.html"' in index  # link thư mục → CLAUDE của domain gần nhất
    assert "Self-Evolution Rules" in index and "<details" in index  # các mục khác của CLAUDE.md gốc: thu gọn
    assert "SP1" in index and "SP2" in index and 'href="platform/plans/p1.html"' in index  # tính năng từ roadmap
    assert 'data-status="Xong"' in index and 'data-status="TẦM NHÌN"' in index
    assert "Platform (lõi)" in index and 'href="platform/architecture/a.html"' in index  # thẻ domain + tài liệu
    decision = 'href="platform/design/decisions.html#d2--không-registry-trung-tâm--2026-09-24"'
    assert decision in index  # quyết định mới nhất, có anchor
    assert index.index("D2 —") < index.index("D1 —")


def test_search_index_lists_every_page(repo: Path) -> None:
    _, out = build(repo)
    data = out["assets/search-index.js"]
    assert data.startswith("window.DOCS_SEARCH=")
    assert '"u":"platform/architecture/a.html"' in data and "Môi trường local (dev)" in data
    assert "x = 1" not in data  # không đưa code block vào chỉ mục tìm kiếm


def test_write_then_check_detects_stale_and_orphans(repo: Path) -> None:
    docs = repo / ".claude"
    ds.render_diagrams(ds.Site(repo), runner=fake_archify())
    site = ds.Site(repo)
    ds.write(site.build(), docs)
    assert ds.check(ds.Site(repo).build(), docs) == []
    (docs / "platform/plans/p1.md").write_text("# SP1 — Plan một (sửa)\n", encoding="utf-8")
    (docs / "platform/old.html").write_text(f"<html>{ds.MARK}</html>", encoding="utf-8")  # .md đã xoá
    (docs / "platform/hand.html").write_text("<html>tự viết</html>", encoding="utf-8")
    problems = ds.check(ds.Site(repo).build(), docs)
    assert "cũ: platform/plans/p1.html" in problems and "thừa: platform/old.html" in problems
    assert not any("hand.html" in p for p in problems)  # HTML không do trình sinh tạo → không đụng
    ds.write(ds.Site(repo).build(), docs)
    assert not (docs / "platform/old.html").exists() and (docs / "platform/hand.html").exists()
    assert ds.check(ds.Site(repo).build(), docs) == []


def test_main_check_fails_on_broken_links(repo: Path) -> None:
    ds.main(["--root", str(repo)])
    assert ds.main(["--root", str(repo), "--check"]) == 1  # ./missing.md
    a = repo / ".claude/platform/architecture/a.md"
    text = a.read_text(encoding="utf-8").replace("[hỏng](./missing.md) ", "")
    a.write_text(text.replace("```archify\n../diagrams/missing.workflow.json\n```\n", ""), encoding="utf-8")
    ds.render_diagrams(ds.Site(repo), runner=fake_archify())
    ds.main(["--root", str(repo)])
    assert ds.main(["--root", str(repo), "--check"]) == 0


def test_repo_docs_html_is_current() -> None:
    """Mọi .md trong .claude/ phải có .html khớp nội dung (chạy `make docs`), không link hỏng."""
    root = ROOT
    site = ds.Site(root)
    problems = ds.check(site.build(), root / ".claude")
    assert problems == [], "chạy `make docs`:\n" + "\n".join(problems)
    assert site.broken == []
    assert (root / ".claude/assets/docs.css").is_file() and (root / ".claude/assets/docs.js").is_file()


def test_diagrams_rendered_once_locked_and_checked(repo: Path) -> None:
    """`make diagrams` chỉ sinh lại spec đổi; khoá hash spec + HTML để CI kiểm mà không cần archify."""
    docs = repo / ".claude"
    spec = "platform/diagrams/flow.workflow.json"
    assert f"sơ đồ chưa sinh: {spec}" in ds.check(ds.Site(repo).build(), docs)
    calls: list = []
    assert ds.render_diagrams(ds.Site(repo), runner=fake_archify(calls)) == [spec]
    assert calls == [("workflow", "flow.workflow.json")]
    assert ds.render_diagrams(ds.Site(repo), runner=fake_archify(calls)) == []  # không đổi → không sinh lại
    assert len(calls) == 1
    ds.write(ds.Site(repo).build(), docs)
    page = (docs / "platform/architecture/a.html").read_text(encoding="utf-8")
    # tỉ lệ theo viewBox của SVG đã sinh + 1rem đệm của chế độ embed (aspect-ratio = dự phòng khi thiếu cqw)
    assert 'style="aspect-ratio: 800 / 400; height: calc(100cqw * 400 / 800 + 1rem)"' in page
    assert not any(p.startswith("sơ đồ") for p in ds.check(ds.Site(repo).build(), docs))

    src = docs / spec
    src.write_text(src.read_text(encoding="utf-8").replace("Luồng A", "Luồng B"), encoding="utf-8")
    assert f"sơ đồ cũ: {spec}" in ds.check(ds.Site(repo).build(), docs)
    ds.render_diagrams(ds.Site(repo), runner=fake_archify())
    (docs / "platform/diagrams/flow.html").write_text("sửa tay", encoding="utf-8")
    assert f"sơ đồ cũ: {spec}" in ds.check(ds.Site(repo).build(), docs)  # HTML không khớp khoá

    (docs / "platform/diagrams/old.html").write_text("<svg></svg>", encoding="utf-8")
    assert "thừa: platform/diagrams/old.html" in ds.check(ds.Site(repo).build(), docs)
    src.unlink()
    ds.render_diagrams(ds.Site(repo), runner=fake_archify())  # spec xoá → HTML + khoá của nó xoá theo
    assert not (docs / "platform/diagrams/flow.html").exists() and not (docs / "platform/diagrams/old.html").exists()
    assert spec not in (docs / "assets/diagrams.lock.json").read_text(encoding="utf-8")


def test_relock_after_rename_accepts_rewritten_spec_and_html(repo: Path) -> None:
    """`make new-app` thay chữ cả spec lẫn HTML → khoá lại theo file đang có, không cần archify."""
    docs = repo / ".claude"
    spec = "platform/diagrams/flow.workflow.json"
    ds.render_diagrams(ds.Site(repo), runner=fake_archify())
    for path in (docs / spec, docs / "platform/diagrams/flow.html"):
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert f"sơ đồ cũ: {spec}" in ds.check(ds.Site(repo).build(), docs)
    assert ds.main(["--root", str(repo), "--relock-diagrams"]) == 0
    assert not any(p.startswith("sơ đồ") for p in ds.check(ds.Site(repo).build(), docs))
    (docs / "platform/diagrams/flow.html").unlink()
    assert ds.relock_diagrams(ds.Site(repo)) == 0
    assert f"sơ đồ chưa sinh: {spec}" in ds.check(ds.Site(repo).build(), docs)


def test_mermaid_blocks_are_rejected(repo: Path) -> None:
    """Sơ đồ viết bằng archify (spec JSON) — khối mermaid còn sót bị `--check` báo."""
    docs = repo / ".claude"
    (docs / "platform/design/old.md").write_text("# Cũ\n\n```mermaid\nflowchart TD\n  A --> B\n```\n", encoding="utf-8")
    assert "mermaid (dùng archify): platform/design/old.md" in ds.check(ds.Site(repo).build(), docs)
