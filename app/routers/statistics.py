"""Study statistics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.database import StudyDatabase

router = APIRouter(prefix="/api", tags=["statistics"])


def _database(request: Request) -> StudyDatabase:
    return request.app.state.database


@router.get("/statistics")
def statistics(
    request: Request,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    timezone_offset_minutes: Annotated[int, Query(ge=-840, le=840)] = 0,
) -> dict:
    return _database(request).statistics(days, timezone_offset_minutes)
