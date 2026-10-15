"""R14: phân trang dùng chung — input limit 1–100 (mặc định 20), offset ≥ 0, query string được ép kiểu; output
`Page[T]` gồm items / total / limit / offset."""

import pytest
from pydantic import BaseModel, ValidationError

from app.core.operations.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, PageIn


class FindIn(PageIn):
    q: str = ""


class Item(BaseModel):
    id: int


def test_defaults_and_bounds():
    page = PageIn()
    assert (page.limit, page.offset, DEFAULT_LIMIT, MAX_LIMIT) == (20, 0, 20, 100)
    assert PageIn(limit=100).limit == 100
    for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        with pytest.raises(ValidationError):
            PageIn.model_validate(bad)


def test_domain_inputs_extend_it_and_coerce_query_strings():
    found = FindIn.model_validate({"q": "a", "limit": "5", "offset": "10"})
    assert (found.q, found.limit, found.offset) == ("a", 5, 10)


def test_page_output_shape():
    page = Page[Item](items=[Item(id=1)], total=5, limit=1, offset=0)
    assert page.model_dump() == {"items": [{"id": 1}], "total": 5, "limit": 1, "offset": 0}
    assert set(Page[Item].model_json_schema()["required"]) == {"items", "total", "limit", "offset"}
