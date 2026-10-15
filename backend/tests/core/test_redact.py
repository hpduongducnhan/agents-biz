import json

from app.core.redact import (
    DEFAULT_REDACT_KEYS,
    REDACTED,
    build_keys,
    is_text_content,
    redact_dsn,
    redact_headers,
    redact_mapping,
    redact_text,
    redact_url,
    render_body,
)

KEYS = build_keys(["pin"])


def test_build_keys_merges_defaults_and_extra():
    assert "password" in KEYS and "pin" in KEYS
    assert DEFAULT_REDACT_KEYS <= KEYS


def test_redact_text_patterns():
    out = redact_text("auth=Bearer abcdefghijkl123 key sk-ABCDEFGHIJKLMNOPQRSTUV password=hunter2 api_key=zz")
    for secret in ("abcdefghijkl123", "ABCDEFGHIJKLMNOPQRSTUV", "hunter2", "api_key=zz"):
        assert secret not in out
    assert REDACTED in out


def test_redact_mapping_nested_and_case_insensitive():
    data = {"user": "a", "Password": "x", "items": [{"token": "t", "v": 1}], "nested": {"PIN": "1"}}
    assert redact_mapping(data, KEYS) == {
        "user": "a",
        "Password": REDACTED,
        "items": [{"token": REDACTED, "v": 1}],
        "nested": {"PIN": REDACTED},
    }


def test_redact_headers():
    out = redact_headers([("Authorization", "Bearer x"), ("Cookie", "a=b"), ("Accept", "json")])
    assert out == {"authorization": REDACTED, "cookie": REDACTED, "accept": "json"}


def test_redact_url_query_values():
    out = redact_url("https://h/p?api_key=zzz&q=1&token=t", KEYS)
    assert "zzz" not in out and "=t" not in out and "q=1" in out
    assert redact_url("https://h/p", KEYS) == "https://h/p"


def test_redact_dsn_hides_password():
    assert redact_dsn("postgresql+psycopg://app:s3cr3t@127.0.0.1:5432/OtherApp") == (
        "postgresql+psycopg://app:***@127.0.0.1:5432/OtherApp"
    )
    assert redact_dsn("redis://127.0.0.1:6379/4") == "redis://127.0.0.1:6379/4"


def test_is_text_content():
    assert is_text_content("application/json; charset=utf-8")
    assert is_text_content("text/plain")
    assert is_text_content("application/problem+json")
    assert not is_text_content("text/event-stream")
    assert not is_text_content("multipart/form-data; boundary=x")
    assert not is_text_content("image/png")
    assert not is_text_content(None)


def test_render_body_json_is_redacted_structurally():
    raw = json.dumps({"name": "a", "password": "hunter2"}).encode()
    out = render_body(raw, "application/json", KEYS, 4096)
    assert json.loads(out) == {"name": "a", "password": REDACTED}


def test_render_body_form_is_redacted():
    out = render_body(b"user=a&password=hunter2", "application/x-www-form-urlencoded", KEYS, 4096)
    assert "hunter2" not in out and "user=a" in out


def test_render_body_truncates_and_still_redacts_json_keys():
    raw = json.dumps({"password": "hunter2", "pad": "x" * 100}).encode()
    out = render_body(raw, "application/json", KEYS, 40)
    assert "hunter2" not in out
    assert "[truncated" in out


def test_render_body_binary_and_total_size():
    assert render_body(b"\x89PNG", "image/png", KEYS, 10) == "<binary 4 bytes>"
    out = render_body(b"abc", "text/plain", KEYS, 2, total_size=10)
    assert out.startswith("ab") and "[truncated 8 bytes]" in out


def test_compound_sensitive_keys_are_redacted():
    out = redact_mapping(
        {
            "new_password": "n",
            "current_password": "c",
            "googleClientSecret": "g",
            "x-api-key": "k",
            "max_tokens": 5,
            "nested": {"db_password": "p", "title": "ok"},
        },
        DEFAULT_REDACT_KEYS,
    )
    assert out["new_password"] == out["current_password"] == out["googleClientSecret"] == "[REDACTED]"
    assert out["x-api-key"] == "[REDACTED]" and out["nested"]["db_password"] == "[REDACTED]"
    assert out["max_tokens"] == 5 and out["nested"]["title"] == "ok"


def test_compound_sensitive_keys_redacted_in_json_text():
    raw = b'{"current_password":"old-secret","new_password":"new-secret","max_tokens":"5"}'
    text = render_body(raw, "application/json", DEFAULT_REDACT_KEYS, 4096)
    assert "old-secret" not in text and "new-secret" not in text and '"max_tokens": "5"' in text
    assert "s3" not in redact_url("https://h/x?client_secret=s3&page=2", DEFAULT_REDACT_KEYS)


def test_llm_key_headers_and_query_key_are_redacted():
    out = redact_headers([("api-key", "x"), ("x-goog-api-key", "y"), ("accept", "z")])
    assert out == {"api-key": "[REDACTED]", "x-goog-api-key": "[REDACTED]", "accept": "z"}
    url = redact_url("https://h/p?key=abc&sort_key=1", frozenset())
    assert "abc" not in url and "sort_key=1" in url


def test_redact_text_hides_dsn_password():
    """URL kết nối có mật khẩu lọt vào message / lỗi (vd lỗi kết nối RabbitMQ) — che phần mật khẩu, giữ user / host."""
    out = redact_text(
        "không nối được amqp://bizwithagents:s3cretpw@rabbit:5672/bizwithagents và redis://:r3d1spw@h:6379/8"
    )
    assert "s3cretpw" not in out and "r3d1spw" not in out
    assert "amqp://bizwithagents:***@rabbit:5672/bizwithagents" in out
