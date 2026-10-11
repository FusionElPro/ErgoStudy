"""Subject creation and organization endpoints."""

import sqlite3

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.database import StudyDatabase
from app.schemas import SubjectInput

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


def _database(request: Request) -> StudyDatabase:
    return request.app.state.database


@router.get("")
def list_subjects(request: Request) -> list[dict]:
    return _database(request).list_subjects()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_subject(payload: SubjectInput, request: Request) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Subject name cannot be blank.")
    try:
        return _database(request).create_subject(name, payload.color)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="A subject with this name already exists."
        ) from exc


@router.delete("/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subject(subject_id: int, request: Request) -> Response:
    if not _database(request).delete_subject(subject_id):
        raise HTTPException(status_code=404, detail="Subject not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
