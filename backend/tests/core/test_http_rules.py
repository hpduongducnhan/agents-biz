import pytest

from app.core.http_rules import HttpLogRule, HttpLogRules, glob_to_regex


def test_glob_single_and_double_star():
    assert glob_to_regex("/api/*/x").match("/api/wallet/x")
    assert not glob_to_regex("/api/*/x").match("/api/a/b/x")
    assert glob_to_regex("/api/**").match("/api/a/b/c")
    assert glob_to_regex("https://h.vn/**").match("https://h.vn/v1/x")


def test_first_match_wins_and_default_is_metadata_only():
    rules = HttpLogRules(
        inbound=[HttpLogRule(match="/api/wallet/**", req_body=True), HttpLogRule(match="/api/**", resp_body=True)],
        outbound=[],
    )
    assert rules.inbound_for("/api/wallet/tx").req_body is True
    assert rules.inbound_for("/api/wallet/tx").resp_body is False
    assert rules.inbound_for("/api/other").resp_body is True
    assert rules.inbound_for("/health") == HttpLogRule(match="**")
    assert rules.outbound_for("https://x.test/a") == HttpLogRule(match="**")


def test_from_file_none_is_empty():
    rules = HttpLogRules.from_file(None)
    assert rules.inbound == [] and rules.outbound == [] and rules.max_body == 4096


def test_from_file_parses_yaml(tmp_path):
    f = tmp_path / "rules.yaml"
    f.write_text(
        "http_log:\n"
        "  max_body: 100\n"
        "  inbound:\n"
        "    - { match: '/api/wallet/**', req_body: true }\n"
        "  outbound:\n"
        "    - { match: 'https://api.partner.vn/**', resp_body: true, propagate_cid: true }\n",
        encoding="utf-8",
    )
    rules = HttpLogRules.from_file(f)
    assert rules.max_body == 100
    assert rules.inbound_for("/api/wallet/a").req_body
    out = rules.outbound_for("https://api.partner.vn/v1/x")
    assert out.resp_body and out.propagate_cid


@pytest.mark.parametrize(
    "body",
    [
        "other: 1\n",
        "http_log:\n  inbound:\n    - { match: '/a', typo: true }\n",
        "http_log:\n  inbound:\n    - { match: '/a', propagate_cid: true }\n",
        "http_log:\n  inbound:\n    - { req_body: true }\n",
    ],
)
def test_from_file_rejects_bad_config(tmp_path, body):
    f = tmp_path / "rules.yaml"
    f.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        HttpLogRules.from_file(f)


def test_from_file_missing_file_fails_fast(tmp_path):
    with pytest.raises(FileNotFoundError):
        HttpLogRules.from_file(tmp_path / "nope.yaml")
