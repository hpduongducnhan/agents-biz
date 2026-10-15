"""Mỗi mã lỗi đã đăng ký nằm đúng dải của owner."""

from app.core.errors import ERROR_RANGES, registered_errors
from app.domains import load_domains


def test_every_registered_code_sits_in_its_owner_range():
    load_domains()
    bad = []
    for code, (_, owner) in sorted(registered_errors().items()):
        low, high = ERROR_RANGES.get(owner, (0, -1))
        if not low <= code <= high:
            bad.append(f"{code} ({owner})")
    assert bad == [], "mã lỗi ngoài dải: " + ", ".join(bad)


CORE = {
    "core": (1000, 1999),
    "auth": (2000, 2999),
    "agent": (6000, 6999),
    "observability": (7000, 7999),
    "notifications": (7000, 7999),
    "mail": (8000, 8999),
}


def test_ranges_match_the_contract():
    """Lõi 4 chữ số cố định; mỗi module một dải 5 chữ số `1NN00–1NN99` riêng (template-v1 §3.4)."""
    assert {k: v for k, v in ERROR_RANGES.items() if k in CORE} == CORE
    modules = sorted((v, k) for k, v in ERROR_RANGES.items() if k not in CORE)
    assert ("tasks" in {k for _, k in modules}) and ERROR_RANGES["tasks"] == (10000, 10099)
    for (low, high), owner in modules:
        assert 10000 <= low and low % 100 == 0 and high == low + 99, owner
    assert len({low for (low, _), _ in modules}) == len(modules)  # không trùng dải
