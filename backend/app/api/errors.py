"""Consistent public errors that do not expose input secrets or storage internals."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.analytics.heroes import HeroNotFound, RepositoryUnavailable
from app.api.models import ErrorBody, ErrorDetail, ErrorResponse
from app.core.logging import get_logger


def error_response(
    status: int, code: str, message: str, details: list[ErrorDetail] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def register_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(RequestValidationError)
    async def invalid_parameters(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            ErrorDetail(location=list(error["loc"]), message=error["msg"], type=error["type"])
            for error in exc.errors()
        ]
        return error_response(422, "invalid_parameters", "Invalid request parameters.", details)

    @application.exception_handler(HeroNotFound)
    async def hero_not_found(_request: Request, _exc: HeroNotFound) -> JSONResponse:
        return error_response(
            404, "hero_not_found", "Hero not observed in the current publication."
        )

    @application.exception_handler(RepositoryUnavailable)
    async def unavailable(_request: Request, _exc: RepositoryUnavailable) -> JSONResponse:
        return error_response(503, "data_unavailable", "Published data is temporarily unavailable.")

    @application.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        response = error_response(exc.status_code, "http_error", "Request could not be completed.")
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @application.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        get_logger(__name__).error(
            "api_request_failed",
            extra={"event": "api_request_failed", "error_type": type(exc).__name__},
        )
        return error_response(500, "internal_error", "An internal error occurred.")
