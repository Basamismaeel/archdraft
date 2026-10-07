"""HTTP API for the frontend.  Run: uvicorn archdraft.api:app --reload --port 8000"""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import google.adk
import pydantic
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field

from archdraft import config, service, storage
from archdraft.config import ConfigError
from archdraft.service import GenerateResult, GenerationError, Judgement, Mode

logger = logging.getLogger("archdraft")

app = FastAPI(title="ArchDraft API", version="0.1.0")


class GenerateRequest(BaseModel):
    requirements_text: str = Field(min_length=1, max_length=60_000)
    mode: Mode = "pipeline"


class JudgeRequest(BaseModel):
    project_ids: list[str] = Field(min_length=1, max_length=4)


class Sample(BaseModel):
    id: str
    title: str
    text: str


class Health(BaseModel):
    ok: bool
    model: str | None
    credentials: bool
    adk_version: str


@app.get("/api/health")
def health() -> Health:
    try:
        config.require_credentials()
        has_credentials = True
    except ConfigError:
        has_credentials = False
    return Health(
        ok=True,
        model=os.environ.get("GEMINI_MODEL") or None,
        credentials=has_credentials,
        adk_version=google.adk.__version__,
    )


@app.post("/api/generate")
async def generate(request: GenerateRequest) -> GenerateResult:
    try:
        return await service.generate(request.requirements_text, request.mode)
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except genai_errors.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini API error: {exc}") from exc
    except pydantic.ValidationError as exc:
        detail = f"The model's answer did not match the schema: {exc.error_count()} problem(s)."
        raise HTTPException(status_code=502, detail=detail) from exc


def _error_detail(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, ConfigError):
        return 503, str(exc)
    if isinstance(exc, GenerationError):
        return 502, str(exc)
    if isinstance(exc, genai_errors.APIError):
        return 502, f"Gemini API error: {exc}"
    if isinstance(exc, pydantic.ValidationError):
        return 502, f"The model's answer did not match the schema: {exc.error_count()} problem(s)."
    logger.exception("Unexpected failure during generation")
    return 500, f"{type(exc).__name__}: {exc}"


@app.post("/api/generate/stream")
async def generate_stream(request: GenerateRequest) -> StreamingResponse:
    """Same as /api/generate, but streams one JSON line per finished pipeline node.

    Lines: {"type": "step", "node", "ms"} ... then {"type": "result", "result"} or
    {"type": "error", "status", "detail"}."""
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def progress(item: dict[str, Any]) -> None:
        await queue.put(item)

    async def worker() -> None:
        try:
            result = await service.generate(
                request.requirements_text, request.mode, progress=progress
            )
            await queue.put({"type": "result", "result": result.model_dump(mode="json")})
        except Exception as exc:  # noqa: BLE001 - reported to the client, never swallowed
            status, detail = _error_detail(exc)
            await queue.put({"type": "error", "status": status, "detail": detail})
        finally:
            await queue.put(None)

    async def lines() -> AsyncIterator[str]:
        task = asyncio.create_task(worker())
        try:
            while (item := await queue.get()) is not None:
                yield json.dumps(item) + "\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.post("/api/judge")
async def judge(request: JudgeRequest) -> dict[str, Judgement]:
    """Grade saved runs of the same requirements with the independent judge."""
    try:
        return await service.judge_saved(request.project_ids)
    except (ConfigError, GenerationError, genai_errors.APIError, pydantic.ValidationError) as exc:
        status, detail = _error_detail(exc)
        raise HTTPException(status_code=status, detail=detail) from exc


@app.get("/api/samples")
def samples() -> list[Sample]:
    files = sorted(config.SAMPLES_DIR.glob("*.txt"), key=lambda p: p.stat().st_size)
    result: list[Sample] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        first = text.splitlines()[0] if text else path.stem
        result.append(Sample(id=path.stem, title=first.lstrip("# ").strip(), text=text))
    return result


@app.get("/api/projects")
def projects() -> list[storage.ProjectSummary]:
    return storage.list_projects()


@app.get("/api/projects/{project_id}")
def project(project_id: str) -> dict[str, Any]:
    data = storage.load(project_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No project '{project_id}'.")
    return data
