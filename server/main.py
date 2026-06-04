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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
