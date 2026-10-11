"""Standalone posture-analysis endpoints used by the website."""

from fastapi import APIRouter, HTTPException, Request

from app.posture import PostureAnalysisManager
from app.study import StudySessionManager

router = APIRouter(prefix="/api/posture", tags=["posture"])


def _posture(request: Request) -> PostureAnalysisManager:
    return request.app.state.posture


def _study(request: Request) -> StudySessionManager:
    return request.app.state.study


@router.get("/status")
def posture_status(request: Request) -> dict:
    return _posture(request).status()


@router.post("/start")
def start_posture_analysis(request: Request) -> dict:
    if _study(request).status()["active"]:
        raise HTTPException(
            status_code=409,
            detail="Finish the current study block before starting a separate posture analysis.",
        )
    try:
        return _posture(request).start()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/stop")
def stop_posture_analysis(request: Request) -> dict:
    try:
        return _posture(request).stop()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/frame")
async def posture_frame(request: Request) -> dict:
    if not _posture(request).status()["active"]:
        raise HTTPException(status_code=409, detail="Start the posture analyzer before sending webcam frames.")
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "image/jpeg":
        raise HTTPException(status_code=415, detail="Webcam frame must be JPEG.")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            too_large = int(content_length) > 2_000_000
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from exc
        if too_large:
            raise HTTPException(status_code=413, detail="Webcam frame exceeds 2 MB.")
    frame = bytearray()
    async for chunk in request.stream():
        frame.extend(chunk)
        if len(frame) > 2_000_000:
            raise HTTPException(status_code=413, detail="Webcam frame exceeds 2 MB.")
    if not frame:
        raise HTTPException(status_code=400, detail="Webcam frame is empty.")
    try:
        return _posture(request).process_frame(bytes(frame))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
