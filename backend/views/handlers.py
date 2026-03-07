from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from backend.views.errors import AppError, SystemError, ValidationError
from backend.views.response import fail
from backend.views.context import ensure_trace_id


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        ensure_trace_id()
        return JSONResponse(status_code=exc.status_code, content=fail(exc.message, exc.code))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        ensure_trace_id()
        validation_error = ValidationError(str(exc))
        return JSONResponse(status_code=validation_error.status_code, content=fail(validation_error.message, validation_error.code))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        ensure_trace_id()
        system_error = SystemError(str(exc))
        return JSONResponse(status_code=system_error.status_code, content=fail(system_error.message, system_error.code))
