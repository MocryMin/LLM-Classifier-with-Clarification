"""
server/main.py — FastAPI backend for the 智能管家 chat playground.
Wraps entrance.py with SSE streaming chat endpoint.
"""
import os
import sys
import json
import time
import asyncio
import traceback

# Ensure entrance and its dependencies are importable
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'src'))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from conversation_manager import (
    list_conversations, create_conversation, get_conversation,
    save_conversation, delete_conversation,
)

app = FastAPI(title="智能管家 Chat Playground", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    messages: list[dict] = Field(..., description="OpenAI format messages")
    l0_threshold: float = Field(0.7, ge=0.0, le=1.0, description="L0 intercept threshold")
    debug: bool = Field(False, description="Enable debug logging")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


async def _run_entrance(messages: list[dict], l0_threshold: float, debug: bool):
    """Run entrance in a thread to avoid blocking the event loop."""
    from entrance import entrance
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, lambda: entrance(messages, l0_threshold, debug)),
        timeout=120,
    )


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    SSE streaming chat endpoint.
    Events:
      - progress: {stage}  -- L0/L1 progress
      - result:   complete entrance return value
      - error:    {message}
    """
    async def event_stream():
        try:
            # Progress: L0 starting
            yield f"event: progress\ndata: {json.dumps({'stage': 'l0_start'}, ensure_ascii=False)}\n\n"

            start_time = time.time()
            result = await _run_entrance(request.messages, request.l0_threshold, request.debug)
            elapsed = time.time() - start_time

            # Progress: complete
            stage = "escalation" if result["case"] == 0 else "l1"
            yield f"event: progress\ndata: {json.dumps({'stage': stage, 'elapsed': round(elapsed, 1)}, ensure_ascii=False)}\n\n"

            # Final result
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


@app.put("/api/conversations/{conv_id}")
async def api_save_conversation(conv_id: str, body: SaveConversationBody):
    ok = save_conversation(conv_id, body.messages, body.meta)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
