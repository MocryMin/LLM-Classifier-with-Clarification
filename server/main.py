"""
server/main.py — FastAPI backend for the V3 chat playground.
Wraps v3.entrance with SSE streaming chat endpoint.
"""
import os
import sys
import json
import time
import asyncio
import traceback
from pathlib import Path

# 项目根目录加入 sys.path, 让 v3 包可被 import
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from conversation_manager import (
    list_conversations, create_conversation, get_conversation,
    save_conversation, delete_conversation,
)

from workspace_manager import (
    get_workspace_path, set_workspace_path,
    import_to_staging, list_staging, get_staging_file,
    delete_staging_file, list_persisted, persist_file,
)
from parser_registry import get_parser_for_content, list_parsers

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app):
    yield
    from workspace_manager import cleanup_staging
    cleanup_staging()


app = FastAPI(title="智能管家 V3 Chat Playground", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health ────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "v3"}


# ─── V3 Chat (SSE streaming) ───────────────────────────────
class ChatRequest(BaseModel):
    messages: list[dict] = Field(..., description="OpenAI format messages")
    debug: bool = Field(False, description="Enable debug logging")


async def _run_v3_entrance(messages: list[dict], debug: bool):
    """Run V3 entrance in a thread to avoid blocking the event loop."""
    from v3.entrance import entrance
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: entrance(messages, debug)),
        timeout=120,
    )


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    V3 SSE streaming chat endpoint.
    Single-stage L1 intent routing.

    Events:
      - progress: {stage}
      - result:   complete entrance return value
      - error:    {message}
    """
    async def event_stream():
        try:
            yield f"event: progress\ndata: {json.dumps({'stage': 'l1_start'}, ensure_ascii=False)}\n\n"

            start_time = time.time()
            result = await _run_v3_entrance(request.messages, request.debug)
            elapsed = time.time() - start_time

            yield f"event: progress\ndata: {json.dumps({'stage': 'l1', 'elapsed': round(elapsed, 1)}, ensure_ascii=False)}\n\n"

            yield f"event: result\ndata: {json.dumps(result, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e), 'traceback': traceback.format_exc()}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Conversation CRUD ─────────────────────────────────────────
@app.get("/api/conversations")
async def api_list_conversations():
    return list_conversations()


@app.post("/api/conversations")
async def api_create_conversation():
    return create_conversation()


@app.get("/api/conversations/{conv_id}")
async def api_get_conversation(conv_id: str):
    conv = get_conversation(conv_id)
    if conv is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Not found"}, status_code=404)
    return conv


class SaveConversationBody(BaseModel):
    messages: list[dict]
    meta: dict | None = None
    results: dict | None = None


@app.put("/api/conversations/{conv_id}")
async def api_save_conversation(conv_id: str, body: SaveConversationBody):
    ok = save_conversation(conv_id, body.messages, body.meta, body.results)
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"status": "ok"}


@app.delete("/api/conversations/{conv_id}")
async def api_delete_conversation(conv_id: str):
    ok = delete_conversation(conv_id)
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"status": "ok"}


# ─── Workspace config ──────────────────────────────────────────
@app.get("/api/workspace/config")
async def api_get_workspace_config():
    return {"path": str(get_workspace_path())}


class WorkspaceConfigBody(BaseModel):
    path: str


@app.put("/api/workspace/config")
async def api_set_workspace_config(body: WorkspaceConfigBody):
    set_workspace_path(body.path)
    return {"path": str(get_workspace_path())}


# ─── Browse workspace ───────────────────────────────────────────
@app.get("/api/workspace/browse")
async def api_browse_workspace(subdir: str = ""):
    """List parseable files in the workspace directory."""
    from workspace_manager import browse_workspace
    try:
        files = browse_workspace(subdir)
        return {"files": files, "path": str(get_workspace_path())}
    except ValueError as e:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": str(e)}, status_code=400)


# ─── Staging ────────────────────────────────────────────────────
@app.post("/api/workspace/import")
async def api_import_to_staging(file: UploadFile = File(...)):
    content = await file.read()
    result = import_to_staging(file.filename or 'unknown', file.filename or 'unknown', content)
    return result


@app.get("/api/workspace/staging")
async def api_list_staging():
    return list_staging()


@app.delete("/api/workspace/staging/{staging_id}")
async def api_delete_staging(staging_id: str):
    ok = delete_staging_file(staging_id)
    if not ok:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"status": "ok"}


# ─── Persisted ──────────────────────────────────────────────────
@app.get("/api/workspace/persisted")
async def api_list_persisted():
    return list_persisted()


class PersistBody(BaseModel):
    staging_id: str


@app.post("/api/workspace/persist")
async def api_persist_file(body: PersistBody):
    return persist_file(body.staging_id)


# ─── Parse ─────────────────────────────────────────────────────
class ParseBody(BaseModel):
    staging_id: str


@app.post("/api/workspace/parse")
async def api_parse_file(body: ParseBody):
    staging_path = get_staging_file(body.staging_id)
    if staging_path is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Staging file not found"}, status_code=404)

    raw = staging_path.read_text(encoding='utf-8')
    ext = staging_path.suffix.lower()
    parser = get_parser_for_content(raw, ext)

    if parser is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": f"No parser found for {ext} files"}, status_code=400)

    messages = parser.parse(raw)
    return {
        "format": parser.name,
        "parser_used": parser.display_name,
        "messages": messages,
    }


# ─── Parse by path ────────────────────────────────────────────
class ParsePathBody(BaseModel):
    path: str


@app.post("/api/workspace/parse-path")
async def api_parse_by_path(body: ParsePathBody):
    """Parse a file directly from a workspace path."""
    file_path = Path(body.path)
    if not file_path.exists():
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "File not found"}, status_code=404)

    raw = file_path.read_text(encoding='utf-8')
    ext = file_path.suffix.lower()
    parser = get_parser_for_content(raw, ext)

    if parser is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": f"No parser found for {ext} files"}, status_code=400)

    messages = parser.parse(raw)
    return {
        "format": parser.name,
        "parser_used": parser.display_name,
        "messages": messages,
    }


# ─── Parsers list ──────────────────────────────────────────────
@app.get("/api/parsers")
async def api_list_parsers():
    return list_parsers()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
