"""Bộ ý định tiếng Việt cho `bw agent-eval`: YAML hợp lệ, slug có thật, 1–3 bước, đủ loại câu."""

from collections import Counter

import pytest

from app.agent.config.seed_data import specialists
from app.agent.eval import CASES, load_cases
from app.domains import load_domains

load_domains()  # chuyên gia của module (vd `tasks`) đăng ký khi nạp miền
SLUGS = {s.slug for s in specialists()}


@pytest.fixture(scope="module")
def cases():
    return load_cases(CASES)


def test_file_is_valid_and_big_enough(cases):
    assert CASES.is_dir() and 10 <= len(cases) <= 400
    for c in cases:
        assert set(c) <= {"text", "expect", "history"} and isinstance(c["text"], str) and c["text"].strip()
        assert set(c["expect"]) in ({"steps"}, {"clarify"})
    texts = [c["text"] for c in cases if not c.get("history")]
    assert len(texts) == len(set(texts))  # không trùng câu


def test_expected_slugs_exist_and_steps_between_one_and_three(cases):
    for c in cases:
        exp = c["expect"]
        if "clarify" in exp:
            assert exp["clarify"] is True
            continue
        assert 1 <= len(exp["steps"]) <= 3 and set(exp["steps"]) <= SLUGS, c["text"]


def test_every_kind_of_sentence_is_covered(cases):
    singles = [c for c in cases if "steps" in c["expect"] and len(c["expect"]["steps"]) == 1]
    clarify = [c for c in cases if c["expect"].get("clarify")]
    follow = [c for c in cases if c.get("history")]
    assert len(singles) >= 8 and len(clarify) >= 3 and len(follow) >= 2
    per_slug = Counter(c["expect"]["steps"][0] for c in singles)
    assert set(per_slug) == SLUGS and min(per_slug.values()) >= 5  # mỗi chuyên gia ≥ 5 câu một ý định


def test_history_entries_are_well_formed(cases):
    for c in cases:
        for h in c.get("history") or []:
            assert h["role"] in ("user", "assistant") and h["text"].strip()
            if h["role"] == "assistant":
                assert h["agent"] in SLUGS
        if c.get("history"):
            assert c["history"][-1]["role"] == "assistant"
