from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel, Generic[T]):
    ok: bool = True
    data: Optional[T] = None
    error: Optional[ErrorBody] = None


class PageData(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20


def normalize_page(page: int = 1, page_size: int = 20, *, max_size: int = 200) -> tuple[int, int, int]:
    """返回 (page, page_size, offset)。"""
    page = max(1, int(page or 1))
    page_size = min(max(1, int(page_size or 20)), max_size)
    return page, page_size, (page - 1) * page_size


def page_payload(items: list[Any], total: int, page: int, page_size: int) -> dict:
    return {
        "items": items,
        "total": int(total),
        "page": page,
        "page_size": page_size,
    }


def paginate_sequence(items: list[Any], page: int = 1, page_size: int = 20, *, max_size: int = 200) -> dict:
    """对已算出的列表做切片分页（适合聚合结果）。"""
    page, page_size, offset = normalize_page(page, page_size, max_size=max_size)
    total = len(items)
    return page_payload(items[offset : offset + page_size], total, page, page_size)


def ok(data: Any = None) -> dict:
    return {"ok": True, "data": data, "error": None}


def fail(code: str, message: str) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}
