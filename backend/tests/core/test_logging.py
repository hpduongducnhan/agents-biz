"""Logging: logger `bw`, miền suy từ tên module, JSON có cid / proc / loc, che bí mật trong message."""

import json
import logging
import sys

from app.core.cid import set_cid
from app.core.logging import LOGGER_NAME, TextFormatter, configure_logging, get_logger, install_redaction, module_of
from app.core.settings import Settings


def test_module_of_maps_app_domains():
    assert module_of("app.notifications.service") == "notifications"
    assert module_of("app.system.health") == "system"
    assert module_of("app.core.connections.redis") == "core"
    assert module_of("app.main") == "core"
    assert module_of("uvicorn.error") == "core"


def test_json_line_carries_cid_module_loc(bw_log):
    set_cid("abc123")
    get_logger("app.system.heartbeat").info("nhịp tim %s", "work", extra={"loc": "sys0001", "role": "work"})
    line = bw_log()[-1]
    assert line["logger"] == LOGGER_NAME == "bw"
    assert (line["module"], line["loc"], line["cid"], line["role"]) == ("system", "sys0001", "abc123", "work")
    assert line["msg"] == "nhịp tim work"


def test_configure_logging_redacts_secrets_and_sets_proc(capsys):
    configure_logging("api", Settings(_env_file=None, LOG_JSON=True, LOG_LEVEL="INFO"))
    get_logger("app.main").info("gọi với Bearer abcdefghijklmnop")
    out = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(out)
    assert data["proc"] == "api" and "abcdefghijklmnop" not in data["msg"] and "[REDACTED]" in data["msg"]
    logging.getLogger().handlers.clear()


def test_redaction_covers_non_str_args(bw_log):
    """Lỗi hay được log dạng `log.warning("…: %s", exc)` — exc không phải str nhưng chuỗi của nó có thể chứa bí mật."""
    install_redaction()
    get_logger("app.core.x").warning("lỗi: %s", RuntimeError("password=hunter2 Bearer abcdefghijklmnop"))
    msg = bw_log()[-1]["msg"]
    assert "hunter2" not in msg and "abcdefghijklmnop" not in msg and "[REDACTED]" in msg


def test_redaction_covers_traceback_in_both_formatters(bw_log):
    install_redaction()
    log = get_logger("app.core.x")
    try:
        raise ValueError("token=zzzzzzzzzz amqp://bizwithagents:s3cretpw@rabbit:5672/bizwithagents")
    except ValueError:
        log.exception("hỏng")
        record = logging.LogRecord("bw", logging.ERROR, __file__, 1, "hỏng", (), sys.exc_info())
    exc = bw_log()[-1]["exc"]
    text = TextFormatter().format(record)
    for out in (exc, text):
        assert "zzzzzzzzzz" not in out and "s3cretpw" not in out and "ValueError" in out
