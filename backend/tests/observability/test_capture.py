"""Chụp lỗi thành issue: fingerprint ổn định theo (loại + frame app gần chỗ ném nhất + loc), traceback đã che ≤ 20KB,
mẫu có kiểu (R13) với context đã che."""

from app.core.errors import AppException
from app.core.redact import build_keys
from app.observability.capture import (
    APP_DIR,
    TRACEBACK_LIMIT,
    exc_type_name,
    fingerprint,
    first_app_frame,
    issue_event,
    redacted_traceback,
    title_of,
)
from app.observability.schemas import IssueSample


def _raiser(filename: str, func: str):
    """Hàm ném lỗi mà traceback ghi tên file `filename` — giả một frame ở chỗ bất kỳ (trong / ngoài app/)."""
    ns: dict = {}
    exec(compile(f"def {func}(exc):\n    raise exc\n", filename, "exec"), ns)
    return ns[func]


def _caller(filename: str, func: str, inner):
    ns: dict = {"inner": inner}
    exec(compile(f"def {func}(exc):\n    inner(exc)\n", filename, "exec"), ns)
    return ns[func]


def _caught(fn, exc: BaseException) -> BaseException:
    try:
        fn(exc)
    except BaseException as err:  # noqa: BLE001 — test cần chính exception đã có traceback
        return err
    raise AssertionError("không ném")


def test_first_app_frame_is_the_app_frame_closest_to_the_raise():
    inner = _raiser(str(APP_DIR / "wallet" / "ledger.py"), "post")
    outer = _caller(str(APP_DIR / "core" / "operations" / "runner.py"), "run_operation", inner)
    assert first_app_frame(_caught(outer, ValueError("x"))) == "wallet/ledger.py:post"


def test_no_app_frame_gives_empty():
    exc = _caught(_raiser("/usr/lib/python3.13/json/decoder.py", "decode"), ValueError("x"))
    assert first_app_frame(exc) == ""
    assert first_app_frame(ValueError("chưa ném")) == ""


def test_fingerprint_ignores_message_but_not_type_frame_or_loc():
    raiser = _raiser(str(APP_DIR / "wallet" / "ledger.py"), "post")
    a = _caught(raiser, ValueError("số 1"))
    b = _caught(raiser, ValueError("số 2 khác hẳn"))
    assert fingerprint(a, "exc0500") == fingerprint(b, "exc0500") and len(fingerprint(a, "exc0500")) == 40
    assert fingerprint(a, "exc0500") != fingerprint(a, "tq0500")
    assert fingerprint(a, "exc0500") != fingerprint(_caught(raiser, KeyError("k")), "exc0500")
    other = _raiser(str(APP_DIR / "wallet" / "slips.py"), "accept")
    assert fingerprint(a, "exc0500") != fingerprint(_caught(other, ValueError("số 1")), "exc0500")


def test_exc_type_name_qualifies_non_builtins():
    assert exc_type_name(ValueError()) == "ValueError"
    assert exc_type_name(AppException(1000)) == "app.core.errors.AppException"


def test_traceback_is_redacted_and_capped():
    raiser = _raiser(str(APP_DIR / "x.py"), "f")
    tb = redacted_traceback(_caught(raiser, RuntimeError("gọi với Bearer abcdefghijklmnopqrst")))
    assert "abcdefghijklmnopqrst" not in tb and tb.rstrip().endswith("[REDACTED]")
    huge = redacted_traceback(_caught(raiser, RuntimeError("ồ" * 30_000)))
    assert len(huge.encode()) <= TRACEBACK_LIMIT and huge.startswith("…(đã cắt phần đầu)…")


def test_title_is_first_line_redacted_and_short():
    assert title_of(ValueError("dòng 1\ndòng 2")) == "ValueError: dòng 1"
    assert title_of(KeyError()) == "KeyError"
    assert "abcdefghijklmnop" not in title_of(RuntimeError("token=abcdefghijklmnop"))
    assert len(title_of(ValueError("x" * 1000))) == 200


def test_issue_event_has_typed_redacted_sample():
    exc = _caught(_raiser(str(APP_DIR / "x.py"), "f"), ValueError("hỏng"))
    context = {"path": "/bizwithagents/api/x", "user_id": "u-1", "method": "GET", "extra": {"password": "p"}}
    ev = issue_event(exc, source="http", loc="exc0500", cid="c1", context=context, keys=build_keys(()))
    assert isinstance(ev.sample, IssueSample) and ev.fingerprint == fingerprint(exc, "exc0500")
    sample = ev.sample
    assert (sample.path, sample.user_id, sample.operation, sample.cid) == ("/bizwithagents/api/x", "u-1", None, "c1")
    assert ev.sample.context == {"method": "GET", "extra": {"password": "[REDACTED]"}}
    assert "ValueError: hỏng" in ev.sample.traceback and ev.title == "ValueError: hỏng" and ev.exc_type == "ValueError"
