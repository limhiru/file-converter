"""Loopback-only web API and buildless UI."""

from pathlib import Path
import json
import threading
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.converters import MAX_FILE_BYTES, ConversionError, capabilities, convert

app = FastAPI(title="파일 변환", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
STATIC = Path(__file__).parent / "static"
slots = threading.BoundedSemaphore(2)


@app.middleware("http")
async def local_requests(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return JSONResponse({"detail": "올바르지 않은 요청 출처입니다."}, status_code=403)
        if parsed.scheme not in ("http", "https") or parsed.netloc != request.url.netloc:
            return JSONResponse({"detail": "이 앱의 화면에서 요청해 주세요."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
        "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    return response


@app.get("/api/formats")
def formats():
    return capabilities()


@app.post("/api/convert")
async def convert_file(request: Request, filename: str = Query(min_length=1, max_length=240),
                       target: str = Query(min_length=1, max_length=8), quality: int = Query(default=90, ge=1, le=100)):
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "다른 파일을 처리 중입니다. 잠시 후 다시 시도하세요.", headers={"Retry-After": "3"})
    try:
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_FILE_BYTES:
                raise HTTPException(413, "파일 크기는 최대 100 MB까지 지원합니다.")
            data.extend(chunk)
        try:
            result = await run_in_threadpool(convert, bytes(data), filename, target, quality)
        except ConversionError as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(content=result.data, media_type=result.mime, headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(result.filename, safe=""),
            "X-Conversion-Notes": quote(json.dumps(result.notes, ensure_ascii=False)),
            "X-Converted-Count": str(result.converted_count),
            "X-Preserved-Count": str(result.skipped_count),
        })
    finally:
        slots.release()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
