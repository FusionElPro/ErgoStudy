"""Focus and break timer endpoints."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from app.database import StudyDatabase
from app.schemas import StartSessionInput
from app.posture import PostureAnalysisManager
from app.study import StudySessionManager

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _database(request: Request) -> StudyDatabase:
    return request.app.state.database


def _study(request: Request) -> StudySessionManager:
    return request.app.state.study


def _posture(request: Request) -> PostureAnalysisManager:
    return request.app.state.posture


@router.get("/active")
def active_session(request: Request) -> dict:
    return _study(request).status()


@router.post("/start")
def start_session(payload: StartSessionInput, request: Request) -> dict:
    if payload.subject_id is not None and not _database(request).subject_exists(payload.subject_id):
        raise HTTPException(status_code=404, detail="The selected subject does not exist.")
    if _posture(request).status()["active"]:
        raise HTTPException(
            status_code=409,
            detail="Stop the standalone posture analyzer before starting a study block.",
        )
    try:
        return _study(request).start(payload.subject_id, payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/stop")
def stop_session(request: Request) -> dict:
    try:
        return _study(request).stop()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("")
def session_history(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict]:
    return _database(request).session_history(limit)
