"""Live webcam analysis endpoint."""

from fastapi import APIRouter, HTTPException, Request

from app.study import StudySessionManager

router = APIRouter(prefix="/api/webcam", tags=["webcam"])


def _study(request: Request) -> StudySessionManager:
    return request.app.state.study


async def _read_bounded_frame(request: Request) -> bytes:
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
    return bytes(frame)


@router.post("/frame")
async def webcam_frame(request: Request) -> dict:
    study = _study(request)
    if not study.status()["active"]:
        raise HTTPException(status_code=409, detail="Start a study block before sending webcam frames.")
    frame = await _read_bounded_frame(request)
    try:
        return study.process_frame(frame)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
