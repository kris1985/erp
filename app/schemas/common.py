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


def ok(data: Any = None) -> dict:
    return {"ok": True, "data": data, "error": None}


def fail(code: str, message: str) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}
