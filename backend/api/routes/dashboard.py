"""Dashboard Analytics endpoints."""

from __future__ import annotations
from typing import Any, Dict
from fastapi import APIRouter, Depends, Query

from backend.api.deps import get_tracker
from backend.core.tracker import TrackerService

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    period_months: int = Query(6, ge=1, le=24, description="Quantidade de meses no histórico temporal"),
    tracker: TrackerService = Depends(get_tracker),
) -> Dict[str, Any]:
    """Retrieve consolidated analytics, KPI cards, timeline, and funnel metrics."""
    return tracker.get_dashboard_stats(period_months=period_months)
