"""OpenAPI documentation of the error envelope (shown in Swagger for each route)."""

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorDetail


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """`responses=` helper so Swagger shows the envelope for the given status codes."""
    return {code: {"model": ErrorResponse} for code in codes}
