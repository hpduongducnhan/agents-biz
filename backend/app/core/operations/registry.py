"""Registry toàn cục của @operation — đăng ký lúc import `app.<miền>.ops` (load_domains)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.operations.spec import OperationSpec

_SPECS: dict[str, OperationSpec] = {}


def register(spec: OperationSpec) -> None:
    if spec.name in _SPECS:
        raise ValueError(f"operation '{spec.name}' bị trùng")
    _SPECS[spec.name] = spec


def get_spec(name: str) -> OperationSpec | None:
    return _SPECS.get(name)


def all_specs() -> list[OperationSpec]:
    return [_SPECS[name] for name in sorted(_SPECS)]


def specs_for(namespace: str) -> list[OperationSpec]:
    return [s for s in all_specs() if s.namespace == namespace]


def namespaces(*, app_only: bool = False) -> list[str]:
    """Namespace đã đăng ký; `app_only` = chỉ operation khai trong `app.*` (bỏ miền giả của test)."""
    return sorted({s.namespace for s in _SPECS.values() if not app_only or s.source.startswith("app.")})
