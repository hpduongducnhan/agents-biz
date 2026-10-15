"""`UrlAction`: link ngoài chỉ https, mở tab mới; loại thông báo phải đăng ký đúng kiểu params."""

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.notifications.schemas import UrlAction, register_kind, registered_kinds, validate_payload


class ExportDoneParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    link: str = ""


register_kind("test.export_done", ExportDoneParams)
LINK = "https://drive.google.com/file/d/abc/view"
PARAMS = {"name": "a.csv", "link": LINK}
KIND = "test.export_done"


def test_url_action_accepts_https_with_optional_label():
    _, action = validate_payload(KIND, PARAMS, {"kind": "url", "url": LINK, "label": "Mở"})
    assert action == {"kind": "url", "url": LINK, "label": "Mở"}
    _, no_label = validate_payload(KIND, PARAMS, UrlAction(url=LINK))
    assert no_label == {"kind": "url", "url": LINK, "label": ""}


@pytest.mark.parametrize(
    "url",
    [
        "http://drive.google.com/file/d/abc/view",
        "javascript:alert(1)",
        "//evil.io/x",
        "/relative",
        "ftp://x.io/f",
        "HTTPS://upper.case",
        "",
        "https:/" + "x" * 1000,
    ],
)
def test_url_action_rejects_non_https_or_too_long(url):
    with pytest.raises(ValueError):
        validate_payload(KIND, PARAMS, {"kind": "url", "url": url})
    with pytest.raises(ValidationError):
        UrlAction(url=url)


def test_url_action_forbids_extra_fields_and_long_label():
    base = {"kind": "url", "url": LINK}
    for bad in ({**base, "to": "/x"}, {**base, "label": "x" * 41}, {"kind": "url"}):
        with pytest.raises(ValueError):
            validate_payload(KIND, PARAMS, bad)


def test_registered_kinds_validate_strict_params_and_reject_clashes():
    assert registered_kinds()[KIND] is ExportDoneParams
    assert validate_payload(KIND, {"name": "a.csv"}, None)[0]["link"] == ""
    for bad in ({}, {"name": "a", "x": 1}):
        with pytest.raises(ValueError):
            validate_payload(KIND, bad, None)
    with pytest.raises(ValueError):
        validate_payload("test.unknown", {}, None)
    with pytest.raises(ValueError):
        register_kind(KIND, BaseModel)
