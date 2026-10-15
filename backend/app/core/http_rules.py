"""Rule log HTTP vào / ra theo pattern đường dẫn / URL (file YAML `LOG_HTTP_RULES_FILE`)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_FLAGS = ("req_body", "req_headers", "resp_headers", "resp_body", "propagate_cid")


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """`**` khớp mọi thứ (kể cả `/`), `*` khớp trong một đoạn."""
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


@dataclass(frozen=True)
class HttpLogRule:
    match: str
    req_body: bool = False
    req_headers: bool = False
    resp_headers: bool = False
    resp_body: bool = False
    propagate_cid: bool = False
    _regex: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_regex", glob_to_regex(self.match))

    def matches(self, target: str) -> bool:
        return bool(self._regex.match(target))


DEFAULT_RULE = HttpLogRule(match="**")


def _parse_rules(items: list, *, inbound: bool) -> list[HttpLogRule]:
    rules = []
    for item in items or []:
        if not isinstance(item, dict) or "match" not in item:
            raise ValueError(f"LOG_HTTP_RULES_FILE: mỗi rule cần 'match' — {item!r}")
        unknown = set(item) - {"match", *_FLAGS}
        if unknown:
            raise ValueError(f"LOG_HTTP_RULES_FILE: khoá lạ {sorted(unknown)} trong {item!r}")
        if inbound and item.get("propagate_cid"):
            raise ValueError("LOG_HTTP_RULES_FILE: propagate_cid chỉ dùng cho outbound")
        rules.append(HttpLogRule(match=str(item["match"]), **{k: bool(item[k]) for k in _FLAGS if k in item}))
    return rules


class HttpLogRules:
    def __init__(self, inbound: list[HttpLogRule], outbound: list[HttpLogRule], max_body: int = 4096) -> None:
        self.inbound = inbound
        self.outbound = outbound
        self.max_body = max_body

    @classmethod
    def empty(cls) -> HttpLogRules:
        return cls([], [])

    @classmethod
    def from_file(cls, path: Path | None) -> HttpLogRules:
        if path is None:
            return cls.empty()
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if "http_log" not in data:
            raise ValueError(f"{path}: thiếu khoá gốc 'http_log'")
        section = data["http_log"] or {}
        return cls(
            inbound=_parse_rules(section.get("inbound"), inbound=True),
            outbound=_parse_rules(section.get("outbound"), inbound=False),
            max_body=int(section.get("max_body", 4096)),
        )

    def inbound_for(self, path: str) -> HttpLogRule:
        return next((r for r in self.inbound if r.matches(path)), DEFAULT_RULE)

    def outbound_for(self, url: str) -> HttpLogRule:
        return next((r for r in self.outbound if r.matches(url)), DEFAULT_RULE)
