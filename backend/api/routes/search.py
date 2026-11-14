"""Search and scanning endpoints with SSE progress streaming."""

from __future__ import annotations
import asyncio
import json
from typing import Any, Dict
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.api.deps import get_evaluator, get_scanner
from backend.api.models import SearchRequest, SearchStatusResponse
from backend.api.security import verify_csrf_token
from backend.core.evaluator import EvaluatorService
from backend.core.scanner import ScannerService

router = APIRouter(tags=["Search"])


@router.post("/search")
def trigger_search(
    req: SearchRequest,
    scanner: ScannerService = Depends(get_scanner),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Trigger an asynchronous portal search job with region routing."""
    started = scanner.start(
        priorities=req.priority,
        jobage=req.jobage,
        focus=req.focus,
        portals=req.portals,
        region=req.region,
        all_priorities=req.all,
        query=req.query,
    )
    return {"ok": started, "started": started}


@router.get("/status", response_model=SearchStatusResponse)
def search_status(
    scanner: ScannerService = Depends(get_scanner),
    evaluator: EvaluatorService = Depends(get_evaluator),
) -> Dict[str, Any]:
    """Check status and output summary of the running search job."""
    return {**scanner.status(), "batch": evaluator.batch_status()}


@router.get("/stream")
async def search_stream(
    scanner: ScannerService = Depends(get_scanner),
) -> StreamingResponse:
    """Server-Sent Events endpoint streaming real-time portal search progress."""
    async def event_generator():
        q: asyncio.Queue = asyncio.Queue()
        scanner.subscribe(q)
        try:
            init_stat = scanner.status()
            yield f"event: status\ndata: {json.dumps(init_stat, ensure_ascii=False)}\n\n"

            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=1.5)
                    evt_type = evt.get("type", "progress")
                    yield f"event: {evt_type}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                    if evt_type == "done":
                        break
                except asyncio.TimeoutError:
                    if not scanner.running:
                        final_stat = scanner.status()
                        yield f"event: done\ndata: {json.dumps(final_stat, ensure_ascii=False)}\n\n"
                        break
                    yield ": keepalive\n\n"
        finally:
            scanner.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/clear-pending")
def clear_pending(
    scanner: ScannerService = Depends(get_scanner),
    _csrf: str = Depends(verify_csrf_token),
) -> Dict[str, Any]:
    """Clear the session's pending search results."""
    cleared = scanner.clear_pending()
    return {"cleared": cleared}


@router.get("/health")
def portal_health(
    scanner: ScannerService = Depends(get_scanner),
) -> Dict[str, Any]:
    """Return installed portal tools and availability status."""
    return {"portals": scanner.installed_portals()}
